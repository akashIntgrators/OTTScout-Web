"""Exercise checked-in workflow scripts offline instead of copying their policy."""
import ast
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github/workflows'


def workflow(name):
    return (WORKFLOWS / name).read_text(encoding='utf-8')


def steps(text):
    """Read only top-level job steps; no YAML loader or expression expansion."""
    starts = list(re.finditer(r'^      - ', text, re.MULTILINE))
    return [text[start.start():starts[index + 1].start() if index + 1 < len(starts) else len(text)]
            for index, start in enumerate(starts)]


def field(step, name):
    match = re.search(r'^        ' + re.escape(name) + r': (.+)$', step, re.MULTILINE)
    if match is None:
        match = re.search(r'^      - ' + re.escape(name) + r': (.+)$', step, re.MULTILINE)
    return match[1] if match else None


def step_with_id(text, ident):
    found = [step for step in steps(text) if field(step, 'id') == ident]
    if len(found) != 1:
        raise AssertionError('Expected exactly one workflow step with id ' + ident)
    return found[0]


def script(step):
    lines = step.splitlines()
    for index, line in enumerate(lines):
        if line.startswith('        run: '):
            value = line[len('        run: '):]
            if value != '|':
                return value + '\n'
            result = []
            for body in lines[index + 1:]:
                if body.startswith('          '):
                    result.append(body[10:])
                elif not body.strip():
                    result.append('')
                else:
                    break
            return '\n'.join(result) + '\n'
    return ''


def expression_value(expression, values):
    """Evaluate the actual expression using explicit fixture event values."""
    if expression is None:
        raise AssertionError('The protected step must have an explicit condition')
    if expression.startswith('${{') and expression.endswith('}}'):
        expression = expression[3:-2].strip()
    expression = expression.replace('always()', 'True')
    for key, value in sorted(values.items(), key=lambda pair: -len(pair[0])):
        expression = expression.replace(key, repr(value))
    expression = expression.replace('&&', ' and ').replace('||', ' or ')
    expression = re.sub(r'!(?!=)', 'not ', expression)
    expression = re.sub(r'\btrue\b', 'True', expression)
    expression = re.sub(r'\bfalse\b', 'False', expression)
    tree = ast.parse(expression, mode='eval')
    allowed = (ast.Expression, ast.BoolOp, ast.Compare, ast.Constant, ast.And, ast.Or,
               ast.Eq, ast.NotEq, ast.UnaryOp, ast.Not)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise AssertionError('Unsupported or unresolved workflow condition: ' + expression)
    return eval(compile(tree, '<workflow guard>', 'eval'), {'__builtins__': {}}, {})


def condition(step, values):
    return bool(expression_value(field(step, 'if'), values))


class ReliabilityWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.collector = workflow('catalog-pilot.yml')
        self.watchdog = workflow('catalogue-watchdog.yml')
        self.publisher = workflow('publish-site.yml')
        self.publish_action = (ROOT / '.github/actions/publish-pages/action.yml').read_text(encoding='utf-8')

    def action_steps(self):
        # Composite children are two spaces shallower than job steps. Normalize
        # indentation only, then execute the same checked-in guards and scripts.
        return steps('\n'.join('  ' + line for line in self.publish_action.splitlines()))

    def run_script(self, source, root, extra, record=False):
        binary = root / 'bin'; binary.mkdir(exist_ok=True)
        if record:
            recorder = root / 'record.py'
            recorder.write_text('import json, os, sys\nwith open(os.environ["ARGV_LOG"], "a") as out:\n    out.write(json.dumps(sys.argv[1:]) + "\\n")\n')
            command = 'exec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(recorder)) + ' "$@"\n'
        else:
            # Only the embedded Python heredoc may execute real Python. A future
            # accidental API command in this step cannot escape onto the network.
            command = 'if [ "$#" != 1 ] || [ "$1" != - ]; then exit 91; fi\nexec ' + shlex.quote(sys.executable) + ' "$@"\n'
        for name in ('python', 'python3'):
            shim = binary / name; shim.write_text('#!/bin/sh\n' + command); shim.chmod(0o755)
        env = {'PATH': str(binary), 'PYTHONNOUSERSITE': '1', **extra}
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', source], cwd=root, env=env,
                              capture_output=True, text=True, check=True, timeout=10)

    def test_actual_checker_routes_offline_and_metadata_runs_only_to_cached_export(self):
        checker = script(step_with_id(self.collector, 'checker'))
        for metadata, offline, initialize in [('false', 'true', 'true'), ('true', 'false', 'true'),
                                              ('true', 'true', 'false')]:
            with self.subTest(metadata=metadata, offline=offline, initialize=initialize), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); log = root / 'argv.jsonl'
                self.run_script(checker, root, {'ARGV_LOG': str(log), 'METADATA_ONLY': metadata,
                                              'OFFLINE_ONLY': offline, 'INITIALIZE': initialize}, record=True)
                self.assertEqual([json.loads(line) for line in log.read_text().splitlines()],
                                 [['scripts/catalog_sync.py', '--export-cached']])

    def test_paused_sony_sources_ignore_stale_relay_flag_and_incomplete_secrets_in_actual_discovery_script(self):
        source = script(step_with_id(self.collector, 'discovery'))
        cases = [
            [{'platform':'SonyLIV','enabled':False},{'platform':'Netflix','enabled':True}],
            [{'platform':'SonyLIV','enabled':'true'},{'platform':'Netflix','enabled':True}],
            [{'platform':'SonyLIV'},{'platform':'Netflix','enabled':True}],
        ]
        for sources in cases:
            with self.subTest(sources=sources), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root / 'data').mkdir(); binary = root / 'bin'; binary.mkdir()
                (root / 'data/official-sources.json').write_text(json.dumps(sources))
                log = root / 'argv.jsonl'; forbidden = root / 'forbidden'; wrapper = root / 'discovery_shim.py'
                wrapper.write_text(
                    'import json, os, socket, sys\n'
                    'def denied(*args, **kwargs):\n    raise AssertionError("No network is allowed")\n'
                    'socket.socket = denied\nsocket.create_connection = denied\n'
                    'if sys.argv[1:] == ["-"]:\n'
                    '    exec(compile(sys.stdin.read(), "<actual workflow heredoc>", "exec"), {"__name__":"__main__"})\n'
                    'elif sys.argv[1:2] == ["scripts/official_discovery.py"]:\n'
                    '    with open(os.environ["ARGV_LOG"], "a") as out:\n        out.write(json.dumps(sys.argv[1:]) + "\\n")\n'
                    'else:\n    raise SystemExit("Unexpected Python command in discovery step")\n')
                for name in ('python', 'python3'):
                    shim = binary / name
                    shim.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(wrapper)) + ' "$@"\n')
                    shim.chmod(0o755)
                for name in ('ssh', 'mktemp'):
                    command = binary / name
                    command.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + '" >> "$FORBIDDEN_LOG"\nexit 92\n')
                    command.chmod(0o755)
                env = {'PATH':str(binary), 'PYTHONNOUSERSITE':'1', 'ARGV_LOG':str(log), 'FORBIDDEN_LOG':str(forbidden),
                       'RUNNER_TEMP':str(root), 'SONY_RELAY_ENABLED':'true', 'SONY_RELAY_HOST':'incomplete-host.invalid',
                       'SONY_RELAY_PRIVATE_KEY':'', 'SONY_RELAY_KNOWN_HOSTS':''}
                subprocess.run(['/bin/bash','--noprofile','--norc','-e','-o','pipefail','-c',source],
                               cwd=root,env=env,capture_output=True,text=True,check=True,timeout=10)
                self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], [[
                    'scripts/official_discovery.py','--catalog','data/catalog.json','--cache-dir','.state/official-discovery',
                    '--output','data/official-discovered.json','--report','reports/official-discovery.json',
                    '--max-requests','12','--max-seconds','120']])
                self.assertFalse(forbidden.exists(), 'Paused sources must not start SSH or prepare a relay directory')
                self.assertEqual(list(root.glob('sony-relay.*')), [])

    def test_health_commands_do_not_override_explicitly_paused_sony_sources_as_required(self):
        for text in (self.collector,self.watchdog):
            health_steps = [step for step in steps(text) if 'scripts/catalogue_health.py' in script(step)]
            self.assertGreaterEqual(len(health_steps), 2)
            for step in health_steps:
                self.assertNotRegex(script(step), r'--required-source\s+sony-(?:movies|series)\b')

    def test_actual_online_checker_retains_initialize_only_when_explicitly_requested(self):
        checker = script(step_with_id(self.collector, 'checker'))
        for initialize, expected in [('true', ['--initialize']), ('false', []), ('', [])]:
            with self.subTest(initialize=initialize), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); log = root / 'argv.jsonl'
                self.run_script(checker, root, {'ARGV_LOG': str(log), 'METADATA_ONLY': '', 'OFFLINE_ONLY': '',
                                              'INITIALIZE': initialize}, record=True)
                self.assertEqual([json.loads(line) for line in log.read_text().splitlines()],
                                 [['scripts/catalog_sync.py', '--allow-cached-on-limit', *expected]])

    def test_actual_metadata_eligibility_program_protects_offline_budget_and_pending_work(self):
        source = script(step_with_id(self.collector, 'metadata'))
        cases = [
            ('true', 'true', False, False, False), ('true', 'false', False, False, False),
            ('false', 'false', True, False, False), ('false', 'false', False, True, False),
            ('false', 'false', False, False, True), ('false', 'true', True, True, True),
        ]
        for offline, metadata, conserving, pending, expected in cases:
            with self.subTest(offline=offline, metadata=metadata, conserving=conserving, pending=pending), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root / 'reports').mkdir(); output = root / 'output'
                (root / 'reports/pilot.json').write_text(json.dumps({'requestBudget': {'conservationMode': conserving},
                    'pendingChangeQueries': {'new': {'cursor': 'saved'}} if pending else {}}))
                self.run_script(source, root, {'GITHUB_OUTPUT': str(output), 'OFFLINE_ONLY': offline, 'METADATA_ONLY': metadata})
                self.assertEqual(output.read_text(), 'allowed=' + str(expected).lower() + '\n')

    def test_actual_metadata_eligibility_defaults_closed_without_a_collector_report(self):
        for explicit, expected in [('false', 'false'), ('true', 'true')]:
            with self.subTest(metadata=explicit), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); output = root / 'output'
                self.run_script(script(step_with_id(self.collector, 'metadata')), root,
                                {'GITHUB_OUTPUT': str(output), 'OFFLINE_ONLY': 'false', 'METADATA_ONLY': explicit})
                self.assertEqual(output.read_text(), 'allowed=' + expected + '\n')

    def test_metadata_execution_still_requires_successful_checker_and_explicit_eligibility(self):
        enrich = step_with_id(self.collector, 'enrichment')
        for checker, allowed, expected in [('success', 'true', True), ('failure', 'true', False),
                                            ('success', 'false', False), ('skipped', 'true', False)]:
            with self.subTest(checker=checker, allowed=allowed):
                self.assertEqual(condition(enrich, {'steps.checker.outcome': checker, 'steps.metadata.outputs.allowed': allowed}), expected)

    def test_cached_modes_cannot_enable_streaming_id_repairs_inside_metadata_enrichment(self):
        enrich = step_with_id(self.collector, 'enrichment')
        assignment = re.search(r'^          TMDB_REFRESH_IDS: (.+)$', enrich, re.MULTILINE)
        self.assertIsNotNone(assignment)
        for offline, metadata, expected in [(False, False, 'motn:123'), (True, False, ''), (False, True, ''), (True, True, '')]:
            with self.subTest(offline=offline, metadata=metadata):
                self.assertEqual(expression_value(assignment[1], {'inputs.offline_only': offline, 'inputs.metadata_only': metadata,
                                                                 'inputs.metadata_ids': 'motn:123'}), expected)

    def test_watchdog_and_manual_publisher_have_no_movie_api_commands_or_credentials(self):
        for name, text in [('watchdog', self.watchdog), ('publisher', self.publisher)]:
            with self.subTest(workflow=name):
                commands = '\n'.join(script(step) for step in steps(text))
                self.assertNotRegex(commands, r'\bpython(?:3)?\s+scripts/(?:catalog_sync|tmdb_enrich|official_discovery)\.py\b')
                self.assertNotRegex(text, r'STREAMING_API_KEY|TMDB_READ_ACCESS_TOKEN|X-API-Key|streaming-availability\.p\.rapidapi|api\.movieofthenight')
                allowed = {'-', 'scripts/fetch_public_catalogue.py', 'scripts/build_site.py',
                           'scripts/catalogue_health.py', 'scripts/notify_catalogue_health.py',
                           'scripts/wait_for_pages_artifact.py'}
                for line in commands.splitlines():
                    match = re.match(r'\s*python(?:3)?\s+(\S+)', line)
                    if match:
                        if match[1] == '-m':
                            self.assertRegex(line, r'^\s*python(?:3)? -m unittest\b')
                        else:
                            self.assertIn(match[1], allowed, 'A new executable Python path needs a zero-API review')
                self.assertIn('scripts/fetch_public_catalogue.py', commands)
        self.assertIn('--previous-health reports/previous-public-health.json', self.watchdog)
        self.assertIn('--discovery-report reports/no-new-source-check.json', self.watchdog)

    def test_collector_watchdog_and_publisher_serialize_mutations_without_cancelling_progress(self):
        groups = []
        for text in (self.collector, self.watchdog, self.publisher):
            block = re.search(r'^concurrency:\n((?:  [^\n]*\n|\n)+)', text, re.MULTILINE)
            self.assertIsNotNone(block)
            group = re.search(r'^  group: (.+)$', block[1], re.MULTILINE)
            self.assertIsNotNone(group); groups.append(group[1])
            self.assertRegex(block[1], r'(?m)^  cancel-in-progress: false$')
        self.assertEqual(groups, ['ottscout-catalog-pilot'] * 3)

    def test_all_pages_deployments_wait_for_the_exact_uploaded_artifact_before_deploying(self):
        for name, text in [('collector', self.collector), ('watchdog', self.watchdog), ('publisher', self.publisher)]:
            with self.subTest(workflow=name):
                ordered = steps(text)
                upload = step_with_id(text, 'pages_upload'); ready = step_with_id(text, 'pages_ready')
                deploy = step_with_id(text, 'deployment')
                self.assertEqual(field(deploy, 'uses'), './.github/actions/publish-pages')
                self.assertIn('uses: actions/upload-pages-artifact@v3', upload)
                name = 'github-pages-${{ github.run_id }}-${{ github.run_attempt }}'
                self.assertIn('name: ' + name, upload)
                self.assertIn('PAGES_ARTIFACT_NAME: ' + name, ready)
                self.assertIn('PAGES_ARTIFACT_ID: ${{ steps.pages_upload.outputs.artifact_id }}', ready)
                self.assertIn('artifact_name: ' + name, deploy)
                self.assertLess(ordered.index(upload), ordered.index(ready)); self.assertLess(ordered.index(ready), ordered.index(deploy))
                self.assertTrue(condition(ready, {'steps.pages_upload.outcome': 'success'}))
                self.assertFalse(condition(ready, {'steps.pages_upload.outcome': 'failure'}))
                self.assertTrue(condition(deploy, {'steps.build.outcome': 'success', 'steps.pages_ready.outcome': 'success'}))
                for outcome in ('failure', 'skipped', 'cancelled'):
                    self.assertFalse(condition(deploy, {'steps.build.outcome': 'success', 'steps.pages_ready.outcome': outcome}))
                self.assertEqual(script(ready).strip(), 'python scripts/wait_for_pages_artifact.py')
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder); log = root / 'argv.jsonl'
                    self.run_script(script(ready), root, {'ARGV_LOG': str(log), 'GITHUB_REPOSITORY': 'owner/repo',
                                                         'GITHUB_RUN_ID': '123'}, record=True)
                    self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], [['scripts/wait_for_pages_artifact.py']])

    def test_artifact_readiness_failure_preserves_publication_incident_and_progress_caches(self):
        for name, text in [('collector', self.collector), ('watchdog', self.watchdog)]:
            with self.subTest(workflow=name):
                guard = step_with_id(text, 'publication_guard')
                notify = next(step for step in steps(text) if 'scripts/notify_catalogue_health.py' in script(step))
                values = {'steps.health.outcome': 'success', 'steps.pages_ready.outcome': 'failure',
                          'steps.deployment.outcome': 'skipped', 'steps.publication_guard.outcome': 'success',
                          'inputs.publish': True, 'vars.PUBLISH_CATALOG': 'false'}
                self.assertTrue(condition(guard, values))
                self.assertTrue(condition(notify, values))
                self.assertFalse(condition(notify, {**values, 'steps.publication_guard.outcome': 'failure'}))
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder); log = root / 'argv.jsonl'
                    self.run_script(script(guard), root, {'ARGV_LOG': str(log)}, record=True)
                    self.assertEqual(json.loads(log.read_text().splitlines()[0])[-2:], ['--input-error', 'website_publication_failed'])
                save = next(step for step in steps(text) if 'uses: actions/cache/save@' in step)
                self.assertTrue(condition(save, {'steps.ledger.outputs.valid': 'true'}), 'Publication readiness failure must not discard validated collection progress')

    def test_readiness_helper_has_readonly_actions_permission_and_publisher_scopes_its_token(self):
        for text in (self.collector, self.watchdog, self.publisher):
            permissions = re.search(r'^permissions:\n((?:  [^\n]*\n|\n)+)', text, re.MULTILINE)
            self.assertIsNotNone(permissions)
            self.assertRegex(permissions[1], r'(?m)^  actions: read$')
            self.assertNotRegex(permissions[1], r'(?m)^  actions: write$')
        publisher_ready = step_with_id(self.publisher, 'pages_ready')
        self.assertRegex(publisher_ready, r'(?m)^          GH_TOKEN: \$\{\{ github\.token \}\}$')
        for step in steps(self.publisher):
            if field(step, 'id') != 'pages_ready':
                self.assertNotIn('GH_TOKEN:', step)

    def run_publish_action(self, outcomes, urls):
        """Run actual composite guards/shell with injected official-action results."""
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); output = root / 'output'; sleep_log = root / 'sleep'
            binary = root / 'bin'; binary.mkdir()
            sleeper = binary / 'sleep'
            sleeper.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$SLEEP_LOG"\n'); sleeper.chmod(0o755)
            values = {}
            for index in range(1, 4):
                values['steps.attempt_' + str(index) + '.outcome'] = 'skipped'
                values['steps.attempt_' + str(index) + '.outputs.page_url'] = ''
            attempts = []
            failure = None
            for step in self.action_steps():
                ident = field(step, 'id')
                if field(step, 'if') is not None and not condition(step, values):
                    continue
                if field(step, 'uses') is not None:
                    self.assertEqual(field(step, 'uses'), 'actions/deploy-pages@v5.0.1')
                    self.assertEqual(field(step, 'continue-on-error'), 'true')
                    attempts.append(ident)
                    values['steps.' + ident + '.outcome'] = outcomes[len(attempts) - 1]
                    values['steps.' + ident + '.outputs.page_url'] = urls[len(attempts) - 1]
                    continue
                env = {'GITHUB_OUTPUT': str(output), 'SLEEP_LOG': str(sleep_log)}
                for match in re.finditer(r'^          ([A-Z_]+): (\$\{\{[^\n]+\}\})$', step, re.MULTILINE):
                    env[match[1]] = expression_value(match[2], values)
                try:
                    self.run_script(script(step), root, env)
                except subprocess.CalledProcessError as error:
                    failure = error.returncode
                    break
            return attempts, sleep_log.read_text().splitlines() if sleep_log.exists() else [], output.read_text() if output.exists() else '', failure

    def test_composite_uses_exact_official_action_and_bounded_inputs_and_exports_result_url(self):
        attempts = [step for step in self.action_steps() if field(step, 'uses') is not None]
        self.assertEqual(len(attempts), 3)
        for step in attempts:
            self.assertEqual(field(step, 'uses'), 'actions/deploy-pages@v5.0.1')
            self.assertEqual(field(step, 'continue-on-error'), 'true')
            self.assertRegex(step, r"(?m)^          timeout: '120000'$")
            self.assertIn('artifact_name: ${{ inputs.artifact_name }}', step)
        self.assertIn('value: ${{ steps.result.outputs.page_url }}', self.publish_action)
        self.assertNotRegex(self.publish_action, r'catalog_sync|tmdb_enrich|official_discovery|STREAMING_API_KEY|TMDB_READ_ACCESS_TOKEN|permissions:')
        self.assertEqual(condition(next(step for step in self.action_steps() if field(step, 'id') == 'result'), {}), True)

    def test_actual_composite_first_success_skips_both_waits_and_later_attempts(self):
        attempts, waits, output, failure = self.run_publish_action(['success'], ['https://ottscout.techiwithhelmet.com/'])
        self.assertEqual(attempts, ['attempt_1']); self.assertEqual(waits, [])
        self.assertEqual(output, 'page_url=https://ottscout.techiwithhelmet.com/\n'); self.assertIsNone(failure)

    def test_actual_composite_second_success_waits_once_after_a_failure_without_deployment_url(self):
        attempts, waits, output, failure = self.run_publish_action(['failure', 'success'],
            ['', 'https://ottscout.techiwithhelmet.com/'])
        self.assertEqual(attempts, ['attempt_1', 'attempt_2']); self.assertEqual(waits, ['15'])
        self.assertEqual(output, 'page_url=https://ottscout.techiwithhelmet.com/\n'); self.assertIsNone(failure)

    def test_actual_composite_third_success_has_only_fifteen_then_thirty_second_waits(self):
        attempts, waits, output, failure = self.run_publish_action(['failure', 'failure', 'success'],
            ['', '', 'https://ottscout.techiwithhelmet.com/'])
        self.assertEqual(attempts, ['attempt_1', 'attempt_2', 'attempt_3']); self.assertEqual(waits, ['15', '30'])
        self.assertEqual(output, 'page_url=https://ottscout.techiwithhelmet.com/\n'); self.assertIsNone(failure)

    def test_actual_composite_all_failures_without_urls_fail_parent(self):
        attempts, waits, output, failure = self.run_publish_action(['failure'] * 3, [''] * 3)
        self.assertEqual(attempts, ['attempt_1', 'attempt_2', 'attempt_3']); self.assertEqual(waits, ['15', '30'])
        self.assertEqual(output, ''); self.assertEqual(failure, 1)

    def test_failed_attempt_with_deployment_url_stops_without_retry(self):
        attempts, waits, output, failure = self.run_publish_action(['failure'], ['https://possibly-deployed.example/'])
        self.assertEqual(attempts, ['attempt_1']); self.assertEqual(waits, [])
        self.assertEqual(output, ''); self.assertEqual(failure, 1)
        attempts, waits, output, failure = self.run_publish_action(['failure', 'failure'], ['', 'https://possibly-deployed.example/'])
        self.assertEqual(attempts, ['attempt_1', 'attempt_2']); self.assertEqual(waits, ['15'])
        self.assertEqual(output, ''); self.assertEqual(failure, 1)

    def test_actual_composite_refuses_unsafe_or_missing_success_url_without_output_injection(self):
        for value in ['', 'http://untrusted.example/', 'https://user:password@example.com/', 'https://example.com/\nother=output']:
            with self.subTest(value=value):
                attempts, waits, output, failure = self.run_publish_action(['success'], [value])
                self.assertEqual(attempts, ['attempt_1']); self.assertEqual(waits, [])
                self.assertEqual(output, ''); self.assertEqual(failure, 1)

    def test_incident_reconciliation_follows_failed_publication_guard_in_both_workflows(self):
        for name, text in [('collector', self.collector), ('watchdog', self.watchdog)]:
            with self.subTest(workflow=name):
                ordered = steps(text)
                guard = [step for step in ordered if '--input-error website_publication_failed' in script(step)]
                notify = [step for step in ordered if 'scripts/notify_catalogue_health.py' in script(step)]
                self.assertEqual(len(guard), 1); self.assertEqual(len(notify), 1)
                self.assertLess(ordered.index(guard[0]), ordered.index(notify[0]))
                values = {'steps.health.outcome': 'success', 'steps.deployment.outcome': 'failure', 'steps.publication_guard.outcome': 'success',
                          'inputs.publish': True, 'vars.PUBLISH_CATALOG': 'false'}
                self.assertTrue(condition(guard[0], values))
                self.assertFalse(condition(guard[0], {**values, 'steps.deployment.outcome': 'success'}))
                self.assertFalse(condition(notify[0], {**values, 'steps.health.outcome': 'failure'}))

    def test_nonpublishing_collector_run_cannot_reconcile_the_production_incident(self):
        notify = next(step for step in steps(self.collector) if 'scripts/notify_catalogue_health.py' in script(step))
        guard = next(step for step in steps(self.collector) if '--input-error website_publication_failed' in script(step))
        values = {'steps.health.outcome': 'success', 'steps.deployment.outcome': 'skipped', 'steps.publication_guard.outcome': 'skipped',
                  'inputs.publish': False, 'vars.PUBLISH_CATALOG': 'false'}
        self.assertFalse(condition(notify, values)); self.assertFalse(condition(guard, values))
        self.assertTrue(condition(notify, {**values, 'inputs.publish': True, 'steps.deployment.outcome': 'success'}))
        self.assertTrue(condition(notify, {**values, 'vars.PUBLISH_CATALOG': 'true', 'steps.publication_guard.outcome': 'success'}))

    def test_failed_publication_guard_cannot_reconcile_or_close_the_production_incident(self):
        for text in (self.collector, self.watchdog):
            notify = next(step for step in steps(text) if 'scripts/notify_catalogue_health.py' in script(step))
            values = {'steps.health.outcome': 'success', 'steps.deployment.outcome': 'failure',
                      'steps.publication_guard.outcome': 'failure', 'inputs.publish': True, 'vars.PUBLISH_CATALOG': 'false'}
            self.assertFalse(condition(notify, values))
            self.assertTrue(condition(notify, {**values, 'steps.publication_guard.outcome': 'success'}))
            self.assertTrue(condition(notify, {**values, 'steps.deployment.outcome': 'success'}))

    def test_build_requires_public_snapshot_and_real_collector_or_recovery_output(self):
        build = step_with_id(self.collector, 'build')
        values = {'steps.snapshot.outcome': 'success', 'steps.checker.outcome': 'success', 'steps.recovery.outcome': 'skipped',
                  'steps.enrichment.outcome': 'success', 'steps.cached_metadata.outcome': 'skipped',
                  'steps.overlay.outcome': 'success', 'steps.health.outcome': 'success', 'inputs.publish': True, 'vars.PUBLISH_CATALOG': 'false'}
        self.assertTrue(condition(build, values))
        self.assertFalse(condition(build, {**values, 'steps.snapshot.outcome': 'failure'}))
        self.assertFalse(condition(build, {**values, 'steps.checker.outcome': 'failure'}))
        self.assertTrue(condition(build, {**values, 'steps.checker.outcome': 'failure', 'steps.recovery.outcome': 'success'}))
        self.assertFalse(condition(build, {**values, 'steps.checker.outcome': 'skipped', 'steps.recovery.outcome': 'skipped'}))

    def test_skipped_or_failed_network_enrichment_requires_cached_metadata_success_before_build(self):
        cached = step_with_id(self.collector, 'cached_metadata')
        self.assertEqual(script(cached).strip(), 'python scripts/tmdb_enrich.py --cached-only')
        build = step_with_id(self.collector, 'build')
        values = {'steps.snapshot.outcome': 'success', 'steps.checker.outcome': 'success', 'steps.recovery.outcome': 'skipped',
                  'steps.enrichment.outcome': 'skipped', 'steps.cached_metadata.outcome': 'skipped',
                  'steps.overlay.outcome': 'success', 'steps.health.outcome': 'success', 'inputs.publish': True, 'vars.PUBLISH_CATALOG': 'false'}
        for enrichment in ('skipped', 'failure'):
            with self.subTest(enrichment=enrichment):
                self.assertTrue(condition(cached, {**values, 'steps.enrichment.outcome': enrichment}))
                for outcome in ('skipped', 'failure', 'cancelled'):
                    self.assertFalse(condition(build, {**values, 'steps.enrichment.outcome': enrichment, 'steps.cached_metadata.outcome': outcome}))
                self.assertTrue(condition(build, {**values, 'steps.enrichment.outcome': enrichment, 'steps.cached_metadata.outcome': 'success'}))
        self.assertFalse(condition(cached, {**values, 'steps.enrichment.outcome': 'success'}))
        self.assertTrue(condition(build, {**values, 'steps.enrichment.outcome': 'success'}))
        self.assertTrue(condition(cached, {**values, 'steps.checker.outcome': 'failure', 'steps.recovery.outcome': 'success'}))
        self.assertFalse(condition(cached, {**values, 'steps.checker.outcome': 'failure'}))

    def test_offline_workflow_keeps_cached_metadata_route_and_never_selects_network_enrichment(self):
        checker = step_with_id(self.collector, 'checker'); metadata = step_with_id(self.collector, 'metadata')
        enrich = step_with_id(self.collector, 'enrichment'); cached = step_with_id(self.collector, 'cached_metadata')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); log = root / 'argv.jsonl'; output = root / 'output'; (root / 'reports').mkdir()
            (root / 'reports/pilot.json').write_text(json.dumps({'requestBudget': {'conservationMode': False}, 'pendingChangeQueries': {}}))
            flags = {'METADATA_ONLY': 'true', 'OFFLINE_ONLY': 'true', 'INITIALIZE': 'false'}
            self.run_script(script(checker), root, {**flags, 'ARGV_LOG': str(log)}, record=True)
            self.run_script(script(metadata), root, {**flags, 'GITHUB_OUTPUT': str(output)})
            self.assertEqual(output.read_text(), 'allowed=false\n')
            outcomes = {'steps.checker.outcome': 'success', 'steps.recovery.outcome': 'skipped',
                        'steps.metadata.outputs.allowed': 'false', 'steps.enrichment.outcome': 'skipped'}
            self.assertFalse(condition(enrich, outcomes)); self.assertTrue(condition(cached, outcomes))
            self.run_script(script(cached), root, {'ARGV_LOG': str(log)}, record=True)
            self.assertEqual([json.loads(line) for line in log.read_text().splitlines()],
                             [['scripts/catalog_sync.py', '--export-cached'], ['scripts/tmdb_enrich.py', '--cached-only']])

    def test_cached_metadata_failure_reaches_actual_health_input_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); log = root / 'argv.jsonl'
            outcomes = {'COLLECTOR_OUTCOME': 'success', 'RECOVERY_OUTCOME': 'skipped', 'DISCOVERY_OUTCOME': 'success',
                        'OVERLAY_OUTCOME': 'success', 'ENRICHMENT_OUTCOME': 'skipped', 'CACHED_METADATA_OUTCOME': 'failure',
                        'SNAPSHOT_OUTCOME': 'success', 'ARGV_LOG': str(log)}
            self.run_script(script(step_with_id(self.collector, 'health')), root, outcomes, record=True)
            args = json.loads(log.read_text().splitlines()[0])
            self.assertEqual(args[-2:], ['--input-error', 'cached_metadata_failed'])

    def test_actual_readonly_ledger_program_cannot_save_missing_empty_or_corrupt_state(self):
        source = script(step_with_id(self.collector, 'ledger'))
        for variant, expected in [('missing', False), ('empty-file', False), ('corrupt', False), ('no-initialization', False),
                                  ('initialized', True), ('partial-initialization', True), ('missing-request-table', False)]:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); state = root / '.state'; state.mkdir(); path = state / 'catalog.sqlite'; output = root / 'output'
                if variant == 'empty-file':
                    path.touch()
                elif variant == 'corrupt':
                    path.write_bytes(b'Not a SQLite database')
                elif variant != 'missing':
                    with sqlite3.connect(path) as db:
                        db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                        if variant != 'missing-request-table':
                            db.execute('CREATE TABLE requests (at INTEGER,endpoint TEXT,status INTEGER)')
                        if variant != 'no-initialization':
                            db.execute('INSERT INTO meta VALUES (?,?)', ('pilot_started', '1795190400'))
                        if variant == 'partial-initialization':
                            db.execute('INSERT INTO requests VALUES (?,?,?)', (1795190400, '/countries/in', 0))
                original = path.read_bytes() if path.exists() else None
                self.run_script(source, root, {'GITHUB_OUTPUT': str(output)})
                self.assertEqual(output.read_text(), 'valid=' + str(expected).lower() + '\n')
                self.assertEqual(path.read_bytes() if path.exists() else None, original, 'Read-only validation cannot initialize or rewrite a ledger')
        save = next(step for step in steps(self.collector) if 'uses: actions/cache/save@' in step)
        self.assertTrue(condition(save, {'steps.ledger.outputs.valid': 'true'}))
        for invalid in ('false', ''):
            self.assertFalse(condition(save, {'steps.ledger.outputs.valid': invalid}))

    def test_actual_collector_exit_gate_breaks_historical_failure_loop_but_fails_current_critical_causes(self):
        gate = next(step for step in steps(self.collector) if 'name: Fail visibly when freshness is critical' in step)
        cases = [([], 'normal', False),
                 ([{'code': 'collector_workflow_failed', 'severity': 'critical'}], 'critical', False),
                 ([{'code': 'new_feed_stale', 'severity': 'critical'}], 'critical', True),
                 ([{'code': 'collector_workflow_failed', 'severity': 'critical'},
                   {'code': 'new_feed_stale', 'severity': 'critical'}], 'critical', True)]
        for causes, status, fails in cases:
            with self.subTest(causes=causes), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root / 'reports').mkdir()
                (root / 'reports/catalogue-health.json').write_text(json.dumps({'status': status, 'causes': causes}))
                if fails:
                    with self.assertRaises(subprocess.CalledProcessError) as failure:
                        self.run_script(script(gate), root, {})
                    self.assertEqual(failure.exception.returncode, 1)
                else:
                    self.run_script(script(gate), root, {})

    def test_actual_independent_watchdog_exit_gate_still_fails_any_critical_report(self):
        gate = next(step for step in steps(self.watchdog) if 'name: Make critical lag visible in workflow notifications' in step)
        for status, causes in [('normal', []), ('warning', []),
                               ('critical', [{'code': 'collector_workflow_failed', 'severity': 'critical'}])]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); (root / 'reports').mkdir()
                (root / 'reports/catalogue-health.json').write_text(json.dumps({'status': status, 'causes': causes}))
                if status == 'critical':
                    with self.assertRaises(subprocess.CalledProcessError) as failure:
                        self.run_script(script(gate), root, {})
                    self.assertEqual(failure.exception.returncode, 1)
                else:
                    self.run_script(script(gate), root, {})


if __name__ == '__main__':
    unittest.main()
