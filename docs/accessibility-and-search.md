# Accessibility, search and audio description

Search improvements include canonical URLs, descriptive titles, crawlable static title/language pages, breadcrumbs and truthful WebSite/WebPage/Movie/TVSeries structured data. They do not guarantee search position. No ratings or offers are invented.

The dashboard uses native controls, visible focus, a skip link, debounced result announcements and deliberate focus recovery after removing cards. The single-character search shortcut is opt-in. Analytics consent remains opt-in and its notice is inline to avoid covering focus.

`data/audio-description.json` contains manually reviewed official provider-page reports. Reports attach only to the exact Netflix provider ID and media type. Ordinary audio, subtitles and TMDB metadata never imply audio description. Reports older than 30 days are excluded from the dashboard. Public Netflix pages may regionalize; India playback is explicitly unverified. The static directory retains dated evidence and asks readers to check older reports directly.

Automated tests cover trusted source identity, expiry, safe structured data, semantic HTML, filters and consent. Local axe scans and keyboard checks complement them. These checks do not establish WCAG conformance; blind-user and screen-reader testing remain needed.
