// A recommendation contains only a public catalogue ID. It is not an inbox,
// an authenticated sender claim, or permission to write a friend's watchlist.
export const validRecommendationId = value => typeof value === 'string' && value.length <= 160 && /^motn:[A-Za-z0-9-]+$/.test(value);

export function parseRecommendationRequest(value, allowLocalPreview = false) {
  try {
    if (typeof value !== 'string' || value.length > 8192) return {kind:'invalid'};
    const url = new URL(value);
    const ids = url.searchParams.getAll('recommend');
    if (!ids.length) return {kind:'none'};
    const local = allowLocalPreview && url.protocol === 'http:' && ['localhost','127.0.0.1'].includes(url.hostname);
    if (url.username || url.password || url.hash || url.pathname !== '/' || (!local && (url.protocol !== 'https:' || url.hostname !== 'ottscout.techiwithhelmet.com' || url.port))) return {kind:'invalid'};
    return ids.length === 1 && validRecommendationId(ids[0]) ? {kind:'title',id:ids[0]} : {kind:'invalid'};
  } catch { return {kind:'invalid'}; }
}

export function recommendationAppLink(id) {
  return validRecommendationId(id) ? 'ottscout://recommend/' + encodeURIComponent(id) : null;
}

export function resolveRecommendation(request, {ready, catalogue}) {
  if (request.kind !== 'title') return {status:request.kind};
  if (!ready) return {status:'loading'};
  const title = catalogue?.titles?.find(row => row.id === request.id);
  return title ? {status:'ready',title} : {status:'unavailable'};
}

/** All writes use the receiver's current session, after their explicit click. */
export async function approveRecommendation(id, {getState, write}) {
  if (!validRecommendationId(id)) return {status:'failed',message:'This recommendation link is invalid.'};
  const before = getState();
  if (before.reason || before.canSave === false) return {status:'blocked',message:before.reason || 'Your watchlist is not ready. Please try again.'};
  if (before.ids.has(id)) return {status:'already-saved',uid:before.uid};
  try {
    const changed = await write(id,before.uid);
    const after = getState();
    if (after.uid !== before.uid) return {status:'changed',message:'Your account changed. Review this recommendation again before saving.'};
    if (!changed || !after.ids.has(id)) return {status:'failed',message:after.reason || 'This title could not be saved. Your recommendation is still here; please try again.'};
    return {status:'approved',uid:before.uid};
  } catch {
    return {status:'failed',message:'This title could not be saved. Your recommendation is still here; please try again.'};
  }
}

/** Accessible inline review; opening a link never changes saved titles. */
export function mountRecommendation(root, ports) {
  const request = parseRecommendationRequest(ports.url,ports.allowLocalPreview === true);
  if (request.kind === 'none') return {refresh() {}};
  const field = id => root.querySelector('#' + id);
  const title = field('recommendation-title'), description = field('recommendation-description');
  const metadata = field('recommendation-meta'), image = field('recommendation-poster');
  const approve = field('recommendation-approve'), decline = field('recommendation-decline');
  const open = field('recommendation-app'), feedback = field('recommendation-feedback');
  let closed = false, busy = false, focused = false, notice = '', noticeError = false, noticeUid, posterFailed = '';
  function tell(message, error = false) {
    notice = message; noticeError = error;
    feedback.setAttribute('role',error ? 'alert' : 'status'); feedback.textContent = message;
  }
  function refresh() {
    if (closed) return;
    const resolved = resolveRecommendation(request,ports.getCatalogue());
    root.hidden = false;
    const ready = resolved.status === 'ready';
    approve.hidden = open.hidden = metadata.hidden = !ready;
    image.hidden = true;
    decline.disabled = busy;
    decline.textContent = ready || resolved.status === 'loading' ? 'Decline' : 'Close recommendation';
    if (!ready) {
      title.textContent = resolved.status === 'loading' ? 'Loading this recommendation…' : resolved.status === 'invalid' ? 'Invalid recommendation link' : 'Title not available';
      description.textContent = resolved.status === 'loading' ? 'Checking the loaded India catalogue.' : resolved.status === 'invalid' ? 'This link does not contain a valid OTTScout title.' : 'This title is not in the loaded catalogue. It may have been removed, or the latest catalogue may be unavailable.';
      return;
    }
    const row = resolved.title, state = ports.getState();
    title.textContent = row.title;
    metadata.textContent = [row.type,Number.isInteger(row.year) ? String(row.year) : '',row.originalLanguage ? row.originalLanguage + ' original' : 'Original language unverified'].filter(Boolean).join(' · ');
    description.textContent = 'Add this recommendation to your own watchlist, or decline. Your choice is private; it is not sent back to the person who shared the link.';
    open.href = recommendationAppLink(row.id);
    try {
      const poster = new URL(row.poster);
      if (poster.protocol === 'https:' && !poster.username && !poster.password && poster.href !== posterFailed) { if(image.src !== poster.href)image.src = poster.href; image.hidden = false; }
    } catch { /* The title is enough when artwork is unavailable. */ }
    const isSaved = state.ids.has(row.id);
    if (isSaved) decline.textContent = 'Close recommendation';
    approve.disabled = busy || isSaved || Boolean(state.reason) || state.canSave === false;
    approve.textContent = busy ? 'Saving…' : isSaved ? 'Already in your watchlist' : 'Add to my watchlist';
    approve.setAttribute('aria-describedby','recommendation-feedback');
    if (noticeUid !== undefined && noticeUid !== state.uid) { notice = ''; noticeError = false; noticeUid = undefined; }
    feedback.setAttribute('role',noticeError ? 'alert' : 'status');
    feedback.textContent = notice || state.reason || (isSaved ? 'This title is already saved. Nothing will be removed.' : state.uid ? 'Saving uses the account currently signed in on this page.' : 'Guest saves stay in this browser. Sign in from the header to sync across devices.');
    if (!focused) {
      focused = true;
      const doc = root.ownerDocument;
      if (doc.activeElement === doc.body) title.focus();
    }
  }
  approve.onclick = async () => {
    if (closed || busy || approve.disabled) return;
    const resolved = resolveRecommendation(request,ports.getCatalogue());
    if (resolved.status !== 'ready') return;
    busy = true; notice = ''; noticeError = false; refresh();
    const result = await approveRecommendation(resolved.title.id,ports);
    busy = false;
    if (closed) return;
    if (result.status === 'approved' || result.status === 'already-saved') {
      noticeUid = result.uid;
      tell(result.status === 'already-saved' ? 'This title is already in your watchlist. Nothing was changed.' : result.uid ? 'Added to your watchlist on this device. Your account will sync when connected.' : 'Added to your guest watchlist in this browser.');
      ports.onSaved?.();
    } else tell(result.message,true);
    refresh();
  };
  decline.onclick = () => {
    if (busy || closed) return;
    closed = true; root.hidden = true;
    ports.onClose?.();
  };
  image.onerror = () => { posterFailed = image.src; image.hidden = true; };
  refresh();
  return {refresh};
}
