import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import fetch_public_catalogue as fetcher


class SnapshotDownloadTests(unittest.TestCase):
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
