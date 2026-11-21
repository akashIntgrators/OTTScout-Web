"""Production CLI pause takes precedence over stale optional relay settings."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import official_discovery as discovery
from scripts import sony_india_transport


NOW = 1795287600
NETFLIX_ROBOTS = b'User-agent: *\nDisallow: /\n'


class SonyPauseIntegrationTests(unittest.TestCase):
    def run_paused_cli(self, stale_arguments):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cache = directory/'cache'
            cache.mkdir()
            cached_record = {'id':'motn:official-sonyliv-123', 'platform':'SonyLIV',
                             'platformTitleId':'123', 'type':'Movie',
                             'verifiedAt':NOW-3600, 'expiresAt':NOW+86400}
            source_history = {source['id']:{'lastAttemptAt':NOW-7200,'lastSuccessAt':NOW-7200}
                              for source in discovery.DEFAULT_SOURCES if source['adapter']=='sony'}
            saved = {'schemaVersion':1,'policyVersion':2,'records':{'sony-movies:123':cached_record},
                     'attempts':{},'sources':source_history}
            (cache/'state.json').write_text(json.dumps(saved))
            calls = []
            clients = []
            real_client = discovery.PublicClient

            def offline_http(url, headers, timeout, maximum, deadline):
                calls.append(url)
                self.assertEqual(url, 'https://www.netflix.com/robots.txt',
                                 'A paused Sony source must not reach even robots.txt')
                return 200, {}, NETFLIX_ROBOTS

            def client_factory(path, now, **options):
                self.assertNotIn('transport', options, 'Paused CLI must use no relay transport')
                client = real_client(path, now, transport=offline_http, **options)
                clients.append(client)
                return client

            arguments = ['official_discovery.py','--cache-dir',str(cache),
                         '--output',str(directory/'automatic.json'),'--report',str(directory/'report.json'),
                         '--now',str(NOW),*stale_arguments]
            with patch.object(sys,'argv',arguments), \
                 patch.object(discovery,'PublicClient',side_effect=client_factory), \
                 patch.object(sony_india_transport,'SonyIndiaTransport') as relay, \
                 patch.dict(sys.modules,{'sony_india_transport':sony_india_transport}), \
                 patch.object(discovery,'public_get',side_effect=AssertionError('No real network request')), \
                 patch('builtins.print'):
                discovery.main()
                relay.assert_not_called()

            self.assertEqual(len(clients),1)
            self.assertEqual(calls,['https://www.netflix.com/robots.txt'])
            self.assertEqual(json.loads((directory/'automatic.json').read_text()),[])
            report = json.loads((directory/'report.json').read_text())
            self.assertEqual(report['providerApiRequests'],0)
            self.assertEqual(report['publicRequests'],1)
            paused = [source for source in report['sources'] if source['platform']=='SonyLIV']
            self.assertEqual(len(paused),2)
            for source in paused:
                self.assertEqual(source['status'],'paused')
                self.assertEqual(source['pauseReason'],'permission-required')
                self.assertFalse(source['required'])
                self.assertEqual(source['attempted'],0)
                self.assertEqual(source['lastAttemptAt'],NOW-7200)
                self.assertEqual(source['lastSuccessAt'],NOW-7200)
            self.assertEqual(report['quarantinedRecords'][0]['id'],cached_record['id'])
            state = json.loads((cache/'state.json').read_text())
            self.assertEqual(state['records'],saved['records'])

    def test_partial_stale_relay_settings_are_ignored_before_validation_or_construction(self):
        variants = [
            ['--sony-ssh-host','invalid stale host'],
            ['--sony-ssh-identity','/nonexistent/stale-key'],
            ['--sony-ssh-known-hosts','/nonexistent/stale-hosts'],
            ['--sony-ssh-host','invalid stale host','--sony-ssh-identity','/nonexistent/stale-key'],
            ['--sony-ssh-host','invalid stale host','--sony-ssh-known-hosts','/nonexistent/stale-hosts'],
            ['--sony-ssh-identity','/nonexistent/stale-key','--sony-ssh-known-hosts','/nonexistent/stale-hosts'],
        ]
        for arguments in variants:
            with self.subTest(arguments=arguments):self.run_paused_cli(arguments)

    def test_full_stale_relay_settings_cannot_enable_paused_sources(self):
        self.run_paused_cli(['--sony-ssh-host','invalid stale host',
                             '--sony-ssh-identity','/nonexistent/stale-key',
                             '--sony-ssh-known-hosts','/nonexistent/stale-hosts'])


if __name__ == '__main__':unittest.main()
