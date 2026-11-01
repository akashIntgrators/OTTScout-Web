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
  querySelector: selector => ids.get(selector) || null,
  querySelectorAll: selector => selector === '#catalog .card' ? ids.get('#catalog').querySelectorAll('.card') : selector === '#weekly-kind button' ? ids.get('#weekly-kind').querySelectorAll('button') : [],
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
const menus = ['platform', 'language', 'original', 'genre'].map(name => {
  const menu = node(name + '-menu', 'details', parameters);
  node(name + '-summary', 'summary', menu);
  return menu;
});
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
const stored = new Map();
const source = fs.readFileSync('app.js', 'utf8').split("for (const kind of ['platforms','languages']) renderOptions(kind);")[0];
const context = vm.createContext({
  document, window: { matchMedia: query => { assert.ok(['(max-width:760px)','(max-width:650px)'].includes(query)); return { matches: mobile }; } },
  localStorage: { getItem: () => null, setItem: (key, value) => stored.set(key, value) },
  console, Intl, URL, menus, setTimeout: () => 0, clearTimeout() {},
});
vm.runInContext(source, context);
const run = code => vm.runInContext(code, context);
run('const renderResults=render;');
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
panel.fire('toggle');
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
assert.equal(panel.open, false, 'Second Escape must close the parent');
assert.equal(document.activeElement, summary);
assert.equal(snapshot(), initialState, 'Escape changed selected filters or watchlist state');

panel.open = true; menus[1].open = true;
menus[1].querySelector('summary').focus();
panel.open = false; panel.fire('toggle');
assert.ok(menus.every(menu => !menu.open), 'Closing the parent left a child expanded');
assert.equal(document.activeElement, summary, 'Closing parent left focus hidden inside it');

panel.open = true; menus[2].open = true; done.focus(); done.onclick(); panel.fire('toggle');
assert.equal(panel.open, false);
assert.ok(menus.every(menu => !menu.open));
assert.equal(document.activeElement, heading, 'Show titles must navigate to the result heading');
assert.equal(snapshot(), initialState, 'Show titles cleared selections');

panel.open = true; menus[0].open = true; dialog.open = true;
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
assert.equal(badge.hidden, true, 'Search, view and media type must not count as the seven parameter groups');
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
assert.equal(badge.hidden, true); assert.equal(badge.textContent, '0 active');
assert.equal(document.activeElement, summary, 'Last chip removal must focus visible Filters, not hidden Reset');
assert.equal(search.value, 'Drive', 'Removing parameter chips erased the independent search');
assert.equal(run('saved.has("motn:42")'), true, 'Removing parameter chips erased the watchlist');

mobile = false;
const wideState = snapshot();
run('setupFilterPanel(menus)');
assert.equal(panel.open, false, 'Wide screens should also start with filters collapsed');
assert.ok(menus.every(menu => !menu.open));
assert.equal(snapshot(), wideState, 'Starting closed on a wide screen changed saved selections');
panel.open = true; panel.fire('toggle');
run('originalOnly=true;activeFilterChips()');
chips.children[0].onclick();
assert.equal(document.activeElement, reset, 'Reset remains a valid focus target while the panel is expanded');
assert.equal(run('titles===originalTitles'), true);
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
  assert.equal(badge.hidden, true);
  assert.equal(run('weeklyKind'), 'older', 'Changing views must retain the weekly selection');
}
run(`view='weekly';activeFilterChips()`);
chips.children[0].onclick();
assert.equal(run('weeklyKind'), 'all');
assert.equal(chips.children.length, 0); assert.equal(badge.hidden, true);
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
  lastCheckedAt:cardNow-60,weekly:true,weeklyPlatforms:['Netflix'],weeklyUpdatedAt:cardNow-60,
  weeklyEvents:[{platform:'Netflix',addedAt:cardNow-60}],
  offers:[{platform:'Netflix',type:'rent',audio:['English'],link:'https://www.netflix.com/title/123',availableSince:cardNow-60}]};
liveCatalog={missingPlatforms:[],recentHistoryComplete:true};view='weekly';
titles=[cardFixture,{...cardFixture,id:'motn:102',title:'Another film'}];render();
`);
const firstCard = catalog.children[0];
const options = firstCard.querySelector('.watch-options');
const hide = firstCard.querySelector('.dismiss-title');
const checked = firstCard.querySelector('.checked-date');
assert.equal(options.open, false);
assert.ok(options.contains(hide), 'Hide title must be inside Where to watch');
assert.ok(options.contains(checked), 'Availability date must be inside Where to watch');
assert.match(checked.textContent, /^Availability checked /);
for (const className of ['card-title', 'card-languages', 'rental-label', 'addition-label']) {
  const detail = firstCard.querySelector('.' + className);
  assert.ok(detail && !options.contains(detail), className + ' should remain visible before expanding Where to watch');
}
assert.equal(firstCard.querySelector('.rental-label').textContent, 'Rent only');
assert.match(firstCard.querySelector('.card-languages').textContent, /Audio: English/);
assert.equal(firstCard.querySelector('.original-language').textContent, 'Original language: English');
assert.ok(options.contains(firstCard.querySelector('.original-language')), 'Original language should be inside Where to watch');
assert.match(firstCard.querySelector('.addition-label').textContent, /Added /);
options.open = true; hide.focus(); hide.onclick();
assert.equal(run('dismissed.has("motn:101")'), true, 'Relocated Hide title lost its handler');
assert.ok(stored.get('ottscout-dismissed').includes('motn:101'), 'Hide title no longer persists');
assert.equal(catalog.children.length, 1);
assert.equal(catalog.children[0].dataset.titleId, 'motn:102');
assert.equal(document.activeElement, catalog.children[0].querySelector('a'), 'Hiding a title must preserve focus on the next card');
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
