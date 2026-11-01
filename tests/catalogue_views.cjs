const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const now = Date.parse('2026-11-02T12:00:00Z') / 1000;
class FixedDate extends Date { static now() { return now * 1000; } }
const source = fs.readFileSync('app.js', 'utf8').split("for (const kind of ['platforms','languages']) renderOptions(kind);")[0];
const context = vm.createContext({
  localStorage: { getItem: () => null }, document: {}, console, Intl, URL,
  Date: FixedDate, assert,
});
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
run(`
const clock=Date.now()/1000;
const stamp=value=>Date.parse(value)/1000;
function resetViewFilters(){
  view='discover';liveCatalog={};selectedOriginals=null;selectedGenres=null;
  originalOnly=false;subscriptionOnly=false;audioDescriptionOnly=false;
  selectedPlatforms.clear();platforms.forEach(name=>selectedPlatforms.add(name));
  selectedLanguages.clear();languages.forEach(name=>selectedLanguages.add(name));
}
function offerAt(platform,extras={}){
  return {platform,type:'subscription',audio:['English'],subtitles:[],
    link:platform==='Netflix'?'https://www.netflix.com/title/123':'https://www.primevideo.com/detail/example',...extras};
}
function weeklyAt(id,time,extras={}){
  return {id,title:id,type:'Movie',year:2001,originalLanguage:'English',weekly:true,
    weeklyPlatforms:['Netflix'],weeklyEvents:[{platform:'Netflix',addedAt:time}],weeklyUpdatedAt:time,
    offers:[offerAt('Netflix')],...extras};
}
resetViewFilters();
const beforeMidnight=weeklyAt('before',stamp('2026-10-31T18:29:59Z'));
const afterMidnight=weeklyAt('after',stamp('2026-10-31T18:30:00Z'));
const laterSunday=weeklyAt('later',stamp('2026-11-01T16:00:00Z'));
const monday=weeklyAt('monday',stamp('2026-11-02T10:00:00Z'));
const grouped=groupWeeklyTitles([beforeMidnight,afterMidnight,laterSunday,monday],clock);
assert.deepEqual(grouped.map(group=>group.key),['2026-11-02','2026-11-01','2026-10-31']);
assert.equal(grouped[1].label,'Sunday, 1 November','IST weekday must come from the date, not a hard-coded release label');
assert.equal(grouped[2].label,'Saturday, 31 October');
assert.deepEqual(grouped[1].titles.map(title=>title.id),['later','after']);
assert.equal(grouped.reduce((total,group)=>total+group.titles.length,0),4,'Each title belongs to one actual addition day');
assert.equal(grouped[1].timestamp,weeklyAdditionTime(laterSunday,clock));
assert.deepEqual([beforeMidnight.id,afterMidnight.id,laterSunday.id,monday.id],['before','after','later','monday'],'Grouping must not change title identities');
`);

run(`
const netflixTime=stamp('2026-10-31T12:00:00Z');
const primeTime=stamp('2026-11-01T12:00:00Z');
const multi=weeklyAt('two-platforms',primeTime,{
  weeklyPlatforms:['Netflix','Prime Video'],weeklyEvents:[{platform:'Netflix',addedAt:netflixTime},{platform:'Prime Video',addedAt:primeTime}],
  offers:[offerAt('Netflix'),offerAt('Prime Video',{audio:['Hindi']})]
});
selectedPlatforms.clear();selectedPlatforms.add('Netflix');
assert.equal(weeklyAdditionTime(multi,clock),netflixTime,'A deselected platform cannot supply the grouping date');
assert.equal(groupWeeklyTitles([multi],clock)[0].key,'2026-10-31');
selectedPlatforms.add('Prime Video');selectedLanguages.clear();selectedLanguages.add('Hindi');
assert.equal(weeklyAdditionTime(multi,clock),primeTime,'Grouping must use matching audio offers');
assert.equal(groupWeeklyTitles([multi],clock)[0].key,'2026-11-01');
selectedLanguages.clear();selectedLanguages.add('English');
assert.equal(weeklyAdditionTime(multi,clock),netflixTime);
resetViewFilters();
const oldOffer=weeklyAt('old-offer',primeTime,{offers:[offerAt('Netflix',{availableSince:clock-8*DAY})]});
assert.equal(weeklyAdditionTime(oldOffer,clock),null,'Recent import events cannot make an old offer newly available');
const futureOffer=weeklyAt('future-offer',primeTime,{offers:[offerAt('Netflix',{availableSince:clock+1})]});
assert.equal(weeklyAdditionTime(futureOffer,clock),null);
const unknownDate=weeklyAt('date-unknown',undefined,{year:2026,firstObservedAt:primeTime,weeklyEvents:[],weeklyUpdatedAt:null});
const unknownGroup=groupWeeklyTitles([unknownDate,oldOffer,monday],clock);
assert.deepEqual(unknownGroup.map(group=>group.key),['2026-11-02','unverified']);
assert.equal(unknownGroup[1].label,'Addition date unverified');
assert.equal(unknownGroup[1].timestamp,null);
assert.equal(weeklyAdditionTime(unknownDate,clock),null,'Release year and import observation date are not provider addition dates');
`);

run(`
resetViewFilters();
const expiryStart=clock+1;
const expiryEdge=clock+30*DAY;
const validSoon=offerAt('Netflix',{expiresOn:expiryStart});
const validEdge=offerAt('Prime Video',{expiresOn:expiryEdge});
const invalidExpiries=[clock,clock-1,clock+30*DAY+1,253368115140,Infinity,NaN,'1793620801',null,undefined];
const expiryTitle={id:'expiry-fixture',title:'Expiration fixture',originalLanguage:'English',offers:[
  validSoon,validEdge,...invalidExpiries.map(expiresOn=>offerAt('Netflix',{expiresOn})),
  offerAt('Netflix',{expiresOn:clock+DAY,availableSince:clock+1})
]};
const originalOffers=expiryTitle.offers.slice();
const validExpiries=expiringOffers(expiryTitle,clock);
assert.equal(validExpiries.length,2,'Only finite actual future expiries within thirty days may be promoted');
assert.ok(validExpiries.includes(validSoon));assert.ok(validExpiries.includes(validEdge));
assert.equal(earliestExpiry(expiryTitle,clock),expiryStart);
assert.deepEqual(expiryTitle.offers,originalOffers,'Expiry filtering must not mutate source offers');
selectedPlatforms.clear();selectedPlatforms.add('Prime Video');
assert.equal(earliestExpiry(expiryTitle,clock),expiryEdge,'A deselected provider cannot make a title leave sooner');
selectedLanguages.clear();selectedLanguages.add('Hindi');
assert.equal(expiringOffers(expiryTitle,clock).length,0,'Unknown or unmatched audio must not enter a specific language expiry view');
assert.equal(earliestExpiry(expiryTitle,clock),null);
resetViewFilters();subscriptionOnly=true;
assert.equal(expiringOffers({...expiryTitle,offers:[offerAt('Netflix',{type:'rent',expiresOn:clock+DAY})]},clock).length,0);
assert.equal(expiringOffers({...expiryTitle,offers:[offerAt('Netflix',{addon:'Extra channel',expiresOn:clock+DAY})]},clock).length,0);
`);

run(`
resetViewFilters();selectedLanguages.clear();selectedLanguages.add('Hindi');audioDescriptionOnly=true;
const reportedOffer=offerAt('Netflix',{expiresOn:clock+DAY,audio:['English'],audioDescription:{
  status:'reported',languages:['Hindi'],sourceURL:'https://www.netflix.com/in/title/123',
  checkedAt:clock-100,expiresAt:clock+DAY,indiaPlaybackVerified:false
}});
const described=weeklyAt('description-fixture',primeTime,{offers:[reportedOffer]});
assert.equal(weeklyAdditionTime(described,clock),primeTime,'Description filters must use description languages, not ordinary audio');
assert.equal(expiringOffers(described,clock).length,1);
const wrongIdentity={...described,offers:[{...reportedOffer,link:'https://www.netflix.com/title/124'}]};
assert.equal(weeklyAdditionTime(wrongIdentity,clock),null);
assert.equal(expiringOffers(wrongIdentity,clock).length,0,'Description evidence must not leak across provider identities');
originalOnly=true;
assert.equal(expiringOffers(described,clock).length,0,'Dubbed description cannot pass original-language-only');
resetViewFilters();
const duplicateA={id:'drive-2011',title:'Drive',year:2011};
const duplicateB={id:'drive-2019',title:'Drive',year:2019};
assert.equal(randomTitle([],()=>{throw Error('Empty pool should not call randomness')}),null);
assert.equal(randomTitle([duplicateA,duplicateB],()=>0),duplicateA);
assert.equal(randomTitle([duplicateA,duplicateB],()=>1-Number.EPSILON),duplicateB);
assert.equal(randomTitle([duplicateB],()=>0.7),duplicateB);
`);
console.log('IST weekly groups, selected-offer dates, unverified dates, strict expiry windows and random title identity scenarios passed.');
