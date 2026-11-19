# Catalogue reliability

No new provider subscription or availability API is introduced. Existing Streaming Availability request limits and the scheduled cadence remain unchanged. TMDB watch-provider fallback is deferred pending commercial licensing; TMDB metadata enrichment remains as previously configured.

Reported gaps can also be filled from the reviewed [official-listing registry](official-listings.md). This local overlay requires exact platform identities and dated first-party evidence, expires stale entries, preserves watchlist aliases, and uses no API requests. Official release dates and audio evidence remain distinct from provider detection and metadata.

## Incomplete metadata

A valid India offer can be published with an empty audio list. The app displays “Audio languages unverified” under All languages. A specific language, original-audio or description-track filter requires explicit matching evidence. Known non-target-only languages and titles with no current offers remain excluded. Static weekly pages include unknown-audio offers; static language pages do not treat them as language matches.

Each exported offer carries availability source/check time and audio source/check time/status. Original language and audio description remain separate fields. Dated official audio evidence applies only to an exact provider ID with missing audio and expires after 30 days. It does not create an availability offer or overwrite reported audio.

## Recovery and retention

Reported titles in data/title-rechecks.json get at most one bounded lookup per run and at most one lookup per UTC day across all unresolved reports. Legacy Netflix movie reports and exact JioHotstar movie/series reports are supported. Resolved reports stop consuming lookups. During quota conservation, a reported-title lookup shares the same two-request daily allowance as new-feed pages, and unresolved reports wait seven days between attempts. Provider network failures retain existing records and are cooled down; budget limits still stop requests. Reports must identify an exact title ID using its canonical official platform URL. Provider results must match that platform, title ID and content type; a similar title string is insufficient. Audio and weekly dates come from the provider result, not from an inferred premiere date or dubbed-language list.

Network or malformed-response sync failures cannot replace the public snapshot. The deployed website retains its previous validated data; successful cached publication under a request cap preserves the original streaming and title check timestamps. Empty change pages do not imply wholesale catalogue deletion. Explicit removal data is still respected. Cached data is not silently relabelled as fresh.

## Operator diagnostics

The private pilot report and GitHub Actions summary show unknown audio counts, titles without current offers, titles not checked for seven days, request usage, and reported-title recheck outcomes. These diagnostics do not restore technical banners to the end-user interface. Review older records and unresolved reports before promising complete coverage.

Tests cover unknown-language inclusion/exclusion, offer evidence, stale check timestamps, official evidence expiry/identity, recheck failure cooldown, and preservation of an existing public snapshot after provider failure. No automatic claim is made that a second provider has verified a listing.
