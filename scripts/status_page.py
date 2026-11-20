"""Readable public freshness status, separate from movie discovery screens."""
from datetime import datetime, timedelta, timezone
from html import escape
import json

IST = timezone(timedelta(hours=5, minutes=30))
SOURCE_NAMES = {'sony-movies': 'SonyLIV movies', 'sony-series': 'SonyLIV series', 'netflix-tudum': 'Netflix announcements'}


def _date(value):
    try:
        if value is None or value == 0 or (type(value) in (int, float) and value < 0):
            return 'Not confirmed'
        date = datetime.fromtimestamp(value, timezone.utc) if type(value) in (int, float) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return date.astimezone(IST).strftime('%d %B, %I:%M %p IST')
    except (ValueError, TypeError, OverflowError):
        return 'Not confirmed'


def render_status(root):
    path = root / 'data/catalogue-health.json'
    try:
        value = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(value, dict): value = {}
    except (ValueError, OSError):
        value = {}
    status = value.get('status', 'unknown')
    title = {'normal': 'Updates are within the current target', 'warning': 'Some release updates need attention',
             'critical': 'Release updates are delayed'}.get(status, 'Freshness has not been confirmed')
    evaluated = value.get('evaluatedAt')
    evaluated = evaluated if type(evaluated) is int and evaluated > 0 else 0
    feed = value.get('newFeed') if isinstance(value.get('newFeed'), dict) else {}
    heartbeat = value.get('heartbeat') if isinstance(value.get('heartbeat'), dict) else {}
    budget = value.get('requestBudget') if isinstance(value.get('requestBudget'), dict) else {}
    discovery = value.get('officialDiscovery') if isinstance(value.get('officialDiscovery'), dict) else {}
    causes = value.get('causes') if isinstance(value.get('causes'), list) else []
    source_items = discovery.get('sources', [])
    if isinstance(source_items, dict):
        source_items = [{'id': key, **row} for key, row in source_items.items() if isinstance(row, dict)]
    sources = []
    for row in source_items if isinstance(source_items, list) else []:
        if not isinstance(row, dict): continue
        name = str(row.get('name') or SOURCE_NAMES.get(row.get('id')) or row.get('platform') or 'Official source')
        state = str(row.get('status') or 'unconfirmed').replace('_', ' ')
        date = _date(row.get('lastSuccessAt'))
        sources.append('<li><strong>' + escape(name) + '</strong> — ' + escape(state) + '. Last successful check: ' + escape(date) + '.</li>')
    issues = ''
    for row in causes:
        if not isinstance(row, dict):
            continue
        source = SOURCE_NAMES.get(str(row.get('code', '')).split(':')[-1])
        message = str(row.get('message', 'An update check needs attention.'))
        issues += '<li>' + escape((source + ': ' if source else '') + message) + '</li>'
    content = ('<section class="status-summary" data-status-evaluated="' + str(evaluated) + '">'
        '<h2 id="freshness-heading" aria-live="polite">' + escape(title) + '</h2>'
        '<p id="freshness-explanation">' + escape(str(value.get('summary') or 'No current monitoring report is available.')) + '</p>'
        '<p>Report checked: <time>' + escape(_date(evaluated)) + '</time>. This page uses India time.</p></section>'
        '<dl class="status-facts"><dt>New-release feed complete through</dt><dd>' + escape(_date(feed.get('completedThrough'))) + '</dd>'
        '<dt>Latest validated release-page progress</dt><dd>' + escape(_date(feed.get('lastProgressAt'))) + '</dd>'
        '<dt>Latest collector run</dt><dd>' + escape(_date(heartbeat.get('lastRunAt'))) + '</dd>'
        '<dt>Streaming requests used this UTC month</dt><dd>' + escape(str(budget.get('requestsUsed', 'Unconfirmed'))) + ' / '
        + escape(str(budget.get('monthlyLimit', '400'))) + '</dd></dl>'
        '<h2>What needs attention</h2>' + ('<ul>' + issues + '</ul>' if issues else '<p>No freshness incident is recorded in this report.</p>')
        + '<p><a href="https://github.com/akashIntgrators/OTTScout-Web/issues">Open update alerts on GitHub</a> · <a href="/data/catalogue-health.json">Read the status data</a></p>'
        '<h2>Automatic official-source checks</h2>' + ('<ul>' + ''.join(sources) + '</ul>' if sources else '<p>Official-source checks have not been confirmed.</p>')
        + '<h2>How to read this status</h2><p>A completed job does not prove that every movie has been collected. Each validated new-release page is published while unfinished pages continue from their saved position. The complete-through time advances only when that entire window is finished.</p>'
        '<p>Automatic fallbacks use supported, accessible official listings. Missing language, original-language or availability evidence stays unverified. Coverage remains partial; unsupported sources and gaps are recorded rather than labelled as checked.</p>'
        '<p>Fresh releases take priority over older imports. Every streaming request, including a failed attempt, shares the enforced monthly and per-run limits. Official website checks and this status page make no streaming-provider or TMDB API calls.</p>'
        '<p>GitHub issue alerts stay open while a freshness incident remains and close after recovery. The monitor runs separately from the collector, so a missed collector run can still be detected. GitHub notification delivery depends on your repository notification settings.</p>'
        '<script src="/web/catalogue-status.js?v=1" defer></script>')
    return content
