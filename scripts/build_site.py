"""Build the public dashboard and crawlable discovery pages from the validated snapshot."""
from pathlib import Path
from html import escape
from urllib.parse import urlparse, quote, urlencode
import json
import shutil
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://ottscout.techiwithhelmet.com'
LANGUAGES = ('English', 'Hindi', 'Telugu', 'Tamil', 'Kannada', 'Malayalam')

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
    urls = ['/']
    navigation = '<a href="/">Dashboard</a><a href="/this-week/">This week</a>' + ''.join(f'<a href="/languages/{lang.lower()}/">{lang}</a>' for lang in LANGUAGES)
    def page(path, title, description, content):
        canonical = BASE + path
        markup = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | OTTScout</title><meta name="description" content="{escape(description, quote=True)}"><link rel="canonical" href="{canonical}"><meta property="og:title" content="{escape(title, quote=True)}"><meta property="og:description" content="{escape(description, quote=True)}"><meta property="og:url" content="{canonical}"><meta property="og:type" content="website"><link rel="stylesheet" href="/style.css?v=discovery8"></head><body><header class="site-header"><a class="brand" href="/">OTT<span>Scout</span></a><span class="region">Streaming in India</span></header><main class="seo-page"><nav class="seo-nav" aria-label="Browse streaming">{navigation}</nav><h1>{escape(title)}</h1><p class="seo-description">{escape(description)}</p>{content}<section class="credits" aria-label="Data credits"><h2>Data credits</h2><a href="https://www.themoviedb.org"><img src="https://www.themoviedb.org/assets/2/v4/logos/v2/blue_square_2-d537fb228cf3ded904ef09b136fe3fec72548ebc1fea3fbbd1ad9e36364db38b.svg" width="56" height="40" alt="TMDB"></a><p>This product uses the TMDB API but is not endorsed or certified by TMDB.</p></section><footer><nav class="seo-nav"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/guides/telugu-weekend-picks/">Weekend picks</a></nav><p>India · Availability may change. Audio and subtitles vary by platform.</p><a href="https://www.movieofthenight.com/about/api">Streaming data by Movie of the Night</a></footer></main><script src="/analytics.js?v=1" defer></script></body></html>'''
        dest = target / path.strip('/') / 'index.html'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markup, encoding='utf-8')
        urls.append(path)
    info_nav = '<nav class="seo-nav" aria-label="About OTTScout"><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/privacy/">Privacy</a><a href="/guides/telugu-weekend-picks/">Weekend picks</a></nav>'
    page('/about/', 'About OTTScout', 'An independent guide to streaming movies and series in India.', '<h2>Find something worth watching</h2><p>OTTScout helps you compare platform availability, audio languages and original-language metadata, then follow a link to the streaming service. We do not host movies or sell streaming subscriptions.</p><p>We focus on English, Hindi, Telugu, Tamil, Kannada and Malayalam. The current feed covers Netflix, Prime Video, JioHotstar, ZEE5 and SonyLIV. Imported coverage is partial and availability can change.</p><h2>How the catalogue works</h2><p>Movie of the Night supplies streaming offers and audio options. TMDB supplies matched original languages and genres. Uncertain matches stay unverified. Audio availability and original language are separate: a Telugu original may only have Hindi audio on a particular platform.</p><p>Updates are scheduled approximately every six hours, subject to provider quotas and scheduler delays. Provider-reported additions are not necessarily premieres. Always confirm the offer on the streaming service.</p><p>This independent project is maintained by <a href="https://github.com/akashIntgrators">Akash</a>. Your watchlist stays in your browser.</p>' + info_nav)
    page('/contact/', 'Contact and corrections', 'Help improve OTTScout through our public GitHub issue tracker.', '<h2>Found something incorrect?</h2><p>Use “Report incorrect details” on a title, or <a href="https://github.com/akashIntgrators/OTTScout-Web/issues/new">open a GitHub issue</a> for feedback and general enquiries. Include the title, streaming platform, language and a source link where possible.</p><p>GitHub requires an account. Issues are public: please do not include passwords, API keys, billing details or other private information. You can review the report before submitting.</p><p>We welcome corrections, feature suggestions and questions about the project.</p>' + info_nav)
    page('/privacy/', 'Privacy at OTTScout', 'What this website stores and which services it uses. Updated 28 October 2026.', '<h2>Browser storage</h2><p>Your watchlist, filters and dismissed titles are saved in local browser storage. They are not synced to an OTTScout account. Clearing website data removes these preferences and your saved watchlist.</p><h2>Hosting and external services</h2><p>GitHub Pages hosts this website and may process connection information such as IP addresses and request logs under <a href="https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement">GitHub’s privacy statement</a>. Poster and attribution images may load from external providers, which receive the connection information needed to deliver them.</p><p>Links to streaming services, TMDB and GitHub open services with their own privacy practices. Correction reports are only submitted when you choose to submit them on GitHub, where they are public.</p><h2>Analytics and advertising</h2><p>Google Analytics is optional and only loads after you choose Allow analytics. It measures page visits and device/browser information; Google receives connection information such as your IP address. We exclude search terms, filters, watchlist contents, URL query strings and referrers from our page-view event. Automatic enhanced measurement and advertising signals are disabled. Your consent choice is stored in this browser. Use Analytics choices in the footer, then No thanks, to stop future measurement and remove analytics cookies set for this host. This does not erase previously collected data. Browsers signalling Do Not Track or Global Privacy Control are not prompted automatically. See <a href="https://policies.google.com/privacy">Google’s privacy policy</a>. Advertisement boxes are reserved space, not live ads; no advertising tracker is installed.</p><h2>Contact</h2><p>For questions, use our <a href="/contact/">GitHub contact route</a>. Avoid posting personal information in public issues.</p>' + info_nav)
    source = target / 'data/catalog.json' 
    if source.exists():
        catalog = json.loads(source.read_text())
        titles = catalog['titles']
        updated = escape(catalog.get('updatedAt', 'Unknown'))
        note = f'<p class="seo-note">Snapshot updated: {updated}. Imported catalogue coverage is limited; this is not an exhaustive list. Provider-reported additions are not confirmed OTT premiere dates.</p>'
        def offers_for(title, language=None, weekly=False):
            return [o for o in title['offers'] if any(l in LANGUAGES for l in o['audio']) and (not language or language in o['audio']) and (not weekly or o['platform'] in title.get('weeklyPlatforms', []))]
        def cards(items, language=None, weekly=False):
            result = []
            for t in items:
                offers = offers_for(t, language, weekly)
                if not offers:
                    continue
                audio = [l for l in LANGUAGES if any(l in o['audio'] for o in offers)]
                providers = ', '.join(dict.fromkeys(o['platform'] for o in offers))
                result.append(f'<li><a href="{title_path(t)}">{escape(t["title"])}</a> <span>· {escape(" · ".join(audio))}</span><small>{escape(t["type"])} · {escape(providers)}</small></li>')
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
        page('/this-week/', 'OTT additions this week in India', 'Browse movies and series reported as newly available on covered streaming platforms in the last seven days, with audio languages and viewing options.', note + cards(recent, weekly=True))
        for lang in LANGUAGES:
            page(f'/languages/{lang.lower()}/', f'{lang} movies and series on OTT in India', f'Find movies and series with {lang} audio on covered streaming platforms in India. Check platform-specific audio, subtitles and subscription or rental options.', note + cards(ordered, lang))
        names = {'subscription':'Included with subscription', 'free':'Free to watch', 'rent':'Rental', 'buy':'Purchase', 'addon':'Add-on subscription'}
        for t in titles:
            rows = []
            for o in offers_for(t):
                link = safe_link(o.get('link'))
                provider = f'<a href="{escape(link, quote=True)}" rel="noopener noreferrer">{escape(o["platform"])} ↗</a>' if link else escape(o['platform'])
                rows.append(f'<li>{provider}<p>{escape(names.get(o.get("type"), "Offer unverified"))}{(" · " + escape(o["addon"])) if o.get("addon") else ""}</p><p>Audio: {escape(" · ".join(o["audio"]) or "Unverified")}</p><p>Subtitles: {escape(" · ".join(o.get("subtitles", [])) or "Unverified")}</p></li>')
            issue_body = f"Title: {t['title']}\nCatalogue ID: {t['id']}\nPage: {BASE + title_path(t)}\nOriginal language listed: {t.get('originalLanguage') or 'Unverified'}\n\nWhat is incorrect?\n\nCorrection and source:\n"
            report_url = 'https://github.com/akashIntgrators/OTTScout-Web/issues/new?' + urlencode({'title':'Incorrect details: '+t['title'], 'body':issue_body})
            report_link = '<p><a href="' + escape(report_url, quote=True) + '" target="_blank" rel="noopener noreferrer">Report incorrect details on GitHub ↗</a> · Public issue; review before submitting. GitHub account required.</p>'
            metadata = t.get('tmdb') or {}
            genres = '<p>Genres (TMDB): ' + escape(' · '.join(metadata.get('genres', [])) or 'Unverified') + '</p>'
            if metadata.get('url') and safe_link(metadata['url']):
                genres += '<p><a href="' + escape(metadata['url'], quote=True) + '">Metadata source: TMDB</a></p>'
            page(title_path(t), f'{t["title"]} — where to watch in India', f'Find where to watch {t["title"]} in India, with platform-specific audio languages, subtitles and viewing options.', f'<p>{escape(str(t.get("year") or "Year unverified"))} · {escape(t["type"])}</p><p>Original language: {escape(t.get("originalLanguage") or "Unverified")}</p><h2>Where to watch</h2><ul class="seo-offers">'+''.join(rows)+'</ul>'+genres+report_link+note)
    else:
        # Validation builds have no provider snapshot. Never invent indexable listings.
        print('No public catalogue snapshot; discovery pages will be generated during catalogue deployment.')
    sitemap = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{escape(BASE+p)}</loc></url>' for p in urls) + '</urlset>'
    (target / 'sitemap.xml').write_text(sitemap)
    (target / 'robots.txt').write_text(f'User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n')
    print(f'Website staged with {len(urls)} sitemap URLs; database and reports excluded.')
    return target

if __name__ == '__main__':
    build()
