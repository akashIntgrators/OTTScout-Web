"""Source-backed accessibility reports and conservative search metadata."""
import json
import re
from urllib.parse import urlparse

BASE = 'https://ottscout.techiwithhelmet.com'
DAY = 86400
AD_LANGUAGES = {'English','Hindi','Telugu','Tamil','Kannada','Malayalam'}


# Common ISO 639 tags in provider records; retain unknown tags rather than guess.
# Registry reference: https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry
LANGUAGE_NAMES = {'en':'English','eng':'English','hi':'Hindi','hin':'Hindi','te':'Telugu','tel':'Telugu','ta':'Tamil','tam':'Tamil','kn':'Kannada','kan':'Kannada','ml':'Malayalam','mal':'Malayalam',
 'ar':'Arabic','ara':'Arabic','cs':'Czech','ces':'Czech','da':'Danish','dan':'Danish','de':'German','deu':'German','el':'Greek','ell':'Greek','fi':'Finnish','fin':'Finnish','fr':'French','fra':'French','he':'Hebrew','heb':'Hebrew','hr':'Croatian','hrv':'Croatian','hu':'Hungarian','hun':'Hungarian','id':'Indonesian','ind':'Indonesian','it':'Italian','ita':'Italian','ja':'Japanese','jpn':'Japanese','ko':'Korean','kor':'Korean','ms':'Malay','msa':'Malay','nl':'Dutch','nld':'Dutch','no':'Norwegian','nb':'Norwegian Bokmål','nob':'Norwegian Bokmål','pl':'Polish','pol':'Polish','pt':'Portuguese','por':'Portuguese','ro':'Romanian','ron':'Romanian','ru':'Russian','rus':'Russian','es':'Spanish','spa':'Spanish','sv':'Swedish','swe':'Swedish','th':'Thai','tha':'Thai','tr':'Turkish','tur':'Turkish','vi':'Vietnamese','vie':'Vietnamese','zh':'Chinese','zho':'Chinese','fil':'Filipino','mr':'Marathi','mar':'Marathi','bn':'Bengali','ben':'Bengali','gu':'Gujarati','guj':'Gujarati','pa':'Punjabi','pan':'Punjabi','ur':'Urdu','urd':'Urdu','cmn':'Mandarin Chinese','yue':'Cantonese'}

def language_label(value):
    if not value:return 'Unverified'
    return LANGUAGE_NAMES.get(value,value)


def netflix_id(value):
    try:
        url = urlparse(value or '')
        if url.scheme != 'https' or url.hostname not in ('netflix.com','www.netflix.com') or url.username or url.password or url.port not in (None,443):
            return None
        match = re.fullmatch(r'/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?:title|watch)/([0-9]+)(?:/)?', url.path)
        return match[1] if match else None
    except (ValueError, TypeError):
        return None


def valid_reports(records, now):
    """A public page is evidence of a report, never of India player availability."""
    result = []
    seen = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError('Invalid audio-description report')
        ident = row.get('providerTitleId')
        checked = row.get('checkedAt')
        langs = row.get('languages')
        if (row.get('platform') != 'Netflix' or not isinstance(ident,str)
            or netflix_id(row.get('sourceURL')) != ident or not re.fullmatch(r'[0-9]+',ident)
            or not isinstance(row.get('title'),str) or not row['title'].strip()
            or row.get('type') not in ('Movie','Series')
            or (row.get('year') is not None and (type(row['year']) is not int or not 1800 < row['year'] < 2100))
            or type(checked) is not int or checked <= 0
            or not isinstance(langs,list) or not langs or not all(isinstance(x,str) and x in AD_LANGUAGES for x in langs)
            or row.get('indiaPlaybackVerified') is not False):
            raise ValueError('Audio-description reports require explicit languages, an exact provider source and an unverified India playback label')
        if ident in seen:
            raise ValueError('Duplicate audio-description provider ID')
        seen.add(ident)
        if now-30*DAY <= checked <= now:
            result.append({**row,'languages':list(dict.fromkeys(langs))})
    return result


def apply_reports(catalog, reports):
    by_id = {r['providerTitleId']:r for r in reports}
    for title in catalog['titles']:
        for offer in title['offers']:
            # Clear old computed claims before rebuilding from the current registry.
            offer.pop('audioDescription', None)
            report = by_id.get(netflix_id(offer.get('link'))) if offer['platform']=='Netflix' else None
            if report and title['type']==report['type']:
                offer['audioDescription'] = {'status':'reported','languages':report['languages'],
                    'sourceURL':report['sourceURL'],'checkedAt':report['checkedAt'],
                    'expiresAt':report['checkedAt']+30*DAY,'indiaPlaybackVerified':False}
    return catalog


def schema_graph(path, title, description, work=None):
    canonical = BASE + path
    website = {'@type':'WebSite','@id':BASE+'/#website','name':'OTTScout','url':BASE+'/',
               'description':'India-first streaming discovery with platform-specific audio and sourced accessibility reports.','inLanguage':'en'}
    page = {'@type':'WebPage','@id':canonical+'#webpage','url':canonical,'name':title,
            'description':description,'inLanguage':'en','isPartOf':{'@id':BASE+'/#website'}}
    graph = [website, page]
    if path != '/':
        breadcrumb = {'@type':'BreadcrumbList','@id':canonical+'#breadcrumb','itemListElement':[
            {'@type':'ListItem','position':1,'name':'OTTScout','item':BASE+'/'},
            {'@type':'ListItem','position':2,'name':title,'item':canonical}]}
        graph.append(breadcrumb);page['breadcrumb']={'@id':breadcrumb['@id']}
    if work:
        entity = {'@type':'Movie' if work['type']=='Movie' else 'TVSeries',
                  '@id':canonical+'#title','name':work['title']}
        if work.get('originalLanguage'):entity['inLanguage']=work['originalLanguage']
        metadata=work.get('tmdb') or {}
        if metadata.get('genres'):entity['genre']=metadata['genres']
        source=urlparse(metadata.get('url') or '')
        if source.scheme=='https' and source.hostname=='www.themoviedb.org':entity['sameAs']=metadata['url']
        page['mainEntity']={'@id':entity['@id']};graph.append(entity)
    return {'@context':'https://schema.org','@graph':graph}


def json_script(value):
    safe=json.dumps(value,ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    return '<script type="application/ld+json">'+safe+'</script>'
