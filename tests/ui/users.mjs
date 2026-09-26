/* The Users sheet, driven the way a person drives it.
 *
 * The server is stubbed: what is under test is the panel — that everyone is
 * listed and you are marked, that you are the one person with no remove
 * button, that a new person's link comes straight up, that a link is built on
 * the public address when there is one, and that removing somebody asks
 * first. And the store: a session that has gone sends the page back through
 * the gate, once, however many requests find out at the same time.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const calls = [];
let reloads = 0;
let copied = '';
globalThis.location = { origin: 'http://192.168.5.41:8674', reload() { reloads += 1; }, replace() {} };
Object.defineProperty(globalThis, 'navigator', {
  value: { onLine: true, clipboard: { writeText: async (text) => { copied = text; } } },
  configurable: true,
});

const soon = new Date(Date.now() + 6 * 86400000).toISOString();
const people = () => ({
  me: 'u1',
  users: [
    { id: 'u1', name: 'Alice', devices: 2, seenAt: new Date().toISOString(), links: [] },
    { id: 'u2', name: 'Bob', devices: 0, seenAt: '', links: [
      { id: 'abcdef012345', createdAt: new Date().toISOString(), expiresAt: soon }] },
  ],
});

globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || 'GET';
  calls.push(`${method} ${url}${init && init.body ? ` ${init.body}` : ''}`);
  const reply = (status, body) => ({
    ok: status < 400, status, text: async () => JSON.stringify(body) });
  if (url === '/api/gone') return reply(401, { error: 'sign in first' });
  if (url === '/api/auth/users' && method === 'GET') return reply(200, people());
  if (url === '/api/auth/users' && method === 'POST') {
    const { name } = JSON.parse(init.body);
    return reply(201, { user: { id: 'u3', name },
      link: { id: 'l3', path: '/login#tokenthree', expiresAt: soon, url: '' } });
  }
  if (url === '/api/auth/users/u2/link') {
    return reply(201, { id: 'l2', path: '/login#tokentwo', expiresAt: soon,
      url: 'https://tracker.example/login#tokentwo' });
  }
  return reply(200, { ok: true });
};

const store = await import('./store.js');
const { openUsers } = await import('./users.js');
const host = document.getElementById('sheet-host');

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const find = (pred) => host.find(pred);
const button = (label) => find((n) => n.tagName === 'BUTTON'
  && (n.getAttribute('aria-label') === label || n.text() === label))[0];
const sheetTitle = () => (find((n) => n.tagName === 'H2')[0] || { textContent: '' }).textContent;

/* ------------------------------------------------------------- the list */

openUsers();
await tick();
const rows = find((n) => n.classList.has('user-row'));
check('everyone is listed', rows.map((r) => r.find((n) => n.classList.has('user-name'))[0].text()),
  ['Alice you', 'Bob']);
check('with where they are signed in', rows.map((r) => r.find((n) => n.classList.has('card-meta'))[0]
  .textContent.split(' · ')[0]), ['signed in on 2 browsers', 'not signed in yet']);
check('you are the one person who cannot be removed here',
  [Boolean(button('Remove Alice')), Boolean(button('Remove Bob'))], [false, true]);
check('a link nobody has opened shows, with a way to cancel it',
  Boolean(button('Cancel the unused link for Bob')), true);

/* --------------------------------------------------------- a new link */

button('New login link for Bob').fire('click');
await tick();
check('a new link comes up in a sheet of its own', sheetTitle(), 'Login link for Bob');
const box = find((n) => n.classList.has('link-box'))[0];
check('built on the public address when the server has one', box.value,
  'https://tracker.example/login#tokentwo');
button('Copy').fire('click');
await tick();
check('Copy copies the link whole', copied, 'https://tracker.example/login#tokentwo');
button('Close').fire('click');
check('closing it goes back to the list', sheetTitle(), 'Users');

/* ------------------------------------------------------ someone new */

const input = find((n) => n.tagName === 'INPUT' && n.getAttribute('aria-label') === 'Name of the person to add')[0];
input.value = '  Dana ';
button('Add').fire('click');
await tick();
check('adding someone sends their name', calls.filter((c) => c.startsWith('POST /api/auth/users '))
  .map((c) => JSON.parse(c.slice(c.indexOf('{'))).name), ['Dana']);
check('and their link comes straight up', sheetTitle(), 'Login link for Dana');
check('built on this address when there is no public one',
  find((n) => n.classList.has('link-box'))[0].value, 'http://192.168.5.41:8674/login#tokenthree');
check('the box is emptied for the next one', input.value, '');
button('Close').fire('click');

/* ------------------------------------------------------ taking out */

calls.length = 0;
button('Remove Bob').fire('click');
await tick();
check('removing somebody asks first', sheetTitle(), 'Remove Bob?');
check('  and nothing has gone yet', calls.filter((c) => c.startsWith('DELETE')), []);
button('Remove').fire('click');
await tick();
check('then they are removed', calls.filter((c) => c.startsWith('DELETE')), ['DELETE /api/auth/users/u2']);

calls.length = 0;
button('Cancel the unused link for Bob').fire('click');
await tick();
check('an unused link can be cancelled', calls.filter((c) => c.startsWith('DELETE')),
  ['DELETE /api/auth/links/abcdef012345']);

/* ---------------------------------------------------- a lost session */

const errors = await Promise.allSettled([store.api('GET', '/gone'), store.api('GET', '/gone')]);
check('a request after the session has gone fails', errors.map((e) => e.status), ['rejected', 'rejected']);
check('  and the page goes back through the gate, once', reloads, 1);

if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nall passed');
