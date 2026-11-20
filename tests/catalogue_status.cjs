const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('web/catalogue-status.js', 'utf8');
const now = Date.parse('2026-11-20T18:00:00Z');
function fixture(evaluated) {
  let clock = now, interval;
  const heading = {textContent: 'Updates are within the current target'};
  const explanation = {textContent: 'Earlier report'};
  const report = {dataset: {statusEvaluated: String(evaluated / 1000)}};
  vm.runInNewContext(code, {Date: {now: () => clock}, Number,
    document: {querySelector: () => report, getElementById: id => id === 'freshness-heading' ? heading : explanation},
    window: {setInterval: callback => {interval = callback;}}});
  return {heading, explanation, advance: milliseconds => {clock += milliseconds; interval();}};
}
const current = fixture(now - 3600000);
assert.equal(current.heading.textContent, 'Updates are within the current target');
current.advance(8 * 3600000);
assert.equal(current.heading.textContent, 'The status check is overdue');
assert.equal(fixture(now - 9 * 3600000).heading.textContent, 'The status check is overdue');
assert.equal(fixture(now + 600000).heading.textContent, 'The status check is overdue');
assert.equal(fixture(0).heading.textContent, 'The status check is overdue');
console.log('Public status cannot remain healthy after its report expires.');
