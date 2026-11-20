"""Maintain one bot-owned GitHub issue for an unresolved catalogue incident."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
try:
    from scripts.catalogue_health import iso, timestamp, workflow_url, write_json
except ModuleNotFoundError:
    from catalogue_health import iso, timestamp, workflow_url, write_json

TITLE = 'OTTScout release updates need attention'
MARKER = '<!-- ottscout-catalogue-health:v1 -->'
BOT = 'github-actions[bot]'
STATUS_URL = 'https://ottscout.techiwithhelmet.com/data-status/'
UPDATE_INTERVAL = 12 * 3600
REPO = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}')
CAUSE = re.compile(r'[a-z0-9][a-z0-9_.:-]{0,119}')
LEVELS = {'normal': 0, 'warning': 1, 'critical': 2}


class NotificationError(ValueError):
    pass


def fingerprint(causes):
    signals = sorted((c['code'], c['severity']) for c in causes)
    return hashlib.sha256(json.dumps(signals, separators=(',', ':')).encode()).hexdigest()


def validate_health(report, now):
    if not isinstance(report, dict) or report.get('schemaVersion') != 1 or report.get('status') not in LEVELS:
        raise NotificationError('The health report is invalid; no issue was changed.')
    evaluated = timestamp(report.get('evaluatedAt'))
    causes = report.get('causes')
    if type(report.get('evaluatedAt')) is not int or evaluated is None or evaluated > now or not isinstance(causes, list) or len(causes) > 100:
        raise NotificationError('The health report is invalid; no issue was changed.')
    seen = set()
    for cause in causes:
        if (not isinstance(cause, dict) or not isinstance(cause.get('code'), str) or not CAUSE.fullmatch(cause['code'])
                or cause.get('severity') not in ('warning', 'critical') or cause['code'] in seen):
            raise NotificationError('The health signals are invalid; no issue was changed.')
        seen.add(cause['code'])
    actual = max((c['severity'] for c in causes), key=lambda s: LEVELS[s], default='normal')
    if actual != report['status']:
        raise NotificationError('The health status is inconsistent; no issue was changed.')
    # A saved green file is not proof of recovery when the monitoring job stopped.
    if now - evaluated > 12 * 3600:
        return {**report, 'status': 'critical', 'causes': [{'code': 'health_report_stale', 'severity': 'critical'}]}
    if actual == 'normal':
        discovery = report.get('officialDiscovery')
        publication = report.get('publication')
        new_feed = report.get('newFeed')
        heartbeat = report.get('heartbeat')
        sources = discovery.get('sources') if isinstance(discovery, dict) else None
        if (not isinstance(sources, list) or not sources or discovery.get('missingRequiredSources') != []
                or not any(isinstance(s, dict) and s.get('required') is True for s in sources)
                or any(not isinstance(s, dict) or (s.get('required') is True and
                       (s.get('status') != 'ok' or timestamp(s.get('lastSuccessAt')) is None)) for s in sources)
                or not isinstance(publication, dict) or publication.get('catalogueAvailable') is not True or publication.get('missingExpected') != []
                or not isinstance(new_feed, dict) or timestamp(new_feed.get('completedThrough')) is None
                or not isinstance(heartbeat, dict) or timestamp(heartbeat.get('lastRunAt')) is None):
            raise NotificationError('Recovery evidence is incomplete; no issue was changed.')
    return report


def validate_state(state, repo, now):
    if state is None:
        return {'schemaVersion': 1, 'repo': repo, 'incident': None}
    if not isinstance(state, dict) or state.get('schemaVersion') != 1 or state.get('repo') != repo:
        raise NotificationError('Saved alert state is invalid; no issue was changed.')
    incident = state.get('incident')
    if incident is not None:
        if (not isinstance(incident, dict) or type(incident.get('number')) is not int or incident['number'] <= 0
                or incident.get('level') not in LEVELS or not isinstance(incident.get('fingerprint'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', incident['fingerprint'])
                or type(incident.get('active')) is not bool or type(incident.get('criticalMentioned')) is not bool
                or type(incident.get('openedAt')) is not int or timestamp(incident['openedAt']) is None or incident['openedAt'] > now
                or type(incident.get('lastUpdateAt')) is not int or timestamp(incident['lastUpdateAt']) is None or incident['lastUpdateAt'] > now):
            raise NotificationError('Saved incident state is invalid; no issue was changed.')
    return {'schemaVersion': 1, 'repo': repo, 'incident': dict(incident) if incident else None}


def managed(issue):
    author = issue.get('user', issue.get('author', {})) if isinstance(issue, dict) else {}
    return (isinstance(issue, dict) and not issue.get('pull_request') and issue.get('title') == TITLE
            and isinstance(issue.get('body'), str) and MARKER in issue['body']
            and isinstance(author, dict) and author.get('login') == BOT
            and type(issue.get('number')) is int and issue['number'] > 0)


def issue_metadata(issue, now):
    metadata = {}
    match = re.search(r'<!-- ottscout-health-state:(\{[^\n]*\}) -->', issue['body'])
    if match:
        try:
            metadata = json.loads(match[1])
        except ValueError:
            pass
    if (not isinstance(metadata, dict) or metadata.get('level') not in LEVELS
            or not isinstance(metadata.get('fingerprint'), str) or not re.fullmatch(r'[a-f0-9]{64}', metadata['fingerprint'])
            or type(metadata.get('criticalMentioned')) is not bool or type(metadata.get('updatedAt')) is not int or timestamp(metadata.get('updatedAt')) is None
            or metadata['updatedAt'] > now):
        return {}
    return metadata


def adopted_incident(issue, now):
    metadata = issue_metadata(issue, now)
    level = metadata.get('level') if metadata.get('level') in LEVELS else 'warning'
    key = metadata.get('fingerprint')
    if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
        key = fingerprint([])
    updated = timestamp(metadata.get('updatedAt'))
    opened = timestamp(issue.get('created_at') or issue.get('createdAt'))
    return {'number': issue['number'], 'active': not (level == 'normal' and issue.get('state') == 'closed'),
            'openedAt': opened if opened and opened <= now else now,
            'lastUpdateAt': updated if updated and updated <= now else now, 'level': level,
            'fingerprint': key, 'criticalMentioned': metadata.get('criticalMentioned') is True}


def issue_body(report, incident, now, mention=None, workflow=None, recovered=False):
    metadata = {'level': report['status'], 'fingerprint': fingerprint(report['causes']),
                'criticalMentioned': incident['criticalMentioned'], 'updatedAt': now}
    lines = [MARKER, '<!-- ottscout-health-state:' + json.dumps(metadata, separators=(',', ':')) + ' -->', '',
             'OTTScout release monitoring has recovered.' if recovered else 'OTTScout release monitoring needs attention.', '',
             '**Status: ' + report['status'] + '**', '', 'Checked: ' + iso(report['evaluatedAt']) + '.',
             'Incident opened: ' + iso(incident['openedAt']) + '.', '']
    if mention:
        lines += ['@' + mention + ' — the release monitor has detected a critical issue.', '']
    if report['causes']:
        # Codes are generated by our monitor. Never copy raw provider errors,
        # candidate text, tokens or arbitrary input strings into an issue body.
        lines += ['Signals:', ''] + ['- `' + c['code'] + '` — ' + c['severity'] for c in report['causes']] + ['']
    else:
        lines += ['All monitored operational signals are healthy. Catalogue coverage remains partial.', '']
    new_feed = report.get('newFeed', {})
    completed = timestamp(new_feed.get('completedThrough')) if isinstance(new_feed, dict) else None
    lines += ['New-release feed complete through: ' + (iso(completed) or 'not confirmed') + '.']
    budget = report.get('requestBudget', {})
    if isinstance(budget, dict) and all(type(budget.get(k)) is int and budget[k] >= 0 for k in ('requestsUsed', 'monthlyLimit', 'requestsRemaining')):
        lines += ['Streaming requests: ' + str(budget['requestsUsed']) + '/' + str(budget['monthlyLimit']) + '; ' + str(budget['requestsRemaining']) + ' remaining.']
    lines += ['', '[Live catalogue status](' + STATUS_URL + ')']
    links = []
    for label, value in [('Monitor run', workflow), ('Collector run', report.get('heartbeat', {}).get('url') if isinstance(report.get('heartbeat'), dict) else None)]:
        safe = workflow_url(value)
        if safe and safe not in links:
            lines.append('[' + label + '](' + safe + ')'); links.append(safe)
    lines += ['', 'This checks feed completion, discovery and known publication gaps. It does not certify every OTT title, premiere date, audio track or India playback.',
              'This issue stays open until all active monitoring causes recover.']
    return '\n'.join(lines) + '\n'


def reconcile_health(report, state, adapter, repo, now=None, mention=None, workflow=None):
    """Apply at most one issue mutation. Adapter injection keeps tests offline."""
    now = int(time.time()) if now is None else now
    if type(now) is not int or timestamp(now) is None or not isinstance(repo, str) or not REPO.fullmatch(repo):
        raise NotificationError('Invalid notification configuration.')
    if mention is not None and (not isinstance(mention, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', mention)):
        raise NotificationError('Invalid alert recipient.')
    report = validate_health(report, now)
    result = validate_state(state, repo, now)
    incident = result['incident']
    issue = None
    if incident and incident['active']:
        issue = adapter.get(incident['number'])
        if not managed(issue):
            raise NotificationError('The saved issue is not a managed bot alert; no issue was changed.')
        # Collector and watchdog caches are separate. The shared issue's own
        # metadata prevents a stale cache from re-mentioning, bypassing the
        # throttle or reopening an incident another workflow already resolved.
        if issue_metadata(issue, now):
            remote = adopted_incident(issue, now)
            if remote['lastUpdateAt'] >= incident['lastUpdateAt']:
                remote['criticalMentioned'] = remote['criticalMentioned'] or incident['criticalMentioned']
                incident = remote; result['incident'] = incident
    if incident is None or not incident['active']:
        candidates = [i for i in adapter.list_open() if managed(i)]
        if len(candidates) > 1:
            raise NotificationError('Multiple managed alerts need review; no issue was changed.')
        if candidates:
            issue = candidates[0]; incident = adopted_incident(issue, now); result['incident'] = incident
    if report['status'] == 'normal':
        if incident and incident['active']:
            if issue.get('state') != 'closed':
                adapter.update(incident['number'], {'state': 'closed', 'state_reason': 'completed',
                    'body': issue_body(report, incident, now, workflow=workflow, recovered=True)})
            incident.update(active=False, level='normal', fingerprint=fingerprint([]), lastUpdateAt=now)
            return result, 'recovered'
        return result, 'healthy'
    key = fingerprint(report['causes'])
    if incident is None or not incident['active']:
        notify = mention if report['status'] == 'critical' else None
        incident = {'number': 0, 'active': True, 'openedAt': now, 'lastUpdateAt': now, 'level': report['status'],
                    'fingerprint': key, 'criticalMentioned': bool(notify)}
        created = adapter.create(TITLE, issue_body(report, incident, now, mention=notify, workflow=workflow))
        if not managed(created):
            raise NotificationError('GitHub did not return a managed bot issue.')
        incident['number'] = created['number']; result['incident'] = incident
        return result, 'created'
    changed_level = incident['level'] != report['status']
    changed_signals = incident['fingerprint'] != key
    closed = issue.get('state') == 'closed'
    if changed_level or closed or (changed_signals and now - incident['lastUpdateAt'] >= UPDATE_INTERVAL):
        notify = mention if report['status'] == 'critical' and not incident['criticalMentioned'] else None
        incident.update(level=report['status'], fingerprint=key, lastUpdateAt=now,
                        criticalMentioned=incident['criticalMentioned'] or bool(notify))
        payload = {'body': issue_body(report, incident, now, mention=notify, workflow=workflow)}
        if closed:
            payload['state'] = 'open'
        adapter.update(incident['number'], payload)
        return result, 'reopened' if closed else 'updated'
    return result, 'unchanged'


class GitHubIssues:
    def __init__(self, repo):
        if not REPO.fullmatch(repo):
            raise NotificationError('Invalid repository.')
        self.repo = repo

    def call(self, endpoint, method='GET', payload=None, paginate=False):
        args = ['gh', 'api', '--hostname', 'github.com', '--method', method, endpoint]
        if paginate:
            args += ['--paginate', '--slurp']
        if payload is not None:
            args += ['--input', '-']
        try:
            process = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                                     text=True, capture_output=True, check=True)
            return json.loads(process.stdout)
        except (OSError, subprocess.CalledProcessError, ValueError):
            raise NotificationError('GitHub issue access failed; alert state was not advanced.') from None

    def list_open(self):
        pages = self.call('repos/' + self.repo + '/issues?state=open&creator=github-actions%5Bbot%5D&per_page=100', paginate=True)
        if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
            raise NotificationError('GitHub returned invalid issue data.')
        return [issue for page in pages for issue in page]

    def get(self, number):
        return self.call('repos/' + self.repo + '/issues/' + str(number))

    def create(self, title, body):
        return self.call('repos/' + self.repo + '/issues', 'POST', {'title': title, 'body': body})

    def update(self, number, payload):
        return self.call('repos/' + self.repo + '/issues/' + str(number), 'PATCH', payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default='reports/catalogue-health.json')
    parser.add_argument('--state', default='.state/catalogue-alert-state.json')
    parser.add_argument('--repo', required=True)
    parser.add_argument('--mention')
    parser.add_argument('--workflow-url')
    parser.add_argument('--now', type=int)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = json.loads(Path(args.report).read_text(encoding='utf-8'))
        path = Path(args.state)
        state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
        now = int(time.time()) if args.now is None else args.now
        report = validate_health(report, now)
        validate_state(state, args.repo, now)
        if args.dry_run:
            print('Dry run: catalogue status ' + report['status'] + '; no GitHub request or state write.')
            return 0
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise NotificationError('Issue notifications run only in GitHub Actions; use --dry-run locally.')
        saved, action = reconcile_health(report, state, GitHubIssues(args.repo), args.repo, now, args.mention, args.workflow_url)
        write_json(args.state, saved)
        print('Catalogue alert: ' + action + ((' #' + str(saved['incident']['number'])) if saved['incident'] else ''))
        return 0
    except (OSError, ValueError, NotificationError):
        print('Catalogue alert could not be safely reconciled. No recovery is assumed; check the monitoring inputs and GitHub issue access.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
