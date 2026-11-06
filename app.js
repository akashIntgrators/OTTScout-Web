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
let weeklyKind = 'all';
let audioDescriptionOnly = readList('ottscout-audio-description')?.[0] === true;
let shortcutsEnabled = readList('ottscout-shortcuts')?.[0] === true;
let announcementTimer;
let visibleLimit = PAGE_SIZE;
let selectedSearchId=null;
let suggestions=[];
let activeSuggestion=-1;
const weeklyOpen = new Map();
const weeklyLimits = new Map();
const providerLogos = {'Netflix':'netflix','Prime Video':'prime','JioHotstar':'jiohotstar','ZEE5':'zee5','SonyLIV':'sonyliv'};
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
let accountToggleInProgress=false;
let accountWatchlistState=null;
const legacyExcluded = readList('ottscout-excluded-platforms') || [];
const selectedPlatforms = new Set((readList('ottscout-platforms') || platforms.filter(name => !legacyExcluded.includes(name))).filter(name => platforms.includes(name)));
const selectedLanguages = new Set((readList('ottscout-languages') || languages).filter(name => languages.includes(name)));

function watchlistSaveReason() {
  const state=accountWatchlistState;
  if(!state)return '';
  if(state.status==='deletion-pending')return 'Saving is paused because account deletion has started. Open Account to finish deletion.';
  if(state.status==='read-only')return state.error || 'Saved titles are read-only in this tab. Open Account to retry sync.';
  if(state.status==='storage-error'||state.canSave===false)return 'Saving is paused to protect your device data. Open Sign in or Account for details.';
  if(state.uid&&!liveCatalog)return 'Sample titles cannot be synced. Saving will be available when the live catalogue loads.';
  return '';
}
function setSaveAvailability(button) {
  const reason=watchlistSaveReason();
  button.disabled=Boolean(reason);button.setAttribute('aria-disabled',String(Boolean(reason)));
  if(reason){button.setAttribute('aria-describedby','watchlist-save-status');button.title=reason;}
  else {button.removeAttribute('aria-describedby');button.removeAttribute('title');}
}
function updateSaveAvailability() {
  const reason=watchlistSaveReason(),status=$('#watchlist-save-status');
  if(status){status.hidden=!reason;status.textContent=reason;}
  document.querySelectorAll('#catalog .save').forEach(setSaveAvailability);
}
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function secureURL(value) {
  try { const url = new URL(value); return url.protocol === 'https:' ? url.href : null; } catch { return null; }
}
function netflixTitleId(value) {
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:' || !['netflix.com','www.netflix.com'].includes(url.hostname) || url.username || url.password || url.port) return null;
    return url.pathname.match(/^\/(?:[a-z]{2}(?:-[a-z]{2})?\/)?(?:title|watch)\/([0-9]+)\/?$/)?.[1] || null;
  } catch { return null; }
}
function descriptionReport(offer, now = Date.now()/1000) {
  const report=offer.audioDescription;
  if (offer.platform!=='Netflix' || !report || report.status!=='reported' || report.indiaPlaybackVerified!==false
      || !Number.isFinite(report.checkedAt) || report.checkedAt>now || report.checkedAt<now-30*DAY
      || !Number.isFinite(report.expiresAt) || report.expiresAt<now || report.expiresAt>report.checkedAt+30*DAY
      || !Array.isArray(report.languages) || !report.languages.length || !report.languages.every(l=>languages.includes(l))
      || !netflixTitleId(report.sourceURL) || netflixTitleId(report.sourceURL)!==netflixTitleId(offer.link)) return null;
  return report;
}
function descriptionLanguages(offer, title) {
  return (descriptionReport(offer)?.languages || []).filter(l=>selectedLanguages.has(l) && (!originalOnly || l===title.originalLanguage));
}
function titleDomId(id) { return 'title-'+String(id).replace(/[^a-zA-Z0-9_-]/g,'-'); }
function visibleCards() {
  return [...document.querySelectorAll('#catalog .card')].filter(card=>{
    for(let node=card.parentElement;node;node=node.parentElement)if(node.tagName==='DETAILS'&&!node.open)return false;
    return true;
  });
}
function nextCardId(id) {
  const cards=visibleCards();
  const index=cards.findIndex(card=>card.dataset.titleId===String(id));
  return (cards[index+1] || cards[index-1])?.dataset.titleId;
}
function focusTitle(id) {
  const target=id && document.getElementById(titleDomId(id))?.querySelector('a');
  (target || $('#heading')).focus();
}
function announceResults(message) {
  clearTimeout(announcementTimer);
  announcementTimer=setTimeout(()=>{ $('#results-status').textContent=message; },250);
}
function weeklyTitle(title) {
  if (!liveCatalog) return Boolean(title.weekly);
  if (!title.weekly || !title.weeklyPlatforms.length) return false;
  if (!Number.isFinite(title.weeklyUpdatedAt)) return false;
  const now = Date.now() / 1000;
  return title.weeklyUpdatedAt <= now && title.weeklyUpdatedAt >= now - 7 * DAY;
}
function weeklyOfferDate(title, offer, now = Date.now() / 1000) {
  const added = Array.isArray(title.weeklyEvents)
    ? title.weeklyEvents.find(event => event.platform === offer.platform)?.addedAt
    : title.weeklyPlatforms?.includes(offer.platform) ? title.weeklyUpdatedAt : null;
  if (!Number.isFinite(added) || added < now - 7 * DAY || added > now) return null;
  // A new offer on a platform does not make every older offer new.
  if (Number.isFinite(offer.availableSince) && offer.availableSince > 0) {
    return offer.availableSince >= now - 7 * DAY && offer.availableSince <= now ? offer.availableSince : null;
  }
  return added;
}
function weeklyAdditionTime(title, now = Date.now()/1000) {
  const dates=matchingOffers(title,false).map(offer=>weeklyOfferDate(title,offer,now)).filter(Number.isFinite);
  return dates.length?Math.max(...dates):null;
}
function groupWeeklyTitles(items, now = Date.now()/1000) {
  const groups=new Map();
  for(const title of items){
    const timestamp=weeklyAdditionTime(title,now);
    const key=timestamp===null?'unverified':new Date((timestamp+19800)*1000).toISOString().slice(0,10);
    if(!groups.has(key))groups.set(key,{key,label:timestamp===null?'Addition date unverified':new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',weekday:'long',day:'numeric',month:'long'}).format(timestamp*1000),timestamp,titles:[]});
    const group=groups.get(key);group.titles.push(title);
    if(timestamp!==null)group.timestamp=Math.max(group.timestamp,timestamp);
  }
  return [...groups.values()].sort((a,b)=>a.key==='unverified'?1:b.key==='unverified'?-1:b.key.localeCompare(a.key)).map(group=>{
    group.titles.sort((a,b)=>(weeklyAdditionTime(b,now)||0)-(weeklyAdditionTime(a,now)||0)||a.title.localeCompare(b.title));
    return group;
  });
}
function weeklyContextGroups(now = Date.now()/1000) {
  if(!liveCatalog)return [];
  const available=new Set(availablePlatforms());
  const groups=new Map();
  for(const title of titles){
    if(dismissed.has(title.id)||!weeklyTitle(title))continue;
    const offers=title.offers.filter(offer=>available.has(offer.platform)).map(offer=>({offer,timestamp:weeklyOfferDate(title,offer,now)})).filter(item=>item.timestamp!==null);
    if(!offers.length)continue;
    const timestamp=Math.max(...offers.map(item=>item.timestamp));
    const key=new Date((timestamp+19800)*1000).toISOString().slice(0,10);
    if(!groups.has(key))groups.set(key,{key,label:new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',weekday:'long',day:'numeric',month:'long'}).format(timestamp*1000),timestamp,ids:new Set(),platforms:new Set()});
    const group=groups.get(key);group.ids.add(title.id);group.timestamp=Math.max(group.timestamp,timestamp);
    offers.filter(item=>new Date((item.timestamp+19800)*1000).toISOString().slice(0,10)===key).forEach(item=>group.platforms.add(item.offer.platform));
  }
  return [...groups.values()].sort((a,b)=>b.key.localeCompare(a.key)).map(group=>({key:group.key,label:group.label,timestamp:group.timestamp,count:group.ids.size,platforms:platforms.filter(name=>group.platforms.has(name))}));
}
function weeklyDateGroups(found) {
  const groups=new Map(weeklyContextGroups().map(group=>[group.key,{...group,titles:[]}]));
  for(const group of groupWeeklyTitles(found)){
    if(groups.has(group.key))groups.get(group.key).titles=group.titles;
    else groups.set(group.key,{...group,count:group.titles.length,platforms:[]});
  }
  return [...groups.values()].sort((a,b)=>a.key==='unverified'?1:b.key==='unverified'?-1:b.key.localeCompare(a.key));
}
function expiringOffers(title, now = Date.now()/1000) {
  return matchingOffers(title,false).filter(offer=>Number.isFinite(offer.expiresOn)&&offer.expiresOn>now&&offer.expiresOn<=now+30*DAY&&(!Number.isFinite(offer.availableSince)||offer.availableSince<=now)).sort((a,b)=>a.expiresOn-b.expiresOn);
}
function earliestExpiry(title, now = Date.now()/1000) {
  return expiringOffers(title,now)[0]?.expiresOn??null;
}
function randomTitle(items, rng = Math.random) {
  if(!items.length)return null;
  const value=rng();
  return Number.isFinite(value)?items[Math.min(items.length-1,Math.max(0,Math.floor(value*items.length)))]:null;
}
function futureDate(timestamp) {
  return new Intl.DateTimeFormat('en-IN',{timeZone:'Asia/Kolkata',day:'numeric',month:'short',year:'numeric'}).format(timestamp*1000);
}
function olderMovie(title, now = Date.now()) {
  const year = Number(new Intl.DateTimeFormat('en', {year:'numeric', timeZone:'Asia/Kolkata'}).format(new Date(now)));
  return title.type === 'Movie' && Number.isInteger(title.year) && title.year > 1800 && title.year < year;
}
function weeklyKindMatches(title) {
  return weeklyKind === 'all' || (weeklyKind === 'older' ? olderMovie(title) : !olderMovie(title));
}
function additionLabel(title) {
  return olderMovie(title) ? `Older movie · ${title.year}` : title.type === 'Series' ? 'Series addition' : 'Movie addition';
}
function checkedDate(timestamp) {
  return Number.isFinite(timestamp) && timestamp > 0 && timestamp <= Date.now()/1000
    ? new Date(timestamp * 1000).toLocaleDateString('en-IN', {day:'numeric',month:'short',year:'numeric',timeZone:'Asia/Kolkata'}) : 'Unverified';
}
function metadataExplanation(title) {
  if (title.tmdbMatchStatus === 'unmatched') return 'No confident TMDB match. Original language and genres are not guessed from available audio.';
  if (!title.tmdb) return 'TMDB lookup pending. A provider-reported original language may still be shown.';
  return `Matched by ${({'provider-id':'provider TMDB ID','imdb-id':'IMDb ID','exact-title-year':'unique exact title and year'})[title.tmdb.matchMethod] || 'TMDB metadata'}. Metadata checked ${checkedDate(title.tmdb.checkedAt)}. Missing source details remain Unverified.`;
}
function originalBucket(title) {
  return title.originalLanguage ? languages.includes(title.originalLanguage) ? title.originalLanguage : 'Other languages' : 'Unverified';
}
function matchingOriginal(title) {
  return selectedOriginals===null || selectedOriginals.has(originalBucket(title));
}
function matchesViewingAudio(offer,title) {
  if(audioDescriptionOnly) return descriptionLanguages(offer,title).length>0;
  if(!offer.audio.length) return !originalOnly && languages.every(l=>selectedLanguages.has(l));
  return offer.audio.some(language=>selectedLanguages.has(language) && (!originalOnly || language===title.originalLanguage));
}
function matchingOffers(title, weeklyOnly = view === 'weekly') {
  const offers = title.offers || [{platform:title.platform, audio:title.audio, subtitles:[], type:'sample'}];
  const priority = {subscription:0, free:1, addon:2, rent:3, buy:4, sample:5};
  return offers.filter(offer => matchingOriginal(title) && selectedPlatforms.has(offer.platform)
    && (!subscriptionOnly || (offer.type==='subscription' && !offer.addon))
    && matchesViewingAudio(offer,title)
    && (!weeklyOnly || !liveCatalog || weeklyOfferDate(title, offer) !== null))
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
function rentalLabel(offers) {
  if (!offers.some(o=>o.type==='rent')) return '';
  return offers.every(o=>o.type==='rent') ? 'Rent only' : 'Rent option';
}
function providerLink(offer, titleLabel='') {
  const href = secureURL(offer.link);
  const link = element(href ? 'a' : 'div', offer.platform + (href ? ' ↗' : ''), 'provider');
  if (href) { link.href = href; link.rel = 'noopener noreferrer'; link.setAttribute('aria-label', `${offer.platform}${titleLabel?' — watch '+titleLabel:''}`); }
  return link;
}
function primaryPlatform(offer,titleLabel) {
  const link=providerLink(offer,titleLabel);link.className='primary-platform';
  const logo=providerLogos[offer.platform];
  if(logo){const image=element('img');image.src='/assets/platform-'+logo+'.svg';image.alt='';image.width=28;image.height=28;link.replaceChildren(image,element('span',offer.platform));}
  return link;
}
function primaryOfferLabel(offer) {
  if(offer.addon)return 'Add-on · '+offer.addon;
  return offerNames[offer.type]||'Offer unverified';
}
function offerBody(offer, includeSubtitles = true, titleLabel='') {
  const node = element('div', undefined, 'offer');
  node.append(providerLink(offer,titleLabel), element('div', `${offerNames[offer.type] || 'Offer unverified'}${offer.addon ? ' · ' + offer.addon : ''}`, 'offer-type'));
  const audio = element('div', undefined, 'audio');
  audio.append(element('span','Audio: '), document.createTextNode(formatLanguages(offer.audio)));
  node.append(audio);
  const report=descriptionReport(offer);
  if (report) node.append(element('p','Description audio: '+formatLanguages(report.languages)+' · India playback unverified','ad-report'));
  const now=Date.now()/1000;
  if(Number.isFinite(offer.expiresOn)&&offer.expiresOn>now&&offer.expiresOn<=now+30*DAY)node.append(element('p','Provider-reported end: '+futureDate(offer.expiresOn)+'. Confirm on the platform.','offer-expiry'));
  return node;
}
function cardFor(title) {
  const offers = view==='leaving'?expiringOffers(title):matchingOffers(title);
  const watchOffers = view==='leaving'?matchingOffers(title,false):offers;
  const card = element('article', undefined, 'card');
  card.dataset.titleId=String(title.id);card.setAttribute('aria-labelledby',titleDomId(title.id));
  const poster = element(liveCatalog?'a':'div', undefined, 'poster');
  if(liveCatalog){poster.href='/titles/'+encodeURIComponent(title.id.replace(/^motn:/,''))+'/';poster.setAttribute('aria-label','Full details for '+title.title);}
  poster.style.setProperty('--poster-color', title.color || '#345347');
  const fallback = element('strong', title.title, 'poster-title');
  fallback.setAttribute('aria-hidden','true');
  const imageURL = liveCatalog ? secureURL(title.poster) : `assets/${title.artwork}.png`;
  fallback.hidden = Boolean(imageURL && liveCatalog);
  if (imageURL) {
    const image = element('img');
    image.src = imageURL; image.alt = ''; image.loading = 'lazy'; image.width = 480; image.height = 720;
    image.onerror = () => { image.remove(); fallback.hidden = false; };
    poster.append(image);
  }
  poster.append(fallback);
  if(!liveCatalog)poster.append(element('span',title.type+' · Sample','badge'));
  const save = element('button', saved.has(title.id) ? '✓' : '+', 'save'); // taste-skill-ignore: checked state, paired with aria-pressed.
  save.type = 'button';
  save.setAttribute('aria-label', `Save to watchlist: ${title.title}`);
  save.setAttribute('aria-pressed', saved.has(title.id));
  setSaveAvailability(save);
  save.onclick = () => {
    if(save.disabled)return;
    const next=nextCardId(title.id);
    if (window.OTTScoutAccount) {
      accountToggleInProgress=true;
      let changed;try { changed=window.OTTScoutAccount.toggle(title.id); } finally { accountToggleInProgress=false; }
      if (!changed) { announceResults('This title could not be saved. Open Account for details, or choose a live catalogue title.'); return; }
    } else {
      saved.has(title.id) ? saved.delete(title.id) : saved.add(title.id);
      persist('ottscout-watchlist', saved);
    }
    // Preserve focus when a saved card remains visible.
    if (view === 'watchlist') { render();focusTitle(next); }
    else {
      save.textContent = saved.has(title.id) ? '✓' : '+'; // taste-skill-ignore: checked state, paired with aria-pressed.
      save.setAttribute('aria-pressed', saved.has(title.id));
      $('#count').textContent = saved.size;
    }
    announceResults(`${title.title} ${saved.has(title.id)?'added to':'removed from'} your watchlist. ${saved.size} saved ${saved.size===1?'title':'titles'}.`);
  };
  const body = element('div', undefined, 'card-body');
  const audio = [...new Set(offers.flatMap(offer => audioDescriptionOnly ? descriptionLanguages(offer,title) : offer.audio))];
  const heading = element(view==='weekly'?'h3':'h2', undefined, 'card-title');
  heading.id=titleDomId(title.id);
  const name = element(liveCatalog ? 'a' : 'span', title.title);
  if (liveCatalog) name.href = '/titles/' + encodeURIComponent(title.id.replace(/^motn:/, '')) + '/';
  const audioLabel=!audio.length?'Audio languages unverified':(audioDescriptionOnly?'Description audio: ':'Audio: ')+formatLanguages(audio);
  heading.append(name);
  const rental=rentalLabel(watchOffers);
  if (rental) heading.append(document.createTextNode(' '),element('span',rental,'rental-label'));
  body.append(heading);
  body.append(element('p',(title.originalLanguage?formatLanguages([title.originalLanguage])+' original':'Original language unverified')+' · '+(Number.isInteger(title.year)?title.year:'Year unverified')+' · '+title.type,'card-meta'));
  const genres=(liveCatalog?title.tmdb?.genres:title.genres)||[];
  if(genres.length){const list=element('div',undefined,'card-genres');genres.filter(genre=>typeof genre==='string'&&genre!=='Unverified').slice(0,3).forEach(genre=>list.append(element('span',genre,'genre-chip')));if(list.children.length)body.append(list);}
  if(typeof title.overview==='string'&&title.overview.trim())body.append(element('p',title.overview.trim(),'card-overview'));
  if(offers.length){const primary=element('div',undefined,'primary-offer');primary.append(primaryPlatform(offers[0],title.title),element('span',primaryOfferLabel(offers[0]),'primary-offer-label'));body.append(primary);}
  body.append(element('p',audioLabel,'card-audio card-languages'));
  const reported=[...new Set(offers.flatMap(offer=>descriptionReport(offer)?.languages || []))];
  if (liveCatalog && reported.length) body.append(element('p','Audio description reported: '+formatLanguages(reported),'ad-report'));
  if(view==='leaving'&&offers.length)body.append(element('p','Provider-reported end: '+futureDate(offers[0].expiresOn)+' on '+offers[0].platform,'expiry-label'));
  const options = element('details', undefined, 'watch-options');
  const summary=element('summary','Where to watch');summary.append(element('span',' '+title.title,'sr-only'));options.append(summary);
  options.append(element('div', 'Original language: ' + formatLanguages(title.originalLanguage ? [title.originalLanguage] : []), 'original-language'));
  if (liveCatalog && view === 'weekly') {
    const added=weeklyAdditionTime(title);
    options.append(element('p', `${additionLabel(title)} · Added ${checkedDate(added)}`, 'addition-label'));
  }
  watchOffers.forEach(offer => options.append(offerBody(offer,false,title.title)));
  if (liveCatalog) { const details=element('a','Full title details','provider');details.href='/titles/'+encodeURIComponent(title.id.replace(/^motn:/,''))+'/';options.append(details); }
  const report = element('button','Report incorrect details','report-button');
  report.type='button';report.setAttribute('aria-label','Report incorrect details for '+title.title); report.onclick=()=>openReport(title); options.append(report);
  if (view !== 'watchlist') {
    const dismiss = element('button', 'Hide title', 'dismiss-title');
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', 'Hide title: ' + title.title);
    dismiss.onclick = () => { const next=nextCardId(title.id);dismissed.add(title.id); persist('ottscout-dismissed', dismissed); render();focusTitle(next); };
    options.append(dismiss);
  }
  if (liveCatalog) options.append(element('p', `Availability checked ${checkedDate(title.lastCheckedAt)}`, 'checked-date'));
  body.append(options);
  card.append(poster, body, save);
  return card;
}
function adSlot() {
  const slot = element('aside', undefined, 'ad-slot ad-infeed');
  slot.setAttribute('aria-label','Reserved in-feed advertisement space');
  slot.append(element('span','Advertisement','ad-label'));
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
  function chip(label,reset){
    const index=chips.length;
    const button=element('button',label+' ×','filter-chip');
    button.type='button';button.setAttribute('aria-label','Remove filter: '+label);
    button.onclick=()=>{
      reset();visibleLimit=PAGE_SIZE;updateSelections();renderGenres();renderOriginals();render();
      const remaining=$('#active-filters').querySelectorAll('button');
      const fallback=$('#filters-panel')?.open?$('#reset-filters'):$('#filters-summary');
      (remaining[Math.min(index,remaining.length-1)]||fallback||$('#reset-filters')).focus();
    };
    chips.push(button);
  }
  const brief=items=>items.length ? items.slice(0,2).join(', ')+(items.length>2?` +${items.length-2}`:''):'None';
  if(selectedPlatforms.size!==availablePlatforms().length)chip('Platforms: '+brief([...selectedPlatforms]),()=>{selectedPlatforms.clear();availablePlatforms().forEach(x=>selectedPlatforms.add(x));persist('ottscout-platforms',selectedPlatforms);});
  if(selectedLanguages.size!==languages.length)chip('Watch in: '+brief([...selectedLanguages]),()=>{selectedLanguages.clear();languages.forEach(x=>selectedLanguages.add(x));persist('ottscout-languages',selectedLanguages);});
  if(selectedOriginals!==null)chip('Originally: '+brief([...selectedOriginals]),()=>{selectedOriginals=null;persist('ottscout-originals',['*']);});
  if(selectedGenres!==null)chip('Genres: '+brief([...selectedGenres]),()=>{selectedGenres=null;persist('ottscout-genres',['*']);});
  if(view==='weekly'&&weeklyKind!=='all')chip('Additions: '+(weeklyKind==='older'?'Older movies':'Other additions'),()=>{weeklyKind='all';document.querySelectorAll('#weekly-kind button').forEach(button=>button.setAttribute('aria-pressed',button.dataset.kind==='all'));});
  if(subscriptionOnly)chip('Included with subscription',()=>{subscriptionOnly=false;$('#subscription-only').checked=false;persist('ottscout-subscription-only',[false]);});
  if(originalOnly)chip('Original audio only',()=>{originalOnly=false;$('#original-only').checked=false;persist('ottscout-original-only',[false]);});
  if(audioDescriptionOnly)chip('Audio description reported',()=>{audioDescriptionOnly=false;$('#audio-description-only').checked=false;persist('ottscout-audio-description',[false]);});
  $('#active-filters').replaceChildren(...chips);
  const count=$('#filter-count');
  if(count){count.textContent=chips.length?`${chips.length} active`:'All selected';count.hidden=false;}
}
function reportText(title, category, platform, correction) {
  const offers=(title.offers||[]).filter(o=>platform==='All listed platforms'||o.platform===platform);
  return `Title: ${title.title} (${title.year||'Year unverified'})\nCatalogue ID: ${title.id}\nPage: https://ottscout.techiwithhelmet.com/titles/${encodeURIComponent(String(title.id).replace(/^motn:/,''))}/\nIssue: ${category}\nPlatform: ${platform}\nListed original language: ${title.originalLanguage||'Unverified'}\nListed genres: ${(title.tmdb?.genres||[]).join(', ')||'Unverified'}\nListed offers:\n${offers.slice(0,8).map(o=>'- '+o.platform+' | '+(offerNames[o.type]||'Unverified')+(o.addon?' ('+o.addon+')':'')+' | audio: '+formatLanguages(o.audio)+' | description reported: '+formatLanguages(descriptionReport(o)?.languages||[])).join('\n')}\n\nWhat should be corrected?\n${correction.trim()}\n\nSource snapshot: ${liveCatalog?.updatedAt||'Sample preview'}`;
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
  $('#report-close').onclick=()=>dialog.close();update();dialog.showModal();$('#report-category').focus();
}
function availablePlatforms() {
  if (!liveCatalog) return platforms;
  const present=new Set(titles.flatMap(t=>(t.offers || []).map(o=>o.platform)));
  return platforms.filter(p=>!liveCatalog.missingPlatforms.includes(p) && present.has(p));
}
function renderOptions(kind) {
  const list = kind === 'platforms' ? availablePlatforms() : languages;
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
    return label;
  }));
}
function updateSelections() {
  $('#platform-summary small').textContent = selectedPlatforms.size === availablePlatforms().length ? 'All' : `${selectedPlatforms.size}`;
  $('#language-summary small').textContent = selectedLanguages.size === languages.length ? 'All' : `${selectedLanguages.size}`;
  $('#selection-status').textContent = `${selectedPlatforms.size === availablePlatforms().length ? 'All platforms' : `${selectedPlatforms.size} platform${selectedPlatforms.size === 1 ? '' : 's'}`} · ${selectedLanguages.size === languages.length ? 'All six audio languages' : `${selectedLanguages.size} language${selectedLanguages.size === 1 ? '' : 's'}`}`;
  for (const kind of ['platforms','languages']) {
    const selected = kind === 'platforms' ? selectedPlatforms : selectedLanguages;
    document.querySelectorAll(`#${kind} input`).forEach(input => { input.checked = selected.has(input.value); });
  }
  syncQuickFilters();
}
function syncQuickFilters() {
  const available=new Set(availablePlatforms());
  document.querySelectorAll('.quick-platform').forEach(button=>{const active=available.has(button.dataset.platform);button.hidden=!active;button.disabled=!active;button.setAttribute('aria-pressed',active&&selectedPlatforms.has(button.dataset.platform));});
  document.querySelectorAll('.quick-language').forEach(button=>button.setAttribute('aria-pressed',selectedLanguages.has(button.dataset.language)));
  for(const [kind,options,selected] of [['platform',[...available],selectedPlatforms],['language',languages,selectedLanguages]]){
    const count=options.filter(name=>selected.has(name)).length;
    const all=$('#quick-'+kind+'-all');if(all)all.setAttribute('aria-pressed',options.length>0&&count===options.length);
    const status=$('#quick-'+kind+'-status');if(status)status.textContent=count===0?'None selected':count===options.length?`All ${options.length} selected`:`${count} of ${options.length} selected`;
  }
}
function toggleQuickFilter(kind,name) {
  const options=kind==='platforms'?availablePlatforms():languages;
  if(!options.includes(name))return;
  const selected=kind==='platforms'?selectedPlatforms:selectedLanguages;
  if(selected.has(name))selected.delete(name);else selected.add(name);
  persist('ottscout-'+kind,selected);visibleLimit=PAGE_SIZE;updateSelections();render();
}
function selectAllQuickFilters(kind) {
  const selected=kind==='platforms'?selectedPlatforms:selectedLanguages;
  const options=kind==='platforms'?availablePlatforms():languages;
  selected.clear();options.forEach(name=>selected.add(name));
  persist('ottscout-'+kind,selected);visibleLimit=PAGE_SIZE;updateSelections();render();
}
function setupQuickFilters() {
  document.querySelectorAll('.quick-platform').forEach(button=>button.onclick=()=>toggleQuickFilter('platforms',button.dataset.platform));
  document.querySelectorAll('.quick-language').forEach(button=>button.onclick=()=>toggleQuickFilter('languages',button.dataset.language));
  if($('#quick-platform-all'))$('#quick-platform-all').onclick=()=>selectAllQuickFilters('platforms');
  if($('#quick-language-all'))$('#quick-language-all').onclick=()=>selectAllQuickFilters('languages');
  syncQuickFilters();
}
function setView(next, moveFocus=false) {
  view = next; visibleLimit = PAGE_SIZE;
  document.querySelectorAll('.view-tabs button').forEach(button => {
    button.classList.toggle('active',button.dataset.view === view);
    if (button.dataset.view === view) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  });
  render();
  if(moveFocus)$('#heading').focus();
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
  else if (audioDescriptionOnly) {heading='No current description reports match';message='Try more description languages or explore the full catalogue. Unverified does not mean unavailable; confirm tracks with the provider.';}
  else if (view === 'watchlist') { heading = 'A good watch is worth saving'; message = 'Tap + on a title to add it to your watchlist. Your current filters also apply here.'; }
  else if (view === 'leaving') {heading='No departures match';message='No matching provider-reported offer end dates in the next 30 days. Listings can change; confirm on the platform.';}
  else if (view === 'weekly') {
    heading = 'No additions match your filters';
    message = liveCatalog?.recentHistoryComplete ? 'No provider-reported additions match this search in the last seven days. You can still explore the full catalog.' : 'We’re filling in the last seven days of streaming additions. Explore the catalog while that history loads.';
  }
  node.append(element('h2',heading),element('p',message));
  const action = element('button',view === 'discover' ? 'Reset filters' : 'Explore all titles');
  action.type='button'; action.onclick=()=>{ if(view==='discover') resetFilters(); else { $('#search').value=''; setView('discover'); } };
  node.append(action);
  if(audioDescriptionOnly){const guide=element('a','Read the audio-description guide');guide.href='/audio-description/';node.append(guide);}
  return node;
}
function normalizeSearch(value) {
  return value.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase().trim();
}
function suggestTitles(query, items, limit=6) {
  const q=normalizeSearch(query);
  if(q.length<2)return [];
  return items.filter(t=>normalizeSearch(t.title).includes(q)).sort((a,b)=>{
    const rank=t=>normalizeSearch(t.title)===q?0:normalizeSearch(t.title).startsWith(q)?1:2;
    return rank(a)-rank(b)||(b.year||0)-(a.year||0)||a.title.localeCompare(b.title)||String(a.id).localeCompare(String(b.id));
  }).slice(0,limit);
}
function closeSuggestions() {
  suggestions=[];activeSuggestion=-1;$('#search-suggestions').hidden=true;
  $('#search').setAttribute('aria-expanded','false');$('#search').removeAttribute('aria-activedescendant');
  $('#suggestion-status').textContent='';
}
function highlightSuggestion(index) {
  activeSuggestion=index;
  document.querySelectorAll('#search-suggestions [role="option"]').forEach((node,i)=>node.setAttribute('aria-selected',i===index?'true':'false'));
  if(index>=0){$('#search').setAttribute('aria-activedescendant','search-option-'+index);$('#search-option-'+index).scrollIntoView({block:'nearest'});}
  else $('#search').removeAttribute('aria-activedescendant');
}
function chooseSuggestion(title) {
  $('#search').value=title.title;selectedSearchId=title.id;visibleLimit=PAGE_SIZE;
  closeSuggestions();setView('discover');$('#search').blur();$('#heading').focus();
}
function renderSuggestions() {
  const eligible=titles.filter(t=>matchingGenres(t)&&matchingOffers(t,false).length&&!dismissed.has(t.id)&&(contentType==='all'||t.type===contentType));
  suggestions=suggestTitles($('#search').value,eligible);activeSuggestion=-1;
  const list=$('#search-suggestions');list.replaceChildren();
  if(!suggestions.length){closeSuggestions();return;}
  suggestions.forEach((title,i)=>{
    const option=element('div',undefined,'search-option');option.id='search-option-'+i;
    option.setAttribute('role','option');option.setAttribute('aria-selected','false');
    option.append(element('span',title.title,'suggestion-title'),element('span',`${title.year||'Year unverified'} · ${title.type}`,'suggestion-meta'));
    option.onpointerdown=event=>event.preventDefault();
    option.onclick=()=>chooseSuggestion(title);list.append(option);
  });
  list.hidden=false;$('#search').setAttribute('aria-expanded','true');$('#search').removeAttribute('aria-activedescendant');
  $('#suggestion-status').textContent=`${suggestions.length} title suggestion${suggestions.length===1?'':'s'}. Use up and down arrows, then Enter to select.`;
}
function searchInput(event) {
  if(event?.isComposing)return;
  selectedSearchId=null;visibleLimit=PAGE_SIZE;
  if($('#search').value.trim()&&view==='weekly')setView('discover');else render();
  renderSuggestions();
}
function searchKeydown(event) {
  if(event.isComposing)return;
  if((event.key==='ArrowDown'||event.key==='ArrowUp')&&suggestions.length){
    event.preventDefault();highlightSuggestion(event.key==='ArrowDown'?(activeSuggestion+1)%suggestions.length:(activeSuggestion<=0?suggestions.length-1:activeSuggestion-1));
  }else if(event.key==='Escape'&&!$('#search-suggestions').hidden){event.preventDefault();event.stopPropagation();closeSuggestions();}
  else if(event.key==='Enter'){
    event.preventDefault();
    if(activeSuggestion>=0&&suggestions[activeSuggestion])chooseSuggestion(suggestions[activeSuggestion]);
    else{closeSuggestions();$('#search').blur();$('#heading').focus();}
  }
}
function filteredTitles(forView=view) {
  const query = normalizeSearch($('#search').value);
  return titles.filter(title => matchingGenres(title) && matchingOffers(title,forView==='weekly').length
    && (query&&selectedSearchId!==null?title.id===selectedSearchId:normalizeSearch(title.title).includes(query))
    && (forView === 'watchlist' || !dismissed.has(title.id))
    && (contentType === 'all' || title.type === contentType)
    && (forView !== 'watchlist' || saved.has(title.id))
    && (forView !== 'weekly' || (weeklyTitle(title) && weeklyKindMatches(title)))
    && (forView !== 'leaving' || earliestExpiry(title)!==null));
}
function weeklyGroupsContent(found) {
  const groups=weeklyDateGroups(found);
  const rendered=[];
  const description=()=>{
    const open=rendered.filter(group=>group.node.open);
    return `This week: ${found.length} matching ${found.length===1?'title':'titles'} across ${groups.length} date ${groups.length===1?'group':'groups'}. ${open.reduce((sum,group)=>sum+group.shown,0)} titles shown in ${open.length} open ${open.length===1?'group':'groups'}.`+(audioDescriptionOnly?' Only matching provider-reported description languages are included; India playback is unverified.':'');
  };
  const content=groups.map((data,index)=>{
    const group=element('details',undefined,'date-group');group.dataset.date=data.key;
    group.open=weeklyOpen.has(data.key)?weeklyOpen.get(data.key):index===0;
    const summary=element('summary',undefined,'date-summary');
    const label=element('h2',data.label,'date-label');
    const count=element('span',data.titles.length?data.titles.length+' '+(data.titles.length===1?'title':'titles'):'0 matches','date-count');
    const chevron=element('span','⌄','date-chevron');chevron.setAttribute('aria-hidden','true');summary.append(label,count,chevron);group.append(summary);
    const body=element('div',undefined,'date-group-body');
    const list=element('div',undefined,'date-titles');
    const limit=weeklyLimits.get(data.key)||PAGE_SIZE;
    const shown=Math.min(limit,data.titles.length);
    const adAfter=window.matchMedia('(max-width:650px)').matches?6:12;
    data.titles.slice(0,shown).forEach((title,i)=>{list.append(cardFor(title));if(i===adAfter-1&&data.titles.length>adAfter)list.append(adSlot());});
    if(data.titles.length)body.append(list);
    else{
      const note=element('div',undefined,'date-filtered');
      note.append(element('p',`${data.count} ${data.count===1?'addition':'additions'} on ${data.platforms.join(', ')} ${data.count===1?'is':'are'} hidden by your filters.`));
      const reset=element('button','Reset filters');reset.type='button';reset.setAttribute('aria-label','Reset filters and show additions for '+data.label);
      reset.onclick=()=>{weeklyOpen.set(data.key,true);resetFilters();const restored=[...document.querySelectorAll('#catalog .date-group')].find(item=>item.dataset.date===data.key)?.querySelector('summary');(restored||$('#heading')).focus();};
      note.append(reset);body.append(note);
    }
    if(shown<data.titles.length){
      const more=element('button',`Show ${Math.min(PAGE_SIZE,data.titles.length-shown)} more · ${shown} of ${data.titles.length} shown`,'date-load-more');more.type='button';
      more.setAttribute('aria-label',`Show ${Math.min(PAGE_SIZE,data.titles.length-shown)} more titles for ${data.label}. ${shown} of ${data.titles.length} shown.`);
      more.onclick=()=>{const next=data.titles[shown]?.id;weeklyLimits.set(data.key,limit+PAGE_SIZE);weeklyOpen.set(data.key,true);render();focusTitle(next);};body.append(more);
    }
    group.append(body);rendered.push({node:group,shown});
    let lastOpen=group.open;
    group.addEventListener('toggle',event=>{if(event.target!==group||group.open===lastOpen)return;lastOpen=group.open;weeklyOpen.set(data.key,group.open);updateDateToggle();announceResults(description());});
    return group;
  });
  return {content,description};
}
function updateDateToggle() {
  const button=$('#toggle-dates');if(!button)return;
  const groups=[...document.querySelectorAll('#catalog .date-group')];
  button.hidden=view!=='weekly'||!groups.length;
  button.textContent=groups.some(group=>group.open)?'Collapse all dates':'Expand all dates';
}
function toggleAllDates() {
  if(view!=='weekly')return;
  const groups=[...document.querySelectorAll('#catalog .date-group')];
  const open=!groups.some(group=>group.open);
  groups.forEach(group=>weeklyOpen.set(group.dataset.date,open));
  render();$('#toggle-dates').focus();
}
function pickRandomTitle() {
  const choice=randomTitle(filteredTitles());
  if(!choice)return;
  chooseSuggestion(choice);
  announceResults('Random pick: '+choice.title+'. Your platform, language and other filters are retained.');
}
function render() {
  activeFilterChips();syncQuickFilters();
  const found=filteredTitles();
  found.sort((a,b) => view === 'weekly' ? (weeklyAdditionTime(b)||0)-(weeklyAdditionTime(a)||0)||a.title.localeCompare(b.title)
    : view==='leaving'?earliestExpiry(a)-earliestExpiry(b)||a.title.localeCompare(b.title)
    : (b.year || 0) - (a.year || 0) || a.title.localeCompare(b.title));
  $('#count').textContent = saved.size;
  $('#restore-hidden').hidden = dismissed.size === 0;
  $('#restore-hidden').textContent = `Restore hidden titles (${dismissed.size})`;
  $('#weekly-count').textContent = filteredTitles('weekly').length;
  if($('#leaving-count'))$('#leaving-count').textContent=filteredTitles('leaving').length;
  if($('#pick-one')){const pending=$('#catalog-section')?.dataset.ready==='false';$('#pick-one').disabled=pending||!found.length;$('#pick-one').setAttribute('aria-label',pending?'Pick one for me':'Pick one for me. Random choice from '+found.length+' matching titles');}
  $('#weekly-kind').hidden = view !== 'weekly';
  $('#heading').textContent = {discover:'Discover',weekly:'Added this week',watchlist:'Watchlist',leaving:'Leaving soon'}[view];
  $('#description').hidden=Boolean(liveCatalog)&&!['weekly','leaving'].includes(view);
  $('#description').textContent = view === 'weekly' ? liveCatalog ? 'Platform additions · Premiere dates unverified.' : 'Illustrative weekly picks from the sample catalog.'
    : view === 'leaving' ? liveCatalog?'Provider-reported offer end dates in the next 30 days. Confirm on the platform.':'Sample preview · Departure dates are unavailable.'
    : view === 'watchlist' ? 'Your saved titles.'
      : liveCatalog ? 'Movies and series matching your filters.' : 'Explore the sample catalog while live data is unavailable.';
  $('#result-count').textContent = `${found.length} ${found.length === 1 ? 'title' : 'titles'}`;
  const weekly=view==='weekly'?weeklyGroupsContent(found):null;
  const content=weekly?weekly.content:[];
  if(!weekly){const adAfter=window.matchMedia('(max-width:650px)').matches?6:12;found.slice(0,visibleLimit).forEach((title,index)=>{content.push(cardFor(title));if(index===adAfter-1&&found.length>adAfter)content.push(adSlot());});}
  $('#catalog').replaceChildren(...(content.length ? content : [emptyState()]));
  updateSaveAvailability();
  updateDateToggle();
  $('#load-more').hidden = view==='weekly'||found.length <= visibleLimit;
  $('#load-more').textContent = `Show ${Math.min(PAGE_SIZE, Math.max(0,found.length-visibleLimit))} more titles`;
  announceResults(weekly?weekly.description():`${{discover:'Discover',watchlist:'Watchlist',leaving:'Leaving soon'}[view]}: ${found.length} ${found.length===1?'title matches':'titles match'}. ${Math.min(visibleLimit,found.length)} shown.${audioDescriptionOnly?' Only provider-reported description languages matching Watch in are included; India playback is unverified.':''}`);
}
function resetFilters() {
  selectedPlatforms.clear(); availablePlatforms().forEach(name=>selectedPlatforms.add(name));
  selectedLanguages.clear(); languages.forEach(name=>selectedLanguages.add(name));
  persist('ottscout-platforms',selectedPlatforms); persist('ottscout-languages',selectedLanguages);
  selectedOriginals=null;persist('ottscout-originals',['*']);renderOriginals();
  subscriptionOnly=false;$('#subscription-only').checked=false;persist('ottscout-subscription-only',[false]);
  selectedGenres=null; persist('ottscout-genres',['*']);renderGenres();
  originalOnly=false; $('#original-only').checked=false; persist('ottscout-original-only',[false]);
  audioDescriptionOnly=false;$('#audio-description-only').checked=false;persist('ottscout-audio-description',[false]);
  $('#search').value=''; contentType='all'; weeklyKind='all'; visibleLimit=PAGE_SIZE;
  document.querySelectorAll('#weekly-kind button').forEach(button=>button.setAttribute('aria-pressed',button.dataset.kind==='all'));
  document.querySelectorAll('#type button').forEach(button=>button.setAttribute('aria-pressed',button.dataset.type==='all'));
  updateSelections(); render();
}
function restoreHiddenTitles() {
  const count=dismissed.size;
  dismissed.clear();
  persist('ottscout-dismissed',dismissed);
  render();
  $('#heading').focus();
  announceResults(count ? `${count} hidden ${count===1?'title':'titles'} restored. Current filters and view still apply.` : 'No hidden titles to restore.');
}
function setupFilterPanel(menus) {
  const panel=$('#filters-panel');
  if(!panel)return;
  const summary=$('#filters-summary');
  const advanced=$('#advanced-filters');
  const closeMenus=()=>menus.forEach(menu=>{menu.open=false;});
  const closeChildren=()=>{closeMenus();if(advanced)advanced.open=false;};
  const viewport=window.matchMedia('(max-width:900px)');
  panel.open=!viewport.matches;
  closeChildren();
  panel.addEventListener('toggle',event=>{
    if(event.target!==panel)return;
    if(panel.open){$('#search').blur();closeSuggestions();return;}
    closeChildren();
    if(panel.contains(document.activeElement)&&document.activeElement!==summary)summary.focus();
  });
  if(advanced)advanced.addEventListener('toggle',event=>{
    if(event.target!==advanced||advanced.open)return;
    closeMenus();
    if(panel.open&&advanced.contains(document.activeElement))advanced.querySelector('summary').focus();
  });
  const resize=()=>{
    if(viewport.matches){panel.open=false;closeChildren();if(panel.contains(document.activeElement))summary.focus();}
    else{panel.open=true;if(document.activeElement===summary)$('#search').focus();}
  };
  if(viewport.addEventListener)viewport.addEventListener('change',resize);else if(viewport.addListener)viewport.addListener(resize);
  $('#filters-done').onclick=()=>{panel.open=false;closeChildren();$('#heading').focus();};
}
function setupFilterMenus(menus) {
  menus.forEach(menu=>{
    menu.addEventListener('toggle',()=>{
      if(!menu.open)return;
      if($('#filters-panel')&&!$('#filters-panel').open){menu.open=false;return;}
      menus.filter(other=>other!==menu).forEach(other=>{other.open=false;});
    });
    menu.addEventListener('focusout',event=>{
      if(menu.open&&!menu.contains(event.relatedTarget))menu.open=false;
    });
  });
  document.addEventListener('click',event=>menus.forEach(menu=>{if(!menu.contains(event.target))menu.open=false;}));
}
function handleGlobalKeydown(event,menus) {
  if(event.defaultPrevented || $('#account-dialog')?.open)return;
  if(shortcutsEnabled && event.key==='/'&&!event.altKey&&!event.ctrlKey&&!event.metaKey&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName) && !document.activeElement.isContentEditable && !$('#report-dialog').open){event.preventDefault();$('#search').focus();}
  if($('#report-dialog').open)return;
  if(event.key!=='Escape')return;
  const child=menus.find(menu=>menu.open);
  if(child){event.preventDefault();const hadFocus=child.contains(document.activeElement);child.open=false;if(hadFocus)child.querySelector('summary').focus();return;}
  const advanced=$('#advanced-filters');
  if(advanced?.open){event.preventDefault();const hadFocus=advanced.contains(document.activeElement);advanced.open=false;if(hadFocus)advanced.querySelector('summary').focus();return;}
  const panel=$('#filters-panel');
  if(panel?.open){event.preventDefault();const hadFocus=panel.contains(document.activeElement);panel.open=false;if(hadFocus)$('#filters-summary').focus();}
}
// Account capability updates apply even when the saved IDs have not changed.
function applyAccountWatchlistState(state) {
  if (!(state?.ids instanceof Set)) return;
  accountWatchlistState=state;
  const changed=saved.size!==state.ids.size || [...saved].some(id=>!state.ids.has(id));
  if(!changed){updateSaveAvailability();return;}
  saved.clear();state.ids.forEach(id=>saved.add(id));
  if(accountToggleInProgress){updateSaveAvailability();return;}
  const focused=document.activeElement;
  const focusedCard=focused?.closest?.('.card');
  const focusId=focusedCard?.dataset.titleId;
  const wasSave=focused?.classList?.contains('save');
  render();
  if(focusId&&wasSave){
    const button=[...document.querySelectorAll('#catalog .card')].find(card=>card.dataset.titleId===focusId)?.querySelector('.save');
    if(button&&!button.disabled)button.focus();
  }
}
for (const kind of ['platforms','languages']) renderOptions(kind);
if(new URL(window.location.href).searchParams.get('audio-description')==='reported'){audioDescriptionOnly=true;view='discover';}
updateSelections();
renderGenres();renderOriginals();
setupQuickFilters();
if($('#pick-one'))$('#pick-one').onclick=pickRandomTitle;
if($('#toggle-dates'))$('#toggle-dates').onclick=toggleAllDates;
$('#original-all').onclick=()=>{selectedOriginals=null;persist('ottscout-originals',['*']);visibleLimit=PAGE_SIZE;renderOriginals();render();};
$('#original-clear').onclick=()=>{selectedOriginals=new Set();persist('ottscout-originals',selectedOriginals);visibleLimit=PAGE_SIZE;renderOriginals();render();};
$('#subscription-only').checked=subscriptionOnly;
$('#subscription-only').onchange=()=>{subscriptionOnly=$('#subscription-only').checked;persist('ottscout-subscription-only',[subscriptionOnly]);visibleLimit=PAGE_SIZE;render();};
$('#genre-all').onclick=()=>{selectedGenres=null;persist('ottscout-genres',['*']);visibleLimit=PAGE_SIZE;renderGenres();render();};
$('#genre-clear').onclick=()=>{selectedGenres=new Set();persist('ottscout-genres',selectedGenres);visibleLimit=PAGE_SIZE;renderGenres();render();};
$('#original-only').checked=originalOnly;
$('#original-only').onchange=()=>{originalOnly=$('#original-only').checked;persist('ottscout-original-only',[originalOnly]);visibleLimit=PAGE_SIZE;render();};
$('#restore-hidden').onclick=restoreHiddenTitles;
$('#search').onkeydown=searchKeydown;
$('#search').oninput=searchInput;
$('#search').oncompositionend=searchInput;
$('#search').onfocus=renderSuggestions;
$('#search').onblur=closeSuggestions;
document.addEventListener('pointerdown',event=>{if(!event.target.closest?.('.search-autocomplete'))closeSuggestions();});
$('#reset-filters').onclick=resetFilters;
$('#audio-description-only').checked=audioDescriptionOnly;
$('#audio-description-only').onchange=()=>{audioDescriptionOnly=$('#audio-description-only').checked;persist('ottscout-audio-description',[audioDescriptionOnly]);visibleLimit=PAGE_SIZE;render();};
$('#enable-shortcuts').checked=shortcutsEnabled;
$('#enable-shortcuts').onchange=()=>{shortcutsEnabled=$('#enable-shortcuts').checked;persist('ottscout-shortcuts',[shortcutsEnabled]);};
document.querySelectorAll('#weekly-kind button').forEach(button=>button.onclick=()=>{
  weeklyKind=button.dataset.kind;visibleLimit=PAGE_SIZE;
  document.querySelectorAll('#weekly-kind button').forEach(option=>option.setAttribute('aria-pressed',option===button));render();
});
$('#load-more').onclick=()=>{const before=new Set([...document.querySelectorAll('#catalog .card')].map(n=>n.dataset.titleId));visibleLimit+=PAGE_SIZE;render();focusTitle([...document.querySelectorAll('#catalog .card')].find(n=>!before.has(n.dataset.titleId))?.dataset.titleId);};
for (const attribute of ['select-all','clear']) document.querySelectorAll(`[data-${attribute}]`).forEach(button=>{
  button.onclick=()=>{
    const kind=button.dataset[attribute==='select-all'?'selectAll':'clear'];
    const selected=kind==='platforms'?selectedPlatforms:selectedLanguages;
    const options=kind==='platforms'?availablePlatforms():languages;
    selected.clear(); if(attribute==='select-all') options.forEach(name=>selected.add(name));
    persist('ottscout-'+kind,selected);visibleLimit=PAGE_SIZE;updateSelections();render();
  };
});
document.querySelectorAll('#type button').forEach(button=>button.onclick=()=>{
  contentType=button.dataset.type;visibleLimit=PAGE_SIZE;
  document.querySelectorAll('#type button').forEach(option=>option.setAttribute('aria-pressed',option===button));render();
});
document.querySelectorAll('.view-tabs button').forEach(button=>button.onclick=()=>setView(button.dataset.view,true));
const menus=[$('#platform-menu'),$('#language-menu'),$('#original-menu'),$('#genre-menu')];
setupFilterPanel(menus);
setupFilterMenus(menus);
document.addEventListener('keydown',event=>handleGlobalKeydown(event,menus));
setView(view);

async function loadCatalog() {
  try {
    const response=await fetch('data/catalog.json',{cache:'no-store'});
    if(!response.ok)throw new Error('No live snapshot');
    const data=await response.json();
    if(data.schemaVersion!==1||data.mode!=='live'||!Array.isArray(data.titles)||!Number.isFinite(Date.parse(data.updatedAt))||!Array.isArray(data.missingPlatforms))throw new Error('Invalid catalog');
    for(const title of data.titles){
      if(title.tmdb && (!Array.isArray(title.tmdb.genres)||!title.tmdb.genres.every(g=>typeof g==='string')))throw new Error('Invalid genres');
      if(title.originalLanguage != null && typeof title.originalLanguage !== 'string')throw new Error('Invalid original language');
      if(title.weeklyEvents !== undefined && (!Array.isArray(title.weeklyEvents) || title.weeklyEvents.some(event => !event || !platforms.includes(event.platform) || !Number.isFinite(event.addedAt))))throw new Error('Invalid addition history');
      if(typeof title.id!=='string'||!title.id.startsWith('motn:')||typeof title.title!=='string'||!['Movie','Series'].includes(title.type)||!Array.isArray(title.offers)||!Array.isArray(title.weeklyPlatforms)||!Number.isFinite(title.lastCheckedAt))throw new Error('Invalid title');
      for(const offer of title.offers)if(!platforms.includes(offer.platform)||!Array.isArray(offer.audio)||!offer.audio.every(x=>typeof x==='string')||!Array.isArray(offer.subtitles)||!offer.subtitles.every(x=>typeof x==='string'))throw new Error('Invalid offer');
    }
    liveCatalog=data;titles=data.titles;
    for (const p of selectedPlatforms) if (!availablePlatforms().includes(p)) selectedPlatforms.delete(p);
    renderGenres();renderOriginals();
    $('#catalog-status').hidden=true;
    renderOptions('platforms');updateSelections();render();
  } catch {
    $('#catalog-status').textContent='Sample preview · Live catalog unavailable. Titles and streaming details below are illustrative.';
    $('#catalog-status').hidden=false;
  } finally {
    $('#catalog-section').dataset.ready='true';
    $('#catalog-loading').hidden=true;
    $('#search').disabled=false;$('#search').placeholder='Search a movie or series…';
    render();
    if(document.activeElement===$('#search'))renderSuggestions();
    document.dispatchEvent(new Event('ottscout:ready'));
  }
}
loadCatalog();

window.addEventListener('ottscout:watchlist',event=>applyAccountWatchlistState(event.detail));
window.dispatchEvent(new Event('ottscout:watchlist-request'));
