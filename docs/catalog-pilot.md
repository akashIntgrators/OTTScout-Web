# OTTScout continuous catalogue collector

## What is ready

A standard-library Python collector queries Streaming Availability API v4 for India. It discovers which of our seven platforms are supported, starts with a bounded popular-title sample, then gradually imports older platform catalogues and tracks show-level additions, updates and removals. Collection is continuous: there is no 30-day automatic stop. The workflow label **OTTScout catalog pilot**, this guide's filename, report filenames and existing state keys are retained for continuity. Coverage remains partial; this is not an episode tracker. The authenticated country endpoint determines provider support for each platform, including Sun NXT and aha.

A SQLite database holds title snapshots, per-provider change events, request attempts, successful watermarks, and run history. The public website consumes a validated, curated JSON view. No API key or SQLite database is included in the website or committed to the public repository. Client-side search covers only imported titles.

## Set up

1. Create a free account at https://developers.movieofthenight.com/ and obtain its API key. No paid plan is required to start.
2. In this repository's Settings → Secrets and variables → Actions, create a repository **secret** named `STREAMING_API_KEY`. Never put it in source files, a public issue, or chat.
3. In Actions variables, use `STREAMING_API_MODE=direct` for a key issued by Movie of the Night. If using RapidAPI instead, use `STREAMING_API_MODE=rapidapi` and that platform's key.
4. Verify your actual provider account quota. This collector keeps the existing **400 requests per UTC calendar month** and **12 requests per run** guardrails. `MONTHLY_REQUEST_LIMIT` and `RUN_REQUEST_LIMIT` may lower those limits; values above 400 or 12 are clamped. These are conservative local limits, not a claim about the provider plan or a quota increase. Bootstrap, country discovery, pagination, title lookups and failed network attempts all count before sending. Other apps or key consumers are outside this ledger. Failed calls are not automatically retried within a run.
5. Open Actions → **OTTScout catalog pilot** → Run workflow. Set `initialize=true` only if no database exists. Existing deployments continue with `initialize=false`; do not reinitialize or reset their ledger. Leave `publish=false` for a first coverage review. A limited baseline resumes its completed platform/type tasks on a later run.
6. Read the Actions summary and `pilot-report` JSON artifact. They show ongoing collection, coverage gaps, request usage, the protected freshness reserve, available older-import budget and update times. Review actual usage and data quality periodically; day 30 no longer ends collection.

Schedule: `30 0,6,12,18 * * *` in UTC, corresponding to midnight, 6 AM, noon and 6 PM IST. GitHub may delay runs. Before initialization, scheduled runs make no provider calls. New-addition checks use **6-hour UTC buckets**; updated/removed checks use **UTC calendar days** (24-hour buckets). This avoids skipped or repeated checks caused by scheduler jitter. Pending change windows resume first regardless of their normal cadence. All due change tracking runs before optional older imports. Reported-title fallback lookups are limited to one streaming-provider request per UTC day across unresolved reports. Pagination and request caps can delay completion; the cadence is not a promise of complete coverage at each scheduled time.

## Enable the real catalog after validation

An initial unpublished collector run does not automatically replace sample titles. Validate audio/subtitle completeness and India coverage against the OTT apps, and confirm the provider plan permits the intended public end-user display and caching. Original language is never used to infer dubbing. Offers with unknown audio do not match a specific language selection.

In Settings → Pages, use **GitHub Actions** as the publishing source. Then run the pilot with `publish=true` for one publication, or set repository variable `PUBLISH_CATALOG=true` for automatic publication after eligible successful updates or validated cached fallback on a request limit. This publishes the curated website data and required attribution. It does not publish provider response dumps or database exports. The publication job uses `scripts/build_site.py` to stage only public dashboard files, the local account bundle and public SDK configuration, curated data, assets and crawlable pages. The curated catalog is packaged directly into the Pages website artifact; provider data is never committed to the public source repository.

The exported snapshot records source, coverage and the last complete streaming watermark. Updated/removal checks run daily, so that complete watermark can lag the latest new-addition check by about a day; individual title check dates remain separate. Each title lists offer-specific audio/subtitles and distinguishes subscription, free, rental, purchase and add-on availability. Weekly results use provider-reported new show availability from the last seven days, including a one-time historical backfill. A baseline import alone never qualifies a title as new; dates are not confirmed premiere dates. The backfill saves its cursor after each validated page and resumes within the existing request limits. Season/episode-level notifications and upcoming-release predictions are not implemented. Platform and language filters are positive checkbox selections and persist in the browser. Advertisement placeholders reserve space. Optional website analytics and account services are configured separately from this collector.

## State durability and recovery

The SQLite database is saved through GitHub Actions cache after each run, including failed runs, with serial workflow concurrency. Removing the time limit does not make this a durable database: the cache remains a best-effort store. GitHub may evict caches; do not store secrets or personal data here. On missing state, scheduled runs fail closed and make zero provider calls rather than silently resetting usage and importing everything again.

For durable catalogue operation, move collector state to durable storage or a managed private database. If the cache is lost, review provider-side usage before manually reinitializing: local request counts cannot recover calls from lost state or other consumers. Continuous operation preserves the original `pilot_started` value, request ledger, watermarks and pagination cursors. Initialization never resets a present database. API keys belong only in Secrets.

A failed update leaves the last published snapshot intact. A limited run may publish only a validated cached/partial snapshot through the fallback described below. No failed request is interpreted as a removal. Each change-type watermark advances only after all its result pages validate successfully. A gap of more than 30 days requires a new baseline because the changes endpoint has limited history.

## Local checks

- `npm run check`: browser code syntax.
- `npm test`: collector failure, pagination, language, coverage, event, and request-budget tests; no paid/live calls.
- `npm run dev`: local preview at http://127.0.0.1:5174, using the repository root (the actual Pages source).
- `npm run build`: creates `.site/` containing only public website files.

Live collection locally: set `STREAMING_API_KEY` in your process environment, then run `python3 scripts/catalog_sync.py --initialize`. This consumes real provider quota. Do not run fixture tests against production data files.

References:
- https://docs.movieofthenight.com/resource/shows
- https://docs.movieofthenight.com/resource/countries
- https://docs.movieofthenight.com/resource/changes
- https://github.com/movieofthenight/streaming-availability-api/blob/main/TERMS.md
- https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching


## Original audio and older-title search

TMDB supplies normal original-language and genre enrichment without spending streaming-provider requests. Legacy original-language-filtered streaming scans are disabled by default: the workflow sets `ORIGINAL_LANGUAGE_BACKFILL_PAGES=0`. Their saved cursors and previously verified originals are retained. If explicitly enabled for local maintenance, these scans run after generic older-title imports, use only remaining backfill allowance and are bounded to two pages per run.

Original language remains separate from each platform's audio. Original audio only requires the title's reported original language to be present on a matching selected offer. Missing metadata stays Unverified; title, country and first-listed audio never establish an original language.

Older imports use alphabetical pagination across supported platforms and movies/series. Each validated page and its cursor are committed together. Imports do not create weekly-addition events. They cover older titles currently offered by the provider, rather than a history of removed offers or every movie ever made. Completion depends on coverage, retained cursors and available budget; there is no guaranteed completion date.

Hidden titles and the original-audio preference are saved in this browser. Restore
hidden titles clears dismissals; the watchlist remains accessible.

Dr. 56 (`motn:57489`) has a verified Kannada original-language correction, applied
also to previously imported records. Source: https://tv.apple.com/in/movie/dr-56/umc.cmc.48r2rpynxx4gtg53d94qc7aki . Its Hindi JioHotstar offer remains Hindi.

## TMDB original-language and genre enrichment

Add the **API Read Access Token** as the Actions secret `TMDB_READ_ACCESS_TOKEN`. It is available only to the enrichment step, never browser JavaScript. TMDB supplies `original_language` and genres; streaming-platform audio remains independent. The original-only switch still requires that the original audio is actually available in the selected offer.

`scripts/tmdb_enrich.py` runs after an eligible streaming check, including validated cached fallback on a request limit, before saving `.state` and building the public website. It preserves provider TMDB/IMDb IDs for future updates and uses those where available. Older records without IDs require a unique exact title and release/first-air year; ambiguous matches stay unverified. No fuzzy first-result matching.

The SQLite cache `.state/tmdb.sqlite` shares the existing private Actions cache. Positive results refresh after 30 days and unmatched results after 7 days. `TMDB_RUN_REQUEST_LIMIT` defaults to **300 requests per run**, independent of the streaming API budget. A title search plus details costs two requests; a direct TMDB ID costs one. Latest additions get priority. Initial coverage builds over successive successful runs. API errors stop the batch without retries, keep cached metadata, and do not block valid streaming updates. Cache eviction may require re-enrichment.

Genres use TMDB data only, with an explicit Unverified option; selecting several genres matches any. All genres includes unverified titles. Original-language values retain their source; unmatched titles keep existing verified provider originals. TMDB reports one original-language field, which is not a complete list of a multilingual production's original languages.

The public snapshot includes matched TMDB ID, match method, check timestamp, original language and genres; no access token. Credits appear on the dashboard and title/language pages. Confirm appropriate TMDB commercial licensing before enabling advertising; developer access is for non-commercial use. See https://developer.themoviedb.org/docs/faq.

## Discovery filters and corrections

The dashboard has independent **Originally** and **Watch in** checkbox dropdowns. Originally filters the title's known original language; Watch in filters audio on the selected platform's offer. Both match any selected choice within their own group, and groups combine with AND. Original audio only additionally requires that matching offer to carry the title's original audio. Existing original-audio preferences are preserved. Unverified originals are selectable explicitly; non-target original languages are grouped under Other languages.

Included with subscription accepts only base `subscription` offers without an add-on. It excludes free, rent, buy and addon offers. Active-filter chips clear one filter group; Reset filters clears all groups. Watchlist and hidden-title state are unaffected.

Each card's Where to watch section opens a correction dialog. The visitor can choose an issue type and platform, add a correction/source, review a generated public-data report, copy it, or open a prefilled public GitHub issue. GitHub requires sign-in and a separate submit action; the site never silently submits a report. Individual title pages also link to a prefilled issue. No email, browser storage, API token or personal identifier is included automatically.

A manual **metadata_only** workflow run exports the previously validated streaming snapshot and refreshes TMDB data without calling the streaming provider. It does not update the streaming-data timestamp. The normal six-hour workflow remains unchanged. Explicit metadata-ID repairs are disabled in this mode because those require streaming requests. Known provider IDs are prioritised to improve matching and avoid unnecessary text searches. Coverage reports distinguish pending and unmatched TMDB records and count known original languages.

## Older titles across platforms

Catalogue backfill rotates across each supported platform and movies/series, fetching at most one page per task per run. This avoids finishing a large platform before importing from another. Existing per-task cursors are retained, including those from the previous sequential importer. A saved next-task pointer resumes the rotation after request limits or interruptions. Completed tasks are skipped.

Scheduled and manual runs default to **up to six older catalogue pages**, shared across platforms. Manual `catalog_pages` can select six or two; `CATALOG_BACKFILL_PAGES` is also bounded to six. This is a ceiling, not a guaranteed number of calls: pending/due change feeds run first, every attempt shares the 12-request run cap, and older imports can use only the budget above the monthly freshness reserve. Generic catalogue pages run before optional original-language-filtered scans. A backfilled older title becomes a weekly addition only if the provider independently reports a recent offer. Older titles appear in Discover and search; imported coverage stays partial until platform/type pagination is complete.

### Adaptive monthly budget

The fixed reserve protects **8 requests per remaining UTC day, plus 20 requests of headroom**. The partial current day is rounded up. These planning constants do not guarantee the actual pagination cost of a freshness check, and are not workflow settings.

`freshnessReserve = 8 × remaining UTC days + 20`

`backfillAvailable = max(0, requestsRemaining − freshnessReserve)`

For example, with 320 of 400 requests used and four days remaining, 80 remain, 52 are protected and 28 are available for older imports across subsequent runs. Each run still stops at its own page ceiling and request cap. If the allowance is zero, optional older imports wait; the hard monthly cap continues to apply to every streaming request. A new UTC calendar month opens a new monthly allowance without erasing historical usage or cursors.

The report's `requestBudget` contains `monthlyLimit`, `requestsUsed`, `requestsRemaining`, `freshnessReserve`, `backfillAvailable`, `headroom` and `maintenanceRequestsPerDay`. **`freshnessReserve` already includes `headroom`; do not subtract it twice.** Continuous reports use `collectorMode: "continuous"`, `pilotEndsAt: null`, `scheduleHours: 6` and `maintenanceHours: 24`. Legacy `pilotStartedAt` and `requestsDuringPilot` retain their original start/usage meaning; they are not reset to begin another trial.


## Weekly accuracy and bounded catch-up

Weekly exports include per-platform `weeklyEvents` timestamps. The dashboard and crawlable weekly page also check an offer's `availableSince`: a newly reported free/rental option cannot make an older base-subscription offer appear new. Missing offer dates fall back to a labelled platform-addition date. Older movies are films released before the current IST year; series are never labelled new seasons from their first-air year. No provider detection date is presented as a verified OTT premiere.

Cards show their individual availability check date, while the report/snapshot retains the last complete streaming watermark. Metadata explanations distinguish pending lookups, no confident match, missing source fields, and known provider originals. Missing TMDB original languages preserve known provider values. Exact matching remains conservative; ambiguous searches remain unverified.

Large change queries persist validated pages and a fixed from/to window in private SQLite state. On a later run they resume at the saved cursor under the same request caps. A change feed is applied only after its final validated page, and its watermark advances to that window's end, not the resume time. Earlier page check timestamps remain intact. The report exposes `pendingChangeQueries` for diagnosis; raw staged pages are never published.

The scheduled collector uses `--allow-cached-on-limit`: if a request cap is reached and a previously validated snapshot exists, metadata and website updates may continue from that cache. `syncStatus` stays limited in the report/snapshot, and the last complete streaming watermark is not advanced. An incomplete initial baseline, malformed response, or provider error cannot take this fallback path. Explicit metadata-only publication also works when the most recent streaming run was limited. Streaming caps remain 12 requests/run and 400/calendar month; TMDB keeps its separate 300/run cap.
