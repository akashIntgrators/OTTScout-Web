# Official OTT listing fallback

`data/official-listings.json` holds reviewed entries for gaps in the streaming API. `official_discovery.py` can also produce bounded, verified SonyLIV records in `data/official-discovered.json`; `official_registry.py` merges them before the local overlay applies. Neither route introduces a paid availability API or extra Streaming Availability/TMDB request. Website-only publication uses existing evidence without re-running discovery or renewing its review times. No general scraper or social-post ingestion is enabled.

## Evidence and publication

Each entry identifies an exact India title page and platform ID, content type, dated release evidence, a post-release review time, and an expiry no more than 30 days after review. Access type requires evidence; audio and original language require separate explicit evidence. A Tamil promo alone does not establish every playable audio track. Unknown fields stay empty. A future announcement cannot turn into a current offer without a review on or after its release date.

The first entry is **Mr & Mrs Office**, JioHotstar ID **1271718279**. Its official title link is paired with Vi Movies & TV's first-party distribution listing for that exact ID and India region. Vi reports 18 November 2026 and Tamil, Hindi, Telugu, Kannada and Malayalam. Subscription inclusion is supported by JioStar's official all-content plan document. This does not claim that every episode requires payment, that every plan/device works, or that OTTScout tested playback. Original language, subtitles and artwork are not inferred from those fields. Placeholder cast/season metadata in a source must not be copied.

The registry also covers **Guarding Stars** (Netflix **81749470**, 18 November), **The Altruists** (Netflix **81681910**, 19 November), and **Lo Chudail Chali Sasural** (SonyLIV **1790007924**, 18 November). All dates are in 2026. Netflix's dated Tudum articles establish release dates; its exact India title pages report English as original audio, plus English, Hindi, Tamil and Telugu tracks. SonyLIV's exact show page reports Hindi, while its dated official trailer establishes the release date. SonyLIV's India subscription FAQ includes Sony SET and SAB shows in its plans; this supports subscription inclusion without claiming every episode requires payment. The Sony original language stays unverified because a Hindi audio track alone does not establish it. Public listings do not constitute an authenticated India playback test.

To add or reverify an entry:

1. Confirm the exact official title ID and India URL, rather than matching only a name.
2. Review current first-party release, access and language evidence. Official authorized-distributor listings are acceptable when they identify the same platform title ID and region.
3. Update the registry's dated facts and evidence URLs; set `verifiedAt` to the actual review time and `expiresAt` no more than 30 days later. Never extend evidence merely because a generic page returns HTTP 200.
4. Run the offline tests and publish through the website workflow. No provider key or API lookup is required for that publication.

Invalid or conflicting records fail closed. Expired or unconfirmed records add no availability offer. Expiry is enforced on every catalogue export and website build, including rebuilding a previously published snapshot. The web dashboard also hides expired official offers. Existing offline phone/TV/widget caches need to refresh to receive removals; evidence expiry is deliberately not exported as a streaming departure (`expiresOn`).

A newer explicit show/platform removal recorded by the provider suppresses older official evidence until it is reviewed again. A missing API offer alone is not treated as a removal: that distinction is what lets the fallback fill genuine coverage gaps.

## Supported automatic discovery

The reviewed source list contains SonyLIV movie/series indexes and a Netflix Tudum lead. The workflow allows at most **12 public requests and 120 seconds** for discovery, with robots checks, cached HTTP responses, response/byte/time bounds, candidate rotation and bounded verification per source. These public requests are separate from the streaming-provider ledger. The adapter inspects only supported exact-title evidence; it does not claim every platform release is covered.

Sony verification requires an exact full movie or series ID and type, explicit India region/contract availability, a recent digital-release date and subscription entitlement. Movie bundles must resolve to a unique full base asset with matching identity and release-announcement evidence. Series require exact parent/first-full-episode evidence. Explicit `comingSoon` conflicts, mismatched dates, ambiguous playable identity, unknown access or unknown region leave candidates unverified and add no fallback offer. Trailer language is not copied as playable audio; only explicit matching track evidence is used. Public metadata still does not constitute an authenticated India playback test.

A confirmed record receives its actual successful review time and expiry no more than 30 days later. Reverification can renew it only after the same strict checks pass again. Robots blocks, network failures, partial scans, generic HTTP 200 responses or contradictory flags cannot extend evidence. Cached valid records may survive a failed scan only until their existing expiry; they are never silently relabelled as freshly verified.

Netflix automatic discovery remains disabled when robots policy blocks the bot; the implementation also requires an enabled, verified region-aware parser before importing Netflix candidates. Reviewed Netflix entries can still be maintained through exact first-party evidence. Prime Video, JioHotstar, ZEE5, Sun NXT and aha have no automatic adapter here; existing manually reviewed registry support is distinct from automatic coverage. The source report records required Sony checks, optional blocked Netflix, unverified candidates and reasons. Independent monitoring reuses those observations without changing their dates.

## Identity and source integrity

Use an existing catalogue ID when the title already has one. For a genuinely missing title, use the explicit internal form `motn:official-hotstar-<ID>`, `motn:official-netflix-<ID>` or `motn:official-sonyliv-<ID>`. The `motn:` prefix is a legacy client format; the `official-` marker identifies an OTTScout-curated record and is not a fabricated upstream provider ID.

Exact platform IDs deduplicate later API records. Learned provider-ID aliases persist in the private SQLite metadata and public snapshot independently of evidence expiry or registry removal. This keeps saved titles stable without rewriting provider-owned database rows. Provider availability takes priority when the exact offer is present. Other platforms and their dates stay separate. Curated identity edits invalidate stale metadata matches; unchanged entries retain independent TMDB enrichment.

Official offers carry their real source URL, review/expiry times, reported-audio evidence and day-precision release date. They do not advance the provider's complete-update watermark or invent a provider detection timestamp. The legacy weekly event uses the release day's IST date with explicit official-source metadata. The compact widget feed retains its existing schema. Poster images are omitted unless a separately supported source is available.

The website labels official offers and links the underlying evidence on title pages. Catalogue-level credits distinguish provider data, official listings and TMDB metadata. No live advertising settings are changed by this fallback.
