import json
from pathlib import Path
import tempfile
import unittest
import subprocess

from scripts.status_page import render_status


class StatusPageTests(unittest.TestCase):
    def test_stale_status_is_detected_in_an_already_open_browser(self):
        subprocess.run(['node', 'tests/catalogue_status.cjs'], cwd=Path(__file__).parents[1], check=True, capture_output=True)

    def test_absent_report_never_claims_healthy_or_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            html = render_status(Path(directory))
            self.assertIn('Freshness has not been confirmed', html)
            self.assertNotIn('Updates are within the current target', html)
            self.assertIn('Coverage remains partial', html)

    def test_published_status_uses_feed_completion_and_escapes_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'data').mkdir()
            report = {'status': 'critical', 'evaluatedAt': 1795194000,
                      'newFeed': {'completedThrough': '2026-11-19T07:45:29+00:00'},
                      'requestBudget': {'requestsUsed': 374, 'monthlyLimit': 400},
                      'causes': [{'message': '<script>bad</script>'}],
                      'officialDiscovery': {'sources': [{'id': 'sony-movies', 'status': 'ok', 'lastSuccessAt': 1795194000}]}}
            (root / 'data/catalogue-health.json').write_text(json.dumps(report))
            html = render_status(root)
            self.assertIn('Release updates are delayed', html)
            self.assertIn('19 November, 01:15 PM IST', html)
            self.assertIn('374 / 400', html)
            self.assertIn('&lt;script&gt;bad&lt;/script&gt;', html)
            self.assertNotIn('<script>bad</script>', html)
