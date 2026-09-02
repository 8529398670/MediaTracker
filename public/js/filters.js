/* View state: search, filters, sort, grouping. Persisted locally so the
 * phone remembers how you last left the list. */

import { TYPES, STATUSES, TYPE_LABEL, STATUS_LABEL, allTags, live } from './store.js';
import { el, field, openSheet, toast } from './ui.js';

const VIEW_KEY = 'mt.view.v2';

/* The library is split into sections, and each section has the same three
 * lists: everything, the queue you keep in order by hand, and the pile you
 * have already watched. TV keeps its own of each. */
export const SECTIONS = [
  { id: 'movie', label: 'Movies', types: ['movie', 'doc'] },
  { id: 'tv',    label: 'TV',     types: ['tv', 'anime'] },
  { id: 'other', label: 'Other',  types: ['book', 'game', 'podcast', 'other'] },
];

export const SECTION_LABEL = Object.fromEntries(SECTIONS.map((s) => [s.id, s.label]));

export const SECTION_OF = Object.fromEntries(
  SECTIONS.flatMap((section) => section.types.map((type) => [type, section.id])));

export const sectionOf = (item) => SECTION_OF[item.type] || 'other';

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

export const filters = {
  section: 'movie',
  view: 'list',
  q: '',
  types: [],
  statuses: [],
  tags: [],
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
  return filters;
}

export function saveView() {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify({ ...filters, q: '' })); } catch { /* ignore */ }
}

export function activeCount() {
  let n = 0;
  if (filters.types.length) n += 1;
  if (filters.statuses.length) n += 1;
  if (filters.tags.length) n += 1;
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
    types: [], statuses: [], tags: [],
    hideWatched: false, heartsOnly: false, unratedOnly: false,
    minRating: 0, yearFrom: null, yearTo: null, hasLinks: false, noLinks: false,
  });
  saveView();
}

/* ------------------------------------------------------------------ search */

/** Splits `matrix tag:noir year:1999 -remake` into terms and field filters. */
function parseQuery(raw) {
  const terms = [];
  const fields = [];
  const negatives = [];
  const pattern = /"([^"]+)"|(\S+)/g;
  let match;
  while ((match = pattern.exec(raw || '')) !== null) {
    const token = (match[1] || match[2] || '').trim();
    if (!token) continue;
    const colon = token.indexOf(':');
    if (colon > 0 && !token.startsWith('http')) {
      fields.push([token.slice(0, colon).toLowerCase(), token.slice(colon + 1).toLowerCase()]);
    } else if (token.startsWith('#') && token.length > 1) {
      fields.push(['tag', token.slice(1).toLowerCase()]);
    } else if (token.startsWith('-') && token.length > 1) {
      negatives.push(token.slice(1).toLowerCase());
    } else {
      terms.push(token.toLowerCase());
    }
  }
  return { terms, fields, negatives };
}

function haystack(item) {
  return [
    item.title, item.year, item.notes, item.overview, item.creator,
    item.tags.join(' '), item.genres.join(' '),
    item.links.map((l) => `${l.label} ${l.url}`).join(' '),
    TYPE_LABEL[item.type], STATUS_LABEL[item.status],
  ].filter(Boolean).join('  ').toLowerCase();
}

function matchesQuery(item, parsed) {
  const hay = haystack(item);
  for (const term of parsed.terms) if (!hay.includes(term)) return false;
  for (const term of parsed.negatives) if (hay.includes(term)) return false;

  for (const [key, value] of parsed.fields) {
    switch (key) {
      case 'tag': if (!item.tags.some((t) => t.includes(value))) return false; break;
      case 'type': if (!item.type.startsWith(value)) return false; break;
      case 'status': if (!item.status.startsWith(value)) return false; break;
      case 'year': if (String(item.year || '') !== value) return false; break;
      case 'rating': if (String(item.rating || '') !== value) return false; break;
      case 'genre': if (!item.genres.some((g) => g.toLowerCase().includes(value))) return false; break;
      case 'note': case 'notes': if (!(item.notes || '').toLowerCase().includes(value)) return false; break;
      case 'link': if (!item.links.some((l) => l.url.toLowerCase().includes(value))) return false; break;
      case 'is':
        if (value === 'loved' && !item.heart) return false;
        if (value === 'rated' && !item.rating) return false;
        if (value === 'unrated' && item.rating) return false;
        if (value === 'watched' && item.status !== 'watched') return false;
        break;
      default: if (!hay.includes(`${key}:${value}`) && !hay.includes(value)) return false;
    }
  }
  return true;
}

/* ------------------------------------------------------------------ filter */

export function apply(items = live()) {
  const parsed = parseQuery(filters.q);
  const searching = Boolean(filters.q.trim());

  return items.filter((item) => {
    if (sectionOf(item) !== filters.section) return false;
    if (!inView(item)) return false;
    // While searching, watched items stay visible - you are looking for them.
    if (filters.hideWatched && filters.view === 'list' && !searching
        && item.status === 'watched') return false;
    if (filters.heartsOnly && !item.heart) return false;
    if (filters.unratedOnly && item.rating) return false;
    if (filters.types.length && !filters.types.includes(item.type)) return false;
    if (filters.statuses.length && !filters.statuses.includes(item.status)) return false;
    if (filters.tags.length && !filters.tags.every((t) => item.tags.includes(t))) return false;
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
    groups.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
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

  body.append(field('Type', multiChips(TYPES, draft.types)));
  body.append(field('Status', multiChips(STATUSES, draft.statuses)));

  const tags = allTags();
  if (tags.length) {
    body.append(field(
      'Tags',
      multiChips(tags.slice(0, 60).map(([tag, count]) => ({ id: tag, label: `${tag} ${count}` })), draft.tags),
      tags.length > 60 ? 'Showing the 60 most used tags - search #tag for the rest.' : null,
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
