/* Other's types, added, renamed and deleted in the app.
 *
 * The six Other started with are entries in the library's own list like any
 * other: each can be renamed, which changes the name everywhere and touches
 * no title, or deleted, which first moves its titles to a type picked in the
 * same sheet. Every change says what it will do on its button, and has an
 * Undo. The list is library data: it syncs with the titles, and a browser
 * that has not changed it takes the server's.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const puts = [];
let served = null;
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || 'GET';
  const reply = (body) => ({ ok: true, status: 200, text: async () => JSON.stringify(body) });
  if (url.endsWith('/api/library') && method === 'PUT') {
    puts.push(JSON.parse(init.body));
    return reply({ ok: true, rev: puts.length });
  }
  if (url.endsWith('/api/library')) return reply(served);
  return reply({ ok: true });
};

const store = await import('./store.js');
const { filters, apply, sectionKinds, pickType, pickedTypes, addingType } = await import('./filters.js');
const types = await import('./types.js');
const { rowToItem } = await import('./importer.js');

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));

const host = document.getElementById('sheet-host');
const toasts = document.getElementById('toast-host');
const inSheet = (pred) => host.find(pred);
const sheetTitle = () => (inSheet((n) => n.tagName === 'H2')[0] || { textContent: '' }).textContent;
const primary = () => inSheet((n) => n.tagName === 'BUTTON'
  && (n.classList.has('primary') || n.classList.has('danger')) && n.classList.has('grow'))[0];
const typeInto = (text) => {
  const box = inSheet((n) => n.tagName === 'INPUT')[0];
  box.value = text;
  box.fire('input');
};
const pressedLookup = () => (inSheet((n) => n.tagName === 'BUTTON'
  && n.getAttribute('aria-pressed') === 'true')[0] || { textContent: '' }).textContent;
const hint = () => (inSheet((n) => n.classList.has('type-clash'))[0] || { textContent: '' }).textContent;
const undoLast = () => toasts.children[toasts.children.length - 1]
  .find((n) => n.tagName === 'BUTTON' && n.text() === 'Undo')[0].fire('click');
const ids = () => store.otherTypes().map((t) => t.id);

const now = '2026-01-01T00:00:00Z';
const make = (id, title, type, extra = {}) => ({
  id, title, year: null, type, status: 'queue', rating: null, heart: false, tags: [],
  links: [], notes: '', poster: '', overview: '', runtime: null, genres: [], creator: '',
  cast: [], certification: '', order: null, addedAt: now, watchedAt: null, updatedAt: now,
  deleted: false, ...extra,
});
store.state.items = [
  make('a1', 'Into Thin Air', 'audiobook'),
  make('b1', 'Dune', 'book', { order: 4 }),
  make('b2', 'Emma', 'book', { order: 7 }),
  make('p1', 'The Daily', 'podcast'),
  make('m1', 'Heat', 'movie'),
];
filters.section = 'other';
filters.view = 'list';
filters.q = '';

/* --------------------------------------------------------- the starting list */

check('Other starts with the six it had', ids(),
  ['anime', 'doc', 'book', 'game', 'audiobook', 'other']);
check('every Type menu is Movie, TV, then those', store.TYPES.map((t) => t.label),
  ['Movie', 'TV', 'Anime', 'Documentary', 'Book', 'Game', 'Audio Book', 'Other']);
check('a type no list names still has a name', store.TYPE_LABEL.podcast, 'Podcast');
check('the manager lists them all, and the podcast a title carries',
  types.typeRows().map((r) => `${r.label}${r.listed ? '' : '*'} ${r.count}`),
  ['Anime 0', 'Documentary 0', 'Book 2', 'Game 0', 'Audio Book 1', 'Other 0', 'Podcast* 1']);

/* ----------------------------------------------------------------- adding */

types.editType(null);
check('Add asks for a name first', [sheetTitle(), primary().text(), primary().disabled], [
  'Add a type to Other', 'Add', true]);
typeInto('Concert films');
check('a name that says film is looked up as one, until told otherwise', pressedLookup(), 'Film');
typeInto('Book');
check('a name already in the list is refused', [primary().disabled, hint()],
  [true, 'There is a “Book” already.']);
typeInto('Movies');
check('and so is a tab\'s own name', [primary().disabled, hint()],
  [true, 'Movies and TV are tabs of their own.']);
typeInto('Stand-up Comedy');
check('the button says what it will add', [primary().text(), primary().disabled, pressedLookup()],
  ['Add “Stand-up Comedy”', false, 'Anything']);
primary().fire('click');
check('added, at the end of the list', store.otherTypes().at(-1),
  { id: 'stand-up-comedy', label: 'Stand-up Comedy', lookup: 'other' });
check('in every Type menu at once', store.TYPES.at(-1), { id: 'stand-up-comedy', label: 'Stand-up Comedy' });
check('with a chip on the Other tab', sectionKinds(store.live()).map((k) => k.label).includes('Stand-up Comedy'), true);
check('and waiting to go to the server', store.state.typesDirty, true);
check('a second one of the same name would get its own id', types.newTypeId('Stand-up Comedy'),
  'stand-up-comedy-2');
check('a name with no letters it can use still gets one', types.newTypeId('日本'), 'type');

/* --------------------------------------------------------------- renaming */

filters.q = 'audio book';
check('before: "audio book" finds the audio book by its type', apply().map((i) => i.title),
  ['Into Thin Air']);
types.editType(types.typeRows().find((r) => r.id === 'audiobook'));
check('Rename starts from the name it has', [sheetTitle(), primary().disabled],
  ['Rename “Audio Book”', true]);
typeInto('Audiobooks');
check('and says what it will be', primary().text(), 'Rename to “Audiobooks”');
primary().fire('click');
check('renamed everywhere', [store.TYPE_LABEL.audiobook, store.TYPES.find((t) => t.id === 'audiobook').label],
  ['Audiobooks', 'Audiobooks']);
check('and no title touched: it is the same type', store.getItem('a1').type, 'audiobook');
filters.q = 'audiobooks';
check('a search goes by the new name at once', apply().map((i) => i.title), ['Into Thin Air']);
filters.q = 'type:audiobooks';
check('type: goes by the name too', apply().map((i) => i.title), ['Into Thin Air']);
filters.q = '';
undoLast();
check('Undo puts the old name back', store.TYPE_LABEL.audiobook, 'Audio Book');

types.editType(types.typeRows().find((r) => r.id === 'podcast'));
typeInto('Podcasts');
primary().fire('click');
check('renaming a type no list had takes it in, titles and all',
  [store.otherTypes().at(-1), store.getItem('p1').type],
  [{ id: 'podcast', label: 'Podcasts', lookup: 'podcast' }, 'podcast']);

/* --------------------------------------------------------------- deleting */

types.deleteType(types.typeRows().find((r) => r.id === 'game'));
check('an empty type says so, and deletes on the word', [sheetTitle(), primary().text()],
  ['Delete “Game”?', 'Delete “Game”']);
primary().fire('click');
check('gone from the list', ids().includes('game'), false);

pickType('book');
types.deleteType(types.typeRows().find((r) => r.id === 'book'));
check('a type with titles asks where they go, Other first',
  [sheetTitle(), primary().text()], ['Delete “Book”?', 'Delete, and move 2 to Other']);
check('and names them', inSheet((n) => n.tagName === 'LI').map((n) => n.textContent), ['Dune', 'Emma']);
inSheet((n) => n.dataset && n.dataset.type === 'movie')[0].fire('click');
check('another place can be picked — Movie too', [primary().text(),
  inSheet((n) => n.tagName === 'P' && n.classList.has('hint'))[0].textContent],
  ['Delete, and move 2 to Movie', 'They move to the Movies tab, at the back of its queue.']);
primary().fire('click');
check('the titles moved first, to the back of the Movies queue',
  ['b1', 'b2'].map((id) => [store.getItem(id).type, store.getItem(id).order]),
  [['movie', null], ['movie', null]]);
check('the type is gone', ids().includes('book'), false);
check('and so is the chip that was picking it', pickedTypes(), []);
undoLast();
check('Undo puts the type back where it was', ids().indexOf('book'), 2);
check('and the titles back in it, in their places',
  ['b1', 'b2'].map((id) => [store.getItem(id).type, store.getItem(id).order]),
  [['book', 4], ['book', 7]]);

/* ---------------------------------------------------- what is left of Other */

store.setOtherTypes([{ id: 'other', label: 'Other', lookup: 'other' },
  { id: 'book', label: 'Book', lookup: 'book' }]);
types.deleteType(types.typeRows().find((r) => r.id === 'other'));
primary().fire('click');
check('with "Other" deleted, a title with no type in mind goes to the first left',
  [addingType('other'), rowToItem({ title: 'x' }, { type: 'any' }).type], ['book', 'book']);
check('the last type cannot go: there is nowhere left to put it',
  types.deleteType(types.typeRows().find((r) => r.id === 'book')), null);
types.openTypes();
const lastDelete = inSheet((n) => n.getAttribute && n.getAttribute('aria-label') === 'Delete Book')[0];
check('and its Delete is not offered',
  Boolean(lastDelete.disabled || lastDelete.getAttribute('disabled') !== null), true);

/* ------------------------------------------------------- adding under a type */

store.setOtherTypes(store.DEFAULT_TYPES.concat([{ id: 'concerts', label: 'Concerts', lookup: 'movie' }]));
check('a book found for Audio Book is the audio book',
  rowToItem({ title: 'Dune', type: 'book' }, { type: 'audiobook' }).type, 'audiobook');
check('a film found for Documentary is the documentary',
  rowToItem({ title: 'Life', type: 'movie' }, { type: 'doc' }).type, 'doc');
check('a film found for a type looked up as film keeps that type',
  rowToItem({ title: 'Stop Making Sense', type: 'movie' }, { type: 'concerts' }).type, 'concerts');
check('but a series is a series', rowToItem({ title: 'Cheers', type: 'tv' }, { type: 'concerts' }).type, 'tv');
check('and a lookup is asked the way the type says', [store.lookupKind('concerts'),
  store.lookupKind('audiobook'), store.lookupKind('stand-up')], ['movie', 'book', 'other']);

/* ------------------------------------------------------------------- sync */

await store.sync();
check('the list goes to the server with the titles', puts.at(-1).types.map((t) => t.id).at(-1), 'concerts');
check('and once it has, it is the server\'s to hand out', store.state.typesDirty, false);
served = { rev: 99, items: store.state.items,
  types: [{ id: 'book', label: 'Books', lookup: 'book' }, { id: 'other', label: 'Other', lookup: 'other' }] };
await store.refresh({ force: true });
check('a list changed elsewhere is taken here', [ids(), store.TYPE_LABEL.book], [['book', 'other'], 'Books']);
store.setOtherTypes([...store.otherTypes(), { id: 'zines', label: 'Zines', lookup: 'book' }]);
served = { ...served, rev: 100 };
await store.refresh({ force: true });
check('but not over a change made here that has not been sent', ids(), ['book', 'other', 'zines']);
await tick(900);
check('which then goes', puts.at(-1).types.map((t) => t.id), ['book', 'other', 'zines']);

console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
