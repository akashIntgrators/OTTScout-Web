from html import unescape
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit, parse_qs

from scripts.corrections_page import correction_link, render_corrections, INBOX
from scripts.build_site import build


class CorrectionsPageTests(unittest.TestCase):
    def test_browser_links_preserve_context_and_require_structured_review(self):
        subprocess.run(['node', 'tests/correction_links.cjs'], cwd=Path(__file__).parents[1], check=True, capture_output=True)

    def test_static_links_prefill_supported_form_fields_without_unsafe_destinations(self):
        title = {'title': 'A & <movie> తెలుగు', 'type': 'Movie', 'offers': [
            {'platform': 'Netflix', 'link': 'https://www.netflix.com/in/title/123'}]}
        url = urlsplit(correction_link(title, notes='A source & context'))
        self.assertEqual(url.netloc, 'github.com')
        fields = parse_qs(url.query)
        self.assertEqual(fields['template'], ['catalogue-correction.yml'])
        self.assertEqual(fields['title_name'], [title['title']])
        self.assertEqual(fields['official_url'], [title['offers'][0]['link']])
        self.assertNotIn('body', fields)
        title['offers'][0]['link'] = 'javascript:alert(1)'
        self.assertNotIn('official_url', parse_qs(urlsplit(correction_link(title)).query))
        self.assertLessEqual(len(correction_link(title, notes='తెలుగు' * 4000)), 7500)
        self.assertEqual(parse_qs(urlsplit(INBOX).query)['q'], ['is:issue is:open label:catalogue-correction'])

    def test_public_page_has_real_report_and_inbox_links_without_auto_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('index.html', 'app.js', 'style.css', 'CNAME'):
                (root / name).write_text('')
            (root / 'data').mkdir()
            (root / 'data/catalog.json').write_text(json.dumps({'titles': [], 'updatedAt': '2026-11-21'}))
            site = build(root)
            page = (site / 'corrections/index.html').read_text()
            self.assertIn('template=catalogue-correction.yml', unescape(page))
            self.assertIn(INBOX, unescape(page))
            self.assertIn('never change the catalogue automatically', page)
            self.assertIn('account is required', page)
            self.assertIn('name="robots" content="noindex,follow"', page)
            self.assertIn('/corrections/', (site / 'contact/index.html').read_text())
            self.assertNotIn('<form', page, 'Submission goes to the real GitHub review form')
