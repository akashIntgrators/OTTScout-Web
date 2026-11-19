"""Official gaps must survive normal export and API-free website publication."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import build_site, catalog_sync
from scripts.official_listings import apply_official_listings


NOW = 1795089600  # 19 November 2026, 12:00 UTC
IDENT = 'motn:official-hotstar-1271718279'
TITLE_URL = 'https://www.hotstar.com/in/shows/mr-and-mrs-office/1271718279'


def record():
    return {'id': IDENT, 'platform': 'JioHotstar', 'platformTitleId': '1271718279',
            'title': 'Mr & Mrs Office', 'type': 'Series', 'year': 2026, 'sourceURL': TITLE_URL,
            'releaseDate': '2026-11-18', 'releaseEvidenceURL': 'https://moviesandtv.myvi.in/tvshow/hs-1271718279',
            'verifiedAt': NOW - 3600, 'expiresAt': NOW + 7 * 86400,
            'access': {'type': 'subscription', 'evidenceURL': 'https://cdn.jiostar.com/jiostar/plans.pdf'},
            'audio': ['Tamil'], 'audioEvidenceURL': 'https://moviesandtv.myvi.in/tvshow/hs-1271718279',
            'originalLanguage': None}


def show(services=('hotstar',)):
    return {'id': '777', 'title': 'Mr & Mrs Office', 'showType': 'series', 'firstAirYear': 2026,
            'streamingOptions': {'in': [{'service': {'id': service}, 'type': 'subscription',
                'audios': [{'language': 'tam'}], 'subtitles': [],
                'link': TITLE_URL if service == 'hotstar' else 'https://www.netflix.com/title/123',
                'availableSince': NOW - 100} for service in services]}}


class OfficialPipelineTests(unittest.TestCase):
    def test_cached_export_uses_no_requests_and_keeps_alias_after_registry_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); registry = root / 'official.json'; registry.write_text(json.dumps([record()]))
            db = catalog_sync.open_db(root / 'catalog.sqlite')
            self.addCleanup(db.close)
            catalog_sync.set_meta(db, 'last_success', NOW - 86400)
            catalog_sync.set_meta(db, 'coverage', {'mapping': {'JioHotstar': 'hotstar', 'Netflix': 'netflix'}})
            db.execute('INSERT INTO requests(at,endpoint,status) VALUES (?,?,?)', (NOW, '/fixture', 200)); db.commit()
            output = root / 'catalog.json'; mapping = {'JioHotstar': 'hotstar', 'Netflix': 'netflix'}
            with patch.object(catalog_sync, 'OFFICIAL_LISTINGS_PATH', registry), \
                    patch.object(catalog_sync, 'urlopen', side_effect=AssertionError('Unexpected provider request')):
                self.assertTrue(catalog_sync.export_catalog(db, output, NOW))
                first = json.loads(output.read_text())
                self.assertEqual(first['titles'][0]['id'], IDENT)
                self.assertEqual(first['updatedAt'], catalog_sync.stamp(NOW - 86400))
                catalog_sync.save_show(db, show(), mapping, NOW + 1); db.commit()
                catalog_sync.export_catalog(db, output, NOW + 1)
                second = json.loads(output.read_text())
                self.assertEqual([t['id'] for t in second['titles']], [IDENT])
                self.assertEqual(catalog_sync.get_meta(db, 'official_listing_aliases_v1')['motn:777'], IDENT)
                self.assertIsNone(db.execute('SELECT id FROM titles WHERE id=?', (IDENT,)).fetchone())
                # A newer explicit removal suppresses old official evidence;
                # a current offer on another platform and its stable ID survive.
                catalog_sync.save_show(db, show(('netflix',)), mapping, NOW + 2)
                db.execute('INSERT INTO events VALUES (?,?,?,?,?)', ('removed', 'motn:777', 'JioHotstar', 'removed', NOW + 2)); db.commit()
                catalog_sync.export_catalog(db, output, NOW + 2)
                third = json.loads(output.read_text())['titles'][0]
                self.assertEqual(third['id'], IDENT)
                self.assertEqual([o['platform'] for o in third['offers']], ['Netflix'])
                self.assertEqual(third['officialListing']['inactiveReason'], 'newer-provider-removal')
                registry.unlink()
                catalog_sync.export_catalog(db, output, NOW + 3)
                withdrawn = json.loads(output.read_text())['titles'][0]
                self.assertEqual(withdrawn['id'], IDENT)
                self.assertNotIn('officialListing', withdrawn)
                self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)

    def test_website_publication_only_allows_official_overlay_and_rechecks_expiry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root / 'data').mkdir(); (root / 'runner').mkdir()
            for name in ('index.html', 'app.js', 'style.css', 'CNAME'):
                (root / name).write_text('')
            provider = {'id': 'motn:1', 'title': 'Provider title', 'type': 'Movie', 'year': 2020,
                        'lastCheckedAt': NOW - 100, 'offers': [{'platform': 'Netflix', 'type': 'subscription',
                            'audio': ['English'], 'subtitles': [], 'link': 'https://www.netflix.com/title/1'}],
                        'weeklyEvents': [], 'weeklyPlatforms': [], 'weekly': False}
            baseline = {'schemaVersion': 1, 'mode': 'live', 'updatedAt': '2026-11-13T07:02:34+00:00',
                        'coverage': ['Netflix', 'JioHotstar'], 'missingPlatforms': [], 'titles': [provider]}
            source = root / 'data/catalog.json'; source.write_text(json.dumps(baseline))
            original_bytes = source.read_bytes()
            (root / 'data/official-listings.json').write_text(json.dumps([record()]))
            site = build_site.build(root, NOW)
            widget = json.loads((site / 'data/widget.json').read_text())
            self.assertIn(IDENT, [t['id'] for t in widget['titles']])
            title_html = (site / 'titles/official-hotstar-1271718279/index.html').read_text()
            self.assertIn('Official listing', title_html)
            self.assertIn('2026-11-18 (day precision)', title_html)
            self.assertIn('Reported audio languages: official distributor listing', title_html)
            # Tamper with a general-builder row: the publisher must restore the
            # immutable downloaded provider data and retain only the overlay.
            staged = site / 'data/catalog.json'; value = json.loads(staged.read_text())
            value['titles'][0]['title'] = 'Unrelated builder mutation'; staged.write_text(json.dumps(value))
            (root / 'runner/ottscout-published-catalogue.sha256').write_text(hashlib.sha256(original_bytes).hexdigest())
            workflow = (Path(__file__).parents[1] / '.github/workflows/publish-site.yml').read_text()
            start = workflow.index('          import hashlib, json, os, shutil, time')
            end = workflow.index('          PYCODE', start)
            guard = '\n'.join(line[10:] for line in workflow[start:end].splitlines())
            previous = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {'RUNNER_TEMP': str(root / 'runner')}), patch.object(time, 'time', return_value=NOW):
                    exec(guard, {})
            finally:
                os.chdir(previous)
            published = json.loads(staged.read_text())
            self.assertEqual(next(t for t in published['titles'] if t['id'] == 'motn:1'), provider)
            self.assertIn(IDENT, [t['id'] for t in published['titles']])
            self.assertEqual(source.read_bytes(), original_bytes)
            # Rebuilding that previously published snapshot after expiry must
            # remove it from catalogue, widgets and crawlable title pages.
            source.write_text(json.dumps(published))
            site = build_site.build(root, NOW + 8 * 86400)
            self.assertNotIn(IDENT, [t['id'] for t in json.loads((site / 'data/catalog.json').read_text())['titles']])
            self.assertNotIn(IDENT, [t['id'] for t in json.loads((site / 'data/widget.json').read_text())['titles']])
            self.assertFalse((site / 'titles/official-hotstar-1271718279/index.html').exists())

    def test_withdrawn_registry_does_not_keep_stale_official_release_metadata(self):
        provider = {'id': 'motn:777', 'title': 'Mr & Mrs Office', 'type': 'Series', 'year': 2026,
                    'lastCheckedAt': NOW, 'offers': [{'platform': 'JioHotstar', 'type': 'subscription',
                        'audio': ['Tamil'], 'subtitles': [], 'link': TITLE_URL}], 'weeklyEvents': []}
        first, _ = apply_official_listings({'titles': [provider]}, [record()], NOW)
        second, _ = apply_official_listings(first, [], NOW + 8 * 86400)
        self.assertEqual(second['titles'][0]['id'], IDENT)
        self.assertEqual(second['titles'][0]['offers'], provider['offers'])
        self.assertNotIn('officialListing', second['titles'][0])
