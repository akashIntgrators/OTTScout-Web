"""Validate a trusted maintainer's correction; registry changes require --apply.

This command has no network, issue-event or publication integration. Public issue
text is never loaded or executed. URL validation checks identity and provenance;
a maintainer must actually inspect the cited evidence before approving a review.
"""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
import time

try:
    from scripts.official_listings import (DAY, SERVICES, OfficialListingError, _identity,
        _validate, apply_official_listings)
    from scripts.official_registry import load_records
except ModuleNotFoundError:
    from official_listings import (DAY, SERVICES, OfficialListingError, _identity,
        _validate, apply_official_listings)
    from official_registry import load_records


TRUSTED_MAINTAINERS = {'akashintgrators'}
REVIEW_KEYS = {'schemaVersion', 'decision', 'issueURL', 'reviewedBy', 'availability', 'indiaEvidenceURL', 'listing'}
ISSUE_URL = re.compile(r'https://github\.com/akashIntgrators/OTTScout-Web/issues/[1-9][0-9]*')


class CorrectionReviewError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise CorrectionReviewError(message)


def read_json(path, maximum, *, optional=False):
    path = Path(path)
    if optional and not path.exists():
        return []
    require(path.is_file() and path.stat().st_size <= maximum, 'Missing or oversized review input: ' + path.name)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON fields are not accepted')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)


def prepare_review(review, curated, catalogue, discovered, *, reviewer, now):
    """Return a validated registry copy and summary; never change input objects."""
    require(type(now) is int and 0 < now <= 4102444800, 'Invalid review clock')
    require(isinstance(reviewer, str) and reviewer.casefold() in TRUSTED_MAINTAINERS,
            'A configured trusted maintainer must review this correction')
    require(isinstance(review, dict) and set(review) == REVIEW_KEYS and type(review.get('schemaVersion')) is int
            and review['schemaVersion'] == 1 and review.get('decision') == 'approve', 'Expected an explicitly approved maintainer review file')
    require(isinstance(review['reviewedBy'], str) and review['reviewedBy'].casefold() == reviewer.casefold(),
            'Review author does not match the explicit maintainer')
    require(isinstance(review['issueURL'], str) and ISSUE_URL.fullmatch(review['issueURL']), 'Expected this repository\'s correction issue URL')
    require(review['availability'] == 'available-now-in-india', 'Announcements and unverified availability remain in triage, not the live registry')
    require(isinstance(curated, list) and len(curated) <= 100 and isinstance(discovered, list) and len(discovered) <= 100,
            'Invalid existing official registry')
    require(isinstance(catalogue, dict) and type(catalogue.get('schemaVersion')) is int and catalogue['schemaVersion'] == 1 and catalogue.get('mode') == 'live'
            and isinstance(catalogue.get('titles'), list) and 0 < len(catalogue['titles']) <= 100000,
            'A real published catalogue snapshot is required to preserve saved-title identities')
    # Validate the snapshot/previous registry before trusting its alias map or
    # IDs. The overlay is pure, so this does not change the downloaded snapshot.
    apply_official_listings(catalogue, curated, now)
    row = deepcopy(review['listing'])
    require(isinstance(row, dict) and isinstance(row.get('platform'), str) and row['platform'] in SERVICES,
            'This platform has no reviewed overlay adapter; retain the report for maintainer triage')
    require(row.get('type') in ('Movie', 'Series'), 'Select Movie or Series')
    require(isinstance(row.get('platformTitleId'), str) and re.fullmatch(r'[0-9]{1,30}', row['platformTitleId']), 'Invalid exact platform title ID')
    row.setdefault('id', 'motn:official-' + SERVICES[row['platform']] + '-' + row['platformTitleId'])
    require(_identity(review['indiaEvidenceURL'], row['platform'], row['type']) == row['platformTitleId'],
            'India availability needs an exact matching official title URL; generic plans or announcements are insufficient')
    # Reuse the same stable binding path as automatic/curated overlays. Existing
    # reviewed IDs take precedence; otherwise the published exact ID/alias wins.
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); old = root / 'curated.json'; one = root / 'candidate.json'; auto = root / 'automatic.json'
        old.write_text(json.dumps(curated), encoding='utf-8'); one.write_text(json.dumps([row]), encoding='utf-8')
        bound = load_records(root, catalogue, curated_path=old, discovered_path=one, now=now)
        identity = (row['platform'], row['platformTitleId'])
        existing = [item for item in curated if isinstance(item, dict) and (item.get('platform'), item.get('platformTitleId')) == identity]
        require(len(existing) <= 1, 'Duplicate existing reviewed platform identity')
        selected = [item for item in bound if (item['platform'], item['platformTitleId']) == identity]
        require(len(selected) == 1, 'Could not preserve an unambiguous saved-title identity')
        row['id'] = selected[0]['id']
        known = {title.get('id') for title in catalogue['titles'] if isinstance(title, dict)}
        known.update(catalogue.get('officialListingAliases', {}).values())
        release = _validate(row, now, known)
        require(release <= row['verifiedAt'] <= now < row['expiresAt'], 'A current post-release review with unexpired evidence is required')
        require(row['access']['type'] != 'addon', 'Named add-on conditions need maintainer triage; the reviewed registry cannot represent them yet')
        if existing:
            require(row['type'] == existing[0].get('type'), 'Changing a reviewed title\'s type needs a separate identity review')
            require(row['verifiedAt'] >= existing[0]['verifiedAt'], 'A correction cannot replace a newer review')
        updated = deepcopy(curated)
        if existing:
            updated[curated.index(existing[0])] = row
        else:
            updated.append(row)
        old.write_text(json.dumps(updated), encoding='utf-8'); auto.write_text(json.dumps(discovered), encoding='utf-8')
        merged = load_records(root, catalogue, curated_path=old, discovered_path=auto, now=now)
        output, _ = apply_official_listings(catalogue, merged, now)
        active = [t for t in output['titles'] if t['id'] == row['id'] and isinstance(t.get('officialListing'), dict)
                  and t['officialListing'].get('sourceURL') == row['sourceURL'] and t['officialListing'].get('active') is True]
        require(len(active) == 1, 'The review conflicts with a later removal or existing identity; no registry change is allowed')
    return updated, {'operation': 'update' if existing else 'add', 'id': row['id'], 'platform': row['platform'],
        'platformTitleId': row['platformTitleId'], 'issueURL': review['issueURL'], 'reviewedBy': reviewer,
        'providerApiRequests': 0, 'tmdbRequests': 0}


def new_review(reviewer, now, ask=None):
    """Maintainer-only prompt helper; the resulting file is validated before save."""
    ask = input if ask is None else ask
    print('Inspect the issue and official evidence first. These answers do not publish a title.')
    issue = ask('Correction issue URL: ').strip()
    title = ask('Exact title: ').strip()
    platform = ask('Platform (Netflix / JioHotstar / SonyLIV): ').strip()
    kind = ask('Movie or Series: ').strip()
    ident = ask('Exact numeric platform title ID: ').strip()
    source = ask('Canonical official India title URL: ').strip()
    india = ask('Exact title URL checked for current India availability [same URL]: ').strip() or source
    require(ask('Have you confirmed it is available now in India, rather than only announced? (yes/no): ').strip().casefold() == 'yes',
            'Keep announced or unverified titles in triage')
    release = ask('India OTT release date (YYYY-MM-DD): ').strip()
    dated = ask('Dated official OTT release evidence URL: ').strip()
    access = ask('Access (subscription / free / rent / buy; named add-ons stay in triage): ').strip()
    access_source = ask('Exact access or supported official plan evidence URL: ').strip()
    audio = [item.strip() for item in ask('Explicit playable audio languages, comma separated [unknown]: ').split(',') if item.strip()]
    audio_source = ask('Exact playable-audio evidence URL: ').strip() if audio else None
    original = ask('Explicit original language [unknown]: ').strip() or None
    original_source = ask('Explicit original-language evidence URL: ').strip() if original else None
    days = int(ask('Evidence validity in days (1-30) [7]: ').strip() or '7')
    require(1 <= days <= 30, 'Evidence validity must be 1-30 days')
    return {'schemaVersion': 1, 'decision': 'approve', 'issueURL': issue, 'reviewedBy': reviewer,
        'availability': 'available-now-in-india', 'indiaEvidenceURL': india,
        'listing': {'platform': platform, 'platformTitleId': ident, 'title': title, 'type': kind,
            'sourceURL': source, 'releaseDate': release, 'releaseEvidenceURL': dated,
            'verifiedAt': now, 'expiresAt': now + days * DAY, 'access': {'type': access, 'evidenceURL': access_source},
            'audio': audio, 'audioEvidenceURL': audio_source, 'originalLanguage': original,
            'originalLanguageEvidenceURL': original_source}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review_file', nargs='?')
    parser.add_argument('--new', metavar='REVIEW_JSON', help='Prompt a maintainer and save a validated review file; do not apply it')
    parser.add_argument('--reviewer', required=True, help='Explicit trusted maintainer GitHub handle')
    parser.add_argument('--catalog', default='data/catalog.json')
    parser.add_argument('--registry', default='data/official-listings.json')
    parser.add_argument('--discovered', default='data/official-discovered.json')
    parser.add_argument('--apply', action='store_true', help='Write the validated reviewed registry locally; never publish')
    args = parser.parse_args(argv)
    try:
        require(bool(args.review_file) != bool(args.new), 'Choose an existing review file or --new, not both')
        require(not (args.new and args.apply), '--new prepares a review; applying it is a separate explicit step')
        require(not args.apply or os.environ.get('GITHUB_EVENT_NAME') not in ('issues', 'issue_comment', 'pull_request_target'),
                'Public issue events cannot apply corrections')
        now = int(time.time()); registry = Path(args.registry)
        require(not registry.is_symlink(), 'The reviewed registry must not be a symbolic link')
        before = registry.read_bytes() if registry.exists() else None
        curated = read_json(registry, 1_000_000, optional=True)
        catalogue = read_json(args.catalog, 25_000_000)
        discovered = read_json(args.discovered, 1_000_000, optional=True)
        review = new_review(args.reviewer, now) if args.new else read_json(args.review_file, 64_000)
        updated, summary = prepare_review(review, curated, catalogue, discovered, reviewer=args.reviewer, now=now)
        if args.new:
            target = Path(args.new)
            require(target.resolve() not in {registry.resolve(), Path(args.catalog).resolve(), Path(args.discovered).resolve()}, 'Review output must be separate from catalogue data')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as output:
                output.write(json.dumps(review, ensure_ascii=False, indent=2) + '\n')
            print('Validated review file prepared; no registry change or publication.')
        elif args.apply:
            require((registry.read_bytes() if registry.exists() else None) == before, 'Registry changed during review; revalidate before applying')
            registry.parent.mkdir(parents=True, exist_ok=True)
            temporary = registry.with_suffix('.review.tmp')
            temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(registry)
            print('Reviewed registry updated locally. Review its diff before submitting a PR; nothing was published.')
        else:
            print('Dry run passed. No registry change or publication; use --apply only after maintainer review.')
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except (OSError, ValueError, OfficialListingError, EOFError) as error:
        print('Correction not applied: ' + str(error))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
