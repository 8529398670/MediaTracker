/* Tiny DOM helpers plus the sheet / toast machinery.
 * No innerHTML anywhere: every node is built, so user data can never
 * become markup. (The CSP would stop scripts, but this stops the rest.) */

const SVG_NS = 'http://www.w3.org/2000/svg';

/* This was called Halo. Carry anything it saved in this browser over to the
 * new names once, so a rename does not cost you your collapsed sections,
 * your theme or the list you had open. Runs before anything reads them:
 * every module that touches storage imports this one. */
try {
  for (const old of Object.keys(localStorage)) {
    if (!old.startsWith('halo.')) continue;
    const renamed = `mt.${old.slice(5)}`;
    if (localStorage.getItem(renamed) === null) {
      localStorage.setItem(renamed, localStorage.getItem(old));
    }
    localStorage.removeItem(old);
  }
} catch { /* private mode, or storage is disabled — nothing to carry over */ }

/** el('div.card', {onclick}, [children]) — tag may carry .classes and #id. */
export function el(spec, props = null, children = null) {
  const [tagPart, ...classes] = String(spec).split('.');
  const [tag, id] = tagPart.split('#');
  const node = document.createElement(tag || 'div');
  if (id) node.id = id;
  if (classes.length) node.className = classes.join(' ');

  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className += (node.className ? ' ' : '') + value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'dataset') Object.assign(node.dataset, value);
      else if (key === 'style') for (const [k, v] of Object.entries(value)) node.style.setProperty(k, v);
      else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2), value);
      else if (key in node && typeof node[key] !== 'object') node[key] = value;
      else node.setAttribute(key, value === true ? '' : value);
    }
  }
  append(node, children);
  return node;
}

export function append(parent, children) {
  if (children === null || children === undefined || children === false) return parent;
  if (Array.isArray(children)) { children.forEach((c) => append(parent, c)); return parent; }
  parent.append(children instanceof Node ? children : document.createTextNode(String(children)));
  return parent;
}

export function icon(name, cls = 'ico') {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', `#i-${name}`);
  svg.append(use);
  return svg;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function clear(node) { while (node.firstChild) node.firstChild.remove(); return node; }

/** Like replaceChildren, but nulls are dropped instead of becoming "null". */
export function setChildren(node, children) { return append(clear(node), children); }

/* --------------------------------------------------------------- formatting */

export function fmtDate(iso, { time = false } = {}) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(+date)) return '';
  const opts = { year: 'numeric', month: 'short', day: 'numeric' };
  if (time) { opts.hour = 'numeric'; opts.minute = '2-digit'; }
  return date.toLocaleDateString(undefined, opts);
}

export function fmtAgo(iso) {
  if (!iso) return '';
  const then = new Date(iso);
  if (Number.isNaN(+then)) return '';
  const secs = (Date.now() - then.getTime()) / 1000;
  const table = [
    [60, 'second', 1], [3600, 'minute', 60], [86400, 'hour', 3600],
    [2592000, 'day', 86400], [31536000, 'month', 2592000], [Infinity, 'year', 31536000],
  ];
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  for (const [limit, unit, div] of table) {
    if (Math.abs(secs) < limit) return rtf.format(-Math.round(secs / div), unit);
  }
  return '';
}

/** dateFor(<input type=date>) — an ISO stamp anchored at local midday. */
export function dateInputToISO(value) {
  if (!value) return null;
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(+date) ? null : date.toISOString().replace(/\.\d+Z$/, 'Z');
}

export function isoToDateInput(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(+date)) return '';
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
}

/* ------------------------------------------------------------------ sheets */

const host = () => document.getElementById('sheet-host');
const stack = [];

export function openSheet({ title, body, footer, onClose, wide = false }) {
  const root = host();
  const sheet = el('div.sheet');
  if (wide) sheet.style.setProperty('max-width', '820px');

  sheet.append(el('div.sheet-grip'));

  const head = el('div.sheet-head', null, [
    el('h2', { text: title || '' }),
  ]);
  const closeBtn = el('button.icon-btn', { type: 'button', 'aria-label': 'Close' }, icon('x'));
  closeBtn.addEventListener('click', () => close(handle));
  head.append(closeBtn);

  const bodyNode = el('div.sheet-body');
  append(bodyNode, body);

  sheet.append(head, bodyNode);
  if (footer) {
    const foot = el('div.sheet-foot');
    append(foot, footer);
    sheet.append(foot);
  }

  const handle = { node: sheet, body: bodyNode, onClose, close: () => close(handle) };
  stack.push(handle);
  root.hidden = false;
  clear(root).append(sheet);
  document.body.style.setProperty('overflow', 'hidden');

  // Focus the first meaningful control, but never a text input on mobile
  // (an unexpected keyboard eats half the screen).
  const first = sheet.querySelector('[data-autofocus]');
  if (first) setTimeout(() => first.focus(), 60);

  return handle;
}

function close(handle) {
  const index = stack.indexOf(handle);
  if (index === -1) return;
  stack.splice(index, 1);
  if (handle.onClose) { try { handle.onClose(); } catch { /* ignore */ } }
  const root = host();
  if (stack.length) {
    clear(root).append(stack[stack.length - 1].node);
  } else {
    clear(root);
    root.hidden = true;
    document.body.style.removeProperty('overflow');
  }
}

export function closeTop() { if (stack.length) close(stack[stack.length - 1]); }
export function closeAll() { while (stack.length) close(stack[stack.length - 1]); }

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && stack.length) { event.preventDefault(); closeTop(); }
});

document.addEventListener('click', (event) => {
  if (event.target === host() && stack.length) closeTop();
});

/* ------------------------------------------------------------------ toasts */

export function toast(message, { action, error = false, ms = 4200 } = {}) {
  const root = document.getElementById('toast-host');
  const node = el('div.toast', { class: error ? 'err' : '' }, el('span', { text: message }));
  let timer = 0;
  const dismiss = () => { clearTimeout(timer); node.remove(); };

  if (action) {
    node.append(el('button', {
      type: 'button',
      text: action.label,
      onclick: () => { dismiss(); action.fn(); },
    }));
  }
  root.append(node);
  timer = setTimeout(dismiss, ms);
  while (root.children.length > 3) root.firstChild.remove();
  return dismiss;
}

/* ----------------------------------------------------------------- confirm */

/* `detail` is a list of lines under the message — the titles a change is
 * about to touch, so what is being agreed to is in front of you. */
export function confirmSheet({
  title, message, detail = null, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false,
}) {
  return new Promise((resolve) => {
    let answered = false;
    const finish = (value) => { if (!answered) { answered = true; resolve(value); } };

    const cancel = el('button.btn.ghost.grow', { type: 'button', text: cancelLabel });
    const ok = el('button.btn.grow', {
      type: 'button',
      text: confirmLabel,
      class: danger ? 'danger' : 'primary',
      'data-autofocus': '',
    });

    const handle = openSheet({
      title,
      body: el('div', null, [
        el('p', { text: message, style: { margin: '4px 0 8px', color: 'var(--text-2)' } }),
        detail && detail.length
          ? el('ul.confirm-list', null, detail.map((line) => el('li', { text: line })))
          : null,
      ]),
      footer: [cancel, ok],
      onClose: () => finish(false),
    });

    cancel.addEventListener('click', () => { finish(false); handle.close(); });
    ok.addEventListener('click', () => { finish(true); handle.close(); });
  });
}

/* ------------------------------------------------------------------ inputs */

export function field(label, control, hint) {
  return el('div.field', null, [
    el('label.field-label', { text: label }),
    control,
    hint ? el('p.hint', { text: hint }) : null,
  ]);
}

export function segmented(options, value, onPick) {
  const box = el('div.seg');
  for (const option of options) {
    const button = el('button', {
      type: 'button',
      text: option.label,
      'aria-pressed': String(option.id === value),
      onclick: () => {
        [...box.children].forEach((c) => c.setAttribute('aria-pressed', 'false'));
        button.setAttribute('aria-pressed', 'true');
        onPick(option.id);
      },
    });
    box.append(button);
  }
  return box;
}

export function select(options, value, onPick, { label } = {}) {
  const node = el('select.input', { 'aria-label': label || '' });
  for (const option of options) {
    node.append(el('option', { value: option.id, text: option.label, selected: option.id === value }));
  }
  node.addEventListener('change', () => onPick(node.value));
  return node;
}

/** A file download that works inside the sandboxed viewer and on iOS Safari. */
export function download(filename, text, mime = 'application/json') {
  const blob = new Blob([text], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const link = el('a', { href: url, download: filename });
  document.body.append(link);
  link.click();
  setTimeout(() => { link.remove(); URL.revokeObjectURL(url); }, 4000);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // No clipboard API outside https, which is the app on its LAN address.
    // The old way still works there.
    try {
      const area = el('textarea', {
        value: text, readOnly: true, 'aria-hidden': 'true',
        style: { position: 'fixed', top: '0', left: '0', opacity: '0' },
      });
      document.body.append(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      return ok;
    } catch {
      return false;
    }
  }
}
