/* The only script anyone without a session is sent.
 *
 * The server hands this page, and nothing else, to a browser it does not
 * know. It does one of three things:
 *
 *   /login#<token>   spends a login link and signs this browser in for good
 *   a kept session   is handed back when the cookie that carries it has gone
 *                    (a browser drops a cookie 400 days after it was set)
 *   anything else    leaves for Google, which is all a stranger ever sees
 *
 * Except in the app installed on a phone's home screen, which has no address
 * bar to open a link in, and on iPhone keeps its own cookies apart from
 * Safari's — so being signed in in the browser does not sign it in. There
 * the link is pasted instead. A stranger never gets that far: to install the
 * app they would have had to open it, and opening it sent them to Google.
 *
 * The token is the part of the link after the #, which a browser never sends
 * anywhere. A chat app fetching the link to draw a preview asks for /login
 * and gets this page with nothing in it to spend, so the preview cannot use
 * the link up before the person it was sent to has opened it.
 */

const AWAY = 'https://www.google.com/';
const KEPT = 'mt.session.v1';
const RESUMED = 'mt.gate.resumed';

const leave = () => location.replace(AWAY);

function kept() {
  try { return localStorage.getItem(KEPT) || ''; } catch { return ''; }
}

function keep(token) {
  try { localStorage.setItem(KEPT, token); } catch { /* private mode: the cookie still works */ }
}

async function post(path, body) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

/** The link's token, taken out of the address bar before anything else. */
function takeLink() {
  const raw = location.hash.slice(1);
  if (raw) history.replaceState(null, '', location.pathname + location.search);
  return /^[A-Za-z0-9_-]{20,128}$/.test(raw) ? raw : '';
}

/* A page being got ready out of sight — a prerender, a preview drawn in a
 * hidden view — is not somebody opening the link. It is spent only once it
 * is on screen. */
function onScreen() {
  return new Promise((resolve) => {
    if (document.visibilityState === 'visible') { resolve(); return; }
    const look = () => {
      if (document.visibilityState !== 'visible') return;
      document.removeEventListener('visibilitychange', look);
      resolve();
    };
    document.addEventListener('visibilitychange', look);
  });
}

/* Whether this tab handed a session back within the last minute. If it did,
 * and the server has taken it back again and still sent this page, the
 * browser is not keeping the cookie — and asking again would go round for
 * ever. A session that has been removed is refused, and that is Google. */
function justResumed() {
  try { return Date.now() - Number(sessionStorage.getItem(RESUMED) || 0) < 60000; }
  catch { return false; }
}

function noteResumed() {
  try { sessionStorage.setItem(RESUMED, String(Date.now())); } catch { /* no storage */ }
}

/* Plain light page, drawn by hand: the app's stylesheet is not for strangers. */
function page(...nodes) {
  const body = document.body;
  for (const [key, value] of Object.entries({
    margin: '0', padding: '28px 20px', background: '#f6f7fb', color: '#131a24',
    font: '16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  })) body.style.setProperty(key, value);
  body.replaceChildren(...nodes);
}

function node(tag, text, style = {}) {
  const made = document.createElement(tag);
  if (text) made.textContent = text;
  for (const [key, value] of Object.entries(style)) made.style.setProperty(key, value);
  return made;
}

/* Only ever shown to someone the server has just said is signed in. */
function explain() {
  page(node('p', 'This browser is not keeping cookies for this site, so it cannot stay '
    + 'signed in. Allow cookies for it, then reload.'));
}

const installed = () => matchMedia('(display-mode: standalone)').matches
  || navigator.standalone === true;

/* The installed app, not signed in: somewhere to paste the link. */
function askForLink() {
  const box = node('input', '', {
    display: 'block', width: '100%', 'box-sizing': 'border-box', margin: '10px 0',
    padding: '12px', 'font-size': '16px', border: '1px solid #d6dee9', 'border-radius': '12px',
    background: '#fff', color: '#131a24',
  });
  Object.assign(box, { type: 'text', autocomplete: 'off', spellcheck: false,
    placeholder: 'https://…/login#…' });
  box.setAttribute('autocapitalize', 'none');
  box.setAttribute('aria-label', 'Login link');
  const go = node('button', 'Sign in', {
    padding: '12px 20px', 'font-size': '16px', 'font-weight': '600', border: '0',
    'border-radius': '12px', color: '#fff', background: '#0b8f7a',
  });
  const said = node('p', '', { color: '#4d5b70', 'font-size': '14px' });
  const submit = async () => {
    const token = (box.value.trim().match(/([A-Za-z0-9_-]{20,128})$/) || [])[1] || '';
    go.disabled = true;
    const got = token ? await post('/api/auth/redeem', { token }) : null;
    if (got && got.token) { keep(got.token); location.replace('/'); return; }
    go.disabled = false;
    said.textContent = 'That link has been used or has lapsed. Ask for a new one.';
  };
  go.addEventListener('click', submit);
  box.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });
  page(
    node('p', 'Paste the login link you were sent. It signs this app in for good.', { margin: '0' }),
    box, go, said);
}

async function main() {
  const atLogin = location.pathname === '/login';
  const link = atLogin ? takeLink() : '';
  if (link) {
    await onScreen();
    const got = await post('/api/auth/redeem', { token: link });
    if (got && got.token) {
      keep(got.token);
      location.replace('/');
      return;
    }
    // Spent, or lapsed. This browser may be signed in already, though — the
    // same link opened a second time — so that is asked next.
  }

  const token = kept();
  if (token || atLogin) {
    const got = await post('/api/auth/resume', token ? { token } : {});
    if (got) {
      // Taken back a moment ago as well, and still sent here: the session is
      // fine and the cookie is what is not being kept.
      if (!atLogin && justResumed()) { explain(); return; }
      noteResumed();
      location.replace(atLogin ? '/' : location.pathname + location.search);
      return;
    }
  }
  if (installed()) { askForLink(); return; }
  leave();
}

main();
