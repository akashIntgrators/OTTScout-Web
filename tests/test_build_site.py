import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('build_site', Path(__file__).resolve().parents[1] / 'scripts/build_site.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DiscoveryBuildTests(unittest.TestCase):
    def test_public_pages_links_language_and_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('index.html','app.js','style.css','CNAME'):
                (root/name).write_text('')
            (root/'favicon.ico').write_bytes(b'icon fixture')
            seller_record = (Path(__file__).parents[1] / 'app-ads.txt').read_text()
            self.assertEqual(seller_record, 'google.com, pub-7509184674593498, DIRECT, f08c47fec0942fa0\n')
            (root/'app-ads.txt').write_text(seller_record)
            (root/'theme.js').write_text('// local appearance preference fixture')
            (root/'data').mkdir()
            titles = [{'id':'motn:42','title':'A & <Movie>','type':'Movie','year':2026,'originalLanguage':'Kannada','weekly':True,'weeklyUpdatedAt':1000000,'weeklyPlatforms':['Netflix'],'offers':[{'platform':'Netflix','type':'subscription','audio':['Hindi'],'subtitles':['English'],'link':'javascript:alert(1)'}]}, {'id':'motn:43','title':'Older title','type':'Series','weekly':True,'weeklyUpdatedAt':1,'weeklyPlatforms':['Netflix'],'offers':[{'platform':'Netflix','audio':['English'],'subtitles':[]}]}]
            titles.extend([
                {'id':'motn:44','title':'Confirmed audio','type':'Movie','offers':[
                    {'platform':'Netflix','type':'subscription','audio':['Hindi'],'link':'https://www.netflix.com/title/44'}]},
                {'id':'motn:45','title':'Other audio','type':'Series','offers':[
                    {'platform':'Netflix','type':'subscription','audio':['French'],'link':'https://www.netflix.com/title/45'}]},
            ])
            (root/'data/catalog.json').write_text(json.dumps({'titles':titles,'updatedAt':'2026-10-25'}))
            (root/'.state').mkdir(); (root/'.state/secret').write_text('private')
            site = module.build(root, now=1000001)
            self.assertEqual((site/'favicon.ico').read_bytes(),b'icon fixture')
            self.assertEqual((site/'app-ads.txt').read_text(),seller_record)
            self.assertEqual((site/'theme.js').read_text(),'// local appearance preference fixture')
            movie = (site/'titles/42/index.html').read_text()
            self.assertIn('A &amp; &lt;Movie&gt;', movie)
            self.assertNotIn('javascript:', movie)
            self.assertIn('Audio: Hindi', movie)
            self.assertIn('Original language: Kannada', movie)
            self.assertIn('/theme.js?v=rail22',movie)
            self.assertIn('Report incorrect details on GitHub', movie)
            self.assertIn('Public issue; review before submitting', movie)
            self.assertIn('/titles/42/', (site/'languages/hindi/index.html').read_text())
            self.assertNotIn('/titles/43/', (site/'languages/hindi/index.html').read_text())
            self.assertNotIn('Older title', (site/'this-week/index.html').read_text())
            self.assertFalse((site/'.state').exists())
            xml = ET.parse(site/'sitemap.xml')
            urls = [node.text for node in xml.findall('.//{*}loc')]
            self.assertNotIn(module.BASE + '/titles/42/', urls)
            self.assertIn('content="noindex,follow"', movie)
            self.assertIn(module.BASE + '/titles/44/', urls)
            self.assertNotIn('name="robots"', (site/'titles/44/index.html').read_text())
            self.assertNotIn(module.BASE + '/titles/45/', urls)
            self.assertIn('no matching viewing offers', (site/'titles/45/index.html').read_text())
            guide_index = (site/'guides/index.html').read_text()
            for path, title, _, _ in module.EDITORIAL_GUIDES:
                self.assertIn(module.BASE + path, urls)
                self.assertIn(f'href="{path}"', guide_index)
                self.assertIn(title, (site/path.strip('/')/'index.html').read_text())
            for node in xml.findall('.//{*}loc'):
                path = node.text[len(module.BASE):].strip('/')
                self.assertTrue((site/path/'index.html').exists())
            self.assertIn('https://ottscout.techiwithhelmet.com/sitemap.xml', (site/'robots.txt').read_text())

    def test_account_bundle_and_public_config_are_packaged(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('index.html','app.js','style.css','CNAME'):(root/name).write_text('')
            (root/'web').mkdir(); (root/'web/account.js').write_text('// fixture entry')
            (root/'web/recommendation-links.js').write_text('// public recommendation receiver fixture')
            (root/'web/not-public.txt').write_text('do not package the entire web source directory')
            (root/'scripts').mkdir()
            (root/'scripts/build-auth.mjs').write_text("import {writeFileSync} from 'node:fs';writeFileSync(process.argv[2], '// bundled account fixture');")
            (root/'data').mkdir(); (root/'data/catalog.json').write_text(json.dumps({'titles':[],'updatedAt':'2026-11-03'}))
            config={'apiKey':'public-key','authDomain':'project.firebaseapp.com','projectId':'project','appId':'public-app-id'}
            (root/'firebase-config.json').write_text(json.dumps(config))
            site=module.build(root,now=1000001)
            self.assertEqual((site/'account.js').read_text(),'// bundled account fixture')
            self.assertEqual(json.loads((site/'firebase-config.json').read_text()),config)
            self.assertEqual((site/'web/recommendation-links.js').read_text(),'// public recommendation receiver fixture')
            self.assertFalse((site/'web/account.js').exists())
            self.assertFalse((site/'web/not-public.txt').exists())
            config['private_key']='never publish a service-account key'
            (root/'firebase-config.json').write_text(json.dumps(config))
            with self.assertRaises(ValueError):module.build(root,now=1000001)

    def test_weekly_offer_dates_and_older_movies(self):
        now=1793275200
        title={'type':'Movie','year':2006,'weeklyPlatforms':['Netflix','Prime Video'],
               'weeklyUpdatedAt':now-10,'weeklyEvents':[{'platform':'Netflix','addedAt':now-10},{'platform':'Prime Video','addedAt':now-8*86400}]}
        self.assertTrue(module.older_movie(title,now))
        self.assertFalse(module.older_movie({**title,'type':'Series'},now))
        self.assertIsNone(module.weekly_offer_date(title,{'platform':'Netflix','availableSince':now-8*86400},now))
        self.assertEqual(module.weekly_offer_date(title,{'platform':'Netflix','availableSince':now-100},now),now-100)
        self.assertIsNone(module.weekly_offer_date(title,{'platform':'Prime Video','availableSince':now-100},now))
        self.assertIsNone(module.weekly_offer_date(title,{'platform':'Netflix','availableSince':now+100},now))
        self.assertEqual(module.weekly_offer_date(title,{'platform':'Netflix'},now),now-10)
        self.assertEqual(module.original_label('ko'),'Korean')

    def test_weekly_page_excludes_old_offer_and_explains_verification(self):
        now=1793275200
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('index.html','app.js','style.css','CNAME'):(root/name).write_text('')
            (root/'data').mkdir()
            title={'id':'motn:99','title':'Older movie','type':'Movie','year':2006,'weekly':True,'weeklyUpdatedAt':now-10,'weeklyPlatforms':['Netflix','Prime Video'],
                   'lastCheckedAt':now-100,'tmdbMatchStatus':'unmatched','offers':[
                   {'platform':'Netflix','type':'subscription','audio':['Hindi'],'subtitles':[],'availableSince':now-9*86400},
                   {'platform':'Prime Video','type':'free','audio':['Hindi'],'subtitles':[],'availableSince':now-10}]}
            (root/'data/catalog.json').write_text(json.dumps({'updatedAt':'2026-10-29','titles':[title]}))
            site=module.build(root,now)
            weekly=(site/'this-week/index.html').read_text()
            self.assertIn('Older movies added',weekly)
            self.assertIn('Prime Video',weekly)
            self.assertNotIn('Netflix',weekly)
            self.assertIn('Premiere unverified',weekly)
            detail=(site/'titles/99/index.html').read_text()
            self.assertIn('No confident TMDB match',detail)
            self.assertIn('Availability checked',detail)
            self.assertIn('Netflix',detail) # Discover/details preserve older offers.

class UnknownAudioPages(unittest.TestCase):
    def test_unknown_audio_has_title_page_and_weekly_but_not_language_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('index.html','app.js','style.css','CNAME'):(root/name).write_text('')
            (root/'data').mkdir()
            title={'id':'motn:unknown','title':'Unknown Audio Film','type':'Movie','weekly':True,'weeklyPlatforms':['Netflix'],'weeklyUpdatedAt':1000000,'offers':[{'platform':'Netflix','type':'subscription','audio':[],'subtitles':[],'link':'https://www.netflix.com/title/123'}]}
            (root/'data/catalog.json').write_text(json.dumps({'titles':[title],'updatedAt':'2026-10-30'}))
            site=module.build(root,now=1000001)
            self.assertIn('Unknown Audio Film',(site/'this-week/index.html').read_text())
            self.assertIn('Audio languages unverified',(site/'this-week/index.html').read_text())
            self.assertNotIn('Unknown Audio Film',(site/'languages/tamil/index.html').read_text())
            self.assertIn('Netflix',(site/'titles/unknown/index.html').read_text())
