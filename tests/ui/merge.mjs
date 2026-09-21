/* What happens to a title while two things are writing to it.
 *
 * The fill-in pass writes on the server; the person writes here. "Johnny
 * Allegro" was typed as "johnny allegro 1949", the pass went and found the
 * poster, the year was fixed by hand while it was away, and one of those two
 * writes was thrown out — whichever came second, wholesale. So the merge is
 * by field now: what was changed here is kept, everything else is taken from
 * the server, and the poster and the year both survive.
 *
 * Also here: the tick that lets a title linger before it leaves the list,
 * and the strip of what was just added.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const calls = [];
let served = null;              // what the server answers to GET /library
let conflict = null;            // a 409 to answer the next PUT with, once
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || 'GET';
  calls.push(`${method} ${url}`);
  if (url.endsWith('/api/library') && method === 'PUT' && conflict) {
    const body = conflict;
    conflict = null;
    return { ok: false, status: 409, text: async () => JSON.stringify(body) };
  }
  if (url.endsWith('/api/library') && method === 'PUT') {
    const sent = JSON.parse(init.body);
    served = { rev: (served?.rev || 0) + 1, items: sent.items, sources: sent.sources };
    return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true, rev: served.rev }) };
  }
  if (url.endsWith('/api/library')) {
    return { ok: true, status: 200, text: async () => JSON.stringify(served || { rev: 0, items: [] }) };
  }
  return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true, running: false }) };
};

const store = await import('./store.js');
const { filters, apply, lingering } = await import('./filters.js');
const views = await import('./views.js');
const { N } = await import('./dom.mjs');
store.state.config = { network: true, providers: {} };

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));

/* ------------------------------------------------- the pass and the person */

const item = store.addItem({ title: 'johnny allegro 1949', type: 'movie', status: 'queue' });
await store.sync();
check('the new title reached the server', served.items.length, 1);

// The pass finds the poster and writes it on the server, a second later.
await tick(5);
const theirs = JSON.parse(JSON.stringify(served));
theirs.rev += 1;
Object.assign(theirs.items[0], {
  title: 'Johnny Allegro', poster: '/api/img?u=allegro', cast: ['George Raft'],
  imdbId: 'tt0041527', updatedAt: store.nowISO(),
});
served = theirs;

// Meanwhile the year is fixed here, on a copy that knows nothing of that.
await tick(5);
store.patchItem(item.id, { year: 1949 });
check('the local copy is behind the server', store.state.rev < served.rev, true);

// The push lands on the newer revision: a conflict, and a merge.
conflict = { error: 'conflict', rev: served.rev, library: served };
await store.sync();
await tick(5);

const merged = store.getItem(item.id);
check('the poster the pass found survived the edit made while it was away',
  [merged.poster, merged.cast, merged.imdbId],
  ['/api/img?u=allegro', ['George Raft'], 'tt0041527']);
check('and the corrected name came with it', merged.title, 'Johnny Allegro');
check('and the year fixed here survived the pass', merged.year, 1949);
check('the merged copy was pushed back', served.items[0].year, 1949);
check('with the poster still on it', served.items[0].poster, '/api/img?u=allegro');

/* A field cleared on purpose stays cleared: the server's older value does
   not creep back in under the merge. */
store.patchItem(item.id, { cast: [] });
conflict = { error: 'conflict', rev: served.rev + 1,
             library: { ...served, rev: served.rev + 1 } };
await store.sync();
await tick(5);
check('a field emptied here is not refilled from an older server copy',
  store.getItem(item.id).cast, []);

/* And with nothing changed here, the server's newer copy is simply taken. */
const newer = JSON.parse(JSON.stringify(served));
newer.rev += 1;
newer.items[0].runtime = 81;
newer.items[0].updatedAt = '2099-01-01T00:00:00Z';
served = newer;
await store.refresh({ force: true });
check('a server write to a field untouched here lands', store.getItem(item.id).runtime, 81);

/* ------------------------------------------------------- the ticked title */

// The refresh took the server's copy, so the object is a new one.
const mine = store.getItem(item.id);
filters.section = 'movie';
filters.view = 'queue';
filters.q = '';
check('a queued title is in the queue', apply([mine]).map((i) => i.id), [item.id]);
store.setStatus(item.id, 'watched');
check('ticked, it is out of the queue', apply([mine]).length, 0);
lingering.add(item.id);
check('but held in the queue while it lingers', apply([mine]).length, 1);
filters.view = 'watched';
check('and it is in the watched list either way', apply([mine]).length, 1);
lingering.delete(item.id);
filters.view = 'queue';
check('and gone once the moment is over', apply([mine]).length, 0);

/* The card says what is happening to it. */
lingering.add(item.id);
const on = { leaving: (i) => lingering.has(i.id), watched() {}, heart() {}, rate() {},
             open() {}, tag() {}, genre() {}, cert() {}, year() {} };
const card = views.card(mine, on);
check('a lingering card is drawn watched and on its way out',
  [card.classList.has('is-watched'), card.classList.has('is-leaving')], [true, true]);
const tickBtn = card.find((n) => n.classList.has('check'))[0];
check('the tick carries the mark whether or not it is ticked',
  tickBtn.find((n) => n.tagName === 'SVG').length, 1);
check('and says what it is for', tickBtn.attrs.title.includes('undo'), true);
lingering.delete(item.id);
const plain = views.card({ ...mine, status: 'queue' }, on);
check('an unticked one carries a ghost of the mark',
  plain.find((n) => n.classList.has('check'))[0].find((n) => n.tagName === 'SVG').length, 1);

/* ----------------------------------------------------------- the strip */

const second = store.addItem({ title: 'The Weather Girl', type: 'movie' });
store.stage([item.id, second.id]);
check('the strip lists what was added, newest first',
  store.staged().map((i) => i.title), ['The Weather Girl', 'Johnny Allegro']);

const strip = new N('div');
views.renderStaging(strip, store.staged(), on, { running: true, current: 'The Weather Girl',
                                                 onClear() {} });
check('the strip is drawn with a card per title',
  strip.find((n) => n.classList.has('card')).length, 2);
check('a title still waiting on its artwork is marked as waiting',
  strip.find((n) => n.classList.has('is-pending')).length, 1);
check('and the heading says what the pass is on',
  strip.find((n) => n.classList.has('strip-note'))[0].text().includes('The Weather Girl'), true);

store.unstage([second.id]);
check('one can be taken off the strip', store.staged().map((i) => i.title), ['Johnny Allegro']);
store.unstage();
check('or all of them', store.staged().length, 0);
views.renderStaging(strip, store.staged(), on, { running: false, current: '', onClear() {} });
check('and an empty strip is hidden', strip.hidden, true);

/* --------------------------------------------- looked up from the search */

const { rowToItem } = await import('./importer.js');
const row = { title: 'The Fuller Brush Man', year: 1948, type: 'movie', source: 'tmdb',
              sourceId: 'movie/1', poster: '/api/img?u=f', cast: ['Red Skelton'],
              link: 'https://www.themoviedb.org/movie/1', extRating: 64 };
const made = rowToItem(row, { type: 'movie', status: 'watched' });
check('a found row becomes the item the + box would make',
  [made.title, made.year, made.type, made.status, made.poster, made.cast, made.links.length,
   Boolean(made.watchedAt)],
  ['The Fuller Brush Man', 1948, 'movie', 'watched', '/api/img?u=f', ['Red Skelton'], 1, true]);
check('a kind of "any" does not become the item type', rowToItem(row, { type: 'any' }).type, 'movie');
check('unless the row has none', rowToItem({ title: 'X' }, { type: 'any' }).type, 'other');

const taken = [];
const found = views.foundRow(row, { badge: 'best match', on: {
  add: (r) => taken.push(['add', r.title]), watched: (r) => taken.push(['watched', r.title]), open() {},
} });
const buttons = found.find((n) => n.tagName === 'BUTTON');
check('a found row offers the queue and the watched pile',
  buttons.map((b) => b.text()), ['Add', 'Watched']);
buttons[1].fire('click');
check('and the watched one says so', taken, [['watched', 'The Fuller Brush Man']]);
check('the best match is labelled', found.text().includes('best match'), true);
const owned = views.foundRow(row, { mine: { id: 'x', title: 'The Fuller Brush Man', type: 'movie' },
                                    on: { add() {}, watched() {}, open() {} } });
check('one already yours says Added instead',
  owned.find((n) => n.tagName === 'BUTTON').map((b) => b.text()), ['Added']);

console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
