/* IMDb's score on the library's cards.
 *
 * The scores are not the library's: they come from the server's copy of
 * IMDb's daily ratings file, by IMDb id, and are only looked up — never
 * synced or saved. So what is under test is that the whole library is asked
 * for once, that a title which gains an id afterwards is asked about by name
 * and only once, that a card says whose score it is carrying, and that the
 * library can be sorted by it.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const calls = [];
globalThis.fetch = async (url, init) => {
  const method = (init && init.method) || 'GET';
  calls.push(`${method} ${url}`);
  let body = { ok: true };
  if (url.startsWith('/api/ratings?')) {
    body = { source: 'imdb', titles: 1714406,
             ratings: url.includes('tt0111161') ? { tt0111161: [93, 3243065] } : {} };
  } else if (url.startsWith('/api/ratings')) {
    body = { source: 'imdb', titles: 1714406, ratings: { tt0034583: [85, 661592] } };
  }
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
};

const store = await import('./store.js');
const { sortItems } = await import('./filters.js');
const views = await import('./views.js');
store.state.config = { network: true, providers: {} };
store.state.loading = false;
store.state.online = true;

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const asked = () => calls.filter((c) => c.startsWith('GET /api/ratings'));

const casablanca = store.addItem({ title: 'Casablanca', type: 'movie', imdbId: 'tt0034583' });
const tmdbOnly = store.addItem({ title: 'Somewhere Else', type: 'movie', extRating: 71 });
const bare = store.addItem({ title: 'Nothing Known', type: 'movie' });
await tick();

check('the whole library is asked for in one call, not title by title',
  asked(), ['GET /api/ratings']);
check("a title with an IMDb id wears IMDb's score, with how many voted",
  store.scoreOf(store.getItem(casablanca.id)), { source: 'imdb', value: 8.5, votes: 661592 });
check('one IMDb has nothing for falls back to TMDB, and says so',
  store.scoreOf(store.getItem(tmdbOnly.id)), { source: 'tmdb', value: 7.1, votes: 0 });
check('and one with neither has none', store.scoreOf(store.getItem(bare.id)), null);

/* A title the fill-in pass has just identified is asked about by name. */
const shawshank = store.addItem({ title: 'The Shawshank Redemption', type: 'movie',
                                  imdbId: 'tt0111161' });
await tick();
check('a title that gains an id is asked about by name',
  asked().slice(1), ['GET /api/ratings?id=tt0111161']);
check('and has its score from then on',
  store.scoreOf(store.getItem(shawshank.id)).value, 9.3);

store.patchItem(bare.id, { notes: 'still nothing' });
await tick();
check('nothing already answered is asked about again', asked().length, 2);

/* ------------------------------------------------------------ the card */

const on = { watched() {}, heart() {}, rate() {}, open() {}, tag() {}, genre() {},
             cert() {}, year() {} };
const badge = (item) => views.card(store.getItem(item.id), on)
  .find((n) => n.classList.has('score'))[0];
check("the card carries the score, IMDb's by its class",
  [badge(casablanca).text(), badge(casablanca).classList.has('imdb')], ['8.5', true]);
check("and TMDB's by its own, so it is never read as IMDb's",
  badge(tmdbOnly).classList.has('tmdb'), true);
check('a card with no score has no badge rather than a blank one',
  badge(bare), undefined);

/* ------------------------------------------------------------ the sort */

check('sorted by IMDb: highest first, TMDB standing in, and none at the end',
  sortItems(store.live(), 'imdb-desc').map((i) => i.title),
  ['The Shawshank Redemption', 'Casablanca', 'Somewhere Else', 'Nothing Known']);

console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
