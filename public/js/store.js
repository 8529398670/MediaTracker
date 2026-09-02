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

export const TYPES = [
  { id: 'movie',   label: 'Movie' },
  { id: 'tv',      label: 'TV' },
  { id: 'anime',   label: 'Anime' },
  { id: 'doc',     label: 'Documentary' },
  { id: 'book',    label: 'Book' },
  { id: 'game',    label: 'Game' },
  { id: 'podcast', label: 'Podcast' },
  { id: 'other',   label: 'Other' },
];

export const STATUSES = [
  { id: 'queue',    label: 'Queue' },
  { id: 'watching', label: 'Watching' },
  { id: 'watched',  label: 'Watched' },
  { id: 'dropped',  label: 'Skipped' },
];

export const TYPE_LABEL = Object.fromEntries(TYPES.map((t) => [t.id, t.label]));
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
  error: '',
  lastSaved: null,
};

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

/** Loose title match used for de-duplicating imports. */
export function titleKey(title, year) {
  const base = String(title || '')
    .toLowerCase()
    .replace(/^(the|a|an)\s+/, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
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

async function api(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
    credentials: 'same-origin',
  });
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
      savedAt: nowISO(),
    }));
  } catch {
    /* private mode or quota — the server copy is still authoritative */
  }
}

/* ------------------------------------------------------------------ merge */

function mergeServer(lib) {
  const byId = new Map(state.items.map((i) => [i.id, i]));
  let localAhead = false;

  for (const remote of lib.items || []) {
    const mine = byId.get(remote.id);
    if (!mine) {
      byId.set(remote.id, remote);
    } else if ((remote.updatedAt || '') > (mine.updatedAt || '')) {
      byId.set(remote.id, remote);
    } else if ((mine.updatedAt || '') > (remote.updatedAt || '')) {
      localAhead = true;
    }
  }
  // Items only we know about still need pushing.
  const remoteIds = new Set((lib.items || []).map((i) => i.id));
  for (const mine of state.items) if (!remoteIds.has(mine.id)) localAhead = true;

  state.items = [...byId.values()];
  if (Array.isArray(lib.sources) && !state.sources.length) state.sources = lib.sources;
  state.rev = lib.rev || 0;
  return localAhead;
}

/* ------------------------------------------------------------------- sync */

let timer = 0;
let inFlight = null;
let backoff = 1000;

export function markDirty() {
  state.dirty = true;
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
    try {
      const res = await api('PUT', '/library', {
        rev: state.rev,
        items: state.items,
        sources: state.sources,
      });
      state.rev = res.rev;
      state.dirty = false;
      state.online = true;
      state.lastSaved = new Date();
      backoff = 1000;
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

export function patchItem(id, fields) {
  const item = getItem(id);
  if (!item) return null;
  Object.assign(item, fields);
  touch(item);
  markDirty();
  return item;
}

export function removeItem(id) {
  const item = getItem(id);
  if (!item) return null;
  item.deleted = true;
  item.deletedAt = nowISO();
  touch(item);
  markDirty();
  return item;
}

/** Status changes carry the watched date with them. */
export function setStatus(id, status) {
  const item = getItem(id);
  if (!item) return null;
  const fields = { status };
  if (status === 'watched' && !item.watchedAt) fields.watchedAt = nowISO();
  if (status !== 'watched') fields.watchedAt = null;
  return patchItem(id, fields);
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
