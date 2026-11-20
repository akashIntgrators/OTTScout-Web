import copy
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
from urllib import request

spec=importlib.util.spec_from_file_location('official_listings',Path(__file__).parents[1]/'scripts/official_listings.py')
official=importlib.util.module_from_spec(spec);spec.loader.exec_module(official)
NOW=int(datetime(2026,11,19,12,tzinfo=timezone.utc).timestamp())
RELEASE=int(datetime(2026,11,18,18,30,tzinfo=timezone.utc).timestamp())
URL='https://www.hotstar.com/in/shows/mr-and-mrs-office/1271718279'


def record():
    return {'id':'motn:official-hotstar-1271718279','platform':'JioHotstar','platformTitleId':'1271718279',
            'title':'Mr & Mrs Office','type':'Series','year':2026,'sourceURL':URL,'releaseDate':'2026-11-19',
            'releaseEvidenceURL':'https://cdn.jiostar.com/press/mr-and-mrs-office.pdf','verifiedAt':NOW-3600,
            'expiresAt':NOW+7*official.DAY,'access':{'type':'subscription','evidenceURL':URL},'audio':[],
            'originalLanguage':None}


def catalog(titles=None):
    return {'schemaVersion':1,'updatedAt':'2026-11-13T07:02:34+00:00','streamingFreshness':{'new':{'completedThrough':'2026-11-18T18:34:00+00:00'}},
            'coverage':['Netflix','JioHotstar'],'titles':titles or []}


def provider_title():
    return {'id':'motn:123','title':'Provider office title','type':'Series','year':2026,'originalLanguage':None,'lastCheckedAt':NOW,
            'offers':[{'platform':'JioHotstar','type':'free','audio':['Hindi'],'link':URL,'availableSince':NOW-2*official.DAY,
                       'availabilitySource':'Streaming Availability API by Movie of the Night'},
                      {'platform':'Netflix','type':'subscription','audio':['English'],'link':'https://www.netflix.com/title/456'}],
            'weeklyEvents':[{'platform':'JioHotstar','addedAt':NOW-2*official.DAY},{'platform':'Netflix','addedAt':NOW-3*official.DAY}]}


def sony_record():
    row=record();url='https://www.sonyliv.com/shows/lo-chudail-chali-sasural-1790007924'
    row.update({'id':'motn:official-sonyliv-1790007924','platform':'SonyLIV','platformTitleId':'1790007924',
                'title':'Lo Chudail Chali Sasural','type':'Series','year':2026,'sourceURL':url,'releaseDate':'2026-11-18',
                'releaseEvidenceURL':'https://www.sonyliv.com/trailer/lo-chudail-chali-sasural-trailer-6-1090551128?watch=true',
                'access':{'type':'subscription','evidenceURL':'https://origin-staticv2.sonyliv.com/UI_icons/india_faqs.html'},
                'audio':['Hindi'],'audioEvidenceURL':url})
    return row


class OfficialListingTests(unittest.TestCase):
    def test_unknown_audio_original_artwork_and_provider_freshness_are_not_invented(self):
        source=catalog();original=copy.deepcopy(source);row=record()
        output,summary=official.apply_official_listings(source,[row],NOW)
        self.assertEqual(source,original)
        self.assertEqual((output['updatedAt'],output['streamingFreshness']),(source['updatedAt'],source['streamingFreshness']))
        title=output['titles'][0];offer=title['offers'][0]
        self.assertEqual((title['id'],title['originalLanguage'],title['poster'],title['overview']),(row['id'],None,None,''))
        self.assertEqual((offer['audio'],offer['audioStatus'],offer['availableSince']),( [],'unverified',None))
        self.assertEqual((offer['officialReleaseAt'],offer['datePrecision']),(RELEASE,'day'))
        self.assertEqual((offer['availabilitySource'],offer['availabilitySourceType'],offer['availabilitySourceURL']),('Official JioHotstar listing','official-listing',URL))
        self.assertEqual(offer['availabilityCheckedAt'],row['verifiedAt'])
        self.assertNotIn('expiresOn',offer,'Evidence expiry is not a platform departure date')
        self.assertEqual(title['weeklyEvents'][0]['addedAt'],RELEASE)
        self.assertEqual(title['weeklyEvents'][0]['datePrecision'],'day')
        self.assertEqual(summary['evaluatedAt'],NOW)
        self.assertEqual((summary['active'],summary['fallback'],summary['providerMatched']),(1,1,0))

    def test_reapplication_is_idempotent_and_retains_independent_metadata(self):
        first,_=official.apply_official_listings(catalog(),[record()],NOW)
        first['titles'][0]['tmdb']={'id':17,'genres':['Comedy']}
        first['titles'][0]['originalLanguage']='Hindi';first['titles'][0]['originalLanguageSource']='TMDB'
        second,_=official.apply_official_listings(first,[record()],NOW)
        self.assertEqual(first,second)
        self.assertEqual(len(second['titles'][0]['offers']),1)
        self.assertEqual(len(second['titles'][0]['weeklyEvents']),1)

    def test_expiry_removes_derived_offers_events_and_empty_titles_but_keeps_stable_aliases(self):
        row=record();first,_=official.apply_official_listings(catalog(),[row],NOW)
        expired,summary=official.apply_official_listings(first,[row],row['expiresAt'])
        self.assertEqual(expired['titles'],[])
        self.assertEqual(expired['officialListingAliases']['hotstar:1271718279'],row['id'])
        self.assertEqual((summary['expired'],summary['active'],summary['fallback']),(1,0,0))
        arriving=copy.deepcopy(provider_title());arriving['lastCheckedAt']=row['expiresAt']+1
        expired['titles'].append(arriving)
        output,summary=official.apply_official_listings(expired,[row],row['expiresAt']+1)
        self.assertEqual(output['titles'][0]['id'],row['id'])
        self.assertEqual(output['titles'][0]['officialListing']['status'],'provider-matched')
        self.assertEqual(len(output['titles'][0]['offers']),2)
        self.assertEqual(summary['providerMatched'],1)

    def test_provider_arrival_deduplicates_and_preserves_provider_offers_events_and_enrichment(self):
        row=record();source,_=official.apply_official_listings(catalog(),[row],NOW)
        source['titles'][0]['tmdb']={'id':99}
        incoming=provider_title();source['titles'].append(copy.deepcopy(incoming))
        output,summary=official.apply_official_listings(source,[row],NOW)
        self.assertEqual(len(output['titles']),1)
        title=output['titles'][0]
        self.assertEqual((title['id'],title['title'],title['tmdb']),(row['id'],incoming['title'],{'id':99}))
        self.assertEqual(title['offers'],incoming['offers'])
        self.assertEqual(title['weeklyEvents'],incoming['weeklyEvents'])
        self.assertEqual(output['officialListingAliases']['motn:123'],row['id'])
        self.assertEqual((summary['fallback'],summary['providerMatched']),(0,1))
        self.assertEqual(official.apply_official_listings(output,[row],NOW)[0],output)

    def test_missing_platform_offer_adds_only_verified_offer_without_borrowing_other_audio(self):
        existing=provider_title();existing['offers']=existing['offers'][1:];existing['weeklyEvents']=existing['weeklyEvents'][1:]
        row=record();row['id']='motn:123'
        output,_=official.apply_official_listings(catalog([existing]),[row],NOW)
        title=output['titles'][0]
        self.assertEqual(title['offers'][0],existing['offers'][0])
        self.assertEqual(title['offers'][1]['audio'],[])
        self.assertIn(existing['weeklyEvents'][0],title['weeklyEvents'])
        self.assertEqual(set(title['weeklyPlatforms']),{'Netflix','JioHotstar'})

    def test_pre_release_verification_does_not_auto_promote_an_announcement_after_release(self):
        row=record();row['releaseDate']='2026-11-20'
        before,summary=official.apply_official_listings(catalog(),[row],NOW)
        self.assertEqual(before['titles'],[]);self.assertEqual(summary['active'],0)
        after,summary=official.apply_official_listings(before,[row],NOW+official.DAY)
        self.assertEqual(after['titles'],[]);self.assertEqual(summary['active'],0)
        row['verifiedAt']=NOW+official.DAY
        verified,summary=official.apply_official_listings(after,[row],NOW+official.DAY)
        self.assertEqual(len(verified['titles']),1);self.assertEqual(summary['active'],1)

    def test_weekly_window_uses_ist_day_precision_and_exact_rolling_bounds(self):
        row=record();row['expiresAt']=row['verifiedAt']+30*official.DAY
        inside,_=official.apply_official_listings(catalog(),[row],RELEASE+7*official.DAY)
        outside,_=official.apply_official_listings(catalog(),[row],RELEASE+7*official.DAY+1)
        self.assertTrue(inside['titles'][0]['weekly'])
        self.assertFalse(outside['titles'][0]['weekly'])
        self.assertEqual(outside['titles'][0]['weeklyEvents'],[])

    def test_explicit_audio_and_original_language_need_exact_primary_evidence(self):
        row=record();row.update({'audio':['Hindi'],'audioEvidenceURL':URL,'originalLanguage':'Hindi','originalLanguageEvidenceURL':URL})
        output,_=official.apply_official_listings(catalog(),[row],NOW)
        self.assertEqual(output['titles'][0]['offers'][0]['audioSourceURL'],URL)
        self.assertEqual(output['titles'][0]['originalLanguage'],'Hindi')
        for key in ('audioEvidenceURL','originalLanguageEvidenceURL'):
            broken=copy.deepcopy(row);broken[key]='https://example.test/evidence'
            with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[broken],NOW)

    def test_registry_rejects_conflicts_spoofed_domains_bad_dates_and_unproved_claims_without_mutating_input(self):
        mutations=[('sourceURL',URL.replace('hotstar.com','hotstar.com.example.test')),('sourceURL',URL.replace('https://','https://user@')),
            ('sourceURL',URL.replace('1271718279','999')),('releaseDate','2026-02-30'),('verifiedAt',NOW+1),
            ('expiresAt',NOW+31*official.DAY),('id','motn:unknown'),('audio',['Hindi']),('originalLanguage','Hindi'),('extra','unreviewed')]
        source=catalog();before=copy.deepcopy(source)
        for key,value in mutations:
            with self.subTest(key=key):
                row=record();row[key]=value
                with self.assertRaises(official.OfficialListingError):official.apply_official_listings(source,[row],NOW)
                self.assertEqual(source,before)
        for records in [[record(),record()],[record(),{**record(),'id':'motn:official-hotstar-999'}]]:
            with self.assertRaises(official.OfficialListingError):official.apply_official_listings(source,records,NOW)

    def test_netflix_uses_india_canonical_source_and_exact_provider_identity(self):
        row=record();url='https://www.netflix.com/in/title/83064751'
        row.update({'id':'motn:official-netflix-83064751','platform':'Netflix','platformTitleId':'83064751','type':'Movie',
                    'sourceURL':url,'releaseEvidenceURL':url,'access':{'type':'subscription','evidenceURL':url}})
        first,_=official.apply_official_listings(catalog(),[row],NOW)
        provider={'id':'motn:77','title':'A provider film','type':'Movie','lastCheckedAt':NOW,
                  'offers':[{'platform':'Netflix','link':'https://www.netflix.com/watch/83064751','type':'subscription','audio':[]}],'weeklyEvents':[]}
        first['titles'].append(provider)
        output,summary=official.apply_official_listings(first,[row],NOW)
        self.assertEqual((len(output['titles']),output['titles'][0]['id'],summary['providerMatched']),(1,row['id'],1))
        wrong=copy.deepcopy(row);wrong['sourceURL']='https://www.netflix.com/title/83064751'
        with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[wrong],NOW)

    def test_overlay_has_zero_network_requests(self):
        with patch.object(request,'urlopen',side_effect=AssertionError('Network forbidden')) as network, \
             patch.object(socket,'create_connection',side_effect=AssertionError('Network forbidden')) as connection:
            official.apply_official_listings(catalog(),[record()],NOW)
        network.assert_not_called();connection.assert_not_called()

    def test_unrelated_provider_records_remain_exactly_unchanged(self):
        unrelated={'id':'motn:999','title':'Another title','type':'Movie','lastCheckedAt':NOW-10,
                   'offers':[{'platform':'Netflix','type':'rent','link':'https://www.netflix.com/title/111','audio':['English']}]}
        output,_=official.apply_official_listings(catalog([copy.deepcopy(unrelated)]),[record()],NOW)
        self.assertEqual(output['titles'][0],unrelated)

    def test_curated_identity_edits_update_title_and_invalidate_previous_tmdb_match(self):
        row=record();first,_=official.apply_official_listings(catalog(),[row],NOW)
        first['titles'][0].update({'tmdb':{'id':55},'tmdbId':55,'imdbId':'tt123','tmdbMatchStatus':'matched',
                                 'originalLanguage':'Hindi','originalLanguageSource':'TMDB','poster':'https://example.test/old.png','genres':['Old genre']})
        for key,value in [('title','Corrected office title'),('year',2025),('type','Movie')]:
            with self.subTest(key=key):
                edited=copy.deepcopy(row);edited[key]=value
                if key=='type':
                    edited['sourceURL']=URL.replace('/shows/','/movies/')
                    edited['access']['evidenceURL']=edited['sourceURL']
                output,_=official.apply_official_listings(first,[edited],NOW)
                title=output['titles'][0]
                self.assertEqual({name:title[name] for name in ('title','type','year')},{name:edited[name] for name in ('title','type','year')})
                for stale in ('tmdb','tmdbId','imdbId','tmdbMatchStatus','originalLanguageSource'):
                    self.assertNotIn(stale,title)
                self.assertIsNone(title['originalLanguage']);self.assertIsNone(title['poster']);self.assertEqual(title['genres'],[])
                self.assertEqual(official.apply_official_listings(output,[edited],NOW)[0],output)

    def test_learned_provider_alias_still_matches_when_its_hotstar_offer_disappears(self):
        row=record();first,_=official.apply_official_listings(catalog([provider_title()]),[row],NOW)
        arriving=provider_title();arriving['offers']=arriving['offers'][1:];arriving['weeklyEvents']=arriving['weeklyEvents'][1:]
        latest=catalog([arriving]);latest['officialListingAliases']=first['officialListingAliases']
        output,summary=official.apply_official_listings(latest,[row],NOW)
        self.assertEqual(len(output['titles']),1)
        self.assertEqual(output['titles'][0]['id'],row['id'])
        self.assertEqual(output['titles'][0]['offers'][0],arriving['offers'][0])
        self.assertEqual(len(output['titles'][0]['offers']),2)
        self.assertEqual((summary['fallback'],summary['providerMatched']),(1,0))
        expired,_=official.apply_official_listings(latest,[row],row['expiresAt'])
        self.assertEqual(len(expired['titles']),1)
        self.assertEqual(expired['titles'][0]['id'],row['id'])
        self.assertEqual(expired['titles'][0]['offers'],arriving['offers'])

    def test_weekly_events_coalesce_per_platform_with_provider_winning_equal_date(self):
        row=record();row['id']='motn:123'
        title=provider_title();title['offers']=title['offers'][1:]
        title['weeklyEvents']=[{'platform':platform,'addedAt':RELEASE} for platform in sorted(official.PLATFORMS)]
        title['weeklyEvents'] += [{'platform':'Netflix','addedAt':NOW-100},{'platform':'Netflix','addedAt':NOW-50}]
        output,_=official.apply_official_listings(catalog([title]),[row],NOW)
        events=output['titles'][0]['weeklyEvents']
        self.assertEqual(len(events),7)
        self.assertEqual(len({event['platform'] for event in events}),7)
        self.assertEqual(next(event for event in events if event['platform']=='Netflix')['addedAt'],NOW-50)
        hotstar=next(event for event in events if event['platform']=='JioHotstar')
        self.assertEqual(hotstar,{'platform':'JioHotstar','addedAt':RELEASE})

    def test_vi_primary_evidence_requires_exact_hotstar_content_identity_and_access_requires_jiostar_pdf(self):
        row=record();vi='https://moviesandtv.myvi.in/tvshow/hs-1271718279'
        row.update({'releaseEvidenceURL':vi,'audio':['Tamil','Hindi','Kannada','Malayalam','Telugu'],'audioEvidenceURL':vi,
                    'access':{'type':'subscription','evidenceURL':'https://cdn.jiostar.com/jiostar/subscription-plans.pdf'}})
        output,_=official.apply_official_listings(catalog(),[row],NOW)
        self.assertEqual(output['titles'][0]['offers'][0]['audio'],row['audio'])
        self.assertIsNone(output['titles'][0]['originalLanguage'],'Offered audio does not identify the original language')
        bad_evidence=[vi.replace('1271718279','999'),vi.replace('moviesandtv.myvi.in','moviesandtv.myvi.in.example.test'),
                      'https://moviesandtv.myvi.in/tvshow/mr-and-mrs-office',vi+'?title=1271718279']
        for value in bad_evidence:
            for key in ('releaseEvidenceURL','audioEvidenceURL'):
                broken=copy.deepcopy(row);broken[key]=value
                with self.subTest(key=key,value=value),self.assertRaises(official.OfficialListingError):
                    official.apply_official_listings(catalog(),[broken],NOW)
        broken=copy.deepcopy(row);broken['access']['evidenceURL']='https://cdn.jiostar.com/press/subscription-plans.pdf'
        with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[broken],NOW)

    def test_mixed_source_retains_provider_attribution_then_restores_it_after_fallback_expiry(self):
        source=catalog();source['source']={'name':'Streaming Availability API by Movie of the Night','url':'https://www.movieofthenight.com/about/api'}
        row=record();first,_=official.apply_official_listings(source,[row],NOW)
        self.assertEqual(first['source'],official.MIXED_SOURCE)
        self.assertEqual(first['providerSource'],source['source'])
        expired,_=official.apply_official_listings(first,[row],row['expiresAt'])
        self.assertEqual(expired['source'],source['source'])
        self.assertNotIn('providerSource',expired)
        self.assertEqual(official.apply_official_listings(expired,[row],row['expiresAt'])[0],expired)

    def test_learned_title_alias_applies_with_no_registry_even_when_the_platform_offer_is_absent(self):
        canonical=record()['id']
        for offers in [provider_title()['offers'],provider_title()['offers'][1:],[]]:
            with self.subTest(offers=len(offers)):
                incoming=provider_title();incoming['offers']=copy.deepcopy(offers)
                source=catalog([incoming]);source['officialListingAliases']={'motn:123':canonical,'hotstar:1271718279':canonical}
                output,summary=official.apply_official_listings(source,[],NOW)
                self.assertEqual(output['titles'][0]['id'],canonical)
                self.assertEqual(output['titles'][0]['offers'],offers)
                self.assertEqual(output['officialListingAliases'],source['officialListingAliases'])
                self.assertEqual((summary['records'],summary['fallback']),(0,0))
                self.assertEqual(official.apply_official_listings(output,[],NOW)[0],output)
                after_expiry,_=official.apply_official_listings(source,[],record()['expiresAt']+1)
                self.assertEqual(after_expiry['titles'][0]['id'],canonical)
                self.assertEqual(after_expiry['titles'][0]['offers'],offers)

    def test_alias_collisions_merge_matching_provider_facts_and_reject_conflicts_or_cycles(self):
        canonical=record()['id'];old=provider_title();current=copy.deepcopy(old)
        current['id']=canonical;current['lastCheckedAt']=NOW-1
        source=catalog([old,current]);source['officialListingAliases']={'motn:123':canonical,'hotstar:1271718279':canonical}
        output,_=official.apply_official_listings(source,[],NOW)
        self.assertEqual(len(output['titles']),1)
        self.assertEqual(output['titles'][0]['id'],canonical)
        self.assertEqual(output['titles'][0]['offers'],old['offers'])
        self.assertEqual(len(output['titles'][0]['weeklyEvents']),2)
        for conflict in ('type','platform','cycle'):
            with self.subTest(conflict=conflict):
                broken=copy.deepcopy(source)
                if conflict=='type':broken['titles'][1]['type']='Movie'
                if conflict=='platform':broken['titles'][0]['offers'][0]['link']=URL.replace('1271718279','999')
                if conflict=='cycle':broken['officialListingAliases'][canonical]='motn:123'
                before=copy.deepcopy(broken)
                with self.assertRaises(official.OfficialListingError):official.apply_official_listings(broken,[],NOW)
                self.assertEqual(broken,before)

    def test_exact_newer_removal_suppresses_official_offer_until_a_later_review_but_absence_does_not(self):
        row=record();row['id']='motn:123'
        existing=provider_title();existing['offers']=existing['offers'][1:];existing['weeklyEvents']=existing['weeklyEvents'][1:]
        source=catalog([existing])
        absent,_=official.apply_official_listings(source,[row],NOW)
        self.assertEqual(len(absent['titles'][0]['offers']),2,'A missing provider offer alone is not removal evidence')
        removed=NOW-100
        source['officialListingRemovals']=[{'id':row['id'],'platform':'JioHotstar','removedAt':removed},
                                          {'id':row['id'],'platform':'JioHotstar','removedAt':removed-1}]
        output,summary=official.apply_official_listings(source,[row],NOW)
        self.assertEqual(output['titles'][0]['offers'],existing['offers'])
        self.assertEqual(output['titles'][0]['officialListing']['inactiveReason'],'newer-provider-removal')
        self.assertEqual((summary['active'],summary['fallback']),(0,0))
        self.assertEqual(len(output['officialListingRemovals']),1)
        reviewed=copy.deepcopy(row);reviewed['verifiedAt']=NOW
        recovered,summary=official.apply_official_listings(output,[reviewed],NOW)
        self.assertEqual(len(recovered['titles'][0]['offers']),2)
        self.assertEqual(summary['fallback'],1)
        other_platform=catalog([existing]);other_platform['officialListingRemovals']=[{'id':row['id'],'platform':'Netflix','removedAt':removed}]
        self.assertEqual(official.apply_official_listings(other_platform,[row],NOW)[1]['fallback'],1)

    def test_removal_signal_preserves_positive_provider_offers_and_rejects_invalid_dates(self):
        row=record();source=catalog([provider_title()])
        source['officialListingRemovals']=[{'id':row['id'],'platform':'JioHotstar','removedAt':NOW-100}]
        output,summary=official.apply_official_listings(source,[row],NOW)
        self.assertEqual(output['titles'][0]['offers'],provider_title()['offers'])
        self.assertEqual(summary['providerMatched'],1)
        for invalid in (0,True,NOW+1):
            broken=copy.deepcopy(source);broken['officialListingRemovals'][0]['removedAt']=invalid
            with self.subTest(removedAt=invalid),self.assertRaises(official.OfficialListingError):
                official.apply_official_listings(broken,[row],NOW)

    def test_sonyliv_series_exact_identity_provider_dedupe_aliases_and_expiry(self):
        row=sony_record();first,summary=official.apply_official_listings(catalog(),[row],NOW)
        self.assertEqual((first['titles'][0]['id'],first['titles'][0]['offers'][0]['audio']),(row['id'],['Hindi']))
        self.assertEqual(first['officialListingAliases']['sonyliv:1790007924'],row['id'])
        self.assertEqual(summary['fallback'],1)
        incoming={'id':'motn:991','title':row['title'],'type':'Series','year':2026,'lastCheckedAt':NOW,
                  'offers':[{'platform':'SonyLIV','type':'subscription','audio':['Hindi'],'link':row['sourceURL']}],
                  'weeklyEvents':[{'platform':'SonyLIV','addedAt':NOW-100}]}
        first['titles'].append(incoming)
        matched,summary=official.apply_official_listings(first,[row],NOW)
        self.assertEqual((len(matched['titles']),summary['providerMatched'],summary['fallback']),(1,1,0))
        self.assertEqual(matched['titles'][0]['offers'],incoming['offers'])
        self.assertEqual(matched['officialListingAliases']['motn:991'],row['id'])
        fresh=catalog([incoming]);fresh['officialListingAliases']=matched['officialListingAliases']
        expired,_=official.apply_official_listings(fresh,[row],row['expiresAt'])
        self.assertEqual(expired['titles'][0]['id'],row['id'])
        self.assertEqual(expired['titles'][0]['offers'],incoming['offers'])
        no_registry,_=official.apply_official_listings(fresh,[],NOW)
        self.assertEqual(no_registry['titles'][0]['id'],row['id'])
        fallback_only,_=official.apply_official_listings(catalog(),[row],NOW)
        self.assertEqual(official.apply_official_listings(fallback_only,[row],row['expiresAt'])[0]['titles'],[])

    def test_sonyliv_release_episode_and_subscription_access_sources_are_exact(self):
        row=sony_record()
        episode=row['sourceURL']+'/the-bride-s-secret-1090554840?watch=true'
        row['releaseEvidenceURL']=episode;row['audioEvidenceURL']=episode
        self.assertEqual(official.apply_official_listings(catalog(),[row],NOW)[1]['fallback'],1)
        cases=[('type','Movie'),('sourceURL',row['sourceURL'].replace('1790007924','1790007999')),
               ('sourceURL',row['sourceURL'].replace('www.sonyliv.com','www.sonyliv.com.example.test')),
               ('releaseEvidenceURL',episode.replace('1790007924','1790007999')),
               ('releaseEvidenceURL','https://www.sonyliv.com/trailer/a-different-show-trailer-6-1090551128'),
               ('releaseEvidenceURL',sony_record()['releaseEvidenceURL'].replace('watch=true','watch=false')),
               ('releaseEvidenceURL',sony_record()['releaseEvidenceURL']+'&redirect=other')]
        for key,value in cases:
            broken=copy.deepcopy(row);broken[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(official.OfficialListingError):
                official.apply_official_listings(catalog(),[broken],NOW)
        exact=copy.deepcopy(row);exact['access']['evidenceURL']=row['sourceURL']
        self.assertEqual(official.apply_official_listings(catalog(),[exact],NOW)[1]['fallback'],1)
        for value in [row['sourceURL'].replace('1790007924','1790007999'),
                      row['sourceURL'].replace('www.sonyliv.com','www.sonyliv.com.example.test'),
                      'https://origin-staticv2.sonyliv.com/UI_icons/india_faqs.html?other=1',
                      'https://origin-staticv2.sonyliv.com.example.test/UI_icons/india_faqs.html']:
            broken=copy.deepcopy(row);broken['access']['evidenceURL']=value
            with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[broken],NOW)
        other=copy.deepcopy(row);other['access']['type']='free'
        with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[other],NOW)

    def test_sonyliv_wrong_provider_show_id_is_not_merged_into_curated_identity(self):
        row=sony_record()
        unrelated={'id':'motn:992','title':row['title'],'type':'Series','lastCheckedAt':NOW,
                   'offers':[{'platform':'SonyLIV','type':'subscription','audio':['Hindi'],
                              'link':row['sourceURL'].replace('1790007924','1790007999')}],'weeklyEvents':[]}
        output,summary=official.apply_official_listings(catalog([unrelated]),[row],NOW)
        self.assertEqual(len(output['titles']),2)
        self.assertEqual(output['titles'][0]['id'],'motn:992')
        self.assertEqual((summary['fallback'],summary['providerMatched']),(1,0))

    def test_netflix_newsroom_release_evidence_is_strict_first_party_and_not_audio_access_or_other_platform(self):
        row=record();url='https://www.netflix.com/in/title/83064751'
        row.update({'id':'motn:official-netflix-83064751','platform':'Netflix','platformTitleId':'83064751','type':'Movie',
                    'sourceURL':url,'access':{'type':'subscription','evidenceURL':url}})
        for evidence in ['https://www.netflix.com/tudum/articles/guarding-stars-release-date',
                         'https://about.netflix.com/en/news/the-altruists-premieres-november-19']:
            row['releaseEvidenceURL']=evidence
            self.assertEqual(official.apply_official_listings(catalog(),[row],NOW)[1]['fallback'],1)
            cross=sony_record();cross['releaseEvidenceURL']=evidence
            with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[cross],NOW)
            cross=record();cross['releaseEvidenceURL']=evidence
            with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[cross],NOW)
            for field in ('audio','access'):
                broken=copy.deepcopy(row)
                if field=='audio':broken.update({'audio':['Hindi'],'audioEvidenceURL':evidence})
                else:broken['access']['evidenceURL']=evidence
                with self.assertRaises(official.OfficialListingError):official.apply_official_listings(catalog(),[broken],NOW)
        for evidence in ['http://www.netflix.com/tudum/articles/title','https://www.netflix.com.example.test/tudum/articles/title',
                         'https://www.netflix.com/tudum/title','https://about.netflix.com/fr/news/title',
                         'https://www.netflix.com/tudum/articles/title?redirect=other','https://user@about.netflix.com/en/news/title']:
            broken=copy.deepcopy(row);broken['releaseEvidenceURL']=evidence
            with self.subTest(evidence=evidence),self.assertRaises(official.OfficialListingError):
                official.apply_official_listings(catalog(),[broken],NOW)
