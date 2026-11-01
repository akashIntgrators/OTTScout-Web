const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Node {
  constructor(tag, owner) {
    this.tagName = tag.toUpperCase(); this.owner = owner; this.children = [];
    this.parent = null; this.hidden = false; this.open = false; this.listeners = {};
    this.attributes = {}; this.textContent = ''; this.value = '';
    this.dataset = {}; this.style = { setProperty() {} };
  }
  get parentElement() { return this.parent; }
  append(...nodes) { nodes.forEach(node => { node.parent = this; this.children.push(node); }); }
  replaceChildren(...nodes) { this.children.forEach(node => { node.parent = null; }); this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [child, ...child.querySelectorAll(selector)]).filter(child => selector === '*' || (selector.startsWith('.') ? (child.className || '').split(' ').includes(selector.slice(1)) : child.tagName === selector.toUpperCase()));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  fire(type, target = this) { (this.listeners[type] || []).forEach(listener => listener({ target })); }
  blur() { if (this.owner.activeElement === this) this.owner.activeElement = this.owner.body; }
  focus() {
    for (let node = this; node; node = node.parent) {
      assert.ok(!node.hidden, 'Focus moved into a hidden element');
      if (node.parent?.tagName === 'DETAILS' && !node.parent.open) {
        assert.equal(node.tagName, 'SUMMARY', 'Focus moved into a collapsed disclosure');
      }
    }
    this.owner.activeElement = this;
  }
}

const ids = new Map();
const document = {
  querySelector: selector => ids.get(selector) || (selector.includes(' ')?ids.get(selector.split(' ')[0])?.querySelector(selector.split(' ').slice(1).join(' ')):null) || null,
  querySelectorAll: selector => selector.startsWith('#')&&selector.includes(' ')?ids.get(selector.split(' ')[0])?.querySelectorAll(selector.split(' ').slice(1).join(' '))||[]:body.querySelectorAll(selector),
  getElementById: id => body.querySelectorAll('*').find(result => result.id === id) || null,
  createElement: tag => new Node(tag, document),
  createTextNode: text => { const result = new Node('#text', document); result.textContent = text; return result; },
};
const body = document.createElement('body');
document.body = body;
document.activeElement = body;
function node(id, tag, parent = body) {
  const result = document.createElement(tag); ids.set('#' + id, result); parent.append(result); return result;
}
const panel = node('filters-panel', 'details');
const summary = node('filters-summary', 'summary', panel);
const badge = node('filter-count', 'span', summary);
const parameters = node('filter-parameters', 'div', panel);
node('selection-status','span',parameters);
const advanced = node('advanced-filters', 'details', parameters);
const advancedSummary = node('advanced-summary', 'summary', advanced);
const menus = ['platform', 'language', 'original', 'genre'].map(name => {
  const menu = node(name + '-menu', 'details', advanced);
  const summary=node(name + '-summary', 'summary', menu);summary.append(document.createElement('small'));
  return menu;
});
for (const [name,menu,names] of [['platforms',menus[0],['Netflix','Prime Video']],['languages',menus[1],['English','Hindi','Telugu','Tamil','Kannada','Malayalam']]]) {
  const list=node(name,'div',menu);
  for(const value of names){const input=document.createElement('input');input.value=value;list.append(input);}
}
const quickPlatforms=['Netflix','Prime Video','SonyLIV'].map(name=>{const button=node('quick-'+name,'button',parameters);button.className='quick-platform';button.dataset.platform=name;return button;});
const quickLanguages=['English','Hindi','Telugu','Tamil','Kannada','Malayalam'].map(name=>{const button=node('quick-'+name,'button',parameters);button.className='quick-language';button.dataset.language=name;return button;});
const allPlatforms=node('quick-platform-all','button',parameters),allLanguages=node('quick-language-all','button',parameters);
const platformStatus=node('quick-platform-status','span',parameters),languageStatus=node('quick-language-status','span',parameters);
const input = node('platform-checkbox', 'input', menus[0]);
const reset = node('reset-filters', 'button', parameters);
const done = node('filters-done', 'button', parameters);
const chips = node('active-filters', 'div');
const heading = node('heading', 'h1');
const search = node('search', 'input');
const suggestions = node('search-suggestions', 'div');
node('suggestion-status', 'p');
const dialog = node('report-dialog', 'dialog');
for (const id of ['count','weekly-count','view-eyebrow','description','result-count','results-status']) node(id, 'p');
node('leaving-count','span');node('pick-one','button');
const toggleDates=node('toggle-dates','button');
node('restore-hidden', 'button', parameters);
const weeklyGroup = node('weekly-kind', 'div', parameters);
for (const kind of ['all','older','other']) {
  const button=node('weekly-'+kind, 'button', weeklyGroup);
  button.dataset.kind=kind;button.setAttribute('aria-pressed',kind==='all');
}
const catalog = node('catalog', 'div');
node('load-more', 'button');
for (const id of ['subscription-only', 'original-only', 'audio-description-only']) node(id, 'input', parameters);
let mobile = true;
const mediaListeners=[];
const stored = new Map();
const source = fs.readFileSync('app.js', 'utf8').split("for (const kind of ['platforms','languages']) renderOptions(kind);")[0];
const context = vm.createContext({
  document, window: { matchMedia: query => { assert.ok(['(max-width:900px)','(max-width:650px)'].includes(query)); return { get matches(){return mobile;},addEventListener(type,listener){if(query==='(max-width:900px)')mediaListeners.push(listener);} }; } },
  localStorage: { getItem: () => null, setItem: (key, value) => stored.set(key, value) },
  console, Intl, URL, menus, setTimeout: () => 0, clearTimeout() {},
});
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
run('const renderResults=render;const updateSelectionsReal=updateSelections;');
function escape() {
  return { key: 'Escape', defaultPrevented: false, stopped: false,
    preventDefault() { this.defaultPrevented = true; }, stopPropagation() { this.stopped = true; } };
}
function globalEscape() {
  const event = escape(); context.event = event; run('handleGlobalKeydown(event,menus)'); return event;
}
function snapshot() {
  return run(`JSON.stringify({platforms:[...selectedPlatforms],languages:[...selectedLanguages],originals:selectedOriginals&&[...selectedOriginals],genres:selectedGenres&&[...selectedGenres],originalOnly,subscriptionOnly,audioDescriptionOnly,view,contentType,weeklyKind,selectedSearchId,saved:[...saved],query:$('#search').value})`);
}

run(`
view='watchlist'; contentType='Movie'; weeklyKind='older'; selectedSearchId='motn:42';
$('#search').value='Drive'; saved.add('motn:42');
const originalTitles=titles;
`);
const initialState = snapshot();
menus[0].open = true;
run('setupFilterPanel(menus)');
assert.equal(panel.open, false, 'Mobile filters should start collapsed');
assert.ok(menus.every(menu => !menu.open), 'Starting collapsed must close child menus');
assert.equal(snapshot(), initialState, 'Disclosure setup changed catalogue selections');
run('if(titles!==originalTitles)throw Error("Disclosure setup replaced titles")');

search.focus(); suggestions.hidden = false;
panel.open = true; panel.fire('toggle', menus[0]);
assert.equal(document.activeElement, search, 'A child toggle must not dismiss search focus');
assert.equal(suggestions.hidden, false, 'A child toggle must not close autocomplete');
panel.fire('toggle');advanced.open=true;
assert.equal(document.activeElement, body, 'Opening Filters must blur the mobile search input');
assert.equal(suggestions.hidden, true, 'Opening Filters must close autocomplete');
assert.equal(search.value, 'Drive', 'Dismissing the search keyboard must retain its query');
heading.focus(); panel.fire('toggle');
assert.equal(document.activeElement, heading, 'Blurring an unfocused search must not move other focus');
menus[0].open = true; input.focus();
assert.equal(globalEscape().defaultPrevented, true);
assert.equal(menus[0].open, false);
assert.equal(panel.open, true, 'First Escape must leave the parent open');
assert.equal(document.activeElement, menus[0].querySelector('summary'));
globalEscape();
assert.equal(advanced.open, false, 'Second Escape must close More filters');
assert.equal(panel.open, true);
assert.equal(document.activeElement, advancedSummary);
globalEscape();
assert.equal(panel.open, false, 'Third Escape must close the parent');
assert.equal(document.activeElement, summary);
assert.equal(snapshot(), initialState, 'Escape changed selected filters or watchlist state');

panel.open = true; advanced.open=true;menus[1].open = true;
menus[1].querySelector('summary').focus();
panel.open = false; panel.fire('toggle');
assert.ok(menus.every(menu => !menu.open), 'Closing the parent left a child expanded');
assert.equal(document.activeElement, summary, 'Closing parent left focus hidden inside it');

panel.open = true; advanced.open=true;menus[2].open = true; done.focus(); done.onclick(); panel.fire('toggle');
assert.equal(panel.open, false);
assert.ok(menus.every(menu => !menu.open));
assert.equal(document.activeElement, heading, 'Show titles must navigate to the result heading');
assert.equal(snapshot(), initialState, 'Show titles cleared selections');

panel.open = true;advanced.open=true; menus[0].open = true; dialog.open = true;
assert.equal(globalEscape().defaultPrevented, false);
assert.equal(panel.open, true); assert.equal(menus[0].open, true, 'Report-dialog Escape closed background filters');
dialog.open = false; suggestions.hidden = false;
const searchEscape = escape(); context.event = searchEscape;
run('searchKeydown(event);handleGlobalKeydown(event,menus)');
assert.equal(suggestions.hidden, true);
assert.equal(searchEscape.stopped, true);
assert.equal(panel.open, true); assert.equal(menus[0].open, true, 'Autocomplete Escape also closed filters');

// Rendering chips exercises the same grouped filter state used by real results.
run(`
renderGenres=()=>{};renderOriginals=()=>{};updateSelections=()=>{};render=()=>activeFilterChips();
activeFilterChips();
`);
assert.equal(badge.hidden, false);assert.equal(badge.textContent,'All selected','Search, view and media type must not count as the seven parameter groups');
assert.equal(chips.children.length, 0);
run(`
selectedPlatforms.clear();selectedPlatforms.add('Netflix');
selectedLanguages.clear();selectedLanguages.add('Hindi');
selectedOriginals=new Set(['Hindi']);selectedGenres=new Set(['Drama']);
subscriptionOnly=true;originalOnly=true;audioDescriptionOnly=true;activeFilterChips();
`);
assert.equal(chips.children.length, 7);
assert.equal(badge.textContent, '7 active'); assert.equal(badge.hidden, false);
panel.open = false; panel.fire('toggle');
chips.children[2].focus(); chips.children[2].onclick();
assert.equal(run('selectedOriginals'), null);
assert.equal(run('originalOnly&&subscriptionOnly&&audioDescriptionOnly'), true, 'Removing one group reset other flags');
assert.equal(run('selectedPlatforms.size'), 1);
assert.equal(badge.textContent, '6 active');
assert.equal(document.activeElement, chips.children[2], 'Removing a middle chip must focus its remaining neighbour');
while (chips.children.length) { chips.children[0].focus(); chips.children[0].onclick(); }
assert.equal(badge.hidden, false); assert.equal(badge.textContent, 'All selected');
assert.equal(document.activeElement, summary, 'Last chip removal must focus visible Filters, not hidden Reset');
assert.equal(search.value, 'Drive', 'Removing parameter chips erased the independent search');
assert.equal(run('saved.has("motn:42")'), true, 'Removing parameter chips erased the watchlist');

mobile = false;
const wideState = snapshot();
run('setupFilterPanel(menus)');
assert.equal(panel.open, true, 'Wide screens should start with the sidebar filters expanded');
assert.equal(advanced.open, false, 'More filters must remain collapsed on desktop');
assert.ok(menus.every(menu => !menu.open));
assert.equal(snapshot(), wideState, 'Starting closed on a wide screen changed saved selections');
panel.open = true; panel.fire('toggle');
run('originalOnly=true;activeFilterChips()');
chips.children[0].onclick();
assert.equal(document.activeElement, reset, 'Reset remains a valid focus target while the panel is expanded');
assert.equal(run('titles===originalTitles'), true);
const resizeState=snapshot();mobile=true;mediaListeners.forEach(listener=>listener());
assert.equal(panel.open,false);assert.equal(advanced.open,false);assert.equal(document.activeElement,summary);
assert.equal(snapshot(),resizeState,'Resizing to mobile lost selections');
mobile=false;mediaListeners.forEach(listener=>listener());
assert.equal(panel.open,true);assert.equal(document.activeElement,search);
assert.equal(snapshot(),resizeState,'Resizing to desktop lost selections');
console.log('Mobile filter disclosure, grouped badge, retained state, Escape priority and visible focus scenarios passed.');

run(`view='weekly';weeklyKind='older';activeFilterChips()`);
for (const button of weeklyGroup.children) button.setAttribute('aria-pressed',button.dataset.kind==='older');
assert.equal(chips.children.length, 1);
assert.equal(chips.children[0].textContent, 'Additions: Older movies ×');
assert.equal(badge.textContent, '1 active'); assert.equal(badge.hidden, false);
panel.open = true; panel.fire('toggle'); menus[0].open = true;
const weeklyState = snapshot(); done.onclick(); panel.fire('toggle');
assert.equal(snapshot(), weeklyState, 'Collapsing Filters lost the weekly addition type');
assert.equal(chips.children[0].textContent, 'Additions: Older movies ×');
for (const view of ['discover','watchlist']) {
  context.testView=view;run('view=testView;activeFilterChips()');
  assert.equal(chips.children.length, 0, 'Inactive weekly selection must not add a chip in '+view);
  assert.equal(badge.hidden, false);assert.equal(badge.textContent,'All selected');
  assert.equal(run('weeklyKind'), 'older', 'Changing views must retain the weekly selection');
}
run(`view='weekly';activeFilterChips()`);
chips.children[0].onclick();
assert.equal(run('weeklyKind'), 'all');
assert.equal(chips.children.length, 0); assert.equal(badge.hidden, false);assert.equal(badge.textContent,'All selected');
assert.equal(document.activeElement, summary);
for (const button of weeklyGroup.children) assert.equal(button.attributes['aria-pressed'], String(button.dataset.kind==='all'));
run(`
weeklyKind='other';selectedPlatforms.clear();selectedPlatforms.add('Netflix');
selectedLanguages.clear();selectedLanguages.add('Hindi');
selectedOriginals=new Set(['Hindi']);selectedGenres=new Set(['Drama']);
subscriptionOnly=true;originalOnly=true;audioDescriptionOnly=true;activeFilterChips();
`);
for (const button of weeklyGroup.children) button.setAttribute('aria-pressed',button.dataset.kind==='other');
assert.equal(chips.children.length, 8); assert.equal(badge.textContent, '8 active');
const additions = chips.children.find(chip => chip.textContent === 'Additions: Other additions ×');
assert.ok(additions); additions.onclick();
assert.equal(run('weeklyKind'), 'all'); assert.equal(chips.children.length, 7);
for (const button of weeklyGroup.children) assert.equal(button.attributes['aria-pressed'], String(button.dataset.kind==='all'));
assert.equal(run('originalOnly&&subscriptionOnly&&audioDescriptionOnly'), true, 'Removing the addition type reset other groups');
while (chips.children.length) chips.children[0].onclick();
console.log('Weekly addition chips remain visible when collapsed, count only in This week, and restore All additions without clearing other filters.');

run(`
render=renderResults;titles=[];$('#search').value='';selectedSearchId=null;contentType='all';
liveCatalog={missingPlatforms:[],recentHistoryComplete:true};view='discover';render();
`);
assert.equal(ids.get('#description').hidden, true, 'Live Discover should omit redundant description text');
run(`view='watchlist';render()`);
assert.equal(ids.get('#description').hidden, true, 'Live Watchlist should omit redundant description text');
run(`view='weekly';render()`);
assert.equal(ids.get('#description').hidden, false);
assert.equal(ids.get('#description').textContent, 'Platform additions · Premiere dates unverified.');
for (const view of ['weekly', 'discover', 'watchlist']) {
  context.testView = view;
  run('liveCatalog=null;view=testView;render()');
  assert.equal(ids.get('#description').hidden, false, 'Sample views must keep their contextual descriptions');
  if (view !== 'watchlist') assert.match(ids.get('#description').textContent, /sample catalog/);
}

run(`
const cardNow=Date.now()/1000;
const cardFixture={id:'motn:101',title:'A rental film',type:'Movie',year:2001,originalLanguage:'English',
  overview:'A test overview that can be clamped to two lines.',tmdb:{genres:['Drama','Thriller','Mystery','Comedy']},
  lastCheckedAt:cardNow-60,weekly:true,weeklyPlatforms:['Netflix'],weeklyUpdatedAt:cardNow-60,
  weeklyEvents:[{platform:'Netflix',addedAt:cardNow-60}],
  offers:[{platform:'Netflix',type:'rent',audio:['English'],link:'https://www.netflix.com/title/123',availableSince:cardNow-60}]};
liveCatalog={missingPlatforms:[],recentHistoryComplete:true};view='weekly';
titles=[cardFixture,{...cardFixture,id:'motn:102',title:'Another film'}];render();
`);
const firstCard = catalog.querySelectorAll('.card')[0];
const options = firstCard.querySelector('.watch-options');
const hide = firstCard.querySelector('.dismiss-title');
const checked = firstCard.querySelector('.checked-date');
assert.equal(options.open, false);
assert.ok(options.contains(hide), 'Hide title must be inside Where to watch');
assert.ok(options.contains(checked), 'Availability date must be inside Where to watch');
assert.match(checked.textContent, /^Availability checked /);
for (const className of ['card-title', 'card-languages', 'rental-label']) {
  const detail = firstCard.querySelector('.' + className);
  assert.ok(detail && !options.contains(detail), className + ' should remain visible before expanding Where to watch');
}
assert.equal(firstCard.querySelector('.rental-label').textContent, 'Rent only');
assert.match(firstCard.querySelector('.card-languages').textContent, /Audio: English/);
assert.equal(firstCard.querySelector('.original-language').textContent, 'Original language: English');
assert.ok(options.contains(firstCard.querySelector('.original-language')), 'Original language should be inside Where to watch');
assert.ok(options.contains(firstCard.querySelector('.addition-label')), 'Repeated addition date should be inside Where to watch');
assert.equal(firstCard.querySelector('.card-title').tagName,'H3');
assert.equal(catalog.children[0].querySelector('.date-label').tagName,'H2');
assert.match(firstCard.querySelector('.card-meta').textContent,/English original · 2001 · Movie/);
assert.equal(firstCard.querySelector('.card-genres').children.length,3);
const cardBody=firstCard.querySelector('.card-body');
assert.ok(cardBody.children.indexOf(firstCard.querySelector('.card-genres'))<cardBody.children.indexOf(firstCard.querySelector('.card-overview')));
assert.equal(firstCard.children[0].tagName,'A');
assert.equal(firstCard.querySelector('.save').parentElement,firstCard,'Watchlist button must sit outside the poster link');
assert.match(firstCard.querySelector('.addition-label').textContent, /Added /);
options.open = true; hide.focus(); hide.onclick();
assert.equal(run('dismissed.has("motn:101")'), true, 'Relocated Hide title lost its handler');
assert.ok(stored.get('ottscout-dismissed').includes('motn:101'), 'Hide title no longer persists');
assert.equal(catalog.querySelectorAll('.card').length, 1);
assert.equal(catalog.querySelectorAll('.card')[0].dataset.titleId, 'motn:102');
assert.equal(document.activeElement, catalog.querySelectorAll('.card')[0].querySelector('.card-title').querySelector('a'), 'Hiding a title must preserve focus on the next visible card');
assert.equal(ids.get('#restore-hidden').hidden, false, 'Hidden title must remain restorable');
run('saved.add("motn:102");view="watchlist";render()');
assert.equal(catalog.children[0].querySelector('.dismiss-title'), null, 'Watchlist should keep its existing absence of Hide title');
assert.ok(catalog.children[0].querySelector('.watch-options').contains(catalog.children[0].querySelector('.checked-date')));
const sampleCard=run(`liveCatalog=null;view='discover';cardFor(sampleTitles[0])`);
const sampleOptions=sampleCard.querySelector('.watch-options');
assert.match(sampleCard.querySelector('.badge').textContent, /Sample/);
assert.ok(!sampleOptions.contains(sampleCard.querySelector('.badge')), 'Sample source label must stay visible');
assert.ok(!sampleOptions.contains(sampleCard.querySelector('.card-languages')), 'Available audio must stay beside the sample title');
assert.ok(sampleOptions.contains(sampleCard.querySelector('.original-language')));
assert.equal(sampleCard.querySelector('.original-language').textContent, 'Original language: Unverified', 'Moving original metadata must not infer it from available audio');
console.log('Concise view context and expandable original-language details retain visible audio/rental/source metadata, hide persistence and next-card focus.');
run(`
liveCatalog={missingPlatforms:[],recentHistoryComplete:true};view='discover';
titles=Array.from({length:13},(_,i)=>({...cardFixture,id:'motn:ad-'+i,title:'Film '+i}));render();
`);
assert.equal(catalog.children.length, 14);
const infeed=catalog.children[12];
assert.equal(infeed.tagName, 'ASIDE', 'Desktop in-feed placement must remain after twelve titles');
assert.equal(catalog.children.filter(child=>child.tagName==='ASIDE').length, 1);
assert.equal(infeed.attributes['aria-label'], 'Reserved in-feed advertisement space');
assert.equal(infeed.children.length, 1);
assert.equal(infeed.children[0].textContent, 'Advertisement');
assert.equal(infeed.querySelector('.ad-placeholder'), null);
console.log('In-feed advertisement remains bounded and in its existing position with a single clear label.');

run(`
updateSelections=updateSelectionsReal;
selectedPlatforms.clear();selectedPlatforms.add('Netflix');selectedPlatforms.add('Prime Video');
selectedLanguages.clear();languages.forEach(name=>selectedLanguages.add(name));
liveCatalog={missingPlatforms:[],recentHistoryComplete:true};view='discover';$('#search').value='';selectedSearchId=null;
titles=[{...cardFixture,id:'quick-en',title:'English film'},
 {...cardFixture,id:'quick-hi',title:'Hindi film',offers:[{platform:'Prime Video',audio:['Hindi'],type:'subscription'}]}];
setupQuickFilters();render();
`);
assert.equal(quickPlatforms[2].hidden,true,'Unsupported platform must not appear in the quick choices');
assert.equal(quickPlatforms[2].disabled,true);
assert.equal(platformStatus.textContent,'All 2 selected');assert.equal(allPlatforms.attributes['aria-pressed'],'true');
quickPlatforms[0].onclick();
assert.equal(run('[...selectedPlatforms].join()'),'Prime Video','Deselecting Netflix from All must retain the other platforms');
assert.equal(quickPlatforms[0].attributes['aria-pressed'],'false');
assert.equal(quickPlatforms[1].attributes['aria-pressed'],'true');
assert.equal(ids.get('#platforms').children[0].checked,false);
assert.equal(ids.get('#platforms').children[1].checked,true,'Quick choice must sync checkbox controls');
assert.equal(platformStatus.textContent,'1 of 2 selected');assert.equal(allPlatforms.attributes['aria-pressed'],'false');
quickPlatforms[0].onclick();
assert.equal(run('selectedPlatforms.size'),2);assert.equal(platformStatus.textContent,'All 2 selected');
assert.ok(quickPlatforms.slice(0,2).every(button=>button.attributes['aria-pressed']==='true'),'Both platform indicators must remain pressed after choosing all');
quickPlatforms[0].onclick();quickPlatforms[1].onclick();
assert.equal(platformStatus.textContent,'None selected');assert.equal(allPlatforms.attributes['aria-pressed'],'false');
assert.equal(run('selectedPlatforms.size'),0);
allPlatforms.onclick();
assert.equal(platformStatus.textContent,'All 2 selected');assert.equal(run('selectedPlatforms.size'),2);
assert.equal(stored.get('ottscout-platforms'),'["Netflix","Prime Video"]');
assert.equal(languageStatus.textContent,'All 6 selected');assert.equal(allLanguages.attributes['aria-pressed'],'true');
quickLanguages[1].onclick();
assert.equal(run('selectedLanguages.size'),5,'Deselecting Hindi from All must preserve the other five languages');
assert.equal(quickLanguages[1].attributes['aria-pressed'],'false');
assert.equal(ids.get('#languages').children[1].checked,false);
assert.equal(ids.get('#languages').children[0].checked,true);
assert.equal(languageStatus.textContent,'5 of 6 selected');assert.equal(allLanguages.attributes['aria-pressed'],'false');
function restoredQuickState(){
  const persisted=vm.createContext({document,console,Intl,URL,localStorage:{getItem:key=>stored.get(key)||null},restoredData:JSON.parse(run('JSON.stringify({titles,liveCatalog})'))});
  vm.runInContext(source,persisted);vm.runInContext('titles=restoredData.titles;liveCatalog=restoredData.liveCatalog;syncQuickFilters()',persisted);return persisted;
}
let restoredQuick=restoredQuickState();
assert.equal(vm.runInContext('selectedLanguages.size',restoredQuick),5);assert.equal(languageStatus.textContent,'5 of 6 selected');
assert.equal(quickLanguages[1].attributes['aria-pressed'],'false','Reloading partial saved choices must retain pressed states');
quickLanguages[1].onclick();
assert.equal(languageStatus.textContent,'All 6 selected');
assert.ok(quickLanguages.every(button=>button.attributes['aria-pressed']==='true'),'All six language indicators must remain pressed');
quickLanguages.forEach(button=>button.onclick());
assert.equal(languageStatus.textContent,'None selected');assert.equal(run('selectedLanguages.size'),0);
restoredQuick=restoredQuickState();assert.equal(vm.runInContext('selectedLanguages.size',restoredQuick),0);assert.equal(languageStatus.textContent,'None selected');
allLanguages.onclick();
assert.equal(languageStatus.textContent,'All 6 selected');assert.equal(allLanguages.attributes['aria-pressed'],'true');
restoredQuick=restoredQuickState();
assert.equal(vm.runInContext('selectedLanguages.size',restoredQuick),6);assert.equal(vm.runInContext('selectedPlatforms.size',restoredQuick),2);
assert.ok(quickLanguages.every(button=>button.attributes['aria-pressed']==='true'));assert.equal(platformStatus.textContent,'All 2 selected');
assert.equal(badge.textContent,'All selected');assert.equal(badge.hidden,false);
assert.equal(run('saved.has("motn:42")'),true,'Quick filters must not change saved titles');

run(`
const nativeNow=Date.now;Date.now=()=>Date.parse('2026-11-02T10:00:00Z');
let lastAnnouncement='';announceResults=message=>{lastAnnouncement=message;};
selectedPlatforms.clear();platforms.forEach(name=>selectedPlatforms.add(name));
selectedLanguages.clear();languages.forEach(name=>selectedLanguages.add(name));
selectedOriginals=null;selectedGenres=null;originalOnly=false;subscriptionOnly=false;audioDescriptionOnly=false;
view='weekly';weeklyKind='all';$('#search').value='';selectedSearchId=null;weeklyOpen.clear();weeklyLimits.clear();
const daily=(id,title,added)=>({...cardFixture,id,title,weeklyUpdatedAt:added,weeklyEvents:[{platform:'Netflix',addedAt:added}],offers:[{platform:'Netflix',audio:['English'],type:'subscription',availableSince:added}]});
const newest=Date.parse('2026-11-01T10:00:00Z')/1000;
const previous=Date.parse('2026-10-31T10:00:00Z')/1000;
titles=[...Array.from({length:31},(_,i)=>daily('new-'+i,'New '+String(i).padStart(2,'0'),newest)),
 ...Array.from({length:12},(_,i)=>daily('old-'+i,'Old '+String(i).padStart(2,'0'),previous))];render();
`);
assert.equal(catalog.children.length,2,'Older day headers must exist even when the newest day has over 24 titles');
let newestGroup=catalog.children[0], olderGroup=catalog.children[1];
assert.equal(newestGroup.dataset.date,'2026-11-01');
assert.equal(newestGroup.querySelector('.date-label').textContent,'Sunday, 1 November');
assert.equal(newestGroup.querySelector('.date-count').textContent,'31 titles');
assert.equal(newestGroup.open,true);assert.equal(olderGroup.open,false);
assert.equal(newestGroup.querySelectorAll('.card').length,24);
assert.equal(olderGroup.querySelectorAll('.card').length,12);
assert.equal(run('visibleCards().length'),24,'Collapsed-day cards must not count as visible');
assert.equal(ids.get('#load-more').hidden,true,'Weekly must use per-day paging');
assert.match(run('lastAnnouncement'),/24 titles shown in 1 open group/);
assert.equal(toggleDates.textContent,'Collapse all dates');
run('toggleAllDates()');
assert.ok(catalog.children.every(group=>!group.open));
assert.equal(toggleDates.textContent,'Expand all dates');
assert.equal(document.activeElement,toggleDates,'Date controls must retain focus on their stable button');
assert.match(run('lastAnnouncement'),/0 titles shown in 0 open groups/);
run('toggleAllDates()');
assert.ok(catalog.children.every(group=>group.open));
assert.equal(toggleDates.textContent,'Collapse all dates');
assert.match(run('lastAnnouncement'),/36 titles shown in 2 open groups/);
run('toggleAllDates()');
newestGroup=catalog.children[0];olderGroup=catalog.children[1];
newestGroup.open=true;newestGroup.fire('toggle');
const dayMore=newestGroup.querySelector('.date-load-more');
assert.match(dayMore.textContent,/Show 7 more.*24 of 31 shown/);
dayMore.onclick();newestGroup=catalog.children[0];olderGroup=catalog.children[1];
assert.equal(newestGroup.querySelectorAll('.card').length,31);
assert.equal(newestGroup.querySelector('.date-load-more'),null);
assert.equal(olderGroup.open,false,'Paging the latest day must not open older groups');
assert.equal(document.activeElement.parentElement.id,'title-new-24','Per-day paging must focus the first newly revealed card title');
olderGroup.open=true;olderGroup.fire('toggle');
assert.match(run('lastAnnouncement'),/43 titles shown in 2 open groups/);
newestGroup.open=false;newestGroup.fire('toggle');
assert.match(run('lastAnnouncement'),/12 titles shown in 1 open group/);
run('render()');assert.equal(catalog.children[0].open,false);assert.equal(catalog.children[1].open,true);
assert.equal(catalog.children[0].querySelectorAll('.card').length,31,'Re-rendering lost per-day paging');
assert.equal(run('visibleCards().every(card=>card.dataset.titleId.startsWith("old-"))'),true,'Focus candidates include a collapsed day');
run(`$('#search').value='no matches';render();$('#search').value='';setView('discover');setView('weekly');`);
assert.equal(catalog.children[0].open,false);assert.equal(catalog.children[1].open,true);
assert.equal(catalog.children[0].querySelectorAll('.card').length,31,'Changing filters/views discarded retained day limits');
run(`liveCatalog=null;titles=sampleTitles.filter(title=>title.weekly);weeklyOpen.clear();render()`);
assert.equal(catalog.children.length,1);
assert.equal(catalog.children[0].dataset.date,'unverified');
assert.equal(catalog.children[0].querySelector('.date-label').textContent,'Addition date unverified','Sample years must not fabricate addition dates');

run(`
liveCatalog={missingPlatforms:[],recentHistoryComplete:true};view='leaving';$('#search').value='';selectedSearchId=null;
const expires=Date.now()/1000+5*DAY;
const expiring={...cardFixture,id:'expiring',title:'Expiring film',offers:[
 {platform:'Prime Video',audio:['English'],type:'subscription',link:'https://www.primevideo.com/detail/TEST'},
 {platform:'Netflix',audio:['English'],type:'rent',expiresOn:expires,link:'https://www.netflix.com/title/123'}]};
titles=[expiring,{...expiring,id:'sentinel',title:'Sentinel film',offers:[{platform:'Netflix',audio:['English'],type:'subscription',expiresOn:253368115140}]}];render();
`);
assert.equal(catalog.children.length,1);
const leavingCard=catalog.children[0];
assert.match(leavingCard.querySelector('.expiry-label').textContent,/on Netflix$/,'Departure date must name the expiring platform');
assert.equal(leavingCard.querySelector('.primary-platform').attributes['aria-label'],'Netflix — watch Expiring film');
assert.equal(leavingCard.querySelector('.primary-offer-label').textContent,'Rent');
assert.equal(leavingCard.querySelector('.rental-label').textContent,'Rent option','An expiring rental must not hide an included alternative behind a Rent only label');
assert.equal(leavingCard.querySelector('.watch-options').querySelectorAll('.offer').length,2,'Where to watch must retain alternative offers');
assert.equal(ids.get('#leaving-count').textContent,1);
assert.equal(ids.get('#pick-one').disabled,false);
assert.equal(toggleDates.hidden,true,'Date controls must be hidden outside the weekly view');
run(`
saved.clear();saved.add('expiring');view='watchlist';render();
const pickState=JSON.stringify({platforms:[...selectedPlatforms],languages:[...selectedLanguages],originals:selectedOriginals,genres:selectedGenres,originalOnly,subscriptionOnly,audioDescriptionOnly,saved:[...saved]});
pickRandomTitle();
if(JSON.stringify({platforms:[...selectedPlatforms],languages:[...selectedLanguages],originals:selectedOriginals,genres:selectedGenres,originalOnly,subscriptionOnly,audioDescriptionOnly,saved:[...saved]})!==pickState)throw Error('Random pick changed saved state or filters');
`);
assert.equal(run('selectedSearchId'),'expiring');assert.equal(run('view'),'discover');
assert.match(run('lastAnnouncement'),/^Random pick: Expiring film/);
assert.equal(document.activeElement,heading);
run(`$('#search').value='no eligible title';selectedSearchId=null;render();`);
assert.equal(ids.get('#pick-one').disabled,true);
const noPickState=snapshot();run('pickRandomTitle()');assert.equal(snapshot(),noPickState);
run(`
view='weekly';$('#search').value='';selectedSearchId=null;contentType='all';weeklyKind='all';
selectedPlatforms.clear();selectedPlatforms.add('Netflix');
selectedLanguages.clear();languages.forEach(name=>selectedLanguages.add(name));
selectedOriginals=null;selectedGenres=null;originalOnly=false;subscriptionOnly=false;audioDescriptionOnly=false;
const contextPrime={...daily('context-prime','Hidden Prime title',newest),weeklyPlatforms:['Prime Video'],weeklyEvents:[{platform:'Prime Video',addedAt:newest}],offers:[{platform:'Prime Video',audio:['English'],type:'subscription',availableSince:newest}]};
titles=[contextPrime,daily('context-netflix','Visible Netflix title',previous),{...contextPrime,id:'dismissed-context',title:'Never reveal dismissed title'}];
dismissed.add('dismissed-context');weeklyOpen.clear();weeklyLimits.clear();render();
`);
assert.equal(catalog.children.length,2,'Platform filters must not erase a valid source date');
let zeroDay=catalog.children[0];
assert.equal(zeroDay.dataset.date,'2026-11-01');assert.equal(zeroDay.open,true);
assert.equal(zeroDay.querySelector('.date-count').textContent,'0 matches');
assert.equal(zeroDay.querySelectorAll('.card').length,0,'Context must not expose a filtered title');
assert.equal(zeroDay.querySelector('.date-filtered').querySelector('p').textContent,'1 addition on Prime Video is hidden by your filters.');
const allText=node=>[node.textContent,...node.children.map(allText)].join(' ');
assert.ok(!allText(catalog).includes('Hidden Prime title'));
assert.ok(!allText(catalog).includes('Never reveal dismissed title'));
assert.equal(catalog.querySelectorAll('.card').length,1);
assert.equal(catalog.querySelector('.card').dataset.titleId,'context-netflix');
run('toggleAllDates()');
assert.ok(catalog.children.every(group=>!group.open),'Collapse all must include zero-match context dates');
assert.equal(toggleDates.textContent,'Expand all dates');assert.equal(document.activeElement,toggleDates);
run('toggleAllDates()');assert.ok(catalog.children.every(group=>group.open));
zeroDay=catalog.children[0];
const resetZero=zeroDay.querySelector('.date-filtered').querySelector('button');
resetZero.focus();resetZero.onclick();
const restoredDay=catalog.children[0];
assert.equal(restoredDay.dataset.date,'2026-11-01');assert.equal(restoredDay.open,true);
assert.equal(restoredDay.querySelector('.date-count').textContent,'1 title');
assert.equal(restoredDay.querySelector('.date-filtered'),null);
assert.equal(restoredDay.querySelector('.card').dataset.titleId,'context-prime');
assert.equal(document.activeElement,restoredDay.querySelector('summary'),'Reset must focus the restored date summary');
assert.notEqual(document.activeElement.tabIndex,-1,'Restoring the date must not remove its summary from keyboard tab order');
assert.equal(platformStatus.textContent,'All 2 selected');assert.equal(languageStatus.textContent,'All 6 selected');
assert.equal(allPlatforms.attributes['aria-pressed'],'true');assert.equal(allLanguages.attributes['aria-pressed'],'true');
assert.equal(badge.textContent,'All selected');assert.equal(badge.hidden,false);
assert.equal(run('saved.has("expiring")'),true,'Resetting filters must keep the saved list');
assert.equal(run('dismissed.has("dismissed-context")'),true,'Resetting filters must not unhide dismissed titles');
run(`dismissed.add('context-prime');render()`);
assert.ok(catalog.children.every(group=>group.dataset.date!=='2026-11-01'),'A date containing only dismissed titles must not leak back through context');
run('Date.now=nativeNow');
console.log('Quick all/partial/none persistence, date-context reset/focus, nested sidebar, paging, Leaving soon and random-pick state scenarios passed.');
