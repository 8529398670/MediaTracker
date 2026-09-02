/* Item detail / edit sheet, the quick rating picker, and the add flow
 * (online lookup, manual entry, or bulk paste). */

import {
  state, api, TYPES, STATUSES, TYPE_LABEL, addItem, patchItem, removeItem,
  checkpoint, undo, nowISO,
} from './store.js';
import {
  el, icon, field, openSheet, toast, confirmSheet, segmented, select,
  setChildren, fmtDate, isoToDateInput, dateInputToISO, hostOf,
} from './ui.js';
import { openPortingSheet } from './porting.js';
import { justWatchUrl } from './views.js';

/* ---------------------------------------------------------- rating picker */

export function openRating(item, onSave) {
  const grid = el('div.rate-grid');
  let value = item.rating || 0;

  const paint = () => {
    [...grid.children].forEach((child) => {
      child.setAttribute('aria-pressed', String(Number(child.dataset.v) === value && value > 0));
    });
  };

  for (let n = 1; n <= 10; n += 1) {
    grid.append(el('button', {
      type: 'button', text: String(n), dataset: { v: String(n) },
      onclick: () => { value = n; paint(); commit(); },
    }));
  }
  grid.append(el('button.clear', {
    type: 'button', text: 'Clear', dataset: { v: '0' },
    onclick: () => { value = 0; paint(); commit(); },
  }));
  paint();

  const heart = el('button.chip.chip-toggle', {
    type: 'button', 'aria-pressed': String(!!item.heart),
  }, [icon(item.heart ? 'heart-fill' : 'heart'), el('span', { text: 'Loved' })]);

  heart.addEventListener('click', () => {
    const next = !(heart.getAttribute('aria-pressed') === 'true');
    heart.setAttribute('aria-pressed', String(next));
    heart.replaceChildren(icon(next ? 'heart-fill' : 'heart'), el('span', { text: 'Loved' }));
    patchItem(item.id, { heart: next });
    onSave();
  });

  const handle = openSheet({
    title: item.title,
    body: el('div', null, [
      field('Rating out of 10', grid),
      field('Or just a heart', el('div.chip-row', null, [heart]),
        'The heart is independent of the number - use whichever you feel like in the moment.'),
    ]),
  });

  function commit() {
    patchItem(item.id, { rating: value || null });
    onSave();
    setTimeout(() => handle.close(), 140);
  }
}

/* -------------------------------------------------------------- edit sheet */

export function openItem(item, { onChange, onDeleted }) {
  const draft = { ...item, tags: [...item.tags], links: item.links.map((l) => ({ ...l })) };
  const body = el('div');

  /* header: poster + quick facts */
  const poster = el('img.detail-poster', { alt: '', src: draft.poster || '' });
  if (!draft.poster) poster.style.setProperty('display', 'none');

  const facts = el('div.kv');
  const paintFacts = () => {
    setChildren(facts, [
      el('span', null, [el('b', { text: 'Added ' }), fmtDate(draft.addedAt)]),
      draft.watchedAt ? el('span', null, [el('b', { text: 'Watched ' }), fmtDate(draft.watchedAt)]) : null,
      draft.runtime ? el('span', null, [el('b', { text: 'Runtime ' }), `${draft.runtime} min`]) : null,
      draft.creator ? el('span', { text: draft.creator }) : null,
      draft.certification
        ? el('span', null, [el('b', { text: 'Rated ' }), draft.certification]) : null,
      draft.genres && draft.genres.length ? el('span', { text: draft.genres.join(', ') }) : null,
      draft.extRating
        ? el('span', null, [el('b', { text: (draft.extRating / 10).toFixed(1) }), ' elsewhere'])
        : null,
    ]);
  };
  paintFacts();

  const head = el('div.detail-top', null, [
    poster,
    el('div', null, [
      el('h3', { text: item.title }),
      facts,
      draft.overview ? el('p.hint', { text: draft.overview }) : null,
    ]),
  ]);
  body.append(head);

  /* fields */
  const title = el('input.input', { type: 'text', value: draft.title, placeholder: 'Title' });
  const year = el('input.input', {
    type: 'number', inputmode: 'numeric', value: draft.year || '', placeholder: 'Year',
  });
  const type = select(TYPES, draft.type, (v) => { draft.type = v; });

  body.append(field('Title', title));
  body.append(el('div.row', null, [field('Year', year), field('Type', type)]));

  body.append(field('Status', segmented(STATUSES, draft.status, (v) => {
    draft.status = v;
    if (v === 'watched' && !draft.watchedAt) {
      draft.watchedAt = nowISO();
      watched.value = isoToDateInput(draft.watchedAt);
    }
    if (v !== 'watched') { draft.watchedAt = null; watched.value = ''; }
    paintFacts();
  })));

  /* rating + heart */
  const rateGrid = el('div.rate-grid');
  const paintRating = () => {
    [...rateGrid.children].forEach((child) => {
      child.setAttribute('aria-pressed', String(Number(child.dataset.v) === (draft.rating || 0) && !!draft.rating));
    });
  };
  for (let n = 1; n <= 10; n += 1) {
    rateGrid.append(el('button', {
      type: 'button', text: String(n), dataset: { v: String(n) },
      onclick: () => { draft.rating = n; paintRating(); },
    }));
  }
  rateGrid.append(el('button.clear', {
    type: 'button', text: 'Clear', dataset: { v: '0' },
    onclick: () => { draft.rating = null; paintRating(); },
  }));
  paintRating();

  const heartChip = el('button.chip.chip-toggle', {
    type: 'button', 'aria-pressed': String(!!draft.heart),
  }, [icon(draft.heart ? 'heart-fill' : 'heart'), el('span', { text: 'Loved' })]);
  heartChip.addEventListener('click', () => {
    draft.heart = !draft.heart;
    heartChip.setAttribute('aria-pressed', String(draft.heart));
    heartChip.replaceChildren(icon(draft.heart ? 'heart-fill' : 'heart'), el('span', { text: 'Loved' }));
  });

  body.append(field('Rating', rateGrid));
  body.append(field('Heart', el('div.chip-row', null, [heartChip])));

  /* tags */
  const tags = el('input.input', {
    type: 'text', value: draft.tags.join(', '), placeholder: 'noir, rewatch, with mom',
    autocapitalize: 'none', spellcheck: false,
  });
  body.append(field('Tags', tags, 'Comma separated.'));

  /* links */
  const linkBox = el('div');
  function drawLinks() {
    linkBox.replaceChildren();
    draft.links.forEach((link, index) => {
      const url = el('input.input', { type: 'url', value: link.url, placeholder: 'https://...' });
      url.addEventListener('input', () => { draft.links[index].url = url.value.trim(); });
      const remove = el('button.icon-btn', {
        type: 'button', 'aria-label': 'Remove link',
        onclick: () => { draft.links.splice(index, 1); drawLinks(); },
      }, icon('trash'));
      linkBox.append(el('div.link-row', null, [url, remove]));
    });
    const add = el('button.btn.sm.ghost', {
      type: 'button', onclick: () => { draft.links.push({ label: '', url: '' }); drawLinks(); },
    }, [icon('plus'), 'Add link']);
    linkBox.append(add);
  }
  drawLinks();
  body.append(field('Links', linkBox, 'Where to actually watch it.'));

  /* notes */
  const notes = el('textarea.input', { placeholder: 'Anything worth remembering', rows: 3 });
  notes.value = draft.notes || '';
  body.append(field('Notes', notes));

  /* dates */
  const added = el('input.input', { type: 'date', value: isoToDateInput(draft.addedAt) });
  const watched = el('input.input', { type: 'date', value: isoToDateInput(draft.watchedAt) });
  body.append(el('div.row', null, [field('Added', added), field('Watched', watched)]));

  /* metadata refresh */
  const lookupBtn = el('button.btn.sm.ghost', { type: 'button' }, [icon('sparkle'), 'Fetch artwork & details']);
  lookupBtn.addEventListener('click', () => {
    openLookupSheet({
      query: title.value || draft.title,
      kind: draft.type,
      onPick: (meta) => {
        Object.assign(draft, pickMeta(meta, draft));
        if (draft.poster) { poster.src = draft.poster; poster.style.removeProperty('display'); }
        if (!year.value && draft.year) year.value = draft.year;
        paintFacts();
        toast('Details attached');
      },
    });
  });
  const posterUrl = el('input.input', { type: 'url', value: draft.poster || '', placeholder: 'Poster image URL' });
  body.append(el('div.divider'));

  if ((draft.cast || []).length) {
    body.append(field('Cast', el('div.chip-row', null,
      draft.cast.slice(0, 14).map((name) => el('span.pill', { text: name })))));
  }

  /* IMDb sells its data and gates its API, but the pages are open to anyone
     with the id — including the parents guide, which no free API carries.
     JustWatch has no public API either, so that one is a search. */
  const chip = (iconName, label, href) => el('a.link-chip', {
    href, target: '_blank', rel: 'noopener noreferrer',
  }, [icon(iconName), label]);

  const refs = [];
  if (draft.imdbId) {
    refs.push(
      chip('imdb', 'IMDb', `https://www.imdb.com/title/${draft.imdbId}/`),
      chip('note', 'Parents guide', `https://www.imdb.com/title/${draft.imdbId}/parentalguide/`),
      chip('star', 'Full cast', `https://www.imdb.com/title/${draft.imdbId}/fullcredits/`),
    );
  }
  if (draft.wikiUrl) refs.push(chip('wiki', 'Wikipedia', draft.wikiUrl));
  if (draft.title) refs.push(chip('play', 'Where to watch', justWatchUrl(draft)));
  if (refs.length) body.append(field('Find it elsewhere', el('div.chip-row', null, refs)));

  body.append(field('Artwork & metadata', el('div.chip-row', null, [lookupBtn])));
  body.append(field('Poster URL', posterUrl));

  /* footer */
  const del = el('button.btn.danger', { type: 'button' }, [icon('trash')]);
  const save = el('button.btn.primary.grow', { type: 'button', text: 'Save' });
  const handle = openSheet({ title: 'Edit', body, footer: [del, save] });

  del.addEventListener('click', async () => {
    const ok = await confirmSheet({
      title: 'Delete this title?',
      message: `"${item.title}" will be removed from the library. You can undo right after.`,
      confirmLabel: 'Delete', danger: true,
    });
    if (!ok) return;
    checkpoint('delete');
    removeItem(item.id);
    handle.close();
    onDeleted && onDeleted();
    toast(`Deleted "${item.title}"`, { action: { label: 'Undo', fn: () => { undo(); onChange(); } } });
  });

  save.addEventListener('click', () => {
    const fields = {
      title: title.value.trim() || item.title,
      year: Number(year.value) || null,
      type: draft.type,
      status: draft.status,
      rating: draft.rating || null,
      heart: draft.heart,
      tags: tags.value.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean),
      links: draft.links.filter((l) => /^https?:\/\//i.test(l.url)),
      notes: notes.value.trim(),
      poster: posterUrl.value.trim(),
      overview: draft.overview,
      genres: draft.genres,
      runtime: draft.runtime,
      creator: draft.creator,
      source: draft.source,
      sourceId: draft.sourceId,
      imdbId: draft.imdbId,
      wikiUrl: draft.wikiUrl || '',
      extRating: draft.extRating,
      cast: draft.cast || [],
      certification: draft.certification || '',
      addedAt: dateInputToISO(added.value) || item.addedAt,
      watchedAt: dateInputToISO(watched.value),
    };
    if (fields.watchedAt && fields.status !== 'watched') fields.status = 'watched';
    if (!fields.watchedAt && fields.status === 'watched') fields.watchedAt = nowISO();
    patchItem(item.id, fields);
    handle.close();
    onChange();
    toast('Saved');
  });
}

/** Only fill in what the item is missing, so a lookup never clobbers edits. */
function pickMeta(meta, draft) {
  const out = {
    source: meta.source || draft.source,
    sourceId: meta.sourceId || draft.sourceId,
  };
  for (const key of ['poster', 'overview', 'creator', 'imdbId', 'certification', 'wikiUrl']) {
    if (meta[key] && !draft[key]) out[key] = meta[key];
  }
  if (meta.cast && meta.cast.length && !(draft.cast || []).length) out.cast = meta.cast;
  if (meta.poster) out.poster = meta.poster;
  if (meta.year && !draft.year) out.year = meta.year;
  if (meta.runtime && !draft.runtime) out.runtime = meta.runtime;
  if (meta.extRating) out.extRating = meta.extRating;
  if (meta.genres && meta.genres.length && !(draft.genres || []).length) out.genres = meta.genres;
  return out;
}

/* ------------------------------------------------------------ lookup sheet */

const LOOKUP_KINDS = [
  { id: 'any', label: 'Anything' },
  { id: 'movie', label: 'Movies' },
  { id: 'tv', label: 'TV' },
  { id: 'book', label: 'Books' },
  { id: 'podcast', label: 'Podcasts' },
];

export function openLookupSheet({ query = '', kind = 'any', onPick, actionLabel = 'Use' }) {
  let mediaKind = ['movie', 'tv', 'book', 'podcast'].includes(kind) ? kind : 'any';
  const input = el('input.input', {
    type: 'search', value: query, placeholder: 'Title to look up',
    enterkeyhint: 'search', autocapitalize: 'words',
  });
  const results = el('div');
  let timer = 0;
  let seq = 0;

  async function run() {
    const term = input.value.trim();
    if (term.length < 2) { results.replaceChildren(); return; }
    const mine = ++seq;
    results.replaceChildren(el('div.center-note', null, [el('div.spinner'), 'Searching...']));
    try {
      const data = await api('GET', `/lookup?q=${encodeURIComponent(term)}&type=${mediaKind}&limit=12`);
      if (mine !== seq) return;
      paint(data);
    } catch (err) {
      if (mine !== seq) return;
      results.replaceChildren(el('p.hint', {
        text: `Lookup failed: ${err.message}. You can still add it by hand.`,
      }));
    }
  }

  function paint(data) {
    results.replaceChildren();
    if (data.note) results.append(el('p.hint', { text: data.note }));
    if (!data.results || !data.results.length) {
      results.append(el('p.hint', { text: 'No matches. Try fewer words, or add it manually.' }));
      return;
    }
    for (const row of data.results) {
      const use = el('button.btn.sm.primary', { type: 'button', text: actionLabel });
      use.addEventListener('click', async () => {
        use.disabled = true;
        let meta = row;
        if (row.source && row.sourceId) {
          try {
            const detail = await api('GET',
              `/lookup/detail?source=${encodeURIComponent(row.source)}&id=${encodeURIComponent(row.sourceId)}`);
            meta = { ...row, ...Object.fromEntries(Object.entries(detail).filter(([, v]) => v)) };
          } catch { /* the search result is enough */ }
        }
        onPick(meta);
        use.disabled = false;
      });

      results.append(el('div.result', null, [
        row.poster ? el('img', { src: row.poster, alt: '', loading: 'lazy' }) : el('img', { alt: '' }),
        el('div.result-body', null, [
          el('h4', { text: row.title }),
          el('div.card-meta', null, [
            row.year ? el('span', { text: String(row.year) }) : null,
            el('span.tag-badge.type', { text: TYPE_LABEL[row.type] || row.type }),
            row.source ? el('span', { text: row.source }) : null,
            row.extRating ? el('span', { text: `${(row.extRating / 10).toFixed(1)}` }) : null,
          ]),
          row.overview ? el('p', { text: row.overview }) : null,
        ]),
        use,
      ]));
    }
  }

  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 350); });
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); run(); } });

  const body = el('div', null, [
    field('Search', input),
    field('Where to look', segmented(LOOKUP_KINDS, mediaKind, (v) => { mediaKind = v; run(); })),
    results,
  ]);

  const providers = state.config && state.config.providers;
  if (providers && !providers.tmdb) {
    body.append(el('p.hint', {
      text: 'Using iTunes, TVmaze and Open Library (no key needed). '
          + 'Set TMDB_API_KEY when you run the container for richer results.',
    }));
  }

  const handle = openSheet({ title: 'Look it up', body });
  if (query.trim().length >= 2) run();
  return handle;
}

/* --------------------------------------------------------------- add sheet */

export function openAdd(onDone, { defaultType = 'movie' } = {}) {
  const body = el('div');
  const tabs = el('div.tabs');
  const panel = el('div');
  let current = 'search';
  const buttons = {};

  for (const [id, label] of [['search', 'Look up'], ['manual', 'By hand'], ['paste', 'Paste a list']]) {
    const button = el('button', {
      type: 'button', text: label, 'aria-selected': String(id === current),
      onclick: () => { current = id; draw(); },
    });
    buttons[id] = button;
    tabs.append(button);
  }

  function draw() {
    for (const [id, button] of Object.entries(buttons)) {
      button.setAttribute('aria-selected', String(id === current));
    }
    if (current === 'search') panel.replaceChildren(searchPanel());
    else if (current === 'manual') panel.replaceChildren(manualPanel());
    else panel.replaceChildren(pastePanel());
  }

  function searchPanel() {
    const wrap = el('div');
    const input = el('input.input', {
      type: 'search', placeholder: 'Search movies, shows, books...',
      enterkeyhint: 'search', autocapitalize: 'words', 'data-autofocus': '',
    });
    let mediaKind = defaultType === 'movie' ? 'any' : defaultType;
    const results = el('div');
    let timer = 0;
    let seq = 0;

    async function run() {
      const term = input.value.trim();
      if (term.length < 2) { results.replaceChildren(); return; }
      const mine = ++seq;
      results.replaceChildren(el('div.center-note', null, [el('div.spinner'), 'Searching...']));
      try {
        const data = await api('GET', `/lookup?q=${encodeURIComponent(term)}&type=${mediaKind}&limit=12`);
        if (mine !== seq) return;
        results.replaceChildren();
        if (!data.results.length) {
          results.append(el('p.hint', { text: 'No matches - try "By hand".' }));
          return;
        }
        for (const row of data.results) {
          const add = el('button.btn.sm.primary', { type: 'button' }, [icon('plus')]);
          add.addEventListener('click', () => {
            const created = addItem({
              title: row.title,
              year: row.year || null,
              type: row.type || defaultType,
              poster: row.poster || '',
              overview: row.overview || '',
              genres: row.genres || [],
              runtime: row.runtime || null,
              creator: row.creator || '',
              source: row.source || '',
              sourceId: row.sourceId || '',
              imdbId: row.imdbId || '',
              extRating: row.extRating || null,
              links: row.link ? [{ label: hostOf(row.link), url: row.link }] : [],
            });
            add.replaceChildren(icon('check'));
            add.disabled = true;
            onDone();
            toast(`Added "${created.title}"`, {
              action: { label: 'Edit', fn: () => openItem(created, { onChange: onDone, onDeleted: onDone }) },
            });
          });

          results.append(el('div.result', null, [
            row.poster ? el('img', { src: row.poster, alt: '', loading: 'lazy' }) : el('img', { alt: '' }),
            el('div.result-body', null, [
              el('h4', { text: row.title }),
              el('div.card-meta', null, [
                row.year ? el('span', { text: String(row.year) }) : null,
                el('span.tag-badge.type', { text: TYPE_LABEL[row.type] || row.type }),
                row.source ? el('span', { text: row.source }) : null,
              ]),
              row.overview ? el('p', { text: row.overview }) : null,
            ]),
            add,
          ]));
        }
      } catch (err) {
        if (mine !== seq) return;
        results.replaceChildren(el('p.hint', {
          text: `Lookup unavailable (${err.message}). Use "By hand" - everything still works offline.`,
        }));
      }
    }

    input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(run, 350); });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); run(); } });

    wrap.append(
      field('Title', input),
      field('Where to look', segmented(LOOKUP_KINDS, mediaKind, (v) => { mediaKind = v; run(); })),
      results,
    );
    return wrap;
  }

  function manualPanel() {
    const wrap = el('div');
    const draft = { type: defaultType, status: 'queue' };
    const title = el('input.input', { type: 'text', placeholder: 'Title', 'data-autofocus': '' });
    const year = el('input.input', { type: 'number', inputmode: 'numeric', placeholder: 'Year' });
    const link = el('input.input', { type: 'url', placeholder: 'https://... (optional)' });
    const tags = el('input.input', { type: 'text', placeholder: 'tags, comma separated', autocapitalize: 'none' });

    wrap.append(
      field('Title', title),
      el('div.row', null, [
        field('Year', year),
        field('Type', select(TYPES, draft.type, (v) => { draft.type = v; })),
      ]),
      field('Status', segmented(STATUSES, draft.status, (v) => { draft.status = v; })),
      field('Link', link),
      field('Tags', tags),
    );

    const save = el('button.btn.primary.grow', { type: 'button', text: 'Add to library' });
    const saveAndNext = el('button.btn.ghost', { type: 'button', text: 'Add & keep going' });

    const commit = () => {
      const name = title.value.trim();
      if (!name) { toast('A title is needed', { error: true }); return null; }
      const created = addItem({
        title: name,
        year: Number(year.value) || null,
        type: draft.type,
        status: draft.status,
        watchedAt: draft.status === 'watched' ? nowISO() : null,
        links: /^https?:\/\//i.test(link.value.trim())
          ? [{ label: hostOf(link.value.trim()), url: link.value.trim() }] : [],
        tags: tags.value.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean),
      });
      onDone();
      return created;
    };

    save.addEventListener('click', () => {
      const created = commit();
      if (created) { handle.close(); toast(`Added "${created.title}"`); }
    });
    saveAndNext.addEventListener('click', () => {
      const created = commit();
      if (!created) return;
      title.value = '';
      year.value = '';
      link.value = '';
      title.focus();
      toast(`Added "${created.title}"`);
    });

    wrap.append(el('div.row', null, [saveAndNext, save]));
    return wrap;
  }

  function pastePanel() {
    const wrap = el('div', null, [
      el('p.hint', {
        text: 'Paste a whole list at once - a Google Docs export, a CSV, or a JSON backup from here. '
            + 'Year headings, checkboxes and indented links are all understood.',
      }),
    ]);
    const go = el('button.btn.primary.grow', { type: 'button', text: 'Open the importer' });
    go.addEventListener('click', () => { handle.close(); openPortingSheet(onDone, 'import'); });
    wrap.append(el('div.field', null, [go]));
    return wrap;
  }

  body.append(tabs, panel);
  draw();
  const handle = openSheet({ title: 'Add to the library', body });
  return handle;
}
