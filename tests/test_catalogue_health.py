"""Offline freshness evidence tests: an empty API result is not a failed update."""
from copy import deepcopy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('catalogue_health', Path(__file__).parents[1] / 'scripts/catalogue_health.py')
health = importlib.util.module_from_spec(spec)
spec.loader.exec_module(health)
NOW = 1795190400
HOUR = 3600


def fixtures():
    feed = {'completedThrough': health.iso(NOW - 60), 'pendingWindow': None}
    budget = {'monthlyLimit': 400, 'requestsUsed': 50, 'requestsRemaining': 350, 'freshnessReserve': 100,
              'newFeedDailyLimit': 4, 'newFeedRequestsToday': 1, 'newFeedRequestsRemainingToday': 3}
    report = {'streamingFreshness': {'new': feed}, 'requestBudget': budget,
              'runs': [{'at': health.iso(NOW - 60), 'status': 'success', 'requests': 1}],
              'catalogBackfill': {'complete': False, 'completedTasks': 0, 'totalTasks': 10}}
    catalogue = {'schemaVersion': 1, 'mode': 'live', 'updatedAt': '2026-11-13T07:02:34+00:00',
                 'titles': [{'id': 'motn:123', 'title': 'An old title', 'year': 1990, 'weeklyEvents': [],
                             'offers': [{'platform': 'Netflix', 'link': 'https://www.netflix.com/in/title/81749470'}]}],
                 'coverage': ['Netflix', 'SonyLIV'], 'missingPlatforms': ['Sun NXT', 'aha'],
                 'streamingFreshness': deepcopy(report['streamingFreshness']), 'requestBudget': deepcopy(budget)}
    sources = [{'id': ident, 'platform': 'SonyLIV', 'required': True, 'lastAttemptAt': NOW - 60,
                'lastSuccessAt': NOW - 60, 'status': 'ok', 'candidates': 0, 'confirmed': 0,
                'gaps': 0, 'errors': [], 'unverifiedCandidates': []} for ident in ('sony-movies', 'sony-series')]
    discovery = {'schemaVersion': 1, 'evaluatedAt': NOW - 60, 'sources': sources,
                 'requiredSources': ['sony-movies', 'sony-series'], 'expectedVerifiedRecent': []}
    return report, catalogue, discovery


def expected(**patch):
    return {'id': 'motn:official-netflix-81749470', 'platform': 'Netflix', 'platformTitleId': '81749470',
            'releaseDate': '2026-11-18', 'verifiedAt': NOW - HOUR, 'expiresAt': NOW + 29 * 86400, **patch}


def signals(result):
    return {c['code']: c['severity'] for c in result['causes']}


class CatalogueHealthTests(unittest.TestCase):
    def evaluate(self, values=None, **kwargs):
        report, catalogue, discovery = values or fixtures()
        return health.evaluate_health(report, catalogue, discovery, now=NOW, **kwargs)

    def test_explicit_permission_pause_is_a_coverage_warning_without_renewing_checks(self):
        values = fixtures()
        values[2]['requiredSources'] = []
        for source in values[2]['sources']:
            source.update(required=False, status='paused', pauseReason='permission-required', lastAttemptAt=None, lastSuccessAt=None)
        result, _ = self.evaluate(values)
        self.assertEqual(result['status'], 'warning')
        self.assertEqual(signals(result), {'official_discovery_permission_paused': 'warning'})
        self.assertEqual(result['officialDiscovery']['requiredSources'], [])
        previous = health.discovery_from_health(result)
        repeated, _ = health.evaluate_health(values[0], values[1], previous, now=NOW + 60)
        self.assertEqual(repeated['officialDiscovery']['sources'], result['officialDiscovery']['sources'])
        self.assertIsNone(repeated['officialDiscovery']['sources'][0]['lastAttemptAt'])
        values[2]['sources'][0]['pauseReason'] = 'anything-else'
        self.assertIn('official_required_sources_unknown', signals(self.evaluate(values)[0]))

    def test_newest_first_partial_page_never_advances_full_completion(self):
        values = fixtures()
        values[0]['streamingFreshness']['new']['completedThrough'] = health.iso(NOW - 30 * HOUR)
        latest = {'checkedAt': health.iso(NOW - 60), 'from': health.iso(NOW - 48 * HOUR - 60),
                  'to': health.iso(NOW - 60), 'oldestEventAt': health.iso(NOW - HOUR),
                  'newestEventAt': health.iso(NOW - 100), 'hasMore': True, 'events': 25,
                  'order': 'desc', 'pages': 1, 'scope': 'last48h'}
        values[0]['latestNewCheck'] = latest
        result, _ = self.evaluate(values)
        self.assertEqual(result['newFeed']['latestNewCheck'], latest)
        self.assertEqual(result['newFeed']['completedThrough'], health.iso(NOW - 30 * HOUR))
        self.assertEqual(signals(result)['new_feed_stale'], 'critical')
        self.assertEqual(signals(result)['newest_page_incomplete'], 'warning')
        self.assertNotIn('newest_check_stale', signals(result))
        for patch in [{'checkedAt': health.iso(NOW + 1)}, {'order': 'asc'}, {'pages': True}, {'events': -1}, {'events': 26},
                      {'from': health.iso(NOW - 47 * HOUR - 60)}, {'checkedAt': health.iso(NOW)},
                      {'from': health.iso(NOW - 120 * HOUR), 'to': health.iso(NOW - 72 * HOUR)},
                      {'oldestEventAt': health.iso(NOW - 50 * HOUR)}, {'hasMore': 'false'}]:
            with self.subTest(patch=patch):
                values[0]['latestNewCheck'] = {**latest, **patch}
                self.assertIn('newest_check_invalid', signals(self.evaluate(values)[0]))

    def test_empty_newest_page_and_independent_monitor_preserve_observation_time(self):
        values = fixtures()
        latest = {'checkedAt': health.iso(NOW - 60), 'from': health.iso(NOW - 48 * HOUR - 60),
                  'to': health.iso(NOW - 60), 'oldestEventAt': None, 'newestEventAt': None,
                  'hasMore': False, 'events': 0, 'order': 'desc', 'pages': 1, 'scope': 'last48h'}
        values[1]['latestNewCheck'] = latest
        result, _ = health.evaluate_health(catalogue=values[1], discovery=values[2], now=NOW)
        self.assertEqual(result['newFeed']['latestNewCheck'], latest)
        self.assertNotIn('newest_check_invalid', signals(result))

    def test_fresh_empty_new_feed_is_healthy_despite_old_title_dates_and_partial_coverage(self):
        result, _ = self.evaluate()
        self.assertEqual(result['status'], 'normal')
        self.assertEqual(result['causes'], [])
        self.assertTrue(result['coverage']['partial'])
        self.assertFalse(result['coverage']['backfillComplete'])
        self.assertEqual(result['coverage']['unsupported'], ['Sun NXT', 'aha'])

    def test_completion_age_boundaries_not_latest_attempt_or_title_dates_decide_freshness(self):
        for age, severity in [(12 * HOUR, None), (12 * HOUR + 1, 'warning'), (24 * HOUR, 'warning'), (24 * HOUR + 1, 'critical')]:
            report, cat, discovery = fixtures()
            report['streamingFreshness']['new']['completedThrough'] = health.iso(NOW - age)
            cat['titles'][0]['weeklyEvents'] = [{'addedAt': NOW}]
            report['runs'][-1]['at'] = health.iso(NOW)
            with self.subTest(age=age):
                result, _ = self.evaluate((report, cat, discovery))
                self.assertEqual(signals(result).get('new_feed_stale'), severity)

    def test_missing_future_or_malformed_watermark_never_looks_healthy(self):
        for value in [None, 'not a date', health.iso(NOW + 1), '2026-11-20T12:00:00']:
            values = fixtures(); values[0]['streamingFreshness']['new']['completedThrough'] = value
            self.assertEqual(self.evaluate(values)[0]['status'], 'critical')
        self.assertEqual(health.evaluate_health(now=NOW)[0]['status'], 'critical')

    def test_pending_window_age_is_reported_and_stale_maintenance_is_qualified(self):
        values = fixtures()
        values[0]['streamingFreshness']['new']['pendingWindow'] = {'from': health.iso(NOW - 25 * HOUR), 'to': health.iso(NOW - HOUR), 'pages': 2}
        values[0]['streamingFreshness']['removed'] = {'pendingWindow': {'from': health.iso(NOW - 7 * 86400), 'to': health.iso(NOW - 86400), 'pages': 5}}
        result, _ = self.evaluate(values)
        self.assertEqual(signals(result)['new_feed_pending_old'], 'critical')
        self.assertEqual(result['pendingFeeds']['new']['pages'], 2)
        self.assertEqual(signals(result)['maintenance_pending_old:removed'], 'warning')

    def test_bad_pagination_is_unknown_not_an_empty_success(self):
        for pending in [{}, {'from': NOW, 'to': NOW - 1, 'pages': 0}, {'from': NOW - 1, 'to': NOW, 'pages': True}]:
            values = fixtures(); values[0]['streamingFreshness']['new']['pendingWindow'] = pending
            self.assertIn('new_feed_pending_unknown', signals(self.evaluate(values)[0]))

    def test_incremental_published_pages_are_progress_without_a_fake_complete_watermark(self):
        values = fixtures(); report = values[0]
        report['streamingFreshness']['new']['completedThrough'] = health.iso(NOW - 48 * HOUR)
        report['streamingFreshness']['new']['pendingWindow'] = {'from': health.iso(NOW - 48 * HOUR), 'to': health.iso(NOW - HOUR), 'pages': 2}
        report['newPublication'] = {'pages': 2, 'latestPublishedAt': NOW - 10}
        prior = {'schemaVersion': 1, 'newFeed': {'completedThrough': NOW - 48 * HOUR,
                 'pendingWindow': {**report['streamingFreshness']['new']['pendingWindow'], 'pages': 1},
                 'firstObservedAt': NOW - 48 * HOUR, 'lastProgressAt': NOW - 36 * HOUR, 'publishedPages': 1}}
        original = deepcopy(report)
        result, saved = self.evaluate(values, previous=prior)
        self.assertEqual(report, original)
        self.assertTrue(result['newFeed']['progressObservedThisCheck'])
        self.assertEqual(saved['newFeed']['lastProgressAt'], NOW)
        self.assertNotIn('new_feed_stalled', signals(result))
        self.assertEqual(result['newFeed']['completedThrough'], health.iso(NOW - 48 * HOUR))
        self.assertEqual(signals(result)['new_feed_stale'], 'critical')

    def test_no_progress_and_watermark_regression_are_visible(self):
        values = fixtures(); pending = {'from': health.iso(NOW - 30 * HOUR), 'to': health.iso(NOW - HOUR), 'pages': 2}
        values[0]['streamingFreshness']['new']['pendingWindow'] = pending
        prior = {'schemaVersion': 1, 'newFeed': {'completedThrough': NOW - 30, 'pendingWindow': pending,
                 'firstObservedAt': NOW - 30 * HOUR, 'lastProgressAt': NOW - 25 * HOUR}}
        result, saved = self.evaluate(values, previous=prior)
        self.assertIn('new_feed_regressed', signals(result))
        self.assertEqual(signals(result)['new_feed_stalled'], 'critical')
        self.assertEqual(saved['newFeed']['completedThrough'], NOW - 30)

    def test_corrupt_progress_state_cannot_create_green_or_poison_future_progress(self):
        for state in [[], {'schemaVersion': 2}, {'schemaVersion': 1, 'newFeed': {}},
                      {'schemaVersion': 1, 'newFeed': {'completedThrough': NOW + HOUR, 'pendingWindow': None,
                       'firstObservedAt': NOW + HOUR, 'lastProgressAt': NOW + HOUR}}]:
            result, saved = self.evaluate(previous=state)
            self.assertIn('health_state_invalid', signals(result))
            self.assertLessEqual(saved['newFeed']['completedThrough'], NOW)

    def test_heartbeat_uses_actual_workflow_execution_and_detects_failure_and_old_queue(self):
        rows = [{'status': 'completed', 'conclusion': 'success', 'createdAt': health.iso(NOW - 25 * HOUR)},
                {'status': 'queued', 'createdAt': health.iso(NOW - 13 * HOUR)}]
        result, _ = self.evaluate(workflow_runs=rows)
        self.assertEqual(signals(result)['collector_heartbeat_stale'], 'critical')
        self.assertEqual(signals(result)['collector_workflow_queued'], 'warning')
        self.assertEqual(result['heartbeat']['lastRunAt'], health.iso(NOW - 25 * HOUR))
        rows = [{'status': 'completed', 'conclusion': 'failure', 'createdAt': health.iso(NOW - 60),
                 'url': 'https://github.com/akashIntgrators/OTTScout-Web/actions/runs/123'}]
        result, _ = self.evaluate(workflow_runs={'workflow_runs': rows})
        self.assertEqual(signals(result)['collector_workflow_failed'], 'critical')
        self.assertTrue(result['heartbeat']['url'].endswith('/123'))
        self.assertIn('collector_heartbeat_unknown', signals(self.evaluate(workflow_runs=[])[0]))

    def test_in_progress_heartbeat_does_not_hide_the_last_completed_workflow_failure(self):
        rows = [{'status': 'completed', 'conclusion': 'failure', 'createdAt': health.iso(NOW - HOUR)},
                {'status': 'in_progress', 'createdAt': health.iso(NOW - 10)}]
        result, _ = self.evaluate(workflow_runs=rows)
        self.assertEqual(result['heartbeat']['status'], 'in_progress')
        self.assertEqual(signals(result)['collector_workflow_failed'], 'critical')

    def test_unknown_workflow_outcome_and_invalid_source_ids_cannot_be_green_or_leak_input(self):
        result, _ = self.evaluate(workflow_runs=[{'status': 'completed', 'conclusion': None, 'createdAt': health.iso(NOW - 10)}])
        self.assertIn('collector_workflow_unknown', signals(result))
        values = fixtures(); values[2].pop('requiredSources')
        values[2]['sources'][0]['id'] = 'private-token@example.test'
        result, _ = self.evaluate(values)
        self.assertEqual(result['status'], 'critical')
        self.assertNotIn('private-token@example.test', json.dumps(result))

    def test_missing_private_pilot_can_use_public_metadata_and_workflow_heartbeat(self):
        _, cat, discovery = fixtures()
        rows = [{'status': 'in_progress', 'createdAt': health.iso(NOW - 60)}]
        result, _ = health.evaluate_health(catalogue=cat, discovery=discovery, workflow_runs=rows, now=NOW)
        self.assertEqual(result['status'], 'normal')

    def test_failed_attempt_and_request_limits_do_not_hide_freshness(self):
        values = fixtures(); values[0]['runs'][-1]['status'] = 'failed'
        self.assertIn('collector_attempt_failed', signals(self.evaluate(values)[0]))
        for used, limit, remaining, code in [(400, 400, 0, 'request_budget_exhausted'),
                                            (401, 400, 0, 'request_budget_exceeded'),
                                            (0, 9999, 9999, 'request_budget_unknown'),
                                            (380, 400, 20, 'request_budget_low'),
                                            (50, 400, 12, 'request_budget_unknown')]:
            values = fixtures(); values[0]['requestBudget'].update(monthlyLimit=limit, requestsUsed=used, requestsRemaining=remaining)
            self.assertIn(code, signals(self.evaluate(values)[0]))

    def test_pending_daily_cap_and_protected_reserve_are_reported_without_requesting_anything(self):
        values = fixtures(); values[0]['requestBudget'].update(requestsUsed=374, requestsRemaining=26, newFeedRequestsRemainingToday=0)
        values[0]['streamingFreshness']['new']['pendingWindow'] = {'from': NOW - HOUR, 'to': NOW - 60, 'pages': 2}
        result, _ = self.evaluate(values)
        self.assertIn('request_budget_below_reserve', signals(result))
        self.assertIn('new_feed_daily_budget_exhausted', signals(result))

    def test_required_source_failures_and_unverified_candidates_cannot_be_green(self):
        values = fixtures(); source = values[2]['sources'][0]
        source.update(lastSuccessAt=NOW - 13 * HOUR, status='blocked', errors=[{'code': 'robots-blocked', 'message': 'ignored secret text'}])
        result, _ = self.evaluate(values)
        self.assertEqual(signals(result)['official_source_failed:sony-movies'], 'critical')
        self.assertNotIn('ignored secret text', json.dumps(result))
        values = fixtures(); values[2]['sources'][0].update(status='partial', gaps=1, unverifiedCandidates=[{'title': 'Not confirmed'}])
        self.assertIn('official_verification_pending:sony-movies', signals(self.evaluate(values)[0]))

    def test_source_flag_conflicts_and_safe_reason_counts_survive_watchdog_reuse(self):
        values = fixtures(); values[2]['sources'][0].update(status='partial', gaps=2,
            unverifiedCandidates=[{'title': 'Do not publish', 'reason': 'source-flag-conflict'},
                                  {'title': 'Do not copy', 'reason': 'availability-unverified'}])
        first, _ = self.evaluate(values)
        self.assertIn('official_source_flag_conflict:sony-movies', signals(first))
        self.assertEqual(first['officialDiscovery']['sourceFlagConflicts'], 1)
        self.assertEqual(first['officialDiscovery']['sources'][0]['unverifiedReasons']['availability-unverified'], 1)
        self.assertNotIn('Do not publish', json.dumps(first))
        reused = health.discovery_from_health(first)
        second, _ = health.evaluate_health(values[0], values[1], reused, now=NOW + 60)
        self.assertEqual(second['officialDiscovery']['sourceFlagConflicts'], 1)
        self.assertEqual(second['officialDiscovery']['sources'][0]['lastSuccessAt'], first['officialDiscovery']['sources'][0]['lastSuccessAt'])

    def test_optional_netflix_block_and_unsupported_platforms_are_coverage_information(self):
        values = fixtures(); values[2]['sources'].append({'id': 'netflix-tudum', 'platform': 'Netflix', 'required': False,
                    'lastAttemptAt': NOW, 'lastSuccessAt': None, 'status': 'blocked', 'errors': [{'code': 'robots-blocked'}],
                    'unverifiedCandidates': [], 'gaps': 0})
        result, _ = self.evaluate(values)
        self.assertEqual(result['status'], 'normal')
        self.assertEqual(result['officialDiscovery']['sources'][-1]['status'], 'blocked')

    def test_only_optional_sources_cannot_claim_a_healthy_active_discovery_service(self):
        values = fixtures(); values[2]['requiredSources'] = []
        values[2]['sources'] = [{'id': 'netflix-tudum', 'required': False, 'status': 'blocked', 'lastSuccessAt': None}]
        self.assertIn('official_required_sources_unknown', signals(self.evaluate(values)[0]))

    def test_missing_required_source_and_missing_discovery_never_recover_as_healthy(self):
        values = fixtures(); values[2]['sources'].pop()
        self.assertIn('official_source_missing:sony-series', signals(self.evaluate(values)[0]))
        self.assertIn('official_discovery_unknown', signals(health.evaluate_health(fixtures()[0], fixtures()[1], now=NOW)[0]))

    def test_expected_exact_identity_matches_numeric_provider_id_and_detects_real_absence(self):
        values = fixtures(); values[2]['expectedVerifiedRecent'] = [expected()]
        result, _ = self.evaluate(values)
        self.assertEqual(result['status'], 'normal', 'Different internal canonical ID is not a missing title')
        self.assertEqual(result['publication']['expectedVerifiedRecent'], 1)
        values[1]['titles'][0]['offers'][0]['link'] = 'https://www.netflix.com/in/title/817494700?reference=81749470'
        result, _ = self.evaluate(values)
        self.assertIn('verified_official_missing', signals(result))
        self.assertEqual(result['publication']['missingExpected'][0]['platformTitleId'], '81749470')

    def test_sony_movie_uses_exact_full_movie_id_while_series_episodes_keep_parent_id(self):
        self.assertEqual(health.exact_identity('https://www.sonyliv.com/movies/a-film-1090551234?watch=true', 'SonyLIV'), '1090551234')
        self.assertEqual(health.exact_identity('https://www.sonyliv.com/shows/a-show-1790007924/an-episode-1090554840?watch=true', 'SonyLIV'), '1790007924')
        self.assertIsNone(health.exact_identity('https://www.sonyliv.com/movies/a-bundle-1599999999/full-film-1090551234', 'SonyLIV'))

    def test_exact_but_expired_future_or_evidence_expired_offers_do_not_satisfy_publication(self):
        for inactive in [{'expiresOn': NOW - 1}, {'availableSince': NOW + 86400}, {'evidenceExpiresAt': NOW}, {'expiresOn': 'invalid'}]:
            values = fixtures(); values[2]['expectedVerifiedRecent'] = [expected()]
            values[1]['titles'][0]['offers'][0].update(inactive)
            self.assertIn('verified_official_missing', signals(self.evaluate(values)[0]))
        values = fixtures(); values[2]['expectedVerifiedRecent'] = [expected()]
        values[1]['titles'][0]['offers'][0]['expiresOn'] = 253368115140
        self.assertNotIn('verified_official_missing', signals(self.evaluate(values)[0]), 'An open-ended far-future provider sentinel remains current')

    def test_reduced_future_capacity_is_explicit_in_public_budget_and_health(self):
        values = fixtures(); values[0]['requestBudget'].update(capacityInsufficient=True, plannedPerFutureDay=1,
            protectedFutureDailyTarget=2, protectedFutureRequests=12, protectedFutureDays=10, emergencyReserve=2)
        result, _ = self.evaluate(values)
        self.assertTrue(result['requestBudget']['capacityInsufficient'])
        self.assertEqual(result['requestBudget']['protectedFutureRequests'], 12)
        self.assertIn('freshness_capacity_insufficient', signals(result))

    def test_expired_and_future_official_records_do_not_claim_current_missing_offers(self):
        values = fixtures(); values[2]['expectedVerifiedRecent'] = [expected(expiresAt=NOW - 1, verifiedAt=NOW - 2 * HOUR)]
        values[1]['titles'][0]['offers'] = []
        self.assertEqual(self.evaluate(values)[0]['publication']['expectedVerifiedRecent'], 0)
        values[2]['expectedVerifiedRecent'] = [expected(releaseDate='2026-12-01')]
        self.assertEqual(self.evaluate(values)[0]['publication']['expectedVerifiedRecent'], 0)

    def test_previous_public_health_reuses_discovery_without_renewing_evidence(self):
        values = fixtures(); values[2]['expectedVerifiedRecent'] = [expected()]
        first, _ = self.evaluate(values)
        reused = health.discovery_from_health(first)
        second, _ = health.evaluate_health(values[0], values[1], reused, now=NOW + 13 * HOUR)
        self.assertEqual(second['officialDiscovery']['evaluatedAt'], first['officialDiscovery']['evaluatedAt'])
        self.assertEqual(second['officialDiscovery']['sources'][0]['lastSuccessAt'], first['officialDiscovery']['sources'][0]['lastSuccessAt'])
        self.assertEqual(second['officialDiscovery']['expectedVerifiedRecent'][0]['expiresAt'], expected()['expiresAt'])
        self.assertIn('official_source_stale:sony-movies', signals(second))

    def test_threshold_and_clock_configuration_fail_safely(self):
        for limits in [{'warningHours': 0}, {'criticalHours': 12}, {'budgetLow': -1}, {'extra': 1}, {'warningHours': True}]:
            with self.assertRaises(ValueError):
                self.evaluate(thresholds=limits)
        with self.assertRaises(ValueError):
            health.evaluate_health(now=True)

    def test_step_failures_are_critical_without_publishing_raw_error_text(self):
        result, _ = self.evaluate(input_errors=['official_overlay_failed', 'collector_step_failed'])
        self.assertEqual(signals(result)['official_overlay_failed'], 'critical')
        self.assertEqual(signals(result)['collector_step_failed'], 'critical')
        self.assertIn('health_input_error_invalid', signals(self.evaluate(input_errors=['secret@example.test'])[0]))

    def test_cli_writes_critical_report_and_state_before_optional_failure_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); out = root / 'health.json'; public = root / 'public.json'; state = root / 'state.json'
            with contextlib.redirect_stdout(io.StringIO()):
                status = health.main(['--report', str(root / 'missing-pilot'), '--catalog', str(root / 'missing-catalog'),
                    '--discovery-report', str(root / 'missing-discovery'), '--state', str(state), '--out', str(out),
                    '--public-out', str(public), '--now', str(NOW), '--fail-on-critical'])
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(out.read_text())['status'], 'critical')
            self.assertEqual(json.loads(public.read_text()), json.loads(out.read_text()))
            self.assertTrue(state.exists())
