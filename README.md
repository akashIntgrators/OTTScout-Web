# OTTScout

India-first movie and series discovery, hosted on GitHub Pages at https://ottscout.techiwithhelmet.com/. Browse platform additions, search the imported catalogue, filter by platform/audio/original language/genre, and save titles. Guest saves stay in the browser; optional accounts sync saved title IDs across devices. Advertisement placements remain reserved space.

The approved mint double-ring identity is shared across website headers, browser and home-screen icons, link previews and the native prototypes. See [brand assets and regeneration](docs/branding.md).

## Development

Use **Node.js 24.12 or later** and Python 3. Firebase's browser SDK is pinned to `13.2.0`; the lockfile pins the build dependencies.

```sh
npm ci
npm run dev
```

The local dashboard opens at http://127.0.0.1:5174. `npm run check` checks browser JavaScript; `npm test` runs catalogue, website, privacy and account-sync regressions; `npm run build` bundles the local Firebase SDK and stages the public website in `.site/`. No Firebase CDN script is required.

The root `index.html`, `app.js`, `style.css`, `web/` and `assets/` are canonical. The older `dist/` directory is a legacy prototype and is not used by the current deployment. Generated `account.js`, `.site/`, `node_modules/`, API secrets, `.state/` and reports are excluded from Git.

## Optional accounts

Accounts use Firebase Authentication (Google or email/password) and Cloud Firestore on the **Spark plan**. No billing upgrade, Cloud Functions or phone/SMS sign-in is part of this setup. Browsing and guest watchlists work when account configuration is unavailable.

To configure another deployment:

1. Register a Firebase web app. Put its public SDK fields in `firebase-config.json`: `apiKey`, `authDomain`, `projectId`, `appId`, and optionally `storageBucket`, `messagingSenderId` or `measurementId`. This Firebase API key identifies the public app; never put a service-account/private key, streaming-provider key or TMDB token in this file. The build rejects extra fields, including native-only `googleWebClientId`.
2. Enable Google and Email/Password in Firebase Authentication. Configure Google's public support address and authorize the website hostname and intended local development hosts.
3. Create the Firestore database and publish the reviewed owner-only rules **separately**. The rules source, deployment record and emulator tests live in the sibling `OTTScout-Firebase` project. Publishing GitHub Pages does not deploy those rules. Do not use open test-mode database rules.
4. Run the website build, then verify sign-in and sync on the published hostname. Missing/invalid account configuration leaves guest browsing available.

Only watchlist title IDs, saved/removed status and server update times sync. Each account has a separate device cache and durable pending changes; sign-out restores the separate guest list. Valid guest saves are imported once per account on a device, without restoring a cloud removal marker. Filters, searches, analytics consent and advertising choices are not synced. One browser tab owns the account queue; another tab is read-only until the first closes and **Retry sync** takes over. A writable offline queue remains available.

Account deletion requires recent sign-in, creates an irreversible deletion marker, removes cloud watchlist documents, then deletes the Auth account. The minimal marker is retained to block old sessions from recreating saves; interrupted cleanup can be retried. The published [privacy page](https://ottscout.techiwithhelmet.com/privacy/) explains this retention.

## Account testing

For local browser integration, start `npm run emulators` in `OTTScout-Firebase` (Node 24.12+ and Java 21+). It uses project `demo-ottscout`, Auth `127.0.0.1:9099` and Firestore `127.0.0.1:8085`. Create an ignored `firebase-config.local.json` with only dummy public SDK fields for that demo project, then run:

```sh
npm run dev:auth-emulator
```

Open http://127.0.0.1:5174/?auth-emulator=1. Emulator mode requires both the explicit development build and a loopback hostname. The production build excludes the local fixture, test project and emulator endpoints.

Validated locally on **4 November 2026**: JavaScript checks, **62 repository tests**, and the production website build passed. Browser checks against local Auth/Firestore emulators covered signup/sign-in, reset feedback, guest import, reload, sign-out, account separation, cross-session additions/removals and tab takeover. These checks do not establish production Google sign-in or full screen-reader conformance; published-host authentication and responsive visual checks are recorded separately.

## Live catalogue pilot

The six-hour collector, SQLite state, usage reports and conditional Pages publication are implemented. See [pilot setup and limitations](docs/catalog-pilot.md). The dashboard falls back to labelled sample titles when no validated public catalogue can be loaded.

Coverage is gradually imported and incomplete; provider support is checked rather than assumed. Audio/subtitles are offer-specific, original language is separate, and unknown dubbing is not inferred. Episode tracking and release email alerts are future work. Provider secrets remain in GitHub Actions, and private collector state must not be published with the website.
