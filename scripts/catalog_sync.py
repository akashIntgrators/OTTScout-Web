#!/usr/bin/env python3
"""Continuous, quota-bounded India catalog sync. No secrets in exported files."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
try:
    from scripts.official_listings import SERVICES as OFFICIAL_SERVICES, apply_official_listings
    from scripts.official_registry import load_records
except ModuleNotFoundError:
    from official_listings import SERVICES as OFFICIAL_SERVICES, apply_official_listings
    from official_registry import load_records

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
MONTHLY_REQUEST_CAP = 400
RUN_REQUEST_CAP = 12
MAINTENANCE_REQUESTS_PER_DAY = 8
BACKFILL_HEADROOM = 20
CONSERVATION_NEW_REQUESTS_PER_DAY = 2
FRESH_NEW_REQUESTS_PER_DAY = 4
CONSERVATION_CATCHUP_REQUESTS_PER_DAY = 6
CONSERVATION_EMERGENCY_RESERVE = 2
LATEST_NEW_ATTEMPT_KEY = 'latest_new_attempt_v1'
LATEST_NEW_CHECK_KEY = 'latest_new_check_v1'
OFFICIAL_LISTINGS_PATH = Path(__file__).resolve().parents[1] / 'data/official-listings.json'

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
    CREATE TABLE IF NOT EXISTS change_pages (kind TEXT NOT NULL, position INTEGER NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind,position));
    CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, at INTEGER NOT NULL, endpoint TEXT NOT NULL, status INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, at INTEGER NOT NULL, status TEXT NOT NULL, requests INTEGER NOT NULL, changed INTEGER NOT NULL, message TEXT NOT NULL);
    ''')
    return db

def get_meta(db, key, default=None):
    row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default

def set_meta(db, key, value):
    db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

def new_feed_requests_today(db, now):
    day = now // DAY
    counted = get_meta(db, 'new_release_attempts_v2', {})
    if counted.get('utcDay') == day:
        return counted.get('attempts', 0)
    # Before v2, v1 counted new-feed pages but not title searches. Seed the
    # shared allowance from both durable sources; never rewrite the ledger.
    legacy = get_meta(db, 'new_feed_attempts_v1', {})
    pages = legacy.get('attempts', 0) if legacy.get('utcDay') == day else 0
    lookups = db.execute('SELECT count(*) FROM requests WHERE endpoint=? AND at>=? AND at<?',
                         ('/shows/search/title', day*DAY, (day+1)*DAY)).fetchone()[0]
    return pages + lookups

def request_budget(db, now, monthly_limit=MONTHLY_REQUEST_CAP):
    """Only bulk-import the allowance above a reserve for the rest of this UTC month."""
    current = datetime.fromtimestamp(now, timezone.utc)
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year+1, month=1) if start.month == 12 else start.replace(month=start.month+1)
    limit = min(MONTHLY_REQUEST_CAP, max(0, monthly_limit))
    used = db.execute('SELECT count(*) FROM requests WHERE at>=?', (int(start.timestamp()),)).fetchone()[0]
    remaining = max(0, limit-used)
    days_left = (int(end.timestamp())-now+DAY-1)//DAY
    reserve = days_left*MAINTENANCE_REQUESTS_PER_DAY + BACKFILL_HEADROOM
    conserving = remaining <= reserve
    new_attempts = new_feed_requests_today(db, now)
    future_days = max(0, (end.date()-current.date()).days-1)
    # Include today's consumed fresh allowance when selecting the day's plan:
    # spending one request must not downgrade the reserve and unlock another
    # tier's allowance on a manual rerun.
    planning_remaining = remaining + new_attempts
    emergency = CONSERVATION_EMERGENCY_RESERVE if future_days else 0
    if planning_remaining >= future_days*FRESH_NEW_REQUESTS_PER_DAY + emergency + 1:
        planned, daily_limit = FRESH_NEW_REQUESTS_PER_DAY, CONSERVATION_CATCHUP_REQUESTS_PER_DAY
        protected = future_days*planned + emergency
    elif planning_remaining >= future_days*CONSERVATION_NEW_REQUESTS_PER_DAY + emergency + 1:
        planned, daily_limit = CONSERVATION_NEW_REQUESTS_PER_DAY, CONSERVATION_CATCHUP_REQUESTS_PER_DAY
        protected = future_days*planned + emergency
    elif planning_remaining >= future_days + emergency + 1:
        planned, daily_limit = 1, CONSERVATION_NEW_REQUESTS_PER_DAY
        protected = future_days + emergency
    else:
        planned, daily_limit = 0, 1
        emergency = min(1, remaining) if future_days else 0
        protected = max(emergency, remaining-1)
    available = max(0, min(daily_limit-new_attempts, remaining-protected))
    interval = 6*3600 if planned >= 4 else 12*3600 if planned >= 2 else DAY
    attempted = get_meta(db, LATEST_NEW_ATTEMPT_KEY)
    current_head_known = (isinstance(attempted, dict) and type(attempted.get('at')) is int
                          and 0 < attempted['at'] <= now and attempted['at']//interval == now//interval)
    future_head_slots = DAY//interval - (now % DAY)//interval - 1 if conserving and current_head_known else 0
    reserved_heads = min(available, future_head_slots)
    backlog = bool(get_meta(db, 'change_window_v2:new'))
    return {'monthlyLimit': limit, 'requestsUsed': used, 'requestsRemaining': remaining,
            'freshnessReserve': reserve, 'backfillAvailable': 0 if backlog else max(0, remaining-reserve),
            'headroom': BACKFILL_HEADROOM, 'maintenanceRequestsPerDay': MAINTENANCE_REQUESTS_PER_DAY,
            'conservationMode': conserving, 'newFeedDailyLimit': daily_limit if conserving else None,
            'newFeedRequestsToday': new_attempts,
            'newFeedRequestsRemainingToday': available if conserving else None,
            'protectedFutureDays': future_days, 'protectedFutureDailyTarget': FRESH_NEW_REQUESTS_PER_DAY,
            'plannedPerFutureDay': planned, 'protectedFutureRequests': protected,
            'emergencyReserve': emergency, 'catchupDailyLimit': CONSERVATION_CATCHUP_REQUESTS_PER_DAY,
            'capacityInsufficient': conserving and planned < FRESH_NEW_REQUESTS_PER_DAY,
            'freshRequestsAvailableToday': available if conserving else None, 'newFeedBacklog': backlog,
            'futureHeadChecksToday': future_head_slots, 'reservedHeadRequestsToday': reserved_heads,
            'newBacklogRequestsAvailableToday': max(0, available-reserved_heads) if conserving else None}

def new_check_interval(db, now, monthly_limit=MONTHLY_REQUEST_CAP):
    budget = request_budget(db, now, monthly_limit)
    if not budget['conservationMode'] or budget['plannedPerFutureDay'] >= 4:
        return 6*3600
    return 12*3600 if budget['plannedPerFutureDay'] >= 2 else DAY

def change_feed_due(db, kind, now, conservation=False, monthly_limit=MONTHLY_REQUEST_CAP):
    if conservation and (kind != 'new' or request_budget(db, now, monthly_limit)['newFeedRequestsRemainingToday'] <= 0):
        return False
    # Resume interrupted windows immediately; their saved query may be older than
    # the normal cadence. Daily maintenance preserves quota for older titles.
    if get_meta(db, 'change_window_v2:'+kind):
        return True
    watermark = get_meta(db, 'watermark:'+kind)
    interval = new_check_interval(db, now, monthly_limit) if conservation and kind == 'new' else (6*3600 if kind == 'new' else DAY)
    # UTC slots tolerate GitHub scheduling jitter without repeating a manual
    # check in the same slot or accidentally waiting twelve hours for new titles.
    return watermark is None or watermark//interval < now//interval

def streaming_freshness(db, now, conservation=False, monthly_limit=MONTHLY_REQUEST_CAP):
    feeds = {}
    for kind in ('new', 'updated', 'removed'):
        watermark = get_meta(db, 'watermark:'+kind)
        pending = get_meta(db, 'change_window_v2:'+kind)
        feeds[kind] = {'completedThrough': stamp(watermark) if watermark is not None else None,
                       'pendingWindow': {'from':stamp(pending['from']), 'to':stamp(pending['to']), 'pages':pending['pages']} if pending else None,
                       'checkDue': change_feed_due(db, kind, now, conservation, monthly_limit),
                       'deferredByConservation': conservation and (kind != 'new' or request_budget(db, now, monthly_limit)['newFeedRequestsRemainingToday'] <= 0)}
        if kind == 'new':
            feeds[kind].update({'publicationMode': 'incremental-pages',
                               'publishedPages': pending.get('publishedPages', 0) if pending else 0,
                               'stagedPages': db.execute("SELECT count(*) FROM change_pages WHERE kind='new'").fetchone()[0]})
    return feeds

def update_complete_watermark(db):
    watermarks = [get_meta(db, 'watermark:'+kind) for kind in ('new','updated','removed')]
    if all(value is not None for value in watermarks):
        set_meta(db, 'last_success', min(watermarks))

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
    old = db.execute('SELECT body,last_checked FROM titles WHERE id=?', (body['id'],)).fetchone()
    # A resumed feed may contain pages fetched before another feed's snapshot.
    # Validate them above, but never roll back current title/offer evidence.
    if old and now < old[1]:
        return 0
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
        self.monthly_limit = min(MONTHLY_REQUEST_CAP, max(0, monthly_limit))
        self.run_limit, self.calls = min(RUN_REQUEST_CAP, max(0, run_limit)), 0
        self.base = 'https://api.movieofthenight.com/v4' if mode == 'direct' else 'https://streaming-availability.p.rapidapi.com'

    def get(self, endpoint, params=None, *, request_checkpoint=None):
        now = int(time.time())
        budget = request_budget(self.db, now, self.monthly_limit)
        if budget['requestsRemaining'] <= 0 or self.calls >= self.run_limit:
            raise BudgetReached('Configured request limit reached; resume on a later run or adjust budget')
        fresh_request = endpoint == '/shows/search/title' or (endpoint == '/changes' and (params or {}).get('change_type') == 'new')
        if endpoint == '/shows/search/title' and (budget['conservationMode'] or budget['newFeedBacklog']):
            raise BudgetReached('Quota conservation: reported-title lookups deferred behind fresh additions')
        if budget['newFeedBacklog'] and (endpoint == '/shows/search/filters' or (endpoint == '/changes' and not fresh_request)):
            raise BudgetReached('Fresh-addition backlog takes priority; maintenance and older imports deferred')
        if budget['conservationMode'] and (endpoint == '/shows/search/filters' or (endpoint == '/changes' and not fresh_request)):
            raise BudgetReached('Quota conservation: maintenance and older imports deferred')
        if fresh_request and budget['conservationMode'] and budget['newFeedRequestsRemainingToday'] <= 0:
            raise BudgetReached('Quota conservation: protected future allowance or daily limit reached; resume next UTC day')
        if (endpoint == '/changes' and fresh_request and (params or {}).get('order_direction') != 'desc'
                and budget['conservationMode'] and budget['newBacklogRequestsAvailableToday'] <= 0):
            raise BudgetReached('Quota conservation: remaining requests reserved for later newest-first checks today')
        # Count and commit before sending, including network failures and malformed responses.
        row = self.db.execute('INSERT INTO requests(at,endpoint,status) VALUES (?,?,0)', (now, endpoint))
        request_id = row.lastrowid
        if fresh_request:
            # Use the pre-insert budget: the just-inserted title ledger row must
            # not be counted once by migration and again by this increment.
            set_meta(self.db, 'new_release_attempts_v2', {'utcDay':now//DAY, 'attempts':budget['newFeedRequestsToday']+1})
        if request_checkpoint is not None:
            # An internal checkpoint shares the charged-request transaction. A
            # prevented request cannot consume the newest-first scan's slot.
            set_meta(self.db, request_checkpoint[0], request_checkpoint[1])
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
    """Share catalogue pages fairly across platforms and content types, preserving cursors."""
    changed = 0
    pages = 0
    tasks = [(platform,service,kind) for kind in ('movie','series') for platform,service in mapping.items()]
    if not tasks:
        return 0
    start = get_meta(db, 'catalog_backfill_next', 0) % len(tasks)
    for offset in range(len(tasks)):
        task_index = (start + offset) % len(tasks)
        platform, service, kind = tasks[task_index]
        key = 'catalog_backfill_v1:' + service + ':' + kind
        state = get_meta(db, key, {'cursor': None, 'complete': False, 'pages': 0})
        if state['complete']:
            continue
        if pages >= max_pages or getattr(client,'calls',0) >= getattr(client,'run_limit',float('inf')):
            return changed
        params = {'country':'in','catalogs':service,'show_type':kind,'series_granularity':'show',
                  'order_by':'original_title','order_direction':'asc'}
        if state['cursor']:
            params['cursor'] = state['cursor']
        try:
            page = client.get('/shows/search/filters',params)
        except BudgetReached:
            return changed
        if not isinstance(page,dict) or not isinstance(page.get('shows'),list) or not isinstance(page.get('hasMore'),bool):
            raise SyncError('Invalid catalog backfill page')
        cursor = page.get('nextCursor')
        if page['hasMore'] and (not isinstance(cursor,str) or not cursor or cursor == state['cursor']):
            raise SyncError('Invalid catalog backfill cursor')
        for show in page['shows']:
            normalize(show,mapping,now)
        for show in page['shows']:
            changed += save_show(db,show,mapping,now)
        state = {'cursor':cursor if page['hasMore'] else None,'complete':not page['hasMore'],'pages':state['pages']+1}
        set_meta(db,key,state)
        set_meta(db,'catalog_backfill_next',(task_index+1)%len(tasks))
        db.commit()
        pages += 1
    return changed

def catalog_backfill_status(db, mapping):
    tasks = [get_meta(db, 'catalog_backfill_v1:' + service + ':' + kind, {})
             for service in mapping.values() for kind in ('movie', 'series')]
    return {'complete': bool(tasks) and all(task.get('complete') for task in tasks),
            'completedTasks': sum(bool(task.get('complete')) for task in tasks),
            'totalTasks': len(tasks), 'pages': sum(task.get('pages', 0) for task in tasks),
            'platforms': {platform:{kind:get_meta(db,'catalog_backfill_v1:'+service+':'+kind,{'pages':0,'complete':False})['pages'] for kind in ('movie','series')} for platform,service in mapping.items()}}

def validate_change_page(page, mapping, state, checked_at):
    if not isinstance(page, dict) or not isinstance(page.get('hasMore'), bool) or not isinstance(page.get('shows'), dict) or not isinstance(page.get('changes'), list):
        raise SyncError('Invalid changes response')
    for ident, item in page['shows'].items():
        body = normalize(item, mapping, checked_at)
        if body['id'] != 'motn:'+str(ident):
            raise SyncError('Change show identity does not match its record')
    for event in page['changes']:
        if not isinstance(event, dict) or str(event.get('showId')) not in {str(k) for k in page['shows']}:
            raise SyncError('Change lacks a current show record; catalog retained')
        if isinstance(event.get('timestamp'), bool) or not isinstance(event.get('timestamp'), int) or not state['from'] <= event['timestamp'] <= state['to']:
            raise SyncError('Change has invalid event date; catalog retained')
        if not isinstance(event.get('service', {}), dict):
            raise SyncError('Change has invalid service evidence')


def apply_change_page(db, page, mapping, kind, checked_at, *, include_history=False):
    changed = sum(save_show(db, item, mapping, checked_at) for item in page['shows'].values())
    reverse = {v:k for k,v in mapping.items()}
    for event in page['changes']:
        service = event.get('service', {}).get('id')
        if (not include_history and event['timestamp'] <= get_meta(db, 'baseline_complete', checked_at)) or service not in reverse:
            continue
        event_id = json.dumps([event.get('showId'), service, kind, event['timestamp'], event.get('link')])
        db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)',
                   (event_id, 'motn:'+str(event['showId']), reverse[service], kind, event['timestamp']))
    return changed


def new_publication(db):
    return get_meta(db, 'new_publication_v1', {'pages':0, 'changedRecords':0, 'recoveredPages':0, 'latestPublishedAt':None})


def record_new_publication(db, now, pages, changed, recovered=False):
    previous = new_publication(db)
    set_meta(db, 'new_publication_v1', {'pages':previous['pages']+pages,
             'changedRecords':previous['changedRecords']+changed,
             'recoveredPages':previous['recoveredPages']+(pages if recovered else 0),
             'latestPublishedAt':now})


def latest_new_due(db, now, monthly_limit=MONTHLY_REQUEST_CAP):
    budget = request_budget(db, now, monthly_limit)
    if budget['requestsRemaining'] <= 0 or (budget['conservationMode'] and budget['newFeedRequestsRemainingToday'] <= 0):
        return False
    attempted = get_meta(db, LATEST_NEW_ATTEMPT_KEY)
    if attempted is not None and (not isinstance(attempted, dict) or type(attempted.get('at')) is not int or not 0 < attempted['at'] <= now):
        raise SyncError('Invalid newest-first request checkpoint')
    # A deployment that already completed this slot needs no duplicate first
    # head request. Once enabled, the independent attempt checkpoint owns cadence.
    previous = attempted['at'] if attempted is not None else get_meta(db, 'watermark:new')
    interval = new_check_interval(db, now, monthly_limit)
    return previous is None or previous//interval < now//interval


def sync_latest_new(db, client, mapping, now):
    """One newest-first public-catalogue page; never advances complete-feed state."""
    monthly_limit = getattr(client, 'monthly_limit', MONTHLY_REQUEST_CAP)
    if not latest_new_due(db, now, monthly_limit) or getattr(client, 'calls', 0) >= getattr(client, 'run_limit', RUN_REQUEST_CAP):
        return 0
    window = {'from':now-2*DAY, 'to':now}
    params = {'country':'in', 'catalogs':','.join(mapping.values()), 'change_type':'new',
              'item_type':'show', 'from':window['from'], 'to':now, 'order_direction':'desc'}
    checkpoint = (LATEST_NEW_ATTEMPT_KEY, {'at':now})
    if isinstance(client, Client):
        page = client.get('/changes', params, request_checkpoint=checkpoint)
    else:
        # Offline injected clients retain the existing interface. Real provider
        # attempts use Client's pre-I/O durable ledger/checkpoint transaction.
        try:
            page = client.get('/changes', params)
        except BudgetReached:
            raise
        except SyncError:
            set_meta(db, *checkpoint); db.commit()
            raise
        set_meta(db, *checkpoint); db.commit()
    validate_change_page(page, mapping, window, now)
    dates = [event['timestamp'] for event in page['changes']]
    if len(dates) > 25 or dates != sorted(dates, reverse=True):
        raise SyncError('Invalid newest-first event ordering or page size')
    if page['hasMore'] and (not isinstance(page.get('nextCursor'), str) or not page['nextCursor']):
        raise SyncError('Missing newest-first continuation evidence')
    scan = {'checkedAt':stamp(now), 'from':stamp(window['from']), 'to':stamp(now),
            'hasMore':page['hasMore'], 'events':len(dates),
            'oldestEventAt':stamp(min(dates)) if dates else None, 'newestEventAt':stamp(max(dates)) if dates else None,
            'order':'desc', 'pages':1, 'scope':'last48h'}
    db.execute('SAVEPOINT publish_latest_new')
    try:
        changed = apply_change_page(db, page, mapping, 'new', now, include_history=True)
        set_meta(db, LATEST_NEW_CHECK_KEY, scan)
        record_new_publication(db, now, 1, changed)
        db.execute('RELEASE publish_latest_new'); db.commit()
        return changed
    except Exception:
        db.execute('ROLLBACK TO publish_latest_new'); db.execute('RELEASE publish_latest_new')
        raise


def flush_staged_new_pages(db, now):
    """Publish already-paid legacy pages without a request or a completed-window claim."""
    rows = db.execute("SELECT position,body FROM change_pages WHERE kind='new' ORDER BY position").fetchall()
    if not rows:
        return 0
    state = get_meta(db, 'change_window_v2:new')
    if not state:
        raise SyncError('Staged new pages lack their saved query; review before recovery')
    mapping = state.get('mapping', get_meta(db, 'coverage', {}).get('mapping', {}))
    published = state.get('publishedPages', 0)
    if [position for position, _ in rows] != list(range(published, published+len(rows))) or published+len(rows) != state['pages']:
        raise SyncError('Staged new-page positions do not match the saved query')
    saved_pages = []
    for _, raw in rows:
        try:
            saved = json.loads(raw)
            checked_at = saved['checkedAt']
            if isinstance(checked_at, bool) or not isinstance(checked_at, int) or not 0 < checked_at <= now:
                raise SyncError('Invalid staged new-page check time')
            validate_change_page(saved['page'], mapping, state, checked_at)
        except (KeyError, TypeError, ValueError) as error:
            raise SyncError('Invalid staged new-page cache; catalog retained') from error
        saved_pages.append(saved)
    db.execute('SAVEPOINT publish_staged_new')
    try:
        changed = sum(apply_change_page(db, saved['page'], mapping, 'new', saved['checkedAt']) for saved in saved_pages)
        set_meta(db, 'change_window_v2:new', {**state, 'publishedPages':published+len(rows)})
        db.execute("DELETE FROM change_pages WHERE kind='new'")
        record_new_publication(db, now, len(rows), changed, recovered=True)
        db.execute('RELEASE publish_staged_new')
        db.commit()
        return changed
    except Exception:
        db.execute('ROLLBACK TO publish_staged_new')
        db.execute('RELEASE publish_staged_new')
        raise


def sync_change_feed(db, client, mapping, kind, started, now):
    """Publish NEW pages atomically as they arrive; maintenance retains whole-window staging."""
    changed = flush_staged_new_pages(db, now) if kind == 'new' else 0
    key = 'change_window_v2:' + kind
    state = get_meta(db, key)
    if not state:
        since = get_meta(db, 'watermark:' + kind, started)
        if now - since > 30 * DAY:
            raise SyncError('Change history gap exceeds 30 days; a new baseline is required')
        state = {'from':max(since-60, now-30*DAY), 'to':now, 'cursor':None, 'seen':[], 'pages':0, 'mapping':dict(mapping)}
        if kind == 'new': state['publishedPages'] = 0
        db.execute('DELETE FROM change_pages WHERE kind=?', (kind,))
        set_meta(db, key, state)
        db.commit()
    if now - state['from'] > 30 * DAY:
        raise SyncError('Saved change query expired; review before starting a new baseline')
    mapping = state.get('mapping', mapping)
    while True:
        budget = request_budget(db, now, getattr(client, 'monthly_limit', MONTHLY_REQUEST_CAP))
        if (kind == 'new' and budget['conservationMode'] and budget['newBacklogRequestsAvailableToday'] <= 0
                and budget['reservedHeadRequestsToday'] > 0):
            return changed
        params = {'country':'in', 'catalogs':','.join(mapping.values()), 'change_type':kind,
                  'item_type':'show', 'from':state['from'], 'to':state['to'], 'order_direction':'asc'}
        if state['cursor']:
            params['cursor'] = state['cursor']
        page = client.get('/changes', params)
        validate_change_page(page, mapping, state, now)
        cursor = page.get('nextCursor')
        if page['hasMore'] and (not isinstance(cursor, str) or not cursor or cursor == state['cursor'] or cursor in state['seen']):
            raise SyncError('Missing or repeated changes cursor')
        next_state = {**state, 'cursor':cursor if page['hasMore'] else None,
                      'seen':state['seen'] + ([cursor] if page['hasMore'] else []), 'pages':state['pages']+1}
        db.execute('SAVEPOINT publish_change_page')
        try:
            if kind == 'new':
                page_changed = apply_change_page(db, page, mapping, kind, now)
                changed += page_changed
                next_state['publishedPages'] = next_state['pages']
                record_new_publication(db, now, 1, page_changed)
            else:
                db.execute('INSERT INTO change_pages VALUES (?,?,?)', (kind, state['pages'], json.dumps({'page':page,'checkedAt':now})))
            set_meta(db, key, next_state)
            if not page['hasMore']:
                if kind != 'new':
                    for raw, in db.execute('SELECT body FROM change_pages WHERE kind=? ORDER BY position', (kind,)).fetchall():
                        saved = json.loads(raw)
                        changed += apply_change_page(db, saved['page'], mapping, kind, saved['checkedAt'])
                set_meta(db, 'watermark:' + kind, next_state['to'])
                update_complete_watermark(db)
                set_meta(db, key, None)
                db.execute('DELETE FROM change_pages WHERE kind=?', (kind,))
            db.execute('RELEASE publish_change_page')
            db.commit()
        except Exception:
            db.execute('ROLLBACK TO publish_change_page')
            db.execute('RELEASE publish_change_page')
            raise
        state = next_state
        if not page['hasMore']:
            return changed

def sync(db, client, now, recheck_reports=False):
    def conserving():
        return request_budget(db, now, getattr(client, 'monthly_limit', MONTHLY_REQUEST_CAP))['conservationMode']
    changed = flush_staged_new_pages(db, now)
    coverage = get_meta(db, 'coverage')
    # Resume the frozen NEW query first with its already-validated mapping;
    # optional coverage refreshes must never spend scarce head-check capacity.
    # Existing authenticated coverage remains usable throughout conservation.
    pending_new = get_meta(db, 'change_window_v2:new')
    if not coverage or (not conserving() and not pending_new and now - coverage['checkedAt'] >= DAY):
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
    changed += sync_latest_new(db, client, mapping, now)
    # Large change feeds resume from committed pages under the same request caps.
    # New releases must never wait behind an arbitrarily large maintenance feed.
    change_types = ['new'] + sorted(('updated', 'removed'),
                                   key=lambda kind: not bool(get_meta(db, 'change_window_v2:'+kind)))
    for change_type in change_types:
        while change_feed_due(db, change_type, now, conserving(), getattr(client, 'monthly_limit', MONTHLY_REQUEST_CAP)):
            previous_watermark = get_meta(db, 'watermark:'+change_type)
            changed += sync_change_feed(db, client, mapping, change_type, started, now)
            watermark = get_meta(db, 'watermark:'+change_type)
            # Completing yesterday's frozen query must not postpone today's
            # additions. Continue only after real progress; request caps remain
            # enforced by Client before every additional page.
            if change_type != 'new' or watermark is None or (previous_watermark is not None and watermark <= previous_watermark):
                break
        if change_type == 'new' and recheck_reports and not conserving() and not get_meta(db, 'change_window_v2:new'):
            # Optional lookups never spend scarce or active-backlog capacity.
            changed += recheck_reported_titles(db, client, now)
    if not conserving() and not get_meta(db, 'change_window_v2:new'):
        changed += backfill_recent(db, client, mapping, now)
    budget = request_budget(db, now, getattr(client, 'monthly_limit', MONTHLY_REQUEST_CAP))
    pages = min(budget['backfillAvailable'], max(0, min(6, int(os.environ.get('CATALOG_BACKFILL_PAGES', '6')))))
    changed += backfill_catalog(db, client, mapping, now, max_pages=pages)
    # TMDB supplies original language without consuming streaming requests. Keep
    # the legacy streaming-language cursors, but make these extra scans opt-in.
    budget = request_budget(db, now, getattr(client, 'monthly_limit', MONTHLY_REQUEST_CAP))
    original_pages = min(budget['backfillAvailable'], max(0, min(2, int(os.environ.get('ORIGINAL_LANGUAGE_BACKFILL_PAGES', '0')))))
    changed += backfill_original_languages(db, client, mapping, now, max_pages=original_pages)
    # A resumed feed covers its original frozen window, not the resume time.
    update_complete_watermark(db)
    db.commit()
    return changed

def report(db, now):
    runs = db.execute('SELECT at,status,requests,changed,message FROM runs ORDER BY id').fetchall()
    begin = get_meta(db, 'pilot_started', now)
    budget = request_budget(db, now, int(os.environ.get('MONTHLY_REQUEST_LIMIT', str(MONTHLY_REQUEST_CAP))))
    coverage = get_meta(db, 'coverage', {})
    catalog = {'totalTitles': 0, 'titlesWithTargetAudio': 0, 'titlesWithUnknownAudio':0, 'titlesWithoutOffers':0, 'titlesNotCheckedFor7Days':0, 'types': {}, 'platforms': {}}
    for raw, checked in db.execute('SELECT body,last_checked FROM titles'):
        title = json.loads(raw)
        catalog['titlesWithUnknownAudio'] += int(any(not o['audio'] for o in title['offers']))
        catalog['titlesWithoutOffers'] += int(not title['offers'])
        catalog['titlesNotCheckedFor7Days'] += int(now-checked>7*DAY)
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
    rechecks=[json.loads(r[0]) for r in db.execute("SELECT value FROM meta WHERE key LIKE 'title_recheck:%'")]
    return {'generatedAt': stamp(now), 'catalog': catalog, 'titleRechecks':rechecks, 'pilotStartedAt': stamp(begin),
            'pilotEndsAt': None, 'collectorMode': 'continuous', 'scheduleHours': 6, 'maintenanceHours': 24,
            'requestBudget': budget, 'requestsThisMonth': budget['requestsUsed'],
            'newCheckHours': (6 if budget['plannedPerFutureDay'] >= 4 else 12 if budget['plannedPerFutureDay'] >= 2 else 24) if budget['conservationMode'] else 6,
            'streamingFreshness': streaming_freshness(db, now, budget['conservationMode'], budget['monthlyLimit']),
            'newPublication': new_publication(db),
            'latestNewCheck': get_meta(db, LATEST_NEW_CHECK_KEY),
            'requestsDuringPilot': db.execute('SELECT count(*) FROM requests WHERE at>=?', (begin,)).fetchone()[0],
            'supportedPlatforms': list(coverage.get('mapping', {})), 'missingPlatforms': coverage.get('missing', list(PLATFORMS)),
            'lastSuccessfulUpdate': stamp(get_meta(db, 'last_success')) if get_meta(db, 'last_success') else None,
            'baselineComplete': bool(get_meta(db, 'baseline_complete')),
            'recentHistory': get_meta(db, 'recent_backfill_v1'),
            'pendingChangeQueries': {kind: get_meta(db, 'change_window_v2:'+kind) for kind in ('new','updated','removed') if get_meta(db, 'change_window_v2:'+kind)},
            'catalogScope': 'Gradually imported platform catalogues plus tracked additions; coverage is still partial and not an episode tracker.',
            'catalogBackfill': catalog_backfill_status(db,coverage.get('mapping',{})),
            'runs': [{'at': stamp(r[0]), 'status': r[1], 'requests': r[2], 'changedRecords': r[3], 'message': r[4]} for r in runs],
            'changesByPlatform': {name: db.execute('SELECT count(*) FROM events WHERE platform=?', (name,)).fetchone()[0] for name in PLATFORMS},
            'successfulRunsWithoutChanges': sum(r[1] == 'success' and r[3] == 0 for r in runs)}

def supplement_reported_audio(title, records, now):
    """Use a dated official Netflix listing only when provider audio is missing."""
    for row in records:
        ident=row.get('netflixId');source=urlparse(row.get('sourceURL',''))
        checked=row.get('checkedAt');audio=row.get('audio')
        if (not isinstance(ident,str) or not ident.isdigit() or source.scheme!='https'
            or source.hostname!='www.netflix.com' or source.path!='/in/title/'+ident
            or type(checked) is not int or not now-30*DAY<=checked<=now
            or not isinstance(audio,list) or not audio or not all(x in LANGUAGES.values() for x in audio)):continue
        for offer in title['offers']:
            url=urlparse(offer.get('link') or '')
            if offer['platform']=='Netflix' and url.hostname in ('netflix.com','www.netflix.com') and url.path.rstrip('/').split('/')[-1]==ident and not offer['audio']:
                offer['audio']=list(dict.fromkeys(audio));offer['audioSource']=row['sourceURL'];offer['audioCheckedAt']=checked
    return title

def export_catalog(db, path, now):
    flush_staged_new_pages(db, now)
    if not get_meta(db, 'last_success'):
        return False
    rows = []
    correction_path=Path(__file__).resolve().parents[1]/'data/title-rechecks.json'
    corrections=json.loads(correction_path.read_text()) if correction_path.exists() else []
    for raw, first_seen, last_checked in db.execute('SELECT body,first_seen,last_checked FROM titles ORDER BY id'):
        title = supplement_reported_audio(json.loads(raw),corrections,now)
        for correction in corrections:
            if title['title'].casefold()==correction['title'].casefold():
                print('Reported title export: '+json.dumps({'title':title['title'],'offers':[{'platform':o['platform'],'audio':o['audio'],'availableSince':o.get('availableSince')} for o in title['offers']]}))
        if title['id'] in ORIGINAL_LANGUAGE_CORRECTIONS:
            title['originalLanguage'] = ORIGINAL_LANGUAGE_CORRECTIONS[title['id']]
        # Missing audio is incomplete metadata, not proof that an India offer is unavailable.
        # Known non-target audio stays out of this six-language catalogue.
        if not title['offers'] or not any(not offer['audio'] or any(language in LANGUAGES.values() for language in offer['audio']) for offer in title['offers']):
            continue
        title['firstObservedAt'] = first_seen
        title['lastCheckedAt'] = last_checked
        for offer in title['offers']:
            offer['availabilitySource']='Streaming Availability API by Movie of the Night'
            offer['availabilityCheckedAt']=last_checked
            offer.setdefault('audioSource','Streaming Availability API by Movie of the Night')
            offer.setdefault('audioCheckedAt',last_checked)
            offer['audioStatus']='reported' if offer['audio'] else 'unverified'
        # Only provider-reported new events qualify, including explicitly fetched history.
        recent = db.execute("SELECT platform,MAX(at) FROM events WHERE title_id=? AND kind='new' AND at>=? AND at<=? GROUP BY platform", (title['id'], now - 7 * DAY, now)).fetchall()
        title['weeklyPlatforms'] = [row[0] for row in recent]
        title['weeklyEvents'] = [{'platform': row[0], 'addedAt': row[1]} for row in recent]
        title['weeklyUpdatedAt'] = max((row[1] for row in recent), default=None)
        title['weekly'] = bool(title['weeklyPlatforms'])
        rows.append(title)
    latest_run = db.execute('SELECT status FROM runs ORDER BY id DESC LIMIT 1').fetchone()
    budget = request_budget(db, now, int(os.environ.get('MONTHLY_REQUEST_LIMIT', str(MONTHLY_REQUEST_CAP))))
    output = {'schemaVersion': 1, 'mode': 'live', 'updatedAt': stamp(get_meta(db, 'last_success')),
              'requestBudget': budget,
              'streamingFreshness': streaming_freshness(db, now, budget['conservationMode'], budget['monthlyLimit']),
              'newPublication': new_publication(db),
              'latestNewCheck': get_meta(db, LATEST_NEW_CHECK_KEY),
              'syncStatus': latest_run[0] if latest_run else 'unknown',
              'scope': 'Gradually expanded streaming catalog plus tracked additions; search covers imported titles.',
              'catalogBackfill': catalog_backfill_status(db, get_meta(db, 'coverage', {}).get('mapping', {})),
              'coverage': report(db, now)['supportedPlatforms'], 'missingPlatforms': report(db, now)['missingPlatforms'],
              'recentHistoryComplete': bool(get_meta(db, 'recent_backfill_v1', {}).get('complete')),
              'source': {'name': 'Streaming Availability API by Movie of the Night', 'url': 'https://www.movieofthenight.com/about/api'},
              'titles': rows}
    official_aliases = get_meta(db, 'official_listing_aliases_v1', {})
    discovered_path = OFFICIAL_LISTINGS_PATH.with_name('official-discovered.json')
    if OFFICIAL_LISTINGS_PATH.exists() or discovered_path.exists() or official_aliases:
        # Identity bindings survive evidence expiry and temporary disappearance
        # of a provider offer, without rewriting provider-owned title rows.
        output['officialListingAliases'] = official_aliases
        records = load_records(OFFICIAL_LISTINGS_PATH.parent.parent, output,
                               curated_path=OFFICIAL_LISTINGS_PATH, discovered_path=discovered_path, now=now)
        targets = {(r.get('id'), r.get('platform')) for r in records if isinstance(r, dict)
                   and isinstance(r.get('id'), str) and isinstance(r.get('platform'), str)} if isinstance(records, list) else set()
        if isinstance(official_aliases, dict):
            for key, ident in official_aliases.items():
                for platform, service in OFFICIAL_SERVICES.items():
                    if key.startswith(service + ':'):
                        targets.add((ident, platform))
        removals = {}
        for ident, platform, removed in db.execute("SELECT title_id,platform,MAX(at) FROM events WHERE kind='removed' AND at<=? GROUP BY title_id,platform", (now,)):
            canonical = official_aliases.get(ident, ident) if isinstance(official_aliases, dict) else ident
            if (canonical, platform) in targets:
                removals[canonical, platform] = max(removed, removals.get((canonical, platform), 0))
        output['officialListingRemovals'] = [{'id': ident, 'platform': platform, 'removedAt': removed}
                                            for (ident, platform), removed in sorted(removals.items())]
        output, _ = apply_official_listings(output, records, now)
        set_meta(db, 'official_listing_aliases_v1', output['officialListingAliases'])
        db.commit()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    temporary.replace(target)
    return True

def official_platform_title_id(value, platform, show_type):
    if not isinstance(value,str): return None
    try:
        url=urlparse(value)
        if url.scheme!='https' or url.username or url.password or url.port not in (None,443): return None
        parts=url.path.strip('/').split('/')
        if platform=='Netflix' and url.hostname in ('netflix.com','www.netflix.com'):
            if len(parts)==2 and parts[0] in ('title','watch'): ident=parts[1]
            elif len(parts)==3 and parts[:2] in (['in','title'],['in','watch']): ident=parts[2]
            else:return None
        elif platform=='JioHotstar' and url.hostname in ('hotstar.com','www.hotstar.com'):
            if parts[-1:] == ['watch']: parts=parts[:-1]
            category='shows' if show_type=='series' else 'movies'
            if len(parts)!=4 or parts[:2]!=['in',category] or not parts[2] or parts[2] in ('.','..'):return None
            ident=parts[3]
        else:return None
        return ident if ident.isascii() and ident.isdigit() else None
    except ValueError:
        return None

def reported_title_identity(row):
    if not isinstance(row,dict) or not isinstance(row.get('title'),str) or not row['title'].strip():
        raise SyncError('Invalid reported title lookup')
    legacy='netflixId' in row and 'platform' not in row and 'platformTitleId' not in row
    platform='Netflix' if legacy else row.get('platform')
    show_type='movie' if legacy else row.get('showType')
    ident=row.get('netflixId') if legacy else row.get('platformTitleId')
    if platform not in ('Netflix','JioHotstar') or show_type not in ('movie','series') or not isinstance(ident,str) or not ident.isascii() or not ident.isdigit():
        raise SyncError('Invalid reported title lookup')
    if not legacy:
        if not isinstance(row.get('sourceURL'),str):
            raise SyncError('Invalid reported title source')
        source=urlparse(row['sourceURL'])
        if source.query or source.fragment or official_platform_title_id(row.get('sourceURL'),platform,show_type)!=ident:
            raise SyncError('Reported title source does not match its official platform identity')
    return platform,show_type,ident

def recheck_reported_titles(db, client, now, records=None):
    """One bounded title lookup per day for unresolved reports; require exact provider identity."""
    budget = request_budget(db, now, getattr(client, 'monthly_limit', MONTHLY_REQUEST_CAP))
    if budget['conservationMode'] or budget['newFeedBacklog']:
        return 0
    attempted = get_meta(db, 'title_recheck_last_attempt')
    if attempted is not None and attempted//DAY >= now//DAY:
        return 0
    if records is None:
        path = Path(__file__).resolve().parents[1] / 'data/title-rechecks.json'
        records = json.loads(path.read_text()) if path.exists() else []
    mapping = get_meta(db, 'coverage', {}).get('mapping', {})
    if not mapping: return 0
    conservation=request_budget(db,now,getattr(client,'monthly_limit',MONTHLY_REQUEST_CAP))['conservationMode']
    cooldown=7*DAY if conservation else DAY
    for row in records:
        platform,show_type,ident=reported_title_identity(row)
        if platform not in mapping:continue
        service='netflix' if platform=='Netflix' else 'hotstar'
        key='title_recheck:'+service+':'+ident
        state=get_meta(db,key,{})
        if state.get('resolved') or now-state.get('checkedAt',0)<cooldown: continue
        try:
            results=client.get('/shows/search/title',{'title':row['title'],'country':'in','show_type':show_type,'series_granularity':'show'})
        except BudgetReached:
            raise
        except SyncError:
            set_meta(db, 'title_recheck_last_attempt', now)
            set_meta(db,key,{'checkedAt':now,'resolved':False,'title':row['title'],'status':'lookup_failed'})
            db.commit()
            return 0
        set_meta(db, 'title_recheck_last_attempt', now)
        # Persist the failed/unverified attempt before validating the response;
        # malformed or ambiguous matches must also respect the cooldown.
        set_meta(db,key,{'checkedAt':now,'resolved':False,'title':row['title'],'status':'lookup_failed'})
        db.commit()
        matches=[]
        try:
            if not isinstance(results,list): raise SyncError('Invalid title search response')
            for show in results:
                body=normalize(show,mapping,now)
                if body['type'] != {'movie':'Movie','series':'Series'}[show_type]:continue
                for offer in body['offers']:
                    if offer['platform']==platform and official_platform_title_id(offer.get('link'),platform,show_type)==ident:
                        matches.append((show,body));break
            if len(matches)>1: raise SyncError('Ambiguous provider identity in title search')
        except (SyncError, TypeError, AttributeError, ValueError):
            # Optional reported-title work cannot invalidate an already completed
            # new feed. No unverified result is saved; the failed-attempt cooldown remains.
            return 0
        changed=0
        if matches:
            show,body=matches[0];changed=save_show(db,show,mapping,now)
            for offer in body['offers']:
                added=offer.get('availableSince')
                if offer['platform']==platform and official_platform_title_id(offer.get('link'),platform,show_type)==ident and type(added) is int and now-7*DAY<=added<=now:
                    event=json.dumps(['title-recheck',body['id'],platform,added])
                    db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?,?)',(event,body['id'],platform,'new',added))
        set_meta(db,key,{'checkedAt':now,'resolved':bool(matches),'title':row['title'],'matches':len(matches)})
        db.commit()
        print('Reported title recheck: '+row['title']+' — '+('imported exact '+platform+' match' if matches else 'provider has no matching '+platform+' India offer'))
        return changed
    return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='.state/catalog.sqlite')
    parser.add_argument('--report', default='reports/pilot.json')
    parser.add_argument('--export', default='data/catalog.json')
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--export-cached', action='store_true', help='Export the last validated streaming snapshot without provider requests')
    parser.add_argument('--allow-cached-on-limit', action='store_true', help='Allow metadata/site updates from cached data when the streaming request cap is reached')
    args = parser.parse_args()
    db = open_db(args.db)
    now = int(time.time())
    publication_before = new_publication(db)['changedRecords']
    recovered = flush_staged_new_pages(db, now)
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
    key = os.environ.get('STREAMING_API_KEY')
    if not key:
        print('STREAMING_API_KEY is missing. Add it as a GitHub Actions repository secret.')
        return 1
    client = Client(db, key, os.environ.get('STREAMING_API_MODE', 'direct'),
                    int(os.environ.get('MONTHLY_REQUEST_LIMIT', '400')),
                    int(os.environ.get('RUN_REQUEST_LIMIT', '12')))
    try:
        changed = recovered + sync(db, client, now, recheck_reports=True)
        if request_budget(db, now, client.monthly_limit)['conservationMode']:
            status, message = 'limited', 'Quota conservation: validated new pages published incrementally within adaptive daily/future reserves; maintenance, reported lookups and older imports deferred'
        else:
            status, message = 'success', 'Catalog check completed'
    except BudgetReached as error:
        db.rollback()
        status, message, changed = 'limited', str(error), new_publication(db)['changedRecords']-publication_before
    except (SyncError, sqlite3.Error) as error:
        db.rollback()
        status, message, changed = 'failed', str(error), new_publication(db)['changedRecords']-publication_before
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
    cached_on_limit = status == 'limited' and args.allow_cached_on_limit and export_catalog(db, args.export, now)
    print(json.dumps({k: v for k, v in result.items() if k != 'runs'}, indent=2))
    print(f'{status}: {message}; requests this run: {calls}')
    return 0 if status == 'success' or cached_on_limit else 1

if __name__ == '__main__':
    sys.exit(main())
