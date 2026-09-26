/* View state: search, filters, sort, grouping. Persisted locally so the
 * phone remembers how you last left the list. */

import {
  TYPES, STATUSES, TYPE_LABEL, STATUS_LABEL, allTags, allCerts, live, genreLabels,
  fold, otherTypes, defaultOther, typesVersion,
} from './store.js';
import { el, field, openSheet, toast } from './ui.js';

const VIEW_KEY = 'mt.view.v2';

/* The library is split into sections, and each section has the same three
 * lists: everything, the queue you keep in order by hand, and the pile you
 * have already watched. TV keeps its own of each.
 *
 * Movies and TV hold one kind of thing apiece. Everything else is Other —
 * documentaries and anime too, which is where the documents the library came
 * from file them — and a row of chips in the toolbar picks one kind of it out,
 * or any mix. What Other is split into is the library's own list (store.js),
 * so its types are read afresh each time. A type the list does not name lands
 * in Other as well, and gets a chip of its own while a title carries it.
 * `adds` is what a title added from the tab starts out as. */
export const SECTIONS = [
  { id: 'movie', label: 'Movies', types: ['movie'], adds: 'movie' },
  { id: 'tv',    label: 'TV',     types: ['tv'], adds: 'tv' },
  { id: 'other', label: 'Other',
    get types() { return otherTypes().map((t) => t.id); },
    get adds() { return defaultOther(); } },
];

export const SECTION_LABEL = Object.fromEntries(SECTIONS.map((s) => [s.id, s.label]));

export const sectionOf = (item) => (item.type === 'movie' || item.type === 'tv' ? item.type : 'other');

export const VIEWS = [
  { id: 'list',    label: 'List' },
  { id: 'queue',   label: 'Queue' },
  { id: 'watched', label: 'Watched' },
];

/** Statuses each view is made of; `list` takes everything. */
const VIEW_STATUS = {
  queue: ['queue', 'watching'],
  watched: ['watched'],
};

export function inView(item, view = filters.view) {
  const allowed = VIEW_STATUS[view];
  return !allowed || allowed.includes(item.status);
}

/* ------------------------------------------------------------------- kinds */

/** The kinds picked out of a section in the toolbar; none means all of them. */
export function pickedTypes(section = filters.section) {
  const list = (filters.sectionTypes || {})[section];
  return Array.isArray(list) ? list : [];
}

/** Pick a kind out, or put it back. `null` puts every kind back. */
export function pickType(type, section = filters.section) {
  const now = pickedTypes(section);
  const next = type === null ? []
    : now.includes(type) ? now.filter((t) => t !== type) : [...now, type];
  const all = { ...filters.sectionTypes };
  if (next.length) all[section] = next; else delete all[section];
  filters.sectionTypes = all;
  saveView();
}

/** A chip for each kind a section is made of — and for any other kind that
 * has turned up in it — with how many the list on screen holds before
 * anything else narrows it. In the order the type menu lists them. */
export function sectionKinds(items, section = filters.section, view = filters.view) {
  const home = (SECTIONS.find((s) => s.id === section) || { types: [] }).types;
  const count = new Map();
  for (const item of items) {
    if (sectionOf(item) !== section || !inView(item, view)) continue;
    count.set(item.type, (count.get(item.type) || 0) + 1);
  }
  // The list's own types in its order, then any other a title still carries.
  const strays = [...count.keys(), ...pickedTypes(section)]
    .filter((id, at, all) => !home.includes(id) && all.indexOf(id) === at);
  return [...home, ...strays]
    .map((id) => ({ id, label: TYPE_LABEL[id] || id, count: count.get(id) || 0 }));
}

/** What a title added from the tab starts out as: the one kind picked out
 * in the toolbar when exactly one is, or else what the section adds. */
export function addingType(section = filters.section) {
  const picked = pickedTypes(section);
  if (picked.length === 1) return picked[0];
  return (SECTIONS.find((s) => s.id === section) || SECTIONS[0]).adds;
}

/* Titles that have just been ticked out of the list on screen and are being
 * given a moment before they go. A tick on the queue would otherwise take
 * the row away under the finger that pressed it, and a slip is only
 * undoable if the thing slipped on is still there to press again. While an
 * id is in here the status filters let it through; the card is drawn with
 * its new status, greyed and crossed out, so it is plain what is about to
 * happen. Not saved: a reload is a fresh look. */
export const lingering = new Set();

export const filters = {
  section: 'movie',
  view: 'list',
  q: '',
  // Section id -> the kinds picked out of it. Kept apart per section, so
  // picking Audio Books on Other does not empty Movies.
  sectionTypes: {},
  statuses: [],
  tags: [],
  certs: [],
  hideWatched: false,
  heartsOnly: false,
  unratedOnly: false,
  minRating: 0,
  yearFrom: null,
  yearTo: null,
  hasLinks: false,
  noLinks: false,
  sort: 'added-desc',
  group: 'year',
  map: true,
};

export function loadView() {
  try {
    const saved = JSON.parse(localStorage.getItem(VIEW_KEY) || '{}');
    Object.assign(filters, saved, { q: '' });
  } catch { /* first run */ }
  // The one type filter used to span every section; it is per section now.
  delete filters.types;
  if (!filters.sectionTypes || typeof filters.sectionTypes !== 'object') filters.sectionTypes = {};
  return filters;
}

export function saveView() {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify({ ...filters, q: '' })); } catch { /* ignore */ }
}

export function activeCount() {
  let n = 0;
  if (pickedTypes().length) n += 1;
  if (filters.statuses.length) n += 1;
  if (filters.tags.length) n += 1;
  if (filters.certs.length) n += 1;
  if (filters.heartsOnly) n += 1;
  if (filters.unratedOnly) n += 1;
  if (filters.hideWatched) n += 1;
  if (filters.minRating > 0) n += 1;
  if (filters.yearFrom || filters.yearTo) n += 1;
  if (filters.hasLinks || filters.noLinks) n += 1;
  return n;
}

export function resetFilters() {
  Object.assign(filters, {
    sectionTypes: {}, statuses: [], tags: [], certs: [],
    hideWatched: false, heartsOnly: false, unratedOnly: false,
    minRating: 0, yearFrom: null, yearTo: null, hasLinks: false, noLinks: false,
  });
  saveView();
}

/* ------------------------------------------------------------------ search */

/* A phone writes a quote as a curly one, and there is no way to type a
 * straight one on the iOS keyboard without fighting it. All four open and
 * close a phrase. */
const QUOTED = /["\u201c\u201d\u2033]([^"\u201c\u201d\u2033]+)["\u201c\u201d\u2033]|(\S+)/g;

/** Splits `matrix tag:noir year:1999 -remake` into terms and field filters. */
export function parseQuery(raw) {
  const terms = [];
  const fields = [];
  const negatives = [];
  QUOTED.lastIndex = 0;
  let match;
  while ((match = QUOTED.exec(raw || '')) !== null) {
    const token = (match[1] || match[2] || '').trim();
    if (!token) continue;
    const colon = token.indexOf(':');
    if (colon > 0 && !token.startsWith('http')) {
      fields.push([token.slice(0, colon).toLowerCase(), token.slice(colon + 1).toLowerCase()]);
    } else if (token.startsWith('#') && token.length > 1) {
      fields.push(['tag', token.slice(1).toLowerCase()]);
    } else if (/^[-\u2010-\u2015]/.test(token) && token.length > 1) {
      negatives.push(token.slice(1).toLowerCase());
    } else {
      terms.push(token.toLowerCase());
    }
  }
  return { terms, fields, negatives };
}

/** Every word a genre search should answer to: the folded labels and the
 * provider genres they were folded from, lowercased. */
function genreTerms(item) {
  const seen = new Set();
  for (const g of genreLabels(item)) seen.add(g.toLowerCase());
  for (const g of item.genres || []) seen.add(g.toLowerCase());
  return [...seen];
}

/* Both sides of the comparison are folded, so a title does not have to be
 * spelled the way the document that carried it in spelled it. "Can't Buy Me
 * Love" typed on a keyboard finds "Can’t Buy Me Love" as Google Docs wrote
 * it; "Wall-E" finds "WALL·E"; "Amelie" finds "Amélie"; "Prince & Me" finds
 * "Prince and Me". Whichever way round, one of them is what you typed. */
function searchable(item) {
  return [
    item.title, item.year, item.notes, item.overview, item.creator,
    item.tags.join(' '), genreTerms(item).join(' '), item.certification,
    (item.cast || []).join(' '),
    item.links.map((l) => `${l.label} ${l.url}`).join(' '),
    TYPE_LABEL[item.type], STATUS_LABEL[item.status],
  ].filter(Boolean).join('  ');
}

/* Folding nine hundred titles costs more than a substring test does, and the
 * same nine hundred are searched again on the next keystroke. Cached against
 * the stamp every edit bumps, so an edited title is folded again and nothing
 * else is. */
const hays = new WeakMap();

function haystack(item) {
  // A renamed type changes what every title of it answers to.
  const stamp = `${item.updatedAt}|${typesVersion}`;
  const seen = hays.get(item);
  if (seen && seen.stamp === stamp) return seen.hay;
  const hay = fold(searchable(item));
  hays.set(item, { stamp, hay });
  return hay;
}

function matchesQuery(item, parsed) {
  const hay = haystack(item);
  for (const term of parsed.terms) if (!hay.includes(fold(term))) return false;
  for (const term of parsed.negatives) if (hay.includes(fold(term))) return false;

  for (const [key, value] of parsed.fields) {
    switch (key) {
      case 'tag': if (!item.tags.some((t) => fold(t).includes(fold(value)))) return false; break;
      // By id or by the name it goes by: `type:audio` finds Audio Books.
      case 'type':
        if (!item.type.startsWith(value)
            && !fold(TYPE_LABEL[item.type] || '').startsWith(fold(value))) return false;
        break;
      case 'status': if (!item.status.startsWith(value)) return false; break;
      case 'year': if (String(item.year || '') !== value) return false; break;
      case 'rating': if (String(item.rating || '') !== value) return false; break;
      /* Matched against the labels as shown *and* the genres underneath, so
         `genre:romantic comedy` finds what the card calls a romantic comedy
         while `genre:romance` still finds the same film by the Romance the
         providers actually stored. Folding the pair must not hide either half. */
      case 'genre':
        if (!genreTerms(item).some((g) => fold(g).includes(fold(value)))) return false;
        break;
      /* The board's rating, not yours — `rating:` is already the score you
         gave it. Exact, because a parent asking for PG does not mean PG-13. */
      case 'cert': case 'age': {
        const cert = (item.certification || '').toLowerCase();
        if (value === 'none' || value === 'unrated') { if (cert) return false; break; }
        if (cert !== value) return false;
        break;
      }
      case 'note': case 'notes':
        if (!fold(item.notes).includes(fold(value))) return false;
        break;
      /* A URL is the one thing not worth folding: `link:themoviedb.org/tv`
         is a shape of its own, and turning the slash into a space loses it. */
      case 'link': if (!item.links.some((l) => l.url.toLowerCase().includes(value))) return false; break;
      case 'is':
        if (value === 'loved' && !item.heart) return false;
        if (value === 'rated' && !item.rating) return false;
        if (value === 'unrated' && item.rating) return false;
        if (value === 'watched' && item.status !== 'watched') return false;
        break;
      /* Not an operator we know. `director:cukor` is not a field here, but
         the director is in the haystack, so what was asked for is looked
         for: the two words together first, then the value on its own. */
      default:
        if (!hay.includes(fold(`${key} ${value}`)) && !hay.includes(fold(value))) return false;
    }
  }
  return true;
}

/** The words of a query with the operators taken out — what to ask a
 * catalogue that only knows how to match words. */
export function plainTerms(raw) {
  return parseQuery(raw).terms.join(' ').trim();
}

/* A search finds a card through anything on it, and that is right — but a
 * card found through its cast is a different kind of answer from one found
 * by name. "juno" is Juno Temple's films and, somewhere below them, Juno.
 * So the name is checked on its own: what matched by name goes first, and
 * what did not says where it matched. */

const every = (hay, terms) => terms.every((term) => hay.includes(fold(term)));

export function titleMatches(title, terms) {
  const words = typeof terms === 'string' ? plainTerms(terms).split(' ') : terms;
  return words.length > 0 && every(fold(title), words);
}

/** Where a card that was not found by name was found — "cast · Juno
 * Temple", "#noir", "notes" — or nothing when the name itself matched. */
export function whyMatched(item, raw) {
  const words = plainTerms(raw).split(' ').filter(Boolean);
  if (!words.length || titleMatches(item.title, words)) return '';
  const name = (item.cast || []).find((n) => every(fold(n), words));
  if (name) return `cast · ${name}`;
  if ((item.cast || []).length && every(fold(item.cast.join(' ')), words)) return 'cast';
  if (item.creator && every(fold(item.creator), words)) return item.creator;
  const tag = item.tags.find((t) => every(fold(t), words));
  if (tag) return `#${tag}`;
  if (genreTerms(item).some((g) => every(fold(g), words))) return 'genre';
  if (every(fold(item.notes), words)) return 'notes';
  if (every(fold(item.overview), words)) return 'overview';
  if (item.links.some((l) => every(fold(`${l.label} ${l.url}`), words))) return 'link';
  return '';
}

/* ------------------------------------------------------------------ filter */

/* `everywhere` lifts the section and the list: the same search, asked of the
 * whole library rather than of the tab that happens to be open. The filters
 * you set on purpose — tags, a year range, loved only — still hold. */
export function apply(items = live(), { everywhere = false } = {}) {
  const parsed = parseQuery(filters.q);
  const searching = Boolean(filters.q.trim());
  // Which kinds of this section are on show is a matter of where you are,
  // like the section itself, so a search that reaches past it lifts it too.
  const kinds = everywhere ? [] : pickedTypes();

  return items.filter((item) => {
    const stays = lingering.has(item.id);
    if (!everywhere && sectionOf(item) !== filters.section) return false;
    if (!everywhere && !stays && !inView(item)) return false;
    // While searching, watched items stay visible - you are looking for them.
    if (!everywhere && !stays && filters.hideWatched && filters.view === 'list' && !searching
        && item.status === 'watched') return false;
    if (filters.heartsOnly && !item.heart) return false;
    if (filters.unratedOnly && item.rating) return false;
    if (kinds.length && !kinds.includes(item.type)) return false;
    if (!stays && filters.statuses.length && !filters.statuses.includes(item.status)) return false;
    if (filters.tags.length && !filters.tags.every((t) => item.tags.includes(t))) return false;
    if (filters.certs.length && !filters.certs.includes(item.certification || '')) return false;
    if (filters.minRating > 0 && (item.rating || 0) < filters.minRating) return false;
    if (filters.yearFrom && (item.year || 0) < filters.yearFrom) return false;
    if (filters.yearTo && (item.year || 9999) > filters.yearTo) return false;
    if (filters.hasLinks && !item.links.length) return false;
    if (filters.noLinks && item.links.length) return false;
    if (searching && !matchesQuery(item, parsed)) return false;
    return true;
  });
}

/* -------------------------------------------------------------------- sort */

const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });
const byText = (a, b) => collator.compare(a || '', b || '');
const nullsLast = (a, b, dir) => {
  if (a === b) return 0;
  if (a === null || a === undefined) return 1;
  if (b === null || b === undefined) return -1;
  return a < b ? -dir : dir;
};

export const SORTS = {
  'added-desc':   (a, b) => byText(b.addedAt, a.addedAt),
  'added-asc':    (a, b) => byText(a.addedAt, b.addedAt),
  'watched-desc': (a, b) => nullsLast(a.watchedAt, b.watchedAt, -1),
  'title-asc':    (a, b) => byText(a.title, b.title),
  'title-desc':   (a, b) => byText(b.title, a.title),
  'year-desc':    (a, b) => nullsLast(a.year, b.year, -1) || byText(a.title, b.title),
  'year-asc':     (a, b) => nullsLast(a.year, b.year, 1) || byText(a.title, b.title),
  'rating-desc':  (a, b) => nullsLast(a.rating, b.rating, -1) || byText(a.title, b.title),
  'rating-asc':   (a, b) => nullsLast(a.rating, b.rating, 1) || byText(a.title, b.title),
  'updated-desc': (a, b) => byText(b.updatedAt, a.updatedAt),
  // Hand-made queue order; anything never placed falls in behind, oldest first.
  'manual':       (a, b) => nullsLast(a.order, b.order, 1) || byText(a.addedAt, b.addedAt),
};

export function sortItems(items, sort = filters.sort) {
  return [...items].sort(SORTS[sort] || SORTS['added-desc']);
}

/** The queue in the order you put it in. */
export function queueOrder(items) {
  return sortItems(items, 'manual');
}

/* ------------------------------------------------------------------- group */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

function groupKey(item, group = filters.group) {
  switch (group) {
    case 'year':
      return item.year ? [String(item.year), String(item.year)] : ['0000', 'No year'];
    case 'decade': {
      if (!item.year) return ['0000', 'No year'];
      const decade = Math.floor(item.year / 10) * 10;
      return [String(decade), `${decade}s`];
    }
    case 'status':
      return [item.status, STATUS_LABEL[item.status] || item.status];
    case 'type':
      return [item.type, TYPE_LABEL[item.type] || item.type];
    case 'rating':
      return item.rating ? [String(item.rating).padStart(2, '0'), `${item.rating} / 10`]
                         : ['00', 'Unrated'];
    case 'added': {
      const date = new Date(item.addedAt || '');
      if (Number.isNaN(+date)) return ['0000-00', 'Unknown'];
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`;
      return [key, `${MONTHS[date.getMonth()]} ${date.getFullYear()}`];
    }
    default:
      return ['all', 'All'];
  }
}

const STATUS_ORDER = ['watching', 'queue', 'watched', 'dropped'];

export function groupItems(items, group = filters.group) {
  if (group === 'none') return [{ key: 'all', label: '', items }];

  const map = new Map();
  for (const item of items) {
    const [key, label] = groupKey(item, group);
    if (!map.has(key)) map.set(key, { key, label, items: [] });
    map.get(key).items.push(item);
  }

  const groups = [...map.values()];
  if (group === 'status') {
    groups.sort((a, b) => STATUS_ORDER.indexOf(a.key) - STATUS_ORDER.indexOf(b.key));
  } else if (group === 'type') {
    const order = TYPES.map((t) => t.id);
    const at = (key) => (order.includes(key) ? order.indexOf(key) : order.length);
    groups.sort((a, b) => at(a.key) - at(b.key));
  } else {
    // Newest first unless the sort is explicitly ascending; "No year"
    // (key 0000) therefore falls to the bottom either way.
    const dir = filters.sort.endsWith('-asc') ? 1 : -1;
    groups.sort((a, b) => (a.key < b.key ? -dir : a.key > b.key ? dir : 0));
  }
  return groups;
}

/* ------------------------------------------------------------ filter sheet */

export function openFilterSheet(onApply) {
  const draft = JSON.parse(JSON.stringify({ ...filters, q: undefined }));
  const body = el('div');

  const toggleChip = (label, get, set) => {
    const chip = el('button.chip.chip-toggle', {
      type: 'button', text: label, 'aria-pressed': String(get()),
    });
    chip.addEventListener('click', () => {
      set(!get());
      chip.setAttribute('aria-pressed', String(get()));
    });
    return chip;
  };

  const multiChips = (options, list) => {
    const row = el('div.chip-row');
    for (const option of options) {
      const chip = el('button.chip.chip-toggle', {
        type: 'button', text: option.label,
        'aria-pressed': String(list.includes(option.id)),
      });
      chip.addEventListener('click', () => {
        const index = list.indexOf(option.id);
        if (index === -1) list.push(option.id); else list.splice(index, 1);
        chip.setAttribute('aria-pressed', String(list.includes(option.id)));
      });
      row.append(chip);
    }
    return row;
  };

  // Only where there is more than one kind to pick from, and the same pick as
  // the chips in the toolbar — so it is this section's, not every section's.
  const kinds = sectionKinds(live());
  if (kinds.length > 1) {
    const picked = [...pickedTypes()];
    draft.sectionTypes = { ...draft.sectionTypes, [filters.section]: picked };
    body.append(field('Type', multiChips(
      kinds.map((k) => ({ id: k.id, label: `${k.label} ${k.count}` })), picked)));
  }
  body.append(field('Status', multiChips(STATUSES, draft.statuses)));

  const tags = allTags();
  if (tags.length) {
    body.append(field(
      'Tags',
      multiChips(tags.slice(0, 60).map(([tag, count]) => ({ id: tag, label: `${tag} ${count}` })), draft.tags),
      tags.length > 60 ? 'Showing the 60 most used tags - search #tag for the rest.' : null,
    ));
  }

  const certs = allCerts();
  if (certs.length > 1) {
    body.append(field(
      'Age rating',
      multiChips(certs.map(([cert, count]) => (
        { id: cert, label: `${cert || 'Not rated'} ${count}` })), draft.certs),
      'What the ratings board gave it — separate from the score you give it.',
    ));
  }

  const flags = el('div.chip-row', null, [
    toggleChip('Loved only', () => draft.heartsOnly, (v) => { draft.heartsOnly = v; }),
    toggleChip('Unrated only', () => draft.unratedOnly, (v) => { draft.unratedOnly = v; }),
    toggleChip('Hide watched', () => draft.hideWatched, (v) => { draft.hideWatched = v; }),
    toggleChip('Has a link', () => draft.hasLinks, (v) => { draft.hasLinks = v; if (v) draft.noLinks = false; }),
    toggleChip('Missing a link', () => draft.noLinks, (v) => { draft.noLinks = v; if (v) draft.hasLinks = false; }),
  ]);
  body.append(field('Flags', flags));

  const minRating = el('select.input');
  minRating.append(el('option', { value: '0', text: 'Any rating' }));
  for (let n = 1; n <= 10; n += 1) {
    minRating.append(el('option', { value: String(n), text: `${n}+` }));
  }
  minRating.value = String(draft.minRating || 0);
  minRating.addEventListener('change', () => { draft.minRating = Number(minRating.value); });
  body.append(field('Minimum rating', minRating));

  const from = el('input.input', {
    type: 'number', inputmode: 'numeric', placeholder: 'from', value: draft.yearFrom || '',
  });
  const to = el('input.input', {
    type: 'number', inputmode: 'numeric', placeholder: 'to', value: draft.yearTo || '',
  });
  from.addEventListener('input', () => { draft.yearFrom = Number(from.value) || null; });
  to.addEventListener('input', () => { draft.yearTo = Number(to.value) || null; });
  body.append(field('Year range', el('div.row', null, [from, to])));

  const clearBtn = el('button.btn.ghost.grow', { type: 'button', text: 'Clear all' });
  const applyBtn = el('button.btn.primary.grow', { type: 'button', text: 'Show results' });

  const handle = openSheet({ title: 'Filters', body, footer: [clearBtn, applyBtn] });

  clearBtn.addEventListener('click', () => {
    resetFilters();
    handle.close();
    onApply();
    toast('Filters cleared');
  });
  applyBtn.addEventListener('click', () => {
    Object.assign(filters, draft, { q: filters.q });
    saveView();
    handle.close();
    onApply();
  });
}
