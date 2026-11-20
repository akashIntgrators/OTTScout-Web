# Catalogue reliability

New releases take priority over maintenance and older imports. The collector keeps local hard limits of **400 Streaming Availability attempts per UTC month and 12 per run**, counts attempts before I/O, and retains failures in its ledger. These guards do not establish the provider account's terms, guarantee free capacity or count other consumers of the same API key. No additional availability-provider subscription is introduced. TMDB watch-provider fallback remains deferred pending licensing.

## Publish valid new data without waiting for a whole query

Each complete, validated NEW page commits title snapshots, independent platform events and its next cursor together. An incomplete multi-page query can therefore publish releases already fetched without falsely advancing its completion watermark. A malformed later page leaves earlier valid pages intact and cannot advance its own cursor. Older staged maintenance snapshots cannot overwrite newer title bodies.

Already-downloaded NEW pages from the previous staging policy recover idempotently before network work, including `--export-cached` with no API key or remaining requests. Original query bounds, check times and cursors remain intact. UPDATE/REMOVED windows still apply atomically only after their final page. Completing an old NEW window starts the current due window in the same run when capacity remains.

Per-feed completion is separate from publication. The global complete-update date remains the oldest complete feed; page commits, official fallback, TMDB enrichment and cached publication never make that timestamp current. Empty provider pages do not imply a wholesale deletion. Explicit exact-title/platform removal events remain authoritative.

## Spend the remaining allowance on freshness first

The nominal target is four checks per day in six-hour UTC slots. Conservation protects the highest affordable plan of four/day, two/day (12-hour slots), one/day or sparse capacity. Higher plans allow bounded catch-up of up to six total new-release attempts per UTC day only above their future floor. The normal future emergency reserve is two requests; sparse capacity keeps one, and the final UTC day releases that reserve. Failed calls use the same durable allowance. Capacity pays for pages rather than guaranteed complete catalogue checks.

During conservation or active NEW pagination, maintenance, historical imports and optional reported-title provider lookups wait without resetting progress. The original bulk-import freshness reserve still limits older imports. The report exposes affordable capacity and `capacityInsufficient` rather than claiming a degraded plan meets the nominal target. A new calendar month changes accounting without deleting history. See the exact [budget and cadence policy](catalog-pilot.md#adaptive-monthly-budget).

## Two bounded fallback paths

Reviewed exact-ID entries and automatic SonyLIV checks are merged through the [official-listing policy](official-listings.md). The automatic adapter checks India region, exact movie/series identity, digital-release evidence, full content and subscription entitlement under bounded public-request/time limits. Coming-soon/date/access conflicts fail closed. Unknown audio stays empty. Netflix automatic discovery respects its robots block; reviewed Netflix records remain available until their evidence expires. Neither path fabricates playback verification or complete platform coverage.

Optional `data/title-rechecks.json` provider lookups support legacy Netflix movies and exact JioHotstar movies/series. When normal capacity is available, unresolved reports get at most one lookup per UTC day across all reports; resolved reports stop repeating. Results must match the exact platform ID and content type. Name similarity is insufficient. Audio and weekly dates come from provider evidence. Conservation or a pending NEW query defers these paid-endpoint lookups entirely.

## Incomplete metadata and retained evidence

A valid India offer with unknown audio may appear under All languages. Specific-language, original-audio and description-track filters require explicit matching evidence. Known non-target-only audio and titles without usable offers remain excluded. Original language never establishes dubbing, and a promo's language never establishes every audio track.

Offer availability, audio and original language retain separate source/check fields. Official evidence lasts at most 30 days and is not renewed by a failed or generic-page check. Provider-only audio supplements do not create an offer or overwrite reported audio. Official fallback availability has its own dated proof and is not exported as a streaming departure. Local app/widget caches must refresh to receive updated evidence and removals.

## Independent monitoring and recovery

The collector's report and summary distinguish downloaded, published and staged pages, current capacity, per-feed completion and unchanged maintenance watermarks. A separate six-hour watchdog and post-collector check reuse the published catalogue, original source timestamps and actual GitHub execution heartbeat with **zero Streaming Availability or TMDB requests**. Missing source observations, lag, stalled pagination, known publication gaps and failed publication cannot look healthy.

The previous public health report is optional monitoring context: a temporary failure to download it must not block required catalogue/evidence downloads or ledger recovery. Public snapshot GETs have a bounded transient retry policy; this does not retry movie API calls. The collector can generate new health from its actual run and fresh discovery evidence. An independent watchdog that cannot recover required source observations reports them as unknown rather than treating missing monitoring data as healthy. The catalogue and any companion evidence required to preserve existing official offers still fail closed when unavailable or inconsistent.

The [public status page](https://ottscout.techiwithhelmet.com/data-status/) and one bot-owned GitHub incident show operational causes. Incidents are deduplicated, ordinary changed-signal updates are throttled, a first critical escalation may notify the owner, and closure requires validated recovery. A previous workflow failure remains visible until a completed successor is independently observed; it does not force an otherwise recovered collector into an endless failure loop. Collector, watchdog and publisher serialize publication and incident actions.

A later provider failure may be followed by a separate offline export of earlier valid page commits. The failure remains in health evidence; cached data is not relabelled as a complete update. Private Actions caches remain best-effort storage. Lost ledger state requires operator review, never an automatic quota reset. Monitoring and tests establish bounded behavior, not exhaustive catalogue accuracy or authenticated India playback.
