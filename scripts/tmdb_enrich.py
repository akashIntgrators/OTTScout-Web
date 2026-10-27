#!/usr/bin/env python3
"""Bounded, cached TMDB metadata enrichment. Secrets never enter public files."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DAY = 86400
LANGUAGES = {'en':'English','hi':'Hindi','te':'Telugu','ta':'Tamil','kn':'Kannada','ml':'Malayalam'}

class TMDBError(Exception):
    pass

class BudgetReached(TMDBError):
    pass

class Client:
    def __init__(self, token, limit=300):
        self.token, self.limit, self.calls = token, limit, 0
    def get(self, endpoint, params=None):
        if self.calls >= self.limit:
            raise BudgetReached('TMDB batch limit reached')
        self.calls += 1
        request = Request('https://api.themoviedb.org/3' + endpoint + ('?' + urlencode(params) if params else ''),
                          headers={'Authorization':'Bearer ' + self.token, 'Accept':'application/json'})
        try:
            time.sleep(0.12)
            with urlopen(request, timeout=30) as response:
                result = json.load(response)
            if not isinstance(result, dict):
                raise TMDBError('Invalid TMDB response')
            return result
        except HTTPError as error:
            if error.code == 404:
                return None
            # No URL, response body, request headers or credentials in logs.
            raise TMDBError('TMDB HTTP ' + str(error.code) + '; stopped without retries') from None
        except (URLError, TimeoutError, ValueError):
            raise TMDBError('TMDB network or response error; stopped without retries') from None

def identity(title):
    return json.dumps([title.get('type'),title.get('title'),title.get('year'),title.get('tmdbId'),title.get('imdbId')], ensure_ascii=False)

def normalized_name(name):
    return ''.join(c for c in unicodedata.normalize('NFKC', name).casefold() if c.isalnum())

def resolve(title, client):
    kind = 'movie' if title['type'] == 'Movie' else 'tv'
    tmdb = title.get('tmdbId')
    if isinstance(tmdb, (str, int)):
        match = re.fullmatch(r'(?:(movie|tv)/)?([1-9][0-9]*)', str(tmdb))
        if match and (not match[1] or match[1] == kind):
            return int(match[2]), 'provider-id'
    imdb = title.get('imdbId')
    if isinstance(imdb, str) and re.fullmatch(r'tt[0-9]+', imdb):
        page = client.get('/find/' + imdb, {'external_source':'imdb_id'})
        results = (page or {}).get(kind + '_results', [])
        if len(results) == 1 and isinstance(results[0].get('id'), int):
            return results[0]['id'], 'imdb-id'
        return None
    # Old catalogue rows lack external IDs. Only a unique exact name + year can match.
    year = title.get('year')
    if not isinstance(year, int):
        return None
    page = client.get('/search/' + kind, {'query':title['title'], 'include_adult':'false',
                       'year' if kind == 'movie' else 'first_air_date_year':year})
    if not page:
        return None
    if not isinstance(page.get('results'), list):
        raise TMDBError('Invalid TMDB search response')
    # A truncated result set cannot prove uniqueness.
    if page.get('total_pages', 1) > 1:
        return None
    name = normalized_name(title['title'])
    candidates = []
    for row in page['results']:
        names = (row.get('title'), row.get('original_title')) if kind == 'movie' else (row.get('name'),row.get('original_name'))
        date = row.get('release_date' if kind == 'movie' else 'first_air_date', '')
        if str(date)[:4] == str(year) and any(isinstance(n,str) and normalized_name(n) == name for n in names) and isinstance(row.get('id'),int):
            candidates.append(row['id'])
    candidates = list(set(candidates))
    return (candidates[0], 'exact-title-year') if len(candidates) == 1 else None

def lookup(title, client):
    resolved = resolve(title, client)
    if not resolved:
        return None
    tmdb_id, method = resolved
    kind = 'movie' if title['type'] == 'Movie' else 'tv'
    data = client.get('/' + kind + '/' + str(tmdb_id), {'language':'en-US'})
    if data is None:
        return None
    if data.get('id') != tmdb_id or not isinstance(data.get('genres'), list):
        raise TMDBError('Invalid TMDB details response')
    code = data.get('original_language')
    if code is not None and (not isinstance(code,str) or not re.fullmatch('[a-z]{2,3}',code)):
        raise TMDBError('Invalid TMDB language')
    genres = data['genres']
    if any(not isinstance(g,dict) or not isinstance(g.get('id'),int) or not isinstance(g.get('name'),str) for g in genres):
        raise TMDBError('Invalid TMDB genres')
    return {'id':tmdb_id,'mediaType':kind,'matchMethod':method,
            'originalLanguageCode':code or None,'originalLanguage':LANGUAGES.get(code,code) or None,
            'genres':sorted(set(g['name'] for g in genres)),
            'url':'https://www.themoviedb.org/' + kind + '/' + str(tmdb_id)}

def open_cache(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, identity TEXT NOT NULL, checked INTEGER NOT NULL, body TEXT)')
    return db

def enrich(catalog, db, client, now, priority_ids=()):
    titles = catalog['titles']
    cached = {row[0]:row[1:] for row in db.execute('SELECT id,identity,checked,body FROM metadata')}
    pending = []
    for title in titles:
        row = cached.get(title['id'])
        if title['id'] in priority_ids or not row or row[0] != identity(title) or now-row[1] >= (30*DAY if row[2] else 7*DAY):
            pending.append(title)
    # Latest weekly additions first, then remaining uncached titles, then expired entries.
    pending.sort(key=lambda t:(t['id'] not in priority_ids, t['id'] in cached, -(t.get('weeklyUpdatedAt') or 0), t['id']))
    status, message = ('ready','TMDB batch completed') if client else ('missing-token','TMDB token not configured; no requests made')
    if client:
        for title in pending:
            try:
                result = lookup(title, client)
            except BudgetReached:
                status, message = 'partial', 'Batch limit reached; resumes automatically'
                break
            except TMDBError as error:
                status, message = 'error', str(error)
                break
            body = json.dumps(result) if result else None
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?,?,?)', (title['id'],identity(title),now,body))
            db.commit()
            cached[title['id']] = (identity(title), now, body)
    matched = 0
    for title in titles:
        row = cached.get(title['id'])
        title['tmdbMatchStatus'] = 'unmatched' if row and row[0] == identity(title) and not row[2] else 'pending'
        title['originalLanguageSource'] = 'Streaming Availability API' if title.get('originalLanguage') else None
        if row and row[0] == identity(title) and row[2]:
            metadata = json.loads(row[2])
            title['tmdbMatchStatus'] = 'matched'
            title['tmdb'] = {**metadata, 'checkedAt':row[1]}
            title['originalLanguage'] = metadata['originalLanguage']
            title['originalLanguageSource'] = 'TMDB' if metadata['originalLanguage'] else None
            matched += 1
    catalog['tmdbEnrichment'] = {'status':status,'message':message,'matched':matched,'total':len(titles),
                               'requestsThisRun':client.calls if client else 0,'checkedAt':now}
    return catalog['tmdbEnrichment']

def repair_external_ids(catalog, requested, now):
    """Explicit manual repair for legacy rows, within the existing streaming budget."""
    ids = [value.strip() for value in requested.split(',') if value.strip()]
    if len(ids) > 5 or any(not re.fullmatch(r'motn:[0-9]+', value) for value in ids):
        raise TMDBError('Metadata repair accepts at most five motn:numeric IDs')
    if not ids:
        return []
    import catalog_sync as streaming
    db = streaming.open_db('.state/catalog.sqlite')
    latest = db.execute('SELECT id,requests FROM runs ORDER BY id DESC LIMIT 1').fetchone()
    remaining = max(0,int(os.environ.get('RUN_REQUEST_LIMIT','12')) - (latest[1] if latest else 12))
    client = streaming.Client(db,os.environ.get('STREAMING_API_KEY',''),os.environ.get('STREAMING_API_MODE','direct'),
                              int(os.environ.get('MONTHLY_REQUEST_LIMIT','400')), remaining)
    repaired = []
    try:
        for title in catalog['titles']:
            if title['id'] not in ids or (title.get('tmdbId') and title.get('imdbId')):
                continue
            show = client.get('/shows/' + title['id'][5:], {'country':'in'})
            normalized = streaming.normalize(show,streaming.get_meta(db,'coverage',{}).get('mapping',{}),now)
            if normalized['id'] != title['id']:
                raise TMDBError('Provider ID repair returned a different title')
            raw = db.execute('SELECT body FROM titles WHERE id=?',(title['id'],)).fetchone()
            if not raw:
                continue
            body = json.loads(raw[0])
            for key in ('tmdbId','imdbId'):
                if normalized.get(key):
                    title[key] = body[key] = normalized[key]
            db.execute('UPDATE titles SET body=? WHERE id=?',(json.dumps(body,sort_keys=True,ensure_ascii=False),title['id']))
            db.commit()
            repaired.append(title['id'])
    except streaming.SyncError:
        print('Legacy ID repair stopped at provider/request limit; existing availability preserved')
    finally:
        if latest:
            db.execute('UPDATE runs SET requests=requests+? WHERE id=?',(client.calls,latest[0]))
            db.commit()
        report = Path('reports/pilot.json')
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(streaming.report(db,now),indent=2))
        db.close()
    return repaired

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--catalog', default='data/catalog.json')
    parser.add_argument('--cache', default='.state/tmdb.sqlite')
    args = parser.parse_args()
    source = Path(args.catalog)
    catalog = json.loads(source.read_text())
    now = int(time.time())
    requested = os.environ.get('TMDB_REFRESH_IDS','')
    if requested:
        repair_external_ids(catalog, requested, now)
    token = os.environ.get('TMDB_READ_ACCESS_TOKEN')
    client = Client(token, int(os.environ.get('TMDB_RUN_REQUEST_LIMIT','300'))) if token else None
    db = open_cache(args.cache)
    try:
        summary = enrich(catalog,db,client,now,tuple(value.strip() for value in requested.split(',')))
    finally:
        db.close()
    temp = source.with_suffix('.tmp')
    temp.write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
    temp.replace(source)
    print(json.dumps(summary))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as output:
            output.write(f"\n### TMDB metadata\n{summary['matched']} / {summary['total']} titles matched. Requests this run: {summary['requestsThisRun']}. Status: {summary['status']}.\n")
    # Metadata failure must not prevent publishing valid streaming availability.
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
