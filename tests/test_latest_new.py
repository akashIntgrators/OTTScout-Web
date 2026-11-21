"""Newest-first discovery uses the real collector ledger with mocked HTTP only."""
import contextlib
from copy import deepcopy
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

from scripts import catalog_sync as sync


NOW = int(datetime.fromisoformat('2026-11-21T06:30:00+00:00').timestamp())
MAPPING = {'Netflix':'netflix','Prime Video':'prime','JioHotstar':'hotstar','ZEE5':'zee5','SonyLIV':'sonyliv'}


def show(ident='recent', added=NOW-60):
    return {'id':ident,'title':ident,'showType':'series','firstAirYear':2026,
            'streamingOptions':{'in':[{'service':{'id':'netflix'},'type':'subscription','audios':[{'language':'eng'}],
                'subtitles':[],'link':'https://www.netflix.com/title/123','availableSince':added}]}}


def page(ident='recent', added=NOW-60, more=True, cursor='next'):
    return {'shows':{ident:show(ident,added)}, 'changes':[{'showId':ident,'service':{'id':'netflix'},'timestamp':added}],
            'hasMore':more,'nextCursor':cursor}


class Response:
    status = 200
    def __init__(self, value): self.value=value
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return json.dumps(self.value).encode()


class LatestNewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.db=sync.open_db(self.root/'catalog.sqlite');self.addCleanup(self.db.close)
        registry=patch.object(sync,'OFFICIAL_LISTINGS_PATH',self.root/'missing-registry.json');registry.start();self.addCleanup(registry.stop)
        network=patch.object(sync,'urlopen',side_effect=AssertionError('Unmocked provider call'));network.start();self.addCleanup(network.stop)
        sync.set_meta(self.db,'pilot_started',NOW-20*sync.DAY)
        sync.set_meta(self.db,'baseline_started',NOW-10*sync.DAY);sync.set_meta(self.db,'baseline_complete',NOW-10*sync.DAY)
        sync.set_meta(self.db,'baseline_done',[service+':'+kind for service in MAPPING.values() for kind in ('movie','series')])
        sync.set_meta(self.db,'coverage',{'mapping':MAPPING,'checkedAt':NOW,'missing':[]})
        sync.set_meta(self.db,'recent_backfill_v1',{'complete':True,'pages':1})
        for kind in ('new','updated','removed'):sync.set_meta(self.db,'watermark:'+kind,NOW-3*sync.DAY)
        sync.set_meta(self.db,'last_success',NOW-3*sync.DAY)
        self.pending={'from':NOW-3*sync.DAY-60,'to':NOW-2*sync.DAY,'cursor':'old-2','seen':['old-2'],
                      'pages':2,'publishedPages':2,'mapping':MAPPING}
        sync.set_meta(self.db,'change_window_v2:new',self.pending);self.db.commit()

    def usage(self, total, attempted=0):
        self.db.executemany('INSERT INTO requests(at,endpoint,status) VALUES (?,?,?)',[(NOW-1,'/fixture',200)]*total)
        if attempted:sync.set_meta(self.db,'new_release_attempts_v2',{'utcDay':NOW//sync.DAY,'attempts':attempted})
        self.db.commit()

    def get_head(self, value, at=NOW, client=None):
        with patch.object(sync.time,'time',return_value=at),patch.object(sync,'urlopen',return_value=Response(value)) as network:
            changed=sync.sync_latest_new(self.db,client or sync.Client(self.db,'fixture-not-a-key'),MAPPING,at)
        return changed,network

    def test_partial_head_publishes_first_all_platforms_and_preserves_old_query_and_complete_watermarks(self):
        self.usage(378) # Two current requests are affordable above the future floor.
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',return_value=Response(page())) as network:
            self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),NOW),1)
        self.assertEqual(network.call_count,1)
        params={key:value[0] for key,value in parse_qs(urlparse(network.call_args.args[0].full_url).query).items()}
        self.assertEqual((params['country'],params['change_type'],params['item_type'],params['order_direction']),('in','new','show','desc'))
        self.assertEqual(set(params['catalogs'].split(',')),set(MAPPING.values()))
        self.assertNotIn('show_type',params);self.assertNotIn('cursor',params)
        self.assertEqual((int(params['from']),int(params['to'])),(NOW-2*sync.DAY,NOW))
        self.assertEqual(sync.get_meta(self.db,'change_window_v2:new'),self.pending)
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW-3*sync.DAY)
        self.assertEqual(sync.get_meta(self.db,'last_success'),NOW-3*sync.DAY)
        expected={'checkedAt':sync.stamp(NOW),'from':sync.stamp(NOW-2*sync.DAY),'to':sync.stamp(NOW),
                  'hasMore':True,'events':1,'oldestEventAt':sync.stamp(NOW-60),'newestEventAt':sync.stamp(NOW-60),
                  'order':'desc','pages':1,'scope':'last48h'}
        self.assertEqual(sync.report(self.db,NOW)['latestNewCheck'],expected)
        self.assertTrue(sync.export_catalog(self.db,self.root/'catalog.json',NOW))
        exported=json.loads((self.root/'catalog.json').read_text())
        self.assertEqual(exported['latestNewCheck'],expected)
        self.assertEqual(exported['titles'][0]['weeklyEvents'],[{'platform':'Netflix','addedAt':NOW-60}])

    def test_two_available_requests_cover_both_twelve_hour_slots_not_the_older_backlog(self):
        self.usage(378)
        calls=[]
        def reply(request,**kwargs):
            params={key:value[0] for key,value in parse_qs(urlparse(request.full_url).query).items()};calls.append(params)
            self.assertEqual(params['order_direction'],'desc')
            return Response(page('recent'+str(len(calls)),int(params['to'])-60))
        with patch.object(sync,'urlopen',side_effect=reply):
            with patch.object(sync.time,'time',return_value=NOW):
                self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),NOW),1)
                budget=sync.request_budget(self.db,NOW)
                self.assertEqual((budget['newFeedRequestsRemainingToday'],budget['futureHeadChecksToday'],
                                  budget['reservedHeadRequestsToday'],budget['newBacklogRequestsAvailableToday']),(1,1,1,0))
                self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),NOW),0)
            later=NOW+12*3600
            with patch.object(sync.time,'time',return_value=later):
                self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),later),1)
                self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),later),0)
        self.assertEqual(len(calls),2)
        self.assertEqual(sync.get_meta(self.db,'change_window_v2:new'),self.pending)
        self.assertEqual(sync.request_budget(self.db,later)['requestsUsed'],380)

    def test_spare_current_capacity_resumes_old_ascending_cursor_but_retains_the_later_head(self):
        self.usage(376) # Four current attempts: head + two backlog pages + later head.
        calls=[]
        def reply(request,**kwargs):
            params={key:value[0] for key,value in parse_qs(urlparse(request.full_url).query).items()};calls.append(params)
            if params['order_direction']=='desc':return Response(page())
            self.assertEqual((int(params['from']),int(params['to'])),(self.pending['from'],self.pending['to']))
            cursor=params['cursor'];index=3 if cursor=='old-2' else 4
            return Response(page('older'+str(index),self.pending['to']-60,True,'old-'+str(index)))
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',side_effect=reply):
            self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),NOW),3)
        self.assertEqual([p['order_direction'] for p in calls],['desc','asc','asc'])
        self.assertEqual([p.get('cursor') for p in calls],[None,'old-2','old-3'])
        state=sync.get_meta(self.db,'change_window_v2:new')
        self.assertEqual((state['cursor'],state['pages'],state['publishedPages']),('old-4',4,4))
        budget=sync.request_budget(self.db,NOW)
        self.assertEqual((budget['requestsUsed'],budget['requestsRemaining'],budget['reservedHeadRequestsToday']),(379,21,1))

    def test_stale_optional_coverage_without_old_pending_query_cannot_steal_the_later_fresh_head(self):
        self.usage(378)
        sync.set_meta(self.db,'change_window_v2:new',None)
        sync.set_meta(self.db,'coverage',{'mapping':MAPPING,'checkedAt':NOW-8*sync.DAY,'missing':[]});self.db.commit()
        calls=[]
        def reply(request,**kwargs):
            parsed=urlparse(request.full_url);params={key:value[0] for key,value in parse_qs(parsed.query).items()}
            calls.append((parsed.path,params))
            self.assertTrue(parsed.path.endswith('/changes'))
            self.assertEqual(params['order_direction'],'desc')
            return Response(page('fresh'+str(len(calls)),int(params['to'])-60))
        with patch.object(sync,'urlopen',side_effect=reply):
            for at in (NOW,NOW+12*3600):
                with patch.object(sync.time,'time',return_value=at):
                    self.assertEqual(sync.sync(self.db,sync.Client(self.db,'fixture-not-a-key'),at),1)
        self.assertEqual(len(calls),2)
        self.assertEqual(sync.get_meta(self.db,'coverage')['checkedAt'],NOW-8*sync.DAY)
        self.assertEqual(sync.request_budget(self.db,NOW+12*3600)['requestsUsed'],380)

    def test_overlap_deduplicates_events_and_manual_repeats_do_not_repeat_the_head_slot(self):
        changed,first=self.get_head(page())
        self.assertEqual((changed,first.call_count),(1,1))
        self.assertEqual(self.get_head(page())[1].call_count,0)
        changed,second=self.get_head(page(),NOW+6*3600)
        self.assertEqual((changed,second.call_count),(0,1))
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM titles').fetchone()[0],1)
        self.assertEqual(sync.new_publication(self.db)['pages'],2)

    def test_empty_or_complete_head_never_claims_complete_ascending_history(self):
        changed,network=self.get_head({'shows':{},'changes':[],'hasMore':False})
        self.assertEqual((changed,network.call_count),(0,1))
        check=sync.get_meta(self.db,sync.LATEST_NEW_CHECK_KEY)
        self.assertEqual((check['hasMore'],check['events'],check['oldestEventAt'],check['newestEventAt']),(False,0,None,None))
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW-3*sync.DAY)
        self.assertEqual(sync.get_meta(self.db,'change_window_v2:new'),self.pending)

    def test_old_maintenance_snapshot_after_head_cannot_replace_newer_body_audio_or_check_time(self):
        self.get_head(page())
        before=self.db.execute("SELECT body,first_seen,last_checked FROM titles WHERE id='motn:recent'").fetchone()
        older=page();older['shows']['recent']['title']='Older title'
        older['shows']['recent']['streamingOptions']['in'][0]['audios']=[{'language':'hin'}]
        self.assertEqual(sync.apply_change_page(self.db,older,MAPPING,'updated',NOW-100),0)
        self.assertEqual(self.db.execute("SELECT body,first_seen,last_checked FROM titles WHERE id='motn:recent'").fetchone(),before)
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE kind='updated'").fetchone()[0],1)

    def test_newest_first_dates_order_size_and_continuation_must_validate_before_publication(self):
        cases=[]
        missing=page();missing.pop('nextCursor');cases.append(missing)
        future=page(added=NOW+1);cases.append(future)
        unordered=page();unordered['shows']['later']=show('later',NOW-1)
        unordered['changes'].append({'showId':'later','service':{'id':'netflix'},'timestamp':NOW-1});cases.append(unordered)
        oversized=page();oversized['changes']=oversized['changes']*26;cases.append(oversized)
        for index,value in enumerate(cases):
            with self.subTest(case=index):
                self.db.execute('DELETE FROM meta WHERE key=?',(sync.LATEST_NEW_ATTEMPT_KEY,));self.db.commit()
                with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',return_value=Response(value)):
                    with self.assertRaises(sync.SyncError):sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key'),MAPPING,NOW)
                self.assertEqual(self.db.execute('SELECT count(*) FROM titles').fetchone()[0],0)
                self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
                self.assertIsNone(sync.get_meta(self.db,sync.LATEST_NEW_CHECK_KEY))

    def test_malformed_later_record_preserves_last_good_scan_and_uses_only_one_attempt_in_slot(self):
        previous={'checkedAt':sync.stamp(NOW-6*3600),'scope':'last48h'}
        sync.set_meta(self.db,sync.LATEST_NEW_CHECK_KEY,previous);self.db.commit()
        bad=page();bad['shows']['bad']=show('bad');bad['shows']['bad']['showType']='invalid'
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',return_value=Response(bad)) as network:
            with self.assertRaises(sync.SyncError):sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key'),MAPPING,NOW)
            self.assertEqual(sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key'),MAPPING,NOW),0)
        self.assertEqual(network.call_count,1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM titles').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
        self.assertEqual(sync.get_meta(self.db,sync.LATEST_NEW_CHECK_KEY),previous)
        self.assertEqual(sync.new_publication(self.db)['pages'],0)

    def test_failure_checkpoint_is_atomic_with_real_request_ledger_and_prevents_same_slot_network_retry(self):
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',side_effect=URLError('offline')) as network:
            with self.assertRaises(sync.SyncError):sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key'),MAPPING,NOW)
            self.assertEqual(sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key'),MAPPING,NOW),0)
        self.assertEqual(network.call_count,1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests WHERE status=0').fetchone()[0],1)
        self.assertEqual(sync.get_meta(self.db,sync.LATEST_NEW_ATTEMPT_KEY),{'at':NOW})
        self.assertIsNone(sync.get_meta(self.db,sync.LATEST_NEW_CHECK_KEY))

    def test_prevented_request_does_not_claim_head_slot_and_same_slot_can_use_a_later_allowed_client(self):
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',return_value=Response(page())) as network:
            self.assertEqual(sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key',run_limit=0),MAPPING,NOW),0)
            self.assertIsNone(sync.get_meta(self.db,sync.LATEST_NEW_ATTEMPT_KEY))
            network.assert_not_called()
            self.assertEqual(sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key',run_limit=1),MAPPING,NOW),1)
        self.assertEqual(network.call_count,1)

    def test_exhausted_daily_allowance_or_monthly_cap_has_zero_head_calls_and_no_slot_checkpoint(self):
        self.usage(378,attempted=6)
        with patch.object(sync,'urlopen') as network:
            self.assertEqual(sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key'),MAPPING,NOW),0)
            self.assertIsNone(sync.get_meta(self.db,sync.LATEST_NEW_ATTEMPT_KEY));network.assert_not_called()
            self.assertEqual(sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key',monthly_limit=0),MAPPING,NOW),0)

    def test_head_transaction_rolls_back_bodies_events_scan_and_publication_on_write_failure(self):
        original=sync.save_show
        def fail(db,item,mapping,at):
            original(db,item,mapping,at)
            raise sync.sqlite3.OperationalError('Simulated full disk')
        with patch.object(sync.time,'time',return_value=NOW),patch.object(sync,'urlopen',return_value=Response(page())),patch.object(sync,'save_show',side_effect=fail):
            with self.assertRaises(sync.sqlite3.OperationalError):sync.sync_latest_new(self.db,sync.Client(self.db,'fixture-not-a-key'),MAPPING,NOW)
        self.assertEqual(self.db.execute('SELECT count(*) FROM titles').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0],0)
        self.assertIsNone(sync.get_meta(self.db,sync.LATEST_NEW_CHECK_KEY))
        self.assertEqual(sync.new_publication(self.db)['pages'],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM requests').fetchone()[0],1)

    def test_explicit_recent_history_can_supply_real_events_before_a_new_baseline_without_inventing_dates(self):
        sync.set_meta(self.db,'baseline_complete',NOW);self.db.commit()
        self.get_head(page())
        self.assertEqual(self.db.execute('SELECT at FROM events').fetchone()[0],NOW-60)
        self.assertEqual(sync.get_meta(self.db,'watermark:new'),NOW-3*sync.DAY)

    def test_cached_export_never_runs_a_newest_first_request_or_claims_a_new_scan(self):
        sync.save_show(self.db,show('cached'),MAPPING,NOW-3600);self.db.commit()
        args=['catalog_sync.py','--db',str(self.root/'catalog.sqlite'),'--export',str(self.root/'catalog.json'),
              '--report',str(self.root/'report.json'),'--export-cached']
        with patch.object(sys,'argv',args),patch.dict(os.environ,{},clear=True),patch.object(sync.time,'time',return_value=NOW), \
             patch.object(sync,'urlopen') as network,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sync.main(),0);network.assert_not_called()
        self.assertIsNone(json.loads((self.root/'catalog.json').read_text())['latestNewCheck'])
        self.assertIsNone(sync.get_meta(self.db,sync.LATEST_NEW_ATTEMPT_KEY))


if __name__=='__main__':unittest.main()
