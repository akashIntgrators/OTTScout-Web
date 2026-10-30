# OTTScout

The approved mint double-ring identity is shared across website headers, browser and home-screen icons, link previews and the native prototypes. See [brand assets and regeneration](docs/branding.md).

India-first movie and series discovery, hosted on GitHub Pages at http://ottscout.techiwithhelmet.com/. Supports seven OTT filters, six audio languages, positive checkbox filters, All / Movies / Series, a seven-day additions feed, and a browser-local watchlist. The slate-and-mint interface follows the Integration Labs palette, with reserved advertisement placements.

## Live catalog pilot

The six-hour collector, SQLite state, usage reports, and conditional Pages publication are implemented. Activation requires an API secret and an initial manual run. The website uses clearly labelled sample titles until a validated catalog is published. See [pilot setup and limitations](docs/catalog-pilot.md).

Initial live scope is a popular-title sample plus subsequent show-level changes; full catalogs, episode tracking, email alerts, and cross-device accounts are future work. Coverage of all seven OTTs is not guaranteed and is checked against the provider. Audio and subtitles are offer-specific; unknown dubbing is not inferred.

## Development

`npm run dev` starts the root website at http://127.0.0.1:5174. `npm run check` checks browser JavaScript. `npm test` runs offline collector tests. `npm run build` stages public files in `.site/`.

The root index.html, app.js, style.css, and assets/ are canonical. The older dist/ directory is a legacy uploaded prototype; the current scripts and Pages deployment do not use it.

API secrets, `.state/` database files, and reports are excluded from Git. The pilot uses best-effort GitHub Actions cache for state and stops provider calls after 30 days; production needs durable database storage. Only the curated end-user catalog may be published after validation and provider-terms review.
