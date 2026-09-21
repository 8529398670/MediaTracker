/* The search box, driven the way it is typed into.
 *
 * A library written by hand and a library written by a phone spell the same
 * title differently, and the search has to close that gap: Google Docs turns
 * an apostrophe into ’, an iOS keyboard turns a quote into “, and nobody
 * types the accent on Amélie. Every case below is a title that was in the
 * library and could not be found.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const store = await import('./store.js');
const { filters, apply, titleMatches, whyMatched } = await import('./filters.js');
const { fold, titleKey } = store;

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};

/* ------------------------------------------------------------------ fold */

check('fold: curly and straight apostrophes agree',
  fold('Can’t Buy Me Love'), fold("Can't Buy Me Love"));
check('fold: no apostrophe at all agrees too',
  fold('Cant Buy Me Love'), fold("Can't Buy Me Love"));
check('fold: an accent is optional', fold('Amélie'), fold('Amelie'));
check('fold: & is a word', fold('The Prince & Me'), fold('The Prince and Me'));
check('fold: a middle dot is a space', fold('WALL·E'), fold('Wall-E'));
check('fold: nothing left but the words', fold('  O Brother, Where Art Thou?  '),
  'o brother where art thou');

check('titleKey: the importer sees one title, not two',
  titleKey('Can’t Buy Me Love', 1987), titleKey("Can't Buy Me Love", 1987));
check('titleKey: the leading article is not part of it',
  titleKey('The Prince & Me'), titleKey('Prince and Me'));

/* ---------------------------------------------------------------- search */

const now = '2026-01-01T00:00:00Z';
const make = (title, extra = {}) => ({
  id: title, title, year: null, type: 'movie', status: 'queue', rating: null,
  heart: false, tags: [], links: [], notes: '', poster: '', overview: '',
  runtime: null, genres: [], creator: '', cast: [], certification: '',
  order: null, addedAt: now, watchedAt: null, updatedAt: now, deleted: false,
  ...extra,
});

store.state.items = [
  make('Can’t Buy Me Love', { year: 1987 }),
  make('Adam’s Rib', { year: 1949, creator: 'George Cukor' }),
  make('Amélie', { year: 2001 }),
  make('WALL·E', { year: 2008, genres: ['Animation'] }),
  make('The Prince & Me', { year: 2004 }),
  make('The Women', { year: 1939, tags: ['noir'], genres: ['Comedy', 'Romance'] }),
  make('The Women', { year: 2008, notes: 'a remake', id: 'women-2008' }),
  make('Bridget Jones’s Diary', { year: 2001, cast: ['Renée Zellweger'] }),
];

filters.section = 'movie';
filters.view = 'list';

const titles = (query) => {
  filters.q = query;
  return apply(store.state.items).map((i) => `${i.title} (${i.year})`);
};

check('the bug: a typed apostrophe finds a curly one',
  titles("Can't Buy Me Love"), ['Can’t Buy Me Love (1987)']);
check('and a curly one finds it as well',
  titles('Can’t Buy Me Love'), ['Can’t Buy Me Love (1987)']);
check('and none at all finds it too',
  titles('cant buy me love'), ['Can’t Buy Me Love (1987)']);
check('an unaccented search finds the accent', titles('amelie'), ['Amélie (2001)']);
check('a hyphen finds the middle dot', titles('wall-e'), ['WALL·E (2008)']);
check('& finds "and"', titles('prince & me'), ['The Prince & Me (2004)']);
check('"and" finds &', titles('prince and me'), ['The Prince & Me (2004)']);
check('a cast name with an accent', titles('renee zellweger'), ['Bridget Jones’s Diary (2001)']);

check('a straight-quoted phrase', titles('"the women"'),
  ['The Women (1939)', 'The Women (2008)']);
check('a phone’s curly-quoted phrase', titles('“the women”'),
  ['The Women (1939)', 'The Women (2008)']);
check('minus still excludes', titles('women -remake'), ['The Women (1939)']);
check('and so does the dash a phone types', titles('women –remake'),
  ['The Women (1939)']);

check('year: still works', titles('year:1987'), ['Can’t Buy Me Love (1987)']);
check('#tag still works', titles('#noir'), ['The Women (1939)']);
check('a folded genre pair still works', titles('"genre:romantic comedy"'),
  ['The Women (1939)']);
check('note: is an operator', titles('note:remake'), ['The Women (2008)']);
/* Not an operator, but the director is in the haystack, so asking for one
   by name has to keep working rather than falling through to nothing. */
check('and one that is not still looks for what was asked',
  titles('director:cukor'), ['Adam’s Rib (1949)']);
check('an operator nobody has anywhere finds nothing',
  titles('director:hitchcock'), []);
check('nothing matches nothing', titles('zzzz'), []);

/* A card found through its cast is not a card found by name: "juno" is Juno
   Temple's films and, somewhere under them, Juno. The name is checked on its
   own, and a card not found by it says where it was found. */
const madding = make('Far from the Madding Crowd', { year: 2015, cast: ['Carey Mulligan', 'Juno Temple'] });
const juno = make('Juno', { year: 2007, id: 'juno' });
check('a search matches through the cast', (filters.q = 'juno', apply([madding, juno]).length), 2);
check('but only one of them by name',
  [titleMatches(madding.title, 'juno'), titleMatches(juno.title, 'juno')], [false, true]);
check('and the other says where it matched', whyMatched(madding, 'juno'), 'cast · Juno Temple');
check('a name match says nothing', whyMatched(juno, 'juno'), '');
check('a tag, a note and a director are named too',
  [whyMatched(make('X', { tags: ['noir'] }), 'noir'),
   whyMatched(make('Y', { notes: 'a remake' }), 'remake'),
   whyMatched(make('Z', { creator: 'George Cukor' }), 'cukor')],
  ['#noir', 'notes', 'George Cukor']);
check('every word has to be in the name', titleMatches('Juno and the Paycock', 'juno paycock'), true);
check('not just one of them', titleMatches('Juno', 'juno temple'), false);

filters.q = '';
console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
