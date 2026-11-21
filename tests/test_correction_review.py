from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import correction_review as review
from scripts.official_listings import OfficialListingError


NOW = 1795232627
REVIEWER = 'akashIntgrators'
URL = 'https://www.netflix.com/in/title/81749470'


def listing():
    return {'platform':'Netflix', 'platformTitleId':'81749470', 'title':'Guarding Stars', 'type':'Movie', 'year':2026,
        'sourceURL':URL, 'releaseDate':'2026-11-18', 'releaseEvidenceURL':'https://www.netflix.com/tudum/articles/new-on-netflix',
        'verifiedAt':NOW-60, 'expiresAt':NOW+7*review.DAY, 'access':{'type':'subscription','evidenceURL':URL},
        'audio':['English','Hindi'], 'audioEvidenceURL':URL, 'originalLanguage':None,'originalLanguageEvidenceURL':None}


def request():
    return {'schemaVersion':1, 'decision':'approve', 'issueURL':'https://github.com/akashIntgrators/OTTScout-Web/issues/42',
        'reviewedBy':REVIEWER, 'availability':'available-now-in-india', 'indiaEvidenceURL':URL, 'listing':listing()}


def catalogue():
    return {'schemaVersion':1,'mode':'live','titles':[{'id':'motn:900','title':'Guarding Stars','type':'Movie','year':2026,
        'lastCheckedAt':NOW-100,'offers':[{'platform':'Netflix','link':URL,'type':'subscription','audio':['Hindi']}],
        'weeklyEvents':[]}],'officialListingAliases':{}}


class CorrectionReviewTests(unittest.TestCase):
    def prepare(self, report=None, rows=None, catalog=None):
        return review.prepare_review(request() if report is None else report, [] if rows is None else rows,
            catalogue() if catalog is None else catalog, [], reviewer=REVIEWER, now=NOW)

    def test_exact_provider_identity_is_preserved_without_mutating_snapshot_or_audio(self):
        report=request(); catalog=catalogue(); original=deepcopy((report,catalog))
        rows,summary=self.prepare(report,catalog=catalog)
        self.assertEqual(rows[0]['id'],'motn:900')
        self.assertIsNone(rows[0]['originalLanguage'])
        self.assertEqual(rows[0]['audio'],['English','Hindi'])
        self.assertEqual((report,catalog),original)
        self.assertEqual(summary['providerApiRequests'],0)
        self.assertEqual(summary['tmdbRequests'],0)

    def test_new_title_uses_official_id_and_learned_alias_survives_absent_offer(self):
        report=request();report['listing']['platformTitleId']='81681910';report['listing']['sourceURL']='https://www.netflix.com/in/title/81681910'
        report['indiaEvidenceURL']=report['listing']['sourceURL'];report['listing']['access']['evidenceURL']=report['listing']['sourceURL']
        report['listing']['audio']=[];report['listing']['audioEvidenceURL']=None
        self.assertEqual(self.prepare(report)[0][0]['id'],'motn:official-netflix-81681910')
        catalog=catalogue();catalog['officialListingAliases']={'netflix:81749470':'motn:900'}
        catalog['titles'][0]['offers']=[{'platform':'Prime Video','link':'https://www.primevideo.com/detail/ABC','type':'subscription'}]
        self.assertEqual(self.prepare(catalog=catalog)[0][0]['id'],'motn:900')

    def test_existing_reviewed_identity_wins_and_update_keeps_all_other_rows(self):
        previous=listing();previous.update(id='motn:official-netflix-81749470',verifiedAt=NOW-1000)
        report=request();report['listing']['title']='Corrected title'
        rows,summary=self.prepare(report,rows=[previous])
        self.assertEqual(rows[0]['id'],previous['id']);self.assertEqual(rows[0]['title'],'Corrected title')
        self.assertEqual(summary['operation'],'update')

    def test_untrusted_or_unapproved_review_and_announcements_are_not_accepted(self):
        for key,value in [('decision','pending'),('reviewedBy','someone-else'),('availability','announced'),
                          ('issueURL','https://github.com/another/repo/issues/42')]:
            with self.subTest(key=key):
                report=request();report[key]=value
                with self.assertRaises(review.CorrectionReviewError):self.prepare(report)
        with self.assertRaises(review.CorrectionReviewError):
            review.prepare_review(request(),[],catalogue(),[],reviewer='untrusted',now=NOW)

    def test_future_expired_overlong_and_pre_release_reviews_fail_closed(self):
        cases=[{'verifiedAt':NOW+1},{'verifiedAt':NOW-100,'expiresAt':NOW-1},
               {'expiresAt':NOW+31*review.DAY},{'releaseDate':'2026-11-22'}]
        for changes in cases:
            with self.subTest(changes=changes):
                report=request();report['listing'].update(changes)
                with self.assertRaises((review.CorrectionReviewError,OfficialListingError)):self.prepare(report)

    def test_generic_india_link_wrong_title_and_unproven_language_fail_closed(self):
        cases=[('indiaEvidenceURL','https://www.netflix.com/in/'),
               ('sourceURL','https://www.netflix.com/in/title/9999'),
               ('audioEvidenceURL',None),('releaseEvidenceURL','https://example.com/news')]
        for key,value in cases:
            with self.subTest(key=key):
                report=request()
                if key=='indiaEvidenceURL':report[key]=value
                else:report['listing'][key]=value
                with self.assertRaises((review.CorrectionReviewError,OfficialListingError)):self.prepare(report)
        report=request();report['listing']['originalLanguage']='Hindi'
        with self.assertRaises(OfficialListingError):self.prepare(report)

    def test_unsupported_platforms_stay_in_triage(self):
        for platform in ['Prime Video','Sun NXT','ZEE5','aha']:
            with self.subTest(platform=platform):
                report=request();report['listing']['platform']=platform
                with self.assertRaisesRegex(review.CorrectionReviewError,'triage'):self.prepare(report)
        report=request();report['listing']['access']['type']='addon'
        with self.assertRaisesRegex(review.CorrectionReviewError,'triage'):self.prepare(report)

    def test_ambiguous_provider_ids_later_removals_and_corrupt_aliases_cannot_be_written(self):
        catalog=catalogue();other=deepcopy(catalog['titles'][0]);other['id']='motn:901';catalog['titles'].append(other)
        with self.assertRaises(OfficialListingError):self.prepare(catalog=catalog)
        catalog=catalogue();catalog['officialListingRemovals']=[{'id':'motn:900','platform':'Netflix','removedAt':NOW}]
        with self.assertRaises(review.CorrectionReviewError):self.prepare(catalog=catalog)
        catalog=catalogue();catalog['officialListingAliases']=[]
        with self.assertRaises(OfficialListingError):self.prepare(catalog=catalog)

    def cli_files(self, root):
        paths={name:root/(name+'.json') for name in ['review','registry','catalog','discovered']}
        for name,data in [('review',request()),('registry',[]),('catalog',catalogue()),('discovered',[])]:
            paths[name].write_text(json.dumps(data))
        args=[str(paths['review']),'--reviewer',REVIEWER,'--registry',str(paths['registry']),
              '--catalog',str(paths['catalog']),'--discovered',str(paths['discovered'])]
        return paths,args

    def run_cli(self,args):
        with mock.patch.object(review.time,'time',return_value=NOW),redirect_stdout(io.StringIO()), \
             mock.patch('urllib.request.urlopen',side_effect=AssertionError('No network is allowed')):
            return review.main(args)

    def test_cli_dry_run_is_default_and_explicit_apply_changes_only_local_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            paths,args=self.cli_files(Path(folder));before={k:v.read_bytes() for k,v in paths.items()}
            self.assertEqual(self.run_cli(args),0)
            self.assertEqual({k:v.read_bytes() for k,v in paths.items()},before)
            self.assertEqual(self.run_cli([*args,'--apply']),0)
            self.assertEqual(json.loads(paths['registry'].read_text())[0]['id'],'motn:900')
            for key in ['review','catalog','discovered']:self.assertEqual(paths[key].read_bytes(),before[key])
            self.assertFalse(paths['registry'].with_suffix('.review.tmp').exists())

    def test_corrupt_or_unverified_review_does_not_replace_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            paths,args=self.cli_files(Path(folder));before=paths['registry'].read_bytes()
            for raw in ['{broken','{"schemaVersion":1,"schemaVersion":1}',json.dumps({**request(),'availability':'announced'})]:
                paths['review'].write_text(raw)
                self.assertEqual(self.run_cli([*args,'--apply']),1)
                self.assertEqual(paths['registry'].read_bytes(),before)

    def test_public_issue_events_cannot_apply_a_registry_change(self):
        with tempfile.TemporaryDirectory() as folder:
            paths,args=self.cli_files(Path(folder));before=paths['registry'].read_bytes()
            with mock.patch.dict(os.environ,{'GITHUB_EVENT_NAME':'issues'}):
                self.assertEqual(self.run_cli([*args,'--apply']),1)
            self.assertEqual(paths['registry'].read_bytes(),before)

    def test_interactive_helper_prepares_review_without_requiring_json_copy_paste(self):
        answers=iter(['https://github.com/akashIntgrators/OTTScout-Web/issues/42','Guarding Stars','Netflix','Movie',
            '81749470',URL,'','yes','2026-11-18','https://www.netflix.com/tudum/articles/new-on-netflix',
            'subscription',URL,'Hindi',URL,'','7'])
        with redirect_stdout(io.StringIO()):draft=review.new_review(REVIEWER,NOW,ask=lambda _:next(answers))
        rows,_=self.prepare(draft)
        self.assertEqual(rows[0]['audio'],['Hindi']);self.assertIsNone(rows[0]['originalLanguage'])
        self.assertEqual(rows[0]['expiresAt'],NOW+7*review.DAY)


if __name__=='__main__':
    unittest.main()
