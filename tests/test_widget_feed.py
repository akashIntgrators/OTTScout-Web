"""The Android widget gets a bounded public feed, with offer-level evidence."""
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_site


NOW = 1793952000
DAY = 86400


def offer(platform='Netflix', audio=None, **values):
    return {'platform': platform, 'type': 'subscription', 'audio': ['Hindi'] if audio is None else audio,
            'subtitles': [], **values}


def title(ident='motn:42', **values):
    return {'id': ident, 'title': 'A weekly film', 'type': 'Movie',
            'weekly': True, 'weeklyUpdatedAt': NOW - 10, 'weeklyPlatforms': ['Netflix'],
            'offers': [offer()], **values}


def catalogue(titles):
    return {'schemaVersion': 1, 'mode': 'live', 'updatedAt': '2026-11-06T00:00:00+00:00',
            'coverage': ['Netflix', 'Prime Video', 'Sun NXT'], 'missingPlatforms': ['Sun NXT'],
            'titles': titles}


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def newest_check(**overrides):
    return {'checkedAt': iso(NOW - 5), 'from': iso(NOW - 5 - 48 * 3600), 'to': iso(NOW - 5),
            'hasMore': True, 'events': 25, 'oldestEventAt': iso(NOW - 50),
            'newestEventAt': iso(NOW - 10), 'order': 'desc', 'pages': 1, 'scope': 'last48h', **overrides}


class WidgetFeedTests(unittest.TestCase):
    def decode(self, source):
        return json.loads(build_site.widget_feed(source, NOW))

    def test_feed_uses_only_each_current_weekly_offer_and_its_audio(self):
        row = title(weeklyEvents=[{'platform': 'Netflix', 'addedAt': NOW - 10},
                                 {'platform': 'Prime Video', 'addedAt': NOW - 20},
                                 {'platform': 'Sun NXT', 'addedAt': NOW - 30}],
                    offers=[offer(availableSince=NOW - 8 * DAY),
                            offer('Prime Video', ['Telugu'], type='rent', availableSince=NOW - 20),
                            offer('Prime Video', ['Tamil'], type='buy', expiresOn=NOW),
                            offer('Prime Video', ['French']),
                            offer('Sun NXT', ['Hindi'])])
        result = self.decode(catalogue([row]))
        self.assertEqual(result['coverage'], ['Netflix', 'Prime Video'])
        self.assertEqual(result['titles'][0]['offers'], [
            {'platform': 'Prime Video', 'type': 'rent', 'audio': ['Telugu'],
             'addedAt': NOW - 20, 'expiresOn': None}])
        self.assertEqual(result['updatedAt'], '2026-11-06T00:00:00+00:00')
        self.assertEqual(result['generatedAt'], '2026-11-06T08:00:00+00:00')

    def test_provider_page_observation_keeps_its_partial_scope_and_complete_watermark(self):
        source = catalogue([title()])
        source['latestNewCheck'] = newest_check(privateIgnoredField='must not escape')
        result = self.decode(source)
        self.assertEqual(result['schemaVersion'], 1)
        self.assertEqual(result['latestNewCheck'], newest_check())
        self.assertTrue(result['latestNewCheck']['hasMore'])
        self.assertEqual(result['updatedAt'], source['updatedAt'])
        self.assertNotEqual(result['latestNewCheck']['checkedAt'], result['generatedAt'])

    def test_zero_event_check_is_valid_without_event_dates(self):
        source = catalogue([title()])
        source['latestNewCheck'] = newest_check(events=0, hasMore=False, oldestEventAt=None, newestEventAt=None)
        self.assertEqual(self.decode(source)['latestNewCheck'], source['latestNewCheck'])

    def test_invalid_observations_and_legacy_feeds_cannot_claim_a_new_provider_check(self):
        invalid = [None, 'not a check', {}, newest_check(checkedAt=iso(NOW + 1), to=iso(NOW + 1)),
                   newest_check(**{'from': iso(NOW - 48 * 3600)}),
                   newest_check(order='asc'), newest_check(pages=True), newest_check(pages=2),
                   newest_check(events=26), newest_check(events=True), newest_check(hasMore='false'),
                   newest_check(scope='all'), newest_check(newestEventAt=iso(NOW)),
                   newest_check(oldestEventAt=iso(NOW - 49 * 3600)),
                   newest_check(events=0), newest_check(newestEventAt=None)]
        for check in invalid:
            with self.subTest(check=check):
                source = {**catalogue([title()]), 'latestNewCheck': check}
                result = self.decode(source)
                self.assertNotIn('latestNewCheck', result)
                self.assertEqual(result['updatedAt'], source['updatedAt'])
        self.assertNotIn('latestNewCheck', self.decode(catalogue([title()])))

    def test_weekly_window_includes_boundary_but_never_falls_back_to_older_titles(self):
        rows = [title('motn:boundary', weeklyUpdatedAt=NOW - 7 * DAY),
                title('motn:expired', weeklyUpdatedAt=NOW - 7 * DAY - 1),
                title('motn:future', offers=[offer(availableSince=NOW + 1)]),
                title('motn:older', weeklyUpdatedAt=NOW - 20 * DAY)]
        self.assertEqual([row['id'] for row in self.decode(catalogue(rows))['titles']], ['motn:boundary'])
        self.assertEqual(self.decode(catalogue(rows[1:]))['titles'], [])

    def test_unknown_audio_is_preserved_without_guessing_original_language(self):
        row = title(originalLanguage='Telugu', overview='Not needed by the widget',
                    offers=[offer(audio=[], type='free')], poster='https://cdn.movieofthenight.com/poster.jpg')
        result = self.decode(catalogue([row]))['titles'][0]
        self.assertEqual(result['offers'][0]['audio'], [])
        self.assertNotIn('originalLanguage', result)
        self.assertNotIn('overview', result)
        self.assertEqual(result['poster'], row['poster'])

    def test_widget_images_only_use_known_public_https_cdns(self):
        for unsafe in ('http://cdn.movieofthenight.com/a.jpg', 'https://localhost/a.jpg',
                       'https://127.0.0.1/a.jpg', 'https://cdn.movieofthenight.com.evil.test/a.jpg',
                       'https://name:password@image.tmdb.org/a.jpg', 'https://image.tmdb.org:8443/a.jpg',
                       'file:///private/a.jpg', 'https://image.tmdb.org:bad/a.jpg'):
            with self.subTest(unsafe=unsafe):
                self.assertNotIn('poster', self.decode(catalogue([title(poster=unsafe)]))['titles'][0])

    def test_size_and_duplicate_errors_abort_instead_of_silently_losing_titles(self):
        source = catalogue([title('motn:a'), title('motn:b')])
        with patch.object(build_site, 'WIDGET_MAX_TITLES', 1), self.assertRaises(ValueError):
            build_site.widget_feed(source, NOW)
        with patch.object(build_site, 'WIDGET_MAX_BYTES', 100), self.assertRaises(ValueError):
            build_site.widget_feed(source, NOW)
        with self.assertRaises(ValueError):
            build_site.widget_feed(catalogue([title(), title()]), NOW)

    def test_site_build_publishes_widget_feed_without_private_or_full_catalogue_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('index.html', 'app.js', 'style.css', 'CNAME'):
                (root / name).write_text('')
            (root / 'data').mkdir()
            source = catalogue([title()])
            source['privateIgnoredField'] = 'not part of widget contract'
            original = json.dumps(source)
            (root / 'data/catalog.json').write_text(original)
            site = build_site.build(root, NOW)
            result = json.loads((site / 'data/widget.json').read_text())
            self.assertEqual(set(result), {'schemaVersion', 'country', 'updatedAt', 'generatedAt', 'coverage', 'titles'})
            self.assertEqual(result['country'], 'IN')
            self.assertNotIn('privateIgnoredField', result)
            self.assertEqual((root / 'data/catalog.json').read_text(), original)
            privacy = (site / 'privacy/index.html').read_text()
            self.assertIn('home-screen widgets store a public weekly-catalogue snapshot', privacy)
            self.assertIn('Widgets do not read your account, sign-in credentials or watchlist', privacy)
            self.assertIn('widgets and watch views add no analytics or advertising requests', privacy)


if __name__ == '__main__':
    unittest.main()
