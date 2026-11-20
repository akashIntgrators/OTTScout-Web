"""Evaluate catalogue delivery health from saved evidence; never calls a data API."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlparse

HOUR = 3600
PLATFORMS = ('Netflix', 'Prime Video', 'Sun NXT', 'JioHotstar', 'ZEE5', 'aha', 'SonyLIV')
DEFAULT_THRESHOLDS = {'warningHours': 12, 'criticalHours': 24, 'budgetLow': 20}
LEVELS = {'normal': 0, 'warning': 1, 'critical': 2}
SOURCE_ID = re.compile(r'[a-z0-9][a-z0-9_.-]{0,79}')
TITLE_ID = re.compile(r'motn:[A-Za-z0-9-]{1,95}')


def timestamp(value):
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                return None
            value = parsed.timestamp()
        except (ValueError, OverflowError):
            return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 4102444800:
        return None
    return int(value)


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def count(value):
    return value if type(value) is int and 0 <= value <= 1000000000 else None


def workflow_url(value):
    if not isinstance(value, str):
        return None
    return value if re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/[0-9]+', value) else None


def exact_identity(link, platform):
    """Match title identifiers, never substrings, episode IDs or a title's name."""
    if not isinstance(link, str) or len(link) > 8192:
        return None
    try:
        url = urlparse(link)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            return None
        if platform == 'Netflix' and url.hostname in ('netflix.com', 'www.netflix.com'):
            match = re.fullmatch(r'/(?:in/)?(?:title|watch)/([0-9]+)/?', url.path)
        elif platform == 'JioHotstar' and url.hostname in ('hotstar.com', 'www.hotstar.com'):
            match = re.fullmatch(r'/in/(?:shows|movies)/[A-Za-z0-9-]+/([0-9]+)(?:/watch)?/?', url.path)
        elif platform == 'SonyLIV' and url.hostname in ('sonyliv.com', 'www.sonyliv.com'):
            match = re.fullmatch(r'/shows/[A-Za-z0-9-]+-([0-9]+)(?:/[A-Za-z0-9-]+-[0-9]+)?/?', url.path)
            if match is None:
                match = re.fullmatch(r'/movies/[A-Za-z0-9-]+-([0-9]+)/?', url.path)
        else:
            return None
        return match[1] if match else None
    except ValueError:
        return None


def current_offer(offer, now):
    """An exact link alone is insufficient if every corresponding offer is inactive."""
    for key in ('availableSince', 'expiresOn', 'evidenceExpiresAt'):
        value = offer.get(key)
        if value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return False
        if value == 0 and key != 'evidenceExpiresAt':
            continue
        if (key == 'availableSince' and value > now) or (key != 'availableSince' and value <= now):
            return False
    return True


def _thresholds(overrides):
    result = {**DEFAULT_THRESHOLDS, **(overrides or {})}
    if set(result) != set(DEFAULT_THRESHOLDS) or any(type(v) is not int for v in result.values()):
        raise ValueError('Invalid health thresholds')
    if not 1 <= result['warningHours'] < result['criticalHours'] <= 168 or not 0 <= result['budgetLow'] <= 100:
        raise ValueError('Invalid health thresholds')
    return result


def _pending(value, now):
    if value is None:
        return None
    if not isinstance(value, dict):
        return False
    start, end, pages = timestamp(value.get('from')), timestamp(value.get('to')), count(value.get('pages'))
    if start is None or end is None or start > end or end > now or pages is None:
        return False
    return {'from': iso(start), 'to': iso(end), 'pages': pages, 'ageHours': round((now - start) / HOUR, 2)}


def evaluate_health(report=None, catalogue=None, discovery=None, workflow_runs=None, previous=None,
                    now=None, thresholds=None, required_sources=None, input_errors=()):
    """Return (report, persisted progress state). Missing observations cannot be green."""
    now = int(time.time()) if now is None else now
    if type(now) is not int or not 0 < now <= 4102444800:
        raise ValueError('Invalid evaluation time')
    limits = _thresholds(thresholds)
    if required_sources is not None and (not isinstance(required_sources, (tuple, list)) or len(required_sources) > 20 or any(
            not isinstance(s, str) or not SOURCE_ID.fullmatch(s) for s in required_sources)):
        raise ValueError('Invalid required discovery sources')
    causes = {}

    def add(code, severity, message, **details):
        causes[code] = {'code': code, 'severity': severity, 'message': message, 'details': details}

    def age_level(age):
        return 'critical' if age > limits['criticalHours'] else 'warning' if age > limits['warningHours'] else None

    for code in input_errors:
        if isinstance(code, str) and re.fullmatch(r'[a-z0-9_]{1,80}', code):
            add(code, 'critical', 'A required monitoring input could not be read.')
        else:
            add('health_input_error_invalid', 'critical', 'A monitoring failure signal could not be validated.')
    if report is not None and not isinstance(report, dict):
        add('collector_report_invalid', 'critical', 'The collector report is invalid.')
    report = report if isinstance(report, dict) else {}
    valid_catalogue = isinstance(catalogue, dict) and catalogue.get('schemaVersion') == 1 and catalogue.get('mode') == 'live' and isinstance(catalogue.get('titles'), list) and bool(catalogue['titles'])
    if not valid_catalogue:
        add('published_snapshot_unknown', 'critical', 'The published catalogue could not be checked.')
    catalogue = catalogue if valid_catalogue else {}
    basis = report if isinstance(report.get('streamingFreshness'), dict) else catalogue
    freshness = basis.get('streamingFreshness', {})
    freshness = freshness if isinstance(freshness, dict) else {}
    new = freshness.get('new', {})
    new = new if isinstance(new, dict) else {}
    complete = timestamp(new.get('completedThrough'))
    if complete is None or complete > now:
        complete = None
        add('new_feed_unknown', 'critical', 'The new-release feed has no valid completion watermark.')
    new_age = (now - complete) / HOUR if complete is not None else None
    if new_age is not None and age_level(new_age):
        add('new_feed_stale', age_level(new_age), 'The new-release feed completion is behind.', ageHours=round(new_age, 2))
    pending = _pending(new.get('pendingWindow'), now)
    if pending is False:
        add('new_feed_pending_unknown', 'critical', 'New-release pagination progress is invalid.')
        pending = None
    if pending and age_level(pending['ageHours']):
        add('new_feed_pending_old', age_level(pending['ageHours']), 'A new-release window is still incomplete.', **pending)

    prior = {}
    if previous is not None:
        if (not isinstance(previous, dict) or previous.get('schemaVersion') != 1 or not isinstance(previous.get('newFeed'), dict)
                or not {'completedThrough', 'pendingWindow', 'firstObservedAt', 'lastProgressAt'} <= set(previous['newFeed'])):
            add('health_state_invalid', 'critical', 'Saved monitoring progress could not be validated.')
        else:
            prior = previous['newFeed']
    prior_complete = timestamp(prior.get('completedThrough'))
    last_progress = timestamp(prior.get('lastProgressAt'))
    first_seen = timestamp(prior.get('firstObservedAt')) or now
    if prior_complete is not None and prior_complete > now:
        prior_complete = None
        add('health_state_invalid', 'critical', 'Saved monitoring progress could not be validated.')
    if first_seen > now:
        first_seen = now
        add('health_state_invalid', 'critical', 'Saved monitoring progress could not be validated.')
    if last_progress and last_progress > now:
        last_progress = None
        add('health_state_invalid', 'critical', 'Saved monitoring progress could not be validated.')
    if prior_complete and complete and complete < prior_complete:
        add('new_feed_regressed', 'critical', 'The observed new-release watermark moved backwards.')
    prior_pending = prior.get('pendingWindow')
    progressed = bool(complete and prior_complete and complete > prior_complete)
    if pending and isinstance(prior_pending, dict):
        progressed = progressed or (pending['from'] == prior_pending.get('from') and pending['to'] == prior_pending.get('to')
                                    and type(prior_pending.get('pages')) is int and pending['pages'] > prior_pending['pages'])
    if progressed:
        last_progress = now
    if pending and prior and age_level((now - (last_progress or first_seen)) / HOUR):
        stalled = (now - (last_progress or first_seen)) / HOUR
        add('new_feed_stalled', age_level(stalled), 'No forward new-release progress has been observed.', ageHours=round(stalled, 2))
    publication_progress = basis.get('newPublication', {})
    publication_progress = publication_progress if isinstance(publication_progress, dict) else {}
    published_pages = count(publication_progress.get('publishedPages', publication_progress.get('pages')))
    published_at = timestamp(publication_progress.get('latestPublishedAt'))
    if published_at is not None and published_at > now:
        published_at = None
        add('new_publication_unknown', 'critical', 'Published new-release progress has an invalid time.')
    if published_pages is not None and type(prior.get('publishedPages')) is int and published_pages > prior['publishedPages']:
        progressed = True
        last_progress = now
        causes.pop('new_feed_stalled', None)
    new_result = {'completedThrough': iso(complete), 'ageHours': round(new_age, 2) if new_age is not None else None,
                  'pendingWindow': pending, 'lastProgressAt': iso(last_progress), 'progressObservedThisCheck': progressed}
    new_result['publication'] = {'publishedPages': published_pages, 'latestPublishedAt': iso(published_at)}
    pending_feeds = {}
    for kind in ('new', 'updated', 'removed'):
        raw_feed = freshness.get(kind)
        if not isinstance(raw_feed, dict):
            continue
        item = _pending(raw_feed.get('pendingWindow'), now)
        if item is False:
            add('feed_progress_invalid:' + kind, 'critical', 'A feed pagination window is invalid.')
        elif item:
            pending_feeds[kind] = item
            if kind != 'new' and item['ageHours'] > limits['criticalHours']:
                add('maintenance_pending_old:' + kind, 'warning', 'Availability maintenance is incomplete.', feed=kind, **item)

    runs = report.get('runs', [])
    attempts = [r for r in runs if isinstance(r, dict) and timestamp(r.get('at')) is not None] if isinstance(runs, list) else []
    latest = max(attempts, key=lambda r: timestamp(r['at'])) if attempts else {}
    attempt_at = timestamp(latest.get('at'))
    if attempt_at and attempt_at > now:
        add('collector_attempt_unknown', 'critical', 'The latest collector attempt has an invalid time.')
        attempt_at = None
    if latest.get('status') == 'failed':
        add('collector_attempt_failed', 'critical', 'The latest collector attempt failed.')
    collector = {'latestAttempt': {'at': iso(attempt_at), 'status': latest.get('status') if latest.get('status') in ('success', 'limited', 'failed') else 'unknown',
                                   'requests': count(latest.get('requests'))}}
    heartbeat = {'lastRunAt': iso(attempt_at), 'basis': 'collector-report', 'status': collector['latestAttempt']['status'], 'conclusion': None, 'url': None}
    if workflow_runs is not None:
        rows = workflow_runs if isinstance(workflow_runs, list) else workflow_runs.get('workflow_runs') if isinstance(workflow_runs, dict) else None
        valid = []
        queued = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    add('workflow_observation_invalid', 'critical', 'Collector workflow observations are invalid.')
                    continue
                at = timestamp(row.get('startedAt') or row.get('run_started_at') or row.get('createdAt') or row.get('created_at'))
                if at is None or at > now or row.get('status') not in ('completed', 'in_progress', 'queued', 'waiting', 'pending'):
                    add('workflow_observation_invalid', 'critical', 'Collector workflow observations are invalid.')
                if at and at <= now and row.get('status') in ('queued', 'waiting', 'pending'):
                    queued.append((at, row))
                if at and at <= now and row.get('status') in ('completed', 'in_progress'):
                    valid.append((at, row))
        if valid:
            at, row = max(valid, key=lambda x: x[0])
            conclusion = row.get('conclusion') if row.get('conclusion') in ('success', 'failure', 'cancelled', 'timed_out', 'action_required', 'neutral', 'skipped') else None
            heartbeat = {'lastRunAt': iso(at), 'basis': 'github-workflow', 'status': row['status'], 'conclusion': conclusion,
                         'url': workflow_url(row.get('url') or row.get('html_url'))}
            completed = [(at, r) for at, r in valid if r['status'] == 'completed']
            if completed:
                finished_at, finished = max(completed, key=lambda x: x[0])
                final = finished.get('conclusion')
                heartbeat['lastCompleted'] = {'at': iso(finished_at), 'conclusion': final if final in ('success', 'failure', 'cancelled', 'timed_out', 'action_required', 'neutral', 'skipped') else 'unknown',
                                               'url': workflow_url(finished.get('url') or finished.get('html_url'))}
                if final in ('failure', 'cancelled', 'timed_out', 'action_required'):
                    add('collector_workflow_failed', 'critical', 'The latest completed collector workflow did not succeed.')
                elif final not in ('success', 'neutral', 'skipped'):
                    add('collector_workflow_unknown', 'critical', 'The completed collector workflow outcome is unknown.')
                elif final in ('neutral', 'skipped'):
                    add('collector_workflow_not_run', 'warning', 'The latest completed collector workflow did not confirm a collection run.')
        else:
            heartbeat = {'lastRunAt': None, 'basis': 'github-workflow', 'status': 'unknown', 'conclusion': None, 'url': None}
        if queued:
            queued_at, queued_row = max(queued, key=lambda x: x[0])
            heartbeat['queued'] = {'since': iso(queued_at), 'status': queued_row['status'],
                                   'url': workflow_url(queued_row.get('url') or queued_row.get('html_url'))}
            if age_level((now - queued_at) / HOUR):
                add('collector_workflow_queued', age_level((now - queued_at) / HOUR), 'A collector workflow remains queued.', ageHours=round((now - queued_at) / HOUR, 2))
    beat_at = timestamp(heartbeat['lastRunAt'])
    if beat_at is None:
        add('collector_heartbeat_unknown', 'critical', 'A collector run could not be confirmed.')
    elif age_level((now - beat_at) / HOUR):
        add('collector_heartbeat_stale', age_level((now - beat_at) / HOUR), 'No recent collector execution was observed.', ageHours=round((now - beat_at) / HOUR, 2))

    budget = basis.get('requestBudget')
    budget = budget if isinstance(budget, dict) else {}
    budget_result = {key: count(budget.get(key)) for key in ('monthlyLimit', 'requestsUsed', 'requestsRemaining', 'freshnessReserve',
                     'newFeedDailyLimit', 'newFeedRequestsToday', 'newFeedRequestsRemainingToday', 'protectedFutureDays',
                     'protectedFutureDailyTarget', 'plannedPerFutureDay', 'protectedFutureRequests', 'emergencyReserve',
                     'catchupDailyLimit', 'freshRequestsAvailableToday')}
    for key in ('conservationMode', 'capacityInsufficient', 'newFeedBacklog'):
        budget_result[key] = budget.get(key) if type(budget.get(key)) is bool else None
    limit, used, remaining = (budget_result[k] for k in ('monthlyLimit', 'requestsUsed', 'requestsRemaining'))
    if None in (limit, used, remaining) or limit > 400 or remaining != max(0, limit - used):
        add('request_budget_unknown', 'critical', 'The protected streaming-request budget could not be validated.')
    elif used > limit:
        add('request_budget_exceeded', 'critical', 'Recorded requests exceed the configured protected limit.')
    elif remaining == 0:
        add('request_budget_exhausted', 'critical', 'The monthly streaming-request allowance is exhausted.')
    elif remaining <= limits['budgetLow']:
        add('request_budget_low', 'warning', 'The remaining monthly streaming-request allowance is low.', remaining=remaining)
    elif budget_result['freshnessReserve'] is not None and remaining < budget_result['freshnessReserve']:
        add('request_budget_below_reserve', 'warning', 'The remaining allowance is below planned freshness needs.', remaining=remaining)
    if pending and budget_result['newFeedRequestsRemainingToday'] == 0:
        add('new_feed_daily_budget_exhausted', 'warning', 'New-release pagination must wait for its next daily allowance.', pages=pending['pages'])
    if budget_result['capacityInsufficient'] is True:
        add('freshness_capacity_insufficient', 'warning', 'The remaining allowance cannot sustain the preferred future check rate.',
            plannedPerFutureDay=budget_result['plannedPerFutureDay'], targetPerFutureDay=budget_result['protectedFutureDailyTarget'])

    discovery_ok = isinstance(discovery, dict) and discovery.get('schemaVersion') == 1 and isinstance(discovery.get('sources'), list)
    source_results = []
    seen = set()
    unverified_total = 0
    flag_conflicts_total = 0
    if not discovery_ok or not discovery.get('sources'):
        add('official_discovery_unknown', 'critical', 'Official-release discovery could not be checked.')
        if not discovery_ok:
            discovery = {}
    evaluated = timestamp(discovery.get('evaluatedAt'))
    if discovery_ok and (evaluated is None or evaluated > now):
        add('official_discovery_unknown', 'critical', 'Official-release discovery has no valid evaluation time.')
    declared_required = discovery.get('requiredSources')
    if required_sources is None and declared_required is not None:
        if not isinstance(declared_required, list) or len(declared_required) > 20 or any(not isinstance(s, str) or not SOURCE_ID.fullmatch(s) for s in declared_required):
            add('official_discovery_invalid', 'critical', 'Required official-release sources are invalid.')
            required_sources = []
        else:
            required_sources = declared_required
    if required_sources is None:
        required_sources = [s['id'] for s in discovery.get('sources', []) if isinstance(s, dict)
                            and isinstance(s.get('id'), str) and SOURCE_ID.fullmatch(s['id'])
                            and s.get('required', True) is True]
    if not required_sources:
        add('official_required_sources_unknown', 'critical', 'No active required official-release discovery source is configured.')
    for source in discovery.get('sources', [])[:50]:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str) or not SOURCE_ID.fullmatch(source['id']) or source['id'] in seen:
            add('official_discovery_invalid', 'critical', 'Official-release source monitoring is invalid.')
            continue
        ident = source['id']; seen.add(ident)
        success, attempted = timestamp(source.get('lastSuccessAt')), timestamp(source.get('lastAttemptAt'))
        success = success if success is not None and success <= now else None
        attempted = attempted if attempted is not None and attempted <= now else None
        status = source.get('status') if source.get('status') in ('ok', 'partial', 'error', 'blocked', 'unsupported', 'disabled') else 'unknown'
        required = ident in required_sources
        candidates = source.get('unverifiedCandidates', [])
        unresolved = len(candidates) if isinstance(candidates, list) else count(candidates)
        reasons = {}
        if isinstance(candidates, list):
            for candidate in candidates:
                reason = candidate.get('reason') if isinstance(candidate, dict) else None
                reason = reason if isinstance(reason, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', reason) else 'unspecified'
                reasons[reason] = reasons.get(reason, 0) + 1
        elif isinstance(source.get('unverifiedReasons'), dict):
            for reason, total in list(source['unverifiedReasons'].items())[:50]:
                if isinstance(reason, str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', reason) and count(total) is not None:
                    reasons[reason] = total
        flag_conflicts = max(reasons.get('source-flag-conflict', 0), count(source.get('sourceFlagConflicts')) or 0)
        gaps = count(source.get('gaps'))
        errors = source.get('errors', [])
        error_count = len(errors) if isinstance(errors, list) else count(errors)
        result = {'id': ident, 'platform': source.get('platform') if source.get('platform') in PLATFORMS else None,
                  'lastAttemptAt': iso(attempted), 'lastSuccessAt': iso(success), 'status': status, 'required': required,
                  'candidates': count(source.get('candidates')), 'confirmed': count(source.get('confirmed')),
                  'gaps': gaps, 'unverifiedCandidates': unresolved, 'unverifiedReasons': reasons,
                  'sourceFlagConflicts': flag_conflicts, 'errors': error_count}
        source_results.append(result)
        unverified_total += unresolved or 0
        flag_conflicts_total += flag_conflicts
        if not required:
            continue
        if status in ('unsupported', 'disabled'):
            add('official_source_unsupported:' + ident, 'critical', 'A required official-release source is unavailable.')
        if success is None or attempted is None or status == 'unknown' or unresolved is None or error_count is None:
            add('official_source_unknown:' + ident, 'critical', 'An official-release source lacks valid scan evidence.')
        else:
            age = (now - success) / HOUR
            if age > limits['warningHours']:
                add('official_source_stale:' + ident, age_level(age), 'An official-release source has not been scanned successfully recently.', ageHours=round(age, 2))
            if status in ('error', 'blocked') or error_count:
                add('official_source_failed:' + ident, 'critical' if age > limits['warningHours'] else 'warning', 'An official-release source scan or verification failed.', errors=error_count)
        if status == 'partial' or (unresolved or 0) or (gaps or 0):
            add('official_verification_pending:' + ident, 'warning', 'Some official-release candidates remain unverified.', candidates=unresolved or 0, gaps=gaps or 0)
        if flag_conflicts:
            add('official_source_flag_conflict:' + ident, 'warning', 'An official source has conflicting availability evidence.', count=flag_conflicts)
    missing_sources = sorted(set(required_sources) - seen)
    for ident in missing_sources:
        add('official_source_missing:' + ident, 'critical', 'A required official-release discovery source is missing.')

    expected_raw = discovery.get('expectedVerifiedRecent', [])
    expected, expected_evidence, missing = [], [], []
    if discovery_ok and not isinstance(expected_raw, list):
        add('official_expectations_invalid', 'critical', 'Verified official-release expectations are invalid.')
        expected_raw = []
    if isinstance(expected_raw, list) and len(expected_raw) > 1000:
        add('official_expectations_invalid', 'critical', 'Verified official-release expectations exceed the monitoring bound.')
        expected_raw = expected_raw[:1000]
    seen_expected = set()
    for item in expected_raw:
        if not isinstance(item, dict):
            add('official_expectations_invalid', 'critical', 'Verified official-release expectations are invalid.'); continue
        ident, platform, platform_id = item.get('id'), item.get('platform'), item.get('platformTitleId')
        reviewed, expiry = timestamp(item.get('verifiedAt')), timestamp(item.get('expiresAt'))
        try:
            release = datetime.strptime(item.get('releaseDate', ''), '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp() - 19800
        except (ValueError, TypeError):
            release = None
        if ((ident is not None and (not isinstance(ident, str) or not TITLE_ID.fullmatch(ident))) or platform not in PLATFORMS
                or not isinstance(platform_id, str) or not re.fullmatch(r'[0-9]{1,30}', platform_id)
                or reviewed is None or expiry is None or release is None or expiry <= reviewed or expiry > reviewed + 30 * 86400
                or (platform, platform_id) in seen_expected):
            add('official_expectations_invalid', 'critical', 'Verified official-release expectations are invalid.'); continue
        seen_expected.add((platform, platform_id))
        if not release <= reviewed <= now < expiry:
            continue
        expected.append({'id': ident, 'platform': platform, 'platformTitleId': platform_id})
        expected_evidence.append({**expected[-1], 'releaseDate': item['releaseDate'], 'verifiedAt': reviewed, 'expiresAt': expiry})
        found = any(isinstance(t, dict) and isinstance(t.get('offers'), list) and any(isinstance(o, dict) and o.get('platform') == platform
                    and exact_identity(o.get('link'), platform) == platform_id and current_offer(o, now) for o in t['offers']) for t in catalogue.get('titles', []))
        if valid_catalogue and not found:
            missing.append(expected[-1])
    if missing:
        add('verified_official_missing', 'critical', 'Verified recent official releases are absent from the published catalogue.', count=len(missing))

    covered_raw = catalogue.get('coverage', report.get('supportedPlatforms', []))
    unsupported_raw = catalogue.get('missingPlatforms', report.get('missingPlatforms', []))
    covered = [p for p in covered_raw if p in PLATFORMS] if isinstance(covered_raw, list) else []
    unsupported = [p for p in unsupported_raw if p in PLATFORMS] if isinstance(unsupported_raw, list) else []
    backfill = basis.get('catalogBackfill', {})
    backfill = backfill if isinstance(backfill, dict) else {}
    ordered = sorted(causes.values(), key=lambda c: (-LEVELS[c['severity']], c['code']))
    status = max((c['severity'] for c in ordered), key=lambda s: LEVELS[s], default='normal')
    result = {'schemaVersion': 1, 'evaluatedAt': now, 'generatedAt': iso(now), 'status': status,
              'summary': 'Monitored release checks are current; catalogue coverage remains partial.' if status == 'normal' else 'Catalogue release monitoring needs attention.',
              'causes': ordered, 'newFeed': new_result, 'pendingFeeds': pending_feeds, 'collector': collector,
              'heartbeat': heartbeat, 'requestBudget': budget_result,
              'officialDiscovery': {'evaluatedAt': iso(evaluated), 'sources': source_results,
                                    'unverifiedCandidates': unverified_total, 'missingRequiredSources': missing_sources,
                                    'sourceFlagConflicts': flag_conflicts_total,
                                    'requiredSources': sorted(set(required_sources)),
                                    'expectedVerifiedRecent': expected_evidence},
              'publication': {'catalogueAvailable': valid_catalogue, 'expectedVerifiedRecent': len(expected), 'missingExpected': missing[:50]},
              'coverage': {'partial': True, 'covered': covered, 'unsupported': unsupported,
                           'backfillComplete': backfill.get('complete') is True,
                           'completedTasks': count(backfill.get('completedTasks')), 'totalTasks': count(backfill.get('totalTasks'))}}
    saved = {'schemaVersion': 1, 'evaluatedAt': now, 'newFeed': {
        'completedThrough': max(x for x in (complete, prior_complete) if x is not None) if complete is not None or prior_complete is not None else None,
        'pendingWindow': pending, 'firstObservedAt': first_seen, 'lastProgressAt': last_progress, 'publishedPages': published_pages}}
    return result, saved


def discovery_from_health(previous):
    """Reuse public observations for an independent watchdog, without renewing them."""
    if not isinstance(previous, dict) or previous.get('schemaVersion') != 1:
        return None
    source = previous.get('officialDiscovery')
    if not isinstance(source, dict) or not isinstance(source.get('sources'), list):
        return None
    required = source.get('requiredSources')
    if required is None:
        required = [s['id'] for s in source['sources'] if isinstance(s, dict)
                    and s.get('required') is True and isinstance(s.get('id'), str)]
    return {'schemaVersion': 1, 'evaluatedAt': source.get('evaluatedAt'), 'sources': source['sources'],
            'requiredSources': required,
            'expectedVerifiedRecent': source.get('expectedVerifiedRecent', [])}


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default='reports/pilot.json')
    parser.add_argument('--catalog', default='data/catalog.json')
    parser.add_argument('--discovery-report', default='reports/official-discovery.json')
    parser.add_argument('--workflow-runs')
    parser.add_argument('--previous-health')
    parser.add_argument('--state', default='.state/catalogue-health-state.json')
    parser.add_argument('--out', default='reports/catalogue-health.json')
    parser.add_argument('--public-out', default='data/catalogue-health.json')
    parser.add_argument('--now', type=int)
    parser.add_argument('--required-source', action='append')
    parser.add_argument('--fail-on-critical', action='store_true')
    def input_code(value):
        if not re.fullmatch(r'[a-z0-9_]{1,80}', value):
            raise argparse.ArgumentTypeError('Use a constant lowercase monitoring failure code.')
        return value
    parser.add_argument('--input-error', action='append', default=[], type=input_code)
    args = parser.parse_args(argv)
    errors = list(args.input_error)

    def read(path, label, optional=False):
        if path is None:
            return None
        try:
            target = Path(path)
            if target.stat().st_size > (50_000_000 if label == 'catalog' else 5_000_000):
                raise ValueError('Oversized monitoring input')
            return json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            if not optional or Path(path).exists():
                errors.append(label + '_input_unavailable')
            return None

    report = read(args.report, 'collector', optional=True)
    catalogue = read(args.catalog, 'catalog')
    discovery = read(args.discovery_report, 'discovery', optional=True)
    previous_health = read(args.previous_health, 'previous_health', optional=True)
    if discovery is None:
        discovery = discovery_from_health(previous_health)
    workflows = read(args.workflow_runs, 'workflow')
    previous = read(args.state, 'health_state', optional=True)
    health, state = evaluate_health(report, catalogue, discovery, workflows, previous, args.now,
                                   required_sources=args.required_source, input_errors=errors)
    write_json(args.out, health)
    if args.public_out:
        write_json(args.public_out, health)
    write_json(args.state, state)
    print('Catalogue health: ' + health['status'] + '; signals: ' + ', '.join(c['code'] for c in health['causes']))
    return 1 if args.fail_on_critical and health['status'] == 'critical' else 0


if __name__ == '__main__':
    raise SystemExit(main())
