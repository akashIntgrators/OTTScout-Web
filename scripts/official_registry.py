"""Combine reviewed and automatically verified listings without changing saved IDs."""
import json
from copy import deepcopy
from pathlib import Path

try:
    from scripts.official_listings import SERVICES, OfficialListingError, _identity, apply_official_listings
except ModuleNotFoundError:
    from official_listings import SERVICES, OfficialListingError, _identity, apply_official_listings


def _read(path):
    if not path.exists():
        return []
    if path.stat().st_size > 1_000_000:
        raise OfficialListingError('Official registry is unexpectedly large')
    records = json.loads(path.read_text())
    if not isinstance(records, list) or len(records) > 100:
        raise OfficialListingError('Invalid official registry')
    return records


def load_records(root, catalog=None, *, curated_path=None, discovered_path=None, now=None):
    root = Path(root)
    curated = _read(Path(curated_path) if curated_path is not None else root / 'data/official-listings.json')
    discovered = _read(Path(discovered_path) if discovered_path is not None else root / 'data/official-discovered.json')
    output = deepcopy(curated)
    identities = set()
    reviewed_positions = {}
    for position, row in enumerate(curated):
        if not isinstance(row, dict) or not isinstance(row.get('platform'), str) or not isinstance(row.get('platformTitleId'), str):
            raise OfficialListingError('Invalid reviewed listing identity')
        identity = (row['platform'], row['platformTitleId'])
        if identity in identities:
            raise OfficialListingError('Duplicate reviewed listing identity')
        identities.add(identity)
        reviewed_positions[identity] = position
    catalog = catalog or {}
    aliases = catalog.get('officialListingAliases', {})
    for item in discovered:
        if not isinstance(item, dict) or not isinstance(item.get('platform'), str) or not isinstance(item.get('platformTitleId'), str):
            raise OfficialListingError('Invalid discovered listing identity')
        identity = (item['platform'], item['platformTitleId'])
        if identity in identities:
            position = reviewed_positions.get(identity)
            reviewed = output[position] if position is not None else None
            if (reviewed is not None and type(now) is int and type(reviewed.get('expiresAt')) is int
                    and reviewed['expiresAt'] <= now and type(item.get('verifiedAt')) is int
                    and item['verifiedAt'] > reviewed.get('verifiedAt', 0)):
                if reviewed.get('type') != item.get('type'):
                    raise OfficialListingError('Automatic evidence conflicts with reviewed title type')
                # Expired evidence is no longer authoritative. Fresh exact-title
                # proof may renew it, while the existing saved-title ID survives.
                output[position] = {**deepcopy(item), 'id': reviewed['id']}
            continue  # A reviewed correction always takes precedence.
        identities.add(identity)
        row = deepcopy(item)
        service = SERVICES.get(row['platform'])
        bound = aliases.get(service + ':' + row['platformTitleId']) if service and isinstance(aliases, dict) else None
        matches = {title['id'] for title in catalog.get('titles', [])
                   if title.get('type') == row.get('type') and any(
                       offer.get('platform') == row['platform']
                       and _identity(offer.get('link'), row['platform'], row.get('type')) == row['platformTitleId']
                       for offer in title.get('offers', []))}
        if bound:
            row['id'] = bound
        elif len(matches) == 1:
            row['id'] = next(iter(matches))
        elif len(matches) > 1:
            raise OfficialListingError('Ambiguous existing official title identity')
        output.append(row)
    if len(output) > 100:
        raise OfficialListingError('Combined official registry exceeds its safety limit')
    return output


def main():
    import argparse
    import time
    parser = argparse.ArgumentParser(description='Apply verified official listings without movie API requests')
    parser.add_argument('--catalog', default='data/catalog.json')
    parser.add_argument('--root', default='.')
    parser.add_argument('--now', type=int)
    args = parser.parse_args()
    path = Path(args.catalog)
    catalog = json.loads(path.read_text())
    now = args.now or int(time.time())
    output, summary = apply_official_listings(catalog, load_records(args.root, catalog, now=now), now)
    temporary = path.with_suffix('.official.tmp')
    temporary.write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    print(f'Applied {summary["fallback"]} verified official listings; no movie API calls.')


if __name__ == '__main__':
    main()
