"""Fetch the existing public snapshot and companion evidence; never a movie API."""
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
try:
    from scripts.official_listings import SERVICES
except ModuleNotFoundError:
    from official_listings import SERVICES

BASE = 'https://ottscout.techiwithhelmet.com'


class SiteRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        target = urlparse(newurl)
        if target.scheme != 'https' or target.hostname != 'ottscout.techiwithhelmet.com' or target.username or target.password:
            raise ValueError('Unexpected public snapshot redirect')
        return super().redirect_request(request, response, code, message, headers, newurl)


def get_json(path, limit, optional=False):
    for attempt in range(3):
        try:
            suffix = '?snapshot_retry=' + str(time.time_ns()) if attempt else ''
            request = Request(BASE + path + suffix, headers={'Accept': 'application/json', 'Cache-Control': 'no-cache', 'User-Agent': 'OTTScout-monitor/1.0'})
            with build_opener(SiteRedirects()).open(request, timeout=30) as response:
                data = response.read(limit + 1)
            if len(data) > limit:
                raise ValueError('Oversized public snapshot')
            return json.loads(data)
        except HTTPError as error:
            if optional and error.code == 404:
                return None
            if error.code not in (408, 425, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    args = parser.parse_args(argv)
    root = Path(args.root)
    catalog = get_json('/data/catalog.json', 25_000_000)
    if not isinstance(catalog, dict) or catalog.get('schemaVersion') != 1 or catalog.get('mode') != 'live' or not catalog.get('titles'):
        raise ValueError('Invalid public catalogue snapshot')
    discovery = get_json('/data/official-discovered.json', 1_000_000, optional=True)
    try:
        health = get_json('/data/catalogue-health.json', 5_000_000, optional=True)
        if health is not None and not isinstance(health, dict):
            raise ValueError('Invalid public status report')
    except (OSError, ValueError):
        # Status is an observation, not catalogue evidence. In particular a
        # brand-new status endpoint may be unavailable before first publication.
        # Fresh collector inputs can still establish health; a watchdog without
        # source observations stays unknown/critical instead of inventing them.
        health = None
        print('Previous public status unavailable; fresh monitoring evidence is required.')
    if discovery is not None and (not isinstance(discovery, list) or len(discovery) > 100):
        raise ValueError('Invalid public official evidence registry')
    curated_path = root / 'data/official-listings.json'
    curated = json.loads(curated_path.read_text()) if curated_path.exists() else []
    reviewed = {SERVICES.get(row['platform'], row['platform']) + ':' + row['platformTitleId']: row for row in curated}
    known = set(reviewed)
    extra = [key for key in catalog.get('officialListingAliases', {}) if not key.startswith('motn:') and key not in known]
    if discovery is None and extra:
        raise ValueError('Automatic evidence registry is missing; retain the published snapshot')
    # A catalogue and an older companion can arrive from different CDN edges.
    # Rebuilding with that older registry would strip confirmed offers. Match
    # every embedded automatic observation before replacing any local files.
    by_identity = {}
    for row in discovery or []:
        if not isinstance(row, dict) or not isinstance(row.get('platform'), str) or not isinstance(row.get('platformTitleId'), str):
            raise ValueError('Invalid public official evidence identity')
        key = SERVICES.get(row['platform'], row['platform']) + ':' + row['platformTitleId']
        if key in by_identity:
            raise ValueError('Duplicate public official evidence identity')
        by_identity[key] = row
    aliases = catalog.get('officialListingAliases', {})
    titles = {title.get('id'): title for title in catalog['titles'] if isinstance(title, dict)}
    proof_fields = ('platform', 'sourceURL', 'releaseDate', 'releaseEvidenceURL', 'verifiedAt', 'expiresAt')
    for key in aliases:
        if key.startswith('motn:'):
            continue
        embedded = titles.get(aliases[key], {}).get('officialListing', {})
        if not embedded.get('active') or not key.startswith(SERVICES.get(embedded.get('platform'), 'unknown') + ':'):
            continue
        if key in reviewed and all(reviewed[key].get(field) == embedded.get(field) for field in proof_fields):
            continue
        row = by_identity.get(key, {})
        if any(row.get(field) != embedded.get(field) for field in proof_fields):
            raise ValueError('Public automatic evidence does not match the catalogue; retain the published snapshot')
    for name, value in [('data/catalog.json', catalog), ('data/official-discovered.json', discovery),
                        ('reports/previous-public-health.json', health)]:
        if value is None:
            continue
        target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.download.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        temporary.replace(target)
    # Copy the existing status for website-only changes without pretending that
    # an old provider or official-source check ran again today.
    if health is not None:
        path = root / 'data/catalogue-health.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(health, ensure_ascii=False), encoding='utf-8')
    print(f'Reusing {len(catalog["titles"])} published titles without movie API imports.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
