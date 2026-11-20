import copy
from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
spec = importlib.util.spec_from_file_location('tmdb',Path(__file__).parents[1]/'scripts/tmdb_enrich.py')
tmdb=importlib.util.module_from_spec(spec);spec.loader.exec_module(tmdb)
TITLE={'id':'motn:7','title':'Test Film','type':'Movie','year':2025,'offers':[{'platform':'Netflix','audio':['Hindi']}],'originalLanguage':'Hindi'}
DETAILS={'id':77,'original_language':'kn','genres':[{'id':18,'name':'Drama'}]}
class Fake:
    def __init__(self, pages, limit=10):self.pages=pages;self.limit=limit;self.calls=0;self.paths=[]
    def get(self,path,params=None):
        if self.calls>=self.limit:raise tmdb.BudgetReached()
        self.calls+=1;self.paths.append(path)
        result=self.pages[path]
        if isinstance(result,Exception):raise result
        return copy.deepcopy(result)
class MetadataTests(unittest.TestCase):
    def cached_cli(self, source, cache):
        with mock.patch.dict(os.environ, {'TMDB_READ_ACCESS_TOKEN':'test-token',
                 'TMDB_REFRESH_IDS':'invalid repair value', 'GITHUB_STEP_SUMMARY':''}), \
             mock.patch.object(tmdb, 'Client', side_effect=AssertionError('Cached mode constructed an API client')), \
             mock.patch.object(tmdb, 'repair_external_ids', side_effect=AssertionError('Cached mode repaired IDs')), \
             mock.patch.object(tmdb, 'urlopen', side_effect=AssertionError('Cached mode accessed the network')), \
             mock.patch.object(tmdb.time, 'time', return_value=40*tmdb.DAY), redirect_stdout(io.StringIO()):
            self.assertEqual(tmdb.main(['--catalog',str(source),'--cache',str(cache),'--cached-only']),0)
        return json.loads(source.read_text())

    def test_cached_only_cli_ignores_credentials_and_repairs_but_preserves_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'cache.sqlite'; source=Path(folder)/'catalog.json'
            raw={**copy.deepcopy(TITLE),'tmdbId':77}
            db=tmdb.open_cache(cache)
            tmdb.enrich({'titles':[copy.deepcopy(raw)]},db,Fake({'/movie/77':DETAILS}),1000)
            before=db.execute('SELECT * FROM metadata').fetchall(); db.close()
            source.write_text(json.dumps({'titles':[raw]}))
            catalog=self.cached_cli(source,cache); title=catalog['titles'][0]
            self.assertEqual(title['originalLanguage'],'Kannada')
            self.assertEqual(title['originalLanguageSource'],'TMDB')
            self.assertEqual(title['providerOriginalLanguage'],'Hindi')
            self.assertEqual(title['providerOriginalLanguageSource'],'Streaming Availability API')
            self.assertEqual(title['offers'],raw['offers'])
            self.assertEqual(title['tmdb']['genres'],['Drama'])
            self.assertEqual(title['tmdb']['checkedAt'],1000)
            self.assertEqual(title['tmdbMatchStatus'],'matched')
            self.assertEqual(catalog['tmdbEnrichment']['status'],'cached')
            self.assertEqual(catalog['tmdbEnrichment']['requestsThisRun'],0)
            db=tmdb.open_cache(cache)
            self.assertEqual(db.execute('SELECT * FROM metadata').fetchall(),before); db.close()

    def test_cached_only_cli_keeps_original_source_when_cached_original_is_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'cache.sqlite'; source=Path(folder)/'catalog.json'
            official='https://www.hotstar.com/in/shows/test-film/123'
            raw={**copy.deepcopy(TITLE),'tmdbId':77,'originalLanguage':'Tamil','originalLanguageSource':official}
            db=tmdb.open_cache(cache)
            tmdb.enrich({'titles':[copy.deepcopy(raw)]},db,Fake({'/movie/77':{**DETAILS,'original_language':None}}),1000)
            db.close(); source.write_text(json.dumps({'titles':[raw]}))
            title=self.cached_cli(source,cache)['titles'][0]
            self.assertEqual(title['originalLanguage'],'Tamil')
            self.assertEqual(title['originalLanguageSource'],official)
            self.assertEqual(title['providerOriginalLanguageSource'],official)
            self.assertEqual(title['tmdb']['genres'],['Drama'])
            self.assertIsNone(title['tmdb']['originalLanguage'])
            self.assertEqual(title['tmdb']['checkedAt'],1000)

    def test_cached_only_cli_rejects_changed_identity_and_does_not_guess_audio_original(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'cache.sqlite'; source=Path(folder)/'catalog.json'
            old={**copy.deepcopy(TITLE),'tmdbId':77}; db=tmdb.open_cache(cache)
            tmdb.enrich({'titles':[old]},db,Fake({'/movie/77':DETAILS}),1000)
            db.close(); changed={**old,'tmdbId':78}
            unknown={**copy.deepcopy(TITLE),'id':'motn:8','originalLanguage':None}
            source.write_text(json.dumps({'titles':[changed,unknown]}))
            catalog=self.cached_cli(source,cache); title,missing=catalog['titles']
            self.assertNotIn('tmdb',title)
            self.assertEqual(title['originalLanguage'],'Hindi')
            self.assertEqual(title['originalLanguageSource'],'Streaming Availability API')
            self.assertEqual(title['tmdbMatchStatus'],'pending')
            self.assertIsNone(missing['originalLanguage'])
            self.assertEqual(missing['tmdbMatchStatus'],'pending')
            self.assertEqual(missing['offers'],unknown['offers'])
            self.assertEqual(catalog['tmdbEnrichment']['matched'],0)

    def test_official_original_language_keeps_its_source_across_repeated_enrichment(self):
        with tempfile.TemporaryDirectory() as folder:
            db=tmdb.open_cache(Path(folder)/'cache.sqlite')
            source='https://www.hotstar.com/in/shows/a-title/123'
            title={**TITLE,'tmdbId':77,'originalLanguage':'Tamil','originalLanguageSource':source,'providerOriginalLanguage':None}
            catalog={'titles':[title]}
            tmdb.enrich(catalog,db,Fake({'/movie/77':{**DETAILS,'original_language':None}}),1000)
            tmdb.enrich(catalog,db,None,1001)
            self.assertEqual(title['originalLanguage'],'Tamil')
            self.assertEqual(title['originalLanguageSource'],source)
            self.assertEqual(title['providerOriginalLanguageSource'],source)
            db.close()
    def test_external_id_type_and_original_audio_separation(self):
        title={**TITLE,'tmdbId':'movie/77'}
        client=Fake({'/movie/77':DETAILS})
        result=tmdb.lookup(title,client)
        self.assertEqual(result['originalLanguage'],'Kannada')
        self.assertEqual(result['genres'],['Drama'])
        self.assertEqual(title['offers'][0]['audio'],['Hindi'])
        self.assertEqual(client.paths,['/movie/77'])
    def test_exact_search_year_and_ambiguity(self):
        row={'id':77,'title':'Test Film','release_date':'2025-01-01'}
        client=Fake({'/search/movie':{'results':[row,{**row,'id':78}],'total_pages':1}})
        self.assertIsNone(tmdb.lookup(TITLE,client))
        for page in [{'results':[{**row,'release_date':'2024-01-01'}]}, {'results':[row],'total_pages':2}]:
            self.assertIsNone(tmdb.resolve(TITLE,Fake({'/search/movie':page})))
        client=Fake({'/search/movie':{'results':[row]},'/movie/77':DETAILS})
        self.assertEqual(tmdb.lookup(TITLE,client)['matchMethod'],'exact-title-year')
    def test_imdb_uses_correct_media_type(self):
        client=Fake({'/find/tt123':{'movie_results':[],'tv_results':[{'id':77}]},'/tv/77':DETAILS})
        self.assertEqual(tmdb.lookup({**TITLE,'type':'Series','imdbId':'tt123'},client)['mediaType'],'tv')
    def test_resume_cache_and_no_false_negative_on_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            db=tmdb.open_cache(Path(folder)/'cache.sqlite')
            catalog={'titles':[{**TITLE,'tmdbId':'movie/77'},{**TITLE,'id':'motn:8','tmdbId':'movie/78'}]}
            client=Fake({'/movie/77':DETAILS},limit=1)
            report=tmdb.enrich(catalog,db,client,1000)
            self.assertEqual(report['status'],'partial');self.assertEqual(report['matched'],1)
            self.assertEqual(db.execute('SELECT count(*) FROM metadata').fetchone()[0],1)
            client=Fake({'/movie/78':{**DETAILS,'id':78}})
            self.assertEqual(tmdb.enrich(catalog,db,client,1001)['matched'],2)
            self.assertEqual(client.paths,['/movie/78'])
            self.assertEqual(tmdb.enrich(catalog,db,None,1002)['matched'],2)
            db.close()
    def test_failures_preserve_availability_and_unknowns(self):
        with tempfile.TemporaryDirectory() as folder:
            db=tmdb.open_cache(Path(folder)/'cache.sqlite')
            title=copy.deepcopy(TITLE);catalog={'titles':[title]}
            result=tmdb.enrich(catalog,db,Fake({'/search/movie':tmdb.TMDBError('TMDB HTTP 401')}),1000)
            self.assertEqual(result['status'],'error');self.assertNotIn('tmdb',title)
            self.assertEqual(title['offers'],TITLE['offers'])
            self.assertEqual(db.execute('SELECT count(*) FROM metadata').fetchone()[0],0)
            db.close()
    def test_unknown_language_not_derived_from_audio(self):
        result=tmdb.lookup({**TITLE,'tmdbId':77},Fake({'/movie/77':{**DETAILS,'original_language':None}}))
        self.assertIsNone(result['originalLanguage'])

    def test_changed_external_ids_get_priority_and_invalidate_cached_miss(self):
        with tempfile.TemporaryDirectory() as folder:
            db=tmdb.open_cache(Path(folder)/'cache.sqlite')
            legacy=copy.deepcopy(TITLE)
            tmdb.enrich({'titles':[legacy]},db,Fake({'/search/movie':{'results':[]}}),1000)
            repaired={**TITLE,'tmdbId':'movie/77'}
            catalog={'titles':[{**TITLE,'id':'motn:8','tmdbId':'movie/78'},repaired]}
            client=Fake({'/movie/77':DETAILS},limit=1)
            result=tmdb.enrich(catalog,db,client,1001,priority_ids=['motn:7'])
            self.assertEqual(repaired['originalLanguage'],'Kannada')
            self.assertEqual(repaired['tmdbMatchStatus'],'matched')
            self.assertEqual(result['matched'],1)
            self.assertEqual(catalog['titles'][0]['tmdbMatchStatus'],'pending')
            db.close()

    def test_missing_tmdb_original_preserves_provider_value(self):
        with tempfile.TemporaryDirectory() as folder:
            db=tmdb.open_cache(Path(folder)/'cache.sqlite')
            title={**TITLE,'tmdbId':77}
            tmdb.enrich({'titles':[title]},db,Fake({'/movie/77':{**DETAILS,'original_language':None}}),1000)
            self.assertEqual(title['originalLanguage'],'Hindi')
            self.assertEqual(title['originalLanguageSource'],'Streaming Availability API')
            self.assertEqual(title['tmdb']['genres'],['Drama'])
            db.close()

    def test_changed_identity_clears_old_match_and_restores_provider_original(self):
        with tempfile.TemporaryDirectory() as folder:
            db=tmdb.open_cache(Path(folder)/'cache.sqlite')
            title={**TITLE,'tmdbId':77};catalog={'titles':[title]}
            tmdb.enrich(catalog,db,Fake({'/movie/77':DETAILS}),1000)
            title['tmdbId']=78
            tmdb.enrich(catalog,db,None,1001)
            self.assertNotIn('tmdb',title)
            self.assertEqual(title['originalLanguage'],'Hindi')
            self.assertEqual(title['originalLanguageSource'],'Streaming Availability API')
            self.assertEqual(title['tmdbMatchStatus'],'pending')
            db.close()

    def test_recent_addition_precedes_background_external_id(self):
        with tempfile.TemporaryDirectory() as folder:
            db=tmdb.open_cache(Path(folder)/'cache.sqlite')
            weekly={**TITLE,'id':'motn:9','weekly':True,'weeklyUpdatedAt':1000}
            background={**TITLE,'id':'motn:1','tmdbId':78}
            client=Fake({'/search/movie':{'results':[{'id':77,'title':'Test Film','release_date':'2025-01-01'}]},'/movie/77':DETAILS},limit=2)
            tmdb.enrich({'titles':[background,weekly]},db,client,1001)
            self.assertEqual(weekly['tmdbMatchStatus'],'matched')
            self.assertEqual(background['tmdbMatchStatus'],'pending')
            self.assertEqual(client.calls,2)
            db.close()
