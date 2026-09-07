/* Discover — the films Wikipedia already knows about, before you search.
 *
 * The library is what you have put in it. This is the other half: everything
 * that came out, year by year, with the two facts that separate a film worth
 * an evening from four hundred that were also released — what it took at the
 * box office, and what it won. The server harvests it from Wikipedia's own
 * lists and keeps it on disk; this is the browsing of it, and the one tap
 * that moves a row from there to here.
 *
 * The rows are not library items and never become library items by being
 * looked at. Nothing is written until you press +.
 */

import {
  api, live, titleKey, addItem, state, TYPE_LABEL,
} from './store.js';
import {
  el, icon, field, openSheet, setChildren, toast,
} from './ui.js';

const VIEW_KEY = 'mt.discover.v1';
const PAGE = 60;

/* The two answers on the rating scale that are not ratings. `none` is what
 * Wikidata says has none, which is most of a century of films — the MPA did
 * not exist before November 1968. `unknown` is what has not been asked about
 * yet, which is a different thing entirely and the picker says so. */
const SPECIAL = ['none', 'unknown'];

export const discover = {
  filter: 'all',           // all | boxoffice | awarded | topic:<id>
  sort: 'notable',
  yearFrom: 0,
  yearTo: 0,
  genres: [],              // folded ids: ['crime', 'western']
  genreMode: 'any',        // any of them, or all of them at once
  ratings: [],             // ['PG', 'PG-13'], plus 'none' and 'unknown'
  showSkipped: false,      // the ones passed over, instead of the ones left
  actor: '',               // one name, as billed
  // What a row says beyond the title, the people in it and what it is.
  // Both start off: the money a film took in 1937 and the company that put
  // it out are facts about the industry, not about whether to watch it.
  showMoney: false,
  showCrew: false,
};

/* What has been fetched from the server, and what it answered. */
const cache = {
  catalogue: null,
  coverage: null,
  facets: { genres: [], years: {}, ratings: [] },
  verdicts: { skip: 0 },
  // Where the rating pass has got to, so the picker can say how much of the
  // catalogue it is actually filtering. Asked for when the sheet opens.
  certs: null,
  films: [],
  total: 0,
  loading: false,
  error: '',
  query: '',
};

export function loadDiscover() {
  try {
    Object.assign(discover, JSON.parse(localStorage.getItem(VIEW_KEY) || '{}'));
  } catch { /* first run */ }
  // One saved genre from before combinations existed is one genre now.
  if (typeof discover.genre === 'string') {
    if (discover.genre && !discover.genres.length) discover.genres = [discover.genre];
    delete discover.genre;
  }
  discover.genres = (discover.genres || []).map((g) => String(g).toLowerCase());
  if (discover.genreMode !== 'all') discover.genreMode = 'any';
  // The two that are not ratings stay lowercase; a rating is the word as it
  // is printed, so PG-13 is what travels and what the server matches.
  discover.ratings = (discover.ratings || []).map((r) => (
    SPECIAL.includes(String(r).toLowerCase())
      ? String(r).toLowerCase() : String(r).toUpperCase()));
  discover.showSkipped = !!discover.showSkipped;
  discover.showMoney = !!discover.showMoney;
  discover.showCrew = !!discover.showCrew;
  discover.actor = String(discover.actor || '');
  return discover;
}

function save() {
  try { localStorage.setItem(VIEW_KEY, JSON.stringify(discover)); } catch { /* ignore */ }
}

/** Change what is being looked at, and remember it. */
export function setView(patch) {
  Object.assign(discover, patch);
  save();
  return discover;
}

/* ------------------------------------------------------------------ join */

/* Which of these are already yours. Matched on the Wikipedia article first —
 * it is the one identifier both sides carry and it tells The Killers of 1946
 * from The Killers of 1964 — then on the folded title and year, which is the
 * same key the importer de-duplicates with. */
function libraryIndex() {
  const byWiki = new Map();
  const byKey = new Map();
  for (const item of live()) {
    if (item.wikiUrl) byWiki.set(item.wikiUrl.replace(/_/g, ' ').toLowerCase(), item);
    byKey.set(titleKey(item.title, item.year), item);
    if (item.year) byKey.set(titleKey(item.title, null), item);
  }
  return (film) => byWiki.get((film.url || '').replace(/_/g, ' ').toLowerCase())
    || byKey.get(titleKey(film.title, film.year))
    || byKey.get(titleKey(film.title, null))
    || null;
}

/* ------------------------------------------------------------------ fetch */

function params(offset) {
  const query = new URLSearchParams();
  if (discover.yearFrom) query.set('from', String(discover.yearFrom));
  if (discover.yearTo) query.set('to', String(discover.yearTo));
  for (const genre of discover.genres) query.append('genre', genre);
  if (discover.genres.length > 1) query.set('genremode', discover.genreMode);
  // Ratings only ever widen: a film holds one or two, so PG *and* R would be
  // asking for nothing. There is no mode to send.
  for (const rating of discover.ratings) query.append('rating', rating);
  if (discover.filter.startsWith('topic:')) query.set('topic', discover.filter.slice(6));
  else if (discover.filter !== 'all') query.set('only', discover.filter);
  if (discover.actor) query.set('actor', discover.actor);
  query.set('skipped', discover.showSkipped ? 'only' : 'hide');
  query.set('sort', discover.sort);
  query.set('limit', String(PAGE));
  query.set('offset', String(offset));
  if (cache.query) query.set('q', cache.query);
  return query.toString();
}

let token = 0;

async function fetchFilms({ more = false } = {}) {
  const mine = ++token;
  cache.loading = true;
  cache.error = '';
  try {
    const offset = more ? cache.films.length : 0;
    const answer = await api('GET', `/lists/films?${params(offset)}`);
    if (mine !== token) return false;             // a newer query overtook it
    cache.films = more ? [...cache.films, ...answer.films] : answer.films;
    cache.total = answer.total;
    cache.coverage = answer.coverage;
    if (answer.facets) cache.facets = answer.facets;
    if (answer.verdicts) cache.verdicts = answer.verdicts;
  } catch (err) {
    if (mine !== token) return false;
    cache.error = err.message || 'the server did not answer';
  } finally {
    if (mine === token) cache.loading = false;
  }
  return true;
}

/* ------------------------------------------------------------------- rows */

const SIGNS = [
  (s) => (s.weeks ? `#1 for ${s.weeks} week${s.weeks > 1 ? 's' : ''}` : ''),
  (s) => (s.rank ? `${ordinal(s.rank)} highest-grossing` : ''),
  (s) => (s.topOfYear ? 'biggest of the year' : ''),
  (s) => s.award || '',
];

function ordinal(n) {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  return `${n}${['th', 'st', 'nd', 'rd'][n % 10] || 'th'}`;
}

function justWatch(film) {
  const q = [film.title, film.year].filter(Boolean).join(' ');
  return `https://www.justwatch.com/us/search?q=${encodeURIComponent(q)}`;
}

/* Names as the same word however they were typed, so a click on a cast list
 * finds the person and not the spelling. The server folds the same way. */
function fold(name) {
  return String(name || '').toLowerCase().normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
}

/* The links under a row. Wikipedia and a way to watch it are known from the
 * harvest; IMDb and its parents guide need the film's IMDb id, which arrives
 * with the poster — so they appear when it does, and not before. */
function linksFor(film) {
  const { imdb } = factsFor(film.article);
  return [
    film.url ? el('a.link-chip', {
      href: film.url, target: '_blank', rel: 'noopener noreferrer',
    }, [icon('wiki'), 'Wikipedia']) : null,
    imdb ? el('a.link-chip', {
      href: `https://www.imdb.com/title/${imdb}/`,
      target: '_blank', rel: 'noopener noreferrer',
    }, [icon('imdb'), 'IMDb']) : null,
    imdb ? el('a.link-chip', {
      href: `https://www.imdb.com/title/${imdb}/parentalguide/`,
      target: '_blank', rel: 'noopener noreferrer',
      title: 'What is in it, scene by scene',
    }, [icon('shield'), 'Parents guide']) : null,
    el('a.link-chip', {
      href: justWatch(film), target: '_blank', rel: 'noopener noreferrer',
    }, [icon('play'), 'Watch']),
  ];
}

/* The parts of a row that are only knowable once Wikidata has answered: the
 * age rating beside the year, and the two IMDb links. Put in place after the
 * row is already on the page rather than holding the row back for them, and
 * through the nodes the paint kept rather than by searching the document. */
function dressRow(place) {
  const { film, slot, heading, links, on } = place;
  const { thumb } = factsFor(film.article);
  const rating = factsFor(film.article).rating || film.rating || '';
  if (thumb) slot.replaceChildren(poster(thumb));
  if (rating && !place.rated) {
    place.rated = true;
    heading.append(certBadge(rating, on));
  }
  setChildren(links, linksFor(film));
}

/* The rating on a row is a way into everything else rated the same, the way
 * a genre badge beside it is. It is the question a row most often prompts —
 * what kind of evening is this — so answering it with one tap rather than a
 * trip to the filter sheet is the whole point of having it there. */
function certBadge(rating, on) {
  const held = discover.ratings.includes(rating);
  return el('button.tag-badge.cert', {
    type: 'button', text: rating, 'aria-pressed': String(held),
    title: held ? `Stop filtering by ${rating}` : `Everything rated ${rating}`,
    onclick: () => on.rating(rating),
  });
}

/* What the year lists did not print: the poster, the IMDb id and the age
 * rating.
 *
 * The poster is held as an address, not a picture — the browser fetches it
 * from Wikimedia and caches it there, and nothing about it is written to the
 * server's disk. An article that answers with nothing is remembered as having
 * nothing, so a blank row is only asked about once.
 */
const known = new Map();

const NOTHING = { thumb: '', imdb: '', rating: '' };

function factsFor(article) { return known.get(article) || NOTHING; }

/* The slots the current paint put on the page, so the answer can be dropped
 * into them without searching the document or re-rendering anything. */
let drawn = [];

function artSlot(film) {
  const slot = el('div.disco-art', { dataset: { article: film.article || '' } });
  const found = factsFor(film.article).thumb;
  if (found) slot.append(poster(found));
  else slot.append(el('span', { text: initials(film.title) }));
  return slot;
}

/* Most of the four hundred films a year nobody remembers have no free image
 * at all, so the standing-in matters: the first letter of each of the first
 * two words, which reads as a mark rather than as a truncated title. */
function initials(title) {
  const words = String(title || '?').trim().split(/\s+/).slice(0, 2);
  return words.map((word) => word[0]).join('').toUpperCase() || '?';
}

function poster(src) {
  return el('img', {
    // Stated so the row keeps its shape before the file lands, and so the
    // browser decodes no more pixels than the slot can show.
    src, alt: '', loading: 'lazy', decoding: 'async', width: '52', height: '78',
    onerror: (event) => event.target.remove(),
  });
}

/* Ask for the ones on screen whose article has not been asked about yet.
 * Fifty at a time, and the answer is dropped into the rows already drawn
 * rather than re-rendering them — nothing moves, the posters just arrive. */
export async function fillFacts() {
  const places = drawn;                   // a newer paint gets its own list
  const asking = [...new Set(places.map((p) => p.article).filter((a) => !known.has(a)))];
  if (!asking.length) return;

  for (let start = 0; start < asking.length; start += 50) {
    const batch = asking.slice(start, start + 50);
    const query = new URLSearchParams();
    for (const article of batch) query.append('a', article);
    let answer = {};
    try {
      answer = (await api('GET', `/lists/facts?${query}`)).facts || {};
    } catch {
      return;                       // no extras this time; the rows still read
    }
    for (const article of batch) known.set(article, answer[article] || NOTHING);
    if (places !== drawn) return;         // repainted while we were asking
    for (const place of places) {
      if (answer[place.article]) dressRow(place);
    }
  }
}

function row(film, on, mine) {
  const node = el('article.disco', { dataset: { key: film.key } });
  if (mine) node.classList.add('is-mine');

  // The rating comes down with the row, so it is on the page from the first
  // paint; the poster call only fills it in for a row the answer predates.
  // Drawn from what is already known rather than only when the answer
  // arrives, or it would be lost every time the row is painted again.
  const rated = factsFor(film.article).rating || film.rating || '';
  const heading = el('h3.disco-title', null, [
    film.title,
    film.year ? el('span.disco-year', { text: String(film.year) }) : null,
    rated ? certBadge(rated, on) : null,
  ]);

  // Who made it and what it took are off by default. They are facts about
  // the industry rather than about whether to spend an evening on it, and on
  // a phone they were most of the row.
  const facts = [];
  if (discover.showCrew && film.director) facts.push(el('span', { text: film.director }));
  if (discover.showCrew && film.studio) facts.push(el('span', { text: film.studio }));
  if (discover.showMoney && film.gross) facts.push(el('span', { text: film.gross }));

  const badges = [
    ...(film.genres || []).slice(0, 3).map((genre) => {
      const held = discover.genres.includes(genre.toLowerCase());
      return el('button.tag-badge.genre', {
        type: 'button', text: genre, 'aria-pressed': String(held),
        title: held ? `Stop filtering by ${genre}` : `Add ${genre} to the filter`,
        onclick: () => on.genre(genre),
      });
    }),
    ...SIGNS.map((read) => read(film.signals || {})).filter(Boolean)
      .map((text) => el('span.tag-badge.signal', { text })),
    ...(film.signals?.topics || []).map((id) => el('button.tag-badge', {
      type: 'button', text: `#${id}`, onclick: () => on.topic(id),
    })),
  ];

  const links = el('div.card-links.disco-links', null, linksFor(film));

  // Each name is a way into everything else they were in. Name and comma are
  // one unbreakable piece, or a line wraps between them and the next line
  // opens with a comma.
  const people = film.cast || [];
  const cast = el('div.card-cast', null, people.map((name, at) => el('span.castbit', null, [
    el('button.castname', {
      type: 'button', text: name,
      'aria-pressed': String(fold(name) === fold(discover.actor)),
      title: `Everything with ${name}`,
      onclick: () => on.actor(name),
    }),
    at < people.length - 1 ? ',' : null,
  ])));

  const body = el('div.disco-body', null, [
    heading,
    facts.length ? el('div.card-meta', null, facts) : null,
    people.length ? cast : null,
    badges.length ? el('div.disco-badges', null, badges) : null,
    links,
  ]);

  const add = mine
    ? el('button.btn.sm.ghost.disco-act', {
      type: 'button', title: `Already in your library — ${TYPE_LABEL[mine.type] || mine.type}`,
      onclick: () => on.open(mine),
    }, [icon('check'), 'Added'])
    : el('button.btn.sm.primary.disco-act', {
      type: 'button', 'aria-label': `Add ${film.title}`,
      onclick: () => on.add(film),
    }, [icon('plus'), 'Add']);

  // Passing on one is a verdict too, and the only one that makes the page
  // smaller — so it is a button on the row, not something behind a menu.
  // Already-yours rows have nothing to pass on.
  const pass = discover.showSkipped
    ? el('button.btn.sm.ghost.disco-act', {
      type: 'button', 'aria-label': `Put ${film.title} back`,
      title: 'Put this back among the rest',
      onclick: () => on.unskip(film, lift(node)),
    }, [icon('refresh'), 'Put back'])
    : (mine ? null : el('button.btn.sm.ghost.disco-act.skip', {
      type: 'button', 'aria-label': `Skip ${film.title}`,
      title: 'Not for me — take it off the list',
      onclick: () => on.skip(film, lift(node)),
    }, [icon('eye-off'), 'Skip']));

  const slot = artSlot(film);
  if (film.article) {
    drawn.push({ article: film.article, film, slot, heading, links, on, rated: !!rated });
  }

  node.append(slot, body, el('div.disco-acts', null, [add, pass]));
  return node;
}

/* Take a row off the page and hand back the way to put it exactly where it
 * was. A verdict during a run through four hundred films has to be instant
 * and it has to be undoable, and re-asking the server for the whole page is
 * neither — so the row leaves the document and keeps its place in it. */
function lift(node) {
  const parent = node.parentNode;
  const next = node.nextSibling;
  node.remove();
  return () => {
    if (!parent) return;
    if (next) parent.insertBefore(node, next);
    else parent.append(node);
  };
}

/* ----------------------------------------------------------------- adding */

/* Everything the harvest already knows travels with it, so a title added
 * here starts with its year, its director, its cast and its genres rather
 * than as a bare name the fill-in pass has to identify from scratch. The
 * Wikipedia article comes too — it is the exact one, not a guess at the URL,
 * which is what lets the enricher ask Wikidata for the IMDb id directly. */
export function addFilm(film) {
  const tags = (film.signals?.topics || []).slice(0, 3);
  const item = addItem({
    title: film.title,
    year: film.year || null,
    type: 'movie',
    status: 'queue',
    creator: film.director || '',
    cast: film.cast || [],
    genres: film.genres || [],
    wikiUrl: film.url || '',
    tags,
    notes: [film.studio, film.gross].filter(Boolean).join(' · '),
  });
  // Artwork, cast and the IMDb id, for this one title rather than the library.
  if (state.config?.network) {
    api('POST', '/enrich', { action: 'start', scope: 'missing', ids: [item.id] })
      .catch(() => { /* it will be picked up by the next full pass */ });
  }
  return item;
}

/* --------------------------------------------------------------- verdicts */

/* Skipping is recorded on the server, not in this browser: it is the half of
 * the signal that says *not this*, and the half a recommendation will be
 * built out of, so it has to outlive the tab and reach the phone. The counts
 * are kept in step here so the toolbar does not have to re-ask for them. */
/** Record a verdict, and account for the row leaving the list it was in.
 *
 * `shown` is that accounting and it is -1 in both ordinary directions: a skip
 * takes the row out of the films, a put-back takes it out of the skipped.
 * Undoing either is the same call with `shown: 1`, because the row is being
 * put back where it came from.
 */
export async function setVerdict(film, verdict, { shown = -1 } = {}) {
  const step = verdict === 'skip' ? 1 : -1;
  cache.verdicts.skip = Math.max(0, (cache.verdicts.skip || 0) + step);
  cache.total = Math.max(0, cache.total + shown);
  try {
    const answer = await api('POST', '/verdicts', { key: film.key, verdict });
    if (answer && answer.counts) cache.verdicts = answer.counts;
  } catch (err) {
    cache.verdicts.skip = Math.max(0, (cache.verdicts.skip || 0) - step);
    cache.total = Math.max(0, cache.total - shown);
    throw err;
  }
  return cache.verdicts;
}

export function skippedCount() { return cache.verdicts.skip || 0; }

/* --------------------------------------------------------------- painting */

function groupByYear(films) {
  const map = new Map();
  for (const film of films) {
    const key = film.year ? String(film.year) : '0000';
    if (!map.has(key)) {
      map.set(key, { key, label: film.year ? String(film.year) : 'No year', items: [] });
    }
    map.get(key).items.push(film);
  }
  return [...map.values()];
}

export function renderDiscover(root, on) {
  const mineOf = libraryIndex();
  const nodes = [];
  drawn = [];

  if (cache.error) {
    nodes.push(el('div.center-note', null, [
      el('div', { text: cache.error }),
      el('button.btn.sm.ghost', { type: 'button', text: 'Try again', onclick: on.reload }),
    ]));
  } else if (cache.loading && !cache.films.length) {
    nodes.push(el('div.center-note', null, [el('div.spinner'), 'Reading the lists…']));
  } else if (!cache.films.length) {
    nodes.push(emptyState(on));
  } else {
    const grouped = discover.sort.startsWith('year');
    const groups = grouped
      ? groupByYear(cache.films)
      : [{ key: 'all', label: '', items: cache.films }];
    for (const group of groups) {
      const section = el('section.group', { dataset: { key: group.key } });
      if (group.label) {
        section.append(el('div.group-head.static', null, [
          el('h2', { text: group.label }),
          el('span.group-count', { text: String(group.items.length) }),
        ]));
      }
      const list = el('div.group-items');
      for (const film of group.items) list.append(row(film, on, mineOf(film)));
      section.append(list);
      nodes.push(section);
    }
    if (cache.films.length < cache.total) {
      nodes.push(el('div.disco-more', null, el('button.btn.ghost', {
        type: 'button',
        text: cache.loading ? 'Loading…' : `Show more (${cache.total - cache.films.length} left)`,
        disabled: cache.loading,
        onclick: on.more,
      })));
    }
  }

  root.replaceChildren(...nodes);
  if (state.config?.network) fillFacts();
}

function emptyState(on) {
  const harvested = cache.coverage && cache.coverage.films;
  if (discover.showSkipped) {
    return el('div.empty-state', null, [
      el('h2', { text: filterSummary() ? 'None of those were skipped' : 'Nothing skipped yet' }),
      el('p', {
        text: 'Press Skip on a row and it comes here instead of back into the '
            + 'list. What is here is the half of the signal that says not this '
            + 'one, which is the half worth having.',
      }),
      el('button.btn.primary', {
        type: 'button',
        onclick: () => { setView({ showSkipped: false }); on.change(); },
      }, [icon('list'), 'Back to the films']),
    ]);
  }
  // Combining genres makes an empty answer easy to reach on purpose, and
  // "collect more years" is the wrong remedy for it — the filters are.
  const narrowed = filterSummary();
  // Asking for PG-13 before the lookup pass has run finds nothing, and the
  // remedy for that is not a wider year range — so it is named here rather
  // than left to be discovered inside the sheet.
  const unread = discover.ratings.length
    && !discover.ratings.includes('unknown')
    && (cache.facets.ratings || []).some((r) => r.id === 'unknown' && r.count);
  return el('div.empty-state', null, [
    el('h2', { text: harvested ? 'Nothing matches that' : 'No lists collected yet' }),
    el('p', {
      text: (unread && `Nothing looked up so far is ${narrowed}. Most of what `
              + 'is collected has not been asked about yet — the Rating filter '
              + 'has the button that fixes that.')
        || (narrowed && `Nothing collected is ${narrowed}`)
        || (harvested && 'There are films here, but not for that topic or search.')
        || 'Wikipedia publishes a list of every American film released, for every '
          + 'year, alongside the weekly box-office number ones and the year’s '
          + 'top ten. Collect them once and they are yours to browse offline.',
    }),
    unread ? el('button.btn.primary', {
      type: 'button', onclick: () => openRefine(on, { focus: 'ratings' }),
    }, [icon('shield'), 'Look up the ratings']) : null,
    narrowed ? el(unread ? 'button.btn.ghost' : 'button.btn.primary', {
      type: 'button',
      onclick: () => {
        setView({ yearFrom: 0, yearTo: 0, genres: [], genreMode: 'any', ratings: [] });
        on.change();
      },
    }, [icon('x'), 'Clear the filters']) : null,
    el(narrowed ? 'button.btn.ghost' : 'button.btn.primary',
      { type: 'button', onclick: on.fetch },
      [icon('download'), harvested ? 'Collect more years' : 'Collect the lists']),
  ]);
}

/* Counts and a line about what the list is showing. */
export function discoverStats(node) {
  const coverage = cache.coverage || { films: 0, years: {} };
  const years = Object.keys(coverage.years || {}).length;
  const summary = filterSummary();
  setChildren(node, [
    el('b', { text: String(cache.total) }),
    el('span', { text: discover.showSkipped ? ' skipped' : ' shown' }),
    summary ? el('span.stat-filter', { text: summary }) : null,
    el('span.divider'),
    el('b', { text: String(coverage.films || 0) }),
    el('span', { text: ` collected across ${years} year${years === 1 ? '' : 's'}` }),
    !discover.showSkipped && skippedCount() ? el('span', {
      text: `${skippedCount()} skipped`,
    }) : null,
  ]);
  node.hidden = false;
}

/* ---------------------------------------------------------------- toolbar */

const SORTS = [
  { id: 'notable', label: 'Most notable' },
  { id: 'year', label: 'Year, new→old' },
  { id: 'year-asc', label: 'Year, old→new' },
  { id: 'title', label: 'Title A→Z' },
];

/* The genres are named by the server with the counts, so the label a person
 * reads comes from the data rather than from a list kept in step by hand. */
function genreLabel(id) {
  const known = (cache.facets.genres || []).find((g) => g.id === id);
  return known ? known.label : id.replace(/\b\w/g, (c) => c.toUpperCase());
}

function genreCount(id) {
  const known = (cache.facets.genres || []).find((g) => g.id === id);
  return known ? known.count : 0;
}

/** Follow one name, or stop following it when it is the one already on. */
export function setActor(name) {
  const wanted = String(name || '');
  return setView({ actor: discover.actor === wanted ? '' : wanted });
}

/** Add or remove one genre, keeping the order they were picked in. */
export function toggleGenre(id) {
  const genre = String(id).toLowerCase();
  const genres = discover.genres.includes(genre)
    ? discover.genres.filter((g) => g !== genre)
    : [...discover.genres, genre];
  return setView({ genres });
}

/** Add or remove one rating. Several always mean any of them. */
export function toggleRating(id) {
  const rating = SPECIAL.includes(String(id).toLowerCase())
    ? String(id).toLowerCase() : String(id).toUpperCase();
  const ratings = discover.ratings.includes(rating)
    ? discover.ratings.filter((r) => r !== rating)
    : [...discover.ratings, rating];
  return setView({ ratings });
}

/* What a rating is called where it is not a rating. The server sends the
 * label with the count, the same way it does for genres, so a chip already
 * chosen still reads properly when nothing came back to name it. */
const RATING_LABEL = { none: 'Not rated', unknown: 'Not looked up' };

function ratingLabel(id) {
  const known = (cache.facets.ratings || []).find((r) => r.id === id);
  return (known && known.label) || RATING_LABEL[id] || id;
}

/* What the filters add up to, in the words the toolbar uses: "Crime and
 * Western, 1931–1939". Shown beside the count so the number has a subject. */
export function filterSummary() {
  const parts = [];
  if (discover.genres.length) {
    const names = discover.genres.map(genreLabel);
    parts.push(names.length === 1 ? names[0]
      : names.join(discover.genreMode === 'all' ? ' + ' : ' or '));
  }
  if (discover.ratings.length) parts.push(discover.ratings.map(ratingLabel).join(' or '));
  if (discover.actor) parts.push(discover.actor);
  if (discover.yearFrom && discover.yearTo) parts.push(`${discover.yearFrom}–${discover.yearTo}`);
  else if (discover.yearFrom) parts.push(`${discover.yearFrom} onwards`);
  else if (discover.yearTo) parts.push(`up to ${discover.yearTo}`);
  return parts.join(' · ');
}

/* The decades the harvest actually covers. Taken from the coverage rather
 * than from the current answer, so a decade does not disappear from the
 * picker the moment a genre is chosen that has nothing in it — it stands
 * there with a zero, which is the useful thing to know. */
function decades() {
  const years = Object.keys((cache.coverage || {}).years || {})
    .map(Number).filter(Boolean);
  const tens = [...new Set(years.map((y) => Math.floor(y / 10) * 10))];
  return tens.sort((a, b) => a - b);
}

function inDecade(ten) {
  const counts = cache.facets.years || {};
  let total = 0;
  for (const [year, count] of Object.entries(counts)) {
    if (Number(year) >= ten && Number(year) < ten + 10) total += count;
  }
  return total;
}

export function buildTools(bar, on) {
  const tabs = el('div.viewtabs', { role: 'tablist', 'aria-label': 'Which films' });

  const tab = (id, label) => {
    const button = el('button', {
      type: 'button', role: 'tab', dataset: { pick: id },
      'aria-selected': String(discover.filter === id),
      onclick: () => { discover.filter = id; save(); on.change(); },
    }, el('span.tab-label', { text: label }));
    return button;
  };

  // Only the topics actually collected: a tab that can only ever be empty is
  // a dead end, and the collect sheet is where the rest are offered.
  const topics = (cache.catalogue?.topics || [])
    .filter((t) => (cache.coverage?.pages || {})[`topic:${t.id}`]);
  tabs.append(
    tab('all', 'Everything'),
    tab('boxoffice', 'Box office'),
    tab('awarded', 'Awarded'),
    ...topics.map((t) => tab(`topic:${t.id}`, t.label)),
  );

  const from = el('input.input.yr', {
    type: 'number', inputmode: 'numeric', placeholder: 'from',
    value: discover.yearFrom || '', 'aria-label': 'From year',
  });
  const to = el('input.input.yr', {
    type: 'number', inputmode: 'numeric', placeholder: 'to',
    value: discover.yearTo || '', 'aria-label': 'To year',
  });
  const settle = (input, key) => input.addEventListener('change', () => {
    discover[key] = Number(input.value) || 0;
    save();
    on.change();
  });
  settle(from, 'yearFrom');
  settle(to, 'yearTo');

  const yearSet = discover.yearFrom || discover.yearTo;
  const yearWrap = el('label.chip.yr-chip', {
    'aria-pressed': String(Boolean(yearSet)),
  }, [el('span.yr-range', null, [from, '–', to])]);
  if (yearSet) {
    yearWrap.append(el('button.icon-btn.tiny', {
      type: 'button', 'aria-label': 'All years',
      onclick: () => { setView({ yearFrom: 0, yearTo: 0 }); on.change(); },
    }, icon('x')));
  }

  const sort = el('select', { 'aria-label': 'Sort by' });
  for (const option of SORTS) {
    sort.append(el('option', {
      value: option.id, text: option.label, selected: option.id === discover.sort,
    }));
  }
  sort.addEventListener('change', () => { discover.sort = sort.value; save(); on.change(); });

  // The picker, and then one removable chip per genre already chosen — the
  // combination has to be readable without opening anything.
  const picked = discover.genres.length;
  const genreBtn = el('button.chip', {
    type: 'button', dataset: { control: 'genres' },
    'aria-pressed': String(picked > 0),
    title: 'Filter by genre',
    onclick: () => openRefine(on),
  }, [icon('tag'), el('span', {
    text: picked ? `Genres ${picked}` : 'Genres',
  })]);

  const genreChips = discover.genres.map((id) => el('button.chip.chip-toggle.genre-chip', {
    type: 'button', 'aria-pressed': 'true', dataset: { genre: id },
    title: `Remove ${genreLabel(id)}`,
    onclick: () => { toggleGenre(id); on.change(); },
  }, [el('span', { text: genreLabel(id) }), icon('x')]));

  // The rating, which answers a different question from all the rest of
  // these — not what a film is, but what kind of evening it is and who can
  // be in the room. It gets its own chip beside the genres for that reason.
  const rated = discover.ratings.length;
  const certBtn = el('button.chip', {
    type: 'button', dataset: { control: 'ratings' },
    'aria-pressed': String(rated > 0),
    title: 'Filter by age rating',
    onclick: () => openRefine(on, { focus: 'ratings' }),
  }, [icon('shield'), el('span', {
    // A rating is two or three characters, so up to three of them read
    // better in the bar than three chips would. Past that it is a count,
    // the way the genres are.
    text: (rated && rated <= 3 && discover.ratings.map(ratingLabel).join(', '))
      || (rated ? `Rating ${rated}` : 'Rating'),
  })]);

  const certClear = rated ? el('button.icon-btn.tiny.cert-clear', {
    type: 'button', 'aria-label': 'Any rating',
    onclick: () => { setView({ ratings: [] }); on.change(); },
  }, icon('x')) : null;

  // Two genres mean nothing until it is said how they combine, so the switch
  // appears exactly when there is something for it to switch.
  const modeChip = picked > 1 ? el('button.chip.mode-chip', {
    type: 'button', dataset: { control: 'mode' },
    title: discover.genreMode === 'all'
      ? 'Showing films that are all of these — tap for any of them'
      : 'Showing films that are any of these — tap for all of them',
    onclick: () => {
      setView({ genreMode: discover.genreMode === 'all' ? 'any' : 'all' });
      on.change();
    },
  }, [icon('shuffle'), el('span', {
    text: discover.genreMode === 'all' ? 'all of these' : 'any of these',
  })]) : null;

  // Whoever is being followed at the moment, and the way to stop.
  const castChip = discover.actor ? el('button.chip.chip-toggle.actor-chip', {
    type: 'button', 'aria-pressed': 'true', dataset: { control: 'actor' },
    title: `Stop following ${discover.actor}`,
    onclick: () => { setView({ actor: '' }); on.change(); },
  }, [el('span', { text: discover.actor }), icon('x')]) : null;

  // The other half of the triage: what has been passed over, so a verdict
  // can be looked at again rather than being a one-way door.
  const passed = el('button.chip.chip-toggle', {
    type: 'button', dataset: { control: 'skipped' },
    'aria-pressed': String(discover.showSkipped),
    title: discover.showSkipped
      ? 'Back to the ones you have not decided about'
      : 'Look again at the ones you passed over',
    onclick: () => { setView({ showSkipped: !discover.showSkipped }); on.change(); },
  }, [icon('eye-off'), el('span', { text: 'Skipped' }),
      el('span.chip-count', { text: String(skippedCount()) })]);

  setChildren(bar, [
    tabs,
    el('span.bar-sep', { 'aria-hidden': 'true' }),
    yearWrap,
    genreBtn,
    ...genreChips,
    modeChip,
    certBtn,
    certClear,
    castChip,
    el('label.chip.chip-select', null, [icon('sort'), sort]),
    passed,
    el('button.chip', { type: 'button', onclick: on.fetch },
      [icon('download'), el('span', { text: 'Collect' })]),
  ]);
}

/* ------------------------------------------------------------- refining */

/* Year and genre, with room to combine them.
 *
 * Nothing is drafted and applied: every tap goes straight through to the
 * list underneath and the counts come back from the same answer, so the
 * numbers on the chips are what choosing them would actually give rather
 * than what they gave before the last two taps.
 */
export function openRefine(on, { focus = '' } = {}) {
  const body = el('div');
  const years = el('div');
  const genres = el('div');
  const certs = el('div');
  const rows = el('div');
  const total = el('p.hint');
  let expanded = false;

  const refresh = () => {
    paint();
    Promise.resolve(on.change()).then(paint, () => {});
  };

  /* The pass that asks Wikidata what everything was rated.
   *
   * Every other filter here reads something Wikipedia's year lists printed,
   * so it works the moment a year is collected. The rating is the one that
   * does not: it lives in Wikidata, fifty films to a query and a second and
   * a half a query, and until it has been fetched a film is *not looked up*
   * rather than *not rated*. So the picker says which, and offers the fetch
   * here — where the gap in it is actually noticed — rather than burying it
   * in the collect sheet next to the harvest.
   *
   * It runs on the server and survives this sheet being closed. What it has
   * written stays written, so stopping it and starting it again a week later
   * carries on rather than beginning again.
   */
  let timer = 0;
  const pass = el('div.cert-pass');

  const askPass = async () => {
    const was = cache.certs && cache.certs.running;
    try { cache.certs = await api('GET', '/lists/certs'); } catch { return; }
    clearTimeout(timer);
    if (cache.certs.running) { paintPass(); timer = setTimeout(askPass, 2000); }
    // Every count on every chip above is now a different number, and so is
    // the list underneath — so the end of the pass is a repaint, not a line
    // of text saying it finished.
    else if (was) refresh();
    else paintPass();
  };

  const runPass = async (action) => {
    try {
      cache.certs = await api('POST', '/lists/certs', { action });
    } catch (err) {
      toast(err.message || 'could not start the lookup', { error: true });
      return;
    }
    paintPass();
    clearTimeout(timer);
    if (cache.certs.running) timer = setTimeout(askPass, 1500);
    // What it learns changes the counts on every chip above, so the list
    // underneath is asked again once the pass has finished.
    else refresh();
  };

  function paintPass() {
    const status = cache.certs;
    if (!status) { pass.replaceChildren(); return; }
    if (status.running) {
      const left = Math.max(1, Math.ceil(status.etaSeconds / 60));
      setChildren(pass, [
        el('div.sync-line', null, [
          el('span.sync-dot.busy'),
          el('span', {
            text: `Looking up ${status.done} of ${status.total} — about `
                + `${left} min left. You can close this; it keeps going.`,
          }),
        ]),
        el('button.btn.sm.ghost', {
          type: 'button', text: 'Stop', onclick: () => runPass('stop'),
        }),
      ]);
      return;
    }
    if (!status.unknown) {
      setChildren(pass, [el('p.hint', {
        text: `All ${status.films} collected films have been looked up; `
            + `${status.rated} of them carry a rating.`,
      })]);
      return;
    }
    // The number that makes the difference between a filter and a guess.
    setChildren(pass, [
      el('p.hint', {
        text: `${status.unknown} of ${status.films} collected films have not `
            + 'been looked up yet, so they answer to Not looked up rather '
            + 'than to a rating.',
      }),
      status.network ? el('button.btn.sm.primary', {
        type: 'button', onclick: () => runPass('start'),
      }, [icon('download'), 'Look them up']) : el('p.hint', {
        text: 'Lookups are switched off in this container.',
      }),
    ]);
  }

  const decadeChip = (ten) => el('button.chip.chip-toggle', {
    type: 'button',
    'aria-pressed': String(discover.yearFrom === ten && discover.yearTo === ten + 9),
    onclick: () => {
      const on_ = discover.yearFrom === ten && discover.yearTo === ten + 9;
      setView(on_ ? { yearFrom: 0, yearTo: 0 }
        : { yearFrom: ten, yearTo: ten + 9 });
      refresh();
    },
  }, [el('span', { text: `${ten}s` }),
      el('span.chip-count', { text: String(inDecade(ten)) })]);

  const genreChip = (facet) => el('button.chip.chip-toggle', {
    type: 'button', dataset: { genre: facet.id },
    'aria-pressed': String(discover.genres.includes(facet.id)),
    onclick: () => { toggleGenre(facet.id); refresh(); },
  }, [el('span', { text: facet.label }),
      el('span.chip-count', { text: String(facet.count) })]);

  const certChip = (facet) => el('button.chip.chip-toggle', {
    type: 'button', dataset: { rating: facet.id },
    'aria-pressed': String(discover.ratings.includes(facet.id)),
    title: facet.id === 'unknown'
      ? 'Collected, but Wikidata has not been asked what it was rated'
      : (facet.id === 'none'
        ? 'Wikidata has no rating for these — most films before 1968 never had one'
        : `Rated ${facet.id}`),
    onclick: () => { toggleRating(facet.id); refresh(); },
  }, [el('span', { text: facet.label }),
      el('span.chip-count', { text: String(facet.count) })]);

  function paint() {
    const from = el('input.input', {
      type: 'number', inputmode: 'numeric', placeholder: 'from',
      value: discover.yearFrom || '', 'aria-label': 'From year',
      onchange: (event) => { setView({ yearFrom: Number(event.target.value) || 0 }); refresh(); },
    });
    const to = el('input.input', {
      type: 'number', inputmode: 'numeric', placeholder: 'to',
      value: discover.yearTo || '', 'aria-label': 'To year',
      onchange: (event) => { setView({ yearTo: Number(event.target.value) || 0 }); refresh(); },
    });
    const spread = decades();
    setChildren(years, [
      el('div.row', null, [from, to]),
      spread.length ? el('div.chip-row.decades', null, [
        el('button.chip.chip-toggle', {
          type: 'button',
          'aria-pressed': String(!discover.yearFrom && !discover.yearTo),
          text: 'All years',
          onclick: () => { setView({ yearFrom: 0, yearTo: 0 }); refresh(); },
        }),
        ...spread.map(decadeChip),
      ]) : null,
    ]);

    // Everything collected has a genre or it has not; the ones with one film
    // behind them are real but they are not what a picker is for, so the tail
    // waits behind a word rather than being dropped.
    const all = cache.facets.genres || [];
    const chosen = discover.genres.filter((id) => !all.some((g) => g.id === id))
      .map((id) => ({ id, label: genreLabel(id), count: genreCount(id) }));
    const offered = [...chosen, ...all];
    const head = expanded ? offered : offered.slice(0, 14);
    const rest = offered.length - head.length;

    setChildren(genres, [
      discover.genres.length > 1 ? el('div.seg.mode-seg', null, [
        el('button', {
          type: 'button', text: 'Any of these',
          'aria-pressed': String(discover.genreMode !== 'all'),
          onclick: () => { setView({ genreMode: 'any' }); refresh(); },
        }),
        el('button', {
          type: 'button', text: 'All of these',
          'aria-pressed': String(discover.genreMode === 'all'),
          onclick: () => { setView({ genreMode: 'all' }); refresh(); },
        }),
      ]) : null,
      el('div.chip-row', null, [
        ...head.map(genreChip),
        rest > 0 ? el('button.chip.ghost-chip', {
          type: 'button', text: `${rest} more…`,
          onclick: () => { expanded = true; paint(); },
        }) : null,
      ]),
      discover.genres.length ? el('button.btn.sm.ghost', {
        type: 'button', text: 'Clear genres',
        onclick: () => { setView({ genres: [] }); refresh(); },
      }) : null,
    ]);

    // The scale, plus anything already chosen that this cut has none of —
    // so a chip stays where it was rather than vanishing when the count that
    // named it goes to zero.
    const scale = cache.facets.ratings || [];
    const held = discover.ratings.filter((id) => !scale.some((r) => r.id === id))
      .map((id) => ({ id, label: ratingLabel(id), count: 0 }));
    setChildren(certs, [
      el('div.chip-row', null, [
        el('button.chip.chip-toggle', {
          type: 'button', text: 'Any rating',
          'aria-pressed': String(!discover.ratings.length),
          onclick: () => { setView({ ratings: [] }); refresh(); },
        }),
        ...[...held, ...scale].map(certChip),
      ]),
      pass,
    ]);
    paintPass();

    const shows = (label, key, note) => el('button.chip.chip-toggle', {
      type: 'button', 'aria-pressed': String(!!discover[key]), title: note,
      text: label,
      onclick: () => { setView({ [key]: !discover[key] }); paint(); on.change(); },
    });
    setChildren(rows, [
      el('div.chip-row', null, [
        shows('The money it took', 'showMoney',
          'What it grossed, as the year list printed it'),
        shows('Director and studio', 'showCrew',
          'Who directed it and who released it'),
      ]),
    ]);

    const summary = filterSummary();
    total.textContent = `${cache.total} film${cache.total === 1 ? '' : 's'}`
      + (summary ? ` — ${summary}` : ' — everything collected');
  }

  paint();
  askPass();
  body.append(
    field('Year', years,
      'A decade is one tap; the boxes take any range. The number on a decade '
      + 'is what it holds under the genres chosen below.'),
    field('Genre', genres,
      'Pick as many as you like. Any of these is the wider net — crime or '
      + 'western; all of these is the narrower one — the crime films that are '
      + 'also westerns. The number is how many carry that genre in the years '
      + 'showing.'),
    field('Rating', certs,
      'G, PG, PG-13 and the rest, as Wikidata has them. Picking several is '
      + 'any of them — a film holds one or two, so asking for both PG and R '
      + 'would be asking for nothing. Not rated is the honest answer for most '
      + 'films before November 1968, when there was no MPA to rate them.'),
    field('On each row', rows,
      'The people in it, what it is and how it did are always there. These two '
      + 'are off because they are facts about the industry rather than about '
      + 'whether to watch it — turn them back on if you want them.'),
    field('Showing', total),
  );

  const clear = el('button.btn.ghost.grow', { type: 'button', text: 'Clear all' });
  const done = el('button.btn.primary.grow', { type: 'button', text: 'Done' });
  const handle = openSheet({
    title: 'What to show',
    body,
    footer: [clear, done],
    onClose: () => clearTimeout(timer),
  });
  clear.addEventListener('click', () => {
    setView({ yearFrom: 0, yearTo: 0, genres: [], genreMode: 'any',
              ratings: [], actor: '' });
    refresh();
  });
  done.addEventListener('click', () => handle.close());
  if (focus === 'ratings') certs.scrollIntoView?.({ block: 'nearest' });
  return handle;
}

/* ------------------------------------------------------------ the harvest */

/* The collecting sheet. Wikimedia asks for about a call a second, so a
 * century of three pages a year is minutes rather than seconds — it runs on
 * the server, survives this tab being closed, and archives each page the
 * moment it is parsed. */
export function openHarvest(onDone) {
  const body = el('div');
  const line = el('div.sync-line');
  const bar = el('div.progress', null, el('i'));
  const detail = el('p.hint');
  const start = el('button.btn.primary.grow', { type: 'button', text: 'Collect' });
  const stop = el('button.btn.ghost', { type: 'button', text: 'Stop' });

  const chosen = {
    sets: new Set(['american', 'boxoffice', 'yearfilm']),
    topics: new Set(),
  };
  const range = { from: discover.yearFrom || suggestFrom(), to: discover.yearTo || suggestTo() };
  let timer = 0;

  const paint = (status) => {
    const pct = status.total ? Math.round((status.done / status.total) * 100) : 0;
    bar.firstChild.style.setProperty('--w', `${pct}%`);
    bar.hidden = !status.total;
    line.replaceChildren(
      el('span.sync-dot', { class: status.running ? 'busy' : '' }),
      el('span', {
        text: status.running
          ? `${status.done} of ${status.total} — ${status.current || 'starting…'}`
          : status.note || 'Not running',
      }),
    );
    detail.textContent = status.running
      ? `About ${Math.max(1, Math.ceil(status.etaSeconds / 60))} min left. `
        + `${status.films} films so far. You can close this — it keeps going.`
      : `${(status.coverage || {}).films || 0} films collected. Pages already `
        + 'fetched are re-read from disk, so collecting a year twice costs nothing.';
    start.disabled = status.running || !status.network;
    stop.disabled = !status.running;
    if (status.coverage) cache.coverage = status.coverage;
  };

  const poll = async () => {
    try {
      const status = await api('GET', '/lists');
      cache.catalogue = status.catalogue;
      paint(status);
      if (!status.running) { onDone(); clearTimeout(timer); return; }
      onDone();
    } catch { /* the sheet stays open; the next tick tries again */ }
    timer = setTimeout(poll, 2500);
  };

  const setBox = (id, label, note) => {
    const box = el('input', {
      type: 'checkbox', checked: chosen.sets.has(id),
      onchange: (event) => {
        if (event.target.checked) chosen.sets.add(id); else chosen.sets.delete(id);
      },
    });
    return el('label.pickrow', null, [box, el('span', null, [
      el('b', { text: label }), el('small', { text: note }),
    ])]);
  };

  const topicBox = (topic) => {
    const box = el('input', {
      type: 'checkbox',
      onchange: (event) => {
        if (event.target.checked) chosen.topics.add(topic.id);
        else chosen.topics.delete(topic.id);
      },
    });
    return el('label.pickrow', null, [box, el('span', null, [
      el('b', { text: topic.label }), el('small', { text: topic.note }),
    ])]);
  };

  const from = el('input.input', {
    type: 'number', inputmode: 'numeric', value: String(range.from), 'aria-label': 'From year',
    onchange: (event) => { range.from = Number(event.target.value) || 0; },
  });
  const to = el('input.input', {
    type: 'number', inputmode: 'numeric', value: String(range.to), 'aria-label': 'To year',
    onchange: (event) => { range.to = Number(event.target.value) || 0; },
  });

  const sets = el('div');
  const topics = el('div');

  body.append(
    field('Years', el('div.row', null, [from, to]),
      'One year is three pages and about eight seconds. A whole decade is a '
      + 'couple of minutes. Nothing is fetched twice unless you ask for it again.'),
    field('What to collect from each year', sets),
    field('And these, whatever year they are from', topics),
    field('Progress', el('div', null, [line, bar, detail])),
  );

  body.append(el('p.hint', {
    text: 'Everything lands in data/lists/ as JSON — the pages exactly as they were '
        + 'parsed, and the merge built from them. The merge can be rebuilt from the '
        + 'archive without asking Wikipedia for any of it again.',
  }));

  const rebuild = el('button.btn.sm.ghost', { type: 'button', text: 'Rebuild the merge' });
  rebuild.addEventListener('click', async () => {
    rebuild.disabled = true;
    try {
      paint(await api('POST', '/lists', { action: 'rebuild' }));
      onDone();
      toast('Merged again from what is on disk');
    } catch (err) { toast(err.message || 'could not rebuild', { error: true }); }
    rebuild.disabled = false;
  });
  body.append(field('Already collected', el('div.chip-row', null, [rebuild])));

  start.addEventListener('click', async () => {
    start.disabled = true;
    try {
      paint(await api('POST', '/lists', {
        action: 'start',
        sets: [...chosen.sets],
        topics: [...chosen.topics],
        from: range.from,
        to: range.to,
      }));
      clearTimeout(timer);
      poll();
    } catch (err) {
      toast(err.message || 'could not start', { error: true });
      start.disabled = false;
    }
  });
  stop.addEventListener('click', async () => {
    try { paint(await api('POST', '/lists', { action: 'stop' })); }
    catch { /* it stops on its own soon enough */ }
  });

  const handle = openSheet({
    title: 'Collect the lists',
    body,
    footer: [stop, start],
    onClose: () => clearTimeout(timer),
  });

  api('GET', '/lists').then((status) => {
    cache.catalogue = status.catalogue;
    sets.replaceChildren(...status.catalogue.sets.map(
      (s) => setBox(s.id, s.label, s.note)));
    topics.replaceChildren(...status.catalogue.topics.map(topicBox));
    from.min = String(status.catalogue.firstYear);
    to.max = String(status.catalogue.lastYear);
    paint(status);
    if (status.running) poll();
  }).catch(() => { detail.textContent = 'The server did not answer.'; });

  return handle;
}

/* A first range that is about the library you already have, rather than 1900. */
function suggestFrom() {
  const years = live().map((i) => i.year).filter(Boolean).sort((a, b) => a - b);
  return years.length ? Math.max(1900, years[Math.floor(years.length * 0.1)] - 2) : 1940;
}

function suggestTo() {
  const years = live().map((i) => i.year).filter(Boolean).sort((a, b) => a - b);
  return years.length ? years[Math.floor(years.length * 0.9)] + 2 : 1949;
}

/* ------------------------------------------------------------------ entry */

/** Ask the server again, then repaint. */
export async function refreshDiscover(query, { more = false } = {}) {
  cache.query = query || '';
  return fetchFilms({ more });
}

export function discoverState() { return cache; }

export async function ensureCatalogue() {
  if (cache.catalogue) return cache.catalogue;
  try {
    const status = await api('GET', '/lists');
    cache.catalogue = status.catalogue;
    cache.coverage = status.coverage;
  } catch { /* the empty state says what to do about it */ }
  return cache.catalogue;
}

