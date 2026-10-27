const platforms = ['Netflix', 'Prime Video', 'Sun NXT', 'JioHotstar', 'ZEE5', 'aha', 'SonyLIV'];
const languages = ['English', 'Hindi', 'Telugu', 'Tamil', 'Kannada', 'Malayalam'];
const sampleTitles = [
  ['The Last Horizon', 'Movie', 2026, 'Netflix', ['English', 'Hindi'], '#456359', true, 'horizon', ['Adventure', 'Science fiction']],
  ['Hyderabad Nights', 'Series', 2026, 'aha', ['Telugu', 'Tamil'], '#70483a', true, 'hyderabad', ['Drama']],
  ['Monsoon Letters', 'Movie', 2025, 'Prime Video', ['Malayalam', 'Tamil', 'Hindi'], '#46647b', false, 'monsoon', ['Romance', 'Drama']],
  ['City of Echoes', 'Series', 2026, 'SonyLIV', ['Hindi', 'English'], '#675173', true, 'echoes', ['Mystery', 'Thriller']],
  ['A Sunday in Chennai', 'Movie', 2026, 'Sun NXT', ['Tamil', 'Telugu'], '#9b6740', false, 'chennai', ['Drama', 'Comedy']],
  ['Beyond the Hills', 'Movie', 2026, 'ZEE5', ['Kannada', 'Telugu'], '#536744', true, 'hills', ['Adventure']],
  ['The Quiet Coast', 'Series', 2025, 'JioHotstar', ['English', 'Hindi', 'Tamil'], '#376c72', false, 'coast', ['Mystery']],
  ['Homeward Bound', 'Movie', 2026, 'Prime Video', ['Malayalam', 'Kannada'], '#866252', true, 'homeward', ['Family', 'Drama']],
].map((x, id) => ({ id, title: x[0], type: x[1], year: x[2], platform: x[3], audio: x[4], color: x[5], weekly: x[6], artwork: x[7], genres: x[8] }));

const $ = selector => document.querySelector(selector);
const DAY = 86400;
const PAGE_SIZE = 24;
let titles = sampleTitles;
let liveCatalog = null;
let view = 'weekly';
let contentType = 'all';
let visibleLimit = PAGE_SIZE;
const storedGenres = readList('ottscout-genres');
let selectedGenres = storedGenres && !storedGenres.includes('*') ? new Set(storedGenres) : null;
let originalOnly = readList('ottscout-original-only')?.[0] === true;
let subscriptionOnly = readList('ottscout-subscription-only')?.[0] === true;
const originalChoices = [...languages, 'Other languages', 'Unverified'];
const storedOriginals = readList('ottscout-originals');
let selectedOriginals = storedOriginals && !storedOriginals.includes('*') ? new Set(storedOriginals.filter(x=>originalChoices.includes(x))) : null;

function readList(key) {
  try { const value = JSON.parse(localStorage.getItem(key)); return Array.isArray(value) ? value : null; }
  catch { return null; }
}
function persist(key, value) {
  try { localStorage.setItem(key, JSON.stringify([...value])); } catch { /* Optional browser storage. */ }
}
const dismissed = new Set(readList('ottscout-dismissed') || []);
const saved = new Set(readList('ottscout-watchlist') || []);
const legacyExcluded = readList('ottscout-excluded-platforms') || [];
const selectedPlatforms = new Set((readList('ottscout-platforms') || platforms.filter(name => !legacyExcluded.includes(name))).filter(name => platforms.includes(name)));
const selectedLanguages = new Set((readList('ottscout-languages') || languages).filter(name => languages.includes(name)));

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function secureURL(value) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; } catch { return null; }
}
function weeklyTitle(title) {
  if (!liveCatalog) return Boolean(title.weekly);
  if (!title.weekly || !title.weeklyPlatforms.length) return false;
  if (!Number.isFinite(title.weeklyUpdatedAt)) return true; // Older published schema.
  const now = Date.now() / 1000;
  return title.weeklyUpdatedAt <= now && title.weeklyUpdatedAt >= now - 7 * DAY;
}
function originalBucket(title) {
  return title.originalLanguage ? languages.includes(title.originalLanguage) ? title.originalLanguage : 'Other languages' : 'Unverified';
}
function matchingOriginal(title) {
  return selectedOriginals===null || selectedOriginals.has(originalBucket(title));
}
function matchingOffers(title, weeklyOnly = view === 'weekly') {
  const offers = title.offers || [{platform:title.platform, audio:title.audio, subtitles:[], type:'sample'}];
  const priority = {subscription:0, free:1, addon:2, rent:3, buy:4, sample:5};
  return offers.filter(offer => matchingOriginal(title) && selectedPlatforms.has(offer.platform)
    && (!subscriptionOnly || (offer.type==='subscription' && !offer.addon))
    && offer.audio.some(language => selectedLanguages.has(language) && (!originalOnly || language === title.originalLanguage))
    && (!weeklyOnly || !liveCatalog || title.weeklyPlatforms.includes(offer.platform)))
    .sort((a,b) => (priority[a.type] ?? 6) - (priority[b.type] ?? 6) || a.platform.localeCompare(b.platform));
}
function formatLanguages(available) {
  if (!available.length) return 'Unverified';
  const preferred = languages.filter(language => available.includes(language));
  if (preferred.length) {
    const others = available.length - preferred.length;
    return preferred.join(' · ') + (others ? ` · +${others} more` : '');
  }
  const labels = available.map(language => {
    try { return /^[a-z]{2,3}$/.test(language) ? new Intl.DisplayNames(['en'], {type:'language'}).of(language) : language; }
    catch { return language; }
  });
  return labels.slice(0,3).join(' · ') + (labels.length > 3 ? ` · +${labels.length - 3} more` : '');
}
const offerNames = {subscription:'Included with subscription', free:'Free to watch', rent:'Rent', buy:'Buy', addon:'Add-on subscription', sample:'Sample listing'};
function providerLink(offer) {
  const href = secureURL(offer.link);
  const link = element(href ? 'a' : 'div', offer.platform + (href ? ' ↗' : ''), 'provider');
  if (href) { link.href = href; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
  return link;
}
function offerBody(offer, includeSubtitles = true) {
  const node = element('div', undefined, 'offer');
  node.append(providerLink(offer), element('div', `${offerNames[offer.type] || 'Offer unverified'}${offer.addon ? ' · ' + offer.addon : ''}`, 'offer-type'));
  const audio = element('div', undefined, 'audio');
  audio.append(element('span','Audio: '), document.createTextNode(formatLanguages(offer.audio)));
  node.append(audio);
  if (includeSubtitles) {
    const subtitles = element('div', undefined, 'audio');
    subtitles.append(element('span','Subtitles: '), document.createTextNode(formatLanguages(offer.subtitles)));
    node.append(subtitles);
  }
  return node;
}
function cardFor(title) {
  const offers = matchingOffers(title);
  const card = element('article', undefined, 'card');
  const poster = element('div', undefined, 'poster');
  poster.style.setProperty('--poster-color', title.color || '#345347');
  const fallback = element('strong', title.title, 'poster-title');
  const imageURL = liveCatalog ? secureURL(title.poster) : `assets/${title.artwork}.png`;
  fallback.hidden = Boolean(imageURL && liveCatalog);
  if (imageURL) {
    const image = element('img');
    image.src = imageURL; image.alt = ''; image.loading = 'lazy'; image.width = 480; image.height = 720;
    image.onerror = () => { image.remove(); fallback.hidden = false; };
    poster.append(image);
  }
  poster.append(fallback, element('span', title.type + (liveCatalog ? '' : ' · Sample'), 'badge'));
  const save = element('button', saved.has(title.id) ? '✓' : '+', 'save');
  save.type = 'button';
  save.setAttribute('aria-label', `${saved.has(title.id) ? 'Remove from' : 'Add to'} watchlist: ${title.title}`);
  save.setAttribute('aria-pressed', saved.has(title.id));
  save.onclick = () => {
    saved.has(title.id) ? saved.delete(title.id) : saved.add(title.id);
    persist('ottscout-watchlist', saved);
    // Preserve focus when a saved card remains visible.
    if (view === 'watchlist') render();
    else {
      save.textContent = saved.has(title.id) ? '✓' : '+';
      save.setAttribute('aria-pressed', saved.has(title.id));
      save.setAttribute('aria-label', `${saved.has(title.id) ? 'Remove from' : 'Add to'} watchlist: ${title.title}`);
      $('#count').textContent = saved.size;
    }
  };
  poster.append(save);
  const body = element('div', undefined, 'card-body');
  const audio = [...new Set(offers.flatMap(offer => offer.audio))];
  const heading = element('h3', undefined, 'card-title');
  const name = element(liveCatalog ? 'a' : 'span', title.title);
  if (liveCatalog) name.href = '/titles/' + encodeURIComponent(title.id.replace(/^motn:/, '')) + '/';
  heading.append(name, document.createTextNode(' '), element('span', '· Audio: ' + formatLanguages(audio), 'card-languages'));
  body.append(heading, element('div', 'Original language: ' + formatLanguages(title.originalLanguage ? [title.originalLanguage] : []), 'original-language'));
  if (view !== 'watchlist') {
    const dismiss = element('button', 'Hide title', 'dismiss-title');
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', 'Hide title: ' + title.title);
    dismiss.onclick = () => { dismissed.add(title.id); persist('ottscout-dismissed', dismissed); render(); };
    body.append(dismiss);
  }
  const options = element('details', undefined, 'watch-options');
  options.append(element('summary', 'Where to watch'));
  if(title.tmdb) {
    const metadata=element('div',`Genres: ${title.tmdb.genres.join(' · ') || 'Unverified'}`, 'audio');
    const credit=element('a','Original language & genres: TMDB ↗','provider');
    credit.href='https://www.themoviedb.org/'+title.tmdb.mediaType+'/'+title.tmdb.id;credit.target='_blank';credit.rel='noopener noreferrer';
    options.append(metadata,credit);
  }
  offers.forEach(offer => options.append(offerBody(offer)));
  const report = element('button','Report incorrect details','report-button');
  report.type='button'; report.onclick=()=>openReport(title); options.append(report);
  body.append(options);
  card.append(poster, body);
  return card;
}
function adSlot() {
  const slot = element('aside', undefined, 'ad-slot ad-infeed');
  slot.setAttribute('aria-label','Advertisement space');
  slot.append(element('span','ADVERTISEMENT','ad-label'));
  const copy = element('div', undefined, 'ad-placeholder');
  copy.append(element('span','Your ad here'), element('small','In-feed placement'));
  slot.append(copy);
  return slot;
}
function titleGenres(title) {
  return Array.isArray(title.tmdb?.genres) && title.tmdb.genres.length ? title.tmdb.genres : ['Unverified'];
}
function matchingGenres(title) {
  return selectedGenres === null || titleGenres(title).some(genre => selectedGenres.has(genre));
}
function genreOptions() {
  return [...new Set(titles.flatMap(titleGenres))].sort((a,b) => a === 'Unverified' ? 1 : b === 'Unverified' ? -1 : a.localeCompare(b));
}
function renderGenres() {
  const genres = genreOptions();
  $('#genres').replaceChildren(...genres.map(genre => {
    const label = element('label');
    const checkbox = element('input'); checkbox.type='checkbox'; checkbox.value=genre;
    checkbox.checked = selectedGenres === null || selectedGenres.has(genre);
    checkbox.setAttribute('aria-label',genre);
    checkbox.onchange=()=>{
      if(selectedGenres===null) selectedGenres=new Set(genres);
      checkbox.checked ? selectedGenres.add(genre) : selectedGenres.delete(genre);
      persist('ottscout-genres',selectedGenres); visibleLimit=PAGE_SIZE;$('#genre-summary small').textContent=selectedGenres.size;render();
    };
    label.append(checkbox,element('span',genre)); return label;
  }));
  $('#genre-summary small').textContent=selectedGenres===null ? 'All' : [...selectedGenres].filter(g=>genres.includes(g)).length;
}
function renderOriginals() {
  $('#originals').replaceChildren(...originalChoices.map(language=>{
    const label=element('label');const input=element('input');input.type='checkbox';input.value=language;
    input.checked=selectedOriginals===null || selectedOriginals.has(language);
    input.setAttribute('aria-label','Originally '+language);
    input.onchange=()=>{if(selectedOriginals===null)selectedOriginals=new Set(originalChoices);input.checked?selectedOriginals.add(language):selectedOriginals.delete(language);persist('ottscout-originals',selectedOriginals);visibleLimit=PAGE_SIZE;$('#original-summary small').textContent=selectedOriginals.size;render();};
    label.append(input,element('span',language));return label;
  }));
  $('#original-summary small').textContent=selectedOriginals===null?'All':selectedOriginals.size;
}
function activeFilterChips() {
  const chips=[];
  function chip(label,reset){const button=element('button',label+' ×','filter-chip');button.type='button';button.setAttribute('aria-label','Remove filter: '+label);button.onclick=()=>{reset();visibleLimit=PAGE_SIZE;updateSelections();renderGenres();renderOriginals();render();};chips.push(button);}
  const brief=items=>items.length ? items.slice(0,2).join(', ')+(items.length>2?` +${items.length-2}`:''):'None';
  if(selectedPlatforms.size!==platforms.length)chip('Platforms: '+brief([...selectedPlatforms]),()=>{selectedPlatforms.clear();platforms.forEach(x=>selectedPlatforms.add(x));persist('ottscout-platforms',selectedPlatforms);});
  if(selectedLanguages.size!==languages.length)chip('Watch in: '+brief([...selectedLanguages]),()=>{selectedLanguages.clear();languages.forEach(x=>selectedLanguages.add(x));persist('ottscout-languages',selectedLanguages);});
  if(selectedOriginals!==null)chip('Originally: '+brief([...selectedOriginals]),()=>{selectedOriginals=null;persist('ottscout-originals',['*']);});
  if(selectedGenres!==null)chip('Genres: '+brief([...selectedGenres]),()=>{selectedGenres=null;persist('ottscout-genres',['*']);});
  if(subscriptionOnly)chip('Included with subscription',()=>{subscriptionOnly=false;$('#subscription-only').checked=false;persist('ottscout-subscription-only',[false]);});
  if(originalOnly)chip('Original audio only',()=>{originalOnly=false;$('#original-only').checked=false;persist('ottscout-original-only',[false]);});
  $('#active-filters').replaceChildren(...chips);
}
function reportText(title, category, platform, correction) {
  const offers=(title.offers||[]).filter(o=>platform==='All listed platforms'||o.platform===platform);
  return `Title: ${title.title} (${title.year||'Year unverified'})\nCatalogue ID: ${title.id}\nPage: https://ottscout.techiwithhelmet.com/titles/${encodeURIComponent(String(title.id).replace(/^motn:/,''))}/\nIssue: ${category}\nPlatform: ${platform}\nListed original language: ${title.originalLanguage||'Unverified'}\nListed genres: ${(title.tmdb?.genres||[]).join(', ')||'Unverified'}\nListed offers:\n${offers.slice(0,8).map(o=>'- '+o.platform+' | '+(offerNames[o.type]||'Unverified')+(o.addon?' ('+o.addon+')':'')+' | audio: '+formatLanguages(o.audio)).join('\n')}\n\nWhat should be corrected?\n${correction.trim()}\n\nSource snapshot: ${liveCatalog?.updatedAt||'Sample preview'}`;
}
function openReport(title) {
  const dialog=$('#report-dialog');$('#report-title').textContent='Report: '+title.title;
  $('#report-correction').value='';$('#report-category').value='Original language';$('#report-feedback').textContent='';
  const choices=['All listed platforms',...new Set((title.offers||[]).map(o=>o.platform))];
  $('#report-platform').replaceChildren(...choices.map(name=>{const option=element('option',name);option.value=name;return option;}));
  const update=()=>{
    const text=reportText(title,$('#report-category').value,$('#report-platform').value,$('#report-correction').value);
    $('#report-preview').value=text;
    const url=new URL('https://github.com/akashIntgrators/OTTScout-Web/issues/new');url.searchParams.set('title','Incorrect details: '+title.title);url.searchParams.set('body',text);
    $('#report-github').href=url.href;
  };
  for(const id of ['report-category','report-platform','report-correction'])$('#'+id).oninput=update;
  $('#report-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('#report-preview').value);$('#report-feedback').textContent='Report copied.';}catch{$('#report-preview').focus();$('#report-preview').select();$('#report-feedback').textContent='Select and copy the report below.';}};
  $('#report-close').onclick=()=>dialog.close();update();dialog.showModal();
}
function renderOptions(kind) {
  const list = kind === 'platforms' ? platforms : languages;
  const selected = kind === 'platforms' ? selectedPlatforms : selectedLanguages;
  $('#' + kind).replaceChildren(...list.map(name => {
    const label = element('label');
    const checkbox = element('input');
    checkbox.type = 'checkbox'; checkbox.value = name; checkbox.checked = selected.has(name);
    checkbox.setAttribute('aria-label', name);
    checkbox.onchange = () => {
      checkbox.checked ? selected.add(name) : selected.delete(name);
      persist('ottscout-' + kind, selected);
      updateSelections();
      visibleLimit = PAGE_SIZE;
      render();
    };
    label.append(checkbox, element('span',name));
    if (kind === 'platforms' && liveCatalog?.missingPlatforms.includes(name)) label.append(element('small','Not covered'));
    return label;
  }));
}
function updateSelections() {
  $('#platform-summary small').textContent = selectedPlatforms.size === platforms.length ? 'All' : `${selectedPlatforms.size}`;
  $('#language-summary small').textContent = selectedLanguages.size === languages.length ? 'All' : `${selectedLanguages.size}`;
  $('#selection-status').textContent = `${selectedPlatforms.size === platforms.length ? 'All platforms' : `${selectedPlatforms.size} platform${selectedPlatforms.size === 1 ? '' : 's'}`} · ${selectedLanguages.size === languages.length ? 'All six audio languages' : `${selectedLanguages.size} language${selectedLanguages.size === 1 ? '' : 's'}`}`;
  for (const kind of ['platforms','languages']) {
    const selected = kind === 'platforms' ? selectedPlatforms : selectedLanguages;
    document.querySelectorAll(`#${kind} input`).forEach(input => { input.checked = selected.has(input.value); });
  }
}
function setView(next) {
  view = next; visibleLimit = PAGE_SIZE;
  document.querySelectorAll('.view-tabs button').forEach(button => {
    button.classList.toggle('active',button.dataset.view === view);
    if (button.dataset.view === view) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  render();
}
function emptyState() {
  const node = element('div',undefined,'empty');
  let heading = 'No matches this time';
  let message = 'Try another search or select more platforms and languages.';
  if (!selectedPlatforms.size) message = 'Select at least one platform to see titles.';
  else if (!selectedLanguages.size) message = 'Select at least one audio language to see titles.';
  else if (selectedOriginals!==null && !selectedOriginals.size) message='Select at least one original language, or choose All.';
  else if (selectedGenres!==null && !selectedGenres.size) message='Select at least one genre, or choose All.';
  else if (subscriptionOnly) message='No base-subscription offers match these filters. Try more platforms or turn off Included with subscription.';
  else if (liveCatalog && [...selectedPlatforms].every(name => liveCatalog.missingPlatforms.includes(name))) message = 'Our current data provider does not cover the selected platforms. Choose another platform to explore available titles.';
  else if (view === 'watchlist') { heading = 'A good watch is worth saving'; message = 'Tap + on a title to add it to your watchlist. Your current filters also apply here.'; }
  else if (view === 'weekly') {
    heading = 'No additions match your filters';
    message = liveCatalog?.recentHistoryComplete ? 'No provider-reported additions match this search in the last seven days. You can still explore the full catalog.' : 'We’re filling in the last seven days of streaming additions. Explore the catalog while that history loads.';
  }
  node.append(element('h3',heading),element('p',message));
  const action = element('button',view === 'discover' ? 'Reset filters' : 'Explore all titles');
  action.type='button'; action.onclick=()=>{ if(view==='discover') resetFilters(); else { $('#search').value=''; setView('discover'); } };
  node.append(action);
  return node;
}
function render() {
  activeFilterChips();
  const query = $('#search').value.toLocaleLowerCase().trim();
  const found = titles.filter(title => matchingGenres(title) && matchingOffers(title).length
    && title.title.toLocaleLowerCase().includes(query)
    && (view === 'watchlist' || !dismissed.has(title.id))
    && (contentType === 'all' || title.type === contentType)
    && (view !== 'watchlist' || saved.has(title.id))
    && (view !== 'weekly' || weeklyTitle(title)));
  found.sort((a,b) => view === 'weekly' ? (b.weeklyUpdatedAt || 0) - (a.weeklyUpdatedAt || 0) || a.title.localeCompare(b.title)
    : (b.year || 0) - (a.year || 0) || a.title.localeCompare(b.title));
  $('#count').textContent = saved.size;
  $('#restore-hidden').hidden = dismissed.size === 0;
  $('#restore-hidden').textContent = `Restore hidden titles (${dismissed.size})`;
  $('#weekly-count').textContent = titles.filter(title => matchingGenres(title) && !dismissed.has(title.id) && weeklyTitle(title) && matchingOffers(title,true).length).length;
  $('#heading').textContent = {discover:'Find your next favourite',weekly:'Fresh on your platforms',watchlist:'Saved for a good night in'}[view];
  $('#view-eyebrow').textContent = {discover:'A LITTLE DISCOVERY',weekly:'THE LAST SEVEN DAYS',watchlist:'YOUR PERSONAL PICKS'}[view];
  $('#description').textContent = view === 'weekly' ? liveCatalog ? 'New streaming additions reported by our provider. Dates are not confirmed premiere dates.' : 'Illustrative weekly picks from the sample catalog.'
    : view === 'watchlist' ? 'Your watchlist is saved on this browser. Filters apply here too.'
      : liveCatalog ? 'Movies and series across your selected platforms. Audio is listed per platform.' : 'Explore the sample catalog while live data is unavailable.';
  $('#result-count').textContent = `${found.length} ${found.length === 1 ? 'title' : 'titles'}`;
  const content = [];
  const adAfter = window.matchMedia('(max-width:650px)').matches ? 6 : 12;
  found.slice(0,visibleLimit).forEach((title,index) => { content.push(cardFor(title)); if (index === adAfter - 1 && found.length > adAfter) content.push(adSlot()); });
  $('#catalog').replaceChildren(...(content.length ? content : [emptyState()]));
  $('#load-more').hidden = found.length <= visibleLimit;
  $('#load-more').textContent = `Show ${Math.min(PAGE_SIZE, Math.max(0,found.length-visibleLimit))} more titles`;
}
function resetFilters() {
  selectedPlatforms.clear(); platforms.forEach(name=>selectedPlatforms.add(name));
  selectedLanguages.clear(); languages.forEach(name=>selectedLanguages.add(name));
  persist('ottscout-platforms',selectedPlatforms); persist('ottscout-languages',selectedLanguages);
  selectedOriginals=null;persist('ottscout-originals',['*']);renderOriginals();
  subscriptionOnly=false;$('#subscription-only').checked=false;persist('ottscout-subscription-only',[false]);
  selectedGenres=null; persist('ottscout-genres',['*']);renderGenres();
  originalOnly=false; $('#original-only').checked=false; persist('ottscout-original-only',[false]);
  $('#search').value=''; contentType='all'; visibleLimit=PAGE_SIZE;
  document.querySelectorAll('#type button').forEach(button=>button.setAttribute('aria-pressed',button.dataset.type==='all'));
  updateSelections(); render();
}
for (const kind of ['platforms','languages']) renderOptions(kind);
updateSelections();
renderGenres();renderOriginals();
$('#original-all').onclick=()=>{selectedOriginals=null;persist('ottscout-originals',['*']);visibleLimit=PAGE_SIZE;renderOriginals();render();};
$('#original-clear').onclick=()=>{selectedOriginals=new Set();persist('ottscout-originals',selectedOriginals);visibleLimit=PAGE_SIZE;renderOriginals();render();};
$('#subscription-only').checked=subscriptionOnly;
$('#subscription-only').onchange=()=>{subscriptionOnly=$('#subscription-only').checked;persist('ottscout-subscription-only',[subscriptionOnly]);visibleLimit=PAGE_SIZE;render();};
$('#genre-all').onclick=()=>{selectedGenres=null;persist('ottscout-genres',['*']);visibleLimit=PAGE_SIZE;renderGenres();render();};
$('#genre-clear').onclick=()=>{selectedGenres=new Set();persist('ottscout-genres',selectedGenres);visibleLimit=PAGE_SIZE;renderGenres();render();};
$('#original-only').checked=originalOnly;
$('#original-only').onchange=()=>{originalOnly=$('#original-only').checked;persist('ottscout-original-only',[originalOnly]);visibleLimit=PAGE_SIZE;render();};
$('#restore-hidden').onclick=()=>{dismissed.clear();persist('ottscout-dismissed',dismissed);render();};
$('#search').oninput=()=>{visibleLimit=PAGE_SIZE;if($('#search').value.trim() && view==='weekly')setView('discover');else render();};
$('#reset-filters').onclick=resetFilters;
$('#load-more').onclick=()=>{visibleLimit+=PAGE_SIZE;render();};
for (const attribute of ['select-all','clear']) document.querySelectorAll(`[data-${attribute}]`).forEach(button=>{
  button.onclick=()=>{
    const kind=button.dataset[attribute==='select-all'?'selectAll':'clear'];
    const selected=kind==='platforms'?selectedPlatforms:selectedLanguages;
    const options=kind==='platforms'?platforms:languages;
    selected.clear(); if(attribute==='select-all') options.forEach(name=>selected.add(name));
    persist('ottscout-'+kind,selected);visibleLimit=PAGE_SIZE;updateSelections();render();
  };
});
document.querySelectorAll('#type button').forEach(button=>button.onclick=()=>{
  contentType=button.dataset.type;visibleLimit=PAGE_SIZE;
  document.querySelectorAll('#type button').forEach(option=>option.setAttribute('aria-pressed',option===button));render();
});
document.querySelectorAll('.view-tabs button').forEach(button=>button.onclick=()=>setView(button.dataset.view));
const menus=[$('#platform-menu'),$('#language-menu'),$('#original-menu'),$('#genre-menu')];
menus.forEach(menu=>menu.addEventListener('toggle',()=>{if(menu.open)menus.filter(other=>other!==menu).forEach(other=>{other.open=false;});}));
document.addEventListener('click',event=>menus.forEach(menu=>{if(!menu.contains(event.target))menu.open=false;}));
document.addEventListener('keydown',event=>{
  if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){event.preventDefault();$('#search').focus();}
  if($('#report-dialog').open)return;
  if(event.key==='Escape'){const open=menus.find(menu=>menu.open);if(open){open.open=false;open.querySelector('summary').focus();}}
});
render();

async function loadCatalog() {
  try {
    const response=await fetch('data/catalog.json',{cache:'no-store'});
    if(!response.ok)throw new Error('No live snapshot');
    const data=await response.json();
    if(data.schemaVersion!==1||data.mode!=='live'||!Array.isArray(data.titles)||!Number.isFinite(Date.parse(data.updatedAt))||!Array.isArray(data.missingPlatforms))throw new Error('Invalid catalog');
    for(const title of data.titles){
      if(title.tmdb && (!Array.isArray(title.tmdb.genres)||!title.tmdb.genres.every(g=>typeof g==='string')))throw new Error('Invalid genres');
      if(title.originalLanguage != null && typeof title.originalLanguage !== 'string')throw new Error('Invalid original language');
      if(typeof title.id!=='string'||!title.id.startsWith('motn:')||typeof title.title!=='string'||!['Movie','Series'].includes(title.type)||!Array.isArray(title.offers)||!Array.isArray(title.weeklyPlatforms)||!Number.isFinite(title.lastCheckedAt))throw new Error('Invalid title');
      for(const offer of title.offers)if(!platforms.includes(offer.platform)||!Array.isArray(offer.audio)||!offer.audio.every(x=>typeof x==='string')||!Array.isArray(offer.subtitles)||!offer.subtitles.every(x=>typeof x==='string'))throw new Error('Invalid offer');
    }
    liveCatalog=data;titles=data.titles;
    renderGenres();renderOriginals();
    const enrichment=data.tmdbEnrichment;
    $('#metadata-status').textContent=enrichment ? `Original language known for ${titles.filter(t=>t.originalLanguage).length} of ${titles.length} titles. Genre coverage is still expanding${enrichment.status==='error'?' · Metadata update delayed':''}. Unmatched details remain Unverified.` : 'Language and genre details are still being verified. Unmatched details remain Unverified.';
    const stale=Date.now()-Date.parse(data.updatedAt)>12*60*60*1000;
    $('#catalog-status').textContent=`${stale?'Updates delayed · ':''}India catalog · Updated ${new Date(data.updatedAt).toLocaleString('en-IN',{day:'numeric',month:'short',hour:'numeric',minute:'2-digit',timeZone:'Asia/Kolkata'})} IST · ${data.coverage?.length || 0} platforms covered`;
    $('#coverage-note').textContent=data.missingPlatforms.length?`Coverage note: ${data.missingPlatforms.join(' and ')} are not available from our current data provider. Search covers our imported catalog.`:'Availability is reported by our data provider. Search covers our imported catalog.';
    if(data.catalogBackfill && !data.catalogBackfill.complete) $('#coverage-note').textContent += ' Older titles are being added gradually.';
    renderOptions('platforms');updateSelections();render();
  } catch {
    $('#catalog-status').textContent='Sample preview · Live catalog unavailable. Titles and streaming details below are illustrative.';
    $('#coverage-note').textContent='Sample data is shown until the live catalog is available.';
  }
}
loadCatalog();
