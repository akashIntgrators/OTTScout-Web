"""Pure, dated official-listing overlay. This module never performs network I/O."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import re
from urllib.parse import parse_qs, urlparse

DAY = 86400
IST = timezone(timedelta(hours=5, minutes=30))
LANGUAGES = {'English', 'Hindi', 'Telugu', 'Tamil', 'Kannada', 'Malayalam'}
SERVICES = {'JioHotstar':'hotstar', 'Netflix':'netflix'}
PLATFORMS = {'Netflix','Prime Video','Sun NXT','JioHotstar','ZEE5','aha','SonyLIV'}
MIXED_SOURCE = {'name':'OTTScout provider and official listings','url':'https://ottscout.techiwithhelmet.com/about/'}
KEYS = {'id','platform','platformTitleId','title','type','year','sourceURL','releaseDate','releaseEvidenceURL',
        'verifiedAt','expiresAt','access','audio','audioEvidenceURL','originalLanguage','originalLanguageEvidenceURL'}
REQUIRED = KEYS - {'year','audioEvidenceURL','originalLanguage','originalLanguageEvidenceURL'}


class OfficialListingError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise OfficialListingError(message)


def _text(value, maximum=500):
    return isinstance(value,str) and 0 < len(value) <= maximum and value == value.strip() and not any(ord(c)<32 for c in value)


def _url(value):
    if not _text(value,2000): return None
    try:
        url=urlparse(value)
        if url.scheme!='https' or url.username or url.password or url.port not in (None,443) or url.fragment:
            return None
        return url
    except ValueError:
        return None


def _identity(value, platform, kind, canonical=False):
    url=_url(value)
    if not url or (canonical and url.query): return None
    parts=url.path.strip('/').split('/')
    if platform=='JioHotstar' and url.hostname in ('hotstar.com','www.hotstar.com'):
        if not canonical and parts[-1:]==['watch']: parts=parts[:-1]
        if len(parts)!=4 or parts[:2]!=['in','shows' if kind=='Series' else 'movies'] or not re.fullmatch(r'[a-zA-Z0-9-]+',parts[2]): return None
        ident=parts[3]
        if canonical and (url.hostname!='www.hotstar.com' or url.path!='/'+'/'.join(parts)): return None
    elif platform=='Netflix' and url.hostname in ('netflix.com','www.netflix.com'):
        if canonical:
            if url.hostname!='www.netflix.com' or len(parts)!=3 or parts[:2]!=['in','title'] or url.path!='/'+'/'.join(parts): return None
            ident=parts[2]
        elif len(parts)==2 and parts[0] in ('title','watch'): ident=parts[1]
        elif len(parts)==3 and parts[:2] in (['in','title'],['in','watch']): ident=parts[2]
        else:return None
    else:return None
    return ident if re.fullmatch(r'[0-9]{1,30}',ident) else None


def _evidence(value, row, purpose):
    url=_url(value)
    if not url:return False
    if _identity(value,row['platform'],row['type'])==row['platformTitleId']:
        return True
    if row['platform']=='JioHotstar':
        if purpose in ('release','original','access') and url.hostname=='cdn.jiostar.com':
            return not url.query and url.path.lower().endswith('.pdf') and (purpose!='access' or url.path.startswith('/jiostar/'))
        if purpose in ('release','audio') and row['type']=='Series' and url.hostname=='moviesandtv.myvi.in':
            return not url.query and url.path=='/tvshow/hs-'+row['platformTitleId']
    if purpose=='release':
        if url.hostname in ('youtube.com','www.youtube.com') and url.path=='/watch':
            params=parse_qs(url.query,keep_blank_values=True)
            return set(params)=={'v'} and len(params['v'])==1 and bool(re.fullmatch(r'[A-Za-z0-9_-]{11}',params['v'][0]))
        if url.hostname=='youtu.be':
            return not url.query and bool(re.fullmatch(r'/[A-Za-z0-9_-]{11}',url.path))
    return False


def _validate(row, now, known_ids):
    _require(isinstance(row,dict) and REQUIRED<=set(row)<=KEYS,'Invalid official-listing fields')
    _require(isinstance(row['platform'],str) and row['platform'] in SERVICES and row['type'] in ('Movie','Series'),'Unsupported official-listing platform/type')
    _require(_text(row['title'],300),'Invalid official title')
    ident=row['platformTitleId']
    _require(isinstance(ident,str) and bool(re.fullmatch(r'[0-9]{1,30}',ident)),'Invalid official platform ID')
    canonical='motn:official-'+SERVICES[row['platform']]+'-'+ident
    _require(_text(row['id'],100) and (row['id']==canonical or (bool(re.fullmatch(r'motn:[0-9]+',row['id'])) and row['id'] in known_ids)), 'Invalid or unknown canonical title ID')
    _require(_identity(row['sourceURL'],row['platform'],row['type'],True)==ident,'Official source is not the exact canonical India listing')
    year=row.get('year')
    _require(year is None or (type(year) is int and 1850<=year<=datetime.fromtimestamp(now,timezone.utc).year+2),'Invalid official title year')
    _require(isinstance(row['releaseDate'],str) and bool(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',row['releaseDate'])),'Invalid official release date')
    try: release=int(datetime.strptime(row['releaseDate'],'%Y-%m-%d').replace(tzinfo=IST).timestamp())
    except ValueError: raise OfficialListingError('Invalid official release date') from None
    _require(release>=0,'Invalid official release date')
    verified=row['verifiedAt'];expiry=row['expiresAt']
    _require(type(verified) is int and 0<verified<=now and type(expiry) is int and verified<expiry<=verified+30*DAY,'Invalid official evidence validity')
    _require(_evidence(row['releaseEvidenceURL'],row,'release'),'Invalid release evidence URL')
    access=row['access']
    _require(isinstance(access,dict) and set(access)=={'type','evidenceURL'} and access['type'] in ('subscription','free','rent','buy','addon'),'Invalid official access evidence')
    _require(_evidence(access['evidenceURL'],row,'access'),'Invalid official access evidence URL')
    audio=row['audio']
    _require(isinstance(audio,list) and len(audio)<=6 and all(isinstance(x,str) and x in LANGUAGES for x in audio) and len(set(audio))==len(audio),'Invalid official audio languages')
    _require((not audio and row.get('audioEvidenceURL') is None) or (bool(audio) and _evidence(row.get('audioEvidenceURL'),row,'audio')),'Official audio requires explicit exact-title evidence')
    original=row.get('originalLanguage')
    _require((original is None and row.get('originalLanguageEvidenceURL') is None) or (isinstance(original,str) and original in LANGUAGES and _evidence(row.get('originalLanguageEvidenceURL'),row,'original')),'Original language requires explicit primary evidence')
    return release


def _merge_unique(items):
    seen=set();result=[]
    for item in items:
        key=json.dumps(item,sort_keys=True,ensure_ascii=False)
        if key not in seen:seen.add(key);result.append(item)
    return result


def _title_id(value):
    return _text(value,100) and bool(re.fullmatch(r'motn:(?:[0-9]+|official-(?:hotstar|netflix)-[0-9]+)',value))


def _resolve_alias(ident, aliases):
    seen=set()
    while ident.startswith('motn:') and ident in aliases:
        _require(ident not in seen,'Cyclic official title alias')
        seen.add(ident);ident=aliases[ident]
    return ident


def _apply_title_aliases(titles, aliases, now):
    """Learned identity survives removal of a curated row or platform offer."""
    grouped={};anchors={}
    for key,target in aliases.items():
        canonical=_resolve_alias(target,aliases)
        if not key.startswith('motn:'):
            service,ident=key.split(':',1)
            anchors.setdefault(canonical,set()).add(({'hotstar':'JioHotstar','netflix':'Netflix'}[service],ident))
        embedded=re.fullmatch(r'motn:official-(hotstar|netflix)-([0-9]+)',canonical)
        if embedded:
            anchors.setdefault(canonical,set()).add(({'hotstar':'JioHotstar','netflix':'Netflix'}[embedded[1]],embedded[2]))
    for title in titles:
        canonical=_resolve_alias(title['id'],aliases)
        # An explicitly different current platform ID is a conflict; absence of
        # that platform is merely missing coverage and remains aliasable.
        for platform,ident in anchors.get(canonical,()):
            current={_identity(offer.get('link'),platform,title['type']) for offer in title['offers'] if offer.get('platform')==platform}
            current.discard(None)
            _require(not current or ident in current,'Learned alias conflicts with current platform identity')
        grouped.setdefault(canonical,[]).append(title)
    output=[]
    for canonical,group in grouped.items():
        _require(len({title.get('type') for title in group})==1,'Conflicting aliased title types')
        for platform in SERVICES:
            identities=[]
            for title in group:
                current={_identity(offer.get('link'),platform,title['type']) for offer in title['offers'] if offer.get('platform')==platform}
                current.discard(None)
                if current:identities.append(current)
            _require(not identities or bool(set.intersection(*identities)),'Conflicting aliased platform identities')
        title=deepcopy(max(group,key=lambda item:(item.get('lastCheckedAt',0),item['id']==canonical,item['id'])))
        title['id']=canonical
        if len(group)>1:
            title['offers']=_merge_unique([offer for item in group for offer in item['offers']])
            title['weeklyEvents']=_merge_unique([event for item in group for event in item.get('weeklyEvents',[])])
            _week(title,now)
        output.append(title)
    return output


def _week(title, now):
    # One deterministic event per platform fits native clients' seven-platform
    # bound. Preserve other platforms; prefer the newest fact, then provider on ties.
    by_platform={}
    for event in title.get('weeklyEvents',[]):
        _require(event.get('platform') in PLATFORMS and type(event.get('addedAt')) is int,'Invalid weekly event')
        platform=event['platform']
        def rank(item):
            return (item['addedAt'],item.get('sourceType')!='official-listing',json.dumps(item,sort_keys=True))
        if platform not in by_platform or rank(event)>rank(by_platform[platform]):by_platform[platform]=event
    events=list(by_platform.values())
    title['weeklyEvents']=events
    recent=[event for event in events if type(event.get('addedAt')) is int and now-7*DAY<=event['addedAt']<=now]
    title['weeklyPlatforms']=list(dict.fromkeys(event['platform'] for event in recent))
    title['weeklyUpdatedAt']=max((event['addedAt'] for event in recent),default=None)
    title['weekly']=bool(recent)


def apply_official_listings(catalog, records, now):
    """Return (independent catalogue, summary); invalid registry input fails closed."""
    _require(type(now) is int and 0<now<=4102444800,'Invalid official overlay evaluation time')
    _require(isinstance(catalog,dict) and isinstance(catalog.get('titles'),list) and len(catalog['titles'])<=100000,'Invalid catalogue')
    _require(isinstance(records,list) and len(records)<=100,'Invalid official registry')
    output=deepcopy(catalog)
    aliases=output.get('officialListingAliases',{})
    _require(isinstance(aliases,dict) and len(aliases)<=1000 and all(_text(k,100) and (_title_id(k) or bool(re.fullmatch(r'(?:hotstar|netflix):[0-9]{1,30}',k))) and _title_id(v) for k,v in aliases.items()),'Invalid existing official aliases')
    for value in list(aliases):aliases[value]=_resolve_alias(aliases[value],aliases)
    raw_removals=output.get('officialListingRemovals',[])
    _require(isinstance(raw_removals,list) and len(raw_removals)<=1000,'Invalid official removal signals')
    removals={}
    for removal in raw_removals:
        _require(isinstance(removal,dict) and set(removal)=={'id','platform','removedAt'} and _title_id(removal['id']) and isinstance(removal['platform'],str) and removal['platform'] in PLATFORMS and type(removal['removedAt']) is int and 0<removal['removedAt']<=now,'Invalid official removal signal')
        key=(_resolve_alias(removal['id'],aliases),removal['platform'])
        removals[key]=max(removals.get(key,0),removal['removedAt'])
    if raw_removals:
        output['officialListingRemovals']=[{'id':ident,'platform':platform,'removedAt':removed} for (ident,platform),removed in sorted(removals.items())]
    known_ids=set(aliases.values())
    catalogue_ids=set()
    for title in output['titles']:
        _require(isinstance(title,dict) and _text(title.get('id'),100) and isinstance(title.get('offers'),list),'Invalid catalogue title')
        _require(title['id'] not in catalogue_ids,'Duplicate catalogue title ID')
        _require(all(isinstance(offer,dict) for offer in title['offers']) and isinstance(title.get('weeklyEvents',[]),list) and all(isinstance(event,dict) for event in title.get('weeklyEvents',[])),'Invalid catalogue offers/events')
        catalogue_ids.add(title['id'])
        known_ids.add(title['id'])
    checked=[];ids=set();identities=set();urls=set()
    for row in records:
        release=_validate(row,now,known_ids)
        _require(_resolve_alias(row['id'],aliases)==row['id'],'Registry canonical ID conflicts with a learned alias')
        identity=SERVICES[row['platform']]+':'+row['platformTitleId']
        _require(row['id'] not in ids and identity not in identities and row['sourceURL'] not in urls,'Duplicate or conflicting official listing')
        _require(identity not in aliases or aliases[identity]==row['id'],'Conflicting stable official alias')
        ids.add(row['id']);identities.add(identity);urls.add(row['sourceURL']);checked.append((row,release,identity))

    # Rebuild derived facts on every application; cache source enrichment for a
    # still-active identity, but never keep expired official offers or events.
    clean=[];previous={}
    for title in output['titles']:
        had_official_offer=any(offer.get('availabilitySourceType')=='official-listing' for offer in title['offers'])
        had_official_event=any(event.get('sourceType')=='official-listing' for event in title.get('weeklyEvents',[]))
        title['offers']=[offer for offer in title['offers'] if offer.get('availabilitySourceType')!='official-listing']
        if had_official_event:
            title['weeklyEvents']=[event for event in title['weeklyEvents'] if event.get('sourceType')!='official-listing']
        if isinstance(title.get('officialListing'),dict):
            previous[title['id']]=deepcopy(title)
            if title['officialListing'].get('status')=='fallback' and not title['offers']:
                continue
            canonical_id = aliases.get(title['id'], title['id'])
            if canonical_id not in ids:
                title.pop('officialListing', None)
        if had_official_offer or had_official_event:_week(title,now)
        clean.append(title)
    summary={'schemaVersion':1,'evaluatedAt':now,'records':len(records),'active':0,'fallback':0,'providerMatched':0,'expired':0,'inactive':0}
    for row,release,identity in checked:
        suppressed=removals.get((row['id'],row['platform']),0)>=row['verifiedAt']
        active=release<=row['verifiedAt'] and release<=now<row['expiresAt'] and not suppressed
        summary['active']+=int(active);summary['expired']+=int(now>=row['expiresAt']);summary['inactive']+=int(not active)
        aliases[identity]=row['id']
        matches=[title for title in clean if title['id']==row['id'] or aliases.get(title['id'])==row['id'] or any(offer.get('platform')==row['platform'] and _identity(offer.get('link'),row['platform'],row['type'])==row['platformTitleId'] for offer in title['offers'])]
        _require(all(title.get('type')==row['type'] for title in matches),'Conflicting official/provider title type')
        provider_match=any(offer.get('platform')==row['platform'] and _identity(offer.get('link'),row['platform'],row['type'])==row['platformTitleId'] for title in matches for offer in title['offers'])
        if not matches and not active:continue
        current_identity={key:row.get(key) for key in ('title','type','year')}
        cached=previous.get(row['id'],{})
        previous_identity=cached.get('officialListing',{}).get('titleIdentity',{key:cached.get(key) for key in ('title','type','year')})
        identity_unchanged=not cached or previous_identity==current_identity
        if matches:
            title=deepcopy(max(matches,key=lambda title:title.get('lastCheckedAt',0)))
            title['offers']=_merge_unique([offer for item in matches for offer in item['offers']])
            title['weeklyEvents']=_merge_unique([event for item in matches for event in item.get('weeklyEvents',[])])
            for item in matches:
                if item['id']!=row['id']:
                    _require(item['id'] not in aliases or aliases[item['id']]==row['id'],'Conflicting provider identity alias')
                    aliases[item['id']]=row['id']
                clean.remove(item)
        else:
            title=deepcopy(previous.get(row['id'],{'id':row['id'],'title':row['title'],'type':row['type'],'year':row.get('year'),
                'offers':[],'poster':None,'overview':'','genres':[],'originalLanguage':None,'firstObservedAt':row['verifiedAt'],
                'lastCheckedAt':row['verifiedAt'],'weeklyEvents':[]}))
            title['lastCheckedAt']=row['verifiedAt']
            title.update(current_identity)
            if not identity_unchanged:
                for key in ('tmdb','tmdbId','imdbId','tmdbMatchStatus','providerOriginalLanguage','providerOriginalLanguageSource','originalLanguageSource'):
                    title.pop(key,None)
                title.update({'originalLanguage':None,'poster':None,'overview':'','genres':[]})
        # Preserve independent TMDB enrichment when a provider arrives without it.
        for key,value in cached.items():
            if identity_unchanged and key in ('tmdb','tmdbMatchStatus','originalLanguage','originalLanguageSource','providerOriginalLanguage','providerOriginalLanguageSource') and title.get(key) is None:
                title[key]=deepcopy(value)
        title['id']=row['id']
        title['officialListing']={key:row[key] for key in ('platform','sourceURL','releaseDate','releaseEvidenceURL','verifiedAt','expiresAt')}
        title['officialListing'].update({'status':'provider-matched' if provider_match else 'fallback','active':active,'titleIdentity':current_identity,'indiaPlaybackVerified':False})
        if not active:title['officialListing']['inactiveReason']='expired' if now>=row['expiresAt'] else 'newer-provider-removal' if suppressed else 'awaiting-post-release-verification'
        if provider_match:
            summary['providerMatched']+=1
        elif active:
            offer={'platform':row['platform'],'type':row['access']['type'],'audio':list(row['audio']),'subtitles':[],
                'link':row['sourceURL'],'addon':None,'availableSince':None,'officialReleaseAt':release,'datePrecision':'day',
                'availabilitySource':'Official '+row['platform']+' listing','availabilitySourceType':'official-listing',
                'availabilitySourceURL':row['sourceURL'],'availabilityCheckedAt':row['verifiedAt'],'checkedAt':row['verifiedAt'],
                'evidenceExpiresAt':row['expiresAt'],'accessSourceURL':row['access']['evidenceURL'],
                'audioStatus':'reported' if row['audio'] else 'unverified'}
            if row['audio']:
                offer.update({'audioSource':'Official title audio evidence','audioSourceURL':row['audioEvidenceURL'],'audioCheckedAt':row['verifiedAt']})
            title['offers'].append(offer);summary['fallback']+=1
            if not title.get('originalLanguage') and row.get('originalLanguage'):
                title.update({'originalLanguage':row['originalLanguage'],'originalLanguageSource':row['originalLanguageEvidenceURL']})
            if now-7*DAY<=release<=now:
                title['weeklyEvents'].append({'platform':row['platform'],'addedAt':release,'datePrecision':'day',
                    'sourceType':'official-listing','sourceURL':row['releaseEvidenceURL']})
        if title['offers']:
            _week(title,now);clean.append(title)
    output['titles']=_apply_title_aliases(clean,aliases,now)
    output['officialListingAliases']=aliases
    output['officialListingOverlay']=deepcopy(summary)
    if summary['fallback']:
        if output.get('source')!=MIXED_SOURCE:
            output['providerSource']=deepcopy(output.get('source'))
        output['source']=deepcopy(MIXED_SOURCE)
    elif output.get('source')==MIXED_SOURCE:
        original=output.pop('providerSource',None)
        if original is None:output.pop('source',None)
        else:output['source']=original
    return output,summary
