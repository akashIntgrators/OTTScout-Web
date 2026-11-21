from contextlib import redirect_stdout
import io
import json
import os
import subprocess
import unittest
from unittest import mock

from scripts import wait_for_pages_artifact as waiter

NAME = 'github-pages-456-2'
ID = '123'


def artifact(**patch):
    return {'id': 123, 'name': NAME, 'expired': False, 'size_in_bytes': 100, **patch}


def response(rows):
    return subprocess.CompletedProcess([], 0, json.dumps({'total_count': len(rows), 'artifacts': rows}), '')


def wait(runner, sleep):
    return waiter.wait_for_pages_artifact('owner/repo', '456', '2', NAME, ID, runner=runner, sleeper=sleep)


class PagesArtifactTests(unittest.TestCase):
    def test_old_attempt_then_exact_current_upload_uses_only_bounded_github_get(self):
        runner = mock.Mock(side_effect=[response([artifact(name='github-pages-456-1', id=99)]), response([artifact()])]); sleep = mock.Mock()
        self.assertEqual(wait(runner, sleep), 123)
        self.assertEqual(runner.call_count, 2); sleep.assert_called_once_with(5)
        for call in runner.call_args_list:
            self.assertEqual(call.args[0], ['gh', 'api', '--hostname', 'github.com', '--method', 'GET',
                'repos/owner/repo/actions/runs/456/artifacts?name=github-pages-456-2&per_page=100'])
            self.assertEqual(call.kwargs['timeout'], 10)
            self.assertTrue(call.kwargs['capture_output'])

    def test_permanent_missing_stops_after_seven_checks_and_thirty_seconds_of_waits(self):
        runner = mock.Mock(return_value=response([])); sleep = mock.Mock()
        with self.assertRaisesRegex(waiter.ArtifactWaitError, 'seven checks'):
            wait(runner, sleep)
        self.assertEqual(runner.call_count, 7); self.assertEqual(sleep.call_count, 6)
        self.assertEqual(sum(call.args[0] for call in sleep.call_args_list), 30)

    def test_network_timeout_and_nonzero_exit_retry_without_output_leak(self):
        runner = mock.Mock(side_effect=[subprocess.TimeoutExpired(['gh'], 10),
            subprocess.CompletedProcess([], 1, 'credential-like-output', 'private-error'), response([artifact()])])
        sleep = mock.Mock(); output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(wait(runner, sleep), 123)
        self.assertEqual(runner.call_count, 3); self.assertEqual(sleep.call_count, 2)
        self.assertEqual(output.getvalue(), '')

    def test_permanent_network_failure_is_bounded(self):
        runner = mock.Mock(side_effect=OSError('private-error')); sleep = mock.Mock()
        with self.assertRaisesRegex(waiter.ArtifactWaitError, 'seven checks') as failure:
            wait(runner, sleep)
        self.assertEqual(runner.call_count, 7); self.assertEqual(sleep.call_count, 6)
        self.assertNotIn('private-error', str(failure.exception))

    def test_malformed_duplicate_expired_or_wrong_id_artifacts_fail_closed(self):
        bad = [subprocess.CompletedProcess([], 0, 'private non-JSON text', ''),
               subprocess.CompletedProcess([], 0, 'null', ''),
               subprocess.CompletedProcess([], 0, json.dumps({'total_count': 101, 'artifacts': []}), ''),
               response([artifact(), artifact(id=124)]), response([artifact(), artifact(id=124, expired=True)]),
               response([artifact(id=124)]), response([artifact(id=True)]), response([artifact(expired=True)]),
               response([artifact(size_in_bytes=0)]), response([artifact(expired='false')]), response([{'name': NAME}])]
        for result in bad:
            with self.subTest(result=result.stdout):
                runner = mock.Mock(return_value=result); sleep = mock.Mock()
                with self.assertRaises(waiter.ArtifactWaitError) as failure:
                    wait(runner, sleep)
                runner.assert_called_once(); sleep.assert_not_called()
                self.assertNotIn('private', str(failure.exception))

    def test_invalid_environment_targets_never_run_gh(self):
        invalid = [('owner/repo;echo', '456', '2', NAME, ID), ('../repo', '456', '2', NAME, ID),
                   ('owner/repo', '0', '2', NAME, ID), ('owner/repo', '456/other', '2', NAME, ID),
                   ('owner/repo', '456', '1', NAME, ID), ('owner/repo', '456', '2', NAME, '0'),
                   ('owner/repo', '456', '2', 'github-pages-456-1', ID)]
        for values in invalid:
            with self.subTest(values=values):
                runner = mock.Mock(); sleep = mock.Mock()
                with self.assertRaises(waiter.ArtifactWaitError):
                    waiter.wait_for_pages_artifact(*values, runner=runner, sleeper=sleep)
                runner.assert_not_called(); sleep.assert_not_called()

    def test_cli_uses_validated_environment_and_prints_only_safe_status(self):
        output = io.StringIO()
        env = {'GITHUB_REPOSITORY':'owner/repo', 'GITHUB_RUN_ID':'456', 'GITHUB_RUN_ATTEMPT':'2',
               'PAGES_ARTIFACT_NAME':NAME, 'PAGES_ARTIFACT_ID':ID}
        with mock.patch.dict(os.environ, env), mock.patch.object(waiter, 'wait_for_pages_artifact', return_value=123) as run, redirect_stdout(output):
            self.assertEqual(waiter.main([]), 0)
        run.assert_called_once_with('owner/repo', '456', '2', NAME, ID)
        self.assertEqual(output.getvalue(), 'Pages artifact is discoverable: 123.\n')


if __name__ == '__main__':
    unittest.main()
