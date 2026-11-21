"""Issue alerts are exercised through an in-memory adapter, never live GitHub."""
from copy import deepcopy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('health_notifications', Path(__file__).parents[1] / 'scripts/notify_catalogue_health.py')
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)
NOW = 1795190400
REPO = 'akashIntgrators/OTTScout-Web'


def report(status='warning', codes=None, now=NOW):
    codes = ([] if status == 'normal' else ['new_feed_stale']) if codes is None else codes
    return {'schemaVersion': 1, 'evaluatedAt': now, 'status': status,
            'causes': [{'code': code, 'severity': status, 'message': 'Raw message must not be copied @everyone SECRET'} for code in codes],
            'newFeed': {'completedThrough': notify.iso(now - 60)},
            'officialDiscovery': {'sources': [{'id': 'sony-series', 'required': True, 'status': 'ok', 'lastSuccessAt': notify.iso(now - 60)},
                                             {'id': 'netflix-tudum', 'required': False, 'status': 'blocked', 'lastSuccessAt': None}],
                                  'missingRequiredSources': []},
            'publication': {'catalogueAvailable': True, 'missingExpected': []},
            'heartbeat': {'lastRunAt': notify.iso(now - 60), 'url': 'https://github.com/' + REPO + '/actions/runs/123'},
            'requestBudget': {'monthlyLimit': 400, 'requestsUsed': 374, 'requestsRemaining': 26}}


class Issues:
    def __init__(self):
        self.rows = {}; self.mutations = []; self.reads = []; self.next_number = 10

    def list_open(self):
        self.reads.append('list')
        return [deepcopy(row) for row in self.rows.values() if row['state'] == 'open']

    def get(self, number):
        self.reads.append(('get', number))
        return deepcopy(self.rows.get(number))

    def create(self, title, body):
        number = self.next_number; self.next_number += 1
        row = {'number': number, 'title': title, 'body': body, 'state': 'open',
               'user': {'login': notify.BOT}, 'created_at': notify.iso(NOW)}
        self.rows[number] = row; self.mutations.append(('create', number, deepcopy(row)))
        return deepcopy(row)

    def update(self, number, payload):
        self.rows[number].update(deepcopy(payload))
        self.mutations.append(('update', number, deepcopy(payload)))


class HealthNotificationTests(unittest.TestCase):
    def test_incident_explains_only_allowlisted_sony_region_diagnostics(self):
        value=report('critical', ['official_source_unknown:sony-series'])
        value['officialDiscovery']['sources'][0].update(status='error',regionEvidence='not-exact-india')
        value['officialDiscovery']['sources'].append({'id':'sony-movies','status':'error','regionEvidence':'missing-or-malformed'})
        value['officialDiscovery']['sources'].append({'id':'@everyone','status':'error','regionEvidence':'not-exact-india'})
        value['officialDiscovery']['sources'].append({'id':'sony-series','status':'error','regionEvidence':'SECRET'})
        api=Issues(); state,_=notify.reconcile_health(value,None,api,REPO,NOW)
        body=api.rows[state['incident']['number']]['body']
        self.assertIn('SonyLIV series: the returned region did not exactly identify India.',body)
        self.assertIn('SonyLIV movies: the returned region was missing or malformed.',body)
        self.assertNotIn('@everyone',body); self.assertNotIn('SECRET',body)
        self.assertEqual(state['incident']['fingerprint'],notify.fingerprint(value['causes']))

    def test_warning_creates_one_managed_issue_and_same_signal_does_not_churn(self):
        api = Issues()
        state, action = notify.reconcile_health(report(), None, api, REPO, NOW, mention='akashIntgrators')
        self.assertEqual(action, 'created')
        self.assertEqual(len(api.mutations), 1)
        body = api.rows[state['incident']['number']]['body']
        self.assertIn(notify.MARKER, body); self.assertIn(notify.STATUS_URL, body)
        self.assertNotIn('@akashIntgrators', body)
        self.assertNotIn('SECRET', body); self.assertNotIn('@everyone', body)
        again, action = notify.reconcile_health(report(now=NOW + 24 * 3600), state, api, REPO, NOW + 24 * 3600)
        self.assertEqual(action, 'unchanged'); self.assertEqual(again, state)
        self.assertEqual(len(api.mutations), 1)

    def test_initial_critical_mentions_owner_once_and_later_changes_do_not_repeat_it(self):
        api = Issues(); state, _ = notify.reconcile_health(report('critical'), None, api, REPO, NOW, mention='akashIntgrators')
        number = state['incident']['number']
        self.assertIn('@akashIntgrators', api.rows[number]['body'])
        state, action = notify.reconcile_health(report('critical', ['verified_official_missing'], NOW + 12 * 3600), state, api, REPO, NOW + 12 * 3600, mention='akashIntgrators')
        self.assertEqual(action, 'updated'); self.assertNotIn('@akashIntgrators', api.rows[number]['body'])
        self.assertTrue(state['incident']['criticalMentioned'])

    def test_first_critical_escalation_bypasses_throttle_and_mentions_only_once(self):
        api = Issues(); state, _ = notify.reconcile_health(report(), None, api, REPO, NOW, mention='akashIntgrators')
        state, action = notify.reconcile_health(report('critical', now=NOW + 60), state, api, REPO, NOW + 60, mention='akashIntgrators')
        self.assertEqual(action, 'updated'); self.assertIn('@akashIntgrators', api.rows[state['incident']['number']]['body'])
        state, _ = notify.reconcile_health(report(now=NOW + 120), state, api, REPO, NOW + 120, mention='akashIntgrators')
        state, _ = notify.reconcile_health(report('critical', now=NOW + 180), state, api, REPO, NOW + 180, mention='akashIntgrators')
        self.assertNotIn('@akashIntgrators', api.rows[state['incident']['number']]['body'])

    def test_changed_causes_stay_on_same_incident_and_wait_twelve_hours(self):
        api = Issues(); state, _ = notify.reconcile_health(report(), None, api, REPO, NOW)
        initial = deepcopy(state)
        state, action = notify.reconcile_health(report(codes=['official_verification_pending:sony-series'], now=NOW + 6 * 3600), state, api, REPO, NOW + 6 * 3600)
        self.assertEqual(action, 'unchanged'); self.assertEqual(state, initial)
        state, action = notify.reconcile_health(report(codes=['official_verification_pending:sony-series'], now=NOW + 12 * 3600), state, api, REPO, NOW + 12 * 3600)
        self.assertEqual(action, 'updated'); self.assertEqual(len(api.rows), 1)
        self.assertEqual(state['incident']['number'], initial['incident']['number'])

    def test_only_complete_recovery_closes_once_then_new_incident_can_open(self):
        api = Issues(); state, _ = notify.reconcile_health(report('critical'), None, api, REPO, NOW)
        number = state['incident']['number']
        still = report('warning', ['official_source_failed:sony-series'], NOW + 60)
        state, _ = notify.reconcile_health(still, state, api, REPO, NOW + 60)
        self.assertEqual(api.rows[number]['state'], 'open')
        state, action = notify.reconcile_health(report('normal', now=NOW + 120), state, api, REPO, NOW + 120)
        self.assertEqual(action, 'recovered'); self.assertFalse(state['incident']['active'])
        self.assertEqual(api.rows[number]['state'], 'closed')
        count = len(api.mutations)
        state, action = notify.reconcile_health(report('normal', now=NOW + 180), state, api, REPO, NOW + 180)
        self.assertEqual(action, 'healthy'); self.assertEqual(len(api.mutations), count)
        state, action = notify.reconcile_health(report(now=NOW + 240), state, api, REPO, NOW + 240)
        self.assertEqual(action, 'created'); self.assertNotEqual(state['incident']['number'], number)

    def test_missing_or_stale_discovery_cannot_close_an_existing_issue(self):
        api = Issues(); state, _ = notify.reconcile_health(report(), None, api, REPO, NOW)
        bad = report('normal'); bad.pop('officialDiscovery')
        with self.assertRaises(notify.NotificationError):
            notify.reconcile_health(bad, state, api, REPO, NOW)
        self.assertEqual(api.rows[state['incident']['number']]['state'], 'open')
        stale = report('normal')
        state, action = notify.reconcile_health(stale, state, api, REPO, NOW + 13 * 3600)
        self.assertEqual(action, 'updated'); self.assertEqual(state['incident']['level'], 'critical')
        self.assertIn('health_report_stale', api.rows[state['incident']['number']]['body'])

    def test_lost_local_state_adopts_existing_bot_issue_without_duplicate_or_edit(self):
        api = Issues(); state, _ = notify.reconcile_health(report('critical'), None, api, REPO, NOW, mention='akashIntgrators')
        adopted, action = notify.reconcile_health(report('critical', now=NOW + 60), None, api, REPO, NOW + 60, mention='akashIntgrators')
        self.assertEqual(action, 'unchanged'); self.assertEqual(adopted['incident']['number'], state['incident']['number'])
        self.assertTrue(adopted['incident']['criticalMentioned']); self.assertEqual(len(api.mutations), 1)

    def test_state_loss_while_healthy_recovers_existing_managed_incident(self):
        api = Issues(); state, _ = notify.reconcile_health(report(), None, api, REPO, NOW)
        _, action = notify.reconcile_health(report('normal', now=NOW + 60), None, api, REPO, NOW + 60)
        self.assertEqual(action, 'recovered'); self.assertEqual(api.rows[state['incident']['number']]['state'], 'closed')

    def test_separate_workflow_caches_use_shared_issue_metadata_for_mentions_and_severity(self):
        api = Issues()
        collector, _ = notify.reconcile_health(report(), None, api, REPO, NOW, mention='akashIntgrators')
        monitor, _ = notify.reconcile_health(report('critical', now=NOW + 60), None, api, REPO, NOW + 60, mention='akashIntgrators')
        self.assertTrue(monitor['incident']['criticalMentioned'])
        stale_collector, action = notify.reconcile_health(report('critical', now=NOW + 120), collector, api, REPO, NOW + 120, mention='akashIntgrators')
        self.assertEqual(action, 'unchanged', 'An old warning cache must not mention the owner again')
        self.assertTrue(stale_collector['incident']['criticalMentioned'])
        self.assertEqual(len(api.mutations), 2)
        _, action = notify.reconcile_health(report(now=NOW + 180), collector, api, REPO, NOW + 180)
        self.assertEqual(action, 'updated', 'Remote critical-to-warning change is immediate even if local cache still said warning')

    def test_stale_active_cache_does_not_reopen_an_incident_another_workflow_recovered(self):
        api = Issues(); collector, _ = notify.reconcile_health(report(), None, api, REPO, NOW)
        original = collector['incident']['number']
        notify.reconcile_health(report('normal', now=NOW + 60), None, api, REPO, NOW + 60)
        fresh, action = notify.reconcile_health(report(now=NOW + 120), collector, api, REPO, NOW + 120)
        self.assertEqual(action, 'created')
        self.assertNotEqual(fresh['incident']['number'], original)
        self.assertEqual(api.rows[original]['state'], 'closed')

    def test_corrupt_state_or_report_does_not_even_read_github(self):
        for state in [[], {'schemaVersion': 1, 'repo': 'another/repo'}, {'schemaVersion': 1, 'repo': REPO, 'incident': {'number': 2}}]:
            api = Issues()
            with self.assertRaises(notify.NotificationError):
                notify.reconcile_health(report(), state, api, REPO, NOW)
            self.assertEqual(api.reads, []); self.assertEqual(api.mutations, [])
        for bad in [None, {'schemaVersion': 1, 'status': 'normal', 'causes': []}, report('normal', ['new_feed_stale']), report('warning', ['unsafe@recipient'])]:
            with self.assertRaises(notify.NotificationError):
                notify.reconcile_health(bad, None, Issues(), REPO, NOW)

    def test_existing_user_issue_with_same_title_is_not_modified(self):
        api = Issues(); row = api.create(notify.TITLE, notify.MARKER)
        api.rows[row['number']]['user']['login'] = 'someone-else'; api.mutations = []
        state, action = notify.reconcile_health(report(), None, api, REPO, NOW)
        self.assertEqual(action, 'created'); self.assertNotEqual(state['incident']['number'], row['number'])
        broken = {'schemaVersion': 1, 'repo': REPO, 'incident': {**state['incident'], 'number': row['number']}}
        mutations = len(api.mutations)
        with self.assertRaises(notify.NotificationError):
            notify.reconcile_health(report('normal'), broken, api, REPO, NOW)
        self.assertEqual(len(api.mutations), mutations)

    def test_multiple_bot_incidents_fail_closed_instead_of_creating_more(self):
        api = Issues(); api.create(notify.TITLE, notify.MARKER); api.create(notify.TITLE, notify.MARKER)
        with self.assertRaises(notify.NotificationError):
            notify.reconcile_health(report(), None, api, REPO, NOW)
        self.assertEqual(len(api.rows), 2)

    def test_ongoing_incident_reopens_same_issue_if_closed_before_recovery(self):
        api = Issues(); state, _ = notify.reconcile_health(report(), None, api, REPO, NOW)
        number = state['incident']['number']; api.rows[number]['state'] = 'closed'
        state, action = notify.reconcile_health(report(now=NOW + 60), state, api, REPO, NOW + 60)
        self.assertEqual(action, 'reopened'); self.assertEqual(api.rows[number]['state'], 'open')

    def test_failed_github_mutation_does_not_advance_input_state(self):
        api = Issues(); state, _ = notify.reconcile_health(report(), None, api, REPO, NOW); before = deepcopy(state)
        with patch.object(api, 'update', side_effect=notify.NotificationError('offline')):
            with self.assertRaises(notify.NotificationError):
                notify.reconcile_health(report('critical', now=NOW + 60), state, api, REPO, NOW + 60)
        self.assertEqual(state, before)

    def test_internal_state_dates_require_epoch_numbers_before_any_github_access(self):
        api = Issues(); state, _ = notify.reconcile_health(report(), None, api, REPO, NOW)
        state['incident']['lastUpdateAt'] = notify.iso(NOW)
        api.reads.clear()
        with self.assertRaises(notify.NotificationError):
            notify.reconcile_health(report(), state, api, REPO, NOW)
        self.assertEqual(api.reads, [])

    def test_cli_adapter_uses_argument_vector_and_json_stdin_without_a_shell(self):
        adapter = notify.GitHubIssues(REPO)
        body = 'Actual newlines\nUnicode தமிழ்; literal `command` and $(anything)'
        with patch.object(notify.subprocess, 'run', return_value=SimpleNamespace(stdout='{}')) as execute:
            adapter.call('repos/' + REPO + '/issues', 'POST', {'title': notify.TITLE, 'body': body})
        args, kwargs = execute.call_args
        self.assertIsInstance(args[0], list); self.assertNotIn('shell', kwargs)
        self.assertEqual(json.loads(kwargs['input'])['body'], body)
        self.assertEqual(args[0][-2:], ['--input', '-'])
        self.assertNotIn('GH_TOKEN', repr(execute.call_args))

    def test_invalid_recipient_repository_and_dry_run_cannot_post(self):
        for repo, recipient in [('owner/repo;command', None), (REPO, 'name @everyone')]:
            api = Issues()
            with self.assertRaises(notify.NotificationError):
                notify.reconcile_health(report(), None, api, repo, NOW, mention=recipient)
            self.assertEqual(api.mutations, [])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root / 'health.json'; path.write_text(json.dumps(report()))
            with contextlib.redirect_stdout(io.StringIO()), patch.object(notify.GitHubIssues, 'call', side_effect=AssertionError('No network')):
                result = notify.main(['--report', str(path), '--state', str(root / 'state.json'), '--repo', REPO, '--now', str(NOW), '--dry-run'])
            self.assertEqual(result, 0); self.assertFalse((root / 'state.json').exists())
