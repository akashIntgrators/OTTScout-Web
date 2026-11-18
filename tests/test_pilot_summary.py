"""The run summary must distinguish deployment success from feed freshness."""
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('pilot_summary', Path(__file__).parents[1] / 'scripts/pilot_summary.py')
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


class PilotSummaryTests(unittest.TestCase):
    def test_partial_conservation_report_shows_actual_cadence_and_feed_ages(self):
        report = {
            'collectorMode': 'continuous', 'scheduleHours': 6, 'newCheckHours': 24,
            'runs': [{'status': 'limited', 'requests': 2, 'message': 'Maintenance deferred'}],
            'requestBudget': {'conservationMode': True, 'newFeedDailyLimit': 2,
                              'newFeedRequestsToday': 2, 'newFeedRequestsRemainingToday': 0},
            'streamingFreshness': {
                'new': {'completedThrough': '2026-11-18T00:00:00+00:00', 'pendingWindow': None,
                        'deferredByConservation': False},
                'removed': {'completedThrough': '2026-11-13T00:00:00+00:00',
                            'pendingWindow': {'pages': 5}, 'deferredByConservation': True},
            },
        }
        text = summary.build_summary(report)
        self.assertIn('24-hour UTC slots', text)
        self.assertIn('does not mean every feed is current', text)
        self.assertIn('2 / 2', text)
        self.assertIn('| new | 2026-11-18T00:00:00+00:00 | 0 | no |', text)
        self.assertIn('| removed | 2026-11-13T00:00:00+00:00 | 5 | yes |', text)

    def test_legacy_report_does_not_claim_a_daily_allowance_or_current_feeds(self):
        text = summary.build_summary({'scheduleHours': 6, 'runs': [{'status': 'success'}]})
        self.assertIn('6-hour UTC slots', text)
        self.assertNotIn('Quota conservation is active', text)
        self.assertNotIn('### Feed completion', text)
