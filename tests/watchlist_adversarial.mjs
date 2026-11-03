import assert from 'node:assert/strict';
import { test } from 'node:test';
import { WatchlistSync } from '../web/watchlist-sync.js';

const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const row = (id, saved, seconds = 1793650000) => ({
  id, data: { titleId: id, saved, updatedAt: { seconds, nanoseconds: 0 } },
});

function storage(uids = ['A']) {
  const map = new Map([['ottscout-watchlist', '["motn:guest"]']]);
  for (const uid of uids) map.set('ottscout-account-watchlist-v1:' + uid, JSON.stringify({
    version: 1, uid, records: [], pending: [], imported: true, deleting: false,
  }));
  return { map, getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key) };
}

// Snapshot delivery and commit acknowledgements are independent channels.
// Publish server state explicitly so tests can place a newer remote change
// before an older local write's acknowledgement.
function remote() {
  let next, error;
  const writes = [];
  let imports = 0;
  return {
    writes,
    get imports() { return imports; },
    subscribe(onNext, onError) { next = onNext; error = onError; return () => {}; },
    async importMissing() { imports++; },
    write(id, saved) {
      const completion = Promise.withResolvers();
      writes.push({ id, saved, resolve: completion.resolve, reject: completion.reject });
      return completion.promise;
    },
    emit(rows) { next(rows); },
    error() { error(new Error('offline')); },
  };
}

test('a late local acknowledgement cannot overwrite a newer authoritative remote snapshot', async () => {
  const local = storage();
  const api = remote();
  const model = new WatchlistSync(local);
  model.setUser('A', api);
  api.emit([row('motn:one', true, 1793650001)]);
  assert.equal(model.toggle('motn:one'), true);
  assert.equal(api.writes.length, 1);
  assert.equal(api.writes[0].saved, false);

  // Own removal committed, then another device saved it again. Its newer
  // snapshot arrives before the removal's delayed acknowledgement.
  api.emit([row('motn:one', false, 1793650002)]);
  api.emit([row('motn:one', true, 1793650003)]);
  api.writes[0].resolve();
  await tick();

  assert.equal(model.pending.size, 0);
  assert.equal(model.ids().has('motn:one'), true);
  assert.equal(JSON.parse(local.map.get(model.key())).records[0].saved, true);
});

test('acknowledging an earlier toggle preserves the newer pending intent until its own commit', async () => {
  const model = new WatchlistSync(storage());
  const api = remote();
  model.setUser('A', api);
  api.emit([row('motn:one', false)]);
  model.toggle('motn:one');
  model.toggle('motn:one');

  api.emit([row('motn:one', true, 1793650001)]);
  api.writes[0].resolve();
  await tick();
  assert.equal(model.ids().has('motn:one'), false);
  assert.equal(model.pending.size, 1);
  assert.equal(api.writes.length, 2);
  assert.equal(api.writes[1].saved, false);

  api.emit([row('motn:one', false, 1793650002)]);
  api.writes[1].resolve();
  await tick();
  assert.equal(model.pending.size, 0);
  assert.equal(model.ids().has('motn:one'), false);
});

test('old account callbacks and rejected writes cannot alter a newer account or its active queue', async () => {
  const local = storage(['A', 'B']);
  const a = remote(), b = remote();
  const model = new WatchlistSync(local);
  model.setUser('A', a);
  a.emit([row('motn:A', true)]);
  model.toggle('motn:pending-A');
  model.setUser('B', b);
  b.emit([row('motn:B', true)]);
  model.toggle('motn:pending-B');

  a.emit([row('motn:late-A', true)]);
  a.error();
  a.writes[0].reject(new Error('old session failed'));
  await tick();
  assert.equal(model.uid, 'B');
  assert.equal(model.busy, true);
  assert.equal(model.pending.size, 1);
  assert.equal(model.status, 'syncing');
  assert.deepEqual([...model.ids()].sort(), ['motn:B', 'motn:pending-B']);
  assert.equal(local.map.get('ottscout-watchlist'), '["motn:guest"]');

  b.emit([row('motn:B', true), row('motn:pending-B', true)]);
  b.writes[0].resolve();
  await tick();
  assert.equal(model.pending.size, 0);
  assert.equal(model.status, 'synced');
});

test('deletion state survives offline restart and ignores late snapshots and write acknowledgements', async () => {
  const local = storage();
  const api = remote();
  let state;
  const model = new WatchlistSync(local, value => { state = value; });
  model.setUser('A', api);
  api.emit([row('motn:one', true)]);
  model.toggle('motn:one');
  model.markDeletionPending();
  api.emit([row('motn:late', true)]);
  api.writes[0].resolve();
  await tick();
  assert.equal(state.status, 'deletion-pending');
  assert.equal(model.pending.size, 0);
  assert.deepEqual([...model.ids()], []);
  assert.equal(model.toggle('motn:new'), false);
  assert.equal(JSON.parse(local.map.get(model.key())).deleting, true);

  const reopenedApi = remote();
  const reopened = new WatchlistSync(local, value => { state = value; });
  reopened.setUser('A', reopenedApi);
  reopenedApi.error();
  reopenedApi.emit([row('motn:late', true)]);
  assert.equal(reopened.toggle('motn:new'), false);
  assert.equal(state.status, 'deletion-pending');
  assert.equal(reopenedApi.imports, 0);
  assert.equal(reopenedApi.writes.length, 0);
  assert.equal(local.map.get('ottscout-watchlist'), '["motn:guest"]');
});
