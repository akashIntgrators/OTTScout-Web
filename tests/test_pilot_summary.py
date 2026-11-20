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
            'collectorMode': 'continuous', 'scheduleHours': 6, 'newCheckHours': 12,
            'runs': [{'status': 'limited', 'requests': 4, 'message': 'Maintenance deferred'}],
            'requestBudget': {'conservationMode': True, 'newFeedDailyLimit': 6,
                              'newFeedRequestsToday': 6, 'newFeedRequestsRemainingToday': 0,
                              'protectedFutureDailyTarget':4, 'plannedPerFutureDay':2, 'protectedFutureDays':10,
                              'protectedFutureRequests':22, 'emergencyReserve':2, 'catchupDailyLimit':6, 'capacityInsufficient':True},
            'streamingFreshness': {
                'new': {'completedThrough': '2026-11-18T00:00:00+00:00', 'pendingWindow': {'pages':4},
                        'publicationMode':'incremental-pages', 'publishedPages':4, 'stagedPages':0, 'deferredByConservation': True},
                'removed': {'completedThrough': '2026-11-13T00:00:00+00:00',
                            'pendingWindow': {'pages': 5}, 'deferredByConservation': True},
            },
            'newPublication':{'pages':6,'recoveredPages':2,'changedRecords':8},
        }
        text = summary.build_summary(report)
        self.assertIn('12-hour UTC slots', text)
        self.assertIn('does not mean every feed is current', text)
        self.assertIn('6 / 6', text)
        self.assertIn('Nominal future-day freshness target: 4 requests/day',text)
        self.assertIn('Affordable plan per future UTC day: 2 requests/day',text)
        self.assertIn('Protected future allowance, including emergency reserve: 22',text)
        self.assertIn('Capacity is insufficient',text)
        self.assertIn('| new | 2026-11-18T00:00:00+00:00 | 4 | 4 | 0 | yes |', text)
        self.assertIn('| removed | 2026-11-13T00:00:00+00:00 | 5 | — | 5 | yes |', text)
        self.assertIn('NEW pages published (cumulative): 6',text)
        self.assertIn('recovered without API calls (cumulative): 2',text)
        self.assertIn('does not advance a feed completion watermark',text)

    def test_legacy_report_does_not_claim_a_daily_allowance_or_current_feeds(self):
        text = summary.build_summary({'scheduleHours': 6, 'runs': [{'status': 'success'}]})
        self.assertIn('6-hour UTC slots', text)
        self.assertNotIn('Quota conservation is active', text)
        self.assertNotIn('### Feed completion', text)

    def test_older_partial_reports_do_not_mislabel_downloaded_new_pages_as_published(self):
        text=summary.build_summary({'streamingFreshness':{'new':{'pendingWindow':{'pages':2}}}})
        self.assertIn('| new | none | 2 | not recorded | not recorded | no |',text)
        self.assertNotIn('NEW pages published (cumulative)',text)

    def test_affordable_nominal_plan_does_not_claim_degraded_capacity(self):
        text=summary.build_summary({'collectorMode':'continuous','newCheckHours':6,
            'requestBudget':{'conservationMode':True,'plannedPerFutureDay':4,'protectedFutureDailyTarget':4,
                             'capacityInsufficient':False,'newFeedDailyLimit':6,'newFeedRequestsToday':1,'newFeedRequestsRemainingToday':5}})
        self.assertIn('6-hour UTC slots',text)
        self.assertIn('Affordable plan per future UTC day: 4 requests/day',text)
        self.assertNotIn('Capacity is insufficient',text)
