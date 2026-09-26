/* Other's types: added, renamed and deleted.
 *
 * Other is everything that is not a film or a programme, and what it is split
 * into is yours to say. The six it started with — Anime, Documentary, Book,
 * Game, Audio Book, Other — are ordinary entries in the list and go the same
 * way as any added later. A type keeps its id for good, so a rename is a new
 * name on every card and chip and touches no title; a delete first asks where
 * its titles go. Each change is its own sheet whose button says exactly what
 * it will do, and each leaves an Undo behind it.
 *
 * Each type also says what it is looked up as, because the fill-in pass has
 * to ask somebody about "Stand-up Comedy", and no provider files anything
 * under that. */

import {
  TYPES, TYPE_LABEL, live, otherTypes, setOtherTypes, patchMany, checkpoint, lookupKind,
  fold,
} from './store.js';
import { el, icon, field, openSheet, toast, segmented, setChildren } from './ui.js';
import { sectionOf, SECTION_LABEL, pickedTypes, pickType } from './filters.js';

/* Where the fill-in pass goes for a type's artwork and details. */
const LOOKUPS = [
  { id: 'movie', label: 'Film' },
  { id: 'tv', label: 'TV' },
  { id: 'book', label: 'Book' },
  { id: 'podcast', label: 'Podcast' },
  { id: 'game', label: 'Game' },
  { id: 'other', label: 'Anything' },
];
// Two the starting list uses, read as the nearest choice above.
const SHOWN_AS = { anime: 'tv', doc: 'movie' };
const lookupName = (lookup) =>
  (LOOKUPS.find((l) => l.id === (SHOWN_AS[lookup] || lookup)) || LOOKUPS[5]).label;

const count = (n) => `${n} ${n === 1 ? 'title' : 'titles'}`;

/** Every type Other holds: the list's own, in order, and then any other type
 * a title still carries — a podcast a provider handed back, say. */
export function typeRows() {
  const tally = new Map();
  for (const item of live()) tally.set(item.type, (tally.get(item.type) || 0) + 1);
  const listed = otherTypes();
  const rows = listed.map((t) => ({ ...t, listed: true, count: tally.get(t.id) || 0 }));
  for (const [id, n] of tally) {
    if (id === 'movie' || id === 'tv' || listed.some((t) => t.id === id)) continue;
    rows.push({ id, label: TYPE_LABEL[id] || id, lookup: lookupKind(id), listed: false, count: n });
  }
  return rows;
}

/** A new type's id: its name as a slug no type in the list has. Named after a
 * type some titles already carry, it takes them in. */
export function newTypeId(label) {
  const base = fold(label).replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '')
    .replace(/-{2,}/g, '-').replace(/^-+|-+$/g, '').slice(0, 28) || 'type';
  const taken = new Set(['movie', 'tv', ...otherTypes().map((t) => t.id)]);
  let id = base;
  for (let n = 2; taken.has(id); n += 1) id = `${base}-${n}`;
  return id;
}

/* A first guess at the lookup from the name being typed, until one is chosen. */
function guessLookup(label) {
  const words = fold(label);
  if (/documentar|\bfilms?\b|\bmovies?\b|cinema/.test(words)) return 'movie';
  if (/\btv\b|series|\bshows?\b|sitcom|anime|cartoon/.test(words)) return 'tv';
  if (/audio ?books?|\bbooks?\b|novel|comic|manga/.test(words)) return 'book';
  if (/podcast|radio|audio/.test(words)) return 'podcast';
  if (/\bgames?\b/.test(words)) return 'game';
  return 'other';
}

const TAB_NAMES = new Set(['movie', 'movies', 'film', 'films', 'tv', 'tv shows']);

/* ------------------------------------------------------------ the sheet */

/** The list, with Rename and Delete on each type and Add at the foot. */
export function openTypes(onChange = () => {}) {
  const list = el('div.type-list');
  const floor = el('p.hint');

  const draw = () => {
    const rows = typeRows();
    const listed = rows.filter((row) => row.listed).length;
    setChildren(list, rows.map((row) => el('div.type-row', null, [
      el('div.type-main', null, [
        el('b', { text: row.label }),
        el('small', {
          text: [count(row.count), `looked up as ${lookupName(row.lookup)}`,
            row.listed ? '' : 'not in the list'].filter(Boolean).join(' · '),
        }),
      ]),
      el('button.btn.sm.ghost', {
        type: 'button', 'aria-label': `Rename ${row.label}`, title: 'Rename',
        onclick: () => editType(row, done),
      }, [icon('edit'), el('span', { text: 'Rename' })]),
      el('button.btn.sm.ghost.danger', {
        type: 'button', 'aria-label': `Delete ${row.label}`, title: 'Delete',
        disabled: row.listed && listed <= 1,
        onclick: () => deleteType(row, done),
      }, [icon('trash'), el('span', { text: 'Delete' })]),
    ])));
    floor.textContent = listed <= 1
      ? 'Other keeps at least one type — add another before deleting this one.' : '';
  };
  const done = () => { draw(); onChange(); };

  const add = el('button.btn.primary.grow', {
    type: 'button', onclick: () => editType(null, done),
  }, [icon('plus'), el('span', { text: 'Add a type' })]);

  draw();
  return openSheet({
    title: 'Types in Other',
    body: el('div', null, [
      el('p.hint.type-intro', {
        text: 'The chips on the Other tab and the choices in every Type menu. A rename '
            + 'changes the name everywhere and moves no title; a delete asks where its '
            + 'titles go first. Movies and TV are tabs of their own.',
      }),
      list,
      floor,
    ]),
    footer: [add],
  });
}

/** Add a type (`row` null), or rename one and change what it is looked up as. */
export function editType(row, done = () => {}) {
  const adding = !row;
  const name = el('input.input', {
    type: 'text', value: adding ? '' : row.label, maxLength: 40,
    placeholder: 'Stand-up Comedy', autocapitalize: 'words', 'data-autofocus': '',
    'aria-label': 'Name',
  });
  let lookup = adding ? 'other' : row.lookup;
  let chosen = !adding;              // whether the lookup was picked by hand
  const seg = el('div');
  const paintSeg = () => setChildren(seg, segmented(LOOKUPS, SHOWN_AS[lookup] || lookup, (v) => {
    lookup = v;
    chosen = true;
    check();
  }));
  const note = el('p.hint.type-clash');
  const cancel = el('button.btn.ghost.grow', { type: 'button', text: 'Cancel' });
  const go = el('button.btn.primary.grow', { type: 'button' });

  const wanted = () => name.value.trim().replace(/\s+/g, ' ').slice(0, 40);

  function check() {
    const want = wanted();
    if (adding && !chosen && guessLookup(want) !== lookup) {
      lookup = guessLookup(want);
      paintSeg();
    }
    const tab = TAB_NAMES.has(fold(want));
    const clash = want && !tab ? otherTypes().find((t) =>
      (adding || t.id !== row.id) && fold(t.label) === fold(want)) : null;
    const unchanged = !adding && row.listed && want === row.label && lookup === row.lookup;
    go.disabled = !want || tab || Boolean(clash) || unchanged;
    go.textContent = adding ? (want ? `Add “${want}”` : 'Add')
      : want && want !== row.label ? `Rename to “${want}”` : 'Save';
    note.textContent = tab ? 'Movies and TV are tabs of their own.'
      : clash ? `There is a “${clash.label}” already.` : '';
  }

  paintSeg();
  check();
  name.addEventListener('input', check);

  const handle = openSheet({
    title: adding ? 'Add a type to Other' : `Rename “${row.label}”`,
    body: el('div', null, [
      field('Name', el('div', null, [name, note])),
      field('Look it up as', seg,
        'Where the fill-in pass goes for artwork and details. Anything asks Wikipedia.'),
      !adding && row.count
        ? el('p.hint', { text: `${count(row.count)} ${row.count === 1 ? 'is' : 'are'} this type. `
            + 'A rename changes the name they go by and nothing else.' })
        : null,
    ]),
    footer: [cancel, go],
  });

  name.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !go.disabled) { event.preventDefault(); go.click(); }
  });
  cancel.addEventListener('click', () => handle.close());
  go.addEventListener('click', () => {
    if (go.disabled) return;
    const want = wanted();
    const before = otherTypes();
    let list;
    let said;
    if (adding) {
      list = [...before, { id: newTypeId(want), label: want, lookup }];
      said = `“${want}” added to Other`;
    } else if (row.listed) {
      list = before.map((t) => (t.id === row.id ? { ...t, label: want, lookup } : t));
      said = want !== row.label ? `“${row.label}” is “${want}” now` : `“${want}” saved`;
    } else {
      list = [...before, { id: row.id, label: want, lookup }];
      said = `“${want}” is in the list now`;
    }
    handle.close();
    setOtherTypes(list);
    done();
    toast(said, {
      ms: 9000,
      action: { label: 'Undo', fn: () => { setOtherTypes(before); done(); } },
    });
  });
  return handle;
}

/** Delete a type. Its titles go to a type picked here first — any of Other's
 * others, or Movie or TV — and the button says where before anything moves. */
export function deleteType(row, done = () => {}) {
  const listed = otherTypes();
  if (row.listed && listed.length <= 1) {
    toast('Other keeps at least one type — add another first', { error: true });
    return null;
  }
  const titles = live().filter((item) => item.type === row.id);
  const targets = TYPES.filter((t) => t.id !== row.id);
  const others = listed.filter((t) => t.id !== row.id);
  let target = titles.length
    ? (others.find((t) => t.id === 'other') || others[0] || targets[0]).id : '';

  const chips = el('div.chip-row.type-pick');
  const where = el('p.hint');
  const cancel = el('button.btn.ghost.grow', { type: 'button', text: 'Cancel' });
  const go = el('button.btn.danger.grow', { type: 'button' });

  const paint = () => {
    for (const chip of chips.children) {
      chip.setAttribute('aria-pressed', String(chip.dataset.type === target));
    }
    const tab = sectionOf({ type: target });
    go.textContent = titles.length
      ? `Delete, and move ${titles.length} to ${TYPE_LABEL[target]}` : `Delete “${row.label}”`;
    where.textContent = !titles.length ? ''
      : tab === 'other' ? `${titles.length === 1 ? 'It stays' : 'They stay'} on the Other tab.`
        : `${titles.length === 1 ? 'It moves' : 'They move'} to the ${SECTION_LABEL[tab]} tab, `
          + 'at the back of its queue.';
  };
  if (titles.length) {
    for (const type of targets) {
      chips.append(el('button.chip.chip-toggle', {
        type: 'button', text: type.label, dataset: { type: type.id },
        onclick: () => { target = type.id; paint(); },
      }));
    }
  }
  paint();

  const shown = titles.slice(0, 8).map((item) => item.title || 'Untitled');
  if (titles.length > 8) shown.push(`…and ${titles.length - 8} more`);

  const handle = openSheet({
    title: `Delete “${row.label}”?`,
    body: el('div', null, [
      el('p', {
        style: { margin: '4px 0 10px', color: 'var(--text-2)' },
        text: titles.length
          ? `${count(titles.length)} ${titles.length === 1 ? 'is' : 'are'} filed under `
            + `${row.label}. Where should ${titles.length === 1 ? 'it' : 'they'} go?`
          : `No title is filed under ${row.label}. It comes off the chips and the Type menus.`,
      }),
      titles.length ? chips : null,
      titles.length ? where : null,
      titles.length ? el('ul.confirm-list', null, shown.map((line) => el('li', { text: line })))
        : null,
    ]),
    footer: [cancel, go],
  });

  cancel.addEventListener('click', () => handle.close());
  go.addEventListener('click', () => {
    const to = target;
    const toLabel = TYPE_LABEL[to];
    const before = otherTypes();
    const moves = titles.map((item) => [item.id, sectionOf(item) === sectionOf({ type: to })
      ? { type: to } : { type: to, order: null }]);
    const back = titles.map((item) => [item.id, { type: item.type, order: item.order ?? null }]);
    handle.close();
    if (moves.length) {
      checkpoint(`delete the type ${row.label}`);
      patchMany(moves);
    }
    if (row.listed) setOtherTypes(before.filter((t) => t.id !== row.id));
    // A chip that no longer exists must not go on filtering the tab.
    if (pickedTypes('other').includes(row.id)) pickType(row.id, 'other');
    done();
    toast(`“${row.label}” deleted${moves.length ? ` — ${count(moves.length)} moved to ${toLabel}` : ''}`, {
      ms: 9000,
      action: {
        label: 'Undo',
        fn: () => {
          if (row.listed) setOtherTypes(before);
          if (back.length) patchMany(back);
          done();
        },
      },
    });
  });
  return handle;
}
