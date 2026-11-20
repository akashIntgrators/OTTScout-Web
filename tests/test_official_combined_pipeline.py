"""Exercise automatic evidence through real cached export and publication code."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import build_site, catalog_sync, fetch_public_catalogue
from scripts.official_listings import apply_official_listings

NOW = 1795201200  #20 November2026,19:00UTC; fixed data-only test clock.
DAY = 86400
AUTO_ID = 'motn:official-sonyliv-1590000999'
AUTO_URL = 'https://www.sonyliv.com/movies/automatic-test-film-1590000999'


def listing(platform='SonyLIV', ident='1590000999', title='Automatic fixture', expiry=NOW+DAY):
    service = 'sonyliv' if platform == 'SonyLIV' else 'netflix'
    url = AUTO_URL if platform == 'SonyLIV' else 'https://www.netflix.com/in/title/' + ident
    return {'id':'motn:official-'+service+'-'+ident,'platform':platform,'platformTitleId':ident,
            'title':title,'type':'Movie','year':2026,'sourceURL':url,'releaseDate':'2026-11-20',
            'releaseEvidenceURL':url,'verifiedAt':NOW-60,'expiresAt':expiry,
            'access':{'type':'subscription','evidenceURL':url},
            'audio':['Tamil'] if platform == 'SonyLIV' else ['English'],'audioEvidenceURL':url,
            'originalLanguage':None,'originalLanguageEvidenceURL':None}


def provider_show(services=('sonyliv',)):
    return {'id':'777','title':'Provider-owned fixture','showType':'movie','releaseYear':2026,
            'streamingOptions':{'in':[{'service':{'id':service},'type':'subscription',
                'audios':[{'language':'tam'}],'subtitles':[],
                'link':AUTO_URL if service=='sonyliv' else 'https://www.netflix.com/title/333',
                'availableSince':NOW-100} for service in services]}}


def bare_catalog():
    return {'schemaVersion':1,'mode':'live','updatedAt':'2026-11-13T07:02:34+00:00',
            'coverage':['SonyLIV','Netflix'],'missingPlatforms':[],
            'titles':[{'id':'motn:777','title':'Provider-owned fixture','type':'Movie','year':2026,
                       'genres':[],'lastCheckedAt':NOW-100,
                       'offers':[{'platform':'SonyLIV','type':'subscription','audio':['Tamil'],'subtitles':[],
                                  'link':AUTO_URL,'availableSince':NOW-100}],
                       'weeklyEvents':[],'weeklyPlatforms':[],'weekly':False}]}


class CombinedOfficialPipelineTests(unittest.TestCase):
    def seed(self, root, curated, automatic):
        (root/'data').mkdir(exist_ok=True)
        (root/'data/official-listings.json').write_text(json.dumps(curated))
        (root/'data/official-discovered.json').write_text(json.dumps(automatic))

    def publication_guard(self, root, now):
        workflow=(Path(__file__).parents[1]/'.github/workflows/publish-site.yml').read_text()
        start=workflow.index('          import hashlib, json, os, shutil, time')
        end=workflow.index('          PYCODE',start)
        guard='\n'.join(line[10:] for line in workflow[start:end].splitlines())
        previous=Path.cwd()
        try:
            os.chdir(root)
            with patch.dict(os.environ,{'RUNNER_TEMP':str(root/'runner')}),patch.object(time,'time',return_value=now), \
                 patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Publication must not perform network I/O')):
                exec(guard,{})
        finally:os.chdir(previous)

    def test_combined_cached_export_preserves_provider_id_database_rows_and_source_watermark(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            curated=listing('Netflix','8300000999','Reviewed fixture',NOW+7*DAY)
            automatic=listing()
            self.seed(root,[curated],[automatic])
            db=catalog_sync.open_db(root/'catalog.sqlite');self.addCleanup(db.close)
            mapping={'SonyLIV':'sonyliv','Netflix':'netflix'}
            catalog_sync.set_meta(db,'last_success',NOW-7*DAY)
            catalog_sync.set_meta(db,'coverage',{'mapping':mapping})
            catalog_sync.save_show(db,provider_show(),mapping,NOW);db.commit()
            target=root/'data/catalog.json'
            with patch.object(catalog_sync,'OFFICIAL_LISTINGS_PATH',root/'data/official-listings.json'), \
                 patch.object(catalog_sync,'urlopen',side_effect=AssertionError('Cached export must not call provider')):
                catalog_sync.export_catalog(db,target,NOW)
                first=json.loads(target.read_text())
                self.assertEqual({t['id'] for t in first['titles']},{'motn:777',curated['id']})
                self.assertNotIn(AUTO_ID,{t['id'] for t in first['titles']})
                self.assertEqual(first['officialListingAliases']['sonyliv:1590000999'],'motn:777')
                self.assertEqual(first['updatedAt'],catalog_sync.stamp(NOW-7*DAY))
                self.assertEqual([row[0] for row in db.execute('SELECT id FROM titles')],['motn:777'])
                # Loss of a provider offer is not an explicit removal signal.
                catalog_sync.save_show(db,provider_show(('netflix',)),mapping,NOW+1);db.commit()
                catalog_sync.export_catalog(db,target,NOW+1)
                mixed=json.loads(target.read_text());same=next(t for t in mixed['titles'] if t['id']=='motn:777')
                self.assertEqual({o['platform'] for o in same['offers']},{'Netflix','SonyLIV'})
                self.assertEqual(next(o for o in same['offers'] if o['platform']=='SonyLIV')['availabilitySourceType'],'official-listing')
                catalog_sync.export_catalog(db,target,NOW+2*DAY)
                expired=json.loads(target.read_text());same=next(t for t in expired['titles'] if t['id']=='motn:777')
                self.assertEqual([o['platform'] for o in same['offers']],['Netflix'])
                self.assertEqual(expired['officialListingAliases']['sonyliv:1590000999'],'motn:777')
                self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],0)

    def test_download_build_actual_publication_guard_and_expiry_use_combined_registry_without_apis(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runner').mkdir()
            reviewed=listing('Netflix','8300000999','Reviewed fixture',NOW+7*DAY)
            fresh_only=listing('Netflix','8310000999','Automatic-only fixture')
            self.seed(root,[reviewed],[listing(),fresh_only])
            for name in ('index.html','app.js','style.css','CNAME'):(root/name).write_text('')
            baseline=bare_catalog();health={'generatedAt':'2026-11-19T07:00:00Z','status':'warning'}
            public={'/data/catalog.json':baseline,'/data/official-discovered.json':[listing(),fresh_only],'/data/catalogue-health.json':health}
            def get_public(path,*args,**kwargs):return deepcopy(public[path])
            with patch.object(fetch_public_catalogue,'get_json',side_effect=get_public) as fetch:
                fetch_public_catalogue.main(['--root',str(root)])
            self.assertEqual([call.args[0] for call in fetch.call_args_list],list(public))
            self.assertEqual(json.loads((root/'data/catalogue-health.json').read_text()),health,'Website-only reuse must not refresh health timestamps')
            original=(root/'data/catalog.json').read_bytes()
            (root/'runner/ottscout-published-catalogue.sha256').write_text(hashlib.sha256(original).hexdigest())
            site=build_site.build(root,NOW)
            staged=site/'data/catalog.json';tampered=json.loads(staged.read_text())
            next(t for t in tampered['titles'] if t['id']=='motn:777')['title']='Unexpected general-builder mutation'
            staged.write_text(json.dumps(tampered))
            self.publication_guard(root,NOW)
            published=json.loads(staged.read_text());ids={t['id'] for t in published['titles']}
            self.assertEqual(ids,{'motn:777',reviewed['id'],fresh_only['id']})
            self.assertEqual(next(t for t in published['titles'] if t['id']=='motn:777')['title'],'Provider-owned fixture')
            self.assertEqual(published['updatedAt'],baseline['updatedAt'])
            self.assertEqual((root/'data/catalog.json').read_bytes(),original)
            self.assertIn(fresh_only['id'],{t['id'] for t in json.loads((site/'data/widget.json').read_text())['titles']})
            # A later website-only publication must expire automatic rows in
            # the catalogue, widget projection and generated title pages.
            (root/'data/catalog.json').write_text(json.dumps(published));original=(root/'data/catalog.json').read_bytes()
            (root/'runner/ottscout-published-catalogue.sha256').write_text(hashlib.sha256(original).hexdigest())
            site=build_site.build(root,NOW+2*DAY)
            self.publication_guard(root,NOW+2*DAY)
            final=json.loads((site/'data/catalog.json').read_text())
            self.assertEqual({t['id'] for t in final['titles']},{'motn:777',reviewed['id']})
            self.assertEqual(next(t for t in final['titles'] if t['id']=='motn:777')['offers'],baseline['titles'][0]['offers'])
            self.assertNotIn(fresh_only['id'],{t['id'] for t in json.loads((site/'data/widget.json').read_text())['titles']})
            self.assertFalse((site/'titles/official-netflix-8310000999/index.html').exists())

    def test_mismatched_public_companion_does_not_overwrite_existing_local_snapshot(self):
        active,_=apply_official_listings(bare_catalog(),[listing()],NOW)
        # No existing binding: create a true automatic-only active title.
        automatic=listing('Netflix','8310000999','Automatic-only fixture')
        active,_=apply_official_listings(active,[automatic],NOW)
        for companion in (None,[],[{**automatic,'verifiedAt':automatic['verifiedAt']-1}]):
            with self.subTest(companion=companion),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);self.seed(root,[],[])
                local=root/'data/catalog.json';local.write_text('previous validated snapshot bytes')
                values={'/data/catalog.json':active,'/data/official-discovered.json':companion,'/data/catalogue-health.json':{}}
                with patch.object(fetch_public_catalogue,'get_json',side_effect=lambda path,*a,**kw:deepcopy(values[path])):
                    with self.assertRaises(ValueError):fetch_public_catalogue.main(['--root',str(root)])
                self.assertEqual(local.read_text(),'previous validated snapshot bytes')


if __name__=='__main__':unittest.main()
