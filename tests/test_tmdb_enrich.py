import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
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
