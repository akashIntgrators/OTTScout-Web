import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError

spec = importlib.util.spec_from_file_location('sync', Path(__file__).parents[1] / 'scripts/catalog_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
NOW = 1792860000

def show(id='1', audio='hin', services=('netflix',)):
    return {'id': id, 'title': 'A real-looking test fixture', 'showType': 'movie', 'releaseYear': 2025,
            'streamingOptions': {'in': [
                {'service': {'id': service}, 'type': 'subscription', 'audios': [{'language': audio}],
                 'subtitles': [{'locale': {'language': 'eng'}}], 'link': 'https://example.com/watch',
                 'availableSince': NOW - 1000} for service in services]},
            'imageSet': {'verticalPoster': {'w480': 'https://example.com/poster.png'}}, 'genres': []}

class FakeClient:
    def __init__(self, fail=None):
        self.calls = 0
        self.fail = fail
    def get(self, endpoint, params=None):
        self.calls += 1
        if self.fail == endpoint:
            raise sync.SyncError('Simulated failure')
        if endpoint == '/countries/in':
            return {'countryCode': 'in', 'services': [{'id': 'netflix', 'name': 'Netflix'}]}
        if endpoint == '/shows/search/filters':
            result = show()
            result['showType'] = params['show_type']
            result['id'] = params['show_type']
            return {'shows': [result], 'hasMore': params.get('order_by') != 'original_title', 'nextCursor': 'more'}
        return {'changes': [], 'shows': {}, 'hasMore': False}

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = sync.open_db(self.root / 'state.sqlite')
    def tearDown(self):
        self.db.close()
        self.temp.cleanup()
    def test_original_language_is_distinct_from_dubbed_offer(self):
        result = show()
        result['originalLanguage'] = 'kn'
        normalized = sync.normalize(result, {'Netflix':'netflix'}, NOW)
        self.assertEqual(normalized['originalLanguage'], 'Kannada')
        self.assertEqual(normalized['offers'][0]['audio'], ['Hindi'])
        self.assertIsNone(sync.normalize(show(), {'Netflix':'netflix'}, NOW)['originalLanguage'])

    def test_full_catalog_resumes_and_does_not_create_weekly_events(self):
        class Pages:
            calls = 0
            run_limit = 10
            def get(inner, endpoint, params):
                inner.calls += 1
                if not params.get('cursor'):
                    return {'shows':[show('older')], 'hasMore':True, 'nextCursor':'page2'}
                self.assertEqual(params['cursor'], 'page2')
                return {'shows':[show('oldest')], 'hasMore':False}
        client = Pages()
        sync.backfill_catalog(self.db, client, {'Netflix':'netflix'}, NOW, max_pages=1)
        self.assertEqual(sync.get_meta(self.db, 'catalog_backfill_v1:netflix:movie')['cursor'], 'page2')
        sync.backfill_catalog(self.db, client, {'Netflix':'netflix'}, NOW, max_pages=1)
        self.assertTrue(sync.get_meta(self.db, 'catalog_backfill_v1:netflix:movie')['complete'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM titles').fetchone()[0], 2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_existing_dr56_is_corrected_without_changing_offer_audio(self):
        sync.save_show(self.db, show('57489'), {'Netflix':'netflix'}, NOW)
        sync.set_meta(self.db, 'last_success', NOW)
        path = self.root / 'catalog.json'
        sync.export_catalog(self.db, path, NOW)
        title = json.loads(path.read_text())['titles'][0]
        self.assertEqual(title['originalLanguage'], 'Kannada')
        self.assertEqual(title['offers'][0]['audio'], ['Hindi'])

    def test_audio_is_per_offer_and_unknown_not_inferred(self):
        result = show(services=('netflix', 'prime'))
        result['streamingOptions']['in'][1]['audios'] = []
        normalized = sync.normalize(result, {'Netflix': 'netflix', 'Prime Video': 'prime'}, NOW)
        self.assertEqual(normalized['offers'][0]['audio'], ['Hindi'])
        self.assertEqual(normalized['offers'][1]['audio'], [])
        self.assertEqual(normalized['offers'][0]['subtitles'], ['English'])
    def test_other_countries_and_services_are_not_imported(self):
        result = show(services=('netflix', 'unwanted'))
        result['streamingOptions']['us'] = result['streamingOptions'].pop('in')
        self.assertEqual(sync.normalize(result, {'Netflix': 'netflix'}, NOW)['offers'], [])
    def test_unsafe_urls_are_discarded(self):
        result = show()
        result['streamingOptions']['in'][0]['link'] = 'javascript:alert(1)'
        result['imageSet']['verticalPoster']['w480'] = 'data:text/html,unsafe'
        normalized = sync.normalize(result, {'Netflix': 'netflix'}, NOW)
        self.assertIsNone(normalized['poster'])
        self.assertIsNone(normalized['offers'][0]['link'])
    def test_initial_import_is_not_weekly_and_coverage_gap_is_visible(self):
        sync.set_meta(self.db, 'pilot_started', NOW)
        sync.sync(self.db, FakeClient(), NOW)
        output = self.root / 'catalog.json'
        self.assertTrue(sync.export_catalog(self.db, output, NOW))
        data = json.loads(output.read_text())
        self.assertEqual(len(data['titles']), 2)
        self.assertTrue(all(not t['weekly'] for t in data['titles']))
        self.assertIn('aha', data['missingPlatforms'])
        self.assertEqual(data['coverage'], ['Netflix'])
    def test_missing_audio_is_not_exported_as_matching_language(self):
        sync.set_meta(self.db, 'last_success', NOW)
        result = show(audio='jpn')
        sync.save_show(self.db, result, {'Netflix': 'netflix'}, NOW)
        output = self.root / 'catalog.json'
        sync.export_catalog(self.db, output, NOW)
        self.assertEqual(json.loads(output.read_text())['titles'], [])
    def test_failed_change_query_does_not_advance_watermark(self):
        sync.sync(self.db, FakeClient(), NOW)
        watermark = sync.get_meta(self.db, 'watermark:new')
        with self.assertRaises(sync.SyncError):
            sync.sync(self.db, FakeClient('/changes'), NOW + 21600)
        self.assertEqual(sync.get_meta(self.db, 'watermark:new'), watermark)
        self.assertEqual(sync.get_meta(self.db, 'last_success'), NOW)
    def test_change_pagination_must_complete_before_upserts(self):
        sync.sync(self.db, FakeClient(), NOW)
        class BrokenPage(FakeClient):
            def get(self, endpoint, params=None):
                if endpoint == '/changes':
                    if params.get('cursor'):
                        raise sync.SyncError('Page two failed')
                    return {'shows': {'new': show('new')},
                            'changes': [{'showId': 'new'}], 'hasMore': True, 'nextCursor': 'second'}
                return super().get(endpoint, params)
        with self.assertRaises(sync.SyncError):
            sync.sync(self.db, BrokenPage(), NOW + 21600)
        self.assertIsNone(self.db.execute("SELECT id FROM titles WHERE id='motn:new'").fetchone())
    def test_monthly_limit_blocks_network_call(self):
        client = sync.Client(self.db, 'not-a-real-key', monthly_limit=0)
        with patch.object(sync, 'urlopen') as network:
            with self.assertRaises(sync.BudgetReached):
                client.get('/countries/in')
            network.assert_not_called()
    def test_network_failure_still_consumes_local_request_budget(self):
        client = sync.Client(self.db, 'not-a-real-key', run_limit=1)
        with patch.object(sync, 'urlopen', side_effect=URLError('offline')):
            with self.assertRaises(sync.SyncError):
                client.get('/countries/in')
            with self.assertRaises(sync.BudgetReached):
                client.get('/countries/in')
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0], 1)
    def test_provider_history_can_populate_weekly_for_an_initial_title(self):
        class History(FakeClient):
            def get(self, endpoint, params=None):
                if endpoint == '/changes' and params['from'] == NOW - 7 * sync.DAY:
                    return {'shows': {'movie': show('movie')}, 'changes': [
                        {'showId': 'movie', 'service': {'id': 'netflix'}, 'timestamp': NOW - sync.DAY,
                         'link': 'https://example.com/watch'}], 'hasMore': False}
                return super().get(endpoint, params)
        sync.sync(self.db, History(), NOW)
        path = self.root / 'catalog.json'
        sync.export_catalog(self.db, path, NOW)
        title = next(t for t in json.loads(path.read_text())['titles'] if t['id'] == 'motn:movie')
        self.assertTrue(title['weekly'])
        self.assertEqual(title['weeklyUpdatedAt'], NOW - sync.DAY)
        self.assertTrue(json.loads(path.read_text())['recentHistoryComplete'])
        sync.export_catalog(self.db, path, NOW + 8 * sync.DAY)
        self.assertFalse(next(t for t in json.loads(path.read_text())['titles'] if t['id'] == 'motn:movie')['weekly'])
    def test_recent_history_resumes_at_saved_cursor_after_budget_limit(self):
        class FirstPage:
            calls = 0
            def get(self, endpoint, params):
                self.calls += 1
                if self.calls > 1:
                    raise sync.BudgetReached('test limit')
                return {'shows': {'old': show('old')}, 'changes': [
                    {'showId': 'old', 'service': {'id': 'netflix'}, 'timestamp': NOW - sync.DAY}],
                    'hasMore': True, 'nextCursor': 'second-page'}
        with self.assertRaises(sync.BudgetReached):
            sync.backfill_recent(self.db, FirstPage(), {'Netflix':'netflix'}, NOW)
        self.assertEqual(sync.get_meta(self.db,'recent_backfill_v1')['cursor'],'second-page')
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0],1)
        class SecondPage:
            def get(inner, endpoint, params):
                self.assertEqual(params['cursor'],'second-page')
                self.assertEqual(params['from'], NOW - 7 * sync.DAY)
                self.assertEqual(params['to'], NOW)
                return {'shows':{},'changes':[],'hasMore':False}
        sync.backfill_recent(self.db, SecondPage(), {'Netflix':'netflix'}, NOW + 300)
        self.assertTrue(sync.get_meta(self.db,'recent_backfill_v1')['complete'])
    def test_invalid_history_page_preserves_cursor_and_titles(self):
        class Invalid:
            def get(self, endpoint, params):
                return {'shows':{'old':show('old')},'changes':[
                    {'showId':'old','service':{'id':'netflix'},'timestamp':NOW + sync.DAY}], 'hasMore':False}
        with self.assertRaises(sync.SyncError):
            sync.backfill_recent(self.db, Invalid(), {'Netflix':'netflix'}, NOW)
        self.assertEqual(self.db.execute('SELECT count(*) FROM titles').fetchone()[0],0)
        self.assertFalse(sync.get_meta(self.db,'recent_backfill_v1')['complete'])
    def test_expired_pilot_makes_zero_calls_without_a_key(self):
        sync.set_meta(self.db, 'pilot_started', 1)
        self.db.commit()
        result = subprocess.run([sys.executable, str(Path(sync.__file__)), '--db', str(self.root / 'state.sqlite'),
                                 '--report', str(self.root / 'report.json')],
                                env={k: v for k, v in os.environ.items() if k != 'STREAMING_API_KEY'}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads((self.root / 'report.json').read_text())
        self.assertEqual(report['runs'][-1]['status'], 'complete')
        self.assertEqual(report['requestsDuringPilot'], 0)
    def test_missing_state_fails_closed_without_initialization(self):
        result = subprocess.run([sys.executable, str(Path(sync.__file__)), '--db', str(self.root / 'empty.sqlite')],
                                env={k: v for k, v in os.environ.items() if k != 'STREAMING_API_KEY'}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('made no API calls', result.stdout)
    def test_repeated_pagination_cursor_is_rejected(self):
        class Repeated:
            def get(self, endpoint, params):
                return {'shows': [], 'hasMore': True, 'nextCursor': 'same'}
        with self.assertRaises(sync.SyncError):
            list(sync.read_pages(Repeated(), '/shows', {}))
    def test_new_platform_event_marks_existing_title_weekly(self):
        sync.sync(self.db, FakeClient(), NOW)
        class NewPlatform(FakeClient):
            def get(self, endpoint, params=None):
                if endpoint == '/changes' and params['change_type'] == 'new':
                    return {'shows': {'movie': show('movie')}, 'changes': [
                        {'showId': 'movie', 'service': {'id': 'netflix'}, 'timestamp': NOW + 100,
                         'link': 'https://example.com/watch'}], 'hasMore': False}
                return super().get(endpoint, params)
        sync.sync(self.db, NewPlatform(), NOW + 21600)
        sync.sync(self.db, NewPlatform(), NOW + 22000)
        output = self.root / 'catalog.json'
        sync.export_catalog(self.db, output, NOW + 22000)
        title = next(t for t in json.loads(output.read_text())['titles'] if t['id'] == 'motn:movie')
        self.assertTrue(title['weekly'])
        self.assertEqual(title['weeklyPlatforms'], ['Netflix'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 1)

if __name__ == '__main__':
    unittest.main()
