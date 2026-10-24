const platforms = ['Netflix', 'Prime Video', 'Sun NXT', 'JioHotstar', 'ZEE5', 'aha', 'SonyLIV'];
const languages = ['English', 'Hindi', 'Telugu', 'Tamil', 'Kannada', 'Malayalam'];
const titles = [
  ['The Last Horizon', 'Movie', 2026, 'Netflix', ['English', 'Hindi'], '#456359', true, 'horizon', ['Adventure', 'Science fiction']],
  ['Hyderabad Nights', 'Series', 2026, 'aha', ['Telugu', 'Tamil'], '#70483a', true, 'hyderabad', ['Drama']],
  ['Monsoon Letters', 'Movie', 2025, 'Prime Video', ['Malayalam', 'Tamil', 'Hindi'], '#46647b', false, 'monsoon', ['Romance', 'Drama']],
  ['City of Echoes', 'Series', 2026, 'SonyLIV', ['Hindi', 'English'], '#675173', true, 'echoes', ['Mystery', 'Thriller']],
  ['A Sunday in Chennai', 'Movie', 2026, 'Sun NXT', ['Tamil', 'Telugu'], '#9b6740', false, 'chennai', ['Drama', 'Comedy']],
  ['Beyond the Hills', 'Movie', 2026, 'ZEE5', ['Kannada', 'Telugu'], '#536744', true, 'hills', ['Adventure']],
  ['The Quiet Coast', 'Series', 2025, 'JioHotstar', ['English', 'Hindi', 'Tamil'], '#376c72', false, 'coast', ['Mystery']],
  ['Homeward Bound', 'Movie', 2026, 'Prime Video', ['Malayalam', 'Kannada'], '#866252', true, 'homeward', ['Family', 'Drama']],
].map((x, id) => ({ id, title: x[0], type: x[1], year: x[2], platform: x[3], audio: x[4], color: x[5], weekly: x[6], artwork: x[7], genres: x[8] }));

function readList(key) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(value) ? value : [];
  } catch { return []; }
}
function persist(key, value) {
  try { localStorage.setItem(key, JSON.stringify([...value])); } catch { /* Browser storage may be unavailable. */ }
}
let saved = new Set(readList('ottscout-watchlist').filter(id => titles.some(t => t.id === id)));
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
  const found = titles.filter(t => !excludedPlatforms.has(t.platform)
    && t.audio.some(language => selectedLanguages.has(language))
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
    ? 'Illustrative weekly selection — live release dates are not connected.'
    : view === 'watchlist'
      ? 'Saved on this browser. Alerts are not connected yet.'
      : 'Explore the sample catalog. Save a title for later.';
  $('#catalog').replaceChildren(...found.map(t => {
    const card = document.createElement('article');
    card.className = 'card';
    card.innerHTML = `<div class="poster" style="--c:${t.color}"><img src="assets/${t.artwork}.png" alt="" loading="lazy" width="1024" height="1536"><span class="badge">${t.type} · SAMPLE</span><strong>${t.title}</strong><button type="button" class="save" aria-label="${saved.has(t.id) ? 'Remove from' : 'Add to'} watchlist: ${t.title}" aria-pressed="${saved.has(t.id)}">${saved.has(t.id) ? '✓' : '+'}</button></div><div class="details"><h3>${t.title}</h3><div class="meta">${t.year} · ${t.type} · Illustrative title</div><div class="provider">${t.platform} · Sample listing</div><div class="audio">Audio: ${t.audio.join(' · ')}<br>Subtitles: Unverified</div></div>`;
    card.querySelector('button').onclick = () => {
      saved.has(t.id) ? saved.delete(t.id) : saved.add(t.id);
      persist('ottscout-watchlist', saved);
      render();
    };
    return card;
  }));
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
