/* Import and export.
 *
 * The outline parser is aimed squarely at Google Docs exports: decade and
 * year headings, `- [ ] Title`, indented links under an item, `* Title - 1948`
 * bullets, numbered lists with `(1995)`, and the backslash escaping Docs
 * sprinkles through markdown. JSON and CSV round-trip losslessly.
 */

import {
  state, live, newItem, titleKey, addMany, replaceAll, addSource, checkpoint,
  TYPES, STATUSES, TYPE_LABEL, STATUS_LABEL,
} from './store.js';
import {
  el, openSheet, toast, download, copyText, fmtDate,
} from './ui.js';
import { universalPanel } from './importer.js';

/* ============================== export ================================= */

export function toJSON(items = state.items, sources = state.sources) {
  return JSON.stringify({
    app: 'media-tracker',
    schema: 1,
    exportedAt: new Date().toISOString(),
    count: items.filter((i) => !i.deleted).length,
    items: items.filter((i) => !i.deleted),
    sources,
  }, null, 2);
}

const CSV_COLUMNS = [
  'title', 'year', 'type', 'status', 'rating', 'heart', 'tags', 'links', 'notes',
  'addedAt', 'watchedAt', 'updatedAt', 'runtime', 'genres', 'creator', 'poster',
  'imdbId', 'overview', 'id',
];

function csvCell(value) {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCSV(items) {
  const rows = [CSV_COLUMNS.join(',')];
  for (const item of items) {
    if (item.deleted) continue;
    rows.push(CSV_COLUMNS.map((key) => {
      if (key === 'tags') return csvCell(item.tags.join('|'));
      if (key === 'genres') return csvCell((item.genres || []).join('|'));
      if (key === 'links') return csvCell(item.links.map((l) => l.url).join(' | '));
      if (key === 'heart') return item.heart ? 'yes' : '';
      return csvCell(item[key]);
    }).join(','));
  }
  return rows.join('\r\n');
}

/** Markdown that looks like the doc this replaced, and re-imports cleanly. */
export function toMarkdown(items) {
  const rows = items.filter((i) => !i.deleted);
  const byYear = new Map();
  for (const item of rows) {
    const key = item.year || 0;
    if (!byYear.has(key)) byYear.set(key, []);
    byYear.get(key).push(item);
  }

  const out = [`# Media library`, '', `_${rows.length} titles, exported ${fmtDate(new Date().toISOString())}_`, ''];
  const years = [...byYear.keys()].sort((a, b) => b - a);

  for (const year of years) {
    out.push(`## ${year || 'No year'}`, '');
    const list = byYear.get(year).sort((a, b) => a.title.localeCompare(b.title));
    for (const item of list) {
      const marks = [];
      if (item.rating) marks.push(`${item.rating}/10`);
      if (item.heart) marks.push('love');
      if (item.status !== 'queue' && item.status !== 'watched') marks.push(STATUS_LABEL[item.status]);
      if (item.type !== 'movie') marks.push(TYPE_LABEL[item.type]);
      const suffix = marks.length ? `  (${marks.join(', ')})` : '';
      out.push(`- [${item.status === 'watched' ? 'x' : ' '}] ${item.title}${suffix}`);
      for (const link of item.links) out.push(`      - ${link.url}`);
      if (item.notes) out.push(`      > ${item.notes.replace(/\n+/g, ' ')}`);
    }
    out.push('');
  }

  if (state.sources.length) {
    out.push('# Sources', '');
    for (const source of state.sources) out.push(`- ${source.url}`);
  }
  return out.join('\n');
}

/* ============================== import ================================= */

const RX = {
  mdLink: /\[([^\]]*)\]\(((?:[^()\s]|\([^()\s]*\))+)\)/g,
  bareUrl: /https?:\/\/[^\s<>()[\]"']+/g,
  bullet: /^(\s*)(?:[-*+•●◦]|\d+[.)])\s+(.*)$/,
  checkbox: /^\[([ xX])\]\s*(.*)$/,
  heading: /^(#{1,6})\s+(.*)$/,
  boldHead: /^\*\*(.+?)\*\*:?\s*$/,
  yearOnly: /^(?:19|20)\d{2}$/,
  decade: /^(?:19|20)?\d0['’]?s$/i,
  // A year, or a run of them, as a document writes it. Kept in step with
  // RX_PAREN_YEARS / RX_DASH_YEARS in server/seed.py.
  yearSpan: /^((?:18|19|20)\d{2})\s*(?:[-–—/]\s*(?:(?:18|19|20)?\d{2}|present|now|date|ongoing|\?+)?)?$/i,
  yearMedium: /^((?:18|19|20)\d{2})\s+(?:film|movie|tv series|television series|series|miniseries|anime|documentary|video game|novel|book)s?$/i,
  dashYears: /^(.{2,}?)\s*[-–—,]\s*((?:18|19|20)\d{2})(?:\s*[-–—/]\s*(?:(?:18|19|20)?\d{2}|present|now|date|ongoing|\?+))?\s*$/i,
};

/** Undo Google Docs' markdown escaping and invisible characters. */
function clean(text) {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .replace(/[​‎‏﻿]/g, '')
    .replace(/ /g, ' ')
    .replace(/\\([^\w\s])/g, '$1');
}

const TAG_STOP = new Set([
  'movies', 'movie', 'films', 'film', 'tv', 'tv-shows', 'shows', 'show', 'series',
  'watched', 'skipped', 'queue', 'sources', 'source', 'list', 'lists', 'misc',
  'books', 'book', 'radio', 'podcasts', 'podcast', 'anime', 'games', 'game',
]);

/* "asdf" is what you type into a document to hold a spot open. It is not a
 * title, and it never becomes one. Kept in step with server/seed.py. */
const KEYBOARD_MASH = /^(?:asdf|fdsa|asdg|qwerty|qwer|zxcv|hjkl|asd|sdf|fgh)+\d*$/;

export function isPlaceholder(title) {
  const squashed = String(title || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
  return !squashed || KEYBOARD_MASH.test(squashed);
}

function slug(text) {
  return String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function headingTags(text) {
  return String(text)
    .split(/\s[-–—]\s|[/,]/)
    .map((part) => slug(part))
    .filter((tag) => tag.length > 1 && tag.length <= 24
                  && !/^\d+$/.test(tag) && !TAG_STOP.has(tag));
}

function typeHint(text) {
  const t = text.toLowerCase();
  if (/anime/.test(t)) return 'anime';
  if (/\btv\b|series|shows?\b/.test(t)) return 'tv';
  if (/documentar/.test(t)) return 'doc';
  if (/podcast|radio/.test(t)) return 'podcast';
  if (/\bbooks?\b|reading/.test(t)) return 'book';
  if (/\bgames?\b/.test(t)) return 'game';
  if (/movies?|films?/.test(t)) return 'movie';
  return null;
}

function statusHint(text) {
  const t = text.toLowerCase();
  if (/skip|drop|abandon|nope/.test(t)) return 'dropped';
  if (/watched|seen|finished|completed/.test(t)) return 'watched';
  if (/watching|in progress|current/.test(t)) return 'watching';
  if (/queue|to watch|want|wish|backlog/.test(t)) return 'queue';
  return null;
}

/** Pull a year, and any trailing parenthetical notes, out of a title. */
function splitTitle(raw) {
  let title = raw.trim().replace(/[*_]+$/, '').replace(/[:;,]\s*$/, '').trim();
  let year = null;
  const notes = [];

  // Trailing parentheses, innermost last: "Title (1995) (a note)",
  // "The Wire (2002-2008)", "Parasite (2019 film)".
  for (let guard = 0; guard < 4; guard += 1) {
    const match = title.match(/^(.*?)\s*[([]([^()[\]]{1,80})[)\]]\s*$/);
    if (!match) break;
    const inner = match[2].trim();
    const span = inner.match(RX.yearSpan) || inner.match(RX.yearMedium);
    if (span) {
      if (!year) year = Number(span[1]);
    } else if (/^(?:18|19|20)\d{2}$/.test(inner)) {
      if (!year) year = Number(inner);
    } else {
      notes.unshift(inner);
    }
    title = match[1].trim();
  }

  // A run a document gives as a span: "Yes, Minister - 1980-1984",
  // "Dickinson - 2019-21", "Cheers - 1982-present". The first year is the one
  // that identifies the title, and the whole span comes off it — matching only
  // the last year leaves "Yes, Minister - 1980" as the title and 1984 as the
  // year, which is neither the name of anything nor the year it started.
  //
  // The span comes off whether or not a year has been found already, because
  // it is not part of the name either way.
  const tail = title.match(RX.dashYears);
  if (tail) {
    title = tail[1].trim();
    if (!year) year = Number(tail[2]);
  }

  return { title: title.replace(/\s{2,}/g, ' ').trim(), year, notes: notes.join(' ') };
}

function extractLinks(text) {
  const links = [];
  let rest = text;

  rest = rest.replace(RX.mdLink, (_all, label, url) => {
    links.push({ label: /^https?:/i.test(label) ? '' : label.trim().slice(0, 80), url });
    return ' ';
  });
  rest = rest.replace(RX.bareUrl, (url) => {
    const trimmed = url.replace(/[.,;)]+$/, '');
    if (!links.some((l) => l.url === trimmed)) links.push({ label: '', url: trimmed });
    return ' ';
  });

  // Dedupe, keeping the first label we saw.
  const seen = new Set();
  const unique = links.filter((l) => (seen.has(l.url) ? false : (seen.add(l.url), true)));
  return { links: unique, rest: rest.replace(/\s{2,}/g, ' ').trim() };
}

/**
 * Parse an outline / list / pasted document into items and sources.
 * Returns { items, sources, stats }.
 */
export function parseOutline(text, options = {}) {
  const opts = {
    type: 'movie',
    status: 'queue',
    headingsAsTags: true,
    captureSources: true,
    extraTags: [],
    ...options,
  };

  const lines = clean(text).split('\n');
  const items = [];
  const sources = [];
  const headings = [];
  let placeholders = 0;
  let last = null;
  let lastIndent = 0;

  const context = () => {
    let year = null;
    let type = opts.type;
    let status = opts.status;
    const tags = [...opts.extraTags];

    for (const heading of headings) {
      if (!heading) continue;
      const bare = heading.trim();
      if (RX.yearOnly.test(bare)) { year = Number(bare); continue; }
      if (RX.decade.test(bare)) continue;
      const t = typeHint(bare); if (t) type = t;
      const s = statusHint(bare); if (s) status = s;
      if (opts.headingsAsTags) tags.push(...headingTags(bare));
    }
    return { year, type, status, tags: [...new Set(tags)].slice(0, 8) };
  };

  const setHeading = (level, value) => {
    headings.length = Math.min(headings.length, level);
    headings[level - 1] = value;
    last = null;
  };

  const pushSource = (link, ctx) => {
    if (!opts.captureSources) return;
    if (sources.some((s) => s.url === link.url)) return;
    sources.push({ url: link.url, title: link.label || '', tags: ctx.tags.slice(0, 4) });
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (!line.trim()) continue;

    const heading = line.match(RX.heading);
    if (heading) { setHeading(heading[1].length, heading[2]); continue; }

    const bold = line.match(RX.boldHead);
    if (bold) { setHeading(3, bold[1]); continue; }

    const bullet = line.match(RX.bullet);
    const indent = bullet ? bullet[1].replace(/\t/g, '    ').length : 0;
    let content = bullet ? bullet[2] : line.trim();

    let done = null;
    const box = content.match(RX.checkbox);
    if (box) { done = box[1].toLowerCase() === 'x'; content = box[2]; }

    // A bare line that is neither a bullet nor a link is treated as a
    // sub-heading (Docs users write "Staged - AppleTV" on its own line).
    if (!bullet && !RX.bareUrl.test(content) && content.length < 60 && !/[.!?]$/.test(content)) {
      RX.bareUrl.lastIndex = 0;
      setHeading(4, content);
      continue;
    }
    RX.bareUrl.lastIndex = 0;

    const { links, rest } = extractLinks(content);
    const ctx = context();

    if (!rest) {
      // Link-only line: belongs to the item above it if it is indented.
      if (links.length && last && (indent > lastIndent || indent >= 2)) {
        for (const link of links) {
          if (!last.links.some((l) => l.url === link.url)) last.links.push(link);
        }
      } else {
        links.forEach((link) => pushSource(link, ctx));
      }
      continue;
    }

    const { title, year, notes } = splitTitle(rest);
    if (!title || !/[a-z0-9]/i.test(title)) continue;
    if (isPlaceholder(title)) { placeholders += 1; last = null; continue; }

    const item = {
      title,
      year: year || ctx.year || null,
      type: ctx.type,
      status: done === true ? 'watched' : ctx.status,
      links,
      tags: ctx.tags,
      notes,
    };
    if (item.status === 'watched') item.watchedAt = new Date().toISOString();
    items.push(item);
    last = item;
    lastIndent = indent;
  }

  return {
    items, sources, placeholders,
    stats: { items: items.length, sources: sources.length, placeholders },
  };
}

/* ------------------------------------------------------------------- CSV */

export function parseCSV(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  const src = clean(text);

  for (let i = 0; i < src.length; i += 1) {
    const char = src[i];
    if (quoted) {
      if (char === '"') {
        if (src[i + 1] === '"') { cell += '"'; i += 1; } else quoted = false;
      } else cell += char;
      continue;
    }
    if (char === '"') { quoted = true; continue; }
    if (char === ',') { row.push(cell); cell = ''; continue; }
    if (char === '\n') { row.push(cell); rows.push(row); row = []; cell = ''; continue; }
    cell += char;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  if (!rows.length) return { items: [], sources: [] };

  const header = rows.shift().map((h) => h.trim().toLowerCase());
  const index = (...names) => {
    for (const name of names) {
      const at = header.indexOf(name);
      if (at !== -1) return at;
    }
    return -1;
  };

  const map = {
    title: index('title', 'name', 'movie', 'film'),
    year: index('year', 'release year', 'released'),
    type: index('type', 'media', 'kind'),
    status: index('status', 'state'),
    rating: index('rating', 'score', 'my rating'),
    heart: index('heart', 'loved', 'favorite', 'favourite'),
    tags: index('tags', 'genre tags', 'labels'),
    links: index('links', 'link', 'url', 'urls'),
    notes: index('notes', 'note', 'comment'),
    addedAt: index('addedat', 'added', 'date added'),
    watchedAt: index('watchedat', 'watched', 'date watched'),
    runtime: index('runtime', 'length'),
    genres: index('genres', 'genre'),
    creator: index('creator', 'director', 'author'),
    poster: index('poster', 'image'),
    overview: index('overview', 'description', 'plot'),
    imdbId: index('imdbid', 'imdb'),
  };
  if (map.title === -1) return { items: [], sources: [] };

  const at = (row, key) => (map[key] >= 0 ? (row[map[key]] || '').trim() : '');
  const items = [];

  for (const line of rows) {
    const title = at(line, 'title');
    if (!title) continue;
    const status = at(line, 'status').toLowerCase();
    const watchedAt = at(line, 'watchedAt');
    items.push({
      title,
      year: Number(at(line, 'year')) || null,
      type: TYPES.some((t) => t.id === at(line, 'type')) ? at(line, 'type') : 'movie',
      status: STATUSES.some((s) => s.id === status) ? status : (watchedAt ? 'watched' : 'queue'),
      rating: Number(at(line, 'rating')) || null,
      heart: /^(y|yes|true|1|love)/i.test(at(line, 'heart')),
      tags: at(line, 'tags').split(/[|;]/).map((t) => slug(t)).filter(Boolean),
      genres: at(line, 'genres').split(/[|;]/).map((g) => g.trim()).filter(Boolean),
      links: at(line, 'links').split(/[\s|]+/).filter((u) => /^https?:/i.test(u))
        .map((url) => ({ label: '', url })),
      notes: at(line, 'notes'),
      addedAt: at(line, 'addedAt') || undefined,
      watchedAt: watchedAt || undefined,
      runtime: Number(at(line, 'runtime')) || null,
      creator: at(line, 'creator'),
      poster: at(line, 'poster'),
      overview: at(line, 'overview'),
      imdbId: at(line, 'imdbId'),
    });
  }
  return { items, sources: [] };
}

/* --------------------------------------------------------------- detection */

export function parseAny(text, options) {
  const trimmed = text.trim();

  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const data = JSON.parse(trimmed);
      const rows = Array.isArray(data) ? data : data.items || [];
      return {
        format: 'json',
        items: rows.filter((r) => r && r.title),
        sources: (Array.isArray(data) ? [] : data.sources) || [],
      };
    } catch { /* fall through to the text parsers */ }
  }

  const firstLine = trimmed.split('\n', 1)[0].toLowerCase();
  if (firstLine.includes(',') && /(^|,)\s*"?title"?\s*(,|$)/.test(firstLine)) {
    return { format: 'csv', ...parseCSV(text) };
  }

  return { format: 'outline', ...parseOutline(text, options) };
}

/* ------------------------------------------------------------ apply import */

export function applyImport(parsed, { mode = 'merge', skipDuplicates = true }) {
  const report = { added: 0, merged: 0, skipped: 0, sources: 0 };

  if (mode === 'replace') {
    checkpoint('replace library');
    const items = parsed.items.map((raw) => newItem(raw));
    replaceAll(items, parsed.sources.map((s) => ({
      id: Math.random().toString(36).slice(2), url: s.url, title: s.title || '',
      tags: s.tags || [], note: '', addedAt: new Date().toISOString(),
    })));
    report.added = items.length;
    report.sources = parsed.sources.length;
    return report;
  }

  checkpoint('import');
  const existing = new Map();
  for (const item of live()) existing.set(titleKey(item.title, item.year), item);
  // A title with no year should still match one that has a year.
  const looseIndex = new Map();
  for (const item of live()) {
    const key = titleKey(item.title, null);
    if (!looseIndex.has(key)) looseIndex.set(key, item);
  }

  const fresh = [];
  for (const raw of parsed.items) {
    const exact = existing.get(titleKey(raw.title, raw.year));
    const loose = raw.year ? null : looseIndex.get(titleKey(raw.title, null));
    const match = exact || loose;

    if (match && skipDuplicates) {
      // Not a straight skip: fold in anything the existing entry is missing.
      let changed = false;
      for (const link of raw.links || []) {
        if (!match.links.some((l) => l.url === link.url)) { match.links.push(link); changed = true; }
      }
      for (const tag of raw.tags || []) {
        if (!match.tags.includes(tag)) { match.tags.push(tag); changed = true; }
      }
      if (!match.year && raw.year) { match.year = raw.year; changed = true; }
      if (raw.status === 'watched' && match.status !== 'watched') {
        match.status = 'watched';
        match.watchedAt = raw.watchedAt || new Date().toISOString();
        changed = true;
      }
      if (changed) { match.updatedAt = new Date().toISOString(); report.merged += 1; }
      else report.skipped += 1;
      continue;
    }

    const item = newItem(raw);
    fresh.push(item);
    existing.set(titleKey(item.title, item.year), item);
    report.added += 1;
  }

  if (fresh.length) addMany(fresh);
  for (const source of parsed.sources || []) {
    if (addSource(source.url, source.title, source.tags)) report.sources += 1;
  }
  return report;
}

/* ============================= the sheet ============================== */

export function openPortingSheet(onDone, initialTab = 'import') {
  const body = el('div');
  const tabs = el('div.tabs');
  const panel = el('div');

  let current = initialTab;
  const tabButtons = {};

  for (const [id, label] of [['import', 'Import'], ['export', 'Export']]) {
    const button = el('button', {
      type: 'button', text: label, 'aria-selected': String(id === current),
      onclick: () => { current = id; draw(); },
    });
    tabButtons[id] = button;
    tabs.append(button);
  }

  function draw() {
    for (const [id, button] of Object.entries(tabButtons)) {
      button.setAttribute('aria-selected', String(id === current));
    }
    panel.replaceChildren(current === 'import' ? universalPanel(onDone) : exportPanel());
  }

  body.append(tabs, panel);
  draw();
  openSheet({ title: 'Import & export', body });
}

function exportPanel() {
  const wrap = el('div');
  const stamp = new Date().toISOString().slice(0, 10);
  const rows = () => state.items.filter((i) => !i.deleted);

  const button = (label, hint, fn) => el('button.menu-item', { type: 'button', onclick: fn }, [
    el('span', null, [label, el('small', { text: hint })]),
  ]);

  wrap.append(el('div.menu-list', null, [
    button('JSON backup', 'Everything: metadata, dates, links, sources. Re-imports exactly.',
      () => { download(`media-library-${stamp}.json`, toJSON(), 'application/json'); toast('JSON downloaded'); }),
    button('CSV', 'One row per title, for spreadsheets.',
      () => { download(`media-library-${stamp}.csv`, toCSV(rows()), 'text/csv'); toast('CSV downloaded'); }),
    button('Markdown', 'Year headings and checkboxes, like the doc this replaced.',
      () => { download(`media-library-${stamp}.md`, toMarkdown(rows()), 'text/markdown'); toast('Markdown downloaded'); }),
    button('Copy JSON to clipboard', 'For pasting somewhere else right now.',
      async () => toast(await copyText(toJSON()) ? 'Copied to clipboard' : 'Clipboard blocked - use the download', { error: false })),
  ]));

  wrap.append(el('p.hint', {
    text: `${rows().length} titles and ${state.sources.length} source links are included. `
        + 'The server also keeps rolling backups in data/backups/.',
  }));
  return wrap;
}

