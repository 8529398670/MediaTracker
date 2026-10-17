/* The Other tab's type chips, and picking several titles at once.
 *
 * Other is everything that is not a film or a programme: documentaries and
 * anime as well as books, audio books, games and the old radio serials. A
 * chip for each kind picks one out, or any mix — and only on that tab, so
 * picking Audio Books there does not empty Movies.
 *
 * Select turns the cards into tick boxes, and the bar does one of five things
 * to all of them: watched, skipped, a type, deleted, or stop. Each one asks
 * first, and each change has an Undo that survives a sync in between.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

let puts = 0;
let writes = 0;                 // times the whole library is written to this browser
const setItem = localStorage.setItem.bind(localStorage);
localStorage.setItem = (key, value) => {
  if (key === 'mt.library.v2') writes += 1;
  return setItem(key, value);
};
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || 'GET';
  if (url.endsWith('/api/library') && method === 'PUT') {
    puts += 1;
    return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true, rev: puts }) };
  }
  return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }) };
};

const store = await import('./store.js');
const {
  filters, apply, sectionOf, sections, addingType, activeCount, loadView, facetPool,
} = await import('./filters.js');
const select = await import('./select.js');
const views = await import('./views.js');
const { N } = await import('./dom.mjs');

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};

const host = document.getElementById('sheet-host');
const toasts = document.getElementById('toast-host');
const inSheet = (pred) => host.find(pred);
const button = (text) => inSheet((n) => n.tagName === 'BUTTON' && n.text() === text)[0];
const sheetTitle = () => (inSheet((n) => n.tagName === 'H2')[0] || { textContent: '' }).textContent;
const lastToast = () => toasts.children[toasts.children.length - 1];
const undoLast = () => lastToast().find((n) => n.tagName === 'BUTTON' && n.text() === 'Undo')[0]
  .fire('click');

const now = '2026-01-01T00:00:00Z';
const make = (id, title, type, extra = {}) => ({
  id, title, year: null, type, status: 'queue', rating: null, heart: false, tags: [],
  links: [], notes: '', poster: '', overview: '', runtime: null, genres: [], creator: '',
  cast: [], certification: '', order: null, addedAt: now, watchedAt: null, updatedAt: now,
  deleted: false, ...extra,
});

store.state.items = [
  make('m1', 'Heat', 'movie', { year: 1995 }),
  make('m2', 'Ninotchka', 'movie', { year: 1939, status: 'watched', watchedAt: now }),
  make('t1', 'Cheers', 'tv'),
  make('d1', 'March of the Penguins', 'doc', { year: 2005, order: 3 }),
  make('b1', 'A Court of Thorns and Roses', 'book', { tags: ['audio-books'] }),
  make('b2', 'Into Thin Air', 'book', { tags: ['audio-books'] }),
  make('o1', 'Ma Perkins', 'other', { tags: ['soap-operas'] }),
  make('p1', 'The Daily', 'podcast'),
];
const titles = (rows) => rows.map((item) => item.title);

/* ----------------------------------------------------------- the sections */

check('a section for every type: Movies, TV, the list\'s own, then a stray one a title carries',
  sections().map((s) => s.label),
  ['Movies', 'TV', 'Anime', 'Documentary', 'Book', 'Game', 'Audio Book', 'Other', 'Podcast']);
check('each holds the one type', ['doc', 'anime', 'podcast'].map((type) => sectionOf({ type })),
  ['doc', 'anime', 'podcast']);
check('so a documentary has left the Movies tab', (() => {
  filters.section = 'movie'; filters.view = 'list'; filters.q = '';
  return titles(apply());
})(), ['Heat', 'Ninotchka']);

filters.section = 'book';
check('Book holds the books', titles(apply()), ['A Court of Thorns and Roses', 'Into Thin Air']);
check('and + adds a book there', addingType(), 'book');
check('Movies adds movies', addingType('movie'), 'movie');

filters.q = 'heat';
check('a search reaching past the section finds the film',
  titles(apply(store.live(), { everywhere: true })), ['Heat']);
filters.q = '';

/* ----------------------------------------------------------- the facets */

store.patchItem('m1', { genres: ['Crime', 'Drama'], certification: 'R' });
store.patchItem('m2', { genres: ['Comedy', 'Romance'], certification: 'PG-13' });
filters.section = 'movie';
check('the facets count the list on screen', facetPool().length, 2);
filters.genres = ['romance'];
check('a genre, picked in any case', titles(apply()), ['Ninotchka']);
filters.genres = ['Romance', 'Drama'];
check('two genres: a title has to be both', titles(apply()), []);
filters.genres = [];
filters.certs = ['PG-13', 'R'];
check('two age ratings: either', titles(apply()).sort(), ['Heat', 'Ninotchka']);
filters.certs = ['PG-13'];
check('one: only that', titles(apply()), ['Ninotchka']);
check('and it counts as a filter', activeCount(), 1);
filters.certs = [];

store.patchItem('m1', { status: 'dropped' });
filters.hideSkipped = true;
check('hide skipped takes the skipped ones off the list', titles(apply()), ['Ninotchka']);
filters.q = 'heat';
check('but a search still finds them', titles(apply()), ['Heat']);
filters.q = '';
filters.hideSkipped = false;
store.patchItem('m1', { status: 'queue' });

localStorage.setItem('mt.view.v2', JSON.stringify({ section: 'other', types: ['movie'], sectionTypes: { other: ['book'] }, group: 'type' }));
loadView();
check('the old type filters are dropped on load', [filters.types, filters.sectionTypes, filters.group],
  [undefined, undefined, 'year']);

/* ------------------------------------------------------------- the cards */

const on = {
  open() {}, heart() {}, rate() {}, watched() {}, tag() {}, genre() {}, cert() {}, year() {},
  selected: (item) => select.isPicked(item),
};
const box = (node) => node.children.filter((k) => k instanceof N && k.classList.has('sel')).length;
check('every card carries a tick box, shown only while picking', box(views.card(store.getItem('m1'), on)), 1);

/* --------------------------------------------------------------- picking */

const bar = new N('div');
const list = new N('div');
const selectButton = new N('button');
let changes = 0;
select.wirePicking({ list, barNode: bar, button: selectButton, changed: () => { changes += 1; } });
select.paintPicking({ ids: ['b1', 'b2', 'd1', 'o1', 'p1'], discover: false });

check('nothing is picked before Select is pressed', select.isPicked(store.getItem('b1')), false);
selectButton.fire('click');
check('the Select button starts it', [select.picking.on, selectButton.getAttribute('aria-pressed')],
  [true, 'true']);
check('the bar invites a tap', bar.find((n) => n.classList.has('sel-count'))[0].textContent,
  'Tap to select');
check('and has nothing to act on yet',
  bar.find((n) => n.classList.has('sel-act')).map((n) => Boolean(n.disabled)), [true, true, true, true]);

select.pick('b1');
check('a tap picks one', [...select.picking.ids], ['b1']);
check('a picked card is drawn with the mark',
  views.card(store.getItem('b1'), on).classList.has('is-selected'), true);
select.pick('p1', { range: true, order: ['b1', 'b2', 'd1', 'o1', 'p1'] });
check('shift-click picks the run between', [...select.picking.ids], ['b1', 'b2', 'd1', 'o1', 'p1']);
select.pick('o1', { range: true, order: ['b1', 'b2', 'd1', 'o1', 'p1'] });
check('and lets a run go the same way, both ends included', [...select.picking.ids],
  ['b1', 'b2', 'd1']);
select.unpickAll();
bar.find((n) => n.classList.has('sel-all'))[0].fire('click');
check('Select all takes the whole list on screen', select.picking.ids.size, 5);
check('then offers the way back', bar.find((n) => n.classList.has('sel-all'))[0].textContent,
  'Deselect all');
select.unpickAll();

/* ------------------------------------------------------------- cancelling */

select.pick('b1');
let stopping = select.stopPicking();
check('Cancel with something picked asks first', sheetTitle(), 'Stop selecting?');
button('Keep selecting').fire('click');
check('and keeping on keeps the pick', [await stopping, select.picking.on, select.picking.ids.size],
  [false, true, 1]);
stopping = select.stopPicking();
button('Stop selecting').fire('click');
check('stopping lets it go', [await stopping, select.picking.on, select.picking.ids.size],
  [true, false, 0]);
select.startPicking();
check('with nothing picked there is nothing to ask', [await select.stopPicking(), host.hidden],
  [true, true]);

/* ---------------------------------------------------------------- a type */

select.startPicking();
select.pick('b1');
select.pick('b2');
select.markType();
check('Type asks what they are', sheetTitle(), 'Mark 2 titles as…');
check('and nothing happens until a type is chosen', button('Pick a type') !== undefined, true);
inSheet((n) => n.dataset && n.dataset.type === 'audiobook')[0].fire('click');
check('choosing one says what the button will do', button('Mark 2 as Audio Book') !== undefined, true);
check('and where they end up', inSheet((n) => n.classList.has('hint'))[0].textContent,
  'They move to Audio Book.');
button('Cancel').fire('click');
check('Cancel changes nothing', store.getItem('b1').type, 'book');

select.markType();
inSheet((n) => n.dataset && n.dataset.type === 'audiobook')[0].fire('click');
button('Mark 2 as Audio Book').fire('click');
check('confirmed, both are audio books', [store.getItem('b1').type, store.getItem('b2').type],
  ['audiobook', 'audiobook']);
check('and the pick is over', [select.picking.on, select.picking.ids.size], [false, 0]);
check('the Audio Book section now holds them', (() => {
  const was = filters.section;
  filters.section = 'audiobook';
  const shown = titles(apply());
  filters.section = was;
  return shown;
})(), ['A Court of Thorns and Roses', 'Into Thin Air']);
undoLast();
check('Undo puts them back as books', [store.getItem('b1').type, store.getItem('b2').type],
  ['book', 'book']);
check('with the fields it changed marked as this browser\'s, so a sync cannot undo the undo',
  store.getItem('b1').updatedAt > now, true);

select.startPicking();
select.pick('d1');
select.markType();
inSheet((n) => n.dataset && n.dataset.type === 'movie')[0].fire('click');
check('a type in another section says it moves', inSheet((n) => n.classList.has('hint'))[0].textContent,
  'It moves to Movies.');
button('Mark 1 as Movie').fire('click');
check('arriving in Movies, it goes to the back of that queue',
  [store.getItem('d1').type, store.getItem('d1').order], ['movie', null]);
undoLast();
check('Undo brings its place back too', [store.getItem('d1').type, store.getItem('d1').order],
  ['doc', 3]);

/* ---------------------------------------------------------- watched, skip */

select.startPicking();
select.pick('m1');
select.pick('m2');
let asked = select.markStatus('watched');
check('Watched asks, counting only what will change', sheetTitle(), 'Mark 1 title as watched?');
check('and names it', inSheet((n) => n.tagName === 'LI').map((n) => n.textContent), ['Heat (1995)']);
button('Mark 1 watched').fire('click');
await asked;
check('confirmed, it is watched and dated', [store.getItem('m1').status, Boolean(store.getItem('m1').watchedAt)],
  ['watched', true]);
undoLast();
check('Undo takes the date away with the tick', [store.getItem('m1').status, store.getItem('m1').watchedAt],
  ['queue', null]);

select.startPicking();
select.pick('m2');
check('all of them watched already: nothing to ask', [await select.markStatus('watched'), host.hidden],
  [false, true]);

asked = select.markStatus('dropped');
check('Skipped asks too', sheetTitle(), 'Skip 1 title?');
button('Cancel').fire('click');
check('and a no leaves it watched', [await asked, store.getItem('m2').status], [false, 'watched']);
asked = select.markStatus('dropped');
button('Skip 1').fire('click');
await asked;
check('a yes skips it', store.getItem('m2').status, 'dropped');
undoLast();
check('Undo puts it back watched, with its day', [store.getItem('m2').status, store.getItem('m2').watchedAt],
  ['watched', now]);

/* ---------------------------------------------------------------- delete */

select.startPicking();
select.pick('o1');
select.pick('p1');
asked = select.remove();
check('Delete asks, naming both', [sheetTitle(),
  inSheet((n) => n.tagName === 'LI').map((n) => n.textContent)],
  ['Delete 2 titles?', ['Ma Perkins', 'The Daily']]);
writes = 0;
button('Delete 2').fire('click');
await asked;
check('confirmed, both are gone', store.live().some((item) => ['o1', 'p1'].includes(item.id)), false);
check('in one write of the library, not one per title', writes, 1);
undoLast();
check('Undo brings both back', ['o1', 'p1'].map((id) => store.getItem(id).deleted), [false, false]);

await new Promise((r) => setTimeout(r, 900));
check('and it all reached the server', [store.state.dirty, puts > 0], [false, true]);

console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
