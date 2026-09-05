/* The universal box.
 *
 * One input that takes whatever you have. A title. A title and a year. A
 * bare IMDb id. A link to IMDb, TMDB, Wikipedia, Letterboxd, Rotten
 * Tomatoes, Trakt, TVmaze, MyAnimeList. A list of any of those, one per
 * line. A CSV or a JSON backup.
 *
 * Everything on this side is presentation and pacing; the server decides
 * what a line refers to, because that is where the providers, the rate
 * limits and the matcher live. See server/resolve.py.
 */

import {
  api, addMany, newItem, live, titleKey, state, sync, refresh,
  TYPES, STATUSES, TYPE_LABEL,
} from './store.js';
import { el, field, openSheet, segmented, toast } from './ui.js';
import { parseAny, isPlaceholder } from './porting.js';

/* How many lines are resolved one by one, with artwork shown as it arrives.
 * Past this a paste is a bulk import: the titles go in immediately and the
 * background pass fills them in, because resolving nine hundred of them up
 * front would take an hour of provider calls before anything appeared. */
const RESOLVE_LIMIT = 30;

/* Requests in flight at once. The server paces each provider itself; this
 * only stops one paste from queueing forty of them at the same instant. */
const LANES = 4;

const looksLikeLink = (text) => /^(?:https?:\/\/|www\.)|^tt\d{6,10}$/i.test(text.trim());

/* Pull down what the fill-in pass writes, until it stops.
 *
 * The pass runs on the server and writes there; this page polls on a slow
 * timer of its own, so without this the artwork it finds would appear a
 * minute later, or on the next visit. One watcher at a time. */
let watcher = 0;

function watchFillIn(onDone) {
  if (watcher) return;
  watcher = setInterval(async () => {
    let running = false;
    try {
      running = (await api('GET', '/enrich')).running;
      await refresh({ force: true });
    } catch { /* offline for a moment; the next tick tries again */ }
    onDone();
    if (!running) { clearInterval(watcher); watcher = 0; }
  }, 2500);
}

/* ------------------------------------------------------------- one entry */

/** A line of input, and what the server made of it. */
function entry(raw) {
  return {
    raw,
    title: raw,
    year: null,
    state: 'waiting',      // waiting | looking | found | unsure | missing
    row: null,             // the metadata to add, once there is any
    candidates: [],
    via: '',
    note: '',
    take: true,            // whether this one is going in
  };
}

async function lookUp(item, kind) {
  item.state = 'looking';
  try {
    const found = await api('POST', '/resolve', { text: item.raw, type: kind, limit: 6 });
    item.via = found.via || '';
    item.note = found.note || '';
    item.candidates = found.candidates || [];
    item.title = found.query || item.raw;
    item.year = found.year || null;
    if (found.best && found.confident) {
      item.row = found.best;
      item.state = 'found';
    } else if (item.candidates.length) {
      item.state = 'unsure';
    } else {
      item.state = 'missing';
    }
  } catch (err) {
    item.state = 'missing';
    item.note = err.message;
  }
  return item;
}

/** Run `work` over `list`, a few at a time, calling `onStep` after each. */
async function pool(list, lanes, work, onStep) {
  let next = 0;
  const lane = async () => {
    while (next < list.length) {
      const mine = list[next];
      next += 1;
      await work(mine);
      onStep(mine);
    }
  };
  await Promise.all(Array.from({ length: Math.min(lanes, list.length) }, lane));
}

/* ------------------------------------------------------------ the item it makes */

/** What goes into the library for one entry. */
function toItem(item, opts) {
  // The guess goes in as shown. It was on the screen, with its artwork, next
  // to a tick that could have been cleared — which is the whole difference
  // between this and the background pass, where nothing uncertain is written.
  const row = item.row || (item.state === 'unsure' ? item.candidates[0] : null) || {};
  const base = {
    title: row.title || item.title || item.raw,
    year: row.year || item.year || null,
    // A link says what it is: a series stays a series even on the film list.
    type: row.type || opts.type,
    status: opts.status,
    poster: row.poster || '',
    overview: row.overview || '',
    genres: row.genres || [],
    runtime: row.runtime || null,
    creator: row.creator || '',
    cast: row.cast || [],
    certification: row.certification || '',
    source: row.source || '',
    sourceId: row.sourceId || '',
    imdbId: row.imdbId || '',
    wikiUrl: row.wikiUrl || '',
    extRating: row.extRating || null,
    links: [],
  };
  if (base.status === 'watched') base.watchedAt = new Date().toISOString();
  for (const url of [row.link, item.via.endsWith('-id') || item.via === 'page' ? item.raw : null]) {
    if (url && /^https?:/i.test(url) && !base.links.some((l) => l.url === url)) {
      base.links.push({ label: '', url });
    }
  }
  return base;
}

/* ================================ the panel ============================= */

export function universalPanel(onDone, { defaultType = 'movie' } = {}) {
  const wrap = el('div');
  const opts = { type: defaultType === 'any' ? 'movie' : defaultType, status: 'queue' };

  const area = el('textarea.input', {
    rows: 4,
    spellcheck: false,
    'data-autofocus': '',
    placeholder: 'A title, a link, or a whole list — one per line.\n'
      + 'The weather girl - 2009\n'
      + 'https://www.imdb.com/title/tt1085515/',
  });
  area.style.setProperty('min-height', '92px');

  const status = el('p.hint', { text: 'Paste anything.' });
  const list = el('div');
  const footer = el('div.field');

  let entries = [];
  let bulk = null;          // a paste too big to resolve line by line
  let seq = 0;
  let busy = false;

  /* ---------------------------------------------------------- rendering */

  const badge = (item) => {
    if (item.state === 'looking') return el('span.spinner');
    if (item.state === 'found') return el('span.tag-badge', { text: viaLabel(item.via) });
    if (item.state === 'unsure') {
      const others = item.candidates.length - 1;
      return el('span.tag-badge.guess', {
        text: others > 0 ? `best guess · ${others} other${others > 1 ? 's' : ''}` : 'best guess',
      });
    }
    if (item.state === 'missing') return el('span.tag-badge', { text: 'not found' });
    return null;
  };

  function drawRow(item) {
    // A match the server is not sure of is still shown — with its artwork,
    // labelled as a guess. You are looking at this: a wrong poster in front
    // of you is one tap from being fixed, where the same guess written
    // silently by the background pass would never be noticed. That is why the
    // server is stricter than this panel is.
    const shown = item.row || (item.state === 'unsure' ? item.candidates[0] : null);

    const tick = el('input', {
      type: 'checkbox', checked: item.take, 'aria-label': 'include this one',
    });
    tick.addEventListener('change', () => { item.take = tick.checked; paintFooter(); });

    const body = el('div.result-body', null, [
      el('h4', { text: (shown && shown.title) || item.title || item.raw }),
      el('div.card-meta', null, [
        (shown && shown.year) || item.year
          ? el('span', { text: String((shown && shown.year) || item.year) }) : null,
        el('span.tag-badge.type', {
          text: TYPE_LABEL[(shown && shown.type) || opts.type] || opts.type,
        }),
        badge(item),
      ]),
      item.state === 'unsure'
        ? el('p.hint', { text: 'Not certain — check it, or pick another.' })
        : (item.state === 'missing' && item.note
          ? el('p.hint', { text: item.note }) : null),
    ]);

    const art = shown && shown.poster
      ? el('img', { src: shown.poster, alt: '', loading: 'lazy' })
      : el('img', { alt: '' });

    const parts = [tick, art, body];

    if (item.state === 'unsure') {
      const pick = el('button.btn.sm.ghost', { type: 'button', text: 'Pick' });
      pick.addEventListener('click', () => choose(item));
      parts.push(pick);
    }
    return el('div.result', null, parts);
  }

  function paint() {
    list.replaceChildren();
    if (bulk) {
      status.textContent = bulkSummary(bulk);
      paintFooter();
      return;
    }
    if (!entries.length) {
      status.textContent = 'Paste anything.';
      paintFooter();
      return;
    }
    for (const item of entries) list.append(drawRow(item));
    const found = entries.filter((e) => e.state === 'found').length;
    const left = entries.filter((e) => e.state === 'waiting' || e.state === 'looking').length;
    const missing = entries.filter((e) => e.state === 'missing').length;
    status.textContent = left
      ? `Looking up ${entries.length} — ${found} found so far…`
      : `${entries.length} ${entries.length === 1 ? 'title' : 'titles'}, ${found} matched`
        + (missing ? `, ${missing} not found` : '');
    paintFooter();
  }

  /** Swap one entry for a candidate the reader picked. */
  function choose(item) {
    const box = el('div.menu-list');
    for (const row of item.candidates) {
      const button = el('button.menu-item', { type: 'button' }, [
        row.poster ? el('img.pick-art', { src: row.poster, alt: '', loading: 'lazy' }) : null,
        el('span', null, [
          `${row.title}${row.year ? ` (${row.year})` : ''}`,
          el('small', {
            text: [TYPE_LABEL[row.type] || row.type, row.creator,
              row.extRating ? `${(row.extRating / 10).toFixed(1)}` : '']
              .filter(Boolean).join(' · '),
          }),
        ]),
      ]);
      button.addEventListener('click', () => {
        item.row = row;
        item.state = 'found';
        item.via = 'picked';
        item.take = true;
        sheet.close();
        paint();
      });
      box.append(button);
    }
    const keep = el('button.menu-item', { type: 'button' }, [
      el('span', null, ['None of these',
        el('small', { text: `Add "${item.title}" as typed, with no artwork` })]),
    ]);
    keep.addEventListener('click', () => {
      item.row = null;
      item.state = 'missing';
      item.note = 'added as typed';
      sheet.close();
      paint();
    });
    box.append(keep);
    const sheet = openSheet({ title: item.title || item.raw, body: box });
  }

  function paintFooter() {
    footer.replaceChildren();
    const go = el('button.btn.primary.grow', { type: 'button' });

    if (bulk) {
      go.textContent = bulk.items.length
        ? `Import ${bulk.items.length} ${bulk.items.length === 1 ? 'title' : 'titles'}`
        : 'Nothing to import';
      go.disabled = !bulk.items.length || busy;
      go.addEventListener('click', importBulk);
      footer.append(go);
      return;
    }

    const taking = entries.filter((e) => e.take).length;
    go.textContent = taking ? `Add ${taking} ${taking === 1 ? 'title' : 'titles'}` : 'Nothing selected';
    go.disabled = !taking || busy;
    go.addEventListener('click', addChosen);
    footer.append(go);
  }

  /* ------------------------------------------------------------ reading */

  function read() {
    const text = area.value;
    const trimmed = text.trim();
    seq += 1;
    const mine = seq;
    entries = [];
    bulk = null;

    if (!trimmed) { paint(); return; }

    // A backup, a spreadsheet, or a document. These already carry their own
    // structure, and there may be thousands of them.
    const structured = trimmed.startsWith('{') || trimmed.startsWith('[')
      || /^[^\n]*,[^\n]*\btitle\b/i.test(trimmed.split('\n', 1)[0]);
    const lines = trimmed.split('\n').filter((l) => l.trim()).length;

    if (structured || lines > RESOLVE_LIMIT) {
      bulk = parseAny(text, { ...opts, headingsAsTags: true, captureSources: true });
      paint();
      return;
    }

    entries = trimmed.split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      // A list pasted from a document arrives with its bullets and boxes on.
      .map((line) => line.replace(/^(?:[-*+•●◦]|\d+[.)])\s+/, '').replace(/^\[[ xX]\]\s*/, ''))
      .filter((line) => line && !isPlaceholder(line))
      .map(entry);

    paint();
    pool(entries, LANES, (item) => lookUp(item, opts.type),
      () => { if (mine === seq) paint(); })
      .then(() => { if (mine === seq) paint(); });
  }

  /* ----------------------------------------------------------- importing */

  function bulkSummary(parsed) {
    const n = parsed.items.length;
    if (!n) return `Read it as ${parsed.format.toUpperCase()} but found no titles.`;
    return `${parsed.format.toUpperCase()}: ${n} titles`
      + (parsed.sources && parsed.sources.length ? `, ${parsed.sources.length} source links` : '')
      + (parsed.placeholders ? `, ${parsed.placeholders} placeholders ignored` : '')
      + '. Artwork and details are fetched in the background after importing.';
  }

  /** Fold a list of new items into the library, skipping what is there. */
  function merge(rows) {
    const seen = new Map();
    for (const item of live()) seen.set(titleKey(item.title, item.year), item);
    const loose = new Map();
    for (const item of live()) {
      const key = titleKey(item.title, null);
      if (!loose.has(key)) loose.set(key, item);
    }

    const fresh = [];
    let already = 0;
    for (const raw of rows) {
      const match = seen.get(titleKey(raw.title, raw.year))
        || (raw.year ? null : loose.get(titleKey(raw.title, null)));
      if (match) { already += 1; continue; }
      const made = newItem(raw);
      fresh.push(made);
      seen.set(titleKey(made.title, made.year), made);
    }
    if (fresh.length) addMany(fresh);
    return { added: fresh.length, already, ids: fresh.map((i) => i.id) };
  }

  /** Fill in what these titles are still missing, and show it landing.
   *
   * Three things have to happen in this order, and getting it wrong is why
   * nothing appeared before: the items have to reach the server, because the
   * pass works from the server's copy and adding only marks the library
   * dirty; the pass has to be told which titles, or it sweeps the whole
   * library; and what it writes has to be pulled back down, because it
   * writes on the server and this page would not otherwise ask again for a
   * minute.
   */
  async function fillInTheRest(ids) {
    if (!ids.length || !state.config || !state.config.network) return;
    try {
      await sync();
      await api('POST', '/enrich', { action: 'start', scope: 'missing', ids });
    } catch { /* Settings still has the button */ return; }
    watchFillIn(onDone);
  }

  async function importBulk() {
    busy = true;
    paintFooter();
    const report = merge(bulk.items.map((raw) => ({ ...raw, status: raw.status || opts.status })));
    busy = false;
    said(report, bulk.items.length);
    area.value = '';
    read();
    onDone();
    await fillInTheRest(report.ids);
  }

  async function addChosen() {
    busy = true;
    paintFooter();
    const chosen = entries.filter((e) => e.take);
    const report = merge(chosen.map((e) => toItem(e, opts)));
    busy = false;
    said(report, chosen.length);
    area.value = '';
    read();
    onDone();
    // Every added title, not only the ones that came back blank: a match
    // carries artwork and a cast, and the age rating and the Wikipedia
    // article still have to be gone and fetched.
    await fillInTheRest(report.ids);
  }

  function said(report, asked) {
    if (!report.added) {
      toast(asked ? 'Already in your library' : 'Nothing to add', { error: !asked });
      return;
    }
    toast(`Added ${report.added}`
      + (report.already ? `, ${report.already} already there` : ''));
  }

  /* -------------------------------------------------------------- wiring */

  let timer = 0;
  area.addEventListener('input', () => {
    clearTimeout(timer);
    // A pasted link needs no thinking time; a title being typed does.
    timer = setTimeout(read, looksLikeLink(area.value) ? 60 : 420);
  });
  area.addEventListener('paste', () => { clearTimeout(timer); timer = setTimeout(read, 40); });
  area.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      clearTimeout(timer);
      read();
    }
  });

  const file = el('input', { type: 'file', accept: '.json,.csv,.md,.txt,.markdown,text/*' });
  file.addEventListener('change', async () => {
    const chosen = file.files && file.files[0];
    if (!chosen) return;
    area.value = await chosen.text();
    read();
  });

  wrap.append(
    field('Paste anything', area,
      'A link is looked up exactly. A title is matched even when the year is '
      + 'off or the spelling is not quite right.'),
    el('div.field', null, [file]),
    field('Treat untyped entries as',
      segmented(TYPES.slice(0, 5), opts.type, (v) => { opts.type = v; read(); })),
    field('Status', segmented(STATUSES, opts.status, (v) => { opts.status = v; read(); })),
    status,
    list,
    footer,
  );
  paintFooter();
  return wrap;
}

const VIA_LABEL = {
  'imdb-id': 'from the IMDb link',
  'tmdb-id': 'from the TMDB link',
  'tvmaze-id': 'from the TVmaze link',
  'wikidata-id': 'from the Wikidata link',
  'wikipedia-id': 'matched through Wikipedia',
  wikipedia: 'from Wikipedia',
  page: 'from that page',
  picked: 'you picked it',
  spelling: 'spelling corrected',
  'other-medium': 'found under the other medium',
  tvmaze: 'from TVmaze',
  openlibrary: 'from Open Library',
  itunes: 'from iTunes',
  search: 'matched',
};

function viaLabel(via) { return VIA_LABEL[via] || 'matched'; }
