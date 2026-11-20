const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Exercise the real account event handlers without connecting to Firebase.
const html = fs.readFileSync('index.html', 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
const nodes = new Map();
const document = {activeElement: null, querySelector(selector) { return nodes.get(selector.slice(1)) || null; }};
for (const id of ids) {
  const listeners = {};
  nodes.set(id, {
    id, hidden: false, value: '', textContent: '', attributes: {},
    addEventListener(type, fn) { listeners[type] = fn; },
    click() { listeners.click?.({target:this}); },
    focus() { document.activeElement = this; },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    removeAttribute(name) { delete this.attributes[name]; },
    querySelectorAll() { return []; },
  });
}
assert.ok(nodes.has('account-password-help'), 'Password help must exist in the actual dialog');
const context = vm.createContext({
  document, navigator: {}, localStorage: {},
  window: {addEventListener() {}, dispatchEvent() {}},
  WatchlistSync: class {}, AccountSession: class {},
  setTimeout, clearTimeout, URL, console,
});
const source = fs.readFileSync('web/account.js', 'utf8')
  .replace(/^import .*;\s*$/gm, '')
  .replace(/\nstart\(\);\s*$/, '\n');
vm.runInContext(source, context);
const node = id => nodes.get(id);
vm.runInContext('initialized = true; paint()', context);

// Going back hides the reset form first and returns focus to the visible email.
node('account-email-input').value = 'person@example.com';
node('account-forgot').click();
assert.equal(node('reset-email').value, 'person@example.com');
assert.equal(document.activeElement, node('reset-email'));
assert.equal(node('account-form').hidden, true);
node('account-reset-back').click();
assert.equal(node('account-form').hidden, false);
assert.equal(node('account-reset-form').hidden, true);
assert.equal(document.activeElement, node('account-email-input'));

// Signup help is visible, matches the client rule, and survives an error repaint.
assert.equal(node('account-password-help').hidden, true);
assert.equal(node('account-password').attributes['aria-describedby'], undefined);
node('account-switch').click();
assert.equal(node('account-password').minLength, 8);
assert.equal(node('account-password').autocomplete, 'new-password');
assert.equal(node('account-password-help').hidden, false);
assert.equal(node('account-password-help').textContent, `Use at least ${node('account-password').minLength} characters.`);
assert.equal(node('account-password').attributes['aria-describedby'], 'account-password-help');
vm.runInContext("message('Please try again.', true); paint()", context);
assert.equal(node('account-password-help').hidden, false);
assert.equal(node('account-password').attributes['aria-describedby'], 'account-password-help');
node('account-switch').click();
assert.equal(node('account-password').minLength, 1);
assert.equal(node('account-password-help').hidden, true);
assert.equal(node('account-password').attributes['aria-describedby'], undefined);
console.log('Account reset focus and password instructions passed.');
