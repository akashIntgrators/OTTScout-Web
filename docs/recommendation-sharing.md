# Shared movie recommendations

The phone share sheet sends a public link such as `https://ottscout.techiwithhelmet.com/?recommend=motn%3A42`. It contains a catalogue ID only: no account identifiers, watchlist contents, contacts or sender identity.

The recipient reviews the actual title from the loaded live catalogue. **Add to my watchlist** saves into the recipient's current account or browser guest list. An already-saved title remains saved. **Decline** closes the review and changes nothing. Opening the link never saves automatically, resets filters, or launches a native application. **Open in OTTScout app** is an explicit `ottscout://recommend/...` link for a compatible installed version.

The URL is not an authenticated personal invitation. Anyone holding it can review that public title. There is no friend inbox, delivery tracking, acceptance receipt, notification, or change to another person's private watchlist. Choices stay private to the recipient. No Firestore rules or collections are changed.

If sign-in restoration is still pending, approval waits for the watchlist session. Storage and account-deletion guards stay in force. Failed saves leave the recommendation visible with an error; unknown catalogue IDs do not fall back to similar names or samples. Account switches during approval do not report success for the new account.

The receiver module is copied into the production site under `/web/recommendation-links.js`. `tests/recommendation_links.mjs` covers strict IDs, no implicit writes or app launches, explicit approval, duplicate/already-saved decisions, declines, failures, account changes and deletion guards.

A future authenticated friend inbox would need verified identities, recipient-only decisions, abuse controls, expiry and deletion handling, with separately reviewed database rules. It must retain the rule that a sender cannot directly edit a recipient's saved titles.
