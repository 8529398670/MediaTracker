/* The Discover pane, driven the way a person drives it.
 *
 * The server is stubbed: what is under test is the pane — that the merged
 * catalogue is asked for with the filters that are showing, that a film
 * already in the library is drawn as already in the library rather than
 * offered again, and that pressing + puts one title in with everything the
 * harvest already knew about it.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';

const calls = [];
const verdictCalls = [];
const FILMS = [
  {
    key: 'w:jolson sings again', article: 'Jolson Sings Again',
    title: 'Jolson Sings Again', year: 1949, director: 'Henry Levin',
    cast: ['Larry Parks', 'Barbara Hale'], genres: ['Music', 'Biography'],
    studio: 'Columbia', gross: '$5,000,000',
    url: 'https://en.wikipedia.org/wiki/Jolson_Sings_Again',
    signals: { weeks: 5, topOfYear: true, rank: 1 }, from: ['american'], score: 110,
  },
  {
    key: "w:adam's rib", article: "Adam's Rib", title: "Adam's Rib", year: 1949,
    director: 'George Cukor', cast: ['Spencer Tracy', 'Katharine Hepburn'],
    genres: ['Romance', 'Comedy'], studio: 'MGM', gross: '',
    url: 'https://en.wikipedia.org/wiki/Adam%27s_Rib',
    signals: {}, from: ['american'], score: 3,
  },
  {
    key: 'w:baby face (film)', article: 'Baby Face (film)', title: 'Baby Face',
    year: 1933, director: '', cast: [], genres: ['Drama'], studio: '', gross: '',
    url: 'https://en.wikipedia.org/wiki/Baby_Face_(film)',
    signals: { topics: ['pre-code-hollywood'] }, from: ['topic:pre-code-hollywood'],
    score: 12,
  },
];

/* What the server says each of these was rated. Baby Face predates the MPA
 * by thirty-five years and has none; Jolson has not been looked up. */
const RATED = { "w:adam's rib": 'PG' };

globalThis.fetch = async (url, init) => {
  calls.push(`${(init && init.method) || 'GET'} ${url}`);
  let body = { ok: true };
  if (url.includes('/lists/certs')) {
    // What the rating pass has reached. Most of the catalogue has not been
    // asked about, which is the state the picker has to be honest about.
    body = { running: false, done: 0, total: 0, found: 0, errors: 0,
             current: '', note: '', etaSeconds: 0, network: true,
             films: 922, asked: 2, rated: 1, unknown: 920 };
  } else if (url.includes('/verdicts')) {
    body = { counts: { skip: (verdictCalls.push(init && init.body), verdictCalls.length) } };
  } else if (url.includes('/lists/facts')) {
    body = { facts: {
      'Jolson Sings Again': { thumb: 'https://thumb.wikimedia.org/x/jolson.jpg',
                              imdb: 'tt0041474', rating: '' },
      "Adam's Rib": { thumb: '', imdb: 'tt0041090', rating: 'PG' },
      'Baby Face (film)': { thumb: 'https://thumb.wikimedia.org/y/babyface.jpg',
                            imdb: '', rating: '' },
    } };
  } else if (url.includes('/lists/films')) {
    // The rating comes down with the row now, so the badge is on the page
    // from the first paint rather than after the poster call.
    body = { total: FILMS.length, offset: 0,
             films: FILMS.map((f) => ({ ...f, rating: RATED[f.key] || '' })),
             genres: [], genreMode: 'any',
             facets: {
               genres: [
                 { id: 'drama', label: 'Drama', count: 402 },
                 { id: 'comedy', label: 'Comedy', count: 311 },
                 { id: 'western', label: 'Western', count: 120 },
                 { id: 'crime', label: 'Crime', count: 88 },
                 { id: 'music', label: 'Music', count: 30 },
               ],
               years: { 1933: 28, 1949: 370 },
               ratings: [
                 { id: 'G', label: 'G', count: 4 },
                 { id: 'PG', label: 'PG', count: 11 },
                 { id: 'R', label: 'R', count: 2 },
                 { id: 'none', label: 'Not rated', count: 61 },
                 { id: 'unknown', label: 'Not looked up', count: 844 },
               ],
             },
             coverage: { films: 922, years: { 1949: 370, 1933: 28 },
                         pages: { 'topic:pre-code-hollywood': { films: 129 } } } };
  } else if (url.includes('/api/lists')) {
    body = {
      catalogue: {
        sets: [{ id: 'american', label: 'Every American film', note: 'n' }],
        topics: [{ id: 'pre-code-hollywood', label: 'Pre-Code Hollywood', note: 'n' }],
        firstYear: 1900, lastYear: 2027,
      },
      running: false, done: 0, total: 0, films: 0, errors: 0, current: '',
      note: '', etaSeconds: 0, network: true,
      coverage: { films: 922, years: { 1949: 370 },
                  pages: { 'topic:pre-code-hollywood': { films: 129 } } },
    };
  }
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
};

const store = await import('./store.js');
const disco = await import('./discover.js');
store.state.config = { network: true, providers: {} };

let failures = 0;
const check = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}`
    + (ok ? '' : `\n        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`));
};

const { N } = await import('./dom.mjs');
const root = new N('div');
const bar = new N('div');
const seen = [];
const passed = [];
const on = {
  reload() {}, more() {}, fetch() {},
  // What app.js does: the row is already gone, this records it.
  skip(film, restore) { passed.push(['skip', film.title, restore]); disco.setVerdict(film, 'skip'); },
  unskip(film, restore) { passed.push(['back', film.title, restore]); disco.setVerdict(film, ''); },
  // What app.js does: the answer is awaited, so the refine sheet can repaint
  // its counts from it.
  change() { return disco.refreshDiscover(''); },
  genre(g) { seen.push(`genre:${g}`); disco.toggleGenre(g); },
  rating(r) { seen.push(`rating:${r}`); disco.toggleRating(r); },
  actor(name) { seen.push(`actor:${name}`); disco.setActor(name); },
  topic(t) { seen.push(`topic:${t}`); },
  open(item) { seen.push(`open:${item.title}`); },
  add(film) { seen.push(`add:${film.title}`); disco.addFilm(film); },
  watched(film) {
    seen.push(`watched:${film.title}`);
    disco.addFilm(film, { status: 'watched' });
  },
};

/* ------------------------------------------------------------- the query */

await disco.ensureCatalogue();
disco.discover.yearFrom = 1948;
disco.discover.yearTo = 1949;
disco.discover.sort = 'notable';
await disco.refreshDiscover('hepburn');

const asked = calls.find((c) => c.includes('/lists/films'));
check('the filters showing are the filters asked for',
  [asked.includes('from=1948'), asked.includes('to=1949'),
   asked.includes('sort=notable'), asked.includes('q=hepburn')],
  [true, true, true, true]);

/* --------------------------------------------------------------- the rows */

disco.renderDiscover(root, on);
const rows = root.find((n) => n.classList.has('disco'));
check('one row per film', rows.length, 3);
// The poster slot leads the row now, so the title follows it rather than
// starting it.
check('the title and the year are on the row',
  rows[0].text().includes('Jolson Sings Again 1949'), true);
check('what the world made of it is on the row too',
  ['#1 for 5 weeks', '1st highest-grossing', 'biggest of the year']
    .every((s) => rows[0].text().includes(s)), true);
check('and the genres as the library spells them',
  rows[1].text().includes('Romance') && rows[1].text().includes('Comedy'), true);

/* ------------------------------------------------------------------- add */

const addBtn = rows[1].find((n) => n.classList.has('disco-act'))[0];
addBtn.fire('click');
check('pressing + adds exactly one title', store.live().length, 1);

const added = store.live()[0];
check('and it arrives with what the harvest already knew',
  [added.title, added.year, added.creator, added.genres, added.cast,
   added.status, added.wikiUrl],
  ["Adam's Rib", 1949, 'George Cukor', ['Romance', 'Comedy'],
   ['Spencer Tracy', 'Katharine Hepburn'], 'queue',
   'https://en.wikipedia.org/wiki/Adam%27s_Rib']);
check('the fill-in pass is started for that one title, not the library',
  calls.some((c) => c.startsWith('POST /api/enrich')), true);

/* A topic film carries the topic in as a tag, so it can be found again. */
rows[2].find((n) => n.classList.has('disco-act'))[0].fire('click');
check('a topic comes in as a tag', store.live()[1].tags, ['pre-code-hollywood']);

/* ------------------------------------------------------- already in there */

disco.renderDiscover(root, on);
const again = root.find((n) => n.classList.has('disco'));
check('a title now in the library is not offered again',
  again[1].classList.has('is-mine'), true);
check('its button opens it instead of adding it a second time',
  again[1].find((n) => n.classList.has('disco-act'))[0].text(), 'Added');
again[1].find((n) => n.classList.has('disco-act'))[0].fire('click');
check('and that is what it does', seen.includes("open:Adam's Rib"), true);
check('nothing was added twice', store.live().length, 2);

/* ---------------------------------------------------------------- toolbar */

disco.buildTools(bar, on);
const tabs = bar.find((n) => n.attrs['data-pick'] || n.dataset.pick);
check('a tab for each cut, plus the one topic actually collected',
  tabs.map((t) => t.dataset.pick),
  ['all', 'boxoffice', 'awarded', 'topic:pre-code-hollywood']);

/* ------------------------------------------------------------ posters */

/* The rows are drawn first and the posters arrive into them, so nothing is
 * waiting on Wikipedia to be readable. */
disco.renderDiscover(root, on);
const slots = () => root.find((n) => n.classList.has('disco-art'));
check('every row has a poster slot from the start',
  slots().length, 3);
check('and it holds the initials until an address is known',
  slots()[0].text(), 'JS');

await disco.fillFacts();
const artCall = calls.filter((c) => c.includes('/lists/facts')).pop();
check('the articles on screen are asked about by name, in one call',
  ['Jolson+Sings+Again', 'Adam%27s+Rib', 'Baby+Face+%28film%29']
    .every((a) => artCall.includes(`a=${a}`)), true);

const img = (slot) => slot.find((n) => n.tagName === 'IMG')[0];
check('an address that came back becomes the picture on the row',
  img(slots()[0]).src, 'https://thumb.wikimedia.org/x/jolson.jpg');
check('and it is loaded lazily, at the size of the slot',
  [img(slots()[0]).attrs.loading, img(slots()[0]).attrs.width], ['lazy', '52']);
check('a film with no free image keeps its initials',
  [img(slots()[1]), slots()[1].text()], [undefined, 'AR']);

/* ------------------------------------------- the rating and the links */

const heads = () => root.find((n) => n.classList.has('disco-title'));
const linksOn = (at) => root.find((n) => n.classList.has('disco'))[at]
  .find((n) => n.classList.has('link-chip'));
check('an age rating sits with the year, where one is known',
  heads()[1].text(), "Adam's Rib 1949 PG");
check('and it is there from the first paint, not only once a poster call lands',
  disco.renderDiscover(root, on) || root.find(
    (n) => n.classList.has('disco-title'))[1].text(), "Adam's Rib 1949 PG");
check('and a film with none is left alone',
  heads()[0].text(), 'Jolson Sings Again 1949');
check('an IMDb id becomes both links, the parents guide included',
  linksOn(0).map((c) => c.text()), ['Wikipedia', 'IMDb', 'Parents guide', 'Watch']);
check('pointing at the film, not at a search for it',
  linksOn(0).filter((c) => c.text() === 'Parents guide')[0].href,
  'https://www.imdb.com/title/tt0041474/parentalguide/');
check('and a film Wikidata has no id for keeps the two links it always had',
  linksOn(2).map((c) => c.text()), ['Wikipedia', 'Watch']);

const before = calls.filter((c) => c.includes('/lists/facts')).length;
disco.renderDiscover(root, on);
await disco.fillFacts();
check('and nothing already answered is asked about again',
  calls.filter((c) => c.includes('/lists/facts')).length, before);
check('the picture is still there on the second paint',
  img(slots()[0]).src, 'https://thumb.wikimedia.org/x/jolson.jpg');
check('and so are the rating and the links, which a repaint used to lose',
  [root.find((n) => n.classList.has('disco-title'))[1].text(),
   root.find((n) => n.classList.has('disco'))[0]
     .find((n) => n.classList.has('link-chip')).length],
  ["Adam's Rib 1949 PG", 4]);

/* --------------------------------------------------- year and genre */

const asks = () => calls.filter((c) => c.includes('/lists/films')).pop();

disco.setView({ yearFrom: 0, yearTo: 0, genres: [], genreMode: 'any' });

/* A genre badge on a row builds the filter rather than replacing it, so two
 * clicks on two rows are a combination. */
disco.renderDiscover(root, on);
const badge = (node, name) => node.find(
  (n) => n.classList.has('genre') && n.text() === name)[0];
badge(root.find((n) => n.classList.has('disco'))[1], 'Comedy').fire('click');
await on.change();
check('a genre clicked on a row is asked for by name, folded',
  asks().includes('genre=comedy'), true);
check('and one genre needs no word for how it combines',
  asks().includes('genremode'), false);

disco.renderDiscover(root, on);
check('the row says which of its genres is being filtered by',
  badge(root.find((n) => n.classList.has('disco'))[1], 'Comedy').attrs['aria-pressed'],
  'true');

badge(root.find((n) => n.classList.has('disco'))[2], 'Drama').fire('click');
await on.change();
check('a second genre travels beside the first, not instead of it',
  [asks().includes('genre=comedy'), asks().includes('genre=drama'),
   asks().includes('genremode=any')],
  [true, true, true]);

disco.setView({ genreMode: 'all' });
await on.change();
check('and all-of-these is asked for as such',
  asks().includes('genremode=all'), true);

/* ------------------------------------------------------- the toolbar */

disco.buildTools(bar, on);
const chips = bar.find((n) => n.dataset.genre);
check('every genre chosen is a chip in the bar, in the order picked',
  chips.map((c) => c.dataset.genre), ['comedy', 'drama']);
check('with the switch between the two ways of combining them',
  bar.find((n) => n.dataset.control === 'mode')[0].text(), 'all of these');
check('and the picker says how many are on',
  bar.find((n) => n.dataset.control === 'genres')[0].text(), 'Genres 2');

chips[0].fire('click');
await on.change();
check('a chip in the bar takes its genre back off',
  disco.discover.genres, ['drama']);
disco.buildTools(bar, on);
check('and with one left there is nothing to combine',
  bar.find((n) => n.dataset.control === 'mode').length, 0);

/* --------------------------------------------------------- the sheet */

disco.openRefine(on);
const sheet = document.getElementById('sheet-host');
const offered = sheet.find((n) => n.dataset.genre);
check('the sheet offers the genres the server counted, biggest first',
  offered.map((n) => n.dataset.genre),
  ['drama', 'comedy', 'western', 'crime', 'music']);
check('each with the number of films behind it',
  offered[2].text(), 'Western 120');
check('and the one already chosen reads as chosen',
  offered[0].attrs['aria-pressed'], 'true');

const decade = sheet.find((n) => n.text().startsWith('1930s'))[0];
check('the decades collected are one tap each, with their counts',
  decade.text(), '1930s 28');
decade.fire('click');
await on.change();
check('a decade is a year range',
  [disco.discover.yearFrom, disco.discover.yearTo], [1930, 1939]);
check('which is what the server is asked for',
  asks().includes('from=1930') && asks().includes('to=1939'), true);

sheet.find((n) => n.dataset.genre === 'western')[0].fire('click');
await on.change();
check('a genre picked in the sheet joins the ones already there',
  disco.discover.genres, ['drama', 'western']);

sheet.find((n) => n.text() === 'All years')[0].fire('click');
await on.change();
check('and all years puts the range back',
  [disco.discover.yearFrom, disco.discover.yearTo, asks().includes('from=')],
  [0, 0, false]);

/* --------------------------------------------------------------- rating */

/* The one filter here that reads something Wikipedia's year lists never
 * printed. It has three answers and not two — rated, not rated, and not
 * looked up — and the point of the last one is that a filter which quietly
 * folded it into "not rated" would be lying about a lookup that has not run.
 */

disco.setView({ yearFrom: 0, yearTo: 0, genres: [], ratings: [] });
await on.change();

/* The badge beside the year filters on tap, the way the genres under it do.
 * Adam's Rib is the row Wikidata answered PG for. */
disco.renderDiscover(root, on);
await disco.fillFacts();
const certOn = (at) => root.find((n) => n.classList.has('disco'))[at]
  .find((n) => n.classList.has('cert'))[0];
check('the rating on a row is a control, not just a label',
  [certOn(1).tagName, certOn(1).text()], ['BUTTON', 'PG']);
certOn(1).fire('click');
await on.change();
check('tapping it says which rating to follow', seen.pop(), 'rating:PG');
check('which is what the server is asked for', asks().includes('rating=PG'), true);
disco.renderDiscover(root, on);
await disco.fillFacts();
check('and the row says the rating it is showing is being filtered by',
  certOn(1).attrs['aria-pressed'], 'true');

disco.toggleRating('G');
await on.change();
check('a second rating travels beside the first',
  [asks().includes('rating=PG'), asks().includes('rating=G')], [true, true]);
check('and never with a word for how they combine, because there is only one',
  asks().includes('genremode=all') || asks().includes('ratingmode'), false);

disco.buildTools(bar, on);
const certChip = bar.find((n) => n.dataset.control === 'ratings')[0];
check('the bar carries what is being filtered by', certChip.text(), 'PG, G');
check('and reads as on', certChip.attrs['aria-pressed'], 'true');

/* The sheet, where the scale is offered with its counts. */
disco.setView({ ratings: ['PG'] });
await on.change();
disco.openRefine(on, { focus: 'ratings' });
const sheet2 = document.getElementById('sheet-host');
const scale = sheet2.find((n) => n.dataset.rating);
check('the sheet offers the scale in the order it is read, not biggest first',
  scale.map((n) => n.dataset.rating), ['G', 'PG', 'R', 'none', 'unknown']);
check('each with the number of films behind it', scale[1].text(), 'PG 11');
check('and the one already chosen reads as chosen',
  scale[1].attrs['aria-pressed'], 'true');
check('what has no rating and what has not been looked up are told apart',
  [scale[3].text(), scale[4].text()],
  ['Not rated 61', 'Not looked up 844']);

scale[0].fire('click');
await on.change();
check('a rating picked in the sheet joins the ones already there',
  disco.discover.ratings, ['PG', 'G']);
sheet2.find((n) => n.text() === 'Any rating')[0].fire('click');
await on.change();
check('and any rating puts them all down',
  [disco.discover.ratings, asks().includes('rating=')], [[], false]);

/* The lookup that makes the filter true, offered where the gap in it shows. */
check('the sheet says how much of the catalogue has not been looked up',
  sheet2.text().includes('920 of 922 collected films have not been looked up'),
  true);
const lookup = sheet2.find((n) => n.text() === 'Look them up')[0];
lookup.fire('click');
await new Promise((r) => setTimeout(r, 0));
check('and starting it is one call to the server, not one per film',
  calls.filter((c) => c === 'POST /api/lists/certs').length, 1);

/* ------------------------------------------------------------ skipping */

disco.setView({ yearFrom: 0, yearTo: 0, genres: [], showSkipped: false });
await on.change();
check('the ordinary list asks for the ones not skipped',
  asks().includes('skipped=hide'), true);

disco.renderDiscover(root, on);
const rowsNow = () => root.find((n) => n.classList.has('disco'));
const acts = (r) => r.find((n) => n.classList.has('disco-act')).map((b) => b.text());
check('a row that is not yours offers all three verdicts',
  acts(rowsNow()[0]), ['Add', 'Skip', 'Watched']);
check('but one already in the library has nothing to pass on',
  acts(rowsNow()[1]), ['Added']);

const wasShowing = rowsNow().length;
rowsNow()[0].find((n) => n.classList.has('skip'))[0].fire('click');
check('pressing Skip takes the row off the page at once',
  rowsNow().length, wasShowing - 1);
check('and says which film, with the way back',
  [passed[0][0], passed[0][1], typeof passed[0][2]],
  ['skip', 'Jolson Sings Again', 'function']);
check('the verdict is sent to the server, not kept in this browser',
  JSON.parse(verdictCalls[0]),
  { key: 'w:jolson sings again', verdict: 'skip' });

passed[0][2]();                                   // undo puts it back where it was
check('and undoing it puts the row back where it was',
  rowsNow().map((r) => r.find((n) => n.classList.has('disco-title'))[0].text().split(' ')[0]),
  ['Jolson', "Adam's", 'Baby']);

/* ------------------------------------------------------- the other list */

disco.setView({ showSkipped: true });
await on.change();
check('show-skipped asks for the other side of the same catalogue',
  asks().includes('skipped=only'), true);

disco.renderDiscover(root, on);
// Passed over, and then remembered — the skipped list is exactly where
// "actually, I have seen that" gets said, so Watched is offered there too.
check('and every row there offers a way out of the verdict',
  acts(rowsNow()[0]), ['Add', 'Put back', 'Watched']);
rowsNow()[0].find((n) => n.text() === 'Put back')[0].fire('click');
check('which is recorded as the verdict being taken back',
  [passed[1][0], JSON.parse(verdictCalls[1]).verdict], ['back', '']);

disco.buildTools(bar, on);
const chip = bar.find((n) => n.dataset.control === 'skipped')[0];
check('the toolbar carries the count and says which list is showing',
  [chip.text().startsWith('Skipped'), chip.attrs['aria-pressed']], [true, 'true']);
disco.setView({ showSkipped: false });

/* ------------------------------------------------ what a row says */

disco.setView({ showMoney: false, showCrew: false });
disco.renderDiscover(root, on);
const rowText = () => root.find((n) => n.classList.has('disco'))[0].text();
check('the money and the studio are off to begin with',
  [rowText().includes('$5,000,000'), rowText().includes('Columbia')], [false, false]);
check('but the people in it are not',
  rowText().includes('Larry Parks'), true);

disco.setView({ showMoney: true, showCrew: true });
disco.renderDiscover(root, on);
check('and both come back when they are asked for',
  [rowText().includes('$5,000,000'), rowText().includes('Henry Levin'),
   rowText().includes('Columbia')], [true, true, true]);
disco.setView({ showMoney: false, showCrew: false });

/* ------------------------------------------------------ following one */

disco.renderDiscover(root, on);
const name = root.find((n) => n.classList.has('castname'))[0];
check('every name in a cast list is a way in', name.text(), 'Larry Parks');
name.fire('click');
check('and clicking one says who to follow', seen.pop(), 'actor:Larry Parks');
check('which is what the view is now following', disco.discover.actor, 'Larry Parks');
name.fire('click');
check('and clicking the same name again stops', disco.discover.actor, '');

disco.setActor('Larry Parks');
await on.change();
check('which the server is asked for by name',
  asks().includes('actor=Larry+Parks'), true);
disco.renderDiscover(root, on);
check('the row says whose name is being followed',
  root.find((n) => n.classList.has('castname'))[0].attrs['aria-pressed'], 'true');

disco.buildTools(bar, on);
const following = bar.find((n) => n.dataset.control === 'actor')[0];
check('and the bar carries them, with a way to stop',
  following.text(), 'Larry Parks');
following.fire('click');
check('which puts them down again', disco.discover.actor, '');

/* -------------------------------------------------------------- watched */

/* The third answer a row gets: not *queue this* and not *not for me*, but
 * *I have seen that* — which on a list of four hundred films a year is the
 * commonest of the three. It adds, like +, but into the watched pile.
 *
 * Last in the file on purpose: it puts the one remaining row into the
 * library, and everything above wants a row that is not yours yet.
 */

disco.setView({ showSkipped: false, ratings: [], actor: '' });
disco.renderDiscover(root, on);
const actsOn = (at) => root.find((n) => n.classList.has('disco'))[at]
  .find((n) => n.classList.has('disco-act')).map((b) => b.text());
check('a row that is not yours offers all three answers, Watched under Skip',
  actsOn(0), ['Add', 'Skip', 'Watched']);
check('but one already in the library has nothing left to add',
  actsOn(1), ['Added']);

const wasThere = store.live().length;
root.find((n) => n.classList.has('disco'))[0]
  .find((n) => n.classList.has('seen'))[0].fire('click');
check('pressing it adds exactly one title', store.live().length, wasThere + 1);

const justSeen = store.live()[store.live().length - 1];
check('as watched rather than queued, and dated — the library reads a '
  + 'missing date as never seen',
  [justSeen.title, justSeen.status, typeof justSeen.watchedAt],
  ['Jolson Sings Again', 'watched', 'string']);
check('with everything the harvest knew, the same as +',
  [justSeen.year, justSeen.creator, justSeen.genres],
  [1949, 'Henry Levin', ['Music', 'Biography']]);
check('and nothing was queued by it',
  store.live().filter((i) => i.status === 'queue').map((i) => i.title),
  ["Adam's Rib", 'Baby Face']);
check('the row stays on the page — only a skip takes one off',
  root.find((n) => n.classList.has('disco')).length, 3);

disco.renderDiscover(root, on);
check('and it is drawn as already yours from then on', actsOn(0), ['Added']);

console.log(failures ? `\n${failures} failed` : '\nall good');
process.exit(failures ? 1 : 0);
