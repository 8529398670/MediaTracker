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
  state.types = list.map(({ id, label, lookup }) => ({ id, label, lookup }));
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
    extRating: null,
    cast: [],
    certification: '',
    order: null,
    addedAt: now,
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
  readStaging();
  emit();

  addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  addEventListener('online', () => { refresh(); if (state.dirty) sync(); });
  setInterval(() => { if (!document.hidden) refresh(); }, POLL_MS);
  // Best effort flush if the tab is closed mid-edit.
  addEventListener('pagehide', () => { if (state.dirty) writeLocal(); });
}

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
  // What this page has asked for, cleared with the strip that shows it.
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

/* ---------------------------------------------------------------- staging */

/* Everything added since the strip at the top of the library was last
 * cleared, newest first. A title goes in as a bare name and the fill-in pass
 * dresses it a few seconds later; the strip is where that can be watched
 * happening — and where a title it could not place is seen to be blank,
 * rather than found blank under its year a month on. */
const STAGE_KEY = 'mt.staging.v1';
const STAGE_MAX = 40;

export const staging = [];        // item ids

function readStaging() {
  try {
    const raw = JSON.parse(localStorage.getItem(STAGE_KEY) || '[]');
    if (Array.isArray(raw)) staging.push(...raw.filter((id) => typeof id === 'string'));
  } catch { /* first run */ }
}

function writeStaging() {
  try { localStorage.setItem(STAGE_KEY, JSON.stringify(staging)); } catch { /* ignore */ }
}

/** Put these at the top of the strip, the last one added first. */
export function stage(ids) {
  const fresh = ids.filter((id) => id && !staging.includes(id));
  if (!fresh.length) return;
  staging.unshift(...fresh.reverse());
  staging.length = Math.min(staging.length, STAGE_MAX);
  writeStaging();
  emit();
}

/** Take these out of the strip — or everything, when nothing is named. */
export function unstage(ids = null) {
  const gone = ids ? new Set(ids) : null;
  const keep = gone ? staging.filter((id) => !gone.has(id)) : [];
  if (keep.length === staging.length) return;
  staging.splice(0, staging.length, ...keep);
  if (!staging.length) enrich.asked = 0;
  writeStaging();
  emit();
}

/** The staged titles that still exist, in strip order. One that has been
 * deleted since is dropped from the strip on the way past. */
export function staged() {
  const out = [];
  const keep = [];
  for (const id of staging) {
    const item = getItem(id);
    if (!item || item.deleted) continue;
    out.push(item);
    keep.push(id);
  }
  if (keep.length !== staging.length && !state.loading) {
    staging.splice(0, staging.length, ...keep);
    writeStaging();
  }
  return out;
}

/* -------------------------------------------------------------- mutations */

const undoStack = [];
const UNDO_MAX = 10;

export function checkpoint(label) {
  undoStack.push({ label, items: state.items.map((i) => ({ ...i })) });
  if (undoStack.length > UNDO_MAX) undoStack.shift();
}

export function canUndo() { return undoStack.length > 0; }

export function undo() {
  const snap = undoStack.pop();
  if (!snap) return null;
  state.items = snap.items;
  markDirty();
  return snap.label;
}

function touch(item) {
  item.updatedAt = nowISO();
  return item;
}

export function addItem(partial) {
  const item = newItem(partial);
  state.items.push(item);
  markDirty();
  return item;
}

export function addMany(list) {
  const created = list.map((p) => newItem(p));
  state.items.push(...created);
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

/** Write positions 0..n-1 in the order the ids are given. */
export function reorderQueue(ids) {
  const wanted = new Map(ids.map((id, index) => [id, index]));
  const stamp = nowISO();
  let changed = false;
  for (const item of state.items) {
    const next = wanted.get(item.id);
    if (next === undefined || item.order === next) continue;
    item.order = next;
    item.updatedAt = stamp;
    note(item, { order: next });
    changed = true;
  }
  if (changed) markDirty();
  return changed;
}

export function replaceAll(items, sources) {
  checkpoint('replace library');
  state.items = items;
  if (sources) state.sources = sources;
  markDirty();
}

/* ---------------------------------------------------------------- sources */

export function addSource(url, title = '', tags = []) {
  const clean = String(url || '').trim();
  if (!/^https?:\/\//i.test(clean)) return null;
  if (state.sources.some((s) => s.url === clean)) return null;
  const source = { id: uid(), url: clean, title, tags, note: '', addedAt: nowISO() };
  state.sources.push(source);
  markDirty();
  return source;
}

export function removeSource(id) {
  state.sources = state.sources.filter((s) => s.id !== id);
  markDirty();
}

/* ----------------------------------------------------------- derived data */

export function allTags() {
  const counts = new Map();
  for (const item of live()) {
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
export function allCerts() {
  const counts = new Map();
  for (const item of live()) {
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
