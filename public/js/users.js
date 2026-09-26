/* Who can get in: the people, and the one-time links that let them.
 *
 * Nobody reaches the app without a session, and the only way to get one is a
 * link made here and opened once. Everybody signed in can do all of it — add
 * someone, remove someone, make anyone a link — so it is in the menu for
 * everyone rather than behind a role nobody has. */

import { api, state, sync, forgetLocal } from './store.js';
import {
  el, icon, openSheet, toast, field, fmtAgo, confirmSheet, copyText, setChildren,
} from './ui.js';

const KEPT = 'mt.session.v1';           // the copy gate.js keeps of the session
const AWAY = 'https://www.google.com/';

/** Where a link is sent from: the tunnel's address when there is one, since
 * the person it is for is rarely on this wifi. */
function linkUrl(made) {
  return made.url || `${location.origin}${made.path}`;
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** "active now" for the last minute — yourself, mostly — then "3 days ago". */
const active = (iso) => (Date.now() - new Date(iso).getTime() < 60000
  ? 'active now' : `active ${fmtAgo(iso)}`);

/* ------------------------------------------------------------------ sheet */

export function openUsers() {
  const listBox = el('div.user-list', null,
    el('div.center-note', null, [el('div.spinner'), 'Loading…']));
  const name = el('input.input', {
    type: 'text', placeholder: 'Their name', maxLength: 32, autocomplete: 'off',
    spellcheck: false, enterkeyhint: 'go', 'aria-label': 'Name of the person to add',
  });
  const add = el('button.btn.primary', { type: 'button', text: 'Add' });
  const out = el('button.btn.sm.danger', { type: 'button' }, [icon('x'), 'Sign out of this browser']);

  let people = [];
  let mine = '';

  async function load() {
    try {
      const got = await api('GET', '/auth/users');
      people = got.users || [];
      mine = got.me || '';
      setChildren(listBox, people.map(row));
    } catch (err) {
      setChildren(listBox, el('p.hint', { text: err.message || 'Could not load the people' }));
    }
  }

  function row(person) {
    const isMe = person.id === mine;
    const meta = [person.devices
      ? `signed in on ${plural(person.devices, 'browser', 'browsers')}`
      : 'not signed in yet'];
    if (person.seenAt) meta.push(active(person.seenAt));

    const link = el('button.btn.sm', {
      type: 'button', 'aria-label': `New login link for ${person.name}`,
    }, [icon('link'), 'Login link']);
    link.addEventListener('click', () => makeLink(person, link));

    // You cannot take yourself out: somebody else has to, which is also what
    // stops the last person in from locking everybody out by accident.
    const drop = isMe ? null : el('button.icon-btn', {
      type: 'button', 'aria-label': `Remove ${person.name}`, title: `Remove ${person.name}`,
      onclick: () => removePerson(person),
    }, icon('trash'));

    const pending = person.links.map((made) => el('div.user-pending', null, [
      el('span', {
        text: `Unused link, made ${fmtAgo(made.createdAt)} · stops working ${fmtAgo(made.expiresAt)}`,
      }),
      el('button.btn.sm.ghost', {
        type: 'button', text: 'Cancel', 'aria-label': `Cancel the unused link for ${person.name}`,
        onclick: () => cancelLink(made),
      }),
    ]));

    return el('div.user-row', { dataset: { id: person.id } }, [
      el('div.user-top', null, [
        el('div.user-main', null, [
          el('div.user-name', null, [
            el('span', { text: person.name }),
            isMe ? el('span.tag-badge', { text: 'you' }) : null,
          ]),
          el('div.card-meta', { text: meta.join(' · ') }),
        ]),
        el('div.user-actions', null, [link, drop]),
      ]),
      ...pending,
    ]);
  }

  async function addPerson() {
    const wanted = name.value.trim();
    if (!wanted) { name.focus(); return; }
    add.disabled = true;
    try {
      const got = await api('POST', '/auth/users', { name: wanted });
      name.value = '';
      await load();
      // Somebody is added to be let in, so the link comes straight up.
      if (got.link) showLink(got.user.name, got.link);
    } catch (err) {
      toast(err.message || 'Could not add them', { error: true });
    } finally {
      add.disabled = false;
    }
  }

  async function makeLink(person, button) {
    button.disabled = true;
    try {
      const made = await api('POST', `/auth/users/${encodeURIComponent(person.id)}/link`);
      await load();
      showLink(person.name, made);
    } catch (err) {
      toast(err.message || 'Could not make a link', { error: true });
    } finally {
      button.disabled = false;
    }
  }

  async function removePerson(person) {
    const where = !person.devices ? ''
      : person.devices === 1 ? `${person.name} is signed out of the browser they use, straight away. `
        : `${person.name} is signed out of all ${person.devices} browsers they use, straight away. `;
    const ok = await confirmSheet({
      title: `Remove ${person.name}?`,
      message: `${where}Any link made for them stops working. Nothing in the library changes.`,
      confirmLabel: 'Remove', danger: true,
    });
    if (!ok) return;
    try {
      await api('DELETE', `/auth/users/${encodeURIComponent(person.id)}`);
      toast(`${person.name} removed`);
    } catch (err) {
      toast(err.message || 'Could not remove them', { error: true });
    }
    load();
  }

  async function cancelLink(made) {
    try {
      await api('DELETE', `/auth/links/${encodeURIComponent(made.id)}`);
      toast('Link cancelled — it will not work now');
    } catch (err) {
      toast(err.message || 'Could not cancel it', { error: true });
    }
    load();
  }

  add.addEventListener('click', addPerson);
  name.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); addPerson(); }
  });
  out.addEventListener('click', signOut);

  openSheet({
    title: 'Users',
    body: [
      field('People', listBox),
      field('Add someone', el('div.row.user-add', null, [name, add]),
        'They get a login link straight away. Everyone here can do everything, '
        + 'adding and removing people included.'),
      el('div.divider'),
      out,
    ],
  });
  load();
}

/* ------------------------------------------------------------------- link */

/* The link, once. Only its hash is kept on the server, so closing this is
 * the last anyone sees of it — another is a tap away. */
function showLink(name, made) {
  const url = linkUrl(made);
  const box = el('input.input.link-box', {
    type: 'text', readOnly: true, value: url, 'aria-label': `Login link for ${name}`,
  });
  box.addEventListener('focus', () => box.select());

  const copy = el('button.btn.primary.grow', { type: 'button' }, [icon('copy'), 'Copy']);
  copy.addEventListener('click', async () => {
    const ok = await copyText(url);
    if (!ok) { box.focus(); box.select(); }
    toast(ok ? `Copied — send it to ${name}` : 'Could not copy — select the link and copy it',
      { error: !ok });
  });

  // Only over https: a phone's share sheet is the easy way to send it.
  const share = navigator.share
    ? el('button.btn.grow', { type: 'button' }, [icon('upload'), 'Share…'])
    : null;
  share?.addEventListener('click', () => {
    navigator.share({ text: 'Your login link for Media Tracker. It works once.', url })
      .catch(() => { /* closed without sending */ });
  });

  openSheet({
    title: `Login link for ${name}`,
    body: [
      field('Send them this', box),
      el('p.hint', {
        text: `It works once: whoever opens it first is signed in as ${name} on that browser, `
            + `for good. Unopened, it stops working ${fmtAgo(made.expiresAt)}.`,
      }),
      el('p.hint', { text: 'Don’t open it yourself — it would sign this browser in as them.' }),
    ],
    footer: [share, copy],
  });
}

/* --------------------------------------------------------------- sign out */

async function signOut() {
  const ok = await confirmSheet({
    title: 'Sign out of this browser?',
    message: 'Getting back in takes a new login link from somebody who is signed in. '
      + 'The copy of the library kept in this browser is cleared.',
    confirmLabel: 'Sign out', danger: true,
  });
  if (!ok) return;
  // Whatever is still on its way to the server goes first: after this there
  // is no session to send it with.
  await sync();
  if (state.dirty) {
    toast('Some changes have not reached the server yet — try again once it is reachable',
      { error: true });
    return;
  }
  try {
    await api('POST', '/auth/logout');
  } catch (err) {
    toast(err.message || 'Could not sign out', { error: true });
    return;
  }
  forgetLocal();
  try { localStorage.removeItem(KEPT); } catch { /* nothing kept */ }
  location.replace(AWAY);
}
