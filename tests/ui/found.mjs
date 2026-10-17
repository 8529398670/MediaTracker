/* The links under a title the providers found.
 *
 * A search that finds nothing in the library asks the providers, and the rows
 * that come back are titles you may never have heard of — so each one carries
 * the three places worth going before adding it: Wikipedia, IMDb, and IMDb's
 * parents guide. Only the best match arrives with its IMDb id, and the guide
 * is only ever that id with /parentalguide on the end, so what is under test
 * is which links a row can honestly offer: the real pages when the id or the
 * article is known, a search when it is not, and no parents guide at all
 * without the exact id.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const store = await import('./store.js');
const views = await import('./views.js');
store.state.config = { network: true, providers: {} };

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};

const on = { add() {}, watched() {}, open() {} };
const chips = (row, opts = {}) => views.foundRow(row, { on, ...opts })
  .find((n) => n.classList.has('link-chip'));
const named = (row, label) => chips(row).filter((c) => c.text() === label)[0];

/* ------------------------------------------------- the best match, complete */

const best = {
  source: 'tmdb', sourceId: 'movie/19900', type: 'movie',
  title: 'Weather Girl', year: 2009, imdbId: 'tt1085515',
  link: 'https://www.themoviedb.org/movie/19900',
};

check('a row with an IMDb id carries all five links, the parents guide included',
  chips(best).map((c) => c.text()), ['Wikipedia', 'IMDb', 'Parents guide', 'Watch', 'Apple TV']);
check('Apple TV is a search until the server knows the id', named(best, 'Apple TV').href.startsWith('https://tv.apple.com/us/search?term='), true);
check('IMDb is the title, by id', named(best, 'IMDb').href,
  'https://www.imdb.com/title/tt1085515/');
check('and the parents guide is that id with /parentalguide on the end',
  named(best, 'Parents guide').href,
  'https://www.imdb.com/title/tt1085515/parentalguide/');
check('every link opens away from the page, and safely',
  [named(best, 'IMDb').attrs.target, named(best, 'IMDb').attrs.rel],
  ['_blank', 'noopener noreferrer']);

/* --------------------------------------------------- the rest of the answer

   Search results, which do not carry an id. The second hop fetches one, but
   the row is drawn before it lands — and some titles never get one. */

const bare = { source: 'tmdb', sourceId: 'movie/1234', type: 'movie',
               title: 'Blue Steel', year: 1990,
               link: 'https://www.themoviedb.org/movie/1234' };

check('without an id there is no parents guide link rather than a broken one',
  chips(bare).map((c) => c.text()), ['Wikipedia', 'IMDb', 'Watch', 'Apple TV']);
check("so IMDb's own search stands in", named(bare, 'IMDb').href,
  'https://www.imdb.com/find/?s=tt&q=Blue%20Steel%201990');
check('and the hover says it is a search, not the title',
  named(bare, 'IMDb').attrs.title, 'Search IMDb for Blue Steel');
check('Wikipedia is a search too — a guessed slug is worse than no link',
  named(bare, 'Wikipedia').href,
  'https://en.wikipedia.org/w/index.php?search=Blue%20Steel%201990');
check('and the one link that is always a search is always there',
  named(bare, 'Watch').href, 'https://www.justwatch.com/us/search?q=Blue%20Steel');

/* ------------------------------------------------- when the article is known

   A row found through Wikipedia names its own article; one completed through
   the enricher's path carries it as wikiUrl. Either way it is the right page
   rather than a guess at the slug. */

const fromWiki = { source: 'wikipedia', sourceId: 'Parasite (2019 film)', type: 'movie',
                   title: 'Parasite', year: 2019,
                   link: 'https://en.wikipedia.org/wiki/Parasite_(2019_film)' };
check('a row found through Wikipedia links its own article',
  named(fromWiki, 'Wikipedia').href,
  'https://en.wikipedia.org/wiki/Parasite_(2019_film)');
check('and the hover says so', named(fromWiki, 'Wikipedia').attrs.title,
  'Parasite on Wikipedia');
check('a wikiUrl is the article as well',
  named({ ...bare, wikiUrl: 'https://en.wikipedia.org/wiki/Blue_Steel_(1990_film)' },
    'Wikipedia').href, 'https://en.wikipedia.org/wiki/Blue_Steel_(1990_film)');
check('but a link to anywhere else is not mistaken for one',
  named({ ...bare, link: 'https://www.justwatch.com/us/movie/blue-steel' },
    'Wikipedia').href, 'https://en.wikipedia.org/w/index.php?search=Blue%20Steel%201990');

/* ----------------------------------------------------- beside the two ways in

   The links sit in the row's body; the Add and Watched buttons are its own,
   and a row already in the library keeps neither of them but all of its
   links — the point of the strip is still to look it up. */

const row = views.foundRow(best, { on, mine: { id: 'x', type: 'movie' } });
check('a title already yours still has its links',
  row.find((n) => n.classList.has('link-chip')).length, 5);
check('and one button, which opens the copy you have',
  row.find((n) => n.classList.has('found-acts'))[0].text(), 'Added');

const { appleTvUrl } = await import('./views.js');
check('a title with an Apple TV id goes straight to it',
  appleTvUrl({ title: 'Casablanca', appleTv: 'movie/umc.cmc.6i7o1550iyqet6xexqniqyp4k', links: [] }),
  'https://tv.apple.com/us/movie/umc.cmc.6i7o1550iyqet6xexqniqyp4k');
check('a tv.apple.com link already on the card does as well',
  appleTvUrl({ title: 'X', links: [{ url: 'https://tv.apple.com/us/show/x/umc.cmc.abcdefghij' }] }),
  'https://tv.apple.com/us/show/x/umc.cmc.abcdefghij');

console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
