import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import official_discovery as d
from scripts.official_listings import apply_official_listings

FIXTURE_PATH=Path(__file__).parent/'fixtures/official_discovery/sony-public-2026-11-20.json'
FIXTURES=json.loads(FIXTURE_PATH.read_text())['fixtures']
NOW=int(datetime(2026,11,20,19,tzinfo=timezone.utc).timestamp())
FAQ_HTML='<p>Sony LIV has following subscription offering in India</p><p>LIV Premium</p><p>Sony SET and SAB shows at same time as TV</p><p>Blockbuster Indian Movies</p>'
SONY_ROBOTS='User-agent: *\nDisallow: /search/*\nDisallow: /api/*\nDisallow: /DETAIL/*\n'
NETFLIX_ROBOTS='User-agent: *\nDisallow: /\nUser-agent: ChatGPT-User\nAllow: /\n'
SERIES_SOURCE=next(x for x in d.DEFAULT_SOURCES if x['id']=='sony-series')
MOVIE_SOURCE=next(x for x in d.DEFAULT_SOURCES if x['id']=='sony-movies')
NETFLIX_SOURCE=next(x for x in d.DEFAULT_SOURCES if x['id']=='netflix-tudum')


class Transport:
    def __init__(self,publishable=False):
        self.docs={v['sourceURL']:v['html'] for v in FIXTURES.values()}
        if publishable:
            # A simulated subsequent response clearing the flag exercises the
            # acceptance path. The recorded current responses remain unchanged.
            for key in ('movie','episode'):
                self.docs[FIXTURES[key]['sourceURL']]=mutate_html(key,lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata'].update(comingSoon=False))
        self.docs[d.FAQ]=FAQ_HTML
        self.docs['https://www.sonyliv.com/robots.txt']=SONY_ROBOTS
        self.docs['https://www.netflix.com/robots.txt']=NETFLIX_ROBOTS
        self.errors={};self.calls=[]
    def __call__(self,url,headers,timeout,maximum,deadline):
        self.calls.append((url,headers))
        if url in self.errors:
            result=self.errors[url]
            if isinstance(result,Exception):raise result
            return result,{},b''
        if url=='https://origin-staticv2.sonyliv.com/robots.txt':return 404,{},b''
        text=self.docs.get(url)
        if text is None:return 404,{},b''
        etag='"'+hashlib.sha256(text.encode()).hexdigest()[:20]+'"'
        if headers.get('If-None-Match')==etag:return 304,{'etag':etag},b''
        return 200,{'etag':etag},text.encode()


def run(directory,transport,now=NOW,sources=None,maximum=12,catalog=None):
    client=d.PublicClient(Path(directory)/'http',now,max_requests=maximum,transport=transport)
    return d.discover(directory,now,sources=sources or [SERIES_SOURCE],client=client,catalog=catalog)


def mutate_html(key,callback):
    original=FIXTURES[key]['html'];state,doc=d.sony_state(original);callback(state)
    return ''.join('<a href="'+x+'">Title</a>' for x in doc.links)+'<script>window.INITIAL_STATE = '+json.dumps(state)+'</script>'


class OfficialDiscoveryTests(unittest.TestCase):
    def test_recorded_series_structure_requires_full_episode_flag_to_clear_before_acceptance(self):
        c=d.parse_sony_index(FIXTURES['series-index']['html'],SERIES_SOURCE['url'],'Series')[0]
        with self.assertRaisesRegex(d.DiscoveryError,'coming soon'):
            d.verify_sony(FIXTURES['series']['html'],c,NOW,FAQ_HTML,FIXTURES['episode']['html'])
        episode=mutate_html('episode',lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata'].update(comingSoon=False))
        record=d.verify_sony(FIXTURES['series']['html'],c,NOW,FAQ_HTML,episode)
        self.assertEqual((record['platformTitleId'],record['releaseDate'],record['audio']),('1790007924','2026-11-18',['Hindi']))
        self.assertIsNone(record['originalLanguage'])
        self.assertEqual(record['access'],{'type':'subscription','evidenceURL':c['url']})
        self.assertEqual(record['expiresAt'],NOW+30*d.DAY)
        self.assertNotIn('overview',record);self.assertNotIn('poster',record)
        self.assertTrue(all(len(f['originalResponseSHA256'])==64 for f in FIXTURES.values()))

    def test_real_movie_bundle_is_resolved_to_full_asset_and_not_its_theatrical_date(self):
        c=d.parse_sony_index(FIXTURES['movie-index']['html'],MOVIE_SOURCE['url'],'Movie')[0]
        resolved=d.verify_sony(FIXTURES['movie-bundle']['html'],c,NOW,FAQ_HTML)
        self.assertEqual(resolved['resolveId'],'1090554778')
        child={**d.sony_url(resolved['resolveURL']),'title':c['title'],'streamingDates':resolved['streamingDates']}
        with self.assertRaisesRegex(d.DiscoveryError,'coming soon'):
            d.verify_sony(FIXTURES['movie']['html'],child,NOW,FAQ_HTML)
        ready=mutate_html('movie',lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata'].update(comingSoon=False))
        record=d.verify_sony(ready,child,NOW,FAQ_HTML)
        self.assertEqual(record['releaseDate'],'2026-11-20')
        self.assertEqual(set(record['audio']),{'Tamil','Hindi','Telugu','Malayalam','Kannada'})
        self.assertNotIn('Tamil AD',record['audio']);self.assertIsNone(record['originalLanguage'])

    def test_missing_region_id_episode_access_or_release_proof_fails_closed(self):
        c=d.parse_sony_index(FIXTURES['series-index']['html'],SERIES_SOURCE['url'],'Series')[0]
        changes=[lambda s:s['country']['resultObj'].update(country='United States'),
                 lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata'].update(contentId=999),
                 lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata'].update(episodeCount=0),
                 lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata']['emfAttributes'].update(packageid=''),
                 lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata']['emfAttributes'].update(release_date='2026-11-25T00:00:00Z')]
        for change in changes:
            with self.assertRaises(d.DiscoveryError):d.verify_sony(mutate_html('series',change),c,NOW,FAQ_HTML,FIXTURES['episode']['html'])
        with self.assertRaises(d.DiscoveryError):d.verify_sony(FIXTURES['series']['html'],c,NOW,FAQ_HTML)

    def test_region_diagnostics_keep_india_gate_and_reject_missing_or_hostile_values(self):
        # Region failures remain failures: a locale preference, arbitrary page
        # text, or a malformed country object is not evidence of India.
        for region in ('United States', 'india', 'India '):
            html=mutate_html('movie-index',lambda state:state['country']['resultObj'].update(country=region))
            with self.assertRaises(d.DiscoveryError) as caught:d.sony_state(html)
            self.assertEqual(caught.exception.code,'region-unverified')
            self.assertEqual(str(caught.exception),'Sony region is not an exact India match')
        for value in (None, [], {'resultObj':None}, {'resultObj':{'country':'<India>'}}):
            html=mutate_html('movie-index',lambda state:state.update(country=value))
            with self.assertRaises(d.DiscoveryError) as caught:d.sony_state(html)
            self.assertEqual(caught.exception.code,'region-unverified')
            self.assertEqual(str(caught.exception),'Sony did not provide a usable region')

    def test_unknown_audio_stays_empty_and_does_not_infer_original(self):
        c=d.parse_sony_index(FIXTURES['series-index']['html'],SERIES_SOURCE['url'],'Series')[0]
        html=mutate_html('series',lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata']['emfAttributes'].pop('audio_language_list'))
        episode=mutate_html('episode',lambda s:s['pageDetails']['showDetails']['resultObj']['containers'][0]['metadata'].update(comingSoon=False))
        record=d.verify_sony(html,c,NOW,FAQ_HTML,episode)
        self.assertEqual(record['audio'],[]);self.assertNotIn('audioEvidenceURL',record);self.assertIsNone(record['originalLanguage'])

    def test_generic_html_or_missing_exact_cards_is_a_parser_error_not_healthy_zero(self):
        for html in ['<html><h1>Welcome</h1></html>','<script>window.INITIAL_STATE = {"country":{"resultObj":{"country":"India"}}}</script>']:
            with self.assertRaises(d.DiscoveryError):d.parse_sony_index(html,SERIES_SOURCE['url'],'Series')

    def test_robots_honors_real_default_deny_without_spoofing_a_whitelisted_bot(self):
        self.assertFalse(d.robots_policy(NETFLIX_ROBOTS,NETFLIX_SOURCE['url'])[0])
        self.assertTrue(d.robots_policy(SONY_ROBOTS,SERIES_SOURCE['url'])[0])
        self.assertFalse(d.robots_policy(SONY_ROBOTS,'https://www.sonyliv.com/api/hidden')[0])
        with tempfile.TemporaryDirectory() as folder:
            t=Transport();records,report=run(folder,t,sources=[NETFLIX_SOURCE])
            self.assertEqual(records,[]);self.assertEqual(report['sources'][0]['status'],'blocked')
            self.assertFalse(report['sources'][0]['required'])
            self.assertEqual(len(t.calls),1);self.assertTrue(t.calls[0][0].endswith('/robots.txt'))
            self.assertTrue(t.calls[0][1]['User-Agent'].startswith('OTTScout'))

    def test_actual_discovery_uses_index_not_curated_registry_and_matches_overlay_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            records,report=run(folder,Transport(publishable=True),sources=[MOVIE_SOURCE,SERIES_SOURCE])
            self.assertEqual(len(records),2)
            movie=next(r for r in records if r['type']=='Movie')
            self.assertEqual(movie['platformTitleId'],'1590016841','Retain official index canonical bundle identity')
            self.assertEqual(movie['releaseDate'],'2026-11-20')
            overlay,_=apply_official_listings({'titles':[]},records,NOW)
            self.assertEqual(len(overlay['titles']),2)
            self.assertLessEqual(report['publicRequests'],12)
            self.assertEqual(report['providerApiRequests'],0)
            self.assertEqual(len(report['expectedVerifiedRecent']),2)

    def test_304_title_revalidation_renews_evidence_but_index_only_success_does_not(self):
        with tempfile.TemporaryDirectory() as folder:
            t=Transport(publishable=True);first,_=run(folder,t)
            later=NOW+7*3600;second,_=run(folder,t,later)
            self.assertEqual(second[0]['verifiedAt'],later)
            title_calls=[headers for url,headers in t.calls if url==FIXTURES['series']['sourceURL']]
            self.assertIn('If-None-Match',title_calls[-1])
            t.errors[FIXTURES['series']['sourceURL']]=503
            third,report=run(folder,t,later+7*3600)
            self.assertEqual(third,second)
            self.assertEqual(report['sources'][0]['status'],'partial')
            self.assertEqual(report['sources'][0]['lastSuccessAt'],later+7*3600)

    def test_source_failure_keeps_last_verified_records_without_renewing_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            t=Transport(publishable=True);first,_=run(folder,t)
            t.errors[SERIES_SOURCE['url']]=503
            second,report=run(folder,t,NOW+3600)
            self.assertEqual(second,first);self.assertEqual(report['sources'][0]['lastSuccessAt'],NOW)
            expired,report=run(folder,t,NOW+31*d.DAY)
            self.assertEqual(expired,[]);self.assertEqual(len(report['expiredRecords']),1)

    def test_exact_title_contradiction_revokes_only_automatic_evidence_and_does_not_touch_reviewed_file(self):
        with tempfile.TemporaryDirectory() as folder:
            t=Transport(publishable=True);first,_=run(folder,t)
            self.assertEqual(len(first),1)
            reviewed=Path(folder)/'data/official-listings.json';reviewed.parent.mkdir();reviewed.write_text(json.dumps(first))
            original_reviewed=reviewed.read_bytes()
            t.docs[FIXTURES['episode']['sourceURL']]=FIXTURES['episode']['html']
            records,report=run(folder,t,NOW+7*3600)
            self.assertEqual(records,[])
            self.assertEqual(report['revokedAutomaticRecords'],[{'id':first[0]['id'],'checkedAt':NOW+7*3600,'reason':'source-flag-conflict'}])
            self.assertEqual(reviewed.read_bytes(),original_reviewed)

    def test_a_conflicting_episode_from_another_series_cannot_revoke_saved_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            t=Transport(publishable=True);first,_=run(folder,t)
            def wrong_parent(state):
                node=state['pageDetails']['showDetails']['resultObj']['containers'][0]
                node['parents']=[{'parentId':999,'parentSubType':'SHOW'}]
                node['metadata']['comingSoon']=True
            t.docs[FIXTURES['episode']['sourceURL']]=mutate_html('episode',wrong_parent)
            records,report=run(folder,t,NOW+7*3600)
            self.assertEqual(records,first)
            self.assertEqual(report['revokedAutomaticRecords'],[])

    def test_existing_exact_provider_id_is_not_renamed_or_downloaded_unnecessarily(self):
        candidate=d.parse_sony_index(FIXTURES['series-index']['html'],SERIES_SOURCE['url'],'Series')[0]
        catalog={'titles':[{'id':'motn:123','offers':[{'platform':'SonyLIV','link':candidate['url']}]}]}
        original=copy.deepcopy(catalog)
        with tempfile.TemporaryDirectory() as folder:
            t=Transport();records,report=run(folder,t,catalog=catalog)
            self.assertEqual(records,[]);self.assertEqual(catalog,original)
            self.assertNotIn(candidate['url'],[url for url,_ in t.calls])
            self.assertEqual(report['sources'][0]['status'],'ok')

    def test_real_current_flag_conflicts_are_reported_and_never_published(self):
        with tempfile.TemporaryDirectory() as folder:
            records,report=run(folder,Transport(),sources=[MOVIE_SOURCE,SERIES_SOURCE])
            self.assertEqual(records,[])
            self.assertTrue(all(source['status']=='partial' for source in report['sources']))
            self.assertTrue(all(source['sourceFlagConflicts'] for source in report['sources']))

    def test_movie_without_explicit_streaming_announcement_cannot_use_theatrical_release_field(self):
        c=d.parse_sony_index(FIXTURES['movie-index']['html'],MOVIE_SOURCE['url'],'Movie')[0]
        def remove_dates(state):
            for node in d.walk(state):
                node.get('metadata',{}).pop('longDescription',None)
        with self.assertRaisesRegex(d.DiscoveryError,'streaming-date'):
            d.verify_sony(mutate_html('movie-bundle',remove_dates),c,NOW)

    def test_redirect_outside_official_allowlist_is_rejected_before_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            t=Transport()
            def redirect(url,*args):
                if url==SERIES_SOURCE['url']:return 302,{'location':'https://evil.test/private'},b''
                return t(url,*args)
            client=d.PublicClient(folder,NOW,transport=redirect)
            with self.assertRaises(d.DiscoveryError):client.get(SERIES_SOURCE['url'])
            self.assertFalse(any('evil.test' in url for url,_ in t.calls))

    def test_byte_and_request_limits_include_robots_and_stop_before_an_extra_get(self):
        with tempfile.TemporaryDirectory() as folder:
            t=Transport();client=d.PublicClient(folder,NOW,max_requests=1,transport=t)
            with self.assertRaises(d.DiscoveryError):client.get(SERIES_SOURCE['url'])
            self.assertEqual(client.requests,1)
        with tempfile.TemporaryDirectory() as folder:
            client=d.PublicClient(folder,NOW,max_document_bytes=5,transport=Transport())
            with self.assertRaises(d.DiscoveryError):client.get(SERIES_SOURCE['url'])

    def test_callers_cannot_disable_the_reviewed_network_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            for options in [{'max_requests':13},{'max_requests':0},{'max_seconds':301},
                            {'max_document_bytes':4_000_001},{'max_total_bytes':24_000_001}]:
                with self.subTest(options=options),self.assertRaises(d.DiscoveryError):
                    d.PublicClient(folder,NOW,transport=Transport(),**options)

    def test_candidate_attempt_checkpoint_moves_later_candidates_ahead_after_a_failed_title(self):
        candidate=d.parse_sony_index(FIXTURES['series-index']['html'],SERIES_SOURCE['url'],'Series')[0]
        second={**candidate,'id':'999','title':'Synthetic failure candidate','position':1,'url':'https://www.sonyliv.com/shows/synthetic-999'}
        with tempfile.TemporaryDirectory() as folder,patch.object(d,'parse_sony_index',return_value=[candidate,second]):
            t=Transport();t.errors[candidate['url']]=503
            run(folder,t,maximum=3)
            state=json.loads((Path(folder)/'state.json').read_text())
            self.assertIn('sony-series:'+candidate['id'],state['attempts'])
            t.calls=[];run(folder,t,NOW+3600,maximum=3)
            requested=[url for url,_ in t.calls if '/shows/' in url]
            self.assertEqual(requested[0],second['url'])

    def test_source_rotation_survives_request_budget_exhaustion(self):
        with tempfile.TemporaryDirectory() as folder:
            first=Transport();_,a=run(folder,first,sources=[MOVIE_SOURCE,SERIES_SOURCE],maximum=2)
            second=Transport();_,b=run(folder,second,NOW+3600,sources=[MOVIE_SOURCE,SERIES_SOURCE],maximum=2)
            self.assertEqual(a['sources'][0]['id'],'sony-movies')
            self.assertEqual(b['sources'][0]['id'],'sony-series')
            self.assertLessEqual(len(second.calls),2)


if __name__=='__main__':unittest.main()
