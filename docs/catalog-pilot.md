# OTTScout live-catalog pilot

## What is ready

A standard-library Python collector queries Streaming Availability API v4 for India. It discovers which of our seven platforms are supported, imports a bounded popular-title sample (one movie page and one series page per supported platform), then backfills seven days of provider-reported show additions and tracks subsequent show-level additions, updates, and removals across all supported platforms. This is a discovery pilot, not a full catalog import or an episode tracker. Sun NXT and aha are not listed in the provider's published India example; the authenticated country endpoint is the source of truth.

A SQLite database holds title snapshots, per-provider change events, request attempts, successful watermarks, and run history. The public website consumes a validated, curated JSON view. No API key or SQLite database is included in the website or committed to the public repository. Client-side search covers only imported titles.

## Set up

1. Create a free account at https://developers.movieofthenight.com/ and obtain its API key. No paid plan is required to start.
2. In this repository's Settings → Secrets and variables → Actions, create a repository **secret** named `STREAMING_API_KEY`. Never put it in source files, a public issue, or chat.
3. In Actions variables, use `STREAMING_API_MODE=direct` for a key issued by Movie of the Night. If using RapidAPI instead, use `STREAMING_API_MODE=rapidapi` and that platform's key.
4. Verify your actual account quota. The application defaults to `MONTHLY_REQUEST_LIMIT=400` and `RUN_REQUEST_LIMIT=12`. These are conservative application limits, not claims about the provider's plan. They count this collector's attempts only; calls made from another app/key consumer are not included. Bootstrap, pagination, and failed network attempts all count. No automatic retries are made.
5. Open Actions → **OTTScout catalog pilot** → Run workflow. Set `initialize=true` for the first run. Leave `publish=false` for the trial coverage review. A normal run uses `initialize=false`. A limited baseline may need another run to finish; it resumes the completed platform/type tasks.
6. Read the Actions summary and download the `pilot-report` JSON artifact. It lists coverage gaps, requests, changes, failed runs, and update times. Review at days 7, 14, 21, and 30. The job makes no more provider calls after day 30.

Schedule: `30 0,6,12,18 * * *` in UTC, corresponding to midnight, 6 AM, noon, and 6 PM IST. GitHub may delay runs. Before initialization, scheduled runs make no provider calls.

## Enable the real catalog after validation

The trial does not automatically replace sample titles. Validate audio/subtitle completeness and India coverage against the OTT apps, and confirm the provider plan permits the intended public end-user display and caching. Original language is never used to infer dubbing. Unknown audio offers are excluded from language-matched results.

In Settings → Pages, use **GitHub Actions** as the publishing source. Then run the pilot with `publish=true` for one publication, or set repository variable `PUBLISH_CATALOG=true` for automatic publication after each complete successful update. This publishes the curated website data and required attribution. It does not publish provider response dumps or database exports. The publication job stages only index.html, app.js, style.css, assets/, data/, and CNAME. The curated catalog is packaged directly into the Pages website artifact; provider data is never committed to the public source repository.

The live UI shows missing platform coverage, source, last-successful-update time, and a delayed-update message after 12 hours. Each title lists offer-specific audio/subtitles and distinguishes subscription, free, rental, purchase, and add-on availability. Weekly results use provider-reported new show availability from the last seven days, including a one-time historical backfill. A baseline import alone never qualifies a title as new; dates are not confirmed premiere dates. The backfill saves its cursor after each validated page and resumes within the existing request limits. Season/episode-level notifications and upcoming-release predictions are not implemented. Platform and language filters are positive checkbox selections and persist in the browser. Labelled leaderboard, sidebar, and in-feed ad placeholders reserve space; no ad network or tracking scripts are installed.

## State durability and recovery

For this low-cost pilot, the SQLite database is saved through GitHub Actions cache after each run, including failed runs, with serial workflow concurrency. This is a best-effort trial store, not a production database or a private vault. GitHub may evict caches; do not store secrets or personal data here. On missing state, scheduled runs fail closed and make zero provider calls rather than silently resetting usage and importing everything again.

Before a long-term launch or user accounts, move SQLite to durable storage or a managed private database. If pilot cache is lost, review provider-side usage before manually reinitializing: local request counts cannot recover calls from lost state or other consumers. Initialization never resets a present pilot database. API keys belong only in Secrets.

The latest published JSON remains intact after a failed or limited update. No failed request is interpreted as a removal. Each change-type watermark advances only after all its result pages validate successfully. A gap of more than 30 days requires a new baseline because the changes endpoint has limited history.

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
