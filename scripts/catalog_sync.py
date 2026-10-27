#!/usr/bin/env python3
"""Six-hour India catalog pilot. Standard library only; no secrets in exported files."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PLATFORMS = {
    'Netflix': ['netflix'], 'Prime Video': ['prime'], 'Sun NXT': ['sunnxt', 'sun nxt'],
    'JioHotstar': ['hotstar', 'jiohotstar'], 'ZEE5': ['zee5'],
    'aha': ['aha'], 'SonyLIV': ['sonyliv', 'sony liv'],
}
LANGUAGES = {'eng': 'English', 'en': 'English', 'hin': 'Hindi', 'hi': 'Hindi',
             'tel': 'Telugu', 'te': 'Telugu', 'tam': 'Tamil', 'ta': 'Tamil',
             'kan': 'Kannada', 'kn': 'Kannada', 'mal': 'Malayalam', 'ml': 'Malayalam'}
# Verified correction: provider audio is Hindi, but the film's original is Kannada.
# https://tv.apple.com/in/movie/dr-56/umc.cmc.48r2rpynxx4gtg53d94qc7aki
ORIGINAL_LANGUAGE_CORRECTIONS = {'motn:57489': 'Kannada'}
DAY = 86400

class SyncError(Exception):
    pass

class BudgetReached(SyncError):
    pass

def stamp(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).isoformat()

def open_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS titles (id TEXT PRIMARY KEY, body TEXT NOT NULL, first_seen INTEGER NOT NULL, last_checked INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, title_id TEXT NOT NULL, platform TEXT NOT NULL, kind TEXT NOT NULL, at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, at INTEGER NOT NULL, endpoint TEXT NOT NULL, status INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, at INTEGER NOT NULL, status TEXT NOT NULL, requests INTEGER NOT NULL, changed INTEGER NOT NULL, message TEXT NOT NULL);
    ''')
    return db

def get_meta(db, key, default=None):
    row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default

def set_meta(db, key, value):
    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

def platform_map(country):
    if country.get('countryCode') != 'in' or not isinstance(country.get('services'), list):
        raise SyncError('Invalid India coverage response')
    found = {}
    for name, aliases in PLATFORMS.items():
        for service in country['services']:
            if service.get('id', '').lower() in aliases or service.get('name', '').lower() in aliases + [name.lower()]:
                found[name] = service['id']
                break
    return found

def language_names(items, subtitle=False):
    result = set()
    for item in items or []:
        locale = item.get('locale', {}) if subtitle else item
        code = locale.get('language', '')
        if code:
            result.add(LANGUAGES.get(code.lower(), code))
    return sorted(result)

def safe_url(value):
    return value if isinstance(value, str) and value.startswith('https://') else None

def normalize(show, mapping, now):
    if not isinstance(show, dict) or not show.get('id') or not isinstance(show.get('title'), str) or show.get('showType') not in ('movie', 'series'):
        raise SyncError('Invalid show record')
    options_map = show.get('streamingOptions')
    if not isinstance(options_map, dict):
        raise SyncError('Missing streaming availability')
    reverse = {v: k for k, v in mapping.items()}
    offers = []
    for option in options_map.get('in', []):
        service_id = option.get('service', {}).get('id')
        if service_id not in reverse:
            continue
        offer_type = option.get('type')
        if offer_type not in ('subscription', 'free', 'rent', 'buy', 'addon'):
            raise SyncError('Invalid offer type')
        offers.append({
            'platform': reverse[service_id], 'type': offer_type,
            'audio': language_names(option.get('audios')),
            'subtitles': language_names(option.get('subtitles'), True),
            'link': safe_url(option.get('link')),
            'addon': option.get('addon', {}).get('name') if isinstance(option.get('addon'), dict) else None,
            # This is provider detection time, not a confirmed OTT premiere date.
            'availableSince': option.get('availableSince'),
            'expiresOn': option.get('expiresOn'),
        })
    poster = show.get('imageSet', {}).get('verticalPoster', {})
    return {'id': 'motn:' + str(show['id']), 'title': show['title'],
            'type': 'Movie' if show['showType'] == 'movie' else 'Series',
            'year': show.get('releaseYear') or show.get('firstAirYear'),
            'overview': show.get('overview', ''),
            'tmdbId': show.get('tmdbId'), 'imdbId': show.get('imdbId'),
            'originalLanguage': LANGUAGES.get(show.get('originalLanguage', '').lower(), show.get('originalLanguage')) if isinstance(show.get('originalLanguage'), str) else None,
            'genres': [g['name'] for g in show.get('genres', []) if isinstance(g, dict) and isinstance(g.get('name'), str)],
            'poster': safe_url(poster.get('w480') or poster.get('w360')),
            'offers': sorted(offers, key=lambda x: (x['platform'], x['type'], x['link'] or ''))}

def save_show(db, show, mapping, now):
    body = normalize(show, mapping, now)
    old = db.execute('SELECT body FROM titles WHERE id=?', (body['id'],)).fetchone()
    if old and not body.get('originalLanguage'):
        body['originalLanguage'] = json.loads(old[0]).get('originalLanguage')
    if old:
        previous = json.loads(old[0])
        for key in ('tmdbId', 'imdbId'):
            if not body.get(key): body[key] = previous.get(key)
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=False)
    changed = not old or old[0] != encoded
    db.execute('''INSERT INTO titles VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,last_checked=excluded.last_checked''',
               (body['id'], encoded, now, now))
    return int(changed)

class Client:
    def __init__(self, db, key, mode='direct', monthly_limit=400, run_limit=12):
        self.db, self.key, self.mode = db, key, mode
        self.monthly_limit, self.run_limit, self.calls = monthly_limit, run_limit, 0
        self.base = 'https://api.movieofthenight.com/v4' if mode == 'direct' else 'https://streaming-availability.p.rapidapi.com'

    def get(self, endpoint, params=None):
        month = datetime.now(timezone.utc).strftime('%Y-%m-01T00:00:00+00:00')
        start = int(datetime.fromisoformat(month).timestamp())
        used = self.db.execute('SELECT count(*) FROM requests WHERE at>=?', (start,)).fetchone()[0]
        if used >= self.monthly_limit or self.calls >= self.run_limit:
            raise BudgetReached('Configured request limit reached; resume on a later run or adjust budget')
        # Count and commit before sending, including network failures and malformed responses.
        now = int(time.time())
        row = self.db.execute('INSERT INTO requests(at,endpoint,status) VALUES (?,?,0)', (now, endpoint))
        request_id = row.lastrowid
        self.db.commit()
        self.calls += 1
        headers = {'Accept': 'application/json'}
        headers['X-API-Key' if self.mode == 'direct' else 'X-RapidAPI-Key'] = self.key
        if self.mode == 'rapidapi':
            headers['X-RapidAPI-Host'] = 'streaming-availability.p.rapidapi.com'
        url = self.base + endpoint + ('?' + urlencode(params) if params else '')
        try:
            with urlopen(Request(url, headers=headers), timeout=45) as response:
                status = response.status
                raw = response.read()
            self.db.execute('UPDATE requests SET status=? WHERE id=?', (status, request_id))
            self.db.commit()
            return json.loads(raw)
        except HTTPError as error:
            self.db.execute('UPDATE requests SET status=? WHERE id=?', (error.code, request_id))
            self.db.commit()
            raise SyncError(f'Provider returned HTTP {error.code}; no automatic retries') from None
        except (URLError, TimeoutError, ValueError):
            raise SyncError('Provider network or JSON response error; previous catalog retained') from None

def read_pages(client, endpoint, params, shows_map=False):
    cursor = None
    seen = set()
    while True:
        page = client.get(endpoint, {**params, **({'cursor': cursor} if cursor else {})})
        if not isinstance(page, dict) or not isinstance(page.get('hasMore'), bool):
            raise SyncError('Invalid paginated response')
        shows = page.get('shows')
        if not isinstance(shows, dict if shows_map else list):
            raise SyncError('Invalid shows response')
        yield page
        if not page['hasMore']:
            break
        cursor = page.get('nextCursor')
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise SyncError('Missing or repeated pagination cursor')
        seen.add(cursor)

def backfill_recent(db, client, mapping, now):
    """Resume a one-time seven-day history query; never infer history from baseline imports."""
    state = get_meta(db, 'recent_backfill_v1')
    if state and state.get('complete'):
        return 0
    if state is None:
        state = {'from': now - 7 * DAY, 'to': now, 'cursor': None, 'complete': False, 'pages': 0}
        set_meta(db, 'recent_backfill_v1', state)
        db.commit()
    if now - state['from'] > 30 * DAY:
        raise SyncError('Recent-history backfill expired before completion; review its state before restarting')
    changed = 0
    reverse = {v: k for k, v in mapping.items()}
    seen = set()
    while not state['complete']:
        params = {'country': 'in', 'catalogs': ','.join(mapping.values()), 'change_type': 'new',
                  'item_type': 'show', 'from': state['from'], 'to': state['to'], 'order_direction': 'asc'}
        if state['cursor']:
            params['cursor'] = state['cursor']
        page = client.get('/changes', params)
        if not isinstance(page, dict) or not isinstance(page.get('hasMore'), bool) or not isinstance(page.get('shows'), dict) or not isinstance(page.get('changes'), list):
            raise SyncError('Invalid recent-history page')
        cursor = page.get('nextCursor')
        if page['hasMore'] and (not isinstance(cursor, str) or not cursor or cursor == state['cursor'] or cursor in seen):
            raise SyncError('Invalid recent-history pagination cursor')
        for show in page['shows'].values():
            normalize(show, mapping, now)
        rows = []
        for event in page['changes']:
            if not isinstance(event, dict) or str(event.get('showId')) not in {str(k) for k in page['shows']}:
                raise SyncError('Recent-history change lacks a show record')
            timestamp = event.get('timestamp')
            service = event.get('service', {}).get('id')
            if not isinstance(timestamp, int) or not state['from'] <= timestamp <= state['to'] or service not in reverse:
                raise SyncError('Recent-history event has invalid date or platform')
            event_id = json.dumps([event.get('showId'), service, 'new', timestamp, event.get('link')])
            rows.append((event_id, 'motn:' + str(event['showId']), reverse[service], 'new', timestamp))
        # A validated page and its resume cursor are committed together.
        for show in page['shows'].values():
            changed += save_show(db, show, mapping, now)
        db.executemany('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)', rows)
        state = {**state, 'cursor': cursor if page['hasMore'] else None,
                 'complete': not page['hasMore'], 'pages': state['pages'] + 1}
        set_meta(db, 'recent_backfill_v1', state)
        db.commit()
        seen.add(cursor)
    return changed

def backfill_original_languages(db, client, mapping, now, max_pages=2):
    """The API omits original language from Show; use its explicit language filter."""
    changed = 0
    pages = 0
    tasks = [(code, kind) for code in ('en','hi','te','ta','kn','ml') for kind in ('movie','series')]
    start = get_meta(db, 'original_backfill_next', 0)
    for offset in range(len(tasks)):
        task_index = (start + offset) % len(tasks)
        code, kind = tasks[task_index]
        key = 'original_backfill_v1:' + code + ':' + kind
        state = get_meta(db, key, {'cursor': None, 'complete': False, 'pages': 0})
        seen = {state['cursor']} if state['cursor'] else set()
        while not state['complete']:
            if pages >= max_pages or getattr(client, 'calls', 0) >= getattr(client, 'run_limit', float('inf')):
                return changed
            params = {'country':'in', 'catalogs':','.join(mapping.values()), 'show_type':kind,
                      'series_granularity':'show', 'order_by':'original_title',
                      'order_direction':'asc', 'show_original_language':code}
            if state['cursor']:
                params['cursor'] = state['cursor']
            try:
                page = client.get('/shows/search/filters', params)
            except BudgetReached:
                return changed
            if not isinstance(page, dict) or not isinstance(page.get('shows'), list) or not isinstance(page.get('hasMore'), bool):
                raise SyncError('Invalid original-language page')
            cursor = page.get('nextCursor')
            if page['hasMore'] and (not isinstance(cursor, str) or not cursor or cursor in seen):
                raise SyncError('Invalid original-language cursor')
            shows = [{**show, 'originalLanguage':code} for show in page['shows'] if isinstance(show, dict)]
            if len(shows) != len(page['shows']):
                raise SyncError('Invalid original-language show')
            for show in shows:
                normalize(show, mapping, now)
            for show in shows:
                changed += save_show(db, show, mapping, now)
            state = {'cursor':cursor if page['hasMore'] else None,
                     'complete':not page['hasMore'], 'pages':state['pages']+1}
            set_meta(db, key, state)
            set_meta(db, 'original_backfill_next', (task_index + 1) % len(tasks))
            db.commit()
            pages += 1
            seen.add(cursor)
            break  # Share limited pages across languages on successive runs.
    return changed

def backfill_catalog(db, client, mapping, now, max_pages=2):
    """Import older streaming titles gradually, committing each page with its cursor."""
    changed = 0
    pages = 0
    for platform, service in mapping.items():
        for kind in ('movie', 'series'):
            key = 'catalog_backfill_v1:' + service + ':' + kind
            state = get_meta(db, key, {'cursor': None, 'complete': False, 'pages': 0})
            seen = {state['cursor']} if state['cursor'] else set()
            while not state['complete']:
                if pages >= max_pages or getattr(client, 'calls', 0) >= getattr(client, 'run_limit', float('inf')):
                    return changed
                params = {'country': 'in', 'catalogs': service, 'show_type': kind,
                          'series_granularity': 'show', 'order_by': 'original_title', 'order_direction': 'asc'}
                if state['cursor']:
                    params['cursor'] = state['cursor']
                try:
                    page = client.get('/shows/search/filters', params)
                except BudgetReached:
                    return changed
                if not isinstance(page, dict) or not isinstance(page.get('shows'), list) or not isinstance(page.get('hasMore'), bool):
                    raise SyncError('Invalid catalog backfill page')
                cursor = page.get('nextCursor')
                if page['hasMore'] and (not isinstance(cursor, str) or not cursor or cursor in seen):
                    raise SyncError('Invalid catalog backfill cursor')
                for show in page['shows']:
                    normalize(show, mapping, now)
                for show in page['shows']:
                    changed += save_show(db, show, mapping, now)
                state = {'cursor': cursor if page['hasMore'] else None,
                         'complete': not page['hasMore'], 'pages': state['pages'] + 1}
                set_meta(db, key, state)
                db.commit()
                pages += 1
                seen.add(cursor)
    return changed

def catalog_backfill_status(db, mapping):
    tasks = [get_meta(db, 'catalog_backfill_v1:' + service + ':' + kind, {})
             for service in mapping.values() for kind in ('movie', 'series')]
    return {'complete': bool(tasks) and all(task.get('complete') for task in tasks),
            'completedTasks': sum(bool(task.get('complete')) for task in tasks),
            'totalTasks': len(tasks), 'pages': sum(task.get('pages', 0) for task in tasks)}

def sync(db, client, now):
    coverage = get_meta(db, 'coverage')
    if not coverage or now - coverage['checkedAt'] >= DAY:
        mapping = platform_map(client.get('/countries/in'))
        if not mapping:
            raise SyncError('None of the requested services are supported')
        coverage = {'mapping': mapping, 'checkedAt': now, 'missing': [p for p in PLATFORMS if p not in mapping]}
        set_meta(db, 'coverage', coverage)
        db.commit()
    mapping = coverage['mapping']
    started = get_meta(db, 'baseline_started')
    if started is None:
        set_meta(db, 'baseline_started', now)
        started = now
        db.commit()
    changed = 0
    # Baseline is intentionally a small discovery sample. Import one complete page per
    # supported platform and content type. Never claim this is the full OTT catalog.
    baseline_done = get_meta(db, 'baseline_done', [])
    for platform, service_id in mapping.items():
        for kind in ('movie', 'series'):
            task = service_id + ':' + kind
            if task in baseline_done:
                continue
            page = client.get('/shows/search/filters', {'country': 'in', 'catalogs': service_id,
                              'show_type': kind, 'series_granularity': 'show', 'order_by': 'popularity_1month'})
            if not isinstance(page, dict) or not isinstance(page.get('shows'), list):
                raise SyncError('Invalid baseline page')
            for show in page['shows']:
                normalize(show, mapping, now)
            # Validate the whole page before writing any records.
            for show in page['shows']:
                changed += save_show(db, show, mapping, now)
            baseline_done.append(task)
            set_meta(db, 'baseline_done', baseline_done)
            db.commit()
    if not get_meta(db, 'baseline_complete'):
        set_meta(db, 'baseline_complete', now)
        db.commit()
    changed += backfill_recent(db, client, mapping, now)
    # A separate watermark per change type avoids repeating successfully completed work.
    for change_type in ('new', 'updated', 'removed'):
        since = get_meta(db, 'watermark:' + change_type, started)
        if now - since > 30 * DAY:
            raise SyncError('Change history gap exceeds 30 days; a new baseline is required')
        params = {'country': 'in', 'catalogs': ','.join(mapping.values()),
                  'change_type': change_type, 'item_type': 'show',
                  'from': max(since - 60, now - 30 * DAY), 'to': now, 'order_direction': 'asc'}
        # Stage all pages. A failed/truncated query must not advance its watermark.
        staged = {}
        events = []
        for page in read_pages(client, '/changes', params, True):
            if not isinstance(page.get('changes'), list):
                raise SyncError('Invalid changes response')
            for key, show in page['shows'].items():
                normalize(show, mapping, now)
                staged[key] = show
            for event in page['changes']:
                if not isinstance(event, dict) or str(event.get('showId')) not in {str(k) for k in page['shows']}:
                    raise SyncError('Change lacks a current show record; catalog retained')
                events.append(event)
        for show in staged.values():
            changed += save_show(db, show, mapping, now)
        reverse = {v: k for k, v in mapping.items()}
        for event in events:
            if not isinstance(event.get('timestamp'), int) or event['timestamp'] <= get_meta(db, 'baseline_complete', now):
                continue
            service_id = event.get('service', {}).get('id')
            if service_id not in reverse:
                continue
            event_id = json.dumps([event.get('showId'), service_id, change_type, event['timestamp'], event.get('link')])
            db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)',
                       (event_id, 'motn:' + str(event['showId']), reverse[service_id], change_type, event['timestamp']))
        set_meta(db, 'watermark:' + change_type, now)
        db.commit()
    changed += backfill_original_languages(db, client, mapping, now)
    changed += backfill_catalog(db, client, mapping, now)
    set_meta(db, 'last_success', now)
    db.commit()
    return changed

def report(db, now):
    runs = db.execute('SELECT at,status,requests,changed,message FROM runs ORDER BY id').fetchall()
    begin = get_meta(db, 'pilot_started', now)
    month_start = int(datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    coverage = get_meta(db, 'coverage', {})
    catalog = {'totalTitles': 0, 'titlesWithTargetAudio': 0, 'types': {}, 'platforms': {}}
    for raw, in db.execute('SELECT body FROM titles'):
        title = json.loads(raw)
        catalog['totalTitles'] += 1
        catalog['types'][title['type']] = catalog['types'].get(title['type'], 0) + 1
        if any(language in LANGUAGES.values() for offer in title['offers'] for language in offer['audio']):
            catalog['titlesWithTargetAudio'] += 1
        for offer in title['offers']:
            stats = catalog['platforms'].setdefault(offer['platform'], {'offers': 0, 'offersWithTargetAudio': 0, 'unknownAudioOffers': 0, 'audioLanguages': {}})
            stats['offers'] += 1
            stats['offersWithTargetAudio'] += int(any(language in LANGUAGES.values() for language in offer['audio']))
            stats['unknownAudioOffers'] += int(not offer['audio'])
            for language in offer['audio']:
                stats['audioLanguages'][language] = stats['audioLanguages'].get(language, 0) + 1
    return {'generatedAt': stamp(now), 'catalog': catalog, 'pilotStartedAt': stamp(begin),
            'pilotEndsAt': stamp(begin + 30 * DAY), 'scheduleHours': 6,
            'requestsThisMonth': db.execute('SELECT count(*) FROM requests WHERE at>=?', (month_start,)).fetchone()[0],
            'requestsDuringPilot': db.execute('SELECT count(*) FROM requests WHERE at>=?', (begin,)).fetchone()[0],
            'supportedPlatforms': list(coverage.get('mapping', {})), 'missingPlatforms': coverage.get('missing', list(PLATFORMS)),
            'lastSuccessfulUpdate': stamp(get_meta(db, 'last_success')) if get_meta(db, 'last_success') else None,
            'baselineComplete': bool(get_meta(db, 'baseline_complete')),
            'recentHistory': get_meta(db, 'recent_backfill_v1'),
            'catalogScope': 'Initial popular-title sample plus subsequently detected show-level changes; not a full catalog or episode tracker.',
            'runs': [{'at': stamp(r[0]), 'status': r[1], 'requests': r[2], 'changedRecords': r[3], 'message': r[4]} for r in runs],
            'changesByPlatform': {name: db.execute('SELECT count(*) FROM events WHERE platform=?', (name,)).fetchone()[0] for name in PLATFORMS},
            'successfulRunsWithoutChanges': sum(r[1] == 'success' and r[3] == 0 for r in runs)}

def export_catalog(db, path, now):
    if not get_meta(db, 'last_success'):
        return False
    rows = []
    for raw, first_seen, last_checked in db.execute('SELECT body,first_seen,last_checked FROM titles ORDER BY id'):
        title = json.loads(raw)
        if title['id'] in ORIGINAL_LANGUAGE_CORRECTIONS:
            title['originalLanguage'] = ORIGINAL_LANGUAGE_CORRECTIONS[title['id']]
        # Exclude unknown or non-target audio rather than infer dubbing from original language.
        if not any(language in LANGUAGES.values() for offer in title['offers'] for language in offer['audio']):
            continue
        title['firstObservedAt'] = first_seen
        title['lastCheckedAt'] = last_checked
        # Only provider-reported new events qualify, including explicitly fetched history.
        recent = db.execute("SELECT platform,MAX(at) FROM events WHERE title_id=? AND kind='new' AND at>=? AND at<=? GROUP BY platform", (title['id'], now - 7 * DAY, now)).fetchall()
        title['weeklyPlatforms'] = [row[0] for row in recent]
        title['weeklyUpdatedAt'] = max((row[1] for row in recent), default=None)
        title['weekly'] = bool(title['weeklyPlatforms'])
        rows.append(title)
    output = {'schemaVersion': 1, 'mode': 'live', 'updatedAt': stamp(get_meta(db, 'last_success')),
              'scope': 'Gradually expanded streaming catalog plus tracked additions; search covers imported titles.',
              'catalogBackfill': catalog_backfill_status(db, get_meta(db, 'coverage', {}).get('mapping', {})),
              'coverage': report(db, now)['supportedPlatforms'], 'missingPlatforms': report(db, now)['missingPlatforms'],
              'recentHistoryComplete': bool(get_meta(db, 'recent_backfill_v1', {}).get('complete')),
              'source': {'name': 'Streaming Availability API by Movie of the Night', 'url': 'https://www.movieofthenight.com/about/api'},
              'titles': rows}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    temporary.replace(target)
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='.state/catalog.sqlite')
    parser.add_argument('--report', default='reports/pilot.json')
    parser.add_argument('--export', default='data/catalog.json')
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--export-cached', action='store_true', help='Export the last validated streaming snapshot without provider requests')
    args = parser.parse_args()
    db = open_db(args.db)
    now = int(time.time())
    if args.export_cached:
        if not export_catalog(db, args.export, now):
            print('No validated streaming snapshot is cached; run a streaming sync first')
            return 1
        target = Path(args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report(db, now), indent=2))
        print('Exported cached streaming snapshot; no streaming API requests made')
        return 0
    if get_meta(db, 'pilot_started') is None:
        if not args.initialize:
            print('No pilot database restored. Run manually with initialize enabled; scheduled run made no API calls.')
            return 1
        set_meta(db, 'pilot_started', now)
        db.commit()
    if now >= get_meta(db, 'pilot_started') + 30 * DAY:
        status, message, changed, calls = 'complete', '30-day pilot complete; no API calls made', 0, 0
    else:
        key = os.environ.get('STREAMING_API_KEY')
        if not key:
            print('STREAMING_API_KEY is missing. Add it as a GitHub Actions repository secret.')
            return 1
        client = Client(db, key, os.environ.get('STREAMING_API_MODE', 'direct'),
                        int(os.environ.get('MONTHLY_REQUEST_LIMIT', '400')),
                        int(os.environ.get('RUN_REQUEST_LIMIT', '12')))
        try:
            changed = sync(db, client, now)
            status, message = 'success', 'Catalog check completed'
        except BudgetReached as error:
            db.rollback()
            status, message, changed = 'limited', str(error), 0
        except (SyncError, sqlite3.Error) as error:
            db.rollback()
            status, message, changed = 'failed', str(error), 0
        calls = client.calls
    db.execute('INSERT INTO runs(at,status,requests,changed,message) VALUES (?,?,?,?,?)', (now, status, calls, changed, message))
    db.commit()
    result = report(db, now)
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding='utf-8')
    # Only a fully successful run may replace the last public snapshot.
    if status == 'success':
        export_catalog(db, args.export, now)
    print(json.dumps({k: v for k, v in result.items() if k != 'runs'}, indent=2))
    print(f'{status}: {message}; requests this run: {calls}')
    return 0 if status in ('success', 'complete') else 1

if __name__ == '__main__':
    sys.exit(main())
