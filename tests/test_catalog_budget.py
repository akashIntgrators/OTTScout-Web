"""Offline regression cases for continuous collection and reserved backfill quota."""
import importlib.util
import contextlib
import io
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
        registry = patch.object(sync, 'OFFICIAL_LISTINGS_PATH', Path(self.temp.name) / 'official-listings.json')
        registry.start()
        self.addCleanup(registry.stop)
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
        if parsed.path.endswith('/countries/in'):
            return Response({'countryCode':'in', 'services':[{'id':ident, 'name':name} for name,ident in self.mapping.items()]})
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

    def test_new_feed_precedes_pending_maintenance_without_losing_its_cursor(self):
        self.prepared_catalogue()
        sync.set_meta(self.db, 'watermark:new', NOW - 6 * 3600)
        sync.set_meta(self.db, 'change_window_v2:updated', {'from': NOW - 300, 'to': NOW - 100,
            'cursor': 'saved-update-cursor', 'seen': ['saved-update-cursor'], 'pages': 0, 'mapping': self.mapping})
        self.db.commit()
        self.run_sync(extra={'CATALOG_BACKFILL_PAGES': '0'})
        self.assertEqual([params['change_type'] for path, params in self.requests], ['new', 'updated'])
        self.assertEqual(self.requests[1][1]['cursor'], 'saved-update-cursor')
        self.assertEqual(self.requests[1][1]['to'], str(NOW - 100))
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

    def pending(self, kind, at=NOW, pages=13):
        state = {'from':at-2*sync.DAY, 'to':at-100, 'cursor':str(pages),
                 'seen':[str(pages)], 'pages':pages, 'mapping':dict(self.mapping)}
        sync.set_meta(self.db, 'change_window_v2:'+kind, state)
        self.db.commit()
        return state

    def test_due_new_feed_commits_before_a_more_than_twelve_page_maintenance_backlog(self):
        self.prepared_catalogue()
        sync.set_meta(self.db, 'watermark:new', NOW-sync.DAY)
        pending = self.pending('removed')
        requests = []
        def reply(request, **kwargs):
            params = {key:values[0] for key,values in parse_qs(urlparse(request.full_url).query).items()}
            requests.append(params)
            if params['change_type'] == 'new':
                item = {'id':'fresh', 'title':'Fresh title', 'showType':'movie', 'streamingOptions':{'in':[]}}
                return Response({'shows':{'fresh':item}, 'changes':[], 'hasMore':False})
            self.assertEqual(params['change_type'],'removed')
            return Response({'shows':{},'changes':[], 'hasMore':True,'nextCursor':str(int(params['cursor'])+1)})
        with patch.object(sync.time,'time',return_value=NOW), patch.object(sync,'urlopen',side_effect=reply):
            client = sync.Client(self.db,'fixture-not-a-key')
            with self.assertRaises(sync.BudgetReached):
                sync.sync(self.db,client,NOW)
        self.db.rollback()
        self.assertEqual((client.calls,requests[0]['change_type']),(12,'new'))
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW)
        self.assertIsNotNone(self.db.execute("SELECT id FROM titles WHERE id='motn:fresh'").fetchone())
        resumed = sync.get_meta(self.db,'change_window_v2:removed')
        self.assertEqual(resumed['pages'],pending['pages']+11)
        self.assertEqual((resumed['from'],resumed['to'],resumed['mapping']),(pending['from'],pending['to'],pending['mapping']))

    def test_conservation_defers_maintenance_and_all_old_imports_without_resetting_state(self):
        self.prepared_catalogue()
        self.attempts(NOW-1,369)
        for kind in ('new','updated','removed'):
            sync.set_meta(self.db,'watermark:'+kind,NOW-sync.DAY)
        maintenance = {kind:self.pending(kind) for kind in ('updated','removed')}
        older = {'cursor':'keep-old','pages':8,'complete':False}
        sync.set_meta(self.db,'catalog_backfill_v1:netflix:movie',older)
        sync.set_meta(self.db,'original_backfill_v1:te:movie',older)
        sync.set_meta(self.db,'coverage',{'mapping':self.mapping,'checkedAt':NOW-2*sync.DAY,'missing':[]})
        self.db.commit()
        client,_ = self.run_sync(extra={'ORIGINAL_LANGUAGE_BACKFILL_PAGES':'2'})
        self.assertEqual(client.calls,1)
        self.assertEqual([p['change_type'] for _,p in self.requests],['new'])
        for kind,state in maintenance.items():
            self.assertEqual(sync.get_meta(self.db,'change_window_v2:'+kind),state)
        self.assertEqual(sync.get_meta(self.db,'catalog_backfill_v1:netflix:movie'),older)
        self.assertEqual(sync.get_meta(self.db,'original_backfill_v1:te:movie'),older)
        self.assertEqual(sync.get_meta(self.db,'last_success'),NOW-sync.DAY)
        budget = sync.request_budget(self.db,NOW)
        self.assertEqual((budget['conservationMode'],budget['newFeedDailyLimit'],budget['newFeedRequestsToday']),(True,2,1))
        self.requests.clear()
        self.assertEqual(self.run_sync(NOW+6*3600)[0].calls,0,'A complete new feed is checked daily in conservation')

    def test_conservation_counts_real_new_attempts_across_restarts_and_resumes_next_utc_day(self):
        self.prepared_catalogue()
        self.attempts(NOW-1,369)
        sync.set_meta(self.db,'watermark:new',NOW-sync.DAY)
        self.db.commit()
        requested = []
        def reply(request, **kwargs):
            params = {key:values[0] for key,values in parse_qs(urlparse(request.full_url).query).items()}
            requested.append(params)
            page = int(params.get('cursor','0'))+1
            return Response({'shows':{},'changes':[],'hasMore':page<3,'nextCursor':str(page)})
        with patch.object(sync.time,'time',return_value=NOW), patch.object(sync,'urlopen',side_effect=reply):
            client=sync.Client(self.db,'fixture-not-a-key')
            with self.assertRaisesRegex(sync.BudgetReached,'next UTC day'):
                sync.sync(self.db,client,NOW)
        self.db.rollback()
        state=sync.get_meta(self.db,'change_window_v2:new')
        self.assertEqual((client.calls,state['pages'],state['cursor']),(2,2,'2'))
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW-sync.DAY)
        freshness=sync.streaming_freshness(self.db,NOW,True)['new']
        self.assertEqual(freshness['completedThrough'],sync.stamp(NOW-sync.DAY))
        self.assertEqual(freshness['pendingWindow']['pages'],2)
        self.assertFalse(freshness['checkDue'])
        self.assertTrue(freshness['deferredByConservation'])
        database=self.db.execute('PRAGMA database_list').fetchone()[2]
        self.db.close();self.db=sync.open_db(database)
        self.assertEqual(sync.new_feed_requests_today(self.db,NOW),2)
        client,_=self.run_sync(NOW+6*3600)
        self.assertEqual(client.calls,0,'Manual/scheduled repeat cannot spend another new-page allowance')
        tomorrow=NOW+sync.DAY
        with patch.object(sync.time,'time',return_value=tomorrow), patch.object(sync,'urlopen',side_effect=reply):
            self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),tomorrow),0)
        self.assertEqual(requested[-1]['cursor'],'2')
        self.assertEqual(int(requested[-1]['to']),state['to'],'A resumed query retains its frozen end')
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW)
        self.assertIsNone(sync.get_meta(self.db,'change_window_v2:new'))
        self.assertEqual(sync.new_feed_requests_today(self.db,tomorrow),1)
        self.assertEqual(sync.request_budget(self.db,tomorrow)['requestsUsed'],372)

    def test_conservation_failed_new_attempts_consume_the_daily_allowance_before_network(self):
        self.prepared_catalogue()
        self.attempts(NOW-1,369)
        class Malformed(Response):
            def read(self):return b'{'
        with patch.object(sync.time,'time',return_value=NOW), patch.object(sync,'urlopen',side_effect=[URLError('offline'),Malformed(None)]) as network:
            for _ in range(2):
                with self.assertRaises(sync.SyncError):
                    sync.Client(self.db,'fixture-not-a-key').get('/changes',{'change_type':'new'})
            with self.assertRaisesRegex(sync.BudgetReached,'next UTC day'):
                sync.Client(self.db,'fixture-not-a-key').get('/changes',{'change_type':'new'})
        self.assertEqual(network.call_count,2)
        self.assertEqual(sync.new_feed_requests_today(self.db,NOW),2)
        self.assertEqual(sync.request_budget(self.db,NOW)['requestsUsed'],371)

    def test_conservation_reuses_coverage_for_seven_days_then_refreshes_it_once(self):
        self.prepared_catalogue()
        self.attempts(NOW-1,369)
        sync.set_meta(self.db,'coverage',{'mapping':self.mapping,'checkedAt':NOW-6*sync.DAY,'missing':[]})
        self.db.commit()
        self.assertEqual(self.run_sync()[0].calls,0)
        sync.set_meta(self.db,'coverage',{'mapping':self.mapping,'checkedAt':NOW-7*sync.DAY,'missing':[]})
        self.db.commit()
        self.assertEqual(self.run_sync()[0].calls,1)
        self.assertEqual(self.requests[0][0],'/v4/countries/in')
        self.assertEqual(sync.get_meta(self.db,'coverage')['checkedAt'],NOW)

    def test_next_month_automatically_resumes_maintenance_with_old_cursors_and_request_history(self):
        self.prepared_catalogue()
        november=epoch('2026-11-30T20:00:00+00:00')
        december=epoch('2026-12-01T01:00:00+00:00')
        self.attempts(november,380)
        sync.set_meta(self.db,'coverage',{'mapping':self.mapping,'checkedAt':november,'missing':[]})
        for kind in ('new','updated','removed'):sync.set_meta(self.db,'watermark:'+kind,november)
        pending=self.pending('updated',november)
        sync.set_meta(self.db,'new_feed_attempts_v1',{'utcDay':november//sync.DAY,'attempts':2})
        self.db.commit()
        self.assertTrue(sync.request_budget(self.db,november)['conservationMode'])
        client,_=self.run_sync(december,{'CATALOG_BACKFILL_PAGES':'0'})
        self.assertFalse(sync.request_budget(self.db,december)['conservationMode'])
        self.assertEqual([p['change_type'] for _,p in self.requests],['new','updated','removed'])
        self.assertEqual(self.requests[1][1]['cursor'],pending['cursor'])
        self.assertEqual(int(self.requests[1][1]['to']),pending['to'])
        self.assertIsNone(sync.get_meta(self.db,'change_window_v2:updated'))
        self.assertEqual((client.calls,sync.request_budget(self.db,december)['requestsUsed']),(3,3))
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0],383,'Monthly accounting never deletes past requests')

    def test_conservation_run_exports_new_freshness_without_claiming_maintenance_is_current(self):
        self.prepared_catalogue()
        self.attempts(NOW-1,369)
        for kind in ('new','updated','removed'):sync.set_meta(self.db,'watermark:'+kind,NOW-sync.DAY)
        pending=self.pending('removed')
        self.db.commit()
        output=Path(self.temp.name)/'catalog.json';report=Path(self.temp.name)/'report.json'
        args=['catalog_sync.py','--db',str(Path(self.temp.name)/'catalog.sqlite'),'--export',str(output),'--report',str(report),'--allow-cached-on-limit']
        with patch.object(sys,'argv',args), patch.dict(os.environ,{'STREAMING_API_KEY':'fixture-not-a-key'},clear=True), \
             patch.object(sync.time,'time',return_value=NOW), patch.object(sync,'urlopen',side_effect=self.reply), \
             patch.object(sync,'recheck_reported_titles',return_value=0) as recheck, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(),0)
            recheck.assert_called_once()
        exported=json.loads(output.read_text());reported=json.loads(report.read_text())
        self.assertEqual(reported['runs'][-1]['status'],'limited')
        self.assertIn('Quota conservation',reported['runs'][-1]['message'])
        self.assertEqual(exported['updatedAt'],sync.stamp(NOW-sync.DAY))
        self.assertEqual(exported['streamingFreshness']['new']['completedThrough'],sync.stamp(NOW))
        self.assertTrue(exported['streamingFreshness']['removed']['deferredByConservation'])
        self.assertEqual(exported['streamingFreshness']['removed']['pendingWindow']['to'],sync.stamp(pending['to']))
        self.assertEqual(exported['streamingFreshness'],reported['streamingFreshness'])
        self.assertEqual((reported['newCheckHours'],reported['requestBudget']['newFeedRequestsToday']),(24,1))

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
        sync.set_meta(self.db, 'watermark:new', NOW-sync.DAY)
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

    def test_new_pages_and_failed_title_lookups_share_the_same_conservation_allowance(self):
        self.prepared_catalogue();self.attempts(NOW-1,369)
        with patch.object(sync.time,'time',return_value=NOW), patch.object(sync,'urlopen',side_effect=[Response({'shows':{},'changes':[],'hasMore':False}),URLError('fixture offline')]) as network:
            client=sync.Client(self.db,'fixture-not-a-key')
            client.get('/changes',{'change_type':'new'})
            with self.assertRaises(sync.SyncError):client.get('/shows/search/title',{'title':'Missing'})
            for endpoint,params in [('/changes',{'change_type':'new'}),('/shows/search/title',{'title':'Another'})]:
                with self.assertRaisesRegex(sync.BudgetReached,'next UTC day'):
                    sync.Client(self.db,'fixture-not-a-key').get(endpoint,params)
        self.assertEqual(network.call_count,2)
        self.assertEqual((sync.request_budget(self.db,NOW)['requestsUsed'],sync.new_feed_requests_today(self.db,NOW)),(371,2))

    def test_shared_allowance_migrates_existing_same_day_new_pages_and_title_ledger_attempts(self):
        self.prepared_catalogue();self.attempts(NOW-1,368)
        legacy={'utcDay':NOW//sync.DAY,'attempts':1}
        sync.set_meta(self.db,'new_feed_attempts_v1',legacy)
        self.db.execute('INSERT INTO requests(at,endpoint,status) VALUES (?,?,?)',(NOW,'/shows/search/title',503))
        self.db.commit()
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen') as network:
            self.assertEqual(sync.request_budget(self.db,NOW)['newFeedRequestsToday'],2)
            for endpoint,params in [('/changes',{'change_type':'new'}),('/shows/search/title',{'title':'Missing'})]:
                with self.assertRaisesRegex(sync.BudgetReached,'next UTC day'):
                    sync.Client(self.db,'fixture-not-a-key').get(endpoint,params)
            network.assert_not_called()
        self.assertEqual(sync.get_meta(self.db,'new_feed_attempts_v1'),legacy)
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0],369)

    def test_first_title_request_initializes_shared_counter_once_without_double_counting_its_ledger_row(self):
        self.prepared_catalogue();self.attempts(NOW-1,369)
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',return_value=Response([])) as network:
            sync.Client(self.db,'fixture-not-a-key').get('/shows/search/title',{'title':'Missing'})
            self.assertEqual(sync.new_feed_requests_today(self.db,NOW),1)
            self.assertEqual(sync.get_meta(self.db,'new_release_attempts_v2'),{'utcDay':NOW//sync.DAY,'attempts':1})
            sync.Client(self.db,'fixture-not-a-key').get('/changes',{'change_type':'new'})
            self.assertEqual(sync.new_feed_requests_today(self.db,NOW),2)
            with self.assertRaises(sync.BudgetReached):
                sync.Client(self.db,'fixture-not-a-key').get('/shows/search/title',{'title':'Another'})
        self.assertEqual(network.call_count,2)
        self.assertEqual(sync.request_budget(self.db,NOW)['requestsUsed'],371)

    def test_shared_counter_rolls_to_next_utc_day_without_recounting_yesterday_or_removing_history(self):
        self.prepared_catalogue();self.attempts(NOW-1,368)
        self.db.execute('INSERT INTO requests(at,endpoint,status) VALUES (?,?,?)',(NOW,'/shows/search/title',0))
        sync.set_meta(self.db,'new_feed_attempts_v1',{'utcDay':NOW//sync.DAY,'attempts':1})
        sync.set_meta(self.db,'new_release_attempts_v2',{'utcDay':NOW//sync.DAY,'attempts':2})
        self.db.commit()
        tomorrow=(NOW//sync.DAY+1)*sync.DAY
        self.assertEqual(sync.new_feed_requests_today(self.db,tomorrow),0)
        with patch.object(sync.time,'time',return_value=tomorrow),patch.object(sync,'urlopen',return_value=Response([])):
            sync.Client(self.db,'fixture-not-a-key').get('/shows/search/title',{'title':'Missing'})
        self.assertEqual(sync.new_feed_requests_today(self.db,tomorrow),1)
        self.assertEqual(sync.get_meta(self.db,'new_release_attempts_v2'),{'utcDay':tomorrow//sync.DAY,'attempts':1})
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0],370)

    def test_optional_malformed_lookup_keeps_completed_new_feed_and_runs_before_maintenance(self):
        self.prepared_catalogue();self.attempts(NOW-1,369)
        sync.set_meta(self.db,'watermark:new',NOW-sync.DAY);self.db.commit()
        records=[{'title':'Mr & Mrs Office','platform':'JioHotstar','showType':'series','platformTitleId':'1271718279',
                  'sourceURL':'https://www.hotstar.com/in/shows/mr-and-mrs-office/1271718279'}]
        calls=[]
        def reply(request,**kwargs):
            parsed=urlparse(request.full_url);params={key:values[0] for key,values in parse_qs(parsed.query).items()}
            calls.append((parsed.path,params))
            if parsed.path.endswith('/changes'):
                item={'id':'newest','title':'New title','showType':'movie','streamingOptions':{'in':[]}}
                return Response({'shows':{'newest':item},'changes':[],'hasMore':False})
            return Response({'invalid':'provider search response'})
        actual=sync.recheck_reported_titles
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',side_effect=reply), \
             patch.object(sync,'recheck_reported_titles',side_effect=lambda db,client,at:actual(db,client,at,records)):
            self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),NOW,recheck_reports=True),1)
        self.assertEqual([path for path,_ in calls],['/v4/changes','/v4/shows/search/title'])
        self.assertEqual(calls[0][1]['change_type'],'new')
        self.assertEqual(calls[1][1]['show_type'],'series')
        self.assertIsNotNone(self.db.execute("SELECT id FROM titles WHERE id='motn:newest'").fetchone())
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW)
        self.assertEqual(sync.get_meta(self.db,'title_recheck:hotstar:1271718279')['status'],'lookup_failed')
        self.assertEqual(sync.new_feed_requests_today(self.db,NOW),2)

    def test_new_feed_uses_run_budget_before_a_reported_lookup_and_blocked_report_does_not_claim_attempt(self):
        self.prepared_catalogue();self.attempts(NOW-1,369)
        sync.set_meta(self.db,'watermark:new',NOW-sync.DAY);self.db.commit()
        records=[{'title':'Fixture','netflixId':'123'}]
        actual=sync.recheck_reported_titles
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',side_effect=self.reply), \
             patch.object(sync,'recheck_reported_titles',side_effect=lambda db,client,at:actual(db,client,at,records)):
            with self.assertRaises(sync.BudgetReached):
                sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key',run_limit=1),NOW,recheck_reports=True)
        self.assertEqual(len(self.requests),1)
        self.assertEqual(self.requests[0][1]['change_type'],'new')
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW)
        self.assertIsNone(sync.get_meta(self.db,'title_recheck_last_attempt'))

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
