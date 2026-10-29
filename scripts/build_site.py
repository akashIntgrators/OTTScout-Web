"""Build the public dashboard and crawlable discovery pages from the validated snapshot."""
from pathlib import Path
from html import escape
from urllib.parse import urlparse, quote, urlencode
import json
import shutil
import time
from datetime import datetime, timezone, timedelta
try:
    from scripts.site_features import apply_reports, valid_reports, netflix_id, schema_graph, json_script, language_label
except ModuleNotFoundError:
    from site_features import apply_reports, valid_reports, netflix_id, schema_graph, json_script, language_label

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://ottscout.techiwithhelmet.com'
LANGUAGES = ('English', 'Hindi', 'Telugu', 'Tamil', 'Kannada', 'Malayalam')
IST = timezone(timedelta(hours=5, minutes=30))

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

def build(root=ROOT, now=None):
    now = int(time.time()) if now is None else now
    target = root / '.site'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    for name in ('index.html', 'app.js', 'style.css', 'CNAME'):
        shutil.copy2(root / name, target / name)
    if (root / 'analytics.js').exists():
        shutil.copy2(root / 'analytics.js', target / 'analytics.js')
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
<meta property="og:type" content="website"><meta property="og:site_name" content="OTTScout"><meta name="twitter:card" content="summary">
<link rel="icon" href="/assets/ottscout-icon.svg?v=1" type="image/svg+xml"><link rel="icon" href="/assets/ottscout-icon.png?v=1" type="image/png"><link rel="apple-touch-icon" href="/assets/ottscout-touch-icon.png?v=1"><meta name="apple-mobile-web-app-title" content="OTTScout">
{structured}<link rel="stylesheet" href="/style.css?v=watch12"></head><body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header"><a class="brand" href="/" aria-label="OTTScout home">OTT<span>Scout</span></a><span class="region">Streaming in India</span></header>
<nav class="seo-nav seo-navigation" aria-label="Browse streaming">{navigation}</nav><main id="main" class="seo-page" tabindex="-1">
<nav class="breadcrumbs" aria-label="Breadcrumb"><a href="/">OTTScout</a><span aria-hidden="true"> / </span><span aria-current="page">{escape(title)}</span></nav>
<h1>{escape(title)}</h1><p class="seo-description">{escape(description)}</p>{content}
<section class="credits" aria-label="Data credits"><h2>Data credits</h2><a href="https://www.themoviedb.org"><img src="https://www.themoviedb.org/assets/2/v4/logos/v2/blue_square_2-d537fb228cf3ded904ef09b136fe3fec72548ebc1fea3fbbd1ad9e36364db38b.svg" width="56" height="40" alt="TMDB"></a><p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p></section></main>
<footer class="seo-footer"><nav class="seo-nav" aria-label="Site information"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/audio-description/">Audio description</a><a href="/accessibility/">Accessibility help</a><a href="/guides/telugu-weekend-picks/">Weekend picks</a></nav><p>India · Availability may change. Audio and subtitles vary by platform.</p><a href="https://www.movieofthenight.com/about/api">Streaming data by Movie of the Night</a></footer><script src="/analytics.js?v=2" defer></script></body></html>'''
        dest = target / path.strip('/') / 'index.html'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markup, encoding='utf-8')
        urls.append(path)
    info_nav = '<nav class="seo-nav" aria-label="About OTTScout"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/guides/telugu-weekend-picks/">Weekend picks</a></nav>'
    page('/about/', 'About OTTScout', 'An independent guide to streaming movies and series in India.', '<h2>Find something worth watching</h2><p>OTTScout helps you compare platform availability, audio languages and original-language metadata, then follow a link to the streaming service. We do not host movies or sell streaming subscriptions.</p><p>We focus on English, Hindi, Telugu, Tamil, Kannada and Malayalam. The current feed covers Netflix, Prime Video, JioHotstar, ZEE5 and SonyLIV. Imported coverage is partial and availability can change.</p><h2>How the catalogue works</h2><p>Movie of the Night supplies streaming offers and audio options. TMDB supplies matched original languages and genres. Uncertain matches stay unverified. Audio availability and original language are separate: a Telugu original may only have Hindi audio on a particular platform.</p><p>Updates are scheduled approximately every six hours, subject to provider quotas and scheduler delays. Provider-reported additions are not necessarily premieres. Always confirm the offer on the streaming service.</p><p>This independent project is maintained by <a href="https://github.com/akashIntgrators">Akash</a>. Your watchlist stays in your browser.</p>' + info_nav)
    page('/contact/', 'Contact and corrections', 'Help improve OTTScout through our public GitHub issue tracker.', '<h2>Found something incorrect?</h2><p>Use “Report incorrect details” on a title, or <a href="https://github.com/akashIntgrators/OTTScout-Web/issues/new">open a GitHub issue</a> for feedback and general enquiries. Include the title, streaming platform, language and a source link where possible.</p><p>GitHub requires an account. Issues are public: please do not include passwords, API keys, billing details or other private information. You can review the report before submitting.</p><p>We welcome corrections, feature suggestions and questions about the project.</p>' + info_nav)
    page('/privacy/', 'Privacy at OTTScout', 'What this website stores and which services it uses. Updated 29 October 2026.', '<h2>Browser storage</h2><p>Your watchlist, filters, optional keyboard shortcut choice and dismissed titles are saved in local browser storage. They are not synced to an OTTScout account. Clearing website data removes these preferences and your saved watchlist.</p><h2>Hosting and external services</h2><p>GitHub Pages hosts this website and may process connection information such as IP addresses and request logs under <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub’s privacy statement</a>. Poster and attribution images may load from external providers, which receive the connection information needed to deliver them.</p><p>Links to streaming services, TMDB and GitHub open services with their own privacy practices. Correction reports are only submitted when you choose to submit them on GitHub, where they are public.</p><h2>Analytics and advertising</h2><p>Google Analytics is optional and only loads after you choose Allow analytics. It measures page visits and device/browser information; Google receives connection information such as your IP address. We exclude search terms, filters, watchlist contents, URL query strings and referrers from our page-view event. Automatic enhanced measurement and advertising signals are disabled. Your consent choice is stored in this browser. Use Analytics choices in the footer, then No thanks, to stop future measurement and remove analytics cookies set for this host. This does not erase previously collected data. Browsers signalling Do Not Track or Global Privacy Control are not prompted automatically. See <a href="https://policies.google.com/privacy">Google’s privacy policy</a>. Advertisement boxes are reserved space, not live ads; no advertising tracker is installed.</p><h2>Contact</h2><p>For questions, use our <a href="/contact/">GitHub contact route</a>. Avoid posting personal information in public issues.</p>' + info_nav)
    page('/accessibility/', 'Accessibility help for OTTScout', 'Keyboard navigation, screen-reader support and audio-description discovery on OTTScout.', '<h2>Use the dashboard with a keyboard</h2><ul><li>Use the Skip to titles link to reach the results.</li><li>Press Tab and Shift+Tab to move between controls. Enter opens links; Enter or Space operates buttons and checkboxes.</li><li>Filter menus use native expandable controls. Press Escape to close an open filter and return to its heading.</li><li>Result counts are announced after filters change. Switching views moves focus to the results heading. Hiding a title or removing it from a watchlist moves focus to the next title when possible.</li><li>The optional / search shortcut is off by default. Enable it in <a href="/#accessibility-options">Keyboard options</a> if it works with your assistive technology.</li></ul><h2>Read without the interactive dashboard</h2><p>The <a href="/this-week/">text weekly feed</a>, language pages and title details use ordinary headings, lists and links and work without JavaScript. The dashboard uses JavaScript for filtering and browser-local watchlists.</p><h2>Find description tracks</h2><p><a href="/audio-description/">Read the audio-description guide</a> for provider-reported candidates, description languages and check dates. A spoken website, subtitles, a dubbed track and a film’s audio-description track are different things.</p><h2>Current limitations and feedback</h2><p>Source data and description-track coverage are incomplete. India playback is not independently verified. Automated checks and keyboard tests do not establish full accessibility conformance; testing with blind users and a range of screen readers is still needed.</p><p>If a control or page is difficult to use, <a href="https://github.com/akashIntgrators/OTTScout-Web/issues/new">report an accessibility issue on GitHub</a>. Include the page and the browser/screen reader you use. GitHub reports are public; avoid personal information. We welcome feedback on focus order, labels and announcements.</p>' + info_nav)
    source = target / 'data/catalog.json'
    if source.exists():
        catalog = apply_reports(json.loads(source.read_text()),reports)
        source.write_text(json.dumps(catalog,ensure_ascii=False),encoding='utf-8')
        titles = catalog['titles']
        updated = escape(catalog.get('updatedAt', 'Unknown'))
        note = f'<p class="seo-note">Snapshot updated: {updated}. Imported catalogue coverage is limited; this is not an exhaustive list. Provider-reported additions are not confirmed OTT premiere dates.</p>'
        def offers_for(title, language=None, weekly=False):
            return [o for o in title['offers'] if any(l in LANGUAGES for l in o['audio']) and (not language or language in o['audio']) and (not weekly or weekly_offer_date(title, o, now) is not None)]
        def cards(items, language=None, weekly=False):
            result = []
            for t in items:
                offers = offers_for(t, language, weekly)
                if not offers:
                    continue
                audio = [l for l in LANGUAGES if any(l in o['audio'] for o in offers)]
                providers = ', '.join(dict.fromkeys(o['platform'] for o in offers))
                addition = f' · Added {checked_date(max(weekly_offer_date(t, o, now) for o in offers), now)} · Premiere unverified' if weekly else ''
                result.append(f'<li><a href="{title_path(t)}">{escape(t["title"])}</a> <span>· {escape(" · ".join(audio))}</span><small>{escape(t["type"])} · {escape(providers)}{escape(addition)}</small></li>')
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
