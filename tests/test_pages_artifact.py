from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import unittest
from unittest import mock

from scripts import wait_for_pages_artifact as waiter


def artifact(**patch):
    return {'id': 123, 'name': 'github-pages', 'expired': False, 'size_in_bytes': 100, **patch}


def response(rows):
    return subprocess.CompletedProcess([], 0, json.dumps({'total_count': len(rows), 'artifacts': rows}), '')


class PagesArtifactTests(unittest.TestCase):
    def test_missing_then_ready_uses_only_bounded_github_get_and_stops(self):
        runner = mock.Mock(side_effect=[response([]), response([artifact()])]); sleep = mock.Mock()
        self.assertEqual(waiter.wait_for_pages_artifact('owner/repo', '456', runner=runner, sleeper=sleep), 123)
        self.assertEqual(runner.call_count, 2); sleep.assert_called_once_with(5)
        for call in runner.call_args_list:
            self.assertEqual(call.args[0], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                'repos/owner/repo/actions/runs/456/artifacts?name=github-pages&per_page=100'])
            self.assertEqual(call.kwargs['timeout'], 10)
            self.assertTrue(call.kwargs['capture_output'])

    def test_permanent_missing_stops_after_seven_checks_and_thirty_seconds_of_waits(self):
        runner = mock.Mock(return_value=response([])); sleep = mock.Mock()
        with self.assertRaisesRegex(waiter.ArtifactWaitError, 'seven checks'):
            waiter.wait_for_pages_artifact('owner/repo', '456', runner=runner, sleeper=sleep)
        self.assertEqual(runner.call_count, 7); self.assertEqual(sleep.call_count, 6)
        self.assertEqual(sum(call.args[0] for call in sleep.call_args_list), 30)

    def test_network_timeout_and_nonzero_exit_retry_without_output_leak(self):
        runner = mock.Mock(side_effect=[subprocess.TimeoutExpired(['gh'], 10),
            subprocess.CompletedProcess([], 1, 'credential-like-output', 'private-error'), response([artifact()])])
        sleep = mock.Mock(); output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(waiter.wait_for_pages_artifact('owner/repo', '456', runner=runner, sleeper=sleep), 123)
        self.assertEqual(runner.call_count, 3); self.assertEqual(sleep.call_count, 2)
        self.assertEqual(output.getvalue(), '')

    def test_permanent_network_failure_is_bounded(self):
        runner = mock.Mock(side_effect=OSError('private-error')); sleep = mock.Mock()
        with self.assertRaisesRegex(waiter.ArtifactWaitError, 'seven checks') as failure:
            waiter.wait_for_pages_artifact('owner/repo', '456', runner=runner, sleeper=sleep)
        self.assertEqual(runner.call_count, 7); self.assertEqual(sleep.call_count, 6)
        self.assertNotIn('private-error', str(failure.exception))

    def test_malformed_metadata_and_duplicate_active_artifacts_fail_immediately(self):
        bad = [subprocess.CompletedProcess([], 0, 'private non-JSON text', ''),
               subprocess.CompletedProcess([], 0, 'null', ''),
               subprocess.CompletedProcess([], 0, json.dumps({'total_count': 101, 'artifacts': []}), ''),
               response([artifact(), artifact(id=124)]), response([artifact(id=True)]),
               response([artifact(size_in_bytes=0)]), response([artifact(expired='false')]),
               response([{'name': 'github-pages'}])]
        for result in bad:
            with self.subTest(result=result.stdout):
                runner = mock.Mock(return_value=result); sleep = mock.Mock()
                with self.assertRaises(waiter.ArtifactWaitError) as failure:
                    waiter.wait_for_pages_artifact('owner/repo', '456', runner=runner, sleeper=sleep)
                runner.assert_called_once(); sleep.assert_not_called()
                self.assertNotIn('private', str(failure.exception))

    def test_expired_artifacts_do_not_establish_readiness_or_create_ambiguity(self):
        runner = mock.Mock(side_effect=[response([artifact(expired=True)]),
            response([artifact(expired=True), artifact(id=124)])]); sleep = mock.Mock()
        self.assertEqual(waiter.wait_for_pages_artifact('owner/repo', '456', runner=runner, sleeper=sleep), 124)
        sleep.assert_called_once_with(5)

    def test_invalid_environment_targets_never_run_gh(self):
        for repo, run in [('owner/repo;echo', '456'), ('../repo', '456'), ('owner/repo', '0'),
                          ('owner/repo', '456/other'), (None, '456')]:
            with self.subTest(repo=repo, run=run):
                runner = mock.Mock(); sleep = mock.Mock()
                with self.assertRaises(waiter.ArtifactWaitError):
                    waiter.wait_for_pages_artifact(repo, run, runner=runner, sleeper=sleep)
                runner.assert_not_called(); sleep.assert_not_called()

    def test_cli_uses_validated_environment_and_prints_only_safe_status(self):
        output = io.StringIO()
        with mock.patch.dict(os.environ, {'GITHUB_REPOSITORY':'owner/repo','GITHUB_RUN_ID':'456'}), \
             mock.patch.object(waiter, 'wait_for_pages_artifact', return_value=123) as wait, redirect_stdout(output):
            self.assertEqual(waiter.main([]), 0)
        wait.assert_called_once_with('owner/repo', '456')
        self.assertEqual(output.getvalue(), 'Pages artifact is discoverable: 123.\n')


if __name__ == '__main__':
    unittest.main()
