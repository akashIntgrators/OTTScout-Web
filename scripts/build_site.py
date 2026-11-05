"""Build the public dashboard and crawlable discovery pages from the validated snapshot."""
from pathlib import Path
from html import escape
from urllib.parse import urlparse, quote, urlencode
import json
import math
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone, timedelta
try:
    from scripts.site_features import apply_reports, valid_reports, netflix_id, schema_graph, json_script, language_label
except ModuleNotFoundError:
    from site_features import apply_reports, valid_reports, netflix_id, schema_graph, json_script, language_label

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://ottscout.techiwithhelmet.com'
LANGUAGES = ('English', 'Hindi', 'Telugu', 'Tamil', 'Kannada', 'Malayalam')
WIDGET_PLATFORMS = ('Netflix', 'Prime Video', 'Sun NXT', 'JioHotstar', 'ZEE5', 'aha', 'SonyLIV')
WIDGET_OFFER_TYPES = ('subscription', 'free', 'rent', 'buy', 'addon')
WIDGET_POSTER_HOSTS = ('cdn.movieofthenight.com', 'www.movieofthenight.com', 'image.tmdb.org')
WIDGET_MAX_TITLES = 3000
WIDGET_MAX_BYTES = 2_000_000
IST = timezone(timedelta(hours=5, minutes=30))

PRIVACY_CONTENT = '''
<p>OTTScout is an independent streaming-discovery project maintained by Akash. This notice covers the OTTScout website and Android apps. For private account or privacy questions, email <a href="mailto:akashashok8960@gmail.com">akashashok8960@gmail.com</a>. Use <a href="/contact/">GitHub</a> for public catalogue corrections.</p>
<nav class="seo-nav" aria-label="Privacy topics"><a href="#device-storage">Device storage</a><a href="#accounts">Accounts</a><a href="#external-services">External services</a><a href="#analytics-ads">Analytics and ads</a><a href="#retention-deletion">Retention and deletion</a></nav>
<h2 id="device-storage">Saved on your device</h2>
<p>On the website, guest watchlists, filters, colour theme, optional keyboard shortcut choice and dismissed titles are saved in local browser storage. Clearing website data removes those local preferences, account caches and changes not yet synced.</p>
<p>On Android, the app saves a catalogue snapshot in its own files for offline browsing. Guest watchlists, appearance preferences, per-account watchlist caches and pending saved-title changes use local app storage. Phone sign-in sessions use Expo SecureStore, backed by Android encrypted storage. Signing out restores the separate guest watchlist; it does not copy account saves into that list.</p>
<p>The optional Android phone home-screen widget stores a public weekly-catalogue snapshot and your selected platforms, audio languages and movie/series preference in private app storage. It does not read your account, sign-in credentials or watchlist. While a widget is placed, background work can download the public weekly feed and poster images, approximately every six hours; Android can delay these updates. These requests reach GitHub Pages and image hosts as described below. Widget selections stay on your device; the widget adds no analytics or advertising requests.</p>
<p>Clearing Android app storage or uninstalling can remove local saves, preferences and unsynced changes. Uninstalling does not delete an online OTTScout account. Android TV currently uses guest saves only.</p>
<h2 id="accounts">Optional accounts and sync</h2>
<p>You can browse without an account. Optional Google or email/password sign-in on the website and Android phone uses Google Firebase Authentication. Firebase handles your email address, authentication identifiers, sign-in provider and profile information supplied through Google sign-in. Passwords are handled by Firebase and are not stored in the OTTScout catalogue. The website retains its Firebase sign-in session in browser storage until you sign out or clear website data.</p>
<p>When signed in, saved title IDs, saved or removed status and server update times are stored under your account in Google Cloud Firestore to sync your watchlist. A removed title keeps a private removal marker so an older device does not restore it. Valid guest saves are imported once per account on a device when no cloud entry exists. Account caches and pending changes stay separate from other accounts and from guest saves.</p>
<p>Filters, searches, catalogue contents, website analytics consent and advertising choices are not written to your cloud watchlist. Firebase receives the connection information needed to authenticate and sync. See <a href="https://firebase.google.com/support/privacy">Firebase privacy information</a> and <a href="https://policies.google.com/privacy">Google’s privacy policy</a>.</p>
<h2 id="external-services">Connections to other services</h2>
<p>GitHub Pages hosts the website and public catalogue snapshot. Requests for these files can provide connection information such as your IP address and request details to GitHub. See <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub’s privacy statement</a>. Poster, provider-logo and attribution images may load from external hosts, which receive the connection information needed to deliver them.</p>
<p>Links to streaming services, TMDB and GitHub open services with their own privacy practices. OTTScout does not receive your streaming-service password or payment details through those links. A correction report is published only when you choose to submit it on GitHub; public issues should not contain private account information.</p>
<h2 id="analytics-ads">Analytics and advertising</h2>
<p>Website Google Analytics is optional and loads only after you choose Allow analytics. It measures page visits and device/browser information; Google receives connection information such as your IP address. Our page-view event excludes search terms, filters, watchlist contents, URL query strings and referrers. Automatic enhanced measurement and advertising signals are disabled. Your choice stays in this browser. Use Analytics choices in the footer, then No thanks, to stop future measurement and remove analytics cookies set for this host. This does not erase previously collected data. Browsers signalling Do Not Track or Global Privacy Control are not prompted automatically.</p>
<p>The native Android apps do not include a separate product-analytics integration. Ad-free Android Play testing builds exclude the Google Mobile Ads SDK and make no advertising requests. Android TV also excludes that SDK. The older 0.4.0 Android phone developer test build includes Google demo ads: its SDK makes test-ad requests and may process connection, device and ad-request information even though requests are non-personalized and cannot earn revenue. The website’s advertisement boxes are reserved space, not live ads. A future live-ad release will need updated disclosures.</p>
<h2 id="retention-deletion">Retention and account deletion</h2>
<p>Cloud watchlist entries, including saved and removed status, stay associated with your account until account deletion. Unsaving a title changes its status; the removal entry remains so older saves do not restore it. Local cached data stays on a device until replaced, cleared or removed. Sign out on shared devices. Only one website tab at a time writes an account cache; guest browsing remains available when a browser cannot safely write account saves.</p>
<p>Use <a href="/delete-account/">Delete your OTTScout account</a> for browser and Android instructions or an email request route. You do not have to reinstall the app. Account deletion reauthenticates you, removes the Firebase Authentication account and its cloud watchlist, and clears the account cache on the device completing deletion. Separate guest saves are kept. Account deletion does not remotely erase local copies on other devices. Clear OTTScout’s app or website storage on those devices to remove those copies. Signing out stops active account access but can retain a local account cache.</p>
<p>A minimal private deletion record containing the account ID, deletion status and server time is retained to stop old sessions from recreating watchlist data. It currently has no automatic expiry. If deletion is interrupted, sign in to the same account and finish deletion; the record blocks new cloud saves while cleanup is pending. Deleting an OTTScout account does not erase records retained by Google or GitHub under their own policies, or previously collected optional website analytics.</p>
<h2>Contact about your data</h2>
<p>Email <a href="mailto:akashashok8960@gmail.com">akashashok8960@gmail.com</a> for account deletion or private data questions. We may need to verify that a request concerns your account. Never send a password. General product feedback and catalogue corrections can use our <a href="/contact/">public GitHub contact route</a>.</p>
'''

DELETION_CONTENT = '''
<p>You can delete the optional account used by OTTScout on Android or the website, together with its online watchlist. This page is available without signing in or installing the app.</p>
<p><a href="/#account-button">Open OTTScout</a>, then choose Sign in or Account. If you cannot access your account, <a href="#request-by-email">request deletion by email</a>.</p>
<h2>Delete through the website</h2>
<ol><li>Open OTTScout and choose Sign in. Use the same Google account or email/password sign-in method you used in the app. If already signed in, choose Account.</li><li>Inside Account, open Delete account.</li><li>Confirm your current email password or reauthenticate with Google. Select the deletion confirmation and choose Confirm account deletion.</li><li>If cleanup is interrupted, sign in to the same account again and choose Finish account deletion. New cloud saves are blocked while deletion is pending.</li></ol>
<p>The website and Android phone share accounts. Deleting the same account through the website also removes that account’s online Android watchlist. Deleting an OTTScout account does not delete your Google account.</p>
<h2>Delete through the Android app</h2>
<p>Open Account, choose Delete account, confirm your password or Google account and approve Delete account. Internet access and a fresh sign-in are required. If you removed the app already, use the website or email route on this page.</p>
<h2 id="request-by-email">Request deletion by email</h2>
<p>Send an <a href="mailto:akashashok8960@gmail.com?subject=OTTScout%20account%20deletion%20request">OTTScout account deletion request to akashashok8960@gmail.com</a>. Say that you want your OTTScout account and associated online watchlist deleted. Send from the email address used for sign-in where possible. If you cannot access that address, explain that in your request so we can discuss how to verify account ownership.</p>
<p>We may ask you to confirm ownership before processing a request. Never email your password or publish account details in a GitHub issue. An email request is reviewed and is not an automatic deletion.</p>
<h2>What deletion removes</h2>
<ul><li>Your OTTScout Firebase Authentication account.</li><li>Your account’s online watchlist, including saved title IDs, saved/removed status and update times.</li><li>The local account cache on the browser or app completing self-service deletion.</li></ul>
<h2>What remains</h2>
<p>A minimal private record of the account ID, deletion status and server time remains to prevent old sessions from recreating saved titles. There is currently no automatic expiry for this record. Separate guest saves are kept. Account deletion does not remotely erase local copies on other devices. Clear OTTScout’s app or website storage on those devices to remove those copies. Signing out stops active account access but can retain a local account cache. Google and GitHub can retain service records under their own policies; previously collected optional website analytics is separate from account deletion. Read the <a href="/privacy/">OTTScout privacy notice</a> for details.</p>
<h2>If you only used guest mode</h2>
<p>There is no OTTScout cloud account to delete. Remove guest saves through the watchlist, or clear OTTScout’s website data or Android app storage. Clearing storage also removes local preferences and unsynced changes. Uninstalling the Android app can remove its local data, but does not delete an online account if you created one.</p>
'''

def checked_date(value, now):
    if not isinstance(value, (int, float)) or value <= 0 or value > now:
        return 'Unverified'
    return datetime.fromtimestamp(value, IST).strftime('%d %b %Y')

def older_movie(title, now):
    year = title.get('year')
    return title['type'] == 'Movie' and type(year) is int and 1800 < year < datetime.fromtimestamp(now, IST).year

def weekly_offer_date(title, offer, now):
    events = title.get('weeklyEvents')
    added = next((e.get('addedAt') for e in events if e.get('platform') == offer['platform']), None) if isinstance(events, list) else title.get('weeklyUpdatedAt') if offer['platform'] in title.get('weeklyPlatforms', []) else None
    if not isinstance(added, (int, float)) or not now-7*86400 <= added <= now:
        return None
    since = offer.get('availableSince')
    if isinstance(since, (int, float)) and since > 0:
        return since if now-7*86400 <= since <= now else None
    return added

def original_label(value):
    return language_label(value)

def title_path(title):
    return '/titles/' + quote(title['id'][5:], safe='') + '/'

def safe_link(value):
    parsed = urlparse(value or '')
    return value if parsed.scheme == 'https' and parsed.netloc else ''

def widget_poster(value):
    """Only public image CDNs; a widget must not fetch arbitrary remote hosts."""
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        parsed = urlparse(value)
        if (parsed.scheme == 'https' and parsed.hostname in WIDGET_POSTER_HOSTS
                and parsed.port in (None, 443) and not parsed.username and not parsed.password):
            return value
    except ValueError:
        pass
    return None

def widget_feed(catalog, now):
    """Derive public weekly offers, never account data or new provider requests.

    A feed is intentionally independent of viewer preferences: Android applies
    selected languages and platforms locally. Each offer retains its own audio,
    rental type, addition date and expiry so one platform cannot supply another
    platform's language or date. Android rechecks dates when rendering offline.
    """
    def timestamp(value):
        return type(value) in (int, float) and math.isfinite(value) and value > 0

    if (not isinstance(catalog, dict) or not isinstance(catalog.get('titles'), list)
            or not isinstance(catalog.get('updatedAt'), str) or not timestamp(now)):
        raise ValueError('Invalid catalogue for widget feed')
    try:
        datetime.fromisoformat(catalog['updatedAt'].replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid widget source timestamp') from error
    coverage = catalog.get('coverage', [])
    missing = catalog.get('missingPlatforms', [])
    if (not isinstance(coverage, list) or not isinstance(missing, list)
            or any(not isinstance(value, str) for value in coverage + missing)):
        raise ValueError('Invalid widget platform coverage')
    present = {offer.get('platform') for title in catalog['titles'] for offer in title.get('offers', [])}
    platforms = [name for name in WIDGET_PLATFORMS if name in coverage and name not in missing and name in present]
    titles = []
    seen = set()
    for title in catalog['titles']:
        offers = []
        for offer in title.get('offers', []):
            if offer.get('platform') not in platforms:
                continue
            added = weekly_offer_date(title, offer, now)
            expiry = offer.get('expiresOn')
            if not timestamp(added) or (timestamp(expiry) and expiry <= now):
                continue
            if expiry is not None and not timestamp(expiry):
                raise ValueError('Invalid widget offer expiry')
            audio = offer.get('audio')
            if (offer.get('type') not in WIDGET_OFFER_TYPES or not isinstance(audio, list)
                    or len(audio) > 200 or any(not isinstance(value, str) or not value.strip() or len(value) > 200 for value in audio)):
                raise ValueError('Invalid widget offer')
            if audio and not any(language in LANGUAGES for language in audio):
                continue
            offers.append({'platform': offer['platform'], 'type': offer['type'],
                           'audio': list(dict.fromkeys(audio)), 'addedAt': added, 'expiresOn': expiry})
        if not offers:
            continue
        ident = title.get('id')
        name = title.get('title')
        if (not isinstance(ident, str) or len(ident) > 100 or not re.fullmatch(r'motn:[a-zA-Z0-9-]+', ident)
                or ident in seen or title.get('type') not in ('Movie', 'Series')
                or not isinstance(name, str) or not name.strip() or len(name) > 1000 or len(offers) > 100):
            raise ValueError('Invalid widget title')
        seen.add(ident)
        row = {'id': ident, 'title': name, 'type': title['type'], 'offers': offers}
        poster = widget_poster(title.get('poster'))
        if poster:
            row['poster'] = poster
        titles.append(row)
    titles.sort(key=lambda title: (-max(offer['addedAt'] for offer in title['offers']), title['title'].casefold(), title['id']))
    feed = {'schemaVersion': 1, 'country': 'IN', 'updatedAt': catalog['updatedAt'],
            'generatedAt': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'coverage': platforms, 'titles': titles}
    encoded = json.dumps(feed, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    # A failed build keeps the last successful deployment. Never silently trim
    # later titles, which would make language/platform filtering incomplete.
    if len(titles) > WIDGET_MAX_TITLES or len(encoded) > WIDGET_MAX_BYTES:
        raise ValueError('Widget feed exceeds its bounded size')
    return encoded

def build(root=ROOT, now=None):
    now = int(time.time()) if now is None else now
    target = root / '.site'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    for name in ('index.html', 'app.js', 'style.css', 'CNAME'):
        shutil.copy2(root / name, target / name)
    if (root / 'web/account.js').exists():
        subprocess.run(['node', str(root / 'scripts/build-auth.mjs'), str(target / 'account.js')], cwd=root, check=True)
    if (root / 'firebase-config.json').exists():
        config = json.loads((root / 'firebase-config.json').read_text())
        allowed = {'apiKey','authDomain','projectId','storageBucket','messagingSenderId','appId','measurementId'}
        if not isinstance(config, dict) or set(config) - allowed or not all(isinstance(config.get(key), str) and config[key] for key in ('apiKey','authDomain','projectId','appId')):
            raise ValueError('firebase-config.json must contain only public Firebase web SDK configuration')
        (target / 'firebase-config.json').write_text(json.dumps(config, indent=2) + '\n')
    if (root / 'theme.js').exists():
        shutil.copy2(root / 'theme.js', target / 'theme.js')
    if (root / 'analytics.js').exists():
        shutil.copy2(root / 'analytics.js', target / 'analytics.js')
    if (root / 'favicon.ico').exists():
        shutil.copy2(root / 'favicon.ico', target / 'favicon.ico')
    for name in ('assets', 'data'):
        if (root / name).exists():
            shutil.copytree(root / name, target / name)
    (target / '.nojekyll').touch()
    reports_path = root / 'data/audio-description.json'
    report_file = json.loads(reports_path.read_text()) if reports_path.exists() else {'schemaVersion':1,'reports':[]}
    if report_file.get('schemaVersion') != 1 or not isinstance(report_file.get('reports'),list):
        raise ValueError('Invalid audio-description registry')
    reports = valid_reports(report_file['reports'],now)
    homepage = target / 'index.html'
    homepage.write_text(homepage.read_text().replace('<!-- SEO:STRUCTURED_DATA -->', json_script(schema_graph('/', 'OTTScout — Where to watch movies and series in India', 'Compare OTT platforms, audio languages and sourced audio-description reports in India.'))))
    theme_script = '<script src="/theme.js?v=rail22"></script>' if (root / 'theme.js').exists() else ''
    urls = ['/']
    navigation = '<a href="/">Dashboard</a><a href="/this-week/">This week</a>' + ''.join(f'<a href="/languages/{lang.lower()}/">{lang}</a>' for lang in LANGUAGES)
    navigation += '<a href="/audio-description/">Audio description</a><a href="/accessibility/">Accessibility help</a>'
    def page(path, title, description, content, work=None):
        canonical = BASE + path
        structured = json_script(schema_graph(path,title,description,work))
        markup = f'''<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} | OTTScout</title><meta name="description" content="{escape(description,quote=True)}">
<link rel="canonical" href="{canonical}"><meta property="og:title" content="{escape(title,quote=True)}">
<meta property="og:description" content="{escape(description,quote=True)}"><meta property="og:url" content="{canonical}">
<meta property="og:type" content="website"><meta property="og:site_name" content="OTTScout">
<meta property="og:image" content="{BASE}/assets/ottscout-social.png?v=brand14"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:alt" content="OTTScout — Find it. Save it. Watch it.">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{BASE}/assets/ottscout-social.png?v=brand14"><meta name="twitter:image:alt" content="OTTScout — Find it. Save it. Watch it.">
<link rel="icon" href="/favicon.ico?v=brand14" type="image/x-icon"><link rel="icon" href="/assets/ottscout-icon.svg?v=brand14" type="image/svg+xml"><link rel="icon" href="/assets/ottscout-icon.png?v=brand14" type="image/png"><link rel="apple-touch-icon" href="/assets/ottscout-touch-icon.png?v=brand14"><meta name="apple-mobile-web-app-title" content="OTTScout">
{structured}{theme_script}<link rel="stylesheet" href="/style.css?v=rail22"></head><body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header"><a class="brand" href="/" aria-label="OTTScout home"><img class="brand-mark" src="/assets/ottscout-mark.svg?v=brand14" width="36" height="36" alt="">OTT<span>Scout</span></a><span class="region">Streaming in India</span><button class="theme-toggle" type="button" aria-label="Switch to light mode"><span class="sun-icon" aria-hidden="true">☼</span><span class="moon-icon" aria-hidden="true">◐</span></button></header>
<nav class="seo-nav seo-navigation" aria-label="Browse streaming">{navigation}</nav><main id="main" class="seo-page" tabindex="-1">
<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">OTTScout</a><span aria-hidden="true"> / </span><span aria-current="page">{escape(title)}</span></nav>
<h1>{escape(title)}</h1><p class="seo-description">{escape(description)}</p>{content}
<section class="credits" aria-label="Data credits"><h2>Data credits</h2><a href="https://www.themoviedb.org"><img src="https://www.themoviedb.org/assets/2/v4/logos/v2/blue_square_2-d537fb228cf3ded904ef09b136fe3fec72548ebc1fea3fbbd1ad9e36364db38b.svg" width="56" height="40" alt="TMDB"></a><p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p></section></main>
<footer class="seo-footer"><a class="brand" href="/" aria-label="OTTScout home"><img class="brand-mark" src="/assets/ottscout-mark.svg?v=brand14" width="36" height="36" alt="">OTT<span>Scout</span></a><nav class="seo-nav" aria-label="Site information"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/delete-account/">Delete account</a><a href="/audio-description/">Audio description</a><a href="/accessibility/">Accessibility help</a><a href="/guides/telugu-weekend-picks/">Weekend picks</a></nav><p>India · Availability may change. Audio and subtitles vary by platform.</p><a href="https://www.movieofthenight.com/about/api">Streaming data by Movie of the Night</a></footer><script src="/analytics.js?v=2" defer></script></body></html>'''
        dest = target / path.strip('/') / 'index.html'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markup, encoding='utf-8')
        urls.append(path)
    info_nav = '<nav class="seo-nav" aria-label="About OTTScout"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/delete-account/">Delete account</a><a href="/guides/telugu-weekend-picks/">Weekend picks</a></nav>'
    page('/about/', 'About OTTScout', 'An independent guide to streaming movies and series in India.', '<h2>Find something worth watching</h2><p>OTTScout helps you compare platform availability, audio languages and original-language metadata, then follow a link to the streaming service. We do not host movies or sell streaming subscriptions.</p><p>We focus on English, Hindi, Telugu, Tamil, Kannada and Malayalam. The current feed covers Netflix, Prime Video, JioHotstar, ZEE5 and SonyLIV. Imported coverage is partial and availability can change.</p><h2>How the catalogue works</h2><p>Movie of the Night supplies streaming offers and audio options. TMDB supplies matched original languages and genres. Uncertain matches stay unverified. Audio availability and original language are separate: a Telugu original may only have Hindi audio on a particular platform.</p><p>Updates are scheduled approximately every six hours, subject to provider quotas and scheduler delays. Provider-reported additions are not necessarily premieres. Always confirm the offer on the streaming service.</p><p>This independent project is maintained by <a href="https://github.com/akashIntgrators">Akash</a>. Browse as a guest with browser-local saves, or optionally sign in to sync your watchlist.</p>' + info_nav)
    page('/contact/', 'Contact and corrections', 'Help improve OTTScout through our public GitHub issue tracker.', '<h2>Found something incorrect?</h2><p>Use “Report incorrect details” on a title, or <a href="https://github.com/akashIntgrators/OTTScout-Web/issues/new">open a GitHub issue</a> for feedback and general enquiries. Include the title, streaming platform, language and a source link where possible.</p><p>GitHub requires an account. Issues are public: please do not include passwords, API keys, billing details or other private information. You can review the report before submitting.</p><p>We welcome corrections, feature suggestions and questions about the project.</p>' + info_nav)
    page('/privacy/', 'Privacy at OTTScout', 'How the OTTScout website and Android apps handle accounts, saved titles and device data. Updated 6 November 2026.', PRIVACY_CONTENT + info_nav)
    page('/delete-account/', 'Delete your OTTScout account', 'Delete your optional OTTScout account and online watchlist through the website, Android app or a private email request.', DELETION_CONTENT + info_nav)
    page('/accessibility/', 'Accessibility help for OTTScout', 'Keyboard navigation, screen-reader support and audio-description discovery on OTTScout.', '<h2>Use the dashboard with a keyboard</h2><ul><li>Use the Skip to titles link to reach the results.</li><li>Press Tab and Shift+Tab to move between controls. Enter opens links; Enter or Space operates buttons and checkboxes.</li><li>Filter menus use native expandable controls. Press Escape to close an open filter and return to its heading.</li><li>Result counts are announced after filters change. Switching views moves focus to the results heading. Hiding a title or removing it from a watchlist moves focus to the next title when possible.</li><li>The optional / search shortcut is off by default. Enable it in <a href="/#accessibility-options">Keyboard options</a> if it works with your assistive technology.</li></ul><h2>Read without the interactive dashboard</h2><p>The <a href="/this-week/">text weekly feed</a>, language pages and title details use ordinary headings, lists and links and work without JavaScript. The dashboard uses JavaScript for filtering and browser-local watchlists.</p><h2>Find description tracks</h2><p><a href="/audio-description/">Read the audio-description guide</a> for provider-reported candidates, description languages and check dates. A spoken website, subtitles, a dubbed track and a film’s audio-description track are different things.</p><h2>Current limitations and feedback</h2><p>Source data and description-track coverage are incomplete. India playback is not independently verified. Automated checks and keyboard tests do not establish full accessibility conformance; testing with blind users and a range of screen readers is still needed.</p><p>If a control or page is difficult to use, <a href="https://github.com/akashIntgrators/OTTScout-Web/issues/new">report an accessibility issue on GitHub</a>. Include the page and the browser/screen reader you use. GitHub reports are public; avoid personal information. We welcome feedback on focus order, labels and announcements.</p>' + info_nav)
    source = target / 'data/catalog.json'
    if source.exists():
        catalog = apply_reports(json.loads(source.read_text()),reports)
        source.write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
        (target / 'data/widget.json').write_bytes(widget_feed(catalog, now))
        titles = catalog['titles']
        updated = escape(catalog.get('updatedAt', 'Unknown'))
        note = f'<p class="seo-note">Snapshot updated: {updated}. Imported catalogue coverage is limited; this is not an exhaustive list. Provider-reported additions are not confirmed OTT premiere dates.</p>'
        def offers_for(title, language=None, weekly=False):
            return [o for o in title['offers'] if (not o['audio'] or any(l in LANGUAGES for l in o['audio'])) and (not language or language in o['audio']) and (not weekly or weekly_offer_date(title, o, now) is not None)]
        def cards(items, language=None, weekly=False):
            result = []
            for t in items:
                offers = offers_for(t, language, weekly)
                if not offers:
                    continue
                audio = [l for l in LANGUAGES if any(l in o['audio'] for o in offers)]
                providers = ', '.join(dict.fromkeys(o['platform'] for o in offers))
                addition = f' · Added {checked_date(max(weekly_offer_date(t, o, now) for o in offers), now)} · Premiere unverified' if weekly else ''
                result.append(f'<li><a href="{title_path(t)}">{escape(t["title"])}</a> <span>· {escape(" · ".join(audio) or "Audio languages unverified")}</span><small>{escape(t["type"])} · {escape(providers)}{escape(addition)}</small></li>')
            return '<ul class="seo-list">' + ''.join(result) + '</ul>' if result else '<p>No matching titles in this snapshot. <a href="/">Explore the dashboard</a>.</p>'
        picks = [
            ('motn:25736', 'For a revenge-action night', 'Yevadu builds its action story around a changed identity and the consequences that follow. Choose it when you want a high-concept revenge plot rather than a quiet character drama.'),
            ('motn:3522553', 'For a hometown romance', 'Rangabali connects a move to the city with romance and a renewed look at home. It is the pick here for viewers drawn to small-town connections and a lighter starting premise.'),
            ('motn:44476', 'For romance with a mystery', 'Iddarammayilatho uses a diary and a musician’s past to pull romance into a conspiracy. Pick this when a straightforward love story would feel too predictable.'),
            ('motn:7524386', 'For an aviation setting', 'Operation Valentine shifts this list into the world of fighter pilots and radar control. Its military setting gives the weekend a different flavour from the romance and crime selections.'),
            ('motn:9299963', 'For a police investigation', 'Satyabhama follows an officer investigating a disappearance while carrying her own past. Choose it for a mystery-led evening; its premise points toward darker subject matter.')]
        sections = []
        for ident, mood, commentary in picks:
            t = next((t for t in titles if t['id'] == ident), None)
            if not t:
                continue
            offers = [o for o in offers_for(t, 'Telugu') if o.get('type') == 'subscription']
            providers = ', '.join(dict.fromkeys(o['platform'] for o in offers)) or 'No Telugu subscription offer verified in this snapshot'
            sections.append(f'<section><h2><a href="{title_path(t)}">{escape(t["title"])} ({t.get("year", "")})</a> · Telugu</h2><h3>{escape(mood)}</h3><p>{escape(commentary)}</p><p>Telugu subscription audio: {escape(providers)}. <a href="{title_path(t)}">Check current offers and subtitles →</a></p></section>')
        page('/guides/telugu-weekend-picks/', 'Five Telugu films for your weekend watchlist', 'A mood-based shortlist spanning action, romance, aviation and investigation, with Telugu audio offers in India.', '<p>Published 28 October 2026 · Curated catalogue picks, not a list of new premieres.</p><p>Start with the kind of evening you want, then check the platform. These choices are based on published story premises and catalogue metadata, rather than first-hand reviews. Platform availability below is refreshed with the site snapshot; confirm on the provider before watching.</p>' + ''.join(sections) + note + info_nav)
        ordered = sorted(titles, key=lambda t:t['title'].casefold())
        recent = sorted([t for t in titles if t.get('weekly') and isinstance(t.get('weeklyUpdatedAt'), (int,float)) and now-7*86400 <= t['weeklyUpdatedAt'] <= now], key=lambda t:t['weeklyUpdatedAt'], reverse=True)
        page('/this-week/', 'OTT additions this week in India', 'Provider-reported additions in the last seven days. These are not confirmed OTT premiere dates; a series addition does not confirm a new season or episode.', note + '<h2>Older movies added</h2><p>Films released before the current year, with a recent offer reported on a covered platform.</p>' + cards([t for t in recent if older_movie(t, now)], weekly=True) + '<h2>Other additions</h2><p>Series updates and movie additions outside the older-movie group. Premiere dates remain unverified.</p>' + cards([t for t in recent if not older_movie(t, now)], weekly=True))
        for lang in LANGUAGES:
            page(f'/languages/{lang.lower()}/', f'{lang} movies and series on OTT in India', f'Find movies and series with {lang} audio on covered streaming platforms in India. Check platform-specific audio, subtitles and subscription or rental options.', f'<h2>Choose {lang} audio with confidence</h2><p>This list matches audio reported on each platform, including dubbed versions. It does not mean every title was originally made in {lang}. Use Originally and Watch in separately on the dashboard.</p><p>Check the offer type before subscribing: a rental, purchase or paid add-on can be listed on the same service as a base-subscription option. Subtitles are listed separately on each title page.</p><p>Looking for narrated visual action? <a href="/audio-description/">Check the sourced audio-description guide</a>; ordinary {lang} audio does not establish an audio-description track.</p>' + note + cards(ordered, lang))
        names = {'subscription':'Included with subscription', 'free':'Free to watch', 'rent':'Rental', 'buy':'Purchase', 'addon':'Add-on subscription'}
        for t in titles:
            rows = []
            for o in offers_for(t):
                link = safe_link(o.get('link'))
                provider = f'<a href="{escape(link, quote=True)}" rel="noopener noreferrer">{escape(o["platform"])} ↗</a>' if link else escape(o['platform'])
                report=o.get('audioDescription')
                ad = ('<p>Audio description reported: '+escape(' · '.join(report['languages']))+'</p><p><a href="'+escape(report['sourceURL'],quote=True)+'">Provider audio-description report</a> · Checked '+checked_date(report['checkedAt'],now)+'. India playback unverified; confirm the track in the player.</p>') if report else '<p>Audio description: Unverified. Ordinary audio and subtitles do not confirm a description track.</p>'
                rows.append(f'<li>{provider}<p>{escape(names.get(o.get("type"), "Offer unverified"))}{(" · " + escape(o["addon"])) if o.get("addon") else ""}</p><p>Audio: {escape(" · ".join(language_label(v) for v in o["audio"]) or "Unverified")}</p><p>Subtitles: {escape(" · ".join(language_label(v) for v in o.get("subtitles", [])) or "Unverified")}</p>{ad}</li>')
            issue_body = f"Title: {t['title']}\nCatalogue ID: {t['id']}\nPage: {BASE + title_path(t)}\nOriginal language listed: {t.get('originalLanguage') or 'Unverified'}\n\nWhat is incorrect?\n\nCorrection and source:\n"
            report_url = 'https://github.com/akashIntgrators/OTTScout-Web/issues/new?' + urlencode({'title':'Incorrect details: '+t['title'], 'body':issue_body})
            report_link = '<p><a href="' + escape(report_url, quote=True) + '" target="_blank" rel="noopener noreferrer">Report incorrect details on GitHub ↗</a> · Public issue; review before submitting. GitHub account required.</p>'
            metadata = t.get('tmdb') or {}
            genres = '<p>Genres (TMDB): ' + escape(' · '.join(metadata.get('genres', [])) or 'Unverified') + '</p>'
            if metadata.get('url') and safe_link(metadata['url']):
                genres += '<p><a href="' + escape(metadata['url'], quote=True) + '">Metadata source: TMDB</a></p>'
            verification = 'No confident TMDB match; details are not guessed from available audio.' if t.get('tmdbMatchStatus') == 'unmatched' else 'TMDB lookup pending.' if not metadata else 'TMDB metadata checked ' + checked_date(metadata.get('checkedAt'), now) + ' (IST). Missing source details remain Unverified.'
            freshness = '<p>Availability checked ' + checked_date(t.get('lastCheckedAt'), now) + ' (IST). This is the last title check, not the latest catalogue run.</p><p>' + escape(verification) + '</p><p>Original-language source: ' + escape(t.get('originalLanguageSource') or 'Unverified') + '</p><p>OTT premiere date: Unverified. Provider addition dates are not premiere dates.</p>'
            display = t['title'] + (f' ({t["year"]})' if t.get('year') else '')
            providers = ', '.join(dict.fromkeys(o['platform'] for o in offers_for(t))) or 'covered OTT platforms'
            page(title_path(t), f'{display} — where to watch in India', f'Where to watch {display} in India. Compare {providers} offers, audio languages, subtitles and sourced accessibility reports.', f'<p>{escape(str(t.get("year") or "Year unverified"))} · {escape(t["type"])}</p><p>Original language: {escape(original_label(t.get("originalLanguage")))}</p>'+freshness+'<h2>Where to watch</h2><ul class="seo-offers">'+''.join(rows)+'</ul>'+genres+report_link+note,work=t)
    else:
        # Validation builds have no provider snapshot. Never invent indexable listings.
        print('No public catalogue snapshot; discovery pages will be generated during catalogue deployment.')
    linked = {}
    if source.exists():
        for t in catalog['titles']:
            for o in t['offers']:
                ident=netflix_id(o.get('link')) if o['platform']=='Netflix' else None
                if ident:linked[ident]=t
    report_cards=[]
    for report in reports:
        match=linked.get(report['providerTitleId'])
        local_link = '<a href="'+title_path(match)+'">Check imported India viewing offers</a>' if match else 'Not currently matched to an imported India offer.'
        report_cards.append('<article class="guide-report"><h2>'+escape(report['title'])+((' ('+str(report['year'])+')') if report.get('year') else '')+'</h2><p>Netflix · '+escape(report['type'])+' · Description languages reported: <strong>'+escape(' · '.join(report['languages']))+'</strong></p><p>Provider public-page report checked '+checked_date(report['checkedAt'],now)+'. India playback is unverified. For series, tracks may differ by episode and season.</p><p><a href="'+escape(report['sourceURL'],quote=True)+'">Read Netflix’s report for '+escape(report['title'])+'</a> · '+local_link+'</p></article>')
    guide = '<nav class="seo-nav" aria-label="Audio-description guide sections"><a href="#description-reports">Reported titles</a><a href="#enable-description">Player instructions</a><a href="#description-feedback">Suggest a correction</a></nav><h2>What an audio-description track does</h2><p>Audio description narrates visual action, expressions and scene changes between dialogue. A regular language track, dubbed version or subtitle listing does not prove that narration is available. OTTScout links to streaming services; it does not play, download or create description tracks.</p><h2>How to read these reports</h2><p>These candidates come from explicit audio-description listings on official public provider pages, accessed through India URLs. Providers can regionalize those pages by visitor location. We have not checked playback with an India account, and subscription, device, profile, season and episode differences can matter. Treat the list as a starting point and confirm the exact description track in your player.</p><p>Reports are dated. The dashboard filter excludes reports older than 30 days; re-check older directory entries directly with the provider. Missing reports mean Unverified, not unavailable. We currently have source reports for English, Hindi, Tamil and Telugu; Kannada and Malayalam description tracks remain unverified in this directory.</p><p><a href="/?audio-description=reported">Show reported description tracks in the imported catalogue</a>. Your current platform and language filters still apply. The Watch in filter matches description languages when the description filter is enabled.</p><h2 id="description-reports">Provider-reported candidates</h2>' + (''.join(report_cards) if report_cards else '<p>No current source reports are promoted. Use the provider instructions below to check a title directly.</p>')
    guide += '<h2 id="enable-description">Check the track before watching</h2><h3>Netflix</h3><p>Start the title, open Audio &amp; Subtitles, and choose a track explicitly marked Audio Description in the language you want. Netflix also supports searches such as Audio Description in English. <a href="https://help.netflix.com/en/node/25079">Netflix’s description-track instructions</a> explain device and episode differences.</p><h3>Prime Video</h3><p>During playback, open Audio &amp; Languages and look for a track labelled Audio Description. Device support and title features can vary. <a href="https://www.primevideo.com/help/?nodeId=GYWG45TK599P4KUL">Read Prime Video’s instructions</a>. We have not verified title-specific India description tracks for Prime Video in this directory.</p><h3>Other covered platforms</h3><p>JioHotstar, ZEE5 and SonyLIV description-track availability is currently unverified here. Do not interpret a platform’s ordinary audio-language list as confirmation of description.</p><h2 id="description-feedback">Help improve the directory</h2><p>Use Report incorrect details → Audio description on a title, or <a href="/contact/">contact us on GitHub</a>. Include the platform, title link, description language, India region, device and check date where possible. Do not share account, payment or login details. Reports are reviewed before they become directory entries.</p><p><a href="/accessibility/">Website keyboard and screen-reader help</a></p>'
    page('/audio-description/','Audio-described movies and series: reports for viewers in India','Find provider-reported audio-description languages and source dates. India playback remains unverified; confirm the exact track on the streaming service.',guide)
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{escape(BASE+p)}</loc></url>' for p in urls) + '</urlset>'
    (target / 'sitemap.xml').write_text(sitemap)
    (target / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n')
    print(f'Website staged with {len(urls)} sitemap URLs; database and reports excluded.')
    return target

if __name__ == '__main__':
    build()
