/* The way back, and the way forward again.
 *
 * Every change to the library is one step in a journal: what each field held
 * on either side, by id, so a step put back goes in as an ordinary edit and
 * is defended in the merge rather than losing to whatever the fill-in pass
 * wrote while you were deciding. What is under test is that one thing done is
 * one step however many titles or calls it took, that a step holds both
 * directions, that an edit made after going back drops what was ahead, and
 * that the two changes no patch can describe — adding a title, and replacing
 * the library — come back whole.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

let puts = 0;
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || 'GET';
  if (url.endsWith('/api/library') && method === 'PUT') {
    puts += 1;
    return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true, rev: puts }) };
  }
  if (url.endsWith('/api/library')) {
    return { ok: true, status: 200,
             text: async () => JSON.stringify({ rev: puts, items: [], sources: [], types: [] }) };
  }
  return { ok: true, status: 200, text: async () => JSON.stringify({ ok: true }) };
};

const store = await import('./store.js');
store.state.config = { network: false, providers: {} };
store.state.loading = false;
store.state.online = true;

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};
const tick = (ms = 20) => new Promise((r) => setTimeout(r, ms));
/* What the journal keeps is private, so it is read the way the buttons read
 * it: what Undo would take back, and what Redo would put back. */
const where = () => [store.undoLabel(), store.redoLabel()];

/* ------------------------------------------------- one edit, both ways */

const film = store.edit('add “Laura”',
  () => store.addItem({ title: 'Laura', year: 1944, type: 'movie' }));
store.edit('rate it', () => store.setRating(film.id, 8));
check('an edit is a step, named', where(), ['rate it', '']);

store.undo();
check('Undo puts the field back', store.getItem(film.id).rating, null);
check('and the step is now ahead', where(), ['add “Laura”', 'rate it']);

store.redo();
check('Redo puts it on again', store.getItem(film.id).rating, 8);
check('and the step is behind again', where(), ['rate it', '']);

/* Only what changed is remembered: the editor saves every field it shows. */
store.edit('edit “Laura”', () => store.patchItem(film.id, { title: 'Laura', notes: 'Preminger' }));
store.undo();
check('an undo leaves the fields that did not change', 
  [store.getItem(film.id).title, store.getItem(film.id).notes], ['Laura', '']);

/* ------------------------------------------------- a step is one thing done */

const many = store.edit('add 3 titles',
  () => store.addMany([{ title: 'Gilda' }, { title: 'The Big Heat' }, { title: 'Pickup' }]));
check('three titles added at once is one step', where(), ['add 3 titles', '']);
store.edit('mark 3 titles watched',
  () => store.patchMany(many.map((i) => [i.id, { status: 'watched' }])));
store.undo();
check('and so is a change to all three', many.map((i) => store.getItem(i.id).status),
  ['queue', 'queue', 'queue']);

/* Two mutations, one thing done: the titles move and the type goes. */
store.edit('delete the type radio', () => {
  store.patchMany(many.map((i) => [i.id, { type: 'other' }]));
  store.setOtherTypes(store.otherTypes().filter((t) => t.id !== 'game'));
});
check('two calls under one name is one step', where(), ['delete the type radio', '']);
store.undo();
check('and both come back together',
  [many.map((i) => store.getItem(i.id).type), store.otherTypes().some((t) => t.id === 'game')],
  [['movie', 'movie', 'movie'], true]);

/* ------------------------------------------------- adding, and taking it back */

store.redo();
const added = store.edit('add “Nightmare Alley”',
  () => store.addItem({ title: 'Nightmare Alley', year: 1947 }));
store.undo();
const dead = store.getItem(added.id);
check('an added title is tombstoned, not dropped', [!!dead, dead && dead.deleted], [true, true]);
check('so the server cannot hand it straight back', store.live().some((i) => i.id === added.id), false);
store.redo();
check('and Redo brings it back', store.getItem(added.id).deleted, false);

/* ------------------------------------------------- what was ahead is dropped */

store.undo();
check('something to redo', store.canRedo(), true);
store.edit('heart it', () => store.toggleHeart(film.id));
check('an edit after going back drops it', [store.canRedo(), store.redoLabel()], [false, '']);

/* ------------------------------------------------- replacing the library */

const kept = store.getItem(film.id);
kept.tags.push('noir');
const before = kept.tags.length;
store.replaceAll([store.newItem({ title: 'Only this' })]);
check('the library is replaced', store.live().map((i) => i.title), ['Only this']);
/* The snapshot is a copy all the way down: the library it came from is still
 * being edited, and an array shared with it would follow the edit. */
kept.tags.push('later');
store.undo();
const back = store.getItem(film.id);
check('the old library comes back', !!back && back.title, 'Laura');
check('with its own arrays, not the live ones', back.tags.length, before);
check('and what replaced it is tombstoned, not left to return',
  store.live().some((i) => i.title === 'Only this'), false);
check('one step back past a replacement, and no further', store.canUndo(), false);

/* ------------------------------------------------- a pull is not an edit */

store.redo();
check('something to undo again', store.canUndo(), true);
const ahead = store.canRedo();
await store.refresh({ force: true });
check('a pull from the server records nothing and keeps the future',
  [store.canUndo(), store.canRedo()], [true, ahead]);

/* ------------------------------------------------- it all reaches the server */

await tick(900);
check('and every step was saved', [store.state.dirty, puts > 0], [false, true]);

console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
