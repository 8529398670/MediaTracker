/* Rendering: stat strip, year sections, and the item cards themselves. */

import { TYPE_LABEL, STATUS_LABEL } from './store.js';
import { el, icon, clear, fmtAgo, hostOf } from './ui.js';

const COLLAPSE_KEY = 'mt.collapsed.v1';

function readCollapsed() {
  try { return new Set(JSON.parse(localStorage.getItem(COLLAPSE_KEY) || '[]')); }
  catch { return new Set(); }
}
const collapsed = readCollapsed();

function saveCollapsed() {
  try { localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...collapsed])); } catch { /* ignore */ }
}

/* ------------------------------------------------------------------- stats */

export function renderStats(node, s, shown) {
  clear(node);
  if (!s.total) { node.hidden = true; return; }
  node.hidden = false;

  const cell = (label, value) => el('span', null, [el('b', { text: String(value) }), ` ${label}`]);

  node.append(cell('tracked', s.total));
  if (shown !== s.total) node.append(cell('shown', shown));
  node.append(cell('in queue', s.queue));
  node.append(cell('watched', s.watched));
  if (s.watching) node.append(cell('watching', s.watching));
  if (s.hearts) node.append(cell('loved', s.hearts));
  if (s.rated) node.append(el('span', null, [el('b', { text: s.avg.toFixed(1) }), ' avg rating']));
}

/* -------------------------------------------------------------------- card */

export function card(item, on) {
  const node = el('article.card', { dataset: { id: item.id } });
  if (item.status === 'watched') node.classList.add('is-watched');
  if (item.status === 'dropped') node.classList.add('is-dropped');
  if (item.heart) node.classList.add('is-loved');

  /* poster */
  const poster = el('button.card-poster', {
    type: 'button',
    'aria-label': `Open ${item.title}`,
    onclick: () => on.open(item),
  });
  if (item.poster) {
    poster.append(el('img', {
      src: item.poster, alt: '', loading: 'lazy', decoding: 'async',
      onerror: (event) => { event.target.remove(); poster.append(placeholder(item)); },
    }));
  } else {
    poster.append(placeholder(item));
  }

  /* body */
  const title = el('h3.card-title', null, [
    item.title || 'Untitled',
    ' ',
    yearControl(item, on),
  ]);

  const meta = el('div.card-meta', null, [
    el('span.tag-badge.type', { text: TYPE_LABEL[item.type] || item.type }),
    item.status !== 'queue'
      ? el('span', { class: `tag-badge st-${item.status}`, text: STATUS_LABEL[item.status] })
      : null,
    item.status === 'watched' && item.watchedAt
      ? el('span', { text: `watched ${fmtAgo(item.watchedAt)}` })
      : el('span', { text: `added ${fmtAgo(item.addedAt)}` }),
    item.certification ? el('span.tag-badge.cert', { text: item.certification }) : null,
    ...item.tags.slice(0, 3).map((tag) => el('span.tag-badge', {
      text: `#${tag}`,
      onclick: (event) => { event.stopPropagation(); on.tag(tag); },
    })),
    item.runtime ? el('span', { text: `${item.runtime}m` }) : null,
  ]);

  const people = (item.cast || []).slice(0, 3).join(', ');
  const billing = people ? el('div.card-cast', { text: people }) : null;

  const tap = el('div.card-tap', {
    role: 'button',
    tabindex: '0',
    'aria-label': `Open ${item.title}`,
    onclick: (event) => { if (!event.target.closest('.yr-edit')) on.open(item); },
    onkeydown: (event) => {
      if (event.target !== tap) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); on.open(item); }
    },
  }, [title, meta]);

  const wrap = el('div.card-body', null, [tap, billing]);
  const refs = refLinks(item);
  if (item.links.length || refs) {
    wrap.append(el('div.card-links', null, [
      ...item.links.slice(0, 2).map((link) => el('a.link-chip', {
        href: link.url, target: '_blank', rel: 'noopener noreferrer',
        onclick: (event) => event.stopPropagation(),
      }, [icon('link'), link.label || hostOf(link.url)])),
      refs,
    ]));
  }

  /* side actions */
  const heart = el('button.act.heart', {
    type: 'button',
    class: item.heart ? 'on' : '',
    'aria-pressed': String(!!item.heart),
    'aria-label': item.heart ? 'Remove from loved' : 'Mark as loved',
    onclick: () => on.heart(item),
  }, icon(item.heart ? 'heart-fill' : 'heart'));

  const rate = el('button.act.rate', {
    type: 'button',
    class: item.rating ? '' : 'unrated',
    text: item.rating ? String(item.rating) : '–',
    'aria-label': item.rating ? `Rated ${item.rating} of 10` : 'Set a rating',
    onclick: () => on.rate(item),
  });

  const check = el('button.act.check', {
    type: 'button',
    class: item.status === 'watched' ? 'on' : '',
    'aria-pressed': String(item.status === 'watched'),
    'aria-label': item.status === 'watched' ? 'Mark as not watched' : 'Mark as watched',
    onclick: () => on.watched(item),
  }, item.status === 'watched' ? icon('check') : null);

  node.append(poster, wrap, el('div.card-side', null, [heart, rate, check]));
  return node;
}

/* ---------------------------------------------------------- year control

   The year sits on the card and is edited there. Tap it, type a year, press
   enter — the card leaves its old section and turns up under the new one.
   Nothing in the library is more often missing, so `year?` is a target you
   can hit rather than a blank you have to open a sheet to fill. */

function yearControl(item, on) {
  const node = el('span.yr-edit', {
    role: 'button',
    tabindex: '0',
    class: item.year ? '' : 'missing',
    text: item.year ? String(item.year) : 'year?',
    'aria-label': item.year ? `Year ${item.year} — change it` : `Add a year to ${item.title}`,
  });

  const edit = () => {
    const input = el('input.yr-input', {
      type: 'number', inputmode: 'numeric', placeholder: 'year',
      min: '1870', max: '2200', value: item.year || '',
      'aria-label': `Year for ${item.title}`,
    });

    let settled = false;
    const finish = (commit) => {
      if (settled) return;
      settled = true;
      const raw = input.value.trim();
      const year = raw === '' ? null : Number(raw);
      input.replaceWith(node);
      if (!commit) return;
      if (year !== null && (!Number.isFinite(year) || year < 1870 || year > 2200)) return;
      if (year === (item.year || null)) return;
      on.year(item, year);
    };

    input.addEventListener('keydown', (event) => {
      event.stopPropagation();
      if (event.key === 'Enter') { event.preventDefault(); finish(true); }
      else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', () => finish(true));
    input.addEventListener('click', (event) => event.stopPropagation());

    node.replaceWith(input);
    input.focus();
    input.select();
  };

  node.addEventListener('click', (event) => { event.stopPropagation(); edit(); });
  node.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    event.stopPropagation();
    edit();
  });
  return node;
}

/* ------------------------------------------------------------- reference

   Three places you actually go when deciding what to watch. Two of them cost
   nothing to work out — IMDb from the id enrichment already found, JustWatch
   from the title, since they have no public API and their search URL always
   resolves. Wikipedia is the page enrichment identified, so it is the right
   article rather than a guess at the slug. */

export function justWatchUrl(item) {
  return 'https://www.justwatch.com/us/search?q=' + encodeURIComponent(item.title || '');
}

const REFS = [
  {
    id: 'imdb',
    icon: 'imdb',
    label: 'IMDb',
    hint: (item) => `${item.title} on IMDb`,
    url: (item) => (item.imdbId ? `https://www.imdb.com/title/${item.imdbId}/` : ''),
  },
  {
    id: 'wiki',
    icon: 'wiki',
    label: 'Wikipedia',
    hint: (item) => `${item.title} on Wikipedia`,
    url: (item) => item.wikiUrl || '',
  },
  {
    id: 'watch',
    icon: 'play',
    label: 'Where to watch',
    hint: (item) => `Where to watch ${item.title}`,
    url: (item) => (item.title ? justWatchUrl(item) : ''),
  },
];

/** The little row of icons. Empty when a title has nothing to point at. */
export function refLinks(item) {
  const chips = [];
  for (const ref of REFS) {
    const url = ref.url(item);
    if (!url) continue;
    chips.push(el('a', {
      class: `ref ref-${ref.id}`,
      href: url,
      target: '_blank',
      rel: 'noopener noreferrer',
      title: ref.hint(item),
      'aria-label': ref.hint(item),
      // The card behind this is itself a button; the tap stops here.
      onclick: (event) => event.stopPropagation(),
    }, icon(ref.icon)));
  }
  return chips.length ? el('div.card-refs', null, chips) : null;
}

function placeholder(item) {
  return el('span', { text: (item.title || '?').trim().slice(0, 2).toUpperCase() });
}

/* ------------------------------------------------------------------ groups */

/* A thousand cards is ~380ms of DOM building, which is far too much to spend
 * on every keystroke. So: sections go in immediately, cards stream in on a
 * time budget, a newer render cancels the one in flight, and collapsed
 * sections are not built at all until they are opened. */

let renderToken = 0;

export function renderGroups(root, groups, on) {
  const token = ++renderToken;
  const fragment = document.createDocumentFragment();
  const queue = [];

  for (const group of groups) {
    const section = el('section.group', { dataset: { key: group.key } });
    const isCollapsed = collapsed.has(group.key);
    if (isCollapsed) section.classList.add('collapsed');

    const list = el('div.group-items');

    if (group.label) {
      const head = el('button.group-head', {
        type: 'button',
        'aria-expanded': String(!isCollapsed),
      }, [
        el('h2', { text: group.label }),
        el('span.group-count', { text: String(group.items.length) }),
        icon('chevron', 'ico chev'),
      ]);
      head.addEventListener('click', () => {
        const nowCollapsed = !section.classList.contains('collapsed');
        section.classList.toggle('collapsed', nowCollapsed);
        head.setAttribute('aria-expanded', String(!nowCollapsed));
        if (nowCollapsed) collapsed.add(group.key); else collapsed.delete(group.key);
        saveCollapsed();
        // Opening a section that was never built: build it now.
        if (!nowCollapsed && !list.childElementCount && group.items.length) {
          for (const item of group.items) list.append(card(item, on));
        }
      });
      section.append(head);
    }

    section.append(list);
    fragment.append(section);
    if (!isCollapsed) queue.push([list, group.items]);
  }

  clear(root).append(fragment);

  let groupIndex = 0;
  let itemIndex = 0;

  /** Append cards until the budget runs out; true when everything is placed. */
  const fill = (budgetMs) => {
    const start = performance.now();
    while (groupIndex < queue.length) {
      const [list, items] = queue[groupIndex];
      while (itemIndex < items.length) {
        list.append(card(items[itemIndex], on));
        itemIndex += 1;
        if (itemIndex % 16 === 0 && performance.now() - start > budgetMs) return false;
      }
      groupIndex += 1;
      itemIndex = 0;
    }
    return true;
  };

  if (fill(28)) return;                    // small library: all in one go

  const pump = () => {
    if (token !== renderToken) return;     // a newer render superseded this one
    if (fill(14)) return;
    setTimeout(pump, 0);
  };
  setTimeout(pump, 0);
}


/* ------------------------------------------------------------------- queue */

/* The queue is the one list kept in an order you chose, so it is drawn as
 * rows rather than cards: a position you can type into, a grip you can drag,
 * and the same three taps as everywhere else. */

function queueRow(item, index, on) {
  const row = el('div.qrow', { dataset: { id: item.id } });
  if (item.status === 'watching') row.classList.add('is-watching');
  if (item.heart) row.classList.add('is-loved');

  const pos = el('button.qpos', {
    type: 'button',
    text: String(index + 1),
    'aria-label': `Position ${index + 1} of ${item.title} — change it`,
    onclick: () => on.position(row),
  });

  const grip = el('span.qgrip', {
    'data-grip': '',
    role: 'button',
    tabindex: '0',
    'aria-label': `Reorder ${item.title}`,
    title: 'Drag to reorder',
  }, icon('grip'));

  const title = el('span.qtitle', null, [
    item.title || 'Untitled',
    ' ',
    yearControl(item, on),
  ]);

  const meta = el('span.qmeta', null, [
    item.status === 'watching' ? el('span.tag-badge.st-watching', { text: 'Watching' }) : null,
    ...item.tags.slice(0, 2).map((tag) => el('span.tag-badge', {
      text: `#${tag}`,
      onclick: (event) => { event.stopPropagation(); on.tag(tag); },
    })),
    item.links.length ? el('span.qlinks', null, [icon('link'), String(item.links.length)]) : null,
    refLinks(item),
  ]);

  const tap = el('div.qtap', {
    role: 'button',
    tabindex: '0',
    'aria-label': `Open ${item.title}`,
    onclick: (event) => { if (!event.target.closest('.yr-edit')) on.open(item); },
    onkeydown: (event) => {
      if (event.target !== tap) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); on.open(item); }
    },
  }, [title, meta]);

  const heart = el('button.act.heart', {
    type: 'button',
    class: item.heart ? 'on' : '',
    'aria-pressed': String(!!item.heart),
    'aria-label': item.heart ? 'Remove from loved' : 'Mark as loved',
    onclick: () => on.heart(item),
  }, icon(item.heart ? 'heart-fill' : 'heart'));

  const check = el('button.act.check', {
    type: 'button',
    'aria-label': `Mark ${item.title} as watched`,
    onclick: () => on.watched(item),
  });

  row.append(pos, grip, tap, el('div.qside', null, [heart, check]));
  return row;
}

/** Renumber the position buttons after a drag or a jump. */
function renumber(list) {
  let n = 0;
  for (const row of list.children) {
    if (!row.dataset || !row.dataset.id) continue;
    n += 1;
    const pos = row.querySelector('.qpos');
    if (pos) {
      pos.textContent = String(n);
      pos.setAttribute('aria-label', `Position ${n} — change it`);
    }
  }
}

export function renderQueue(root, items, on) {
  clear(root);
  const list = el('div.qlist');
  items.forEach((item, index) => list.append(queueRow(item, index, on)));
  root.append(list);

  const ids = () => [...list.children]
    .filter((row) => row.dataset && row.dataset.id)
    .map((row) => row.dataset.id);

  makeSortable(list, {
    onMove: () => renumber(list),
    onCommit: () => on.reorder(ids()),
  });

  // Tapping the number turns it into a box you type the new position into.
  on.position = (row) => {
    const pos = row.querySelector('.qpos');
    if (!pos) return;
    const total = ids().length;
    const from = Number(pos.textContent);
    const input = el('input.qpos-input', {
      type: 'number', inputmode: 'numeric', min: '1', max: String(total),
      value: String(from), 'aria-label': `Move to position, 1 to ${total}`,
    });

    let settled = false;
    const finish = (commit) => {
      if (settled) return;
      settled = true;
      const wanted = Number(input.value);
      input.replaceWith(pos);
      if (!commit || !Number.isFinite(wanted) || wanted === from) return;
      const clamped = Math.max(1, Math.min(total, Math.round(wanted)));
      if (clamped === from) return;
      on.jump(row.dataset.id, clamped);
    };

    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); finish(true); }
      else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', () => finish(true));

    pos.replaceWith(input);
    input.focus();
    input.select();
  };

  return list;
}

/* --------------------------------------------------------------- sortable */

/* Pointer events rather than HTML5 drag-and-drop: the same code then works
 * for a finger and a mouse, and `touch-action: none` on the grip is what
 * stops the page scrolling out from under a drag. */

export function makeSortable(list, { onMove, onCommit }) {
  let row = null;
  let grip = null;
  let pointerId = null;
  let startY = 0;
  let lastY = 0;
  let scrolling = 0;

  const rows = () => [...list.children].filter((n) => n.dataset && n.dataset.id);
  const place = (y) => row.style.setProperty('transform', `translateY(${y - startY}px)`);

  function reposition(clientY) {
    const dragged = row.getBoundingClientRect();
    const middle = dragged.top + dragged.height / 2;
    for (const other of rows()) {
      if (other === row) continue;
      const rect = other.getBoundingClientRect();
      if (middle < rect.top || middle > rect.bottom) continue;
      const target = middle < rect.top + rect.height / 2 ? other : other.nextElementSibling;
      if (target === row) return;
      // Move the node, then shift the origin so it does not visibly jump.
      row.style.removeProperty('transform');
      const was = row.getBoundingClientRect().top;
      list.insertBefore(row, target);
      startY += row.getBoundingClientRect().top - was;
      place(clientY);
      if (onMove) onMove();
      return;
    }
  }

  /* Dragging to the top or bottom of the screen keeps the list moving. */
  function edgeScroll() {
    scrolling = 0;
    if (!row) return;
    const top = 140;
    const bottom = window.innerHeight - 110;
    const speed = lastY < top ? -Math.ceil((top - lastY) / 5)
      : lastY > bottom ? Math.ceil((lastY - bottom) / 5) : 0;
    if (!speed) return;
    const before = window.scrollY;
    window.scrollBy(0, speed);
    const moved = window.scrollY - before;
    if (moved) {
      startY -= moved;
      place(lastY);
      reposition(lastY);
    }
    scrolling = requestAnimationFrame(edgeScroll);
  }

  list.addEventListener('pointerdown', (event) => {
    if (event.button > 0) return;
    const handle = event.target.closest('[data-grip]');
    if (!handle) return;
    const candidate = handle.closest('.qrow');
    if (!candidate) return;
    event.preventDefault();
    row = candidate;
    grip = handle;
    pointerId = event.pointerId;
    startY = event.clientY;
    lastY = event.clientY;
    row.classList.add('dragging');
    list.classList.add('is-sorting');
    try { handle.setPointerCapture(pointerId); } catch { /* older browser */ }
  });

  list.addEventListener('pointermove', (event) => {
    if (!row || event.pointerId !== pointerId) return;
    event.preventDefault();
    lastY = event.clientY;
    place(lastY);
    reposition(lastY);
    if (!scrolling) scrolling = requestAnimationFrame(edgeScroll);
  });

  const drop = (event) => {
    if (!row || (event && event.pointerId !== pointerId)) return;
    cancelAnimationFrame(scrolling);
    scrolling = 0;
    row.style.removeProperty('transform');
    row.classList.remove('dragging');
    list.classList.remove('is-sorting');
    try { grip.releasePointerCapture(pointerId); } catch { /* already gone */ }
    row = null;
    grip = null;
    pointerId = null;
    if (onCommit) onCommit();
  };

  list.addEventListener('pointerup', drop);
  list.addEventListener('pointercancel', drop);

  // Keyboard: the grip moves a row with the arrow keys.
  list.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
    const handle = event.target.closest('[data-grip]');
    if (!handle) return;
    const node = handle.closest('.qrow');
    const order = rows();
    const at = order.indexOf(node);
    const to = event.key === 'ArrowUp' ? at - 1 : at + 1;
    if (at === -1 || to < 0 || to >= order.length) return;
    event.preventDefault();
    list.insertBefore(node, event.key === 'ArrowUp' ? order[to] : order[to].nextElementSibling);
    if (onMove) onMove();
    if (onCommit) onCommit();
    handle.focus();
  });
}

const EMPTY_COPY = {
  list:    ['Nothing here yet', 'This part of the library is empty.'],
  queue:   ['The queue is empty', 'Anything not yet watched turns up here, in the order you put it.'],
  watched: ['Nothing watched yet', 'Tick a title off and it moves here.'],
};

/* --------------------------------------------------------------- year map

   A rail down the right-hand side listing every section in the list — years,
   usually — so a library that runs from 1927 to now is one tap deep instead
   of a long scroll. It scrolls on its own, and follows along as you move
   through the list. */

let mapObserver = null;

export function renderYearMap(node, groups, { onJump }) {
  if (mapObserver) { mapObserver.disconnect(); mapObserver = null; }
  clear(node);

  const labelled = groups.filter((g) => g.label);
  if (labelled.length < 3) { node.hidden = true; return false; }
  node.hidden = false;

  const buttons = new Map();
  for (const group of labelled) {
    const button = el('button.ym-item', {
      type: 'button',
      dataset: { key: group.key, label: group.label },
      title: `${group.label} — ${group.items.length}`,
      'aria-label': `Jump to ${group.label}, ${group.items.length} titles`,
      onclick: () => onJump(group.key),
    }, [
      el('span.ym-label', { text: group.label }),
      el('span.ym-dot', { style: { '--n': String(Math.min(group.items.length, 24)) } }),
    ]);
    // Decades get a heavier tick, so a rail of bare marks still reads.
    if (/^(?:18|19|20)\d0$/.test(group.key)) button.classList.add('decade');
    buttons.set(group.key, button);
    node.append(button);
  }

  /* Which section you are actually looking at. An observer rather than a
     scroll handler: sections collapse and open, so measured offsets go stale
     the moment you touch one. */
  const order = labelled.map((g) => g.key);
  const onScreen = new Set();
  let current = '';

  const mark = () => {
    const next = order.find((key) => onScreen.has(key)) || current;
    if (next === current) return;
    const was = buttons.get(current);
    if (was) was.classList.remove('here');
    current = next;
    const now = buttons.get(current);
    if (!now) return;
    now.classList.add('here');
    // Keep the marker in view as the page moves — but never yank the rail
    // out from under a finger that is already dragging it.
    if (node.classList.contains('scrubbing') || node.matches(':hover')) return;
    const box = node.getBoundingClientRect();
    const pin = now.getBoundingClientRect();
    if (pin.top < box.top + 24 || pin.bottom > box.bottom - 24) {
      node.scrollTo({ top: now.offsetTop - node.clientHeight / 2, behavior: 'smooth' });
    }
  };

  // Following the list is a nicety. Somewhere without an observer still gets
  // a rail it can drag, so this must never be the thing that breaks the page.
  if (typeof IntersectionObserver !== 'function') return () => {};

  const top = parseInt(getComputedStyle(document.documentElement)
    .getPropertyValue('--top-h'), 10) || 104;

  mapObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      const key = entry.target.dataset.key;
      if (entry.isIntersecting) onScreen.add(key); else onScreen.delete(key);
    }
    mark();
  }, { rootMargin: `-${top + 4}px 0px -55% 0px`, threshold: 0 });

  return (root) => {
    for (const section of root.querySelectorAll('.group[data-key]')) mapObserver.observe(section);
  };
}

/* ------------------------------------------------------------- scrubbing

   Press anywhere on the rail and drag: the list follows the pointer the
   whole way down, so a hundred years is one gesture rather than a long
   scroll. Hovering shows where you would land without going there.

   Wired once — renderYearMap rebuilds the rail's children on every paint,
   and listeners bound here sit on the rail itself, so they survive that. */

export function wireYearMap(node, bubble, { onJump }) {
  let scrubbing = false;
  let frame = 0;
  let latestY = 0;
  let lastKey = '';

  /* Rows are identical in height, so the one under the pointer is arithmetic
     rather than a hundred rect reads a frame. Measured fresh each time: the
     rail scrolls under the finger, which moves every row. */
  const rowAt = (clientY) => {
    const rows = [...node.children].filter((row) => row.dataset && row.dataset.key);
    if (!rows.length) return null;
    const first = rows[0].getBoundingClientRect();
    const stride = rows.length > 1
      ? rows[1].getBoundingClientRect().top - first.top
      : first.height;
    if (!stride) return rows[0];
    const index = Math.floor((clientY - first.top) / stride);
    return rows[Math.max(0, Math.min(rows.length - 1, index))];
  };

  const showBubble = (row) => {
    if (!row) { bubble.hidden = true; return; }
    const box = row.getBoundingClientRect();
    bubble.textContent = row.dataset.label || row.dataset.key;
    bubble.style.setProperty('top', `${Math.round(box.top + box.height / 2)}px`);
    bubble.hidden = false;
  };

  /* Held at the top or bottom of the rail, the rail itself keeps moving, so
     a drag can reach years that are not currently on screen. */
  const EDGE = 26;
  const creep = (clientY) => {
    const box = node.getBoundingClientRect();
    let step = 0;
    if (clientY < box.top + EDGE) step = -Math.ceil((box.top + EDGE - clientY) / 2.5);
    else if (clientY > box.bottom - EDGE) step = Math.ceil((clientY - (box.bottom - EDGE)) / 2.5);
    if (step) node.scrollTop += step;
  };

  const settle = () => {
    const row = rowAt(latestY);
    if (!row) return;
    showBubble(row);
    if (row.dataset.key === lastKey) return;
    lastKey = row.dataset.key;
    // Instant, not smooth: a smooth scroll would still be catching up with
    // the last position while the finger is already somewhere else.
    onJump(row.dataset.key, { smooth: false });
  };

  const tick = () => {
    if (!scrubbing) { frame = 0; return; }
    creep(latestY);
    settle();
    frame = requestAnimationFrame(tick);
  };

  node.addEventListener('pointerdown', (event) => {
    if (event.button > 0) return;
    event.preventDefault();
    scrubbing = true;
    lastKey = '';
    latestY = event.clientY;
    node.classList.add('scrubbing');
    try { node.setPointerCapture(event.pointerId); } catch { /* older browser */ }
    settle();
    if (!frame) frame = requestAnimationFrame(tick);
  });

  node.addEventListener('pointermove', (event) => {
    latestY = event.clientY;
    if (scrubbing) { event.preventDefault(); return; }
    showBubble(rowAt(event.clientY));          // hover preview, no scrolling
  });

  const release = (event) => {
    if (!scrubbing) return;
    scrubbing = false;
    node.classList.remove('scrubbing');
    try { node.releasePointerCapture(event.pointerId); } catch { /* already gone */ }
    cancelAnimationFrame(frame);
    frame = 0;
    bubble.hidden = true;
  };
  node.addEventListener('pointerup', release);
  node.addEventListener('pointercancel', release);
  node.addEventListener('pointerleave', () => { if (!scrubbing) bubble.hidden = true; });
}

export function renderEmpty(node, {
  view = 'list', searching, filtered, elsewhere, onGo, onClear, onAdd,
}) {
  clear(node);
  node.hidden = false;

  // A hit in another list is worth pointing at rather than making you hunt.
  const pointer = elsewhere && onGo
    ? el('button.btn.ghost', {
        type: 'button',
        text: `${elsewhere.count} in ${elsewhere.label}`,
        onclick: () => onGo(elsewhere),
      })
    : null;

  if (searching || filtered) {
    node.append(
      el('h3', { text: 'Nothing matches' }),
      el('p', { text: searching ? 'Not in this list. Try fewer words, or clear the filters.'
                                : 'Nothing here passes the current filters.' }),
      el('div.chip-row', null, [
        pointer,
        el('button.btn.primary', { type: 'button', text: 'Clear filters', onclick: onClear }),
      ]),
    );
    return;
  }

  const [title, line] = EMPTY_COPY[view] || EMPTY_COPY.list;
  node.append(
    el('h3', { text: title }),
    el('p', { text: line }),
    el('div.chip-row', null, [
      pointer,
      el('button.btn.primary', { type: 'button', text: 'Add something', onclick: onAdd }),
    ]),
  );
}
