const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('web/home-freshness.js', 'utf8');
const now = 1795430487000;
const base = {schemaVersion: 1, evaluatedAt: now / 1000, status: 'normal', causes: []};

async function render(report, {fail = false, hang = false} = {}) {
  const notice = {hidden: false};
  const message = {textContent: 'initial'};
  const timers = new Map();
  let next = 0;
  const requests = [];
  const context = {
    document: {getElementById: id => ({'home-freshness': notice, 'home-freshness-message': message})[id]},
    Date: {now: () => now}, AbortController,
    fetch: async (url, options) => {
      requests.push({url, options});
      if (fail) throw new Error('offline');
      if (hang) return new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('timeout'))));
      return {ok: true, json: async () => report};
    },
    setTimeout: (fn, delay) => { const id = ++next; timers.set(id, {fn, delay}); return id; },
    clearTimeout: id => timers.delete(id),
  };
  vm.runInNewContext(source, context);
  await new Promise(resolve => setImmediate(resolve));
  return {notice, message, requests, timers};
}

test('current critical new-release delay is visible and links to a local report', async () => {
  const result = await render({...base, status: 'critical', causes: [{code: 'new_feed_stale', severity: 'critical'}]});
  assert.equal(result.notice.hidden, false);
  assert.match(result.message.textContent, /New-release updates are delayed/);
  assert.equal(result.requests.length, 1);
  assert.equal(result.requests[0].url, '/data/catalogue-health.json');
  assert.equal(result.requests[0].options.cache, 'no-store');
  const html = fs.readFileSync('index.html', 'utf8');
  assert.match(html, /id="home-freshness"[^>]*>[^]*?<a href="\/data-status\/">Check catalogue update status<\/a>[^]*?<\/div>/);
});

test('a stalled request times out and leaves the update status unconfirmed', async () => {
  const result = await render(base, {hang: true});
  const timeout = [...result.timers.values()].find(timer => timer.delay === 5000);
  assert.ok(timeout);
  timeout.fn();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(result.notice.hidden, false);
  assert.match(result.message.textContent, /can’t confirm/);
});

test('other warning does not falsely claim new releases are delayed', async () => {
  const {notice, message} = await render({...base, status: 'warning', causes: [{code: 'request_budget_low', severity: 'warning'}]});
  assert.equal(notice.hidden, false);
  assert.match(message.textContent, /checks need attention/);
  assert.doesNotMatch(message.textContent, /updates are delayed/);
});

test('a current healthy report hides the notice, then becomes unknown when it expires', async () => {
  const {notice, message, timers} = await render(base);
  assert.equal(notice.hidden, true);
  const expiry = [...timers.values()].find(timer => timer.delay > 5000);
  assert.ok(expiry, 'a healthy report must expire without a page reload');
  expiry.fn();
  assert.equal(notice.hidden, false);
  assert.match(message.textContent, /can’t confirm/);
});

test('old, malformed, inconsistent, and unavailable reports never look healthy', async () => {
  for (const report of [
    {...base, evaluatedAt: base.evaluatedAt - 8 * 3600 - 1},
    {...base, evaluatedAt: base.evaluatedAt + 301},
    {...base, evaluatedAt: String(base.evaluatedAt)},
    {...base, status: 'normal', causes: [{severity: 'critical'}]},
    {...base, status: 'normal', causes: [{}]},
    {...base, status: 'warning', causes: []},
    {...base, status: 'critical', causes: [{code: 'broken', severity: 'warning'}]},
    {...base, status: 'mystery'}, null,
  ]) {
    const {notice, message} = await render(report);
    assert.equal(notice.hidden, false);
    assert.match(message.textContent, /can’t confirm/);
  }
  const offline = await render(base, {fail: true});
  assert.equal(offline.notice.hidden, false);
  assert.match(offline.message.textContent, /can’t confirm/);
});
