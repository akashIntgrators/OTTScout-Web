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
            (root/'data').mkdir()
            titles = [{'id':'motn:42','title':'A & <Movie>','type':'Movie','year':2026,'weekly':True,'weeklyUpdatedAt':1000000,'weeklyPlatforms':['Netflix'],'offers':[{'platform':'Netflix','type':'subscription','audio':['Hindi'],'subtitles':['English'],'link':'javascript:alert(1)'}]}, {'id':'motn:43','title':'Older title','type':'Series','weekly':True,'weeklyUpdatedAt':1,'weeklyPlatforms':['Netflix'],'offers':[{'platform':'Netflix','audio':['English'],'subtitles':[]}]}]
            (root/'data/catalog.json').write_text(json.dumps({'titles':titles,'updatedAt':'2026-10-25'}))
            (root/'.state').mkdir(); (root/'.state/secret').write_text('private')
            site = module.build(root, now=1000001)
            movie = (site/'titles/42/index.html').read_text()
            self.assertIn('A &amp; &lt;Movie&gt;', movie)
            self.assertNotIn('javascript:', movie)
            self.assertIn('Audio: Hindi', movie)
            self.assertIn('/titles/42/', (site/'languages/hindi/index.html').read_text())
            self.assertNotIn('/titles/43/', (site/'languages/hindi/index.html').read_text())
            self.assertNotIn('Older title', (site/'this-week/index.html').read_text())
            self.assertFalse((site/'.state').exists())
            xml = ET.parse(site/'sitemap.xml')
            for node in xml.findall('.//{*}loc'):
                path = node.text[len(module.BASE):].strip('/')
                self.assertTrue((site/path/'index.html').exists())
            self.assertIn('https://ottscout.techiwithhelmet.com/sitemap.xml', (site/'robots.txt').read_text())
