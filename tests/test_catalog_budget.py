"""Offline regression cases for continuous collection and reserved backfill quota."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse


spec = importlib.util.spec_from_file_location('budget_sync', Path(__file__).parents[1] / 'scripts/catalog_sync.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


NOW = epoch('2026-11-04T06:50:00+00:00')


class Response:
    status = 200

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.value).encode()


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = sync.open_db(Path(self.temp.name) / 'catalog.sqlite')
        self.addCleanup(self.db.close)
        # An unplanned provider access fails the test instead of reaching a network.
        blocker = patch.object(sync, 'urlopen', side_effect=AssertionError('Unmocked provider access'))
        blocker.start()
        self.addCleanup(blocker.stop)
        self.requests = []
        self.mapping = {'Netflix': 'netflix', 'Prime Video': 'prime', 'JioHotstar': 'hotstar',
                        'ZEE5': 'zee5', 'SonyLIV': 'sonyliv'}

    def attempts(self, at, count, statuses=(200,)):
        self.db.executemany('INSERT INTO requests(at,endpoint,status) VALUES (?,?,?)',
                            [(at, '/fixture', statuses[index % len(statuses)]) for index in range(count)])
        self.db.commit()

    def prepared_catalogue(self):
        sync.set_meta(self.db, 'pilot_started', NOW - 90 * sync.DAY)
        sync.set_meta(self.db, 'coverage', {'mapping': self.mapping, 'checkedAt': NOW, 'missing': []})
        sync.set_meta(self.db, 'baseline_started', NOW - sync.DAY)
        sync.set_meta(self.db, 'baseline_complete', NOW - sync.DAY)
        sync.set_meta(self.db, 'baseline_done', [service + ':' + kind for service in self.mapping.values()
                                               for kind in ('movie', 'series')])
        sync.set_meta(self.db, 'recent_backfill_v1', {'complete': True, 'pages': 1})
        for kind in ('new', 'updated', 'removed'):
            sync.set_meta(self.db, 'watermark:' + kind, NOW)
        sync.set_meta(self.db, 'last_success', NOW)
        self.db.commit()

    def reply(self, request, **kwargs):
        parsed = urlparse(request.full_url)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self.requests.append((parsed.path, params))
        if parsed.path.endswith('/changes'):
            return Response({'shows': {}, 'changes': [], 'hasMore': False})
        if parsed.path.endswith('/shows/search/title'):
            return Response([])
        self.assertTrue(parsed.path.endswith('/shows/search/filters'))
        ident = 'older-' + str(len(self.requests))
        service = params['catalogs'].split(',')[0]
        show = {'id': ident, 'title': ident, 'showType': params['show_type'], 'releaseYear': 1997,
                'streamingOptions': {'in': [{'service': {'id': service}, 'type': 'subscription',
                    'audios': [{'language': 'eng'}], 'subtitles': [],
                    'link': 'https://example.test/watch', 'availableSince': NOW - 90 * sync.DAY}]}}
        return Response({'shows': [show], 'hasMore': True, 'nextCursor': 'next-' + ident})

    def run_sync(self, at=NOW, extra=None):
        with patch.dict(os.environ, extra or {}, clear=True), patch.object(sync.time, 'time', return_value=at), \
                patch.object(sync, 'urlopen', side_effect=self.reply):
            client = sync.Client(self.db, 'fixture-not-a-key')
            changed = sync.sync(self.db, client, at)
        return client, changed

    def test_month_lengths_leap_year_and_year_rollover_reserve_whole_remaining_days(self):
        cases = [
            ('2026-01-01T00:00:00+00:00', 31), ('2026-01-31T23:59:59+00:00', 1),
            ('2025-02-01T00:00:00+00:00', 28), ('2024-02-01T00:00:00+00:00', 29),
            ('2024-02-28T00:00:00+00:00', 2), ('2024-02-29T23:59:59+00:00', 1),
            ('2026-12-31T23:59:59+00:00', 1), ('2027-01-01T00:00:00+00:00', 31),
        ]
        for date, days in cases:
            with self.subTest(date=date):
                budget = sync.request_budget(self.db, epoch(date))
                self.assertEqual(budget['freshnessReserve'], days * 8 + 20)
                self.assertEqual(budget['backfillAvailable'], max(0, 400 - days * 8 - 20))

    def test_every_attempt_status_counts_but_previous_month_history_is_retained(self):
        self.attempts(epoch('2026-10-31T23:59:59+00:00'), 3, (0, 429, 500))
        self.attempts(epoch('2026-11-01T00:00:00+00:00'), 4, (0, 200, 429, 503))
        budget = sync.request_budget(self.db, NOW)
        self.assertEqual(budget['requestsUsed'], 4)
        self.assertEqual(budget['requestsRemaining'], 396)
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0], 7)
        following = sync.request_budget(self.db, epoch('2026-12-01T00:00:00+00:00'))
        self.assertEqual(following['requestsUsed'], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0], 7)

    def test_configuration_cannot_raise_the_400_month_or_12_run_ceiling(self):
        raised = sync.Client(self.db, 'fixture-not-a-key', monthly_limit=9999, run_limit=9999)
        self.assertEqual((raised.monthly_limit, raised.run_limit), (400, 12))
        self.assertEqual(sync.request_budget(self.db, NOW, 9999)['monthlyLimit'], 400)
        lowered = sync.Client(self.db, 'fixture-not-a-key', monthly_limit=50, run_limit=3)
        self.assertEqual((lowered.monthly_limit, lowered.run_limit), (50, 3))
        negative = sync.Client(self.db, 'fixture-not-a-key', monthly_limit=-1, run_limit=-1)
        self.assertEqual((negative.monthly_limit, negative.run_limit), (0, 0))

    def test_zero_month_or_run_budget_never_sends_or_records_a_request(self):
        with patch.object(sync.time, 'time', return_value=NOW), patch.object(sync, 'urlopen') as network:
            for monthly, per_run in ((0, 12), (400, 0)):
                with self.subTest(monthly=monthly, per_run=per_run):
                    client = sync.Client(self.db, 'fixture-not-a-key', monthly_limit=monthly, run_limit=per_run)
                    with self.assertRaises(sync.BudgetReached):
                        client.get('/countries/in')
                    self.assertEqual(client.calls, 0)
            network.assert_not_called()
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0], 0)

    def test_failed_400th_attempt_is_counted_and_401st_never_reaches_provider(self):
        self.attempts(NOW - 1, 399, (0, 200, 429, 503))
        error = HTTPError('https://example.test/fixture', 429, 'fixture quota', {}, None)
        with patch.object(sync.time, 'time', return_value=NOW), patch.object(sync, 'urlopen', side_effect=error) as network:
            client = sync.Client(self.db, 'fixture-not-a-key', monthly_limit=9999)
            with self.assertRaises(sync.SyncError):
                client.get('/countries/in')
            with self.assertRaises(sync.BudgetReached):
                client.get('/countries/in')
            self.assertEqual(network.call_count, 1)
        self.assertEqual(sync.request_budget(self.db, NOW)['requestsUsed'], 400)
        self.assertEqual(self.db.execute('SELECT status FROM requests ORDER BY id DESC LIMIT 1').fetchone()[0], 429)

    def test_network_failures_use_the_run_allowance_without_automatic_retries(self):
        with patch.object(sync.time, 'time', return_value=NOW), patch.object(sync, 'urlopen', side_effect=URLError('fixture offline')) as network:
            client = sync.Client(self.db, 'fixture-not-a-key', run_limit=9999)
            for _ in range(12):
                with self.assertRaises(sync.SyncError):
                    client.get('/countries/in')
            with self.assertRaises(sync.BudgetReached):
                client.get('/countries/in')
            self.assertEqual(network.call_count, 12)
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0], 12)

    def test_new_feed_uses_utc_slots_so_scheduler_jitter_cannot_skip_a_new_slot(self):
        sync.set_meta(self.db, 'watermark:new', epoch('2026-11-04T06:50:00+00:00'))
        self.assertFalse(sync.change_feed_due(self.db, 'new', epoch('2026-11-04T07:00:00+00:00')))
        self.assertTrue(sync.change_feed_due(self.db, 'new', epoch('2026-11-04T12:40:00+00:00')))
        sync.set_meta(self.db, 'watermark:new', epoch('2026-11-04T05:59:59+00:00'))
        self.assertTrue(sync.change_feed_due(self.db, 'new', epoch('2026-11-04T06:00:00+00:00')))

    def test_maintenance_uses_utc_days_and_pending_queries_override_every_cadence(self):
        for kind in ('updated', 'removed'):
            sync.set_meta(self.db, 'watermark:' + kind, epoch('2026-11-03T23:50:00+00:00'))
            self.assertTrue(sync.change_feed_due(self.db, kind, epoch('2026-11-04T00:05:00+00:00')))
            sync.set_meta(self.db, 'watermark:' + kind, NOW)
            self.assertFalse(sync.change_feed_due(self.db, kind, epoch('2026-11-04T23:50:00+00:00')))
        for kind in ('new', 'updated', 'removed'):
            sync.set_meta(self.db, 'watermark:' + kind, NOW)
            sync.set_meta(self.db, 'change_window_v2:' + kind, {'cursor': 'pending'})
            self.assertTrue(sync.change_feed_due(self.db, kind, NOW))

    def test_sync_checks_only_due_feeds_and_keeps_the_oldest_complete_freshness_stamp(self):
        self.prepared_catalogue()
        later = epoch('2026-11-04T12:40:00+00:00')
        client, _ = self.run_sync(later, {'CATALOG_BACKFILL_PAGES': '0'})
        self.assertEqual(client.calls, 1)
        self.assertEqual([params['change_type'] for path, params in self.requests], ['new'])
        self.assertEqual(sync.get_meta(self.db, 'watermark:new'), later)
        self.assertEqual(sync.get_meta(self.db, 'watermark:updated'), NOW)
        self.assertEqual(sync.get_meta(self.db, 'last_success'), NOW)

    def test_pending_maintenance_resumes_before_a_fresh_new_feed_without_losing_its_cursor(self):
        self.prepared_catalogue()
        sync.set_meta(self.db, 'watermark:new', NOW - 6 * 3600)
        sync.set_meta(self.db, 'change_window_v2:updated', {'from': NOW - 300, 'to': NOW - 100,
            'cursor': 'saved-update-cursor', 'seen': ['saved-update-cursor'], 'pages': 0, 'mapping': self.mapping})
        self.db.commit()
        self.run_sync(extra={'CATALOG_BACKFILL_PAGES': '0'})
        self.assertEqual([params['change_type'] for path, params in self.requests], ['updated', 'new'])
        self.assertEqual(self.requests[0][1]['cursor'], 'saved-update-cursor')
        self.assertEqual(self.requests[0][1]['to'], str(NOW - 100))
        self.assertIsNone(sync.get_meta(self.db, 'change_window_v2:updated'))
        self.assertEqual(sync.get_meta(self.db, 'watermark:updated'), NOW - 100)

    def test_spare_budget_defaults_to_six_generic_pages_and_preserves_legacy_language_state(self):
        self.prepared_catalogue()
        legacy = {'pages': 22, 'complete': False, 'cursor': 'legacy-catalogue-cursor'}
        original = {'pages': 17, 'complete': False, 'cursor': 'legacy-language-cursor'}
        sync.set_meta(self.db, 'catalog_backfill_v1:netflix:movie', legacy)
        sync.set_meta(self.db, 'catalog_backfill_next', 0)
        sync.set_meta(self.db, 'original_backfill_v1:te:movie', original)
        sync.set_meta(self.db, 'original_backfill_next', 4)
        self.db.commit()
        client, changed = self.run_sync()
        self.assertEqual((client.calls, changed), (6, 6))
        self.assertEqual(self.requests[0][1]['cursor'], legacy['cursor'])
        self.assertTrue(all('show_original_language' not in params for path, params in self.requests))
        self.assertEqual(sync.get_meta(self.db, 'catalog_backfill_v1:netflix:movie')['pages'], 23)
        self.assertEqual(sync.get_meta(self.db, 'original_backfill_v1:te:movie'), original)
        self.assertEqual(sync.get_meta(self.db, 'original_backfill_next'), 4)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_generic_import_precedes_optional_original_scans_and_still_obeys_six_page_maximum(self):
        self.prepared_catalogue()
        client, _ = self.run_sync(extra={'CATALOG_BACKFILL_PAGES': '999', 'ORIGINAL_LANGUAGE_BACKFILL_PAGES': '2'})
        self.assertEqual(client.calls, 8)
        self.assertTrue(all('show_original_language' not in params for path, params in self.requests[:6]))
        self.assertTrue(all('show_original_language' in params for path, params in self.requests[6:]))
        self.assertGreaterEqual(sync.request_budget(self.db, NOW)['requestsRemaining'], sync.request_budget(self.db, NOW)['freshnessReserve'])

    def test_only_the_excess_is_imported_even_when_six_pages_were_requested(self):
        self.prepared_catalogue()
        reserve = sync.request_budget(self.db, NOW)['freshnessReserve']
        self.attempts(NOW - 1, 400 - reserve - 2)
        client, _ = self.run_sync(extra={'CATALOG_BACKFILL_PAGES': '6', 'ORIGINAL_LANGUAGE_BACKFILL_PAGES': '2'})
        self.assertEqual(client.calls, 2)
        budget = sync.request_budget(self.db, NOW)
        self.assertEqual(budget['requestsRemaining'], reserve)
        self.assertEqual(budget['backfillAvailable'], 0)
        self.assertTrue(all('show_original_language' not in params for path, params in self.requests))

    def test_protected_reserve_blocks_old_pages_but_allows_due_freshness_requests(self):
        self.prepared_catalogue()
        reserve = sync.request_budget(self.db, NOW)['freshnessReserve']
        self.attempts(NOW - 1, 400 - reserve)
        legacy = {'pages': 57, 'complete': False, 'cursor': 'do-not-reset'}
        sync.set_meta(self.db, 'catalog_backfill_v1:netflix:movie', legacy)
        self.db.commit()
        later = epoch('2026-11-04T12:40:00+00:00')
        client, _ = self.run_sync(later)
        self.assertEqual(client.calls, 1)
        self.assertEqual(self.requests[0][1]['change_type'], 'new')
        self.assertEqual(sync.get_meta(self.db, 'catalog_backfill_v1:netflix:movie'), legacy)
        self.assertEqual(sync.request_budget(self.db, later)['backfillAvailable'], 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_report_rechecks_are_globally_once_per_utc_day_and_failed_attempts_use_that_slot(self):
        self.prepared_catalogue()
        records = [{'netflixId': '123', 'title': 'First fixture'}, {'netflixId': '456', 'title': 'Second fixture'}]
        with patch.object(sync.time, 'time', return_value=NOW), patch.object(sync, 'urlopen', side_effect=URLError('fixture failure')) as network:
            sync.recheck_reported_titles(self.db, sync.Client(self.db, 'fixture-not-a-key'), NOW, records)
            sync.recheck_reported_titles(self.db, sync.Client(self.db, 'fixture-not-a-key'), NOW + 6 * 3600, records)
            self.assertEqual(network.call_count, 1)
        tomorrow = epoch('2026-11-05T00:30:00+00:00')
        with patch.object(sync.time, 'time', return_value=tomorrow), patch.object(sync, 'urlopen', side_effect=self.reply) as network:
            sync.recheck_reported_titles(self.db, sync.Client(self.db, 'fixture-not-a-key'), tomorrow, records)
            self.assertEqual(network.call_count, 1)

    def test_a_prevented_recheck_does_not_consume_the_daily_slot(self):
        self.prepared_catalogue()
        records = [{'netflixId': '123', 'title': 'Fixture'}]
        with patch.object(sync.time, 'time', return_value=NOW), patch.object(sync, 'urlopen', side_effect=self.reply) as network:
            with self.assertRaises(sync.BudgetReached):
                sync.recheck_reported_titles(self.db, sync.Client(self.db, 'fixture-not-a-key', monthly_limit=0), NOW, records)
            self.assertIsNone(sync.get_meta(self.db, 'title_recheck_last_attempt'))
            network.assert_not_called()
            sync.recheck_reported_titles(self.db, sync.Client(self.db, 'fixture-not-a-key'), NOW, records)
            self.assertEqual(network.call_count, 1)

    def test_legacy_metadata_repair_cannot_bypass_a_full_run_with_oversized_environment_limit(self):
        metadata_spec = importlib.util.spec_from_file_location('budget_tmdb', Path(__file__).parents[1] / 'scripts/tmdb_enrich.py')
        metadata = importlib.util.module_from_spec(metadata_spec)
        metadata_spec.loader.exec_module(metadata)
        self.attempts(NOW - 1, 12)
        self.db.execute('INSERT INTO runs(at,status,requests,changed,message) VALUES (?,?,?,?,?)',
                        (NOW - 1, 'success', 12, 0, 'fixture completed run'))
        self.db.commit()
        database_path = Path(self.temp.name) / 'catalog.sqlite'
        report_path = Path(self.temp.name) / 'reports' / 'pilot.json'
        open_database = sync.open_db
        catalog = {'titles': [{'id': 'motn:7', 'title': 'Repair fixture'}]}
        with patch.dict(sys.modules, {'catalog_sync': sync}), \
                patch.dict(os.environ, {'RUN_REQUEST_LIMIT': '999', 'MONTHLY_REQUEST_LIMIT': '9999',
                                       'STREAMING_API_KEY': 'fixture-not-a-key'}, clear=True), \
                patch.object(sync, 'open_db', side_effect=lambda ignored: open_database(database_path)), \
                patch.object(metadata, 'Path', side_effect=lambda ignored: report_path), \
                patch.object(sync.time, 'time', return_value=NOW), \
                patch.object(sync, 'urlopen') as streaming_network, patch.object(metadata, 'urlopen') as metadata_network:
            self.assertEqual(metadata.repair_external_ids(catalog, 'motn:7', NOW), [])
            streaming_network.assert_not_called()
            metadata_network.assert_not_called()
        self.assertEqual(self.db.execute('SELECT requests FROM runs ORDER BY id DESC LIMIT 1').fetchone()[0], 12)
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0], 12)
        self.assertEqual(json.loads(report_path.read_text())['requestsThisMonth'], 12)


if __name__ == '__main__':
    unittest.main()
