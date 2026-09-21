/* Wiring: boot the store, render on change, and hook up the chrome. */

import {
  api, state, boot, onChange, notify, refresh, sync, live, stats, allTags,
  toggleHeart, toggleWatched, removeSource, addSource, checkpoint, undo,
  reorderQueue, patchItem, getItem, addItem, titleKey, fillIn, stage,
  TYPE_LABEL, STATUS_LABEL,
  enrich, watchEnrich, staging, staged, unstage,
} from './store.js';
import {
  el, icon, $, openSheet, closeAll, toast, field, fmtAgo, fmtDate, hostOf,
  confirmSheet, segmented,
} from './ui.js';
import {
  filters, loadView, saveView, activeCount, resetFilters, lingering, plainTerms,
  titleMatches, whyMatched,
  apply, sortItems, groupItems, openFilterSheet, queueOrder,
  SECTIONS, SECTION_LABEL, VIEWS, sectionOf, inView,
} from './filters.js';
import {
  renderGroups, renderQueue, renderStats, renderEmpty, renderYearMap, wireYearMap,
  renderStaging, stripSection, card, foundRow,
} from './views.js';
import { openItem, openRating, openAdd } from './editor.js';
import { openPortingSheet } from './porting.js';
import { rowToItem, viaLabel } from './importer.js';
import {
  loadDiscover, setView, buildTools, renderDiscover, refreshDiscover, toggleGenre,
  toggleRating,
  discoverStats, discoverState, openHarvest, addFilm, ensureCatalogue,
  setVerdict, setActor, searchCatalogue, catalogueRows, libraryIndex,
} from './discover.js';

/* The list is three boxes on top of each other: what was just added, the
 * list itself, and what a search found beyond this tab. Each is painted on
 * its own, so the middle one can keep its cards in place under a reader
 * while the other two come and go. */
const list = $('#list');
const boxes = {
  staging: el('div.list-staging', { hidden: true }),
  main: el('div.list-main'),
  more: el('div.list-more', { hidden: true }),
};
list.append(boxes.staging, boxes.main, boxes.more);

const dom = {
  q: $('#q'),
  sections: $('#seg-sections'),
  yearmap: $('#yearmap'),
  bubble: $('#ym-bubble'),
  viewtabs: $('#viewtabs'),
  wrapSort: $('#wrap-sort'),
  wrapGroup: $('#wrap-group'),
  qClear: $('#q-clear'),
  list: $('#list'),
  empty: $('#empty'),
  stats: $('#stats'),
  activeFilters: $('#active-filters'),
  filterBadge: $('#filter-badge'),
  btnFilters: $('#btn-filters'),
  btnMenu: $('#btn-menu'),
  btnAdd: $('#btn-add'),
  hideWatched: $('#t-hide-watched'),
  hearts: $('#t-hearts'),
  unrated: $('#t-unrated'),
  sort: $('#sel-sort'),
  group: $('#sel-group'),
  toolbar: $('#toolbar'),
  discoTools: $('#disco-tools'),
};

/* -------------------------------------------------------------- rendering */

/* How long a ticked title stays on screen before it leaves for the other
 * list — long enough to see what happened and tap it back. */
const LINGER_MS = 5000;
const lingerTimers = new Map();

const handlers = {
  open: (item) => openItem(item, { onChange: render, onDeleted: render }),
  heart: (item) => { toggleHeart(item.id); },
  rate: (item) => openRating(item, render),
  leaving: (item) => lingering.has(item.id),
  why: (item) => (filters.q.trim() ? whyMatched(item, filters.q) : ''),
  watched: (shown) => {
    // The card may be holding a copy a sync has since replaced; go by id.
    const item = getItem(shown.id) || shown;
    const wasWatched = item.status === 'watched';
    toggleWatched(item.id);
    // Does the tick take it out of the list on screen? Then it is held there,
    // greyed out, for a moment first. A second tap inside that moment puts it
    // back as if nothing happened; the same tap after it has gone is a trip
    // to the other list.
    clearTimeout(lingerTimers.get(item.id));
    lingerTimers.delete(item.id);
    lingering.delete(item.id);
    const gone = !apply([item]).length;
    if (gone) {
      lingering.add(item.id);
      lingerTimers.set(item.id, setTimeout(() => {
        lingering.delete(item.id);
        lingerTimers.delete(item.id);
        render();
      }, LINGER_MS));
      toast(`"${item.title}" ${wasWatched ? 'back in the queue' : 'watched'}`, {
        action: { label: 'Undo', fn: () => handlers.watched(item) },
      });
    }
  },
  tag: (tag) => {
    if (!filters.tags.includes(tag)) filters.tags.push(tag);
    saveView();
    render();
  },
  genre: (genre) => {
    /* Genres are not a saved facet the way tags are — they come from the
       providers, not from you — so this goes through the search box, where
       it is visible and one tap on the × undoes it. The whole token is
       quoted because "Romantic Comedy" has a space in it. */
    dom.q.value = `"genre:${genre.toLowerCase()}"`;
    filters.q = dom.q.value;
    searched();
  },
  cert: (cert) => {
    /* Unlike a genre, this one is a real saved facet — the very chip the
       filter sheet draws — so tapping the badge ticks it, and tapping the
       same badge again unticks it. */
    const index = filters.certs.indexOf(cert);
    if (index === -1) filters.certs.push(cert); else filters.certs.splice(index, 1);
    saveView();
    render();
  },
  year: (item, year) => {
    patchItem(item.id, { year });
    render();
    if (!year) { toast(`Year cleared from "${item.title}"`); return; }
    // Grouped by year, it has just moved somewhere else — offer to follow it.
    toast(`"${item.title}" moved to ${year}`, filters.group === 'year'
      ? { action: { label: 'Show', fn: () => jumpToGroup(String(year)) } }
      : undefined);
  },
  reorder: (visibleIds) => { commitQueueOrder(visibleIds); },
  jump: (id, position) => {
    const visible = queueOrder(apply(live())).map((item) => item.id);
    const from = visible.indexOf(id);
    const to = Math.max(0, Math.min(visible.length - 1, position - 1));
    if (from === -1 || from === to) return;
    const next = [...visible];
    next.splice(from, 1);
    next.splice(to, 0, id);
    commitQueueOrder(next);
    render();
    toast(`Moved to ${to + 1} of ${visible.length}`);
  },
};

/** Every queued title in the section on screen, in its current order. */
function sectionQueue() {
  return queueOrder(live().filter((item) =>
    sectionOf(item) === filters.section && inView(item, 'queue')));
}

/* A search or a filter can hide part of the queue. Reordering what you can
 * see must not scramble what you cannot, so the visible titles are written
 * back into the slots they already occupied in the full queue. */
function commitQueueOrder(visibleIds) {
  const all = sectionQueue().map((item) => item.id);
  const visible = new Set(visibleIds);
  const next = [...all];
  const slots = [];
  all.forEach((id, index) => { if (visible.has(id)) slots.push(index); });
  slots.forEach((slot, index) => { next[slot] = visibleIds[index]; });
  reorderQueue(next);
}

let pending = 0;
function render() {
  clearTimeout(pending);
  pending = setTimeout(paint, 0);
}

function paint() {
  const everything = live();

  if (inDiscover()) { paintTabs(everything); paintDiscover(); return; }
  showLibraryChrome();

  const searching = Boolean(filters.q.trim());
  const filtered = apply(everything);
  const isQueue = filters.view === 'queue';

  // A search does not stop at the tab that is open. The rest of the library
  // is asked the same question, and so is the catalogue — a title that is
  // not in the library yet is exactly the one worth finding from here.
  const terms = searching ? plainTerms(filters.q) : '';
  const byName = (title) => titleMatches(title, terms);
  // Found by name first, then found through the cast, the notes, a tag.
  const nameFirst = (rows, title) => [
    ...rows.filter((row) => byName(title(row))), ...rows.filter((row) => !byName(title(row)))];

  const shownIds = new Set(filtered.map((item) => item.id));
  const elsewhere = searching
    ? nameFirst(sortItems(apply(everything, { everywhere: true })
        .filter((item) => !shownIds.has(item.id))), (item) => item.title)
    : [];
  const found = searching && catalogue.q === terms ? catalogue.films : [];
  const mineOf = found.length ? libraryIndex() : null;
  const fresh = nameFirst(found.filter((film) => !mineOf(film)), (film) => film.title);

  // No title anywhere that matches the words? Then the providers are asked,
  // the way the + box asks them — after the catalogue has had its say, so
  // the lookup is the last resort and not a request on every keystroke. A
  // match through the cast does not count: "juno" finding Juno Temple's
  // films is not the same as finding Juno.
  const noTitle = searching && terms.length > 0
    && ![...filtered, ...elsewhere].some((item) => byName(item.title))
    && !fresh.some((film) => byName(film.title));
  if (noTitle && catalogue.q === terms) considerLookup(terms);
  lookup.eager = false;
  // "Looking" from the moment no name matched until the providers have
  // answered for these words — the catalogue's turn, the pause, and the
  // request itself all read the same from outside.
  const canLook = terms.length >= 2 && Boolean(state.config && state.config.network);
  const looked = noTitle && lookup.q === terms ? lookup : null;
  const looking = noTitle && canLook && !looked;

  // The strip counts the section you are looking at, not the whole library.
  const here = everything.filter((item) => sectionOf(item) === filters.section);
  renderStats(dom.stats, stats(here), filtered.length,
    { elsewhere: elsewhere.length, discover: fresh.length });
  paintTabs(everything);
  paintActiveFilters();

  // The queue keeps the order you gave it, so sorting and grouping are not
  // offered there; hiding watched titles means nothing outside the main list.
  dom.wrapSort.hidden = isQueue;
  dom.wrapGroup.hidden = isQueue;
  dom.hideWatched.hidden = filters.view !== 'list';

  paintStaging(searching);

  if (!filtered.length) {
    boxes.main.replaceChildren();
    paintYearMap(null);
    const view = VIEWS.find((v) => v.id === filters.view);
    const here = `${SECTION_LABEL[filters.section]} · ${view ? view.label : ''}`;
    if (looking || (looked && looked.rows.length)) {
      dom.empty.hidden = true;
      boxes.main.append(el('p.miss-note', {
        text: `No title in the library or the lists is called that — ${looking ? 'looking it up…' : 'looked it up:'}`,
      }));
    } else if (elsewhere.length || fresh.length) {
      // Not here, but somewhere: a line, and then the somewhere.
      dom.empty.hidden = true;
      boxes.main.append(el('p.miss-note', { text: `Nothing in ${here} for that — but:` }));
    } else {
      renderEmpty(dom.empty, {
        view: filters.view,
        section: filters.section,
        searching,
        // The providers were asked too and had nothing: say so, and offer
        // the box, which takes a link where a name found nothing.
        lookedUp: Boolean(looked),
        filtered: activeCount() > 0,
        elsewhere: searching ? null : matchesElsewhere(everything),
        onGo: (where) => { setPlace(where.section, where.view); },
        onClear: () => { resetFilters(); syncControls(); render(); },
        onAdd: () => addHere(searching ? filters.q : ''),
      });
    }
  } else {
    dom.empty.hidden = true;
    if (isQueue) {
      renderQueue(boxes.main, queueOrder(filtered), handlers, terms);
      paintYearMap(null);
    } else {
      const groups = groupItems(sortItems(filtered));
      renderGroups(boxes.main, groups, handlers, terms);
      paintYearMap(groups);
    }
  }

  paintExtras(elsewhere, fresh, { looking, looked, terms });

  const count = activeCount();
  dom.filterBadge.hidden = count === 0;
  dom.filterBadge.textContent = String(count);
  dom.qClear.hidden = !dom.q.value;
}

/* ----------------------------------------------------------------- staging */

/* Everything added since the strip was last cleared, pinned above the list
 * so the fill-in pass can be watched dressing it. Put away while searching:
 * the results are the point then. */
function paintStaging(searching) {
  renderStaging(boxes.staging, searching ? [] : staged(), handlers, {
    running: enrich.running,
    current: enrich.current,
    onClear: () => { unstage(); render(); },
  });
}

/* ---------------------------------------------------------- beyond the tab */

/* The catalogue's answer to the search box, kept beside the query it
 * answered so a stale answer is never drawn under a newer question. */
const catalogue = { q: '', films: [], asked: '', seq: 0 };

async function pullCatalogueHits({ force = false } = {}) {
  const q = plainTerms(filters.q);
  if (q === catalogue.asked && !force) return;      // answered, or on its way
  catalogue.asked = q;
  const mine = ++catalogue.seq;
  if (!q || !(discoverState().coverage || {}).films) {
    Object.assign(catalogue, { q, films: [] });
    return;
  }
  let films = [];
  try { ({ films } = await searchCatalogue(q, { limit: 12 })); } catch { films = []; }
  if (mine !== catalogue.seq) return;
  Object.assign(catalogue, { q, films });
  render();
}

function paintExtras(elsewhere, films, { looking = false, looked = null, terms = '' } = {}) {
  const parts = [];
  // What the providers found leads when it runs at all: it only runs when
  // nothing below was found by name.
  if (looking) {
    parts.push(stripSection('lookup', {
      label: 'Looking it up',
      note: 'asking the providers, the way the + box does — a name nothing is '
          + 'called can take twenty seconds to give up on',
    }, [el('div.center-note', null, [el('div.spinner'), 'Looking…'])]));
  } else if (looked && looked.rows.length) {
    // A title found this way may already be yours under another spelling
    // — the search missed it, the record's own name does not.
    const byKey = new Map();
    for (const item of live()) byKey.set(titleKey(item.title, item.year), item);
    const others = looked.rows.length - 1;
    const how = looked.via === 'search' ? 'a sure match' : viaLabel(looked.via);
    parts.push(stripSection('lookup', {
      label: 'Looked it up', count: looked.rows.length,
      note: looked.note || (looked.confident
        ? `${how}${others ? `, and ${others} more like it` : ''}`
        : 'not certain which — check before adding'),
      action: { label: 'Open in the add box', fn: () => addHere(terms) },
    }, looked.rows.map((row, at) => foundRow(row, {
      badge: at === 0 && looked.confident ? 'best match' : '',
      mine: byKey.get(titleKey(row.title, row.year)) || null,
      on: foundHandlers,
    }))));
  }
  if (elsewhere.length) {
    parts.push(stripSection('elsewhere', {
      label: 'Elsewhere in the library', count: elsewhere.length,
      note: 'other sections and lists',
    }, elsewhere.map((item) => card(item, handlers))));
  }
  if (films.length) {
    parts.push(stripSection('catalogue', {
      label: 'Discover', count: films.length, note: 'not in your library yet',
      action: { label: 'Open in Discover', fn: () => setPlace(DISCOVER.id, null) },
    }, catalogueRows(films, stripHandlers)));
  }
  boxes.more.replaceChildren(...parts);
  boxes.more.hidden = !parts.length;
}

/* ------------------------------------------------------------- looked up */

/* The providers' answer to a search that found nothing anywhere: the same
 * question the + box asks of /resolve, kept beside the words it answered. It
 * is asked once the catalogue has answered and typing has paused, and asked
 * at once on Enter. */
const lookup = { q: '', asked: '', pending: '', busy: false, rows: [], via: '', note: '',
                 confident: false, seq: 0, eager: false };
let lookupTimer = 0;

/** What kind of thing the tab on screen holds, for the providers. */
function sectionKind() {
  const section = SECTIONS.find((s) => s.id === filters.section);
  return section && section.id !== 'other' ? section.types[0] : 'any';
}

function considerLookup(terms) {
  if (!terms || terms.length < 2 || !state.config || !state.config.network) return;
  if (lookup.asked === terms) return;              // on its way, or answered
  if (lookup.pending === terms && !lookup.eager) return;   // already waiting to ask
  clearTimeout(lookupTimer);
  lookup.pending = terms;
  lookupTimer = setTimeout(() => pullLookup(terms), lookup.eager ? 0 : 450);
}

async function pullLookup(terms) {
  lookup.asked = terms;
  lookup.busy = true;
  const mine = ++lookup.seq;
  render();
  let answer = null;
  try {
    answer = await api('POST', '/resolve', { text: terms, type: sectionKind(), limit: 6 });
  } catch { answer = null; }
  if (mine !== lookup.seq) return;
  const rows = (answer && answer.candidates) || [];
  Object.assign(lookup, {
    q: terms, busy: false, rows,
    via: (answer && answer.via) || '',
    note: (answer && !rows.length && answer.note) || '',
    confident: Boolean(answer && answer.confident),
  });
  render();
}

/* Adding what was found: the same item the + box would make, to the strip
 * of what was just added and to the fill-in pass, and the search then finds
 * it — which is the whole point. */
function takeFound(row, status) {
  const made = rowToItem(row, { type: sectionKind(), status });
  const already = live().find((item) =>
    titleKey(item.title, item.year) === titleKey(made.title, made.year));
  if (already) {
    toast(`"${already.title}" is already in your library`, {
      action: { label: 'Open', fn: () => handlers.open(already) },
    });
    return;
  }
  const item = addItem(made);
  stage([item.id]);
  render();
  fillIn([item.id]);
  toast(`"${item.title}" added ${status === 'watched' ? 'as watched' : 'to the queue'}`, {
    action: { label: 'Open', fn: () => handlers.open(item) },
  });
}

const foundHandlers = {
  open: (item) => handlers.open(item),
  add: (row) => takeFound(row, 'queue'),
  watched: (row) => takeFound(row, 'watched'),
};

/* ---------------------------------------------------------------- discover

   Two panes share one page. The library's chrome — the three lists, the
   filters, the year rail — means nothing against a catalogue you do not own,
   so it is put away rather than left there doing nothing. */

function showLibraryChrome() {
  dom.toolbar.hidden = false;
  dom.discoTools.hidden = true;
  dom.btnFilters.hidden = false;
  document.body.classList.remove('discovering');
  // Discover paints straight into the list; the three boxes go back when
  // the library does, with the cards they were holding still in them.
  if (list.firstElementChild !== boxes.staging) {
    list.replaceChildren(boxes.staging, boxes.main, boxes.more);
  }
}

const discoHandlers = {
  reload: () => { pullDiscover(); },
  more: () => { pullDiscover({ more: true }); },
  fetch: () => openHarvest(() => { paintTabs(live()); pullDiscover(); }),
  // The refine sheet waits on this one: its counts are the answer's counts,
  // so it repaints when the list underneath has been repainted.
  change: () => pullDiscover(),
  genre: (genre) => { toggleGenre(genre); pullDiscover(); },
  // The rating badge on a row is the same kind of control as the genre
  // beside it: one tap for everything else rated the same, a second to stop.
  rating: (id) => { toggleRating(id); pullDiscover(); },
  // Clicking the same name twice stops following them, which is what the
  // pressed state on the row is promising.
  actor: (name) => { setActor(name); pullDiscover(); },
  topic: (id) => { setView({ filter: `topic:${id}` }); pullDiscover(); },
  open: (item) => openItem(item, { onChange: render, onDeleted: render }),
  // The row has already left the page by the time these are called; what is
  // left is to record it, keep the counts honest, and leave a way back.
  skip: (film, restore) => verdict(film, 'skip', restore, `"${film.title}" skipped`),
  unskip: (film, restore) => verdict(film, '', restore,
    `"${film.title}" is back in the list`),
  add: (film) => {
    const item = addFilm(film);
    render();
    toast(`"${item.title}" added to the queue`, {
      action: { label: 'Open', fn: () => discoHandlers.open(item) },
    });
  },
  // The same add, landing in the watched pile instead of the queue. The row
  // stays where it is and redraws as already yours, the way + does — nothing
  // here takes a row off the page except a skip.
  watched: (film) => {
    const item = addFilm(film, { status: 'watched' });
    render();
    toast(`"${item.title}" added as watched`, {
      action: { label: 'Open', fn: () => discoHandlers.open(item) },
    });
  },
};

/* The same rows drawn under a search on a library tab. Adding works the
 * same; everything that would narrow the Discover list — a genre, a name, a
 * rating — goes and does it there, since there is no Discover list here to
 * narrow. A skip takes the row out of the answer rather than repainting the
 * catalogue's toolbar, which is not on the page. */
const stripHandlers = {
  ...discoHandlers,
  genre: (genre) => { toggleGenre(genre); setPlace(DISCOVER.id, null); },
  rating: (id) => { toggleRating(id); setPlace(DISCOVER.id, null); },
  actor: (name) => { setActor(name); setPlace(DISCOVER.id, null); },
  topic: (id) => { setView({ filter: `topic:${id}` }); setPlace(DISCOVER.id, null); },
  skip: async (film, restore) => {
    try {
      await setVerdict(film, 'skip');
    } catch (err) {
      restore();
      toast(err.message || 'could not save that', { error: true });
      return;
    }
    catalogue.films = catalogue.films.filter((f) => f.key !== film.key);
    toast(`"${film.title}" skipped`, {
      action: {
        label: 'Undo',
        fn: async () => {
          try { await setVerdict(film, '', { shown: 1 }); } catch { return; }
          pullCatalogueHits({ force: true });
        },
      },
    });
  },
};

/* One verdict on one film. The row is gone already, so this is the counts,
 * the toast, and putting the row back where it was — either because the
 * server would not take it, or because the person changed their mind. */
async function verdict(film, value, restore, said) {
  try {
    await setVerdict(film, value);
  } catch (err) {
    restore();
    paintVerdict();
    toast(err.message || 'could not save that', { error: true });
    return;
  }
  paintVerdict();
  toast(said, { action: { label: 'Undo', fn: () => undoVerdict(film, value, restore) } });
}

async function undoVerdict(film, value, restore) {
  try {
    await setVerdict(film, value === 'skip' ? '' : 'skip', { shown: 1 });
  } catch (err) {
    toast(err.message || 'could not undo that', { error: true });
    return;
  }
  restore();
  paintVerdict();
}

/* The two things a verdict changes that are not the row itself. */
function paintVerdict() {
  discoverStats(dom.stats);
  buildTools(dom.discoTools, discoHandlers);
}

/** Ask the server again, then repaint. The search box is the query. */
async function pullDiscover({ more = false } = {}) {
  if (!more) dom.list.replaceChildren(
    el('div.center-note', null, [el('div.spinner'), 'Reading the lists…']));
  if (await refreshDiscover(filters.q, { more })) paintDiscover();
}

function paintDiscover() {
  dom.toolbar.hidden = true;
  dom.discoTools.hidden = false;
  dom.btnFilters.hidden = true;
  dom.empty.hidden = true;
  dom.activeFilters.hidden = true;
  dom.filterBadge.hidden = true;
  dom.qClear.hidden = !dom.q.value;
  document.body.classList.add('discovering');
  paintYearMap(null);

  buildTools(dom.discoTools, discoHandlers);
  discoverStats(dom.stats);
  renderDiscover(dom.list, discoHandlers);
}

/* When a search comes up empty here but not everywhere, say where it is. */
function matchesElsewhere(everything) {
  const here = { section: filters.section, view: filters.view };
  for (const section of SECTIONS) {
    for (const view of VIEWS) {
      if (section.id === here.section && view.id === here.view) continue;
      filters.section = section.id;
      filters.view = view.id;
      const hit = apply(everything).length;
      filters.section = here.section;
      filters.view = here.view;
      if (hit) {
        return {
          section: section.id,
          view: view.id,
          count: hit,
          label: `${SECTION_LABEL[section.id]} · ${view.label}`,
        };
      }
    }
  }
  return null;
}

function paintActiveFilters() {
  const chips = [];
  const drop = (label, undoFn) => {
    const pill = el('span.pill', null, [label]);
    pill.append(el('button', {
      type: 'button', 'aria-label': `Remove ${label}`,
      style: { border: '0', background: 'none', color: 'inherit', padding: '0' },
      onclick: () => { undoFn(); saveView(); syncControls(); render(); },
    }, icon('x')));
    chips.push(pill);
  };

  for (const tag of filters.tags) {
    drop(`#${tag}`, () => { filters.tags = filters.tags.filter((t) => t !== tag); });
  }
  for (const type of filters.types) {
    drop(TYPE_LABEL[type] || type, () => { filters.types = filters.types.filter((t) => t !== type); });
  }
  for (const status of filters.statuses) {
    drop(STATUS_LABEL[status] || status, () => { filters.statuses = filters.statuses.filter((s) => s !== status); });
  }
  if (filters.minRating) drop(`${filters.minRating}+`, () => { filters.minRating = 0; });
  if (filters.yearFrom || filters.yearTo) {
    drop(`${filters.yearFrom || '…'}–${filters.yearTo || '…'}`,
      () => { filters.yearFrom = null; filters.yearTo = null; });
  }
  if (filters.hasLinks) drop('has a link', () => { filters.hasLinks = false; });
  if (filters.noLinks) drop('missing a link', () => { filters.noLinks = false; });

  dom.activeFilters.replaceChildren(...chips);
  dom.activeFilters.hidden = chips.length === 0;
}

/* ------------------------------------------------------------- enrichment */

/* The documents that seeded this library were titles and links. This is the
 * server going out to fetch everything they never carried. It runs in the
 * background, a title at a time, and survives the tab being closed. */

function openEnrich() {
  const body = el('div');
  const line = el('div.sync-line');
  const bar = el('div.progress', null, el('i'));
  const detail = el('p.hint');
  const providers = el('div.kv');

  let scope = 'missing';
  let timer = 0;
  let last = null;

  const start = el('button.btn.primary.grow', { type: 'button', text: 'Start' });
  const stop = el('button.btn.ghost', { type: 'button', text: 'Stop' });

  const paintStatus = (status) => {
    last = status;
    const pct = status.total ? Math.round((status.done / status.total) * 100) : 0;
    bar.firstChild.style.setProperty('--w', `${pct}%`);
    bar.hidden = !status.total;

    line.replaceChildren(
      el('span.sync-dot', { class: status.running ? 'busy' : '' }),
      el('span', {
        text: status.running
          ? `${status.done} of ${status.total} — ${status.current || 'starting…'}`
          : status.finishedAt
            ? `Finished: ${status.note}`
            : status.note || 'Not running',
      }),
    );

    detail.textContent = status.running
      ? `About ${Math.ceil(status.etaSeconds / 60)} min left. `
        + `${status.filled} ${status.replacing ? 'updated' : 'filled in'} so far. `
        + 'You can close this — it keeps going.'
      : 'A provider that finds nothing never blanks what is already there.';

    start.disabled = status.running || !status.network;
    stop.disabled = !status.running;
    if (status.running) start.textContent = 'Running…';
    else start.textContent = ['upgrade', 'refresh'].includes(scope) ? 'Replace' : 'Start';
  };

  const poll = async () => {
    try {
      const status = await api('GET', '/enrich');
      paintStatus(status);
      // Pull the newly filled-in titles down so they appear as they land.
      if (status.running || (last && last.running)) await refresh({ force: true });
      render();
    } catch { /* the sheet stays open; the next tick tries again */ }
    timer = setTimeout(poll, 3000);
  };

  /* Artwork that did not come from the best source available. Whichever
     provider filled it in first is recorded in the poster's own URL. */
  const rows = live();
  const notBest = (item) => item.poster && !item.poster.includes('image.tmdb.org');
  const counts = {
    missing: rows.filter((i) => !i.poster || !i.year || !(i.cast || []).length).length,
    artwork: rows.filter((i) => !i.poster).length,
    year: rows.filter((i) => !i.year).length,
    genres: rows.filter((i) => !(i.genres || []).length).length,
    wiki: rows.filter((i) => !i.wikiUrl).length,
    upgrade: rows.filter(notBest).length,
    refresh: rows.length,
  };

  const choices = el('div');
  const note = el('p.hint');

  /* The last two replace rather than fill, so they are worth spelling out. */
  const EXPLAIN = {
    missing: 'Fills any blank it can — artwork, cast, ages, years, IMDb ids.',
    artwork: 'Only titles with no artwork at all.',
    year: 'Only titles with no year. Years you typed yourself are never touched.',
    genres: 'Only titles with no genre yet. Keeps asking each provider in turn until '
          + 'one of them names a genre, rather than stopping at the first that '
          + 'answered everything else.',
    wiki: 'Only titles with no Wikipedia link. Looks the article up by IMDb id rather '
        + 'than by name, which is what finally finds the ones called "Giant (1956 film)" '
        + 'on Wikipedia and just "Giant" here.',
    upgrade: 'Replaces artwork that came from somewhere weaker with the best available. '
           + 'Nothing else about the title changes.',
    refresh: 'Re-fetches every title and replaces artwork, cast, ages, runtimes, genres '
           + 'and overviews. Your years, ratings, hearts, tags, notes and links are left alone.',
  };

  const scopeOptions = () => {
    const list = [
      { id: 'missing', label: `Missing (${counts.missing})` },
      { id: 'artwork', label: `No artwork (${counts.artwork})` },
      { id: 'year', label: `No year (${counts.year})` },
      { id: 'genres', label: `No genre (${counts.genres})` },
      { id: 'wiki', label: `No Wikipedia link (${counts.wiki})` },
    ];
    if (counts.upgrade) list.push({ id: 'upgrade', label: `Better artwork (${counts.upgrade})` });
    list.push({ id: 'refresh', label: `Re-fetch all (${counts.refresh})` });
    return list;
  };

  const pickScope = (value) => {
    scope = value;
    note.textContent = EXPLAIN[value] || '';
    // A pass already running owns the button; do not relabel it underneath.
    if (last && last.running) return;
    start.textContent = ['upgrade', 'refresh'].includes(value) ? 'Replace' : 'Start';
  };

  choices.append(segmented(scopeOptions(), scope, pickScope));
  body.append(field('What to go and find', el('div', null, [choices, note])));
  pickScope(scope);

  body.append(field('Progress', el('div', null, [line, bar, detail])));

  start.addEventListener('click', async () => {
    start.disabled = true;
    try { paintStatus(await api('POST', '/enrich', { action: 'start', scope })); }
    catch (err) { toast(err.message || 'could not start', { error: true }); start.disabled = false; }
  });
  stop.addEventListener('click', async () => {
    try { paintStatus(await api('POST', '/enrich', { action: 'stop' })); }
    catch { /* it will stop on its own soon enough */ }
  });

  body.append(field('Where it looks', providers));
  body.append(el('p.hint', {
    text: 'IMDb has no public API — theirs is an AWS Data Exchange product, and the '
        + 'Parents Guide is a paid add-on to it. What comes back instead is the age '
        + 'certification, the cast, and an IMDb link on each title so its own '
        + 'parents guide is one tap away.',
  }));

  const handle = openSheet({
    title: 'Fill in the details',
    body,
    footer: [stop, start],
    onClose: () => clearTimeout(timer),
  });

  api('GET', '/enrich').then((status) => {
    paintStatus(status);
    const on = Object.entries(status.providers).filter(([, yes]) => yes).map(([name]) => name);
    providers.replaceChildren(
      el('span', null, [el('b', { text: 'Using ' }), on.join(', ')]),
      el('span', null, [el('b', { text: 'TMDB key ' }),
        status.providers.tmdb ? 'set — full artwork and cast'
          : 'not set — old films and TV are covered, modern film posters are not']),
    );
    if (!status.providers.tmdb) {
      providers.append(el('span.hint', {
        text: 'A free key from themoviedb.org/settings/api, then restart with '
            + 'TMDB_API_KEY=… ./dockerRun.sh',
      }));
    }
    poll();
  }).catch(() => { detail.textContent = 'The server did not answer.'; });
}

/* --------------------------------------------------------------- year map */

function paintYearMap(groups) {
  const wanted = groups && filters.map && filters.group !== 'none';
  if (!wanted) {
    dom.yearmap.hidden = true;
    dom.yearmap.replaceChildren();
    document.body.classList.remove('has-map');
    return;
  }
  const observe = renderYearMap(dom.yearmap, groups, { onJump: jumpToGroup });
  document.body.classList.toggle('has-map', !dom.yearmap.hidden);
  if (observe) observe(dom.list);
}

function headerHeight() {
  return parseInt(getComputedStyle(document.documentElement)
    .getPropertyValue('--top-h'), 10) || 104;
}

function jumpToGroup(key, { smooth = true } = {}) {
  const section = dom.list.querySelector(`.group[data-key="${CSS.escape(String(key))}"]`);
  if (!section) return;
  const top = section.getBoundingClientRect().top + window.scrollY - headerHeight() - 6;
  window.scrollTo({ top: Math.max(0, top), behavior: smooth ? 'smooth' : 'auto' });
}

wireYearMap(dom.yearmap, dom.bubble, { onJump: jumpToGroup });

/* ------------------------------------------------------------------ tabs */

/* Two rows of navigation: which part of the library (Movies, TV, Other) and
 * which of its three lists. Both remember where you were. */

/** New titles start as whatever the section you are looking at holds. A
 * line handed in — the search that found nothing — is already in the box. */
function addHere(text = '') {
  const section = SECTIONS.find((s) => s.id === filters.section) || SECTIONS[0];
  return openAdd(render, { defaultType: section.types[0], text });
}

function setPlace(section, view) {
  const arriving = section && section !== filters.section;
  if (section) filters.section = section;
  if (view) filters.view = view;
  saveView();
  window.scrollTo({ top: 0 });
  syncControls();
  if (arriving && inDiscover()) { pullDiscover(); return; }
  render();
}

/* A fourth tab beside Movies, TV and Other. Not a part of the library — it
 * is the pile of films the library was picked out of — so it has no lists,
 * no filters and no year rail, and paints itself. */
const DISCOVER = { id: 'discover', label: 'Discover' };

const inDiscover = () => filters.section === DISCOVER.id;

function buildTabs() {
  for (const section of [...SECTIONS, DISCOVER]) {
    dom.sections.append(el('button', {
      type: 'button', role: 'tab', dataset: { section: section.id },
      onclick: () => setPlace(section.id, null),
    }, [el('span.tab-label', { text: section.label }), el('span.tab-count')]));
  }
  for (const view of VIEWS) {
    dom.viewtabs.append(el('button', {
      type: 'button', role: 'tab', dataset: { view: view.id },
      onclick: () => setPlace(null, view.id),
    }, [el('span.tab-label', { text: view.label }), el('span.tab-count')]));
  }
}

/** Counts are of the library itself, not of what the filters leave behind. */
function paintTabs(everything) {
  const tally = new Map();
  for (const item of everything) {
    const section = sectionOf(item);
    tally.set(section, (tally.get(section) || 0) + 1);
    for (const view of VIEWS) {
      if (view.id !== 'list' && inView(item, view.id)) {
        tally.set(`${section}:${view.id}`, (tally.get(`${section}:${view.id}`) || 0) + 1);
      }
    }
  }

  for (const button of dom.sections.children) {
    const id = button.dataset.section;
    const on = id === filters.section;
    button.setAttribute('aria-pressed', String(on));
    button.setAttribute('aria-selected', String(on));
    button.querySelector('.tab-count').textContent = id === DISCOVER.id
      ? String((discoverState().coverage || {}).films || 0)
      : String(tally.get(id) || 0);
  }
  if (inDiscover()) return;
  for (const button of dom.viewtabs.children) {
    const id = button.dataset.view;
    const on = id === filters.view;
    button.setAttribute('aria-selected', String(on));
    const count = id === 'list' ? (tally.get(filters.section) || 0)
      : (tally.get(`${filters.section}:${id}`) || 0);
    button.querySelector('.tab-count').textContent = String(count);
  }
}

/* ----------------------------------------------------------------- theme */

const THEME_KEY = 'mt.theme.v1';

function readTheme() {
  try { return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'; }
  catch { return 'light'; }
}

/** Light unless you have asked for dark — never whatever the phone feels like. */
function applyTheme(mode) {
  document.documentElement.setAttribute('data-theme', mode);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', mode === 'dark' ? '#0a0e14' : '#f6f7fb');
  try { localStorage.setItem(THEME_KEY, mode); } catch { /* private mode */ }
}

/** Push filter state back into the toolbar controls. */
function syncControls() {
  dom.hideWatched.setAttribute('aria-pressed', String(filters.hideWatched));
  dom.hearts.setAttribute('aria-pressed', String(filters.heartsOnly));
  dom.unrated.setAttribute('aria-pressed', String(filters.unratedOnly));
  dom.sort.value = filters.sort;
  dom.group.value = filters.group;
}

/* ---------------------------------------------------------------- toolbar */

function toggle(button, key) {
  button.addEventListener('click', () => {
    filters[key] = !filters[key];
    button.setAttribute('aria-pressed', String(filters[key]));
    saveView();
    render();
  });
}

toggle(dom.hideWatched, 'hideWatched');
toggle(dom.hearts, 'heartsOnly');
toggle(dom.unrated, 'unratedOnly');

dom.sort.addEventListener('change', () => { filters.sort = dom.sort.value; saveView(); render(); });
dom.group.addEventListener('change', () => { filters.group = dom.group.value; saveView(); render(); });

/* One box, whichever pane is up: the library filters itself in the browser,
 * the catalogue is asked of the server. Discover waits a beat longer, since
 * every keystroke there is a request rather than a substring test. */
let searchTimer = 0;
let catalogueTimer = 0;
const searched = () => {
  if (inDiscover()) { pullDiscover(); return; }
  clearTimeout(lookupTimer);
  lookup.pending = '';
  render();
  // The catalogue is a request rather than a substring test, so it waits a
  // beat longer than the library does and lands when it lands.
  clearTimeout(catalogueTimer);
  catalogueTimer = setTimeout(pullCatalogueHits, 200);
};

dom.q.addEventListener('input', () => {
  clearTimeout(searchTimer);
  dom.qClear.hidden = !dom.q.value;
  searchTimer = setTimeout(() => { filters.q = dom.q.value; searched(); },
    inDiscover() ? 320 : 160);
});
// Enter: whatever is still to be asked is asked now rather than after the pause.
dom.q.addEventListener('search', () => { filters.q = dom.q.value; lookup.eager = true; searched(); });
dom.qClear.addEventListener('click', () => {
  dom.q.value = '';
  filters.q = '';
  dom.q.focus();
  searched();
});

dom.btnFilters.addEventListener('click', () => openFilterSheet(() => { syncControls(); render(); }));
dom.btnAdd.addEventListener('click', () => addHere());
dom.btnMenu.addEventListener('click', openMenu);

/* ------------------------------------------------------------------- menu */

function openMenu() {
  const s = stats();
  const body = el('div.menu-list');

  const entry = (iconName, label, hint, fn) => el('button.menu-item', {
    type: 'button', onclick: fn,
  }, [icon(iconName), el('span', null, [label, hint ? el('small', { text: hint }) : null])]);

  body.append(
    entry('upload', 'Import & export', 'Paste a list, or take a backup out',
      () => { handle.close(); openPortingSheet(render); }),
    entry('shuffle', 'Surprise me', 'Pick something from the queue at random', pickRandom),
    entry('star', 'Statistics', `${s.total} tracked · ${s.watched} watched`,
      () => { handle.close(); openStats(); }),
    entry('link', 'Source links', `${state.sources.length} saved`,
      () => { handle.close(); openSources(); }),
    entry('refresh', 'Sync & storage', state.online ? 'Connected' : 'Offline — changes are queued',
      () => { handle.close(); openSync(); }),
    entry('note', 'Search tips', 'tag:, genre:, cert:, year:, -exclude',
      () => { handle.close(); openHelp(); }),
    entry('sparkle', 'Fill in the details', 'Artwork, cast, genres, ages and IMDb ids',
      () => { handle.close(); openEnrich(); }),
    entry('download', 'Collect the lists',
      `${(discoverState().coverage || {}).films || 0} films from Wikipedia's year lists`,
      () => {
        handle.close();
        openHarvest(() => { paintTabs(live()); if (inDiscover()) pullDiscover(); });
      }),
    entry('map', filters.map ? 'Hide the year rail' : 'Show the year rail',
      filters.map ? 'The list of years down the right' : 'Jump straight to a year',
      () => {
        filters.map = !filters.map;
        saveView();
        handle.close();
        render();
        toast(filters.map ? 'Year rail on' : 'Year rail off');
      }),
    entry(readTheme() === 'dark' ? 'sun' : 'moon',
      readTheme() === 'dark' ? 'Light theme' : 'Dark theme',
      readTheme() === 'dark' ? 'Back to the light one' : 'For reading in bed',
      () => { applyTheme(readTheme() === 'dark' ? 'light' : 'dark'); handle.close(); }),
  );

  const handle = openSheet({ title: 'Media Tracker', body });
}

function pickRandom() {
  const pool = live().filter((item) =>
    sectionOf(item) === filters.section && inView(item, 'queue'));
  if (!pool.length) { toast(`Nothing in the ${SECTION_LABEL[filters.section]} queue`, { error: true }); return; }
  const pick = pool[Math.floor(Math.random() * pool.length)];
  closeAll();
  openItem(pick, { onChange: render, onDeleted: render });
  toast(`How about "${pick.title}"?`);
}

function bar(label, value, total) {
  const fill = el('i');
  fill.style.setProperty('--w', `${total ? Math.round((value / total) * 100) : 0}%`);
  return el('div.statrow', null, [
    el('span', { text: label, style: { 'min-width': '92px' } }),
    el('span.meter', null, fill),
    el('b', { text: String(value) }),
  ]);
}

function openStats() {
  const rows = live();
  const s = stats();
  const body = el('div');

  body.append(field('Overall', el('div', null, [
    bar('Queue', s.queue, s.total),
    bar('Watching', s.watching, s.total),
    bar('Watched', s.watched, s.total),
    bar('Skipped', s.dropped, s.total),
    bar('Loved', s.hearts, s.total),
  ])));

  const byType = new Map();
  for (const item of rows) byType.set(item.type, (byType.get(item.type) || 0) + 1);
  body.append(field('By type', el('div', null,
    [...byType.entries()].sort((a, b) => b[1] - a[1])
      .map(([type, n]) => bar(TYPE_LABEL[type] || type, n, s.total)))));

  const byDecade = new Map();
  for (const item of rows) {
    if (!item.year) continue;
    const decade = `${Math.floor(item.year / 10) * 10}s`;
    byDecade.set(decade, (byDecade.get(decade) || 0) + 1);
  }
  const decades = [...byDecade.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  if (decades.length) {
    const peak = Math.max(...decades.map(([, n]) => n));
    body.append(field('By decade', el('div', null, decades.map(([d, n]) => bar(d, n, peak)))));
  }

  const ratings = new Array(11).fill(0);
  for (const item of rows) if (item.rating) ratings[item.rating] += 1;
  if (s.rated) {
    const peak = Math.max(...ratings);
    body.append(field(`Ratings (${s.avg.toFixed(1)} average over ${s.rated})`,
      el('div', null, ratings.map((n, i) => (i ? bar(`${i} / 10`, n, peak) : null)).filter(Boolean))));
  }

  const tags = allTags().slice(0, 12);
  if (tags.length) {
    const peak = tags[0][1];
    body.append(field('Top tags', el('div', null, tags.map(([tag, n]) => bar(`#${tag}`, n, peak)))));
  }

  const watchedWithDate = rows.filter((i) => i.watchedAt).sort((a, b) => b.watchedAt.localeCompare(a.watchedAt));
  if (watchedWithDate.length) {
    body.append(el('p.hint', {
      text: `Last watched: ${watchedWithDate[0].title} (${fmtDate(watchedWithDate[0].watchedAt)}).`,
    }));
  }

  openSheet({ title: 'Statistics', body });
}

function openSources() {
  const body = el('div');
  const listBox = el('div');

  const input = el('input.input', { type: 'url', placeholder: 'https://... a list you browse for ideas' });
  const add = el('button.btn.sm.primary', { type: 'button', text: 'Save' });
  add.addEventListener('click', () => {
    if (addSource(input.value.trim())) { input.value = ''; draw(); toast('Source saved'); }
    else toast('That needs to be a full https:// link', { error: true });
  });

  function draw() {
    listBox.replaceChildren();
    if (!state.sources.length) {
      listBox.append(el('p.hint', {
        text: 'Nothing here yet. Bare links found while importing land here, '
            + 'so the pages you browse for ideas stay with the library.',
      }));
      return;
    }
    for (const source of [...state.sources].reverse()) {
      const open = el('a.link-chip', {
        href: source.url, target: '_blank', rel: 'noopener noreferrer',
        text: source.title || hostOf(source.url),
      });
      const drop = el('button.icon-btn', {
        type: 'button', 'aria-label': 'Remove',
        onclick: () => { removeSource(source.id); draw(); },
      }, icon('trash'));
      listBox.append(el('div.link-row', null, [
        el('div', { style: { flex: '1', 'min-width': '0' } }, [
          open,
          el('div.card-meta', null, [el('span', { text: hostOf(source.url) })]),
        ]),
        drop,
      ]));
    }
  }
  draw();

  body.append(field('Add a source', el('div.row', null, [input, add])), listBox);
  openSheet({ title: 'Source links', body });
}

function openSync() {
  const body = el('div');
  const line = el('div.sync-line');

  const paintLine = () => {
    const dot = el('span.sync-dot', {
      class: state.saving ? 'busy' : (state.online ? '' : 'off'),
    });
    line.replaceChildren(dot, el('span', {
      text: state.saving ? 'Saving…'
        : state.online
          ? `Saved${state.lastSaved ? ` ${fmtAgo(state.lastSaved.toISOString())}` : ''} · revision ${state.rev}`
          : `Offline — ${state.dirty ? 'changes are queued' : 'no pending changes'}`,
    }));
  };
  paintLine();

  const pull = el('button.btn.sm.ghost', { type: 'button' }, [icon('download'), 'Pull from server']);
  pull.addEventListener('click', async () => { await refresh({ force: true }); paintLine(); render(); toast('Refreshed'); });

  const push = el('button.btn.sm.ghost', { type: 'button' }, [icon('upload'), 'Push now']);
  push.addEventListener('click', async () => { await sync(); paintLine(); toast(state.online ? 'Pushed' : 'Still offline', { error: !state.online }); });

  body.append(field('Status', line));
  body.append(field('Manual sync', el('div.chip-row', null, [pull, push])));

  const config = state.config || {};
  const providers = config.providers || {};
  body.append(field('This server', el('div.kv', null, [
    el('span', null, [el('b', { text: 'Version ' }), config.version || '—']),
    el('span', null, [el('b', { text: 'Library ' }), config.dataPath || 'data/library.json']),
    el('span', null, [el('b', { text: 'Lookups ' }), config.network ? 'enabled' : 'offline mode']),
    el('span', null, [el('b', { text: 'Providers ' }),
      Object.entries(providers).filter(([, on]) => on).map(([name]) => name).join(', ') || 'none']),
  ])));

  const undoBtn = el('button.btn.sm.ghost', { type: 'button', text: 'Undo last bulk change' });
  undoBtn.addEventListener('click', () => {
    const label = undo();
    render();
    toast(label ? `Undid: ${label}` : 'Nothing to undo', { error: !label });
  });

  const wipe = el('button.btn.sm.danger', { type: 'button', text: 'Delete everything' });
  wipe.addEventListener('click', async () => {
    const ok = await confirmSheet({
      title: 'Delete the whole library?',
      message: `All ${live().length} titles will be removed. Export a backup first if you are unsure.`,
      confirmLabel: 'Delete everything', danger: true,
    });
    if (!ok) return;
    checkpoint('delete everything');
    for (const item of live()) { item.deleted = true; item.deletedAt = new Date().toISOString(); }
    notify();
    render();
    toast('Library cleared', { action: { label: 'Undo', fn: () => { undo(); render(); } } });
  });

  body.append(field('Danger zone', el('div.chip-row', null, [undoBtn, wipe])));
  body.append(el('p.hint', {
    text: 'Every change is written to data/library.json on the server and mirrored in this '
        + 'browser, so the app keeps working if the network drops.',
  }));

  openSheet({ title: 'Sync & storage', body });
}

function openHelp() {
  const body = el('div');
  const row = (code, meaning) => el('div.statrow', null, [
    el('code', { text: code, style: { 'min-width': '110px' } }),
    el('span', { text: meaning, style: { color: 'var(--text-2)', 'font-size': '13px' } }),
  ]);

  body.append(field('Search', el('div', null, [
    row('lady eve', 'plain words, all must match'),
    row('"the women"', 'exact phrase'),
    row('-remake', 'exclude'),
    row('#noir', 'tagged noir'),
    row('tag:staged', 'same thing, spelled out'),
    row('"genre:romantic comedy"', 'by genre — quote it if it has a space'),
    row('cert:pg-13', 'by age rating — cert:none for the unrated'),
    row('year:1949', 'released that year'),
    row('type:tv', 'movies, tv, anime, doc, book, game, podcast'),
    row('status:watched', 'queue, watching, watched, dropped'),
    row('rating:9', 'rated exactly 9'),
    row('is:loved', 'hearted'),
    row('is:unrated', 'no number yet'),
    row('link:apple', 'link contains "apple"'),
  ]), 'Watched titles stay visible while you search, even with "Hide watched" on.'));

  body.append(field('On a keyboard', el('div', null, [
    row('/', 'jump to search'),
    row('n', 'add something'),
    row('f', 'filters'),
    row('w', 'toggle hide watched'),
    row('Esc', 'close the sheet'),
  ])));

  openSheet({ title: 'Search tips', body });
}

/* The year headings stick just below the toolbar, whose height depends on
 * font size and the notch — so measure it instead of guessing. */
function trackHeaderHeight() {
  const topbar = document.getElementById('topbar');
  const set = () => document.documentElement.style.setProperty(
    '--top-h', `${Math.round(topbar.getBoundingClientRect().height)}px`);
  set();
  if ('ResizeObserver' in window) new ResizeObserver(set).observe(topbar);
  else addEventListener('resize', set);
}
trackHeaderHeight();

/* -------------------------------------------------------------- shortcuts */

addEventListener('keydown', (event) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
  if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === '/') { event.preventDefault(); dom.q.focus(); dom.q.select(); }
  else if (event.key === 'n') { event.preventDefault(); addHere(); }
  else if (event.key >= '1' && event.key <= '4') {
    event.preventDefault();
    setPlace([...SECTIONS, DISCOVER][Number(event.key) - 1].id, null);
  }
  // The rest are the library's: its filters, its three lists, its watched
  // toggle. None of them mean anything against a catalogue.
  else if (inDiscover()) { /* nothing further */ }
  else if (event.key === 'f') { event.preventDefault(); openFilterSheet(() => { syncControls(); render(); }); }
  else if (event.key === 'w') { event.preventDefault(); dom.hideWatched.click(); }
  else if (event.key === 'q' || event.key === 'l' || event.key === 'v') {
    event.preventDefault();
    setPlace(null, event.key === 'q' ? 'queue' : event.key === 'l' ? 'list' : 'watched');
  }
});

/* ------------------------------------------------------------------- boot */

onChange(render);
applyTheme(readTheme());
loadView();
loadDiscover();
buildTabs();
syncControls();
dom.q.value = '';

dom.list.replaceChildren(el('div.center-note', null, [el('div.spinner'), 'Loading your library…']));

boot().then(async () => {
  render();
  if (!state.online) {
    toast("Server unreachable - using the copy saved on this device", { error: true, ms: 6000 });
  }
  // A strip left from last time may still be being filled in on the server;
  // one look at the pass says whether to keep watching it.
  if (staging.length && state.online) watchEnrich();
  // What has been collected, for the tab's count and the harvest sheet. One
  // small call; the catalogue itself is only read when you go and look at it.
  await ensureCatalogue();
  // The counts on the section tabs, including Discover's — which is only
  // known once the catalogue has answered, so it is painted after it has.
  paintTabs(live());
  if (inDiscover()) pullDiscover();
});
