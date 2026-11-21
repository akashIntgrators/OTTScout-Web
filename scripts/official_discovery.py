"""Bounded discovery from permitted public OTT HTML; no provider API requests.

Only public page HTML is read. Embedded SSR JSON is decoded as data, never
executed. Index discovery is separate from exact India title verification.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

DAY = 86400
IST = timezone(timedelta(hours=5, minutes=30))
USER_AGENT = 'OTTScoutOfficialDiscovery/1.0 (+https://ottscout.techiwithhelmet.com/about/)'
HOSTS = {'www.sonyliv.com', 'sonyliv.com', 'origin-staticv2.sonyliv.com', 'www.netflix.com', 'netflix.com'}
FAQ = 'https://origin-staticv2.sonyliv.com/UI_icons/india_faqs.html'
ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {'ENG':'English','HIN':'Hindi','TEL':'Telugu','TAM':'Tamil','KAN':'Kannada','MAL':'Malayalam'}
DEFAULT_SOURCES = [
    {'id':'sony-movies','platform':'SonyLIV','adapter':'sony','kind':'Movie','url':'https://www.sonyliv.com/custompage/movies-399',
     'enabled':False,'pauseReason':'permission-required'},
    {'id':'sony-series','platform':'SonyLIV','adapter':'sony','kind':'Series','url':'https://www.sonyliv.com/custompage/tv-shows-32990',
     'enabled':False,'pauseReason':'permission-required'},
    {'id':'netflix-tudum','platform':'Netflix','adapter':'netflix-tudum','url':'https://www.netflix.com/tudum/articles/new-on-netflix','enabled':True},
]


class DiscoveryError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition: raise DiscoveryError(code, message)


def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def read_json(path, default):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return deepcopy(default)


def safe_url(url):
    try:
        p = urlsplit(url)
        require(p.scheme == 'https' and p.hostname in HOSTS and not p.username and not p.password
                and p.port in (None,443) and not p.fragment and len(url) <= 2048,
                'unsafe-url', 'Only configured official HTTPS hosts are allowed')
        return url
    except (TypeError, ValueError) as error:
        if isinstance(error, DiscoveryError): raise
        raise DiscoveryError('unsafe-url', 'Invalid official URL') from None


def safe_header(value):
    return value if isinstance(value,str) and 0 < len(value) <= 512 and all(32 <= ord(c) < 127 for c in value) else None


def robots_policy(text, url):
    """RFC-style longest-match rules, including * and $, for our honest bot."""
    require('<html' not in text.lower(), 'robots-invalid', 'Robots endpoint returned HTML')
    groups=[]; agents=[]; rules=[]; delay=0
    for line in text.splitlines() + ['User-agent: __end__']:
        line=line.split('#',1)[0].strip()
        if ':' not in line: continue
        key,value=line.split(':',1); key=key.strip().lower(); value=value.strip()
        if key == 'user-agent':
            if rules or delay:
                groups.append((agents,rules,delay));agents=[];rules=[];delay=0
            agents.append(value.lower())
        elif key in ('allow','disallow') and agents and value:
            rules.append((key=='allow',value))
        elif key == 'crawl-delay' and agents:
            try: delay=max(0,float(value))
            except ValueError: pass
    if agents and (rules or delay):groups.append((agents,rules,delay))
    matches=[]; bot=USER_AGENT.lower()
    for agents,rules,delay in groups:
        score=max((0 if a=='*' else len(a) for a in agents if a=='*' or a in bot), default=-1)
        if score >= 0: matches.append((score,rules,delay))
    if not matches:return True,0
    best=max(x[0] for x in matches); path=urlsplit(url).path or '/'
    if urlsplit(url).query:path+='?'+urlsplit(url).query
    applicable=[];delay=0
    for score,rules,pause in matches:
        if score != best:continue
        delay=max(delay,pause)
        for allow,pattern in rules:
            terminal=pattern.endswith('$');pattern=pattern[:-1] if terminal else pattern
            expression='^'+re.escape(pattern).replace(r'\*','.*')+('$' if terminal else '')
            if re.search(expression,path):applicable.append((len(pattern.replace('*','')),allow))
    return (max(applicable)[1] if applicable else True),delay


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):return None


def public_get(url, headers, timeout, max_bytes, deadline):
    opener=build_opener(NoRedirect)
    try:
        response=opener.open(Request(url,headers=headers),timeout=timeout)
    except HTTPError as error:response=error
    except (URLError,OSError) as error:raise DiscoveryError('network',type(error).__name__) from None
    with response:
        status=response.code; result_headers={k.lower():v for k,v in response.headers.items()}
        chunks=[];total=0
        while status==200:
            require(time.monotonic()<deadline,'time-budget','Public-request time budget reached')
            part=response.read(min(65536,max_bytes+1-total))
            if not part:break
            total+=len(part)
            require(total<=max_bytes,'document-too-large','Official document exceeds byte limit')
            chunks.append(part)
        return status,result_headers,b''.join(chunks)


class PublicClient:
    def __init__(self, directory, now, *, max_requests=12, max_seconds=120, max_document_bytes=4_000_000,
                 max_total_bytes=24_000_000, transport=None):
        require(type(max_requests) is int and 1<=max_requests<=12 and 0<max_seconds<=300,
                'invalid-limit','Discovery requires at most12 public requests and a bounded deadline')
        require(0<max_document_bytes<=4_000_000 and 0<max_total_bytes<=24_000_000,
                'invalid-limit','Discovery byte limits exceed the reviewed bounds')
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.now=now;self.limit=max_requests;self.deadline=time.monotonic()+max_seconds
        self.max_document_bytes=max_document_bytes;self.max_total_bytes=max_total_bytes
        self.transport=transport or public_get;self.requests=0;self.bytes=0;self.source='';self.attempted={};self.last={};self.source_limits={}

    def checkpoint(self):
        require(self.requests<self.limit,'request-budget','Public-request count limit reached')
        require(self.attempted.get(self.source,0)<self.source_limits.get(self.source,1000000),
                'source-budget','This source defers remaining candidates to share the public-request budget')
        require(time.monotonic()<self.deadline,'time-budget','Public-request time budget reached')
        require(self.bytes<self.max_total_bytes,'byte-budget','Public-response byte budget reached')

    def _path(self,url):return self.directory / ('http-'+hashlib.sha256(url.encode()).hexdigest()+'.json')

    def _http(self,url):
        self.checkpoint();safe_url(url)
        path=self._path(url);cached=read_json(path,{})
        headers={'User-Agent':USER_AGENT,'Accept':'text/html, text/plain;q=0.9','Accept-Encoding':'identity'}
        for key,name in [('etag','If-None-Match'),('lastModified','If-Modified-Since')]:
            value=safe_header(cached.get(key))
            if value:headers[name]=value
        self.requests+=1;self.attempted[self.source]=self.attempted.get(self.source,0)+1
        maximum=min(self.max_document_bytes,self.max_total_bytes-self.bytes)
        try:status,response_headers,body=self.transport(url,headers,min(15,max(.1,self.deadline-time.monotonic())),maximum,self.deadline)
        except (OSError,URLError) as error:raise DiscoveryError('network',type(error).__name__) from None
        response_headers={k.lower():v for k,v in response_headers.items()}
        self.bytes+=len(body)
        require(len(body)<=maximum and self.bytes<=self.max_total_bytes,'byte-budget','Public-response byte budget reached')
        require(time.monotonic()<self.deadline,'time-budget','Public-request time budget reached')
        if status in (301,302,303,307,308):return status,response_headers,None
        if status==304:
            require(isinstance(cached.get('body'),str),'invalid-304','Conditional response has no saved public document')
            cached['checkedAt']=self.now;atomic_json(path,cached)
            return status,response_headers,cached['body']
        if status==404:return status,response_headers,''
        require(status==200,'http-status','Official page returned HTTP '+str(status))
        try:text=body.decode('utf-8-sig')
        except UnicodeError:raise DiscoveryError('invalid-encoding','Official page is not UTF-8') from None
        item={'url':url,'body':text,'checkedAt':self.now}
        for key,name in [('etag','etag'),('lastModified','last-modified')]:
            value=safe_header(response_headers.get(name))
            if value:item[key]=value
        atomic_json(path,item)
        return status,response_headers,text

    def allowed(self,url):
        parsed=urlsplit(safe_url(url));robots=parsed.scheme+'://'+parsed.netloc+'/robots.txt'
        cached=read_json(self._path(robots),{})
        if type(cached.get('checkedAt')) is int and self.now-DAY<cached['checkedAt']<=self.now and isinstance(cached.get('body'),str):text=cached['body']
        else:
            status,_,text=self._http(robots)
            require(status in (200,304,404),'robots-unavailable','Robots policy could not be checked')
            if status==404:
                text='';atomic_json(self._path(robots),{'url':robots,'body':'','checkedAt':self.now})
        allowed,pause=robots_policy(text,url)
        require(allowed,'robots-blocked','Official site disallows the OTTScout discovery bot')
        previous=self.last.get(parsed.hostname,0);wait=max(0,previous+pause-time.monotonic())
        require(time.monotonic()+wait<self.deadline,'time-budget','Robots crawl delay exceeds remaining time')
        if wait:time.sleep(wait)

    def get(self,url):
        for _ in range(4):
            self.allowed(url);self.last[urlsplit(url).hostname]=time.monotonic()
            status,headers,text=self._http(url)
            if status in (301,302,303,307,308):
                url=safe_url(urljoin(url,headers.get('location','')));continue
            require(status in (200,304),'not-found','Official title page was not found')
            return text,url
        raise DiscoveryError('redirect-limit','Too many official-site redirects')


class Document(HTMLParser):
    def __init__(self,html):
        super().__init__(convert_charrefs=True);self.links=[];self.scripts=[];self.text=[];self.script=None;self.skip=0
        self.feed(html)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='a' and attrs.get('href'):self.links.append(attrs['href'])
        if tag=='script':self.script=[]
        if tag in ('script','style'):self.skip+=1
    def handle_endtag(self,tag):
        if tag=='script' and self.script is not None:self.scripts.append(''.join(self.script));self.script=None
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if self.script is not None:self.script.append(data)
        if not self.skip and data.strip():self.text.append(data.strip())


def sony_state(html):
    document=Document(html);states=[]
    for script in document.scripts:
        match=re.search(r'\bwindow\.INITIAL_STATE\s*=\s*',script)
        if match:
            try:states.append(json.JSONDecoder().raw_decode(script[match.end():])[0])
            except ValueError:raise DiscoveryError('parser-changed','Sony public state is not valid JSON') from None
    require(len(states)==1 and isinstance(states[0],dict),'parser-changed','Sony public HTML state missing or ambiguous')
    state=states[0]
    country=state.get('country')
    result=country.get('resultObj') if isinstance(country,dict) else None
    region=result.get('country') if isinstance(result,dict) else None
    if region != 'India':
        # Keep the India-only gate and distinguish a nonexact value from
        # missing or malformed evidence without reporting arbitrary HTML.
        observed = isinstance(region,str) and bool(re.fullmatch(r'[A-Za-z][A-Za-z .-]{0,63}',region))
        message = 'Sony region is not an exact India match' if observed else 'Sony did not provide a usable region'
        raise DiscoveryError('region-unverified',message)
    return state,document


def walk(value):
    if isinstance(value,dict):
        yield value
        for item in value.values():yield from walk(item)
    elif isinstance(value,list):
        for item in value:yield from walk(item)


def sony_url(url,kind=None):
    try:safe_url(url)
    except DiscoveryError:return None
    p=urlsplit(url)
    if p.hostname not in ('www.sonyliv.com','sonyliv.com') or p.scheme!='https' or p.query not in ('','watch=true'):return None
    match=re.fullmatch(r'/(shows|movies)/([a-zA-Z0-9-]+)-([0-9]{1,30})(?:/([a-zA-Z0-9-]+)-([0-9]{1,30}))?',p.path)
    if not match or (match[1]=='movies' and match[4]) or (kind and (match[1]=='movies')!=(kind=='Movie')):return None
    return {'id':match[3],'slug':match[2],'kind':'Movie' if match[1]=='movies' else 'Series',
            'url':'https://www.sonyliv.com/'+match[1]+'/'+match[2]+'-'+match[3],
            'episodeURL':url if match[4] else None,'episodeId':match[5]}


def parse_sony_index(html,url,kind):
    state,doc=sony_state(html)
    container=state.get('landingpagedata',{}).get('resultObj',{}).get('containers')
    require(isinstance(container,list) and bool(container),'parser-changed','Sony index containers missing')
    links={}
    for href in doc.links:
        item=sony_url(urljoin(url,href),kind)
        if item:
            if item['id'] not in links or item['episodeURL']:links[item['id']]=item
    result=[];seen=set()
    for node in walk(container):
        meta=node.get('metadata',{});ident=str(meta.get('contentId',''))
        if ident in links and ident not in seen and meta.get('objectSubtype') in ('SHOW','MOVIE','MOVIE_BUNDLE'):
            title=meta.get('title')
            require(isinstance(title,str) and 0<len(title)<=300,'parser-changed','Sony candidate title missing')
            try:hint=release_time(meta)
            except DiscoveryError:hint=0
            seen.add(ident);result.append({**links[ident],'title':title,'position':len(result),'dateHint':hint})
    require(bool(result),'parser-changed','Sony index has no exact linked title cards')
    return result[:32]


def sony_main(html,ident):
    state,doc=sony_state(html)
    nodes=state.get('pageDetails',{}).get('showDetails',{}).get('resultObj',{}).get('containers')
    require(isinstance(nodes,list) and bool(nodes),'parser-changed','Sony exact title container missing')
    matches=[node for node in nodes if str(node.get('metadata',{}).get('contentId'))==ident]
    require(len(matches)==1,'identity-unverified','Sony title ID does not match the public URL')
    return matches[0],doc


def release_time(meta):
    raw=meta.get('emfAttributes',{}).get('release_date')
    try:value=int(datetime.fromisoformat(raw.replace('Z','+00:00')).timestamp())
    except (AttributeError,TypeError,ValueError):raise DiscoveryError('date-unverified','Explicit digital release date missing') from None
    return value


def streaming_dates(html,candidate):
    """Only explicit streaming announcements tied to this work, not theatrical dates."""
    state,_=sony_state(html);main,_=sony_main(html,candidate['id'])
    parents={candidate['id']}|{str(p.get('parentId')) for p in main.get('parents',[]) if p.get('parentSubType')=='MOVIE_BUNDLE'}
    months={name.lower():i for i,name in enumerate(('January','February','March','April','May','June','July','August','September','October','November','December'),1)}
    found=set()
    pattern=r'\bstreaming\s+(?:from|on)\s+([0-9]{1,2})(?:st|nd|rd|th)?\s+('+'|'.join(months)+r')(?:[, ]+([0-9]{4}))?\b'
    for node in walk(state):
        meta=node.get('metadata',{})
        if meta.get('objectSubtype')!='MOVIE_TRAILER' or meta.get('title')!=candidate['title']:continue
        if not any(str(p.get('parentId')) in parents for p in node.get('parents',[])):continue
        for day,month,year in re.findall(pattern,meta.get('longDescription',''),re.I):
            found.add((months[month.lower()],int(day),int(year) if year else None))
    require(len(found)==1,'date-unverified','No unique exact-title streaming-date announcement')
    return [list(next(iter(found)))]


def verify_sony(html,candidate,now,faq_html=None,episode_html=None):
    node,_=sony_main(html,candidate['id']);meta=node['metadata'];kind=candidate['kind']
    require(meta.get('title')==candidate['title'],'identity-unverified','Sony linked title name changed')
    require(meta.get('isGeoBlocked') is False,'region-unverified','Sony India listing is geoblocked or unknown')
    subtype=meta.get('objectSubtype')
    if kind=='Movie' and subtype=='MOVIE_BUNDLE':
        variants=[n for n in walk(node.get('containers',[])) if n.get('metadata',{}).get('objectSubtype')=='MOVIE'
                  and n.get('metadata',{}).get('title')==candidate['title']
                  and n.get('metadata',{}).get('isBaseAsset') is True
                  and any(str(parent.get('parentId'))==candidate['id'] for parent in n.get('parents',[]))]
        require(len(variants)==1,'playable-id-unverified','Movie bundle has no unique explicit base movie asset')
        child=str(variants[0]['metadata'].get('contentId',''))
        require(bool(re.fullmatch(r'[0-9]{1,30}',child)),'playable-id-unverified','Invalid explicit movie asset ID')
        return {'resolveURL':'https://www.sonyliv.com/movies/'+candidate['slug']+'-'+child,'resolveId':child,
                'streamingDates':streaming_dates(html,candidate)}
    require(subtype==('MOVIE' if kind=='Movie' else 'SHOW'),'type-unverified','Exact Sony asset is not a full movie/series')
    released=release_time(meta)
    require(now-30*DAY<=released<=now,'outside-window','Title is outside the past30day digital-release window')
    require(type(meta.get('contractStartDate')) is int and meta['contractStartDate']//1000<=now
            and type(meta.get('contractEndDate')) is int and meta['contractEndDate']//1000>now,
            'availability-unverified','Sony current India listing contract dates are unavailable')
    year=meta.get('year');require(isinstance(year,str) and bool(re.fullmatch(r'[0-9]{4}',year)), 'year-unverified','Sony title year missing')
    require(1850<=int(year)<=datetime.fromtimestamp(now,timezone.utc).year+2,'year-unverified','Sony title year invalid')
    emf=meta.get('emfAttributes',{});packages=emf.get('packageid','').split(',')
    require(any(pack in packages for pack in ('LIV_Pre_1M','LIV_Pre_12M')),'access-unverified','No explicit Sony Premium entitlement on exact title')
    if kind=='Movie':
        if candidate.get('bundleId'):
            require(any(str(parent.get('parentId'))==candidate['bundleId'] for parent in node.get('parents',[])),
                    'identity-unverified','Full movie asset no longer belongs to the indexed bundle')
        require(meta.get('comingSoon') is False,'source-flag-conflict','Full Sony movie still explicitly marked coming soon')
        require(type(meta.get('duration')) is int and meta['duration']>=1800,'availability-unverified','Full movie runtime unavailable')
        announcement=candidate.get('streamingDates') or streaming_dates(html,candidate)
        day=datetime.fromtimestamp(released,IST)
        require(len(announcement)==1 and announcement[0][:2]==[day.month,day.day]
                and announcement[0][2] in (None,day.year),'date-unverified','Streaming announcement and exact asset date disagree')
    else:
        require(type(meta.get('episodeCount')) is int and meta['episodeCount']>0,'availability-unverified','No full episodes listed')
        require(candidate.get('episodeId') and episode_html,'availability-unverified','No linked public full-episode evidence')
        episode,_=sony_main(episode_html,candidate['episodeId']);em=episode['metadata']
        require(em.get('objectSubtype')=='EPISODE' and type(em.get('duration')) is int and em['duration']>=300
                and em.get('isGeoBlocked') is False and any(str(parent.get('parentId'))==candidate['id'] for parent in episode.get('parents',[])),
                'availability-unverified','Full episode does not verify this exact India series')
        require(em.get('comingSoon') is False,'source-flag-conflict','Full Sony episode still explicitly marked coming soon')
        require(release_time(em)<=now and em.get('contractStartDate',now*1000+1)//1000<=now,
                'availability-unverified','Linked full episode has not released')
        require(str(em.get('episodeNumber'))=='1' and emf.get('broadcast_channel') in ('SAB','SET')
                and datetime.fromtimestamp(release_time(em),IST).date()==datetime.fromtimestamp(em['contractStartDate']//1000,IST).date(),
                'date-unverified','Series needs exact first-episode release/start evidence')
    audio=[]
    for language in emf.get('audio_language_list',[]):
        if not isinstance(language,dict) or language.get('lang_identifier')=='AD':continue
        known=LANGUAGES.get(language.get('lang_code'))
        if known and language.get('lang_label')==known and known not in audio:audio.append(known)
    return {'id':'motn:official-sonyliv-'+candidate['id'],'platform':'SonyLIV','platformTitleId':candidate['id'],
            'title':meta['title'],'type':kind,'year':int(year),'sourceURL':candidate['url'],
            'releaseDate':datetime.fromtimestamp(released,IST).date().isoformat(),'releaseEvidenceURL':candidate['url'],
            'verifiedAt':now,'expiresAt':now+30*DAY,'access':{'type':'subscription','evidenceURL':candidate['url']},
            'audio':audio,**({'audioEvidenceURL':candidate['url']} if audio else {}),
            'originalLanguage':None,'originalLanguageEvidenceURL':None}


def provider_covered(catalog,candidate):
    for title in catalog.get('titles',[]):
        for offer in title.get('offers',[]):
            parsed=sony_url(offer.get('link',''),candidate['kind'])
            if offer.get('platform')=='SonyLIV' and offer.get('availabilitySourceType')!='official-listing' and parsed and parsed['id']==candidate['id']:return True
    return False


def discover(cache_dir,now,*,catalog=None,sources=None,client=None):
    directory=Path(cache_dir);directory.mkdir(parents=True,exist_ok=True)
    path=directory/'state.json'
    try:state=json.loads(path.read_text()) if path.exists() else {'schemaVersion':1,'policyVersion':2,'records':{},'attempts':{},'sources':{}}
    except (OSError,ValueError):raise DiscoveryError('cache-invalid','Discovery state is unreadable; keep the last published registry') from None
    require(isinstance(state,dict) and state.get('schemaVersion')==1 and all(isinstance(state.get(k),dict) for k in ('records','attempts','sources')),'cache-invalid','Discovery state is malformed')
    if state.get('policyVersion')!=2:
        # Earlier local previews lacked the explicit coming-soon/date gates.
        # Never grandfather those candidates into the reviewed verifier.
        state['records']={};state['policyVersion']=2
    catalog=catalog or {};sources=DEFAULT_SOURCES if sources is None else sources;client=client or PublicClient(directory/'http',now)
    require(bool(sources),'source-invalid','No reviewed sources configured')
    # Keep omitted paused sources paused too: selecting only another source
    # must not publish saved Sony proof from an earlier enabled configuration.
    policies={source['id']:source for source in DEFAULT_SOURCES}
    policies.update({source['id']:source for source in sources})
    def paused_record(key,record):
        ident=key.split(':',1)[0]
        source=policies.get(ident)
        if source and source.get('enabled') is False:return source
        return next((source for source in policies.values() if source.get('enabled') is False
                     and source['platform']==record.get('platform') and source.get('kind')==record.get('type')),None)
    start=state.get('sourceCursor',0)%len(sources)
    ordered_sources=sources[start:]+sources[:start]
    state['sourceCursor']=(start+1)%len(sources)
    atomic_json(path,state)
    report={'schemaVersion':1,'evaluatedAt':now,'sources':[],'unsupportedPlatforms':['Prime Video','JioHotstar','ZEE5','Sun NXT','aha'],
            'coverageNote':'Automatic coverage is limited by source permission and robots policy. Paused sources are not contacted. This is not a complete provider catalogue.',
            'revokedAutomaticRecords':[],'quarantinedRecords':[]}
    save=lambda:atomic_json(path,state)
    for source in ordered_sources:
        ident=source['id'];client.source=ident;old=state['sources'].get(ident,{})
        item={'id':ident,'platform':source['platform'],'required':source['adapter']=='sony','lastAttemptAt':now,'lastSuccessAt':old.get('lastSuccessAt'),
              'status':'ok','attempted':0,'candidates':0,'confirmed':0,'gaps':0,'errors':[],'unverifiedCandidates':[]}
        report['sources'].append(item)
        if source.get('enabled') is False:
            # Do not even ask robots.txt: permission is a prerequisite distinct
            # from path-level crawling policy or an available cached response.
            item.update({'status':'paused','required':False,'pauseReason':source.get('pauseReason','permission-required'),
                         'lastAttemptAt':old.get('lastAttemptAt'),'sourceFlagConflicts':0,'warnings':[]})
            state['sources'][ident]=deepcopy(item);save()
            continue
        state['sources'][ident]=deepcopy(item);save()
        try:
            html,final=client.get(source['url'])
            if source['adapter']=='netflix-tudum':
                raise DiscoveryError('parser-not-enabled','Netflix robots permission and a verified region-aware adapter are required before activation')
            candidates=parse_sony_index(html,final,source['kind']);item['candidates']=len(candidates);item['lastSuccessAt']=now
            # Reserve opportunities for the other independent index. A large
            # movie archive must not consume every request before series scan.
            client.source_limits[ident]=client.attempted.get(ident,0)+4
            candidates.sort(key=lambda c:(state['attempts'].get(ident+':'+c['id'],0),provider_covered(catalog,c),
                -c.get('dateHint',0) if source['kind']=='Series' else c['position']))
            for candidate_index,candidate in enumerate(candidates):
                key=ident+':'+candidate['id'];record=state['records'].get(key)
                if provider_covered(catalog,candidate):continue
                if record and record.get('expiresAt',0)>now and record.get('verifiedAt',0)>now-6*3600:
                    item['confirmed']+=1;continue
                try:
                    client.checkpoint()
                    state['attempts'][key]=now;save()  # Advance before slow/failing I/O so later candidates cannot starve.
                    title_html,_=client.get(candidate['url'])
                    episode_html=client.get(candidate['episodeURL'])[0] if candidate.get('episodeURL') else None
                    verified=verify_sony(title_html,candidate,now,episode_html=episode_html)
                    if verified.get('resolveURL'):
                        primary_candidate=candidate
                        child=sony_url(verified['resolveURL'],'Movie');require(child is not None,'identity-unverified','Invalid resolved movie URL')
                        candidate={**child,'title':candidate['title'],'bundleId':primary_candidate['id'],'streamingDates':verified['streamingDates']}
                        title_html,_=client.get(candidate['url'])
                        verified=verify_sony(title_html,candidate,now)
                        # The official index identifies the whole movie bundle.
                        # Its public HTML contains this explicitly related base
                        # asset and its digital date, distinct from theatrical date.
                        verified.update({'id':'motn:official-sonyliv-'+primary_candidate['id'],
                            'platformTitleId':primary_candidate['id'],'sourceURL':primary_candidate['url'],
                            'releaseEvidenceURL':primary_candidate['url']})
                        verified['access']['evidenceURL']=primary_candidate['url']
                        if verified['audio']:verified['audioEvidenceURL']=primary_candidate['url']
                    state['records'][key]=verified;item['confirmed']+=1;save()
                except DiscoveryError as error:
                    if error.code=='outside-window':continue
                    if error.code=='source-flag-conflict':
                        # This is exact-title contradictory evidence, unlike a
                        # timeout or changed parser. Quarantine automatic proof
                        # immediately; reviewed corrections are a separate file.
                        revoked=state['records'].pop(key,None)
                        if revoked:
                            report['revokedAutomaticRecords'].append({'id':revoked['id'],'checkedAt':now,'reason':error.code})
                            save()
                    item['unverifiedCandidates'].append({'platformTitleId':candidate['id'],'title':candidate['title'],'reason':error.code})
                    if error.code in ('request-budget','time-budget','byte-budget','source-budget'):
                        item['unverifiedCandidates'].extend({'platformTitleId':pending['id'],'title':pending['title'],'reason':error.code}
                            for pending in candidates[candidate_index+1:] if not provider_covered(catalog,pending))
                        break
                except (AttributeError,TypeError,KeyError,RecursionError):
                    item['unverifiedCandidates'].append({'platformTitleId':candidate['id'],'title':candidate['title'],'reason':'parser-changed'})
        except DiscoveryError as error:
            item['status']='blocked' if error.code=='robots-blocked' else 'error'
            item['errors'].append({'code':error.code,'message':str(error)})
        except (AttributeError,TypeError,KeyError,RecursionError):
            item['status']='error';item['errors'].append({'code':'parser-changed','message':'Official HTML structure changed'})
        item['attempted']=client.attempted.get(ident,0);item['gaps']=len(item['unverifiedCandidates'])
        item['sourceFlagConflicts']=sum(c['reason']=='source-flag-conflict' for c in item['unverifiedCandidates'])
        item['warnings']=[{'code':'source-flag-conflict','platformTitleId':c['platformTitleId'],'message':'Current availability flags conflict; no record published'}
                          for c in item['unverifiedCandidates'] if c['reason']=='source-flag-conflict']
        if item['gaps'] and item['status']=='ok':item['status']='partial'
        state['sources'][ident]=deepcopy(item);save()
    records=[];seen=set()
    for key,record in state['records'].items():
        if isinstance(record,dict) and (paused:=paused_record(key,record)):
            report['quarantinedRecords'].append({'id':record.get('id'),'sourceId':paused['id'],
                'reason':paused.get('pauseReason','permission-required'),
                'verifiedAt':record.get('verifiedAt'),'expiresAt':record.get('expiresAt')})
            continue
        if isinstance(record,dict) and type(record.get('expiresAt')) is int and record['expiresAt']>now and record.get('verifiedAt',now+1)<=now:
            identity=(record.get('platform'),record.get('platformTitleId'))
            if identity not in seen:seen.add(identity);records.append(record)
    records=sorted(records,key=lambda r:(r['platform'],r['platformTitleId']))[:80]
    report['expectedVerifiedRecent']=[{key:record[key] for key in ('id','platform','platformTitleId','title','type','releaseDate','verifiedAt','expiresAt')} for record in records]
    report['expiredRecords']=[{'id':record.get('id'),'expiresAt':record.get('expiresAt')} for record in state['records'].values()
                              if isinstance(record,dict) and type(record.get('expiresAt')) is int and record['expiresAt']<=now]
    report['publicRequests']=client.requests;report['publicBytes']=client.bytes;report['providerApiRequests']=0
    return records,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-dir',default='.state/official-discovery')
    parser.add_argument('--output',default='data/official-discovered.json')
    parser.add_argument('--report',default='reports/official-discovery.json')
    parser.add_argument('--catalog',type=Path)
    parser.add_argument('--sources',type=Path,default=ROOT/'data/official-sources.json')
    parser.add_argument('--max-requests',type=int,default=12)
    parser.add_argument('--max-seconds',type=int,default=120)
    parser.add_argument('--now',type=int,default=None)
    parser.add_argument('--sony-ssh-host',default=None)
    parser.add_argument('--sony-ssh-identity',default=None)
    parser.add_argument('--sony-ssh-known-hosts',default=None)
    args=parser.parse_args();now=args.now or int(time.time())
    require(1<=args.max_requests<=12 and 1<=args.max_seconds<=300,'invalid-limit','Discovery limits are out of range')
    sources=read_json(args.sources,DEFAULT_SOURCES)
    require(isinstance(sources,list) and all(s in DEFAULT_SOURCES for s in sources),'source-invalid','Only reviewed official sources may run')
    catalog=read_json(args.catalog,{}) if args.catalog else {}
    relay_args=(args.sony_ssh_host,args.sony_ssh_identity,args.sony_ssh_known_hosts)
    if not any(source.get('adapter') == 'sony' and source.get('enabled') is True for source in sources):
        # A permission pause dominates all transport settings, including relay
        # configuration left over from a previous deployment.
        relay_args=(None,None,None)
    require(not any(relay_args) or all(relay_args),'relay-config','All Sony relay settings are required')
    if all(relay_args):
        # Never reuse another egress location's cached HTML or conditional headers.
        from sony_india_transport import SonyIndiaTransport
        transport=SonyIndiaTransport(*relay_args)
        with tempfile.TemporaryDirectory(prefix='ottscout-india-http-') as http_dir:
            try:
                records,report=discover(args.cache_dir,now,catalog=catalog,sources=sources,
                    client=PublicClient(http_dir,now,max_requests=args.max_requests,max_seconds=args.max_seconds,transport=transport))
            finally:transport.close()
    else:
        records,report=discover(args.cache_dir,now,catalog=catalog,sources=sources,
            client=PublicClient(Path(args.cache_dir)/'http',now,max_requests=args.max_requests,max_seconds=args.max_seconds))
    atomic_json(args.output,records);atomic_json(args.report,report)
    print(json.dumps({'confirmed':len(records),'publicRequests':report['publicRequests'],'sources':[{k:s[k] for k in ('id','status','candidates','confirmed','gaps')} for s in report['sources']]}))


if __name__=='__main__':main()
