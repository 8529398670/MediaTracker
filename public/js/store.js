/* Library state, persistence and sync.
 *
 * The browser is optimistic: every edit lands in memory immediately, is
 * mirrored to localStorage, and is pushed to the server on a short debounce.
 * The server owns a revision counter; if someone else wrote in between we
 * merge per item (newest updatedAt wins, deletions leave tombstones) and
 * push again. That keeps a phone and a laptop honest without a database.
 */

const LS_KEY = 'mt.library.v2';
const SYNC_DEBOUNCE = 700;
const POLL_MS = 60000;

/* Movies and TV are tabs of their own. Everything else is Other, and what
 * Other is split into is the library's own list — added to, renamed and
 * deleted in the app (types.js), kept in library.json beside the titles and
 * synced with them. A type keeps its id for good, so a rename touches no
 * title; and it says what it is looked up as, since no provider has heard of
 * "Stand-up". This is the list a library starts with. */
export const DEFAULT_TYPES = [
  { id: 'anime',     label: 'Anime',       lookup: 'anime' },
  { id: 'doc',       label: 'Documentary', lookup: 'doc' },
  { id: 'book',      label: 'Book',        lookup: 'book' },
  { id: 'game',      label: 'Game',        lookup: 'game' },
  { id: 'audiobook', label: 'Audio Book',  lookup: 'book' },
  { id: 'other',     label: 'Other',       lookup: 'other' },
];

/* What a type the list does not name is called: one a provider handed back
 * (a podcast), or one a document filed a title under after it was deleted. */
const BUILT_IN_LABEL = {
  movie: 'Movie', tv: 'TV', anime: 'Anime', doc: 'Documentary', book: 'Book',
  game: 'Game', audiobook: 'Audio Book', podcast: 'Podcast', other: 'Other',
};

/* Every type there is to pick — the two tabs, then Other's list — and what
 * each is called. Both are refilled in place when the list changes, so every
 * module holding them sees a rename; `typesVersion` counts the refills. */
export const TYPES = [];
export const TYPE_LABEL = {};
export let typesVersion = 0;

export const STATUSES = [
  { id: 'queue',    label: 'Queue' },
  { id: 'watching', label: 'Watching' },
  { id: 'watched',  label: 'Watched' },
  { id: 'dropped',  label: 'Skipped' },
];

export const STATUS_LABEL = Object.fromEntries(STATUSES.map((s) => [s.id, s.label]));

export const state = {
  items: [],
  sources: [],
  rev: 0,
  config: null,
  loading: true,
  online: true,
  saving: false,
  dirty: false,
  edits: 0,             // bumped on every local change, so a save can tell
  error: '',            // whether anything landed while it was in flight
  lastSaved: null,
  types: DEFAULT_TYPES.map((t) => ({ ...t })),   // Other's types, in chip order
  typesDirty: false,    // changed here and not yet taken by the server
  typesEdits: 0,
};

/* ------------------------------------------------------------------ types */

function applyTypes() {
  const list = otherTypes();
  TYPES.splice(0, TYPES.length, { id: 'movie', label: 'Movie' }, { id: 'tv', label: 'TV' },
    ...list.map((t) => ({ id: t.id, label: t.label })));
  for (const key of Object.keys(TYPE_LABEL)) delete TYPE_LABEL[key];
  Object.assign(TYPE_LABEL, BUILT_IN_LABEL);
  for (const t of list) TYPE_LABEL[t.id] = t.label;
  typesVersion += 1;
}

/** Other's types, in the order its chips show them. */
export function otherTypes() {
  return Array.isArray(state.types) && state.types.length ? state.types : DEFAULT_TYPES;
}

/** What a title filed under Other with no type in mind becomes: Other's own
 * "Other" while there is one, or else the first type it has. */
export function defaultOther() {
  const list = otherTypes();
  return (list.find((t) => t.id === 'other') || list[0]).id;
}

/** What a type is looked up as, when a provider is asked about it. */
export function lookupKind(type) {
  if (type === 'movie' || type === 'tv' || type === 'any') return type;
  const own = otherTypes().find((t) => t.id === type);
  if (own) return own.lookup;
  if (type === 'audiobook') return 'book';
  return BUILT_IN_LABEL[type] ? type : 'other';
}

/** Other's types, replaced: one added, renamed or taken away. */
export function setOtherTypes(list) {
  const before = state.types;
  state.types = list.map(({ id, label, lookup }) => ({ id, label, lookup }));
  recordList('types', before, state.types);
  state.typesDirty = true;
  state.typesEdits += 1;
  applyTypes();
  markDirty();
}

applyTypes();

/* Which fields of which items this browser has changed and not yet pushed.
 *
 * The server's fill-in pass writes to the same items you are editing — you
 * add a title, it goes to fetch the poster, you fix the year while it is
 * away — and "newest copy wins" throws one side's work out: either your year
 * or its poster, whichever was written first. So the merge is by field.
 * Nothing here is sent anywhere; it is only the memory of what is yours. */
const touched = new Map();      // id -> Set of field names

function note(item, fields) {
  let set = touched.get(item.id);
  for (const key of Object.keys(fields)) {
    if (!set) { set = new Set(); touched.set(item.id, set); }
    set.add(key);
  }
}

/* ------------------------------------------------------------------ utils */

export const uid = () =>
  (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : Math.random().toString(36).slice(2) + Date.now().toString(36));

export const nowISO = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');

export const live = () => state.items.filter((i) => !i.deleted);

export function newItem(partial = {}) {
  const now = nowISO();
  return {
    id: uid(),
    title: '',
    year: null,
    type: 'movie',
    status: 'queue',
    rating: null,
    heart: false,
    tags: [],
    links: [],
    notes: '',
    poster: '',
    overview: '',
    runtime: null,
    genres: [],
    creator: '',
    source: '',
    sourceId: '',
    imdbId: '',
    wikiUrl: '',
    appleTv: '',
    extRating: null,
    cast: [],
    certification: '',
    order: null,
    addedAt: now,
    addedBy: (state.config && state.config.me && state.config.me.name) || '',
    watchedAt: null,
    updatedAt: now,
    deleted: false,
    ...partial,
  };
}

/* A title reduced to what two spellings of it have in common.
 *
 * The same fold as server/match.py, because the two must agree about what
 * counts as the same title. Google Docs writes an apostrophe as ’, so the
 * library holds "Can’t Buy Me Love" while a keyboard types "Can't"; the
 * accent on "Amélie" is optional to whoever is typing; and "&" and "and"
 * are the same word. None of that should decide whether a search finds a
 * film, or whether an import counts as a duplicate. */
export function fold(text) {
  return String(text ?? '')
    .normalize('NFKD')
    .replace(/\p{M}+/gu, '')                 // é has already become e + ́
    .toLowerCase()
    .replace(/[&+]/g, ' and ')
    .replace(/['\u2018\u2019\u02bc`\u00b4]/g, '')       // "Your's" is "Yours"
    .replace(/[^\p{L}\p{N}_\s]+/gu, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ');
}

const LEADING_ARTICLE = /^(?:the|a|an)\s+/;

/** Loose title match used for de-duplicating imports. */
export function titleKey(title, year) {
  const base = fold(title).replace(LEADING_ARTICLE, '');
  return year ? `${base}|${year}` : base;
}

/* ------------------------------------------------------------------ genres */

/* Providers hand back the ingredients, not the dish: a romantic comedy comes
 * from every one of them as "Comedy" and "Romance" side by side, because no
 * film database carries the compound as a genre of its own. It is the name
 * anyone would actually use for the film, so the pair is shown as one. The
 * stored genres stay as the providers gave them — this is only how they read. */
const GENRE_PAIRS = [
  { parts: ['romance', 'comedy'], label: 'Romantic Comedy' },
];

/** An item's genres as they should be read, compounds folded together. */
export function genreLabels(item) {
  const list = (item && item.genres) || [];
  const have = new Set(list.map((g) => g.toLowerCase()));
  const used = new Set();
  const out = [];

  for (const pair of GENRE_PAIRS) {
    if (!pair.parts.every((p) => have.has(p))) continue;
    pair.parts.forEach((p) => used.add(p));
    out.push(pair.label);
  }
  for (const genre of list) {
    if (!used.has(genre.toLowerCase())) out.push(genre);
  }
  return out;
}

/* --------------------------------------------------------------- listeners */

const listeners = new Set();
export function onChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
// Coalesce bursts of edits into one notification. A timer rather than
// requestAnimationFrame: rAF is starved while the tab is backgrounded, and a
// queued sync must still land.
let frame = 0;
function emit() {
  if (frame) return;
  frame = setTimeout(() => {
    frame = 0;
    listeners.forEach((fn) => fn());
  }, 0);
}
export { emit as notify };

/* --------------------------------------------------------------- transport */

/* The session this page was opened with is gone: the person was removed, or
 * the cookie was. The page is loaded again from the top and the server
 * decides — the gate puts the session back from what this browser kept, or
 * it is Google. Unsent edits are already in localStorage and wait there. */
let leaving = false;
function signedOut() {
  if (leaving) return;
  leaving = true;
  writeLocal();
  globalThis.location?.reload();
}

async function api(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
    credentials: 'same-origin',
  });
  if (res.status === 401) signedOut();
  const text = await res.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch { /* non-JSON error page */ }
  if (!res.ok) {
    const err = new Error((payload && payload.error) || `HTTP ${res.status}`);
    err.status = res.status;
    err.payload = payload;
    throw err;
  }
  return payload;
}

/* ------------------------------------------------------------ local mirror */

function readLocal() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeLocal() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      rev: state.rev,
      items: state.items,
      sources: state.sources,
      dirty: state.dirty,
      types: state.types,
      typesDirty: state.typesDirty,
      // Unsent edits survive a reload, so what made them must too.
      touched: Object.fromEntries([...touched].map(([id, set]) => [id, [...set]])),
      savedAt: nowISO(),
    }));
  } catch {
    /* private mode or quota — the server copy is still authoritative */
  }
}

/** Everything this browser keeps of the library, gone — for signing out on
 * a machine that is not yours. */
export function forgetLocal() {
  try {
    localStorage.removeItem(LS_KEY);
    localStorage.removeItem(STAGE_KEY);
  } catch { /* nothing was kept */ }
}

/* ------------------------------------------------------------------ merge */

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/* One item, both copies. The fields you changed here are yours whichever
 * copy is newer; every other field is whatever the server has, because a
 * difference in a field you never touched can only have come from there —
 * the fill-in pass, or the phone. Only when nothing is known about what
 * changed does it fall back to the newer copy wholesale. */
function mergeItem(mine, remote) {
  const keys = touched.get(remote.id);
  const theirsNewer = (remote.updatedAt || '') > (mine.updatedAt || '');
  if (!keys || !keys.size) return { item: theirsNewer ? remote : mine, ahead: !theirsNewer };

  const merged = { ...remote };
  let ahead = false;
  for (const key of keys) {
    // Already the same on the server: nothing left to defend.
    if (key === 'updatedAt' || same(merged[key], mine[key])) { keys.delete(key); continue; }
    merged[key] = mine[key];
    ahead = true;
  }
  if (!keys.size) touched.delete(remote.id);
  if (ahead) merged.updatedAt = nowISO();
  return { item: merged, ahead };
}

function mergeServer(lib) {
  const byId = new Map(state.items.map((i) => [i.id, i]));
  let localAhead = false;

  for (const remote of lib.items || []) {
    const mine = byId.get(remote.id);
    if (!mine) {
      byId.set(remote.id, remote);
    } else if ((remote.updatedAt || '') !== (mine.updatedAt || '') || touched.has(remote.id)) {
      const { item, ahead } = mergeItem(mine, remote);
      byId.set(remote.id, item);
      if (ahead) localAhead = true;
    }
  }
  // Items only we know about still need pushing.
  const remoteIds = new Set((lib.items || []).map((i) => i.id));
  for (const mine of state.items) if (!remoteIds.has(mine.id)) localAhead = true;

  state.items = [...byId.values()];
  if (Array.isArray(lib.sources) && !state.sources.length) state.sources = lib.sources;
  // The server's list, unless this browser has changed it and not sent it yet.
  // A library that has never had one keeps the starting list.
  if (state.typesDirty) localAhead = true;
  else if (Array.isArray(lib.types) && lib.types.length && !same(lib.types, state.types)) {
    state.types = lib.types;
    applyTypes();
  }
  state.rev = lib.rev || 0;
  return localAhead;
}

/* ------------------------------------------------------------------- sync */

let timer = 0;
let inFlight = null;
let backoff = 1000;

export function markDirty() {
  close();
  state.dirty = true;
  state.edits += 1;
  writeLocal();
  emit();
  clearTimeout(timer);
  timer = setTimeout(() => { sync(); }, SYNC_DEBOUNCE);
}

export async function sync(attempt = 0) {
  if (inFlight) return inFlight;
  if (!state.dirty) return null;

  state.saving = true;
  state.error = '';
  emit();

  inFlight = (async () => {
    // What this save carries. An edit made while it is on the wire is not in
    // it, and must not be marked as sent when it comes back.
    const edits = state.edits;
    const typesEdits = state.typesEdits;
    const sent = new Map([...touched].map(([id, set]) => [id, new Set(set)]));
    try {
      const res = await api('PUT', '/library', {
        rev: state.rev,
        items: state.items,
        sources: state.sources,
        types: state.types,
      });
      state.rev = res.rev;
      state.online = true;
      state.lastSaved = new Date();
      backoff = 1000;
      for (const [id, keys] of sent) {
        const set = touched.get(id);
        if (!set) continue;
        for (const key of keys) set.delete(key);
        if (!set.size) touched.delete(id);
      }
      if (state.typesEdits === typesEdits) state.typesDirty = false;
      if (state.edits === edits) state.dirty = false;
      else { clearTimeout(timer); timer = setTimeout(() => { sync(); }, SYNC_DEBOUNCE); }
      writeLocal();
    } catch (err) {
      if (err.status === 409 && err.payload && err.payload.library && attempt < 4) {
        mergeServer(err.payload.library);
        inFlight = null;
        state.saving = false;
        return sync(attempt + 1);
      }
      state.online = false;
      state.error = err.message || 'save failed';
      writeLocal();
      // Keep trying: the phone may just be between wifi and cellular.
      clearTimeout(timer);
      timer = setTimeout(() => sync(), backoff);
      backoff = Math.min(backoff * 2, 30000);
    } finally {
      state.saving = false;
      inFlight = null;
      emit();
    }
    return null;
  })();

  return inFlight;
}

/** Pull the server copy and fold it in (used on focus and on a slow poll). */
export async function refresh({ force = false } = {}) {
  if (state.dirty && !force) return;
  try {
    const lib = await api('GET', '/library');
    if (lib.rev === state.rev && !force) { state.online = true; emit(); return; }
    const ahead = mergeServer(lib);
    state.online = true;
    if (ahead) markDirty(); else writeLocal();
    emit();
  } catch {
    state.online = false;
    emit();
  }
}

export async function boot() {
  const local = readLocal();
  if (local && Array.isArray(local.items)) {
    state.items = local.items;
    state.sources = local.sources || [];
    state.rev = local.rev || 0;
    state.dirty = !!local.dirty;
    if (Array.isArray(local.types) && local.types.length) {
      state.types = local.types;
      state.typesDirty = !!local.typesDirty;
      applyTypes();
    }
    for (const [id, keys] of Object.entries(local.touched || {})) {
      if (Array.isArray(keys) && keys.length) touched.set(id, new Set(keys));
    }
  }

  try {
    state.config = await api('GET', '/config');
  } catch { /* offline start is fine */ }

  try {
    const lib = await api('GET', '/library');
    const ahead = mergeServer(lib);
    state.online = true;
    if (ahead || state.dirty) markDirty();
  } catch (err) {
    state.online = false;
    state.error = err.message || 'offline';
  }

  state.loading = false;
  emit();

  addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  addEventListener('online', () => { refresh(); if (state.dirty) sync(); });
  setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
  // Best effort flush if the tab is closed mid-edit.
  addEventListener('pagehide', () => { if (state.dirty) writeLocal(); });
}

/* ----------------------------------------------------------------- scores */

/* IMDb's score for each title, by IMDb id, from the server's copy of IMDb's
 * daily ratings file. Kept beside the library rather than in it: the number
 * changes every day and is nobody's edit, so it is not synced, merged or
 * saved — only looked up. `null` is an answer too: asked, and IMDb has none.
 *
 * The whole library is asked for once, and again twice a day. Between those,
 * anything with an id not yet asked about — a title just added, or one the
 * fill-in pass has just identified — is asked about on the next change. */
const scores = new Map();
const asking = new Set();
const SCORES_EVERY = 12 * 3600 * 1000;
const SCORES_RETRY = 60 * 1000;
let scoresAt = 0;
let scoresFailed = 0;
let scoresBusy = false;

const imdbKey = (item) => String(item.imdbId || '').trim().toLowerCase();

/** Someone else's score for a title, or null: IMDb's where there is one,
 * else what TMDB said when the title was filled in. Takes a library item or
 * a provider's answer, which may carry the IMDb score with it. */
export function scoreOf(item) {
  const imdb = item.imdbScore || scores.get(imdbKey(item));
  if (imdb) return { source: 'imdb', value: imdb[0] / 10, votes: imdb[1] };
  if (item.extRating) return { source: 'tmdb', value: item.extRating / 10, votes: 0 };
  return null;
}

async function wantScores() {
  if (scoresBusy || state.loading || !state.online) return;
  if (Date.now() - scoresFailed < SCORES_RETRY) return;
  const whole = Date.now() - scoresAt > SCORES_EVERY;
  const ids = whole ? [] : [...new Set(state.items.map(imdbKey))]
    .filter((id) => id && !scores.has(id) && !asking.has(id)).slice(0, 300);
  if (!whole && !ids.length) return;

  scoresBusy = true;
  ids.forEach((id) => asking.add(id));
  try {
    const query = new URLSearchParams();
    for (const id of ids) query.append('id', id);
    const answer = await api('GET', `/ratings${ids.length ? `?${query}` : ''}`);
    // The server's file may not have landed yet on a first start. Nothing
    // asked in that minute is an answer, so none of it is written down.
    if (!answer || !answer.titles) { scoresFailed = Date.now(); return; }
    if (whole) { scores.clear(); scoresAt = Date.now(); }
    for (const [id, found] of Object.entries(answer.ratings || {})) scores.set(id, found);
    // Only what was named is known to have no score. The whole-library call
    // asks about the server's copy, which may not have a title added here a
    // moment ago; those are asked about by name on the next change.
    for (const id of ids) if (!scores.has(id)) scores.set(id, null);
    emit();
  } catch {
    scoresFailed = Date.now();
  } finally {
    ids.forEach((id) => asking.delete(id));
    scoresBusy = false;
  }
}
// Every change is a chance that a title has an id it did not have before.
// The check is one pass over the library with nothing to ask, most times.
listeners.add(() => { wantScores(); });

/* ----------------------------------------------------------------- fill-in */

/* The server's fill-in pass, as this page last heard of it.
 *
 * A title just added is handed to it, and what it writes is pulled straight
 * back down while it runs — it writes on the server, and left to itself this
 * page would not ask again for a minute, so the artwork it found would turn
 * up on the next visit rather than in front of you. One watcher, however
 * many titles asked for it. */
export const enrich = {
  running: false, current: '', done: 0, total: 0, filled: 0,
  // What this page has asked for.
  asked: 0,
};

let watcher = 0;

export function watchEnrich() {
  if (watcher) return;
  const tick = async () => {
    let running = false;
    try {
      const status = await api('GET', '/enrich');
      Object.assign(enrich, {
        running: !!status.running, current: status.current || '',
        done: status.done || 0, total: status.total || 0, filled: status.filled || 0,
      });
      running = enrich.running;
      await refresh({ force: true });
    } catch { /* offline for a moment; the next tick tries again */ }
    emit();
    watcher = running ? setTimeout(tick, 2500) : 0;
  };
  watcher = setTimeout(tick, 1200);
}

/** Fill in what these titles are missing, and watch it land.
 *
 * The items have to reach the server first, because the pass works from the
 * server's copy and adding only marks the library dirty; and the pass has to
 * be told which titles, or it sweeps the whole library for them. */
export async function fillIn(ids) {
  if (!ids.length || !state.config || !state.config.network) return false;
  try {
    await sync();
    await api('POST', '/enrich', { action: 'start', scope: 'missing', ids });
  } catch { return false; }
  enrich.running = true;
  enrich.asked += ids.length;
  emit();
  watchEnrich();
  return true;
}

/* ------------------------------------------------------------- just added */

/* The last titles added to the library, newest first — by anyone, since the
 * library is shared, so every browser shows the same list. Nothing is kept
 * for it: it is read off each title's addedAt. */
const JUST_ADDED = 27;

const justAddedMax = () => (state.config && state.config.justAdded) || JUST_ADDED;

/** The latest `limit` titles that `keep` lets through, newest first: the
 * filter goes first, so hiding some still leaves a full list. */
export function recentlyAdded(limit = justAddedMax(), keep = () => true) {
  // Later in the list is later added when two share a moment, so the order
  // is the list's, reversed, and then by date.
  return live().reverse()
    .filter(keep)
    .map((item, at) => [item, at])
    .sort(([a, i], [b, j]) => (b.addedAt || '').localeCompare(a.addedAt || '') || i - j)
    .slice(0, limit)
    .map(([item]) => item);
}

/** A title was added: redraw, so it shows in Just Added. */
export function stage(ids) {
  if (ids && ids.length) emit();
}

/* ---------------------------------------------------------------- history */

/* The way back, and the way forward again.
 *
 * One journal and a cursor rather than two stacks: every entry knows both
 * directions, so Undo walks back along the list and Redo walks forward over
 * the same entries, and an edit made after an undo simply drops whatever
 * future was left.
 *
 * What an entry holds is which fields of which titles changed, and what they
 * held on either side — not a copy of the library. The reason is the one
 * written out at select.js: the server's fill-in pass writes to the very
 * titles you are editing, so putting a whole snapshot back throws away the
 * poster it found while you were deciding. An undo goes in through the same
 * change() as every other edit, so the fields it puts back are this browser's
 * in the merge and are defended against the pass and against the phone.
 *
 * Only replacing the library wholesale keeps a snapshot, because the ids
 * themselves go and no patch can say that.
 */

const journal = [];
const JOURNAL_MAX = 10;
const COALESCE_MS = 1000;

let cursor = 0;        // how far along the journal we are: what Undo takes
let txn = null;        // the change being recorded, still open
let grouped = 0;       // inside edit(), where markDirty must not close it
let groupLabel = '';   // what edit() called it
let replaying = false; // an undo or a redo, which is not an edit of its own

const clone = (value) => (value && typeof value === 'object'
  ? (globalThis.structuredClone ? structuredClone(value) : JSON.parse(JSON.stringify(value)))
  : value);

/* An entry is opened by the first thing that records into it and closed by
 * markDirty(), which every mutation here ends with exactly once. Opening is
 * also what drops the redo future — not markDirty, which is called as well
 * when a merge leaves this browser ahead of the server (boot, refresh), and a
 * poll in the background must not throw away what you could still redo. */
function open(label) {
  if (replaying) return null;
  if (txn) {
    if (!txn.label) txn.label = label || groupLabel || '';
    return txn;
  }
  const name = label || groupLabel || '';
  const last = journal[cursor - 1];
  /* Holding the arrow key on a queue row, or tapping along a row of stars:
   * one step back, not twelve. */
  if (last && name && last.label === name && !last.snapshot
      && Date.now() - last.at < COALESCE_MS) {
    journal.length = cursor - 1;
    cursor -= 1;
    txn = last;
    return txn;
  }
  journal.length = cursor;
  txn = { label: name, before: new Map(), after: new Map(),
          types: null, sources: null, snapshot: null, at: 0 };
  return txn;
}

function close() {
  if (grouped || !txn) return;
  const entry = txn;
  txn = null;
  if (!entry.before.size && !entry.types && !entry.sources && !entry.snapshot) return;
  if (entry.snapshot) {
    entry.snapshot.after = shot();
    journal.length = 0;        // one step back past a replacement, no further
  }
  entry.at = Date.now();
  journal.push(entry);
  if (journal.length > JOURNAL_MAX) journal.splice(0, journal.length - JOURNAL_MAX);
  cursor = journal.length;
}

/** One undo step, named: everything `fn` changes is a single entry, however
 * many mutations it makes. A nested call joins the one already open. */
export function edit(label, fn) {
  if (replaying) return fn();
  if (!grouped && !txn) groupLabel = label;
  grouped += 1;
  try {
    return fn();
  } finally {
    grouped -= 1;
    if (!grouped) { close(); groupLabel = ''; }
  }
}

/* What these fields held before this change, and what they hold after.
 * Kept by id and cloned, both on purpose: a merge hands out fresh item
 * objects, so a held reference goes stale mid-session, and an import pushes
 * into tags and links in place, so an uncloned array would quietly follow the
 * change it is meant to remember. The first value wins and the last change
 * wins, which is what makes a grouped edit one step. */
function record(item, changed) {
  const entry = open();
  if (!entry) return;
  let before = entry.before.get(item.id);
  if (!before) { before = {}; entry.before.set(item.id, before); }
  let after = entry.after.get(item.id);
  if (!after) { after = {}; entry.after.set(item.id, after); }
  for (const key of Object.keys(changed)) {
    if (!(key in before)) before[key] = clone(item[key] ?? null);
    after[key] = clone(changed[key]);
  }
}

/* Undoing an add puts a tombstone on it rather than taking it out of the
 * list. By the time Undo is pressed the save may well have landed, and the
 * merge re-sends anything the server has that this browser does not — so a
 * title spliced out here would simply come back. A tombstone is how this app
 * deletes anyway. (The strip of what was just added drops it on the way past,
 * and a redo does not put it back on the strip; the title itself returns.) */
function recordAdd(created) {
  const entry = open();
  if (!entry) return;
  const stamp = nowISO();
  for (const item of created) {
    entry.before.set(item.id, { deleted: true, deletedAt: stamp });
    entry.after.set(item.id, { deleted: false, deletedAt: null });
  }
}

function recordList(key, before, after) {
  const entry = open();
  if (!entry) return;
  if (!entry[key]) entry[key] = [clone(before), null];
  entry[key][1] = clone(after);
}

const shot = () => ({
  items: clone(state.items), sources: clone(state.sources), types: clone(state.types),
});

/** The library as it is now, kept whole, for the one change no patch can
 * describe: every id replaced at once. */
function snapshot(label) {
  const entry = open(label);
  if (!entry || entry.snapshot) return;
  entry.snapshot = { before: shot(), after: null };
}

/* A snapshot put back. Everything that has appeared since is tombstoned
 * rather than dropped, and everything restored is stamped and noted as this
 * browser's — without both, the merge would hand the replaced library
 * straight back from the server, which is the bug this had before it could
 * be undone at all. */
function restore(snap) {
  const stamp = nowISO();
  const was = new Map(snap.items.map((i) => [i.id, i]));
  const gone = state.items.filter((i) => !was.has(i.id) && !i.deleted);
  state.items = snap.items.map((i) => clone(i));
  for (const item of state.items) {
    item.updatedAt = stamp;
    note(item, item);                  // every field of it is ours to defend
  }
  for (const item of gone) {
    const dead = { ...clone(item), deleted: true, deletedAt: stamp, updatedAt: stamp };
    state.items.push(dead);
    note(dead, { deleted: true, deletedAt: stamp });
  }
  state.sources = snap.sources.map((s) => ({ ...s }));
  if (Array.isArray(snap.types) && snap.types.length) setOtherTypes(snap.types);
}

function play(entry, back) {
  replaying = true;
  try {
    if (entry.snapshot) {
      restore(back ? entry.snapshot.before : entry.snapshot.after);
    } else {
      const map = back ? entry.before : entry.after;
      if (map.size) patchMany([...map].map(([id, fields]) => [id, clone(fields)]));
      if (entry.types) setOtherTypes(back ? entry.types[0] : entry.types[1]);
      if (entry.sources) state.sources = (back ? entry.sources[0] : entry.sources[1]).map((s) => ({ ...s }));
    }
  } finally {
    replaying = false;
  }
}

export const canUndo = () => cursor > 0;
export const canRedo = () => cursor < journal.length;
export const undoLabel = () => (cursor > 0 ? journal[cursor - 1].label : '');
export const redoLabel = () => (cursor < journal.length ? journal[cursor].label : '');

/** The entry an action has just made, for a toast that offers to take that
 * one change back. */
export const current = () => (cursor > 0 ? journal[cursor - 1] : null);

export function undo() {
  if (!canUndo()) return null;
  const entry = journal[cursor - 1];
  play(entry, true);
  cursor -= 1;
  markDirty();
  return entry.label || 'that change';
}

export function redo() {
  if (!canRedo()) return null;
  const entry = journal[cursor];
  play(entry, false);
  cursor += 1;
  markDirty();
  return entry.label || 'that change';
}

/** Take back the one change this entry describes, if it is still the change
 * Undo would take back. Answers whether it did: a toast that has sat there
 * while other edits landed falls back to patching it back by hand, and that
 * patch becomes an entry of its own, which is what it is. */
export function undoIfCurrent(entry) {
  if (!entry || current() !== entry) return false;
  undo();
  return true;
}

/* -------------------------------------------------------------- mutations */

function touch(item) {
  item.updatedAt = nowISO();
  return item;
}

export function addItem(partial) {
  const item = newItem(partial);
  state.items.push(item);
  recordAdd([item]);
  markDirty();
  return item;
}

export function addMany(list) {
  const created = list.map((p) => newItem(p));
  state.items.push(...created);
  recordAdd(created);
  markDirty();
  return created;
}

export function getItem(id) {
  return state.items.find((i) => i.id === id) || null;
}

/* Only what actually changes is yours to defend in a merge: the editor saves
 * every field it shows, edited or not. True when anything did change. */
function change(item, fields) {
  const changed = {};
  for (const [key, value] of Object.entries(fields)) {
    if (!same(item[key], value)) changed[key] = value;
  }
  if (!Object.keys(changed).length) return false;
  record(item, changed);
  Object.assign(item, changed);
  note(item, changed);
  touch(item);
  return true;
}

export function patchItem(id, fields) {
  const item = getItem(id);
  if (!item) return null;
  if (change(item, fields)) markDirty();
  return item;
}

/** The same patch as patchItem, to many titles and saved once — a hundred
 * titles ticked at a time would otherwise write the library out a hundred
 * times over. Takes [[id, fields], …]; answers how many actually changed. */
export function patchMany(patches) {
  let changed = 0;
  for (const [id, fields] of patches) {
    const item = getItem(id);
    if (item && change(item, fields)) changed += 1;
  }
  if (changed) markDirty();
  return changed;
}

export function removeItem(id) {
  const item = getItem(id);
  if (!item) return null;
  return patchItem(id, { deleted: true, deletedAt: nowISO() });
}

/** Status changes carry the watched date with them. */
export function statusFields(item, status) {
  const fields = { status };
  if (status === 'watched' && !item.watchedAt) fields.watchedAt = nowISO();
  if (status !== 'watched') fields.watchedAt = null;
  return fields;
}

export function setStatus(id, status) {
  const item = getItem(id);
  if (!item) return null;
  return patchItem(id, statusFields(item, status));
}

export function toggleWatched(id) {
  const item = getItem(id);
  if (!item) return null;
  return setStatus(id, item.status === 'watched' ? 'queue' : 'watched');
}

export function toggleHeart(id) {
  const item = getItem(id);
  if (!item) return null;
  return patchItem(id, { heart: !item.heart });
}

export function setRating(id, rating) {
  return patchItem(id, { rating: rating || null });
}

/* ------------------------------------------------------------ queue order */

/* `order` is the hand-made position of a title in its section's queue.
 * Null means "never placed" and sorts to the bottom, so something you just
 * added does not jump the line. */

/** Write positions 0..n-1 in the order the ids are given. One save for the
 * whole queue, and one step back: patchMany skips the titles already in
 * place, so only what moved is remembered. */
export function reorderQueue(ids) {
  return patchMany(ids.map((id, index) => [id, { order: index }])) > 0;
}

export function replaceAll(items, sources) {
  snapshot('replace the library');
  state.items = items;
  if (sources) state.sources = sources;
  markDirty();
}

/* ---------------------------------------------------------------- sources */

export function addSource(url, title = '', tags = []) {
  const clean = String(url || '').trim();
  if (!/^https?:\/\//i.test(clean)) return null;
  if (state.sources.some((s) => s.url === clean)) return null;
  const before = state.sources.slice();
  const source = { id: uid(), url: clean, title, tags, note: '', addedAt: nowISO() };
  state.sources.push(source);
  recordList('sources', before, state.sources);
  markDirty();
  return source;
}

export function removeSource(id) {
  const before = state.sources.slice();
  state.sources = state.sources.filter((s) => s.id !== id);
  recordList('sources', before, state.sources);
  markDirty();
}

/* ----------------------------------------------------------- derived data */

export function allTags(items = live()) {
  const counts = new Map();
  for (const item of items) {
    for (const tag of item.tags) counts.set(tag, (counts.get(tag) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

/* The age ratings the library actually holds, the ones anyone recognises
 * first. Providers return whatever board rated the release they know about,
 * so past the familiar names there is a long tail of one-offs — AL, Btl,
 * IIA, 6+ — worth listing only because a title here carries them. */
const CERT_ORDER = ['G', 'PG', 'PG-13', 'R', 'NC-17',
  'TV-Y', 'TV-Y7', 'TV-G', 'TV-PG', 'TV-14', 'TV-MA', 'NR'];

/** [certification, count], familiar ratings first, "not rated" last. */
export function allCerts(items = live()) {
  const counts = new Map();
  for (const item of items) {
    const cert = item.certification || '';
    counts.set(cert, (counts.get(cert) || 0) + 1);
  }
  const rank = (cert) => {
    if (!cert) return 999;
    const at = CERT_ORDER.indexOf(cert);
    return at === -1 ? 500 : at;
  };
  return [...counts.entries()]
    .sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]));
}

/** [genre, count] as the providers stored them, most common first. Spelled
 * the way the first title carrying it spelled it; matched without case. */
export function allGenres(items = live()) {
  const counts = new Map();
  const spelt = new Map();
  for (const item of items) {
    for (const genre of new Set((item.genres || []).map((g) => g.trim()).filter(Boolean))) {
      const key = genre.toLowerCase();
      if (!spelt.has(key)) spelt.set(key, genre);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  return [...counts.entries()]
    .map(([key, n]) => [spelt.get(key), n])
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export function stats(rows = live()) {
  const out = { total: rows.length, watched: 0, queue: 0, watching: 0, dropped: 0, hearts: 0, rated: 0, ratingSum: 0 };
  for (const item of rows) {
    out[item.status] = (out[item.status] || 0) + 1;
    if (item.heart) out.hearts += 1;
    if (item.rating) { out.rated += 1; out.ratingSum += item.rating; }
  }
  out.avg = out.rated ? out.ratingSum / out.rated : 0;
  return out;
}

export { api };
