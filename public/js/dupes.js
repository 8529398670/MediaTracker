/* Duplicates: the same film twice, under two names.
 *
 * The importer has always skipped a title whose folded name and year are
 * already there. That catches "Can't" against "Can’t", and nothing more: a
 * title typed as "Sunrise" while the library holds "Sunrise: A Song of Two
 * Humans", or "The Godfather Part 2" against "The Godfather Part II", went
 * in a second time and nobody was told. This is the looser comparison, used
 * in two places — to warn before something is added, and to find what has
 * already been added twice.
 *
 * It says how sure it is, because the two uses want different things. A
 * warning before an add can afford to mention the 1994 Little Women when the
 * 2019 one is being added; a list of duplicates to clean up cannot.
 *
 * The type is ignored on purpose. About a hundred films in this library are
 * filed under TV, and a duplicate across the two is exactly the kind nobody
 * would spot by looking. */

import { fold, live, TYPE_LABEL, STATUS_LABEL } from './store.js';

/** How sure a match is. `remake` is the same name a different year apart. */
export const CERTAIN = 1;
export const LIKELY = 0.9;
export const SIMILAR = 0.8;
export const REMAKE = 0.5;

/* ------------------------------------------------------------ the words */

const ARTICLES = new Set(['the', 'a', 'an']);
const ROMAN = { ii: 2, iii: 3, iv: 4, vi: 6, vii: 7, viii: 8, ix: 9, xi: 11, xii: 12, xiii: 13 };
// Alone, these are words as often as numerals — "I, Robot", "Malcolm X" —
// so they count only as the last word of a longer title: "Rocky V", "Part I".
const ROMAN_TAIL = { i: 1, v: 5, x: 10 };
const NUMBER = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8,
                 nine: 9, ten: 10, eleven: 11, twelve: 12 };
const ALIAS = { pt: 'part', vol: 'volume', ch: 'chapter', ep: 'episode' };

/* A year on the end is the year, not the title: "The weather girl - 2009",
 * "Heat (1995)". */
const TRAILING_YEAR = /(?:\s*[([]\s*(?:18|19|20)\d\d\s*[)\]]|\s+[-–—]\s*(?:18|19|20)\d\d)\s*$/;

const wordCache = new Map();

/** A title as the words that decide whether two are the same: folded, the
 * year on the end and the articles gone, numbers written one way. */
export function titleWords(title) {
  const raw = String(title ?? '');
  const seen = wordCache.get(raw);
  if (seen) return seen;
  const list = fold(raw.replace(TRAILING_YEAR, '')).split(' ').filter(Boolean);
  const out = [];
  list.forEach((word, at) => {
    if (ARTICLES.has(word)) return;
    if (ROMAN[word]) out.push(String(ROMAN[word]));
    else if (ROMAN_TAIL[word] && at === list.length - 1 && list.length > 1) out.push(String(ROMAN_TAIL[word]));
    else if (NUMBER[word]) out.push(String(NUMBER[word]));
    else out.push(ALIAS[word] || word);
  });
  if (wordCache.size > 5000) wordCache.clear();
  wordCache.set(raw, out);
  return out;
}

export const normKey = (title) => titleWords(title).join(' ');

/** The part before a subtitle: "Sunrise" of "Sunrise: A Song of Two Humans". */
function mainTitle(title) {
  const raw = String(title ?? '').replace(TRAILING_YEAR, '');
  const cut = raw.split(/\s*[:–—]\s*|\s+-\s+/)[0];
  return cut && cut.length < raw.length ? normKey(cut) : '';
}

const numbers = (words) => words.filter((w) => /^\d+$/.test(w)).sort().join(' ');

/* -------------------------------------------------------------- distance */

/** Edits between two strings, a swap of neighbours counting as one. */
function distance(a, b, limit) {
  if (Math.abs(a.length - b.length) > limit) return limit + 1;
  let before = null;
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i += 1) {
    const row = [i];
    let best = i;
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let d = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost);
      if (before && i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        d = Math.min(d, before[j - 2] + 1);
      }
      row.push(d);
      if (d < best) best = d;
    }
    if (best > limit) return limit + 1;
    before = prev;
    prev = row;
  }
  return prev[b.length];
}

function jaccard(a, b) {
  const x = new Set(a);
  const y = new Set(b);
  let both = 0;
  for (const w of x) if (y.has(w)) both += 1;
  return both / (x.size + y.size - both || 1);
}

/* ------------------------------------------------------------ comparing */

const wikiKey = (url) => {
  try { return decodeURIComponent(String(url || '')).toLowerCase().replace(/^https?:\/\/(?:en\.m\.|en\.)?/, '').replace(/_/g, ' '); }
  catch { return String(url || '').toLowerCase(); }
};

const yearsFit = (a, b) => !a || !b || Math.abs(a - b) <= 1;

/** How alike two titles are: `{ score, why }`, score 0 when they are not.
 * Either side may be a library item or anything with a title and a year. */
export function similarity(a, b) {
  const none = { score: 0, why: '' };
  if (!a || !b) return none;

  // A record id is the strongest thing there is, either way: the same IMDb
  // title is the same film whatever it is called, and two different ones
  // are two films however alike the names.
  if (a.imdbId && b.imdbId) {
    return a.imdbId === b.imdbId ? { score: CERTAIN, why: 'the same IMDb title' } : none;
  }
  if (a.wikiUrl && b.wikiUrl && wikiKey(a.wikiUrl) === wikiKey(b.wikiUrl)) {
    return { score: CERTAIN, why: 'the same Wikipedia article' };
  }
  if (a.source && a.sourceId && a.source === b.source && a.sourceId === b.sourceId) {
    return { score: CERTAIN, why: 'the same record' };
  }

  const wa = titleWords(a.title);
  const wb = titleWords(b.title);
  const ka = wa.join(' ');
  const kb = wb.join(' ');
  if (!ka || !kb) return none;
  const ya = Number(a.year) || 0;
  const yb = Number(b.year) || 0;

  if (ka === kb) {
    if (ya && yb) {
      return yearsFit(ya, yb) ? { score: CERTAIN, why: 'the same title and year' }
        : { score: REMAKE, why: `the same title, ${Math.abs(ya - yb)} years apart` };
    }
    return { score: LIKELY, why: 'the same title' };
  }

  // One is the other with a subtitle. Only with both years there and agreeing:
  // "Alien" and "Alien: Resurrection" share a first half and nothing else.
  if (ya && yb && yearsFit(ya, yb)) {
    const ma = mainTitle(a.title);
    const mb = mainTitle(b.title);
    if ((ma && ma === kb) || (mb && mb === ka)) {
      return { score: LIKELY, why: 'the same title, one with a subtitle' };
    }
  }

  if (!yearsFit(ya, yb)) return none;
  // Rocky II is not Rocky III, however close the spelling.
  if (numbers(wa) !== numbers(wb)) return none;

  const longest = Math.max(ka.length, kb.length);
  if (Math.min(ka.length, kb.length) >= 4) {
    const limit = Math.floor(longest * 0.15);
    const d = distance(ka, kb, limit);
    if (d <= limit) {
      return { score: SIMILAR + 0.1 * (1 - d / longest) * 0.5, why: 'spelled almost the same' };
    }
  }
  if (Math.min(wa.length, wb.length) >= 3 && jaccard(wa, wb) >= 0.8) {
    return { score: SIMILAR, why: 'nearly the same words' };
  }
  return none;
}

/* --------------------------------------------------------------- finding */

/* Typed with the year on the end and nothing between: "sleepless in seattle
 * 1993". Could be the year, could be the name — Blade Runner 2049, Wonder
 * Woman 1984 — so both readings are tried and the better one kept. */
const BARE_YEAR = /^(.*\S)\s+((?:18|19|20)\d\d)$/;

function readings(candidate) {
  const out = [candidate];
  const bare = !candidate.year && BARE_YEAR.exec(String(candidate.title || '').trim());
  if (bare && Number(bare[2]) <= new Date().getFullYear() + 2) {
    out.push({ ...candidate, title: bare[1], year: Number(bare[2]) });
  }
  return out;
}

/** What in the library looks like `candidate`, best first. `min` drops to
 * REMAKE for a warning, where the other year's film is worth a mention. */
export function findMatches(candidate, items = live(), { min = SIMILAR, limit = 4, except = null } = {}) {
  const out = [];
  const ways = readings(candidate);
  for (const item of items) {
    if (item === candidate || (except && except.has(item.id))) continue;
    if (candidate.id && item.id === candidate.id) continue;
    let best = { score: 0, why: '' };
    for (const way of ways) {
      const match = similarity(way, item);
      if (match.score > best.score) best = match;
    }
    if (best.score >= min) out.push({ item, ...best });
  }
  return out.sort((x, y) => y.score - x.score).slice(0, limit);
}

/** The strongest match, or null: what a warning is about. */
export function bestMatch(candidate, items = live(), opts = {}) {
  return findMatches(candidate, items, { min: REMAKE, limit: 1, ...opts })[0] || null;
}

export const isCertain = (match) => Boolean(match) && match.score >= CERTAIN;

/* -------------------------------------------------------- not duplicates */

const DISMISS_KEY = 'mt.notdupes.v1';
const pairKey = (x, y) => (x < y ? `${x}|${y}` : `${y}|${x}`);

function dismissed() {
  try { return new Set(JSON.parse(localStorage.getItem(DISMISS_KEY) || '[]')); }
  catch { return new Set(); }
}

/** These are not the same, whatever their names say. Remembered here. */
export function dismissGroup(items) {
  const set = dismissed();
  for (const a of items) for (const b of items) if (a.id < b.id) set.add(pairKey(a.id, b.id));
  try { localStorage.setItem(DISMISS_KEY, JSON.stringify([...set])); } catch { /* ignore */ }
}

/* ------------------------------------------------------------ the groups */

/** Every set of titles that look like one another, surest first. Compared
 * only within blocks that share something — an id, a word, the first few
 * letters — so a thousand titles are not a million comparisons. */
export function findDuplicateGroups(items = live(), { min = SIMILAR } = {}) {
  const blocks = new Map();
  const put = (key, item) => {
    if (!key) return;
    if (!blocks.has(key)) blocks.set(key, []);
    blocks.get(key).push(item);
  };
  for (const item of items) {
    const words = titleWords(item.title);
    const key = words.join(' ');
    put(item.imdbId && `i:${item.imdbId}`, item);
    put(item.wikiUrl && `w:${wikiKey(item.wikiUrl)}`, item);
    put(key && `k:${key}`, item);
    put(key.length >= 4 && `p:${key.replace(/ /g, '').slice(0, 4)}`, item);
    for (const word of new Set(words)) {
      if (word.length >= 4 && !/^\d+$/.test(word)) put(`t:${word}`, item);
    }
  }

  const skip = dismissed();
  const parent = new Map(items.map((item) => [item.id, item.id]));
  const root = (id) => {
    while (parent.get(id) !== id) { parent.set(id, parent.get(parent.get(id))); id = parent.get(id); }
    return id;
  };
  const best = new Map();       // pair -> { score, why }
  const done = new Set();

  for (const block of blocks.values()) {
    if (block.length < 2 || block.length > 250) continue;
    for (let i = 0; i < block.length; i += 1) {
      for (let j = i + 1; j < block.length; j += 1) {
        const a = block[i];
        const b = block[j];
        const pair = pairKey(a.id, b.id);
        if (done.has(pair)) continue;
        done.add(pair);
        if (skip.has(pair)) continue;
        const match = similarity(a, b);
        if (match.score < min) continue;
        best.set(pair, match);
        parent.set(root(a.id), root(b.id));
      }
    }
  }

  const byRoot = new Map();
  for (const item of items) {
    const r = root(item.id);
    if (!byRoot.has(r)) byRoot.set(r, []);
    byRoot.get(r).push(item);
  }
  const groups = [];
  for (const members of byRoot.values()) {
    if (members.length < 2) continue;
    let score = 0;
    let why = '';
    for (const a of members) {
      for (const b of members) {
        const m = a.id < b.id && best.get(pairKey(a.id, b.id));
        if (m && m.score > score) ({ score, why } = m);
      }
    }
    groups.push({ items: members, score, why });
  }
  return groups.sort((x, y) => y.score - x.score
    || normKey(x.items[0].title).localeCompare(normKey(y.items[0].title)));
}

/* --------------------------------------------------------------- telling */

const MONTH = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** What you have, in a line: "Watched Mar 2025 · “Sunrise: A Song of Two
 * Humans” (1927) · Movie". */
export function describe(item, { title = true } = {}) {
  const when = item.status === 'watched' && item.watchedAt ? new Date(item.watchedAt) : null;
  const status = `${STATUS_LABEL[item.status] || item.status}`
    + (when && !Number.isNaN(+when) ? ` ${MONTH[when.getMonth()]} ${when.getFullYear()}` : '');
  return [
    status,
    title ? `“${item.title}”${item.year ? ` (${item.year})` : ''}` : item.year || 'no year',
    TYPE_LABEL[item.type] || item.type,
  ].join(' · ');
}

/** The warning itself: what it looks like, and how sure that is. */
export function warning(match) {
  if (!match) return '';
  const lead = match.score >= CERTAIN ? 'Already in your library'
    : match.score >= SIMILAR ? 'Looks like one you have'
      : 'You have one by this name';
  return `${lead}: ${describe(match.item)}`;
}

/* ---------------------------------------------------------------- merging */

const FILL = ['poster', 'overview', 'runtime', 'creator', 'certification', 'imdbId', 'wikiUrl',
  'year', 'extRating'];
const blank = (v) => v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length);

/** What `keep` becomes when the others are folded into it: watched if any
 * of them was (from the earliest date), your rating and heart, every tag,
 * link and note, and any detail it was missing. Only the fields that change. */
export function mergedFields(keep, others) {
  const all = [keep, ...others];
  const out = {};
  const watched = all.filter((i) => i.status === 'watched');
  if (watched.length && keep.status !== 'watched') out.status = 'watched';
  if (watched.length) {
    const dates = watched.map((i) => i.watchedAt).filter(Boolean).sort();
    if (dates[0] && dates[0] !== keep.watchedAt) out.watchedAt = dates[0];
  } else if (keep.status === 'queue' && others.some((i) => i.status === 'watching')) {
    out.status = 'watching';
  }
  if (!keep.rating) {
    const rated = others.find((i) => i.rating);
    if (rated) out.rating = rated.rating;
  }
  if (!keep.heart && others.some((i) => i.heart)) out.heart = true;

  const tags = [...new Set(all.flatMap((i) => i.tags || []))];
  if (tags.length !== (keep.tags || []).length) out.tags = tags;
  const links = [...(keep.links || [])];
  for (const link of others.flatMap((i) => i.links || [])) {
    if (!links.some((l) => l.url === link.url)) links.push(link);
  }
  if (links.length !== (keep.links || []).length) out.links = links;
  const notes = [...new Set(all.map((i) => (i.notes || '').trim()).filter(Boolean))];
  if (notes.join('\n\n') !== (keep.notes || '').trim() && notes.length) out.notes = notes.join('\n\n');

  for (const key of FILL) {
    if (!blank(keep[key])) continue;
    const from = others.find((i) => !blank(i[key]));
    if (from) out[key] = from[key];
  }
  for (const key of ['genres', 'cast']) {
    if (blank(keep[key])) {
      const from = others.find((i) => !blank(i[key]));
      if (from) out[key] = [...from[key]];
    }
  }
  if (!keep.source) {
    const from = others.find((i) => i.source);
    if (from) { out.source = from.source; out.sourceId = from.sourceId; }
  }
  const added = all.map((i) => i.addedAt).filter(Boolean).sort()[0];
  if (added && added !== keep.addedAt) out.addedAt = added;
  return out;
}
