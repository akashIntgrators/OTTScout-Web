import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts import official_discovery as d
from scripts import sony_india_relay as r
from scripts.sony_india_transport import SonyIndiaTransport

FIXTURES=json.loads((Path(__file__).parent/'fixtures/official_discovery/sony-public-2026-11-20.json').read_text())['fixtures']
MOVIES=next(url for url,kind in r.INDEXES.items() if kind=='Movie')


class SonyRelayTests(unittest.TestCase):
    def test_budget_persists_across_sessions_and_counts_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger'
            ledger=r.Ledger(path,now=lambda:10000)
            relay=r.Relay(ledger,fetch=lambda url: (_ for _ in ()).throw(r.RelayError('network')))
            for _ in range(12):
                with self.assertRaisesRegex(r.RelayError,'network'): relay.get(MOVIES)
            with self.assertRaisesRegex(r.RelayError,'request-budget'): relay.get(MOVIES)
            ledger.close()
            ledger=r.Ledger(path,now=lambda:10001)
            with self.assertRaisesRegex(r.RelayError,'request-budget'): ledger.reserve()
            ledger.close()
            ledger=r.Ledger(path,now=lambda:10000+r.WINDOW)
            ledger.reserve(); self.assertEqual(len(ledger.data['requests']),1); ledger.close()

    def test_six_hour_limit_is_rolling_across_a_fixed_window_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=[100000]
            ledger=r.Ledger(Path(tmp)/'ledger',now=lambda:now[0])
            ledger.reserve()
            now[0]+=r.WINDOW-1
            for _ in range(11): ledger.reserve()
            with self.assertRaisesRegex(r.RelayError,'request-budget'):ledger.reserve()
            now[0]+=1
            ledger.reserve()  # Only the oldest request expired.
            with self.assertRaisesRegex(r.RelayError,'request-budget'):ledger.reserve()
            ledger.close()

    def test_only_india_index_authorizes_linked_titles_and_resolved_movie(self):
        docs={v['sourceURL']:v['html'].encode() for v in FIXTURES.values()}
        docs[r.ROBOTS]=b'User-agent: *\nAllow: /\n'
        calls=[]
        def fetch(url):
            calls.append(url);return (200,None,docs[url])
        with tempfile.TemporaryDirectory() as tmp:
            ledger=r.Ledger(Path(tmp)/'ledger')
            relay=r.Relay(ledger,fetch=fetch)
            candidate=d.parse_sony_index(FIXTURES['movie-index']['html'], MOVIES, 'Movie')[0]
            with self.assertRaisesRegex(r.RelayError,'not-authorized'):relay.get(candidate['url'])
            relay.get(MOVIES)
            relay.get(candidate['url'])
            resolved=d.verify_sony(FIXTURES['movie-bundle']['html'],candidate,int(time.time()))['resolveURL']
            self.assertIn(resolved,relay.authorized)
            with self.assertRaisesRegex(r.RelayError,'not-authorized'):relay.get('https://www.sonyliv.com/movies/not-indexed-123')
            self.assertEqual(calls.count(r.ROBOTS),1)
            self.assertEqual(len(ledger.data['requests']),3)
            ledger.close()

    def test_non_india_index_never_authorizes_candidates(self):
        html=FIXTURES['movie-index']['html'].replace('"country":"India"','"country":"United States"').replace('"country": "India"','"country": "United States"')
        # Verify the simulated response actually violates the independent gate.
        with self.assertRaises(d.DiscoveryError):d.sony_state(html)
        with tempfile.TemporaryDirectory() as tmp:
            ledger=r.Ledger(Path(tmp)/'ledger')
            relay=r.Relay(ledger,fetch=lambda url:(200,None,b'User-agent: *\nAllow: /\n' if url==r.ROBOTS else html.encode()))
            relay.get(MOVIES)
            self.assertEqual(relay.authorized,set(r.INDEXES))
            ledger.close()

    def test_robots_denial_and_redirect_cannot_expand_network_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger=r.Ledger(Path(tmp)/'ledger')
            relay=r.Relay(ledger,fetch=lambda url:(200,None,b'User-agent: *\nDisallow: /custompage/\n'))
            with self.assertRaisesRegex(r.RelayError,'robots-blocked'):relay.get(MOVIES)
            self.assertEqual(len(ledger.data['requests']),1)
            ledger.close()
        with tempfile.TemporaryDirectory() as tmp:
            ledger=r.Ledger(Path(tmp)/'ledger')
            relay=r.Relay(ledger,fetch=lambda url:(200,None,b'User-agent: *\nAllow: /') if url==r.ROBOTS else (302,'https://example.com',b''))
            with self.assertRaisesRegex(r.RelayError,'redirect-not-authorized'):relay.get(MOVIES)
            self.assertEqual(len(ledger.data['requests']),2)
            ledger.close()

    def test_session_deadline_during_fetch_releases_lock_even_if_client_stays_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger'
            code = """from scripts import sony_india_relay as r
import time
class SlowRelay:
    def __init__(self, ledger): pass
    def get(self, url): time.sleep(10)
try: r.serve(%r, session_seconds=0.3, relay_factory=SlowRelay)
except r.SessionExpired: pass
""" % str(path)
            process=subprocess.Popen([sys.executable,'-u','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                process.stdin.write(b'{"id":1,"url":"test"}\n');process.stdin.flush()
                self.assertEqual(process.wait(timeout=3),0)
                ledger=r.Ledger(path);ledger.close()
            finally:
                process.kill();process.communicate()

    def test_corrupt_ledger_and_concurrent_session_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'ledger';ledger=r.Ledger(path)
            with self.assertRaisesRegex(r.RelayError,'busy'):r.Ledger(path)
            ledger.close();path.write_text('invalid')
            with self.assertRaisesRegex(r.RelayError,'ledger'):r.Ledger(path)


class TransportTests(unittest.TestCase):
    def run_reply(self,reply):
        transport=SonyIndiaTransport('user@example.com','/tmp/identity','/tmp/known_hosts')
        script='import sys; sys.stdin.readline(); print('+repr(json.dumps(reply))+',flush=True)'
        def start():
            transport.process=subprocess.Popen([sys.executable,'-u','-c',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
        transport.start=start
        try:
            return transport(MOVIES,{'If-None-Match':'old-region'},3,100,time.monotonic()+3)
        finally:transport.close()

    def test_success_decodes_only_bounded_explicit_body(self):
        self.assertEqual(self.run_reply({'id':1,'status':200,'body':'SW5kaWE='}),(200,{},b'India'))

    def test_discovery_over_real_local_relay_keeps_html_ephemeral_and_no_paid_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp); ledger=base/'ledger'; state=base/'state'
            transport=SonyIndiaTransport('user@example.com','/tmp/identity','/tmp/known_hosts')
            code = """from scripts import sony_india_relay as r
from pathlib import Path
import json
fixtures=json.loads(Path('tests/fixtures/official_discovery/sony-public-2026-11-20.json').read_text())['fixtures']
docs={v['sourceURL']:v['html'].encode() for v in fixtures.values()}
docs[r.ROBOTS]=b'User-agent: *\\nAllow: /\\n'
def fetch(url): return (200,None,docs[url]) if url in docs else (404,None,b'')
class FixtureRelay(r.Relay):
    def __init__(self,ledger): super().__init__(ledger,fetch=fetch)
r.serve(%r,relay_factory=FixtureRelay)
""" % str(ledger)
            def start():
                if transport.process is not None: return
                transport.process=subprocess.Popen([sys.executable,'-u','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
            transport.start=start
            try:
                with tempfile.TemporaryDirectory(dir=base) as http:
                    client=d.PublicClient(http,int(time.time()),transport=transport)
                    with patch('scripts.official_discovery.public_get',side_effect=AssertionError('no paid or direct request')):
                        records,report=d.discover(state,int(time.time()),sources=[next(x for x in d.DEFAULT_SOURCES if x['id']=='sony-movies')],client=client)
                    self.assertGreater(report['sources'][0]['candidates'],0)
                    self.assertIsNotNone(report['sources'][0]['lastSuccessAt'])
                    self.assertEqual(report['providerApiRequests'],0)
                    self.assertGreaterEqual(len(json.loads(ledger.read_text())['requests']),3)
                self.assertFalse(Path(http).exists())
                for file in state.rglob('*'):
                    if file.is_file(): self.assertNotIn('window.INITIAL_STATE',file.read_text())
            finally: transport.close()

    def test_unreachable_relay_does_not_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            def unavailable(*args): raise d.DiscoveryError('relay-unavailable','Sony India relay unavailable')
            client=d.PublicClient(Path(tmp)/'http',int(time.time()),transport=unavailable)
            _,report=d.discover(tmp,int(time.time()),sources=[next(x for x in d.DEFAULT_SOURCES if x['id']=='sony-movies')],client=client)
            self.assertEqual(report['sources'][0]['status'],'error')
            self.assertIsNone(report['sources'][0]['lastSuccessAt'])
            self.assertEqual(report['providerApiRequests'],0)

    def test_cross_region_304_and_unexpected_fields_are_rejected(self):
        for reply in ({'id':1,'status':304,'body':''}, {'id':1,'status':200,'body':'SW5kaWE=','cookie':'private'}):
            with self.subTest(reply=reply),self.assertRaises(d.DiscoveryError):self.run_reply(reply)


if __name__=='__main__': unittest.main()
