import copy
import json
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest
from scripts.site_features import apply_reports, valid_reports, netflix_id, json_script, schema_graph, DAY
from scripts.build_site import build

NOW=1793275200
REPORT={'platform':'Netflix','providerTitleId':'123','title':'A title','type':'Movie','year':2025,'languages':['Hindi'],'sourceURL':'https://www.netflix.com/in/title/123','checkedAt':NOW-100,'indiaPlaybackVerified':False}

class HTMLAudit(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=[];self.main=0;self.references=[];self.unnamed_generic=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        if tag=='main':self.main+=1
        for key in ('aria-describedby','aria-labelledby','aria-controls'):
            self.references.extend((a.get(key) or '').split())
        if tag in ('div','span') and 'aria-label' in a and not a.get('role'):self.unnamed_generic.append(a)

class SiteFeatureTests(unittest.TestCase):
    def test_exact_provider_source_required(self):
        self.assertEqual(netflix_id('https://www.netflix.com/watch/123?x=1'),'123')
        for bad in ['http://netflix.com/title/123','https://netflix.com.evil.test/title/123','https://evil@netflix.com/title/123','https://netflix.com:444/title/123','https://netflix.com/title/123/trailer']:
            self.assertIsNone(netflix_id(bad))
        for bad in [{**REPORT,'sourceURL':'https://www.netflix.com/in/title/124'}, {**REPORT,'languages':[]}, {**REPORT,'indiaPlaybackVerified':True}, {**REPORT,'platform':'Prime Video'}, {**REPORT,'year':'<img>'}]:
            with self.assertRaises(ValueError):valid_reports([bad],NOW)
        with self.assertRaises(ValueError):valid_reports([REPORT,REPORT],NOW)

    def test_expired_or_future_reports_not_promoted(self):
        self.assertEqual(valid_reports([{**REPORT,'checkedAt':NOW-31*DAY}],NOW),[])
        self.assertEqual(valid_reports([{**REPORT,'checkedAt':NOW+100}],NOW),[])
        self.assertEqual(valid_reports([REPORT],NOW)[0]['languages'],['Hindi'])

    def test_no_inference_or_cross_platform_claim(self):
        offers=[{'platform':'Netflix','link':'https://netflix.com/title/123','audio':['English']},
                {'platform':'Prime Video','link':'https://netflix.com/title/123','audio':['Hindi']},
                {'platform':'Netflix','link':'https://netflix.com/title/124','audio':['Hindi']}]
        c={'titles':[{'type':'Movie','offers':copy.deepcopy(offers)},{'type':'Series','offers':copy.deepcopy(offers)}]}
        apply_reports(c,[REPORT])
        self.assertEqual(c['titles'][0]['offers'][0]['audioDescription']['languages'],['Hindi'])
        self.assertNotIn('audioDescription',c['titles'][0]['offers'][1])
        self.assertNotIn('audioDescription',c['titles'][0]['offers'][2])
        self.assertTrue(all('audioDescription' not in o for o in c['titles'][1]['offers']))
        apply_reports(c,[])
        self.assertTrue(all('audioDescription' not in o for t in c['titles'] for o in t['offers']))

    def test_schema_is_truthful_and_script_safe(self):
        title='Film </script><img src=x onerror=alert(1)>'
        graph=schema_graph('/titles/123/',title,'Watch in India',{'title':title,'type':'Movie','originalLanguage':'Hindi','tmdb':{'genres':['Drama'],'url':'https://www.themoviedb.org/movie/123'}})
        encoded=json_script(graph)
        self.assertEqual(encoded.count('</script>'),1)
        self.assertNotIn('<img',encoded)
        payload=json.loads(encoded.split('>',1)[1].rsplit('</script>',1)[0])
        self.assertEqual(payload['@graph'][-1]['name'],title)
        self.assertNotIn('aggregateRating',payload['@graph'][-1])
        self.assertNotIn('accessibilityFeature',payload['@graph'][-1])
        self.assertEqual(payload['@graph'][2]['itemListElement'][1]['item'],'https://ottscout.techiwithhelmet.com/titles/123/')

    def test_dashboard_semantics_and_reference_targets(self):
        text=(Path(__file__).parents[1]/'index.html').read_text()
        audit=HTMLAudit();audit.feed(text)
        self.assertEqual(audit.main,1)
        self.assertEqual(len(audit.ids),len(set(audit.ids)))
        self.assertTrue(all(ref in audit.ids for ref in audit.references))
        self.assertFalse(audit.unnamed_generic)
        self.assertIn('id="results-status"',text)
        self.assertIn('href="/accessibility/"',text)
        self.assertIn('id="enable-shortcuts"',text)
        self.assertIn('id="audio-description-only"',text)

    def test_generated_description_directory_and_indexable_title(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for n in ('index.html','app.js','style.css','CNAME'):(root/n).write_text('<head><!-- SEO:STRUCTURED_DATA --></head>')
            (root/'data').mkdir()
            (root/'data/audio-description.json').write_text(json.dumps({'schemaVersion':1,'reports':[REPORT]}))
            title={'id':'motn:99','title':'A title','type':'Movie','year':2025,'offers':[{'platform':'Netflix','link':'https://www.netflix.com/title/123','audio':['English'],'subtitles':[],'type':'subscription'}]}
            (root/'data/catalog.json').write_text(json.dumps({'titles':[title],'updatedAt':'2026-10-29'}))
            target=build(root,NOW)
            detail=(target/'titles/99/index.html').read_text()
            self.assertIn('A title (2025) — where to watch',detail)
            self.assertIn('Audio description reported: Hindi',detail)
            self.assertIn('India playback unverified',detail)
            self.assertIn('application/ld+json',detail)
            self.assertIn('Skip to main content',detail)
            guide=(target/'audio-description/index.html').read_text()
            self.assertIn('A title',guide)
            self.assertIn('India playback is unverified',guide)
            self.assertIn('/accessibility/',(target/'sitemap.xml').read_text())
            data=json.loads((target/'data/catalog.json').read_text())
            self.assertEqual(data['titles'][0]['offers'][0]['audioDescription']['languages'],['Hindi'])
