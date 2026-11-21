"""Sony-only, bounded public-page relay. Run solely as a restricted SSH command.

The server is an observation endpoint, not an authority that can attest its own
location. The caller must independently apply all Sony verification checks.
"""
import base64
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, ProxyHandler, build_opener

try:
    from .official_discovery import (DiscoveryError, NoRedirect, USER_AGENT, parse_sony_index,
                                     robots_policy, safe_header, verify_sony)
except ImportError:
    from official_discovery import (DiscoveryError, NoRedirect, USER_AGENT, parse_sony_index,
                                    robots_policy, safe_header, verify_sony)

INDEXES = {
    'https://www.sonyliv.com/custompage/movies-399': 'Movie',
    'https://www.sonyliv.com/custompage/tv-shows-32990': 'Series',
}
ROBOTS = 'https://www.sonyliv.com/robots.txt'
WINDOW = 6 * 3600
LIMIT = 12
MAX_DOCUMENT = 4_000_000
MAX_TOTAL = 24_000_000
MAX_REQUEST_LINE = 4096


class RelayError(Exception):
    pass


class SessionExpired(Exception):
    pass


class Ledger:
    """Exclusive lock for the entire session; commit usage before each GET."""
    def __init__(self, path, now=time.time):
        self.now = now
        p = Path(path)
        if not p.is_absolute():
            raise RelayError('ledger')
        self.fd = os.open(p, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        info = os.fstat(self.fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.close(self.fd)
            raise RelayError('ledger')
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(self.fd)
            raise RelayError('busy') from None
        try:
            raw = os.read(self.fd, 4097)
            if len(raw) > 4096:
                raise ValueError()
            current = int(now())
            self.data = json.loads(raw) if raw else {'last': current, 'requests': []}
            if (not isinstance(self.data, dict) or set(self.data) != {'last', 'requests'} or
                type(self.data['last']) is not int or self.data['last'] > current or
                not isinstance(self.data['requests'], list) or len(self.data['requests']) > LIMIT or
                any(type(item) is not int or item > self.data['last'] for item in self.data['requests']) or
                self.data['requests'] != sorted(self.data['requests'])):
                raise ValueError()
            if not raw:
                self._save()
        except (ValueError, OSError):
            self.close()
            raise RelayError('ledger') from None

    def _save(self):
        data = json.dumps(self.data, separators=(',', ':')).encode()
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.write(self.fd, data)
        os.ftruncate(self.fd, len(data))
        os.fsync(self.fd)

    def reserve(self):
        now = int(self.now())
        if now < self.data['last']:
            raise RelayError('ledger')
        recent = [stamp for stamp in self.data['requests'] if stamp > now-WINDOW]
        if len(recent) >= LIMIT:
            raise RelayError('request-budget')
        self.data = {'last': now, 'requests': recent + [now]}
        try:
            self._save()
        except OSError:
            raise RelayError('ledger') from None

    def close(self):
        os.close(self.fd)


class Relay:
    def __init__(self, ledger, fetch=None):
        self.ledger = ledger
        self.fetch = fetch or self._fetch
        self.deadline = time.monotonic() + 120
        self.total = 0
        self.robots = None
        self.last = 0
        self.authorized = set(INDEXES)
        self.candidates = {}

    def _fetch(self, url):
        # Ignore environment proxy settings, cookies and client-supplied headers.
        opener = build_opener(ProxyHandler({}), NoRedirect)
        try:
            response = opener.open(Request(url, headers={'User-Agent': USER_AGENT,
                'Accept': 'text/html, text/plain;q=0.9', 'Accept-Encoding': 'identity'}),
                timeout=max(.1, min(15, self.deadline-time.monotonic())))
        except HTTPError as error:
            response = error
        except (URLError, OSError):
            raise RelayError('network') from None
        with response:
            status = response.code
            if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                raise RelayError('encoding')
            location = safe_header(response.headers.get('Location'))
            body = b''
            if status == 200:
                chunks = []
                remaining = min(MAX_DOCUMENT, MAX_TOTAL-self.total)
                while True:
                    if time.monotonic() >= self.deadline:
                        raise RelayError('time-budget')
                    part = response.read(min(65536, remaining+1))
                    if not part:
                        break
                    remaining -= len(part)
                    if remaining < 0:
                        raise RelayError('byte-budget')
                    chunks.append(part)
                body = b''.join(chunks)
            return status, location, body

    def _get(self, url):
        if time.monotonic() >= self.deadline or self.total >= MAX_TOTAL:
            raise RelayError('budget')
        self.ledger.reserve()
        status, location, body = self.fetch(url)
        if type(status) is not int or status not in (200, 301, 302, 303, 307, 308, 404):
            raise RelayError('http-status')
        if not isinstance(body, bytes) or len(body) > MAX_DOCUMENT or self.total + len(body) > MAX_TOTAL:
            raise RelayError('byte-budget')
        self.total += len(body)
        return status, location, body

    def get(self, url):
        if not isinstance(url, str) or len(url) > 2048 or (url != ROBOTS and url not in self.authorized):
            raise RelayError('not-authorized')
        if self.robots is None:
            status, _, body = self._get(ROBOTS)
            if status not in (200, 404):
                raise RelayError('robots-unavailable')
            try:
                self.robots = body.decode('utf-8-sig') if status == 200 else ''
            except UnicodeError:
                raise RelayError('robots-unavailable') from None
            try:
                robots_policy(self.robots, ROBOTS)
            except DiscoveryError:
                raise RelayError('robots-unavailable') from None
        if url == ROBOTS:
            return 200, None, self.robots.encode('utf-8')
        try:
            allowed, pause = robots_policy(self.robots, url)
        except DiscoveryError:
            raise RelayError('robots-unavailable') from None
        if not allowed:
            raise RelayError('robots-blocked')
        wait = max(0, self.last + pause - time.monotonic())
        if time.monotonic() + wait >= self.deadline:
            raise RelayError('time-budget')
        if wait:
            time.sleep(wait)
        self.last = time.monotonic()
        status, location, body = self._get(url)
        if status in (301, 302, 303, 307, 308):
            # Redirects only preserve the already-authorized exact origin/path/query.
            target = urljoin(url, location or '')
            if target != url:
                raise RelayError('redirect-not-authorized')
            return status, location, body
        if status == 200:
            try:
                html = body.decode('utf-8-sig')
                if url in INDEXES:
                    for candidate in parse_sony_index(html, url, INDEXES[url]):
                        self.authorized.add(candidate['url'])
                        self.candidates[candidate['url']] = candidate
                        if candidate.get('episodeURL'):
                            self.authorized.add(candidate['episodeURL'])
                elif url in self.candidates:
                    result = verify_sony(html, self.candidates[url], int(time.time()))
                    if result.get('resolveURL'):
                        self.authorized.add(result['resolveURL'])
            except (DiscoveryError, UnicodeError, KeyError, TypeError, AttributeError, RecursionError):
                # Client will apply the same verification; never authorize from bad state.
                pass
        return status, None, body


def serve(ledger_path, *, session_seconds=120, relay_factory=Relay):
    # The session deadline also covers a silent SSH client and blocking I/O.
    def deadline_expired(signum, frame):
        raise SessionExpired()
    previous_handler = signal.signal(signal.SIGALRM, deadline_expired)
    signal.setitimer(signal.ITIMER_REAL, session_seconds)
    ledger = None
    try:
        ledger = Ledger(ledger_path)
        relay = relay_factory(ledger)
        while True:
            line = sys.stdin.buffer.readline(MAX_REQUEST_LINE + 1)
            if not line:
                break
            if len(line) > MAX_REQUEST_LINE or not line.endswith(b'\n'):
                break
            request = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) != {'id', 'url'} or type(request['id']) is not int or not 0 <= request['id'] < 1000:
                    break
                status, location, body = relay.get(request['url'])
                reply = {'id': request['id'], 'status': status, 'body': base64.b64encode(body).decode('ascii')}
                if location:
                    reply['location'] = location
            except (RelayError, ValueError) as error:
                reply = {'id': request.get('id', 0) if isinstance(request, dict) else 0,
                         'error': str(error) if isinstance(error, RelayError) else 'invalid-request'}
            sys.stdout.write(json.dumps(reply, separators=(',', ':')) + '\n')
            sys.stdout.flush()
    finally:
        if ledger is not None:
            ledger.close()
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


if __name__ == '__main__':
    # The SSH forced command must pass this one fixed absolute ledger path.
    if len(sys.argv) != 2:
        sys.exit(2)
    try:
        serve(sys.argv[1])
    except (OSError, RelayError, SessionExpired):
        sys.exit(1)
