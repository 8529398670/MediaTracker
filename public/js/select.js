/* Several titles at once.
 *
 * The tick-box button beside the filters (or `s`) turns every card into a
 * tick box: a tap picks it rather than opening it, and shift-click picks the
 * run between that card and the last one tapped. A bar along the bottom holds
 * the count and what can be done to all of them — mark them watched, skip
 * them, say what type they are, delete them, or stop. Every one of those asks
 * first and names what it is about to touch, and every change leaves an Undo.
 *
 * What is picked is a set of ids rather than of cards on screen, so it lasts
 * through a search, a filter or another tab: a pick can be gathered from
 * several places, and the bar says how much of it is out of sight. */

import {
  TYPES, TYPE_LABEL, getItem, patchMany, checkpoint, statusFields, nowISO,
} from './store.js';
import { el, icon, openSheet, toast, confirmSheet, setChildren } from './ui.js';
import { SECTION_LABEL, sectionOf } from './filters.js';

export const picking = { on: false, ids: new Set(), anchor: '' };

/* The page this runs on: the list the cards are in, the bar, the button that
 * starts it, and what to call when the library has been changed. */
const page = { list: null, bar: null, button: null, changed: () => {} };
const bar = { count: null, note: null, all: null, acts: [] };

let shown = [];       // ids of the list on screen, as the last paint drew it
let away = false;     // Discover is up: the pick waits, out of the way
let marked = false;   // whether any card on the page carries the mark

const count = (n) => `${n} ${n === 1 ? 'title' : 'titles'}`;

export const isPicked = (item) => picking.on && picking.ids.has(item.id);

/** What is picked and still in the library, in the order it was picked. */
export function pickedItems() {
  const out = [];
  for (const id of picking.ids) {
    const item = getItem(id);
    if (item && !item.deleted) out.push(item);
  }
  return out;
}

/* ------------------------------------------------------------- the pick */

export function startPicking() {
  picking.on = true;
  picking.anchor = '';
  refresh();
}

/* Leaving lets the pick go. With nothing picked there is nothing to lose, so
 * it goes at once; with something picked it asks, like everything else here. */
export async function stopPicking({ ask = true } = {}) {
  if (!picking.on) return true;
  const n = pickedItems().length;
  if (ask && n) {
    const ok = await confirmSheet({
      title: 'Stop selecting?',
      message: `The ${count(n)} you picked will be let go. Nothing about them changes.`,
      confirmLabel: 'Stop selecting',
      cancelLabel: 'Keep selecting',
    });
    if (!ok) return false;
  }
  picking.on = false;
  picking.ids.clear();
  picking.anchor = '';
  refresh();
  return true;
}

/** Pick one, or let it go. With `range`, everything between it and the one
 * tapped before it — in `order`, the cards as the page lists them — goes the
 * same way as it does. */
export function pick(id, { range = false, order = null } = {}) {
  if (!picking.on || !id) return;
  const want = !picking.ids.has(id);
  let run = [id];
  if (range && picking.anchor && order) {
    const from = order.indexOf(picking.anchor);
    const to = order.indexOf(id);
    if (from !== -1 && to !== -1) run = order.slice(Math.min(from, to), Math.max(from, to) + 1);
  }
  for (const one of run) {
    if (want) picking.ids.add(one); else picking.ids.delete(one);
  }
  picking.anchor = id;
  refresh();
}

export function pickAll(ids) {
  if (!picking.on) return;
  for (const id of ids) picking.ids.add(id);
  refresh();
}

export function unpickAll() {
  picking.ids.clear();
  picking.anchor = '';
  refresh();
}

/* ------------------------------------------------------------ the doing */

/* A change to many titles at once, with the way back. What each field held
 * before is kept, so Undo is a patch as well — it survives the fill-in pass
 * writing in between, where putting a whole snapshot back would lose to it.
 * The snapshot is taken too, for "Undo last bulk change" in Sync & storage. */
function commit(label, patches, said) {
  if (!patches.length) return 0;
  const before = patches.map(([id, fields]) => {
    const item = getItem(id);
    return [id, Object.fromEntries(Object.keys(fields).map((key) => [key, item[key] ?? null]))];
  });
  checkpoint(label);
  const changed = patchMany(patches);
  picking.on = false;              // the job is done; nothing to ask about
  picking.ids.clear();
  picking.anchor = '';
  refresh();
  page.changed();
  toast(said, {
    ms: 9000,
    action: { label: 'Undo', fn: () => { patchMany(before); page.changed(); toast('Undone'); } },
  });
  return changed;
}

/** The picked titles, named: enough of them to see what is about to happen. */
function roll(items, max = 8) {
  const lines = items.slice(0, max).map((item) =>
    (item.year ? `${item.title} (${item.year})` : item.title) || 'Untitled');
  if (items.length > max) lines.push(`…and ${items.length - max} more`);
  return lines;
}

const STATUS_WORDS = {
  watched: {
    title: (n) => `Mark ${count(n)} as watched?`,
    message: 'They move to the Watched list.',
    already: 'watched',
    confirm: (n) => `Mark ${n} watched`,
    done: (n) => `${count(n)} marked watched`,
  },
  dropped: {
    title: (n) => `Skip ${count(n)}?`,
    message: 'They stay in the List, greyed out, and drop out of the Queue and Watched.',
    already: 'skipped',
    confirm: (n) => `Skip ${n}`,
    done: (n) => `${count(n)} skipped`,
  },
};

export async function markStatus(status) {
  const words = STATUS_WORDS[status];
  const items = pickedItems();
  const moving = items.filter((item) => item.status !== status);
  if (!moving.length) {
    toast(items.length ? `All of them are ${words.already} already` : 'Nothing is selected');
    return false;
  }
  const already = items.length - moving.length;
  const losing = status !== 'watched' && moving.some((item) => item.status === 'watched');
  const ok = await confirmSheet({
    title: words.title(moving.length),
    message: [
      words.message,
      losing ? 'The watched ones lose the day they were watched.' : '',
      already ? `${already} of the ${items.length} picked ${already === 1 ? 'is' : 'are'} `
        + `${words.already} already and ${already === 1 ? 'stays' : 'stay'} as ${already === 1 ? 'it is' : 'they are'}.` : '',
    ].filter(Boolean).join(' '),
    detail: roll(moving),
    confirmLabel: words.confirm(moving.length),
  });
  if (!ok) return false;
  commit(`mark ${count(moving.length)} ${words.already}`,
    moving.map((item) => [item.id, statusFields(item, status)]),
    words.done(moving.length));
  return true;
}

export async function remove() {
  const items = pickedItems();
  if (!items.length) { toast('Nothing is selected'); return false; }
  const ok = await confirmSheet({
    title: `Delete ${count(items.length)}?`,
    message: 'They will be removed from the library. You can undo right after.',
    detail: roll(items),
    confirmLabel: `Delete ${items.length}`,
    danger: true,
  });
  if (!ok) return false;
  const stamp = nowISO();
  commit(`delete ${count(items.length)}`,
    items.map((item) => [item.id, { deleted: true, deletedAt: stamp }]),
    `${count(items.length)} deleted`);
  return true;
}

/* Type is the one with a choice in it, so its question is a sheet of its
 * own: the types, how many of the pick are each one now, what the one chosen
 * would move where — and nothing happens until the button that says so. */
export function markType() {
  const items = pickedItems();
  if (!items.length) { toast('Nothing is selected'); return null; }

  const now = new Map();
  for (const item of items) now.set(item.type, (now.get(item.type) || 0) + 1);

  let chosen = '';
  const hint = el('p.hint');
  const cancel = el('button.btn.ghost.grow', { type: 'button', text: 'Cancel' });
  const go = el('button.btn.primary.grow', { type: 'button', text: 'Pick a type', disabled: true });

  const chips = el('div.chip-row.type-pick');
  for (const type of TYPES) {
    chips.append(el('button.chip.chip-toggle', {
      type: 'button', 'aria-pressed': 'false', dataset: { type: type.id },
      onclick: () => choose(type.id),
    }, [
      el('span', { text: type.label }),
      now.get(type.id) ? el('span.chip-count', { text: String(now.get(type.id)) }) : null,
    ]));
  }

  function choose(type) {
    chosen = type;
    for (const chip of chips.children) {
      chip.setAttribute('aria-pressed', String(chip.dataset.type === type));
    }
    const label = TYPE_LABEL[type] || type;
    const changing = items.filter((item) => item.type !== type);
    const section = sectionOf({ type });
    const moving = changing.filter((item) => sectionOf(item) !== section).length;
    go.disabled = !changing.length;
    go.textContent = changing.length ? `Mark ${changing.length} as ${label}` : 'Nothing to change';
    hint.textContent = !changing.length
      ? `${items.length === 1 ? 'It is' : `All ${items.length} are`} ${label} already.`
      : moving === changing.length
        ? `${changing.length === 1 ? 'It moves' : 'They move'} to ${SECTION_LABEL[section]}.`
        : moving
          ? `${moving} of them move to ${SECTION_LABEL[section]}.`
          : `${changing.length === 1 ? 'It stays' : 'They stay'} in ${SECTION_LABEL[section]}.`;
  }

  const handle = openSheet({
    title: `Mark ${count(items.length)} as…`,
    body: el('div', null, [
      chips,
      hint,
      el('ul.confirm-list', null, roll(items).map((line) => el('li', { text: line }))),
    ]),
    footer: [cancel, go],
  });

  cancel.addEventListener('click', () => handle.close());
  go.addEventListener('click', () => {
    if (!chosen) return;
    const label = TYPE_LABEL[chosen] || chosen;
    const section = sectionOf({ type: chosen });
    const changing = items.filter((item) => item.type !== chosen);
    handle.close();
    // A title that changes section arrives at the back of that section's
    // queue, the way a new one does, rather than at the place it held in the
    // queue it came from.
    commit(`mark ${count(changing.length)} as ${label}`,
      changing.map((item) => [item.id, sectionOf(item) === section
        ? { type: chosen } : { type: chosen, order: null }]),
      `${count(changing.length)} marked as ${label}`);
  });
  return handle;
}

/* ------------------------------------------------------------- the page */

/** Wire the pick to the page: the button that starts it, the bar along the
 * bottom, and the list whose cards turn into tick boxes. */
export function wirePicking({ list, barNode, button, changed }) {
  Object.assign(page, { list, bar: barNode, button, changed });
  buildBar(barNode);
  button.addEventListener('click', () => { if (picking.on) stopPicking(); else startPicking(); });

  // While picking, a card is one big tick box: whatever on it was pressed —
  // the poster, the year, a tag, a link — picks it, and nothing else happens.
  list.addEventListener('click', (event) => {
    if (!picking.on || away) return;
    const node = cardOf(event.target);
    if (!node) return;
    event.preventDefault();
    event.stopPropagation();
    pick(node.dataset.id, { range: event.shiftKey, order: event.shiftKey ? order() : null });
  }, true);

  // The keyboard's way to the same place. A button or a link turns Enter
  // into a click of its own, which the handler above takes.
  list.addEventListener('keydown', (event) => {
    if (!picking.on || away || (event.key !== 'Enter' && event.key !== ' ')) return;
    const node = cardOf(event.target);
    if (!node || event.target.closest('button, a')) return;
    event.preventDefault();
    event.stopPropagation();
    pick(node.dataset.id);
  }, true);
}

const cardOf = (target) => (target && target.closest
  ? target.closest('.card[data-id], .qrow[data-id]') : null);

/** Every card on the page, in the order the page lists them. */
function order() {
  const ids = [];
  for (const node of page.list.querySelectorAll('.card[data-id], .qrow[data-id]')) {
    if (!ids.includes(node.dataset.id)) ids.push(node.dataset.id);
  }
  return ids;
}

function buildBar(node) {
  bar.count = el('b.sel-count', { 'aria-live': 'polite' });
  bar.note = el('span.sel-note');
  bar.all = el('button.btn.sm.ghost.sel-all', {
    type: 'button',
    onclick: () => { if (allShownPicked()) unpickAll(); else pickAll(shown); },
  });
  const cancel = el('button.btn.sm.ghost.sel-cancel', {
    type: 'button', title: 'Stop selecting (Esc)', 'aria-label': 'Cancel',
    onclick: () => { stopPicking(); },
  }, [icon('x'), el('span', { text: 'Cancel' })]);

  const act = (id, iconName, label, title, fn, cls = '') => el('button.btn.sel-act', {
    type: 'button', class: cls, title, dataset: { act: id }, onclick: fn,
  }, [icon(iconName), el('span', { text: label })]);
  bar.acts = [
    act('watched', 'check', 'Watched', 'Mark them watched', () => markStatus('watched')),
    act('dropped', 'skip', 'Skipped', 'Mark them skipped', () => markStatus('dropped')),
    act('type', 'tag', 'Type', 'Mark them as a type — Movie, TV, Audio Book…', () => markType()),
    act('delete', 'trash', 'Delete', 'Delete them', () => remove(), 'danger'),
  ];

  // Flat, so one grid can lay it out as two rows on a phone and one on a desk.
  setChildren(node, [bar.count, bar.note, bar.all, cancel, el('div.sel-acts', null, bar.acts)]);
}

const allShownPicked = () => shown.length > 0 && shown.every((id) => picking.ids.has(id));

/** Called on every paint of the library: the ids the list on screen holds,
 * and whether Discover is up instead. */
export function paintPicking({ ids = shown, discover = away } = {}) {
  shown = ids;
  away = discover;
  refresh();
}

function refresh() {
  const on = picking.on && !away;
  const body = document.body;
  if (on) body.classList.add('selecting'); else body.classList.remove('selecting');
  if (page.button) {
    page.button.setAttribute('aria-pressed', String(picking.on));
    page.button.hidden = away;
  }
  if (page.bar) {
    page.bar.hidden = !on;
    if (on) paintBar();
  }
  syncMarks();
}

function paintBar() {
  const n = pickedItems().length;
  const here = new Set(shown);
  const hidden = pickedItems().filter((item) => !here.has(item.id)).length;
  bar.count.textContent = n ? `${n} selected` : 'Tap to select';
  bar.note.textContent = hidden ? `${hidden} not in this list` : '';
  const all = allShownPicked();
  bar.all.textContent = all ? 'Deselect all' : `Select all ${shown.length}`;
  bar.all.disabled = !all && !shown.length;
  for (const button of bar.acts) button.disabled = !n;
}

/* The mark on each card, put right after the pick changes. A card built
 * later reads it for itself (see `selected` in views.js). */
function syncMarks() {
  if (!page.list || !page.list.querySelectorAll) return;
  if (!picking.on && !marked) return;
  marked = false;
  for (const node of page.list.querySelectorAll('.card[data-id], .qrow[data-id]')) {
    const on = picking.on && picking.ids.has(node.dataset.id);
    if (on) { node.classList.add('is-selected'); marked = true; }
    else node.classList.remove('is-selected');
  }
}
