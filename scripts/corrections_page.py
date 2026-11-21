"""Public correction links; submissions remain in GitHub until a maintainer reviews them."""
from html import escape
from urllib.parse import urlencode, urlsplit

ISSUES = 'https://github.com/akashIntgrators/OTTScout-Web/issues'
FORM = ISSUES + '/new?template=catalogue-correction.yml'
INBOX = ISSUES + '?' + urlencode({'q': 'is:issue is:open label:catalogue-correction'})
PLATFORMS = ('Netflix', 'Prime Video', 'Sun NXT', 'JioHotstar', 'ZEE5', 'aha', 'SonyLIV')


def correction_link(title=None, platform=None, notes=''):
    params = {'template': 'catalogue-correction.yml'}
    if isinstance(title, dict):
        name = str(title.get('title') or '')[:200]
        params.update({'title': '[Catalogue correction] ' + name, 'title_name': name})
        if title.get('type') in ('Movie', 'Series'):
            params['title_type'] = title['type']
        offers = title.get('offers', [])
        present = {offer.get('platform') for offer in offers if isinstance(offer, dict)}
        chosen = platform if platform in PLATFORMS else next(iter(present)) if len(present) == 1 else None
        if chosen in PLATFORMS:
            params['platform'] = chosen
            for offer in offers:
                if not isinstance(offer, dict) or offer.get('platform') != chosen:
                    continue
                link = offer.get('link')
                try:
                    parsed = urlsplit(link) if isinstance(link, str) else None
                    if parsed and len(link) <= 1000 and parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not any(c.isspace() for c in link):
                        params['official_url'] = link
                        break
                except ValueError:
                    continue
    if notes:
        params['notes'] = str(notes)[:1800]
    url = ISSUES + '/new?' + urlencode(params)
    while len(url) > 7500 and params.get('notes'):
        params['notes'] = params['notes'][:len(params['notes']) // 2]
        url = ISSUES + '/new?' + urlencode(params)
    if len(url) > 7500:
        params.pop('official_url', None)
        url = ISSUES + '/new?' + urlencode(params)
    return url


def render_corrections():
    return ('<div class="correction-actions"><a class="correction-primary" href="' + escape(FORM, quote=True) + '">Report a correction</a>'
            '<a href="' + escape(INBOX, quote=True) + '">View the corrections inbox</a></div>'
            '<p class="seo-note">Opens GitHub. An account is required, and reports are public. You can review your report before submitting.</p>'
            '<h2>Missing title or incorrect details?</h2><p>Share the movie or series name, its platform link, and what needs changing. Choose whether you saw it available in India or only saw an announcement.</p>'
            '<p>For language corrections, include evidence for the playable audio track. Original language and audio description are separate details; leave either unverified when you are unsure.</p>'
            '<h2>What happens next</h2><ol><li>Your submission enters the public corrections inbox.</li>'
            '<li>A maintainer checks the exact title, India availability and supporting sources. Incomplete reports may need more evidence.</li>'
            '<li>Confirmed corrections are reviewed before publication. Submitted reports and issue labels never change the catalogue automatically.</li></ol>'
            '<p>Availability corrections have a review date and an expiry. Announced releases stay separate from titles confirmed as available.</p>'
            '<p>Do not include passwords, payment details, account screenshots or API keys. For a private account issue, use the contact details on our <a href="/privacy/">privacy page</a>.</p>'
            '<p><a href="/data-status/">Check current catalogue coverage</a> or <a href="/">return to the catalogue</a>.</p>')
