"""Build the public dashboard and crawlable discovery pages from the validated snapshot."""
from pathlib import Path
from html import escape
from urllib.parse import urlparse, quote
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
    for name in ('assets', 'data'):
        if (root / name).exists():
            shutil.copytree(root / name, target / name)
    (target / '.nojekyll').touch()
    urls = ['/']
    navigation = '<a href="/">Dashboard</a><a href="/this-week/">This week</a>' + ''.join(f'<a href="/languages/{lang.lower()}/">{lang}</a>' for lang in LANGUAGES)
    def page(path, title, description, content):
        canonical = BASE + path
        markup = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)} | OTTScout</title><meta name="description" content="{escape(description, quote=True)}"><link rel="canonical" href="{canonical}"><meta property="og:title" content="{escape(title, quote=True)}"><meta property="og:description" content="{escape(description, quote=True)}"><meta property="og:url" content="{canonical}"><meta property="og:type" content="website"><link rel="stylesheet" href="/style.css?v=seo5"></head><body><header class="site-header"><a class="brand" href="/">OTT<span>Scout</span></a><span class="region">Streaming in India</span></header><main class="seo-page"><nav class="seo-nav" aria-label="Browse streaming">{navigation}</nav><h1>{escape(title)}</h1><p class="seo-description">{escape(description)}</p>{content}<footer><p>India · Availability may change. Audio and subtitles vary by platform.</p><a href="https://www.movieofthenight.com/about/api">Streaming data by Movie of the Night</a></footer></main></body></html>'''
        dest = target / path.strip('/') / 'index.html'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markup, encoding='utf-8')
        urls.append(path)
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
            page(title_path(t), f'{t["title"]} — where to watch in India', f'Find where to watch {t["title"]} in India, with platform-specific audio languages, subtitles and viewing options.', f'<p>{escape(str(t.get("year") or "Year unverified"))} · {escape(t["type"])}</p><p>Original language: {escape(t.get("originalLanguage") or "Unverified")}</p><h2>Where to watch</h2><ul class="seo-offers">'+''.join(rows)+'</ul>'+note)
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
