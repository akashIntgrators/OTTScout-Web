# Catalogue reliability

No new provider subscription or availability API is introduced. Existing Streaming Availability request limits and the scheduled cadence remain unchanged. TMDB watch-provider fallback is deferred pending commercial licensing; TMDB metadata enrichment remains as previously configured.

## Incomplete metadata

A valid India offer can be published with an empty audio list. The app displays “Audio languages unverified” under All languages. A specific language, original-audio or description-track filter requires explicit matching evidence. Known non-target-only languages and titles with no current offers remain excluded. Static weekly pages include unknown-audio offers; static language pages do not treat them as language matches.

Each exported offer carries availability source/check time and audio source/check time/status. Original language and audio description remain separate fields. Dated official audio evidence applies only to an exact provider ID with missing audio and expires after 30 days. It does not create an availability offer or overwrite reported audio.

## Recovery and retention

Reported titles in data/title-rechecks.json get at most one bounded lookup per run and at most one lookup per unresolved title per day. Resolved reports stop consuming lookups. Lookups use the same request accounting and limits as scheduled imports. Provider network failures in this optional lookup retain existing records and are cooled down; budget limits still stop requests. Title search results must match the exact Netflix title ID, not only a title string. Weekly dates require provider-reported dates.

Network or malformed-response sync failures cannot replace the public snapshot. The deployed website retains its previous validated data; successful cached publication under a request cap preserves the original streaming and title check timestamps. Empty change pages do not imply wholesale catalogue deletion. Explicit removal data is still respected. Cached data is not silently relabelled as fresh.

## Operator diagnostics

The private pilot report and GitHub Actions summary show unknown audio counts, titles without current offers, titles not checked for seven days, request usage, and reported-title recheck outcomes. These diagnostics do not restore technical banners to the end-user interface. Review older records and unresolved reports before promising complete coverage.

Tests cover unknown-language inclusion/exclusion, offer evidence, stale check timestamps, official evidence expiry/identity, recheck failure cooldown, and preservation of an existing public snapshot after provider failure. No automatic claim is made that a second provider has verified a listing.
