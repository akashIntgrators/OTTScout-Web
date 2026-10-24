# OTTScout

India-first streaming discovery dashboard. Responsive prototype with movie/series search, seven platform filters, six audio-language filters, weekly sample picks, and a browser-local watchlist.

## Run

`npm run dev`, then open http://localhost:5173.

`npm run check` checks JavaScript syntax. Python 3 is required for the development server; Node.js is required for the check.

## Data status

All titles and availability records are fictional illustrations, visibly labeled in the interface. There is no live streaming API, authentication, email delivery, or background release monitoring. Watchlists persist only in the current browser. Upcoming integration must verify India coverage and platform-specific audio/subtitle availability, distinguish subscription/rental/add-on offers, store source timestamps, and comply with provider licensing and attribution. API keys must remain server-side.

## Product scope

India; English, Hindi, Telugu, Tamil, Kannada, Malayalam; Netflix, Prime Video, Sun NXT, JioHotstar, ZEE5, aha, SonyLIV. Audio filters match any selected language.
