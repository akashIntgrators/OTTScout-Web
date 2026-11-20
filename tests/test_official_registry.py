import json
from pathlib import Path
import tempfile
import unittest

from scripts.official_registry import load_records
from scripts.official_listings import OfficialListingError


class OfficialRegistryTests(unittest.TestCase):
    def fixture(self, curated, automatic):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name); (root / 'data').mkdir()
        (root / 'data/official-listings.json').write_text(json.dumps(curated))
        (root / 'data/official-discovered.json').write_text(json.dumps(automatic))
        return root

    def row(self, **changes):
        return {'id': 'motn:official-netflix-123', 'platform': 'Netflix', 'platformTitleId': '123',
                'type': 'Movie', 'title': 'Automatic title', **changes}

    def test_reviewed_correction_wins_and_input_is_independent(self):
        root = self.fixture([self.row(title='Reviewed title')], [self.row()])
        result = load_records(root)
        self.assertEqual([row['title'] for row in result], ['Reviewed title'])
        result[0]['title'] = 'Changed in memory'
        self.assertEqual(load_records(root)[0]['title'], 'Reviewed title')

    def test_existing_provider_id_remains_stable_for_saved_titles(self):
        root = self.fixture([], [self.row()])
        catalog = {'titles': [{'id': 'motn:777', 'type': 'Movie', 'offers': [
            {'platform': 'Netflix', 'link': 'https://www.netflix.com/title/123'}]}]}
        self.assertEqual(load_records(root, catalog)[0]['id'], 'motn:777')
        catalog['officialListingAliases'] = {'netflix:123': 'motn:official-netflix-123'}
        self.assertEqual(load_records(root, catalog)[0]['id'], 'motn:official-netflix-123')

    def test_conflicting_existing_ids_and_malformed_registry_fail_closed(self):
        root = self.fixture([], [self.row()])
        titles = [{'id': 'motn:' + str(i), 'type': 'Movie', 'offers': [
            {'platform': 'Netflix', 'link': 'https://www.netflix.com/title/123'}]} for i in (1, 2)]
        with self.assertRaises(OfficialListingError): load_records(root, {'titles': titles})
        (root / 'data/official-discovered.json').write_text('{}')
        with self.assertRaises(OfficialListingError): load_records(root)

    def test_missing_discovery_is_backward_compatible(self):
        root = self.fixture([self.row()], [])
        (root / 'data/official-discovered.json').unlink()
        self.assertEqual(load_records(root), [self.row()])

    def test_fresh_exact_source_can_renew_expired_review_without_breaking_saved_id(self):
        reviewed = self.row(id='motn:777', title='Reviewed title', verifiedAt=100, expiresAt=200)
        fresh = self.row(title='Current official title', verifiedAt=250, expiresAt=400)
        root = self.fixture([reviewed], [fresh])
        self.assertEqual(load_records(root, now=150), [reviewed])
        self.assertEqual(load_records(root, now=300), [{**fresh, 'id': 'motn:777'}])
