import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import fetch_public_catalogue as fetcher


class SnapshotDownloadTests(unittest.TestCase):
    def test_transient_public_get_retries_with_a_new_cache_key_but_invalid_json_does_not(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true}'
        error = HTTPError(fetcher.BASE + '/data/catalog.json', 503, 'Unavailable', {}, None)
        with patch.object(fetcher, 'build_opener') as opener, patch.object(fetcher.time, 'sleep') as sleep:
            opener.return_value.open.side_effect = [error, response]
            self.assertEqual(fetcher.get_json('/data/catalog.json', 100), {'ok': True})
            calls = opener.return_value.open.call_args_list
            self.assertEqual(len(calls), 2)
            self.assertNotEqual(calls[0].args[0].full_url, calls[1].args[0].full_url)
            sleep.assert_called_once_with(1)
        response.__enter__.return_value.read.return_value = b'not json'
        with patch.object(fetcher, 'build_opener') as opener:
            opener.return_value.open.return_value = response
            with self.assertRaises(ValueError): fetcher.get_json('/data/catalog.json', 100)
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_optional_status_failure_does_not_block_a_valid_catalogue(self):
        root, catalog = self.fixture()
        error = HTTPError(fetcher.BASE + '/data/catalogue-health.json', 503, 'Unavailable', {}, None)
        with patch.object(fetcher, 'get_json', side_effect=[catalog, None, error]):
            self.assertEqual(fetcher.main(['--root', str(root)]), 0)
        self.assertEqual(json.loads((root / 'data/catalog.json').read_text()), catalog)
        self.assertFalse((root / 'reports/previous-public-health.json').exists())
        self.assertFalse((root / 'data/catalogue-health.json').exists())

    def fixture(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name); (root / 'data').mkdir()
        (root / 'data/official-listings.json').write_text(json.dumps([{'platform': 'Netflix', 'platformTitleId': '123'}]))
        catalog = {'schemaVersion': 1, 'mode': 'live', 'titles': [{'id': 'motn:1'}],
                   'officialListingAliases': {'netflix:123': 'motn:1'}}
        return root, catalog

    def test_first_deployment_without_optional_files_preserves_valid_catalogue(self):
        root, catalog = self.fixture()
        with patch.object(fetcher, 'get_json', side_effect=[catalog, None, None]):
            self.assertEqual(fetcher.main(['--root', str(root)]), 0)
        self.assertEqual(json.loads((root / 'data/catalog.json').read_text()), catalog)

    def test_missing_automatic_evidence_does_not_silently_drop_published_titles(self):
        root, catalog = self.fixture()
        previous = b'{"previous":"untouched"}'
        (root / 'data/catalog.json').write_bytes(previous)
        catalog['officialListingAliases']['sonyliv:123'] = 'motn:official-sonyliv-123'
        with patch.object(fetcher, 'get_json', side_effect=[catalog, None, None]):
            with self.assertRaisesRegex(ValueError, 'Automatic evidence registry is missing'):
                fetcher.main(['--root', str(root)])
        self.assertEqual((root / 'data/catalog.json').read_bytes(), previous)

    def test_invalid_companion_data_never_overwrites_an_existing_snapshot(self):
        root, catalog = self.fixture()
        target = root / 'data/catalog.json'; target.write_text('old snapshot')
        with patch.object(fetcher, 'get_json', side_effect=[catalog, {'not': 'a registry'}, None]):
            with self.assertRaises(ValueError): fetcher.main(['--root', str(root)])
        self.assertEqual(target.read_text(), 'old snapshot')

    def test_mixed_cdn_versions_cannot_strip_an_active_automatic_offer(self):
        for platform, identity in [('SonyLIV', 'sonyliv:456'), ('Netflix', 'netflix:123')]:
            with self.subTest(identity=identity):
                root, catalog = self.fixture()
                proof = {'platform': platform, 'platformTitleId': identity.split(':')[1],
                         'sourceURL': 'https://official.example/title', 'releaseDate': '2026-11-20',
                         'releaseEvidenceURL': 'https://official.example/release', 'verifiedAt': 200, 'expiresAt': 300}
                catalog['officialListingAliases'] = {identity: 'motn:1'}
                catalog['titles'][0]['officialListing'] = {**proof, 'active': True}
                target = root / 'data/catalog.json'; target.write_text('previous good snapshot')
                for companion in [[], [{**proof, 'verifiedAt': 100}]]:
                    with patch.object(fetcher, 'get_json', side_effect=[catalog, companion, None]):
                        with self.assertRaisesRegex(ValueError, 'does not match the catalogue'):
                            fetcher.main(['--root', str(root)])
                    self.assertEqual(target.read_text(), 'previous good snapshot')
                with patch.object(fetcher, 'get_json', side_effect=[catalog, [proof], None]):
                    self.assertEqual(fetcher.main(['--root', str(root)]), 0)
                self.assertEqual(json.loads(target.read_text()), catalog)
