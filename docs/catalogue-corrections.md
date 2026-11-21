# Catalogue corrections inbox

[Report a missing title or correction](https://github.com/akashIntgrators/OTTScout-Web/issues/new?template=catalogue-correction.yml), or [review the inbox](https://github.com/akashIntgrators/OTTScout-Web/issues?q=is%3Aissue%20label%3Acatalogue-correction).

Reports are public GitHub issues. Submitting, labelling or closing an issue does not change the catalogue. There is no issue-event workflow, public write endpoint, automatic approval or publication path. The inbox needs a free GitHub account; it introduces no additional service or movie API requests.

The form accepts all seven platforms. Only Netflix, JioHotstar and SonyLIV currently have a strict reviewed-listing adapter. Prime Video, Sun NXT, ZEE5 and aha reports remain useful triage leads; accepting a report does not invent a new offer or extend coverage to those platforms.

## User reports

Ask for the exact official title URL and platform ID, Movie/Series, what is wrong, and whether it is available now in India or merely announced. Dates must refer to the platform's India OTT release rather than a theatrical release. Playable audio and original language are separate claims with separate evidence. Empty/uncertain language fields remain unverified; a trailer's language is not a playable audio list.

Stable issue-form IDs for prefilled links are `title_name`, `title_type`, `platform`, `official_url`, `problem` and `notes`. Encode query values, for example:

```text
https://github.com/akashIntgrators/OTTScout-Web/issues/new?template=catalogue-correction.yml&title_name=Guarding%20Stars&title_type=Movie&platform=Netflix&official_url=https%3A%2F%2Fwww.netflix.com%2Fin%2Ftitle%2F81749470
```

[GitHub's form schema](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema) identifies a form element's `id` as its URL-prefill key. Keep these IDs stable when changing visible labels.

## Maintainer review

1. Inspect the report and open its primary evidence yourself. Confirm the exact title, platform, type and current India availability. A generic HTTP 200 page, plan page, future announcement or public report alone is insufficient. Check the publisher of any trailer/announcement; URL shape validation cannot establish what a page says.
2. Check existing provider data and the reviewed registry. Availability removals, unsupported platforms, disputed identity, add-on conditions that cannot be represented, and provider-owned errors stay in triage until there is a supported correction. This helper adds/updates reviewed fallback evidence; it does not edit provider records, claim authenticated India playback, or remove a title from an OTT service.
3. Prepare a review interactively; no JSON copying is required. Use a current downloaded/public catalogue snapshot so existing saved-title aliases can be retained:

```sh
python scripts/correction_review.py --new outputs/reviews/correction-42.json --reviewer akashIntgrators
```

The prompt asks for current India evidence, the actual OTT release date and its dated evidence, access evidence, optional explicit audio and original-language evidence, and a validity period of 1–30 days (default seven). It uses the actual review time and validates everything before saving the separate review file. Coming-soon/unverified titles cannot become active fallback records. This command never downloads evidence, calls an API or changes the production registry.

4. Validate the saved review again. Dry run is the default:

```sh
python scripts/correction_review.py outputs/reviews/correction-42.json --reviewer akashIntgrators
```

5. After reviewing its evidence and proposed identity, apply the correction **locally**:

```sh
python scripts/correction_review.py outputs/reviews/correction-42.json --reviewer akashIntgrators --apply
git diff -- data/official-listings.json
python -m unittest discover -s tests -p 'test_correction_review.py' -v
```

Only `data/official-listings.json` is replaced, after full validation. The command does not change `data/catalog.json`, provider/TMDB metadata, automatic evidence or learned aliases. It reuses `official_registry.load_records` and the pure official overlay to retain an existing reviewed/provider ID, reject ambiguous matches and later removals, and check the combined registry. Invalid, future, expired or contradictory evidence leaves the registry untouched. Reapplying a registry update never changes its review/expiry timestamps automatically.

Submit the registry diff through the normal maintainer PR/review process, link the original issue, then use the established website publication workflow. Applying a local review does not publish. Close the issue only when the published result has been checked, or explain why it remains unverified. The maintainer allowlist is explicit in `correction_review.py`; a review file's self-declared author is not an authentication mechanism and untrusted issue content must never be fed into an automated `--apply` job.

## Review file format

For an existing hand-prepared file, use an object with exactly `schemaVersion: 1`, `decision: "approve"`, `issueURL`, `reviewedBy`, `availability: "available-now-in-india"`, `indiaEvidenceURL`, and `listing`. `listing` uses the existing [official-listings schema](official-listings.md); `id` may be omitted because the tool derives/preserves it. `indiaEvidenceURL` must identify this exact official platform title. `verifiedAt` is the actual post-release review time in Unix seconds; `expiresAt` must still be in the future and no more than 30 days after that review. Audio without explicit audio evidence and original language without separate original-language evidence are rejected.

Options `--catalog`, `--registry` and `--discovered` allow isolated fixture/preview paths. `--new` cannot be combined with `--apply` and cannot overwrite catalogue inputs. `--apply` is explicitly rejected on public `issues`, `issue_comment` and `pull_request_target` events. No issue automation is installed: human approval and the existing PR publication process remain the only route to a live change.
