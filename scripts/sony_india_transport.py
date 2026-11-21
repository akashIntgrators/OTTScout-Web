"""Bounded SSH transport for India-observed public Sony HTML only."""
import base64
import binascii
import json
import os
import re
import select
import subprocess
import time
from urllib.parse import urlsplit

try:
    from .official_discovery import DiscoveryError, public_get, safe_header
except ImportError:
    from official_discovery import DiscoveryError, public_get, safe_header

MAX_LINE = 5_400_000


class SonyIndiaTransport:
    def __init__(self, host, identity, known_hosts):
        if (not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,255}', host or '') or host.startswith('-') or
            not os.path.isabs(identity) or not os.path.isabs(known_hosts)):
            raise DiscoveryError('relay-config', 'Sony India relay configuration is invalid')
        self.host, self.identity, self.known_hosts = host, identity, known_hosts
        self.process = None
        self.sequence = 0
        self.pending = b''

    def start(self):
        if self.process is not None:
            return
        try:
            self.process = subprocess.Popen(['ssh', '-F', '/dev/null', '-T',
                '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'GlobalKnownHostsFile=/dev/null',
                '-o', 'UserKnownHostsFile=' + self.known_hosts,
                '-o', 'ClearAllForwardings=yes', '-o', 'ForwardAgent=no',
                '-o', 'ConnectTimeout=10', '-i', self.identity, self.host],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        except OSError:
            raise DiscoveryError('relay-unavailable', 'Sony India relay unavailable') from None

    def close(self):
        if self.process is not None:
            self.process.kill()
            self.process.communicate()
            self.process = None

    def __call__(self, url, headers, timeout, maximum, deadline):
        if urlsplit(url).hostname not in ('www.sonyliv.com', 'sonyliv.com'):
            return public_get(url, headers, timeout, maximum, deadline)
        self.start()
        self.sequence += 1
        end = min(deadline, time.monotonic() + timeout)
        request = json.dumps({'id': self.sequence, 'url': url}, separators=(',', ':')).encode() + b'\n'
        try:
            if time.monotonic() >= end or not select.select([], [self.process.stdin], [], max(0, end-time.monotonic()))[1]:
                raise OSError()
            if os.write(self.process.stdin.fileno(), request) != len(request):
                raise OSError()
            while b'\n' not in self.pending:
                if len(self.pending) > MAX_LINE or not select.select([self.process.stdout], [], [], max(0, end-time.monotonic()))[0]:
                    raise OSError()
                data = os.read(self.process.stdout.fileno(), min(65536, MAX_LINE+1-len(self.pending)))
                if not data:
                    raise OSError()
                self.pending += data
            line, self.pending = self.pending.split(b'\n', 1)
            if self.pending or len(line) > MAX_LINE:
                raise ValueError()
            response = json.loads(line)
            if not isinstance(response, dict) or response.get('id') != self.sequence or type(response.get('id')) is not int:
                raise ValueError()
            if set(response) == {'id', 'error'} and isinstance(response['error'], str):
                raise DiscoveryError('relay-unavailable', 'Sony India relay could not verify this request')
            if not set(response) in ({'id', 'status', 'body'}, {'id', 'status', 'body', 'location'}):
                raise ValueError()
            status = response['status']
            if type(status) is not int or status not in (200, 301, 302, 303, 307, 308, 404):
                raise ValueError()
            body = base64.b64decode(response['body'], validate=True)
            if len(body) > maximum or (status != 200 and body):
                raise ValueError()
            location = response.get('location')
            if location is not None and not safe_header(location):
                raise ValueError()
            return status, {'location': location} if location else {}, body
        except (OSError, ValueError, TypeError, binascii.Error, BrokenPipeError):
            self.close()
            raise DiscoveryError('relay-unavailable', 'Sony India relay returned an invalid response') from None
