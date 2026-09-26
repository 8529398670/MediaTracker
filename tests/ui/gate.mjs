/* The gate: the one page a browser without a session is ever given.
 *
 * Each case loads a fresh copy of gate.js into a browser that is in one
 * particular state — a stranger, a login link, a kept session, a removed
 * one, the app installed on a phone — and watches where it sends it. The
 * server is stubbed; what is under test is which way the page goes.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const AWAY = 'https://www.google.com/';
const GOOD_LINK = 'L'.repeat(43);
const GOOD_SESSION = 'S'.repeat(43);
const NEW_SESSION = 'N'.repeat(43);

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};
const tick = (ms = 40) => new Promise((r) => setTimeout(r, ms));

const store = () => ({
  _d: {}, getItem(k) { return this._d[k] ?? null; }, setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
});

let run = 0;
/** One page load of the gate, in a browser set up the way `state` says. */
async function visit({ path = '/', hash = '', kept = '', live = [GOOD_SESSION], links = [GOOD_LINK],
                       installed = false, resumedAgo = null, cookie = false }) {
  const calls = [];
  const went = [];
  globalThis.location = {
    pathname: path, search: '', hash,
    replace(url) { went.push(url); },
  };
  globalThis.history = { replaceState(_s, _t, url) { location.hash = ''; calls.push(`replaceState ${url}`); } };
  globalThis.localStorage = store();
  globalThis.sessionStorage = store();
  if (kept) localStorage.setItem('mt.session.v1', kept);
  if (resumedAgo !== null) sessionStorage.setItem('mt.gate.resumed', String(Date.now() - resumedAgo));
  globalThis.matchMedia = () => ({ matches: installed });
  Object.defineProperty(globalThis, 'navigator', { value: { onLine: true }, configurable: true });
  document.visibilityState = 'visible';
  document.body.replaceChildren();
  globalThis.fetch = async (url, init) => {
    const body = JSON.parse(init.body || '{}');
    calls.push(`POST ${url}`);
    const reply = (status, payload) => ({ ok: status < 400, status, json: async () => payload });
    if (url === '/api/auth/redeem') {
      return links.includes(body.token) ? reply(200, { token: NEW_SESSION, name: 'Alice' })
        : reply(401, { error: 'spent' });
    }
    if (url === '/api/auth/resume') {
      if (body.token && live.includes(body.token)) return reply(200, { name: 'Alice' });
      if (!body.token && cookie) return reply(200, { name: 'Alice' });
      return reply(401, { error: 'no' });
    }
    return reply(404, {});
  };
  run += 1;
  await import(`./gate.js?${run}`);
  await tick();
  return { went, calls, kept: localStorage.getItem('mt.session.v1'), page: document.body.text() };
}

/* ------------------------------------------------------------- strangers */

let seen = await visit({});
check('a stranger is sent to Google', seen.went, [AWAY]);
check('  without asking the server anything', seen.calls, []);

seen = await visit({ path: '/login' });
check('a stranger at the login page, no link: Google', seen.went, [AWAY]);

seen = await visit({ path: '/login', hash: `#${'x'.repeat(43)}` });
check('a made-up link: Google', seen.went, [AWAY]);
check('  and the token is taken out of the address bar first', seen.calls[0], 'replaceState /login');

seen = await visit({ path: '/', hash: `#${GOOD_LINK}` });
check('a token anywhere but /login is not spent', [seen.went, seen.calls.includes('POST /api/auth/redeem')],
  [[AWAY], false]);

/* ------------------------------------------------------------ a link */

seen = await visit({ path: '/login', hash: `#${GOOD_LINK}` });
check('a good link signs this browser in and opens the app', seen.went, ['/']);
check('  keeping the session for later', seen.kept, NEW_SESSION);

seen = await visit({ path: '/login', hash: `#${GOOD_LINK}`, links: [], cookie: true });
check('a spent link, in a browser already signed in: the app', seen.went, ['/']);

seen = await visit({ path: '/login', hash: `#${GOOD_LINK}`, links: [], kept: 'D'.repeat(43), live: [] });
check('a spent link, and nothing kept that still works: Google', seen.went, [AWAY]);

/* ----------------------------------------------------------- kept copy */

seen = await visit({ path: '/', kept: GOOD_SESSION });
check('a lost cookie is put back from the kept session', seen.went, ['/']);
check('  by asking with it', seen.calls, ['POST /api/auth/resume']);

seen = await visit({ path: '/', kept: 'R'.repeat(43), live: [] });
check('a kept session that was removed: Google', seen.went, [AWAY]);
check('  and it stays kept — a restored backup may make it good again', seen.kept, 'R'.repeat(43));

seen = await visit({ path: '/', kept: 'R'.repeat(43), live: [], resumedAgo: 5000 });
check('removed a moment after it was put back: still Google, not a cookie warning', seen.went, [AWAY]);

seen = await visit({ path: '/', kept: GOOD_SESSION, resumedAgo: 5000 });
check('put back twice in a minute: the cookie is not being kept, so it says so',
  [seen.went, /not keeping cookies/.test(seen.page)], [[], true]);

/* ----------------------------------------------------- installed app */

seen = await visit({ path: '/', installed: true });
check('the installed app, not signed in, asks for the link', [seen.went, /Paste the login link/.test(seen.page)],
  [[], true]);
const box = document.body.find((n) => n.tagName === 'INPUT')[0];
const go = document.body.find((n) => n.tagName === 'BUTTON')[0];
box.value = `https://tracker.example/login#${GOOD_LINK}`;
go.fire('click');
await tick();
check('  and a pasted link signs it in', [seen.went, localStorage.getItem('mt.session.v1')], [['/'], NEW_SESSION]);

seen = await visit({ path: '/', installed: true });
document.body.find((n) => n.tagName === 'INPUT')[0].value = 'not a link';
document.body.find((n) => n.tagName === 'BUTTON')[0].fire('click');
await tick();
check('  a paste that is not a link says so and stays put',
  [seen.went, /has been used or has lapsed/.test(document.body.text())], [[], true]);

if (failures) { console.log(`\n${failures} FAILED`); process.exit(1); }
console.log('\nall passed');
