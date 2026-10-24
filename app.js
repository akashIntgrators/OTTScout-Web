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

let titles = sampleTitles;
let liveCatalog = null;

function visibleOffers(title) {
  const offers = title.offers || [{platform: title.platform, audio: title.audio, subtitles: [], type: 'sample'}];
  return offers.filter(offer => !excludedPlatforms.has(offer.platform)
    && offer.audio.some(language => selectedLanguages.has(language))
    && (view !== 'weekly' || !liveCatalog || title.weeklyPlatforms.includes(offer.platform)));
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
function cardFor(title) {
  const card = element('article', undefined, 'card');
  const poster = element('div', undefined, 'poster');
  poster.style.setProperty('--c', title.color || '#40574c');
  const imageURL = liveCatalog ? secureURL(title.poster) : `assets/${title.artwork}.png`;
  if (imageURL) {
    const img = element('img');
    img.src = imageURL; img.alt = ''; img.loading = 'lazy'; img.width = 1024; img.height = 1536;
    img.onerror = () => img.remove();
    poster.append(img);
  }
  poster.append(element('span', title.type + (liveCatalog ? '' : ' · SAMPLE'), 'badge'), element('strong', title.title));
  const save = element('button', saved.has(title.id) ? '✓' : '+', 'save');
  save.type = 'button';
  save.setAttribute('aria-label', `${saved.has(title.id) ? 'Remove from' : 'Add to'} watchlist: ${title.title}`);
  save.setAttribute('aria-pressed', saved.has(title.id));
  save.onclick = () => {
    saved.has(title.id) ? saved.delete(title.id) : saved.add(title.id);
    persist('ottscout-watchlist', saved);
    render();
  };
  poster.append(save);
  const details = element('div', undefined, 'details');
  details.append(element('h3', title.title), element('div', `${title.year || 'Year unverified'} · ${title.type}${liveCatalog ? '' : ' · Illustrative title'}`, 'meta'));
  const offerNames = {subscription: 'Included with subscription', free: 'Free', rent: 'Rental', buy: 'Purchase', addon: 'Add-on subscription', sample: 'Sample listing'};
  for (const offer of visibleOffers(title)) {
    const section = element('div', undefined, 'offer');
    const label = `${offer.platform} · ${offerNames[offer.type] || 'Offer unverified'}${offer.addon ? ' · ' + offer.addon : ''}`;
    const link = secureURL(offer.link);
    const provider = element(link ? 'a' : 'div', label, 'provider');
    if (link) { provider.href = link; provider.target = '_blank'; provider.rel = 'noopener noreferrer'; }
    section.append(provider, element('div', `Audio: ${offer.audio.join(' · ') || 'Unverified'}`, 'audio'),
      element('div', `Subtitles: ${offer.subtitles.join(' · ') || 'Unverified'}`, 'audio'));
    details.append(section);
  }
  if (liveCatalog) details.append(element('div', `Checked ${new Date(title.lastCheckedAt * 1000).toLocaleString('en-IN', {timeZone:'Asia/Kolkata'})} IST`, 'checked'));
  card.append(poster, details);
  return card;
}
function readList(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value : [];
  } catch { return []; }
}
function persist(key, value) {
  try { localStorage.setItem(key, JSON.stringify([...value])); } catch { /* Browser storage may be unavailable. */ }
}
let saved = new Set(readList('ottscout-watchlist')); // Preserve saved IDs when a cached title is temporarily absent.
const excludedPlatforms = new Set(readList('ottscout-excluded-platforms').filter(p => platforms.includes(p)));
const selectedLanguages = new Set(languages);
let view = 'discover';
let contentType = 'all';
const $ = selector => document.querySelector(selector);

function renderLanguageChips() {
  $('#languages').replaceChildren(...languages.map(name => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = name;
    button.setAttribute('aria-pressed', selectedLanguages.has(name));
    button.onclick = () => {
      selectedLanguages.has(name) ? selectedLanguages.delete(name) : selectedLanguages.add(name);
      renderLanguageChips();
      render();
    };
    return button;
  }));
}
function updatePlatformSummary() {
  const count = excludedPlatforms.size;
  $('#platform-summary span').textContent = count ? `${count} excluded` : 'None excluded';
  document.querySelectorAll('#platforms input').forEach(input => { input.checked = excludedPlatforms.has(input.value); });
}
function renderPlatformOptions() {
  $('#platforms').replaceChildren(...platforms.map(name => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = name;
    checkbox.checked = excludedPlatforms.has(name);
    checkbox.setAttribute('aria-label', `Exclude ${name}`);
    checkbox.onchange = () => {
      checkbox.checked ? excludedPlatforms.add(name) : excludedPlatforms.delete(name);
      persist('ottscout-excluded-platforms', excludedPlatforms);
      updatePlatformSummary();
      render();
    };
    label.append(checkbox, document.createTextNode(name));
    return label;
  }));
  updatePlatformSummary();
}
function render() {
  const query = $('#search').value.toLowerCase().trim();
  const found = titles.filter(t => visibleOffers(t).length > 0
    && t.title.toLowerCase().includes(query)
    && (contentType === 'all' || t.type === contentType)
    && (view !== 'watchlist' || saved.has(t.id))
    && (view !== 'weekly' || t.weekly));
  $('#count').textContent = saved.size;
  $('#heading').textContent = {
    discover: 'A little something for every mood',
    weekly: 'Fresh picks for your week',
    watchlist: 'Your next movie night starts here',
  }[view];
  $('#description').textContent = view === 'weekly'
    ? liveCatalog ? 'Newly detected streaming availability in the past seven days. Initial imports are excluded.' : 'Illustrative weekly selection — live release dates are not connected.'
    : view === 'watchlist'
      ? 'Saved on this browser. Alerts are not connected yet.'
      : liveCatalog ? 'Search the imported catalog. Audio languages are reported per platform.' : 'Explore the sample catalog. Save a title for later.';
  $('#catalog').replaceChildren(...found.map(cardFor));
  if (!found.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.setAttribute('role', 'status');
    empty.textContent = excludedPlatforms.size === platforms.length
      ? 'All platforms are excluded. Open Exclude platforms and choose Include all platforms to see titles.'
      : view === 'watchlist'
        ? 'No saved titles match your filters. Save a title from Discover or adjust your filters.'
        : 'No titles match. Try another search, include more platforms, or select more languages.';
    $('#catalog').append(empty);
  }
}
renderPlatformOptions();
renderLanguageChips();
$('#search').oninput = render;
$('#reset-platforms').onclick = () => {
  excludedPlatforms.clear();
  persist('ottscout-excluded-platforms', excludedPlatforms);
  updatePlatformSummary();
  render();
};
document.querySelectorAll('#type button').forEach(button => {
  button.onclick = () => {
    contentType = button.dataset.type;
    document.querySelectorAll('#type button').forEach(option => option.setAttribute('aria-pressed', option === button));
    render();
  };
});
document.querySelectorAll('nav button').forEach(button => {
  button.onclick = () => {
    view = button.dataset.view;
    document.querySelectorAll('nav button').forEach(option => option.classList.toggle('active', option === button));
    render();
  };
});
document.addEventListener('keydown', event => {
  if (event.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
    event.preventDefault();
    $('#search').focus();
  }
  if (event.key === 'Escape' && $('#platform-menu').open) {
    $('#platform-menu').open = false;
    $('#platform-summary').focus();
  }
});
document.addEventListener('click', event => {
  if (!$('#platform-menu').contains(event.target)) $('#platform-menu').open = false;
});
render();

async function loadCatalog() {
  try {
    const response = await fetch('data/catalog.json', {cache: 'no-store'});
    if (!response.ok) throw new Error('No live snapshot');
    const data = await response.json();
    if (data.schemaVersion !== 1 || data.mode !== 'live' || !Array.isArray(data.titles) || !Number.isFinite(Date.parse(data.updatedAt))) throw new Error('Invalid catalog');
    for (const title of data.titles) {
      if (typeof title.id !== 'string' || !title.id.startsWith('motn:') || typeof title.title !== 'string'
        || !['Movie','Series'].includes(title.type) || !Array.isArray(title.offers)
        || !Array.isArray(title.weeklyPlatforms) || !Number.isFinite(title.lastCheckedAt)) throw new Error('Invalid title');
      for (const offer of title.offers) {
        if (!platforms.includes(offer.platform) || !Array.isArray(offer.audio) || !offer.audio.every(x => typeof x === 'string')
          || !Array.isArray(offer.subtitles) || !offer.subtitles.every(x => typeof x === 'string')) throw new Error('Invalid offer');
      }
    }
    liveCatalog = data;
    titles = data.titles;
    const stale = Date.now() - Date.parse(data.updatedAt) > 12 * 60 * 60 * 1000;
    const missing = Array.isArray(data.missingPlatforms) && data.missingPlatforms.length ? ` Coverage unavailable: ${data.missingPlatforms.join(', ')}.` : '';
    $('.notice').textContent = `${stale ? 'Updates delayed · ' : ''}India catalog · Last successful update ${new Date(data.updatedAt).toLocaleString('en-IN', {timeZone:'Asia/Kolkata'})} IST.${missing} Search covers imported titles; this is not a complete platform catalog.`;
    const attribution = element('a', 'Streaming data: Movie of the Night');
    attribution.href = 'https://www.movieofthenight.com/about/api'; attribution.target = '_blank'; attribution.rel = 'noopener noreferrer';
    $('footer').append(attribution);
    $('footer span:last-of-type').textContent = 'Catalog checked every six hours during the pilot. Notifications coming later.';
    render();
  } catch {
    // A missing or invalid snapshot keeps the clearly labelled illustrative catalog.
    $('.notice').textContent = 'Preview · Live catalog is not available yet. Titles, platforms and languages below are illustrative sample data.';
  }
}
loadCatalog();
