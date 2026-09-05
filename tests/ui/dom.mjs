/* Enough of a DOM to build the app's nodes and fire its handlers.
 *
 * There is no browser on this machine and no jsdom to install, but the front
 * end is plain DOM calls with no framework, so a couple of dozen lines of
 * shim are enough to run the real ui.js against and drive a panel end to end.
 * Nodes remember their children, their classes and their listeners; `find`
 * walks the tree and `fire` dispatches, which is all a test needs. */
class N {
  constructor(tag, ns) {
    this.tagName = (tag || '').toUpperCase(); this.ns = ns || null;
    this.children = []; this.attrs = {}; this.handlers = {};
    this.style = { setProperty(){}, removeProperty(){} };
    this.dataset = {}; this.classList = new Set();
    this._text = '';
  }
  get className(){ return [...this.classList].join(' '); }
  set className(v){ this.classList = new Set(String(v || '').split(/\s+/).filter(Boolean)); }
  appendChild(n){ if(n){ n.parent = this; this.children.push(n); } return n; }
  append(...kids){ for (const k of kids.flat(9)) { if (k === null || k === undefined || k === false) continue; if (k instanceof N) k.parent = this; this.children.push(k); } }
  replaceChildren(...kids){ this.children = []; this.append(...kids); }
  remove(){ const p = this.parent; if (p) p.children = p.children.filter((k) => k !== this); }
  setAttribute(k,v){ this.attrs[k] = String(v); }
  getAttribute(k){ return this.attrs[k] ?? null; }
  removeAttribute(k){ delete this.attrs[k]; }
  addEventListener(ev, fn){ (this.handlers[ev] ||= []).push(fn); }
  removeEventListener(){}
  querySelector(){ return null; }
  querySelectorAll(){ return []; }
  focus(){}
  contains(){ return false; }
  get firstChild(){ return this.children[0] || null; }
  get textContent(){ return this._text; }
  set textContent(v){ this._text = String(v ?? ''); this.children = []; }
  // A real element has these as properties, so `el()` assigns them rather
  // than calling setAttribute. The shim has to agree or tests read the wrong
  // one back.
  get src(){ return this._src ?? this.attrs.src ?? ''; }
  set src(v){ this._src = String(v); }
  get href(){ return this._href ?? this.attrs.href ?? ''; }
  set href(v){ this._href = String(v); }
  get value(){ return this._value ?? ''; }
  set value(v){ this._value = v; }
  get checked(){ return !!this._checked; }
  set checked(v){ this._checked = !!v; }
  fire(ev, detail){ for (const fn of this.handlers[ev] || []) fn({ preventDefault(){}, stopPropagation(){}, key: (detail||{}).key, ...detail }); }
  find(pred, out = []) {
    if (pred(this)) out.push(this);
    for (const k of this.children) if (k instanceof N) k.find(pred, out);
    return out;
  }
  text(){ let s = this._text; for (const k of this.children) if (k instanceof N) s += ' ' + k.text(); return s.trim(); }
}
const doc = {
  createElement: (t) => new N(t),
  createElementNS: (ns, t) => new N(t, ns),
  createTextNode: (t) => { const n = new N('#text'); n._text = t; return n; },
  createDocumentFragment: () => new N('#fragment'),
  body: new N('body'), documentElement: new N('html'),
  addEventListener(){}, removeEventListener(){},
  querySelector(){ return null; }, querySelectorAll(){ return []; },
  _byId: {},
  getElementById(id){ return (this._byId[id] ||= new N('div')); },
  activeElement: null,
};
globalThis.document = doc;
globalThis.window = { addEventListener(){}, removeEventListener(){}, matchMedia: () => ({ matches:false, addEventListener(){} }), confirm: () => true, location: { href:'/', search:'' }, setTimeout, clearTimeout };
globalThis.localStorage = { _d:{}, getItem(k){ return this._d[k] ?? null; }, setItem(k,v){ this._d[k]=String(v); }, removeItem(k){ delete this._d[k]; }, key(i){ return Object.keys(this._d)[i] ?? null; }, get length(){ return Object.keys(this._d).length; } };
try { Object.defineProperty(globalThis, 'navigator', { value: { clipboard: null, onLine: true }, configurable: true }); } catch { /* node supplies one */ }
if (!globalThis.crypto) Object.defineProperty(globalThis, 'crypto', { value: { randomUUID: () => Math.random().toString(16).slice(2).padEnd(32,'0') }, configurable: true });
globalThis.addEventListener = () => {};
globalThis.removeEventListener = () => {};
globalThis.Node = N;
globalThis.HTMLElement = N;
globalThis.SVGElement = N;
export { N };
