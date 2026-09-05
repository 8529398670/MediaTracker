/* The universal importer, driven the way a person drives it.
 *
 * The server is stubbed: what is under test is the panel — that a pasted link
 * becomes one row and one item with its artwork and ids intact, that a large
 * paste takes the bulk path instead of resolving line by line, that a result
 * the server is unsure about is offered rather than applied, and that the
 * same title twice does not become two.
 *
 *     ./tests/ui.sh
 */
import './dom.mjs';
const calls = [];
// Stand in for the network: the panel must never talk to a real provider here.
globalThis.fetch = async (url, init) => {
  calls.push(`${(init && init.method) || 'GET'} ${url}`);
  const body = url.includes('/resolve')
    ? {
        input: 'x', via: 'imdb-id', confident: true, query: 'Weather Girl', year: 2009,
        best: { title: 'Weather Girl', year: 2009, type: 'movie', poster: '/api/img?u=p',
                source: 'tmdb', sourceId: 'movie/19900', imdbId: 'tt1085515',
                cast: ['A'], overview: 'o', genres: ['Comedy'], link: 'https://x/y' },
        candidates: [{ title: 'Weather Girl', year: 2009, type: 'movie', poster: '/api/img?u=p' },
                     { title: 'Weather Girl', year: 2021, type: 'movie', poster: '' }],
        note: '',
      }
    : { ok: true };
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
};

const { universalPanel } = await import('./importer.js');
const store = await import('./store.js');
store.state.config = { network: true, providers: { tmdb: true } };

let doneCalls = 0;
const panel = universalPanel(() => { doneCalls += 1; }, { defaultType: 'movie' });

const areas = panel.find((n) => n.tagName === 'TEXTAREA');
if (areas.length !== 1) throw new Error(`expected one textarea, got ${areas.length}`);
const area = areas[0];

// --- a single pasted link ---
area.value = 'https://www.imdb.com/title/tt1085515/fullcredits/';
area.fire('paste');
await new Promise((r) => setTimeout(r, 250));

const rows = panel.find((n) => n.classList.has('result'));
if (rows.length !== 1) throw new Error(`expected one result row, got ${rows.length}`);
if (!rows[0].text().includes('Weather Girl')) throw new Error(`row text: ${rows[0].text()}`);

const buttons = panel.find((n) => n.tagName === 'BUTTON' && /^Add \d/.test(n.textContent));
if (!buttons.length) throw new Error('no Add button');
buttons[0].fire('click');
await new Promise((r) => setTimeout(r, 120));

const live = store.live();
if (live.length !== 1) throw new Error(`expected one item added, got ${live.length}`);
const added = live[0];
for (const [k, v] of Object.entries({ title: 'Weather Girl', year: 2009, type: 'movie',
                                      imdbId: 'tt1085515', poster: '/api/img?u=p' })) {
  if (added[k] !== v) throw new Error(`${k}: expected ${v}, got ${added[k]}`);
}
if (!added.links.length) throw new Error('the link it came from was not kept');
if (!doneCalls) throw new Error('onDone was never called');
if (!calls.some((c) => c.startsWith('POST /api/resolve'))) throw new Error('never called /api/resolve');
if (!calls.some((c) => c.includes('/api/enrich'))) console.log('note: no enrich kick (expected — nothing was left blank)');

// --- a bulk paste goes down the other path ---
const many = Array.from({ length: 60 }, (_, i) => `- [ ] Film ${i} (19${50 + (i % 40)})`).join('\n');
area.value = many;
area.fire('paste');
await new Promise((r) => setTimeout(r, 250));
const importBtn = panel.find((n) => n.tagName === 'BUTTON' && /^Import \d+ titles/.test(n.textContent));
if (!importBtn.length) throw new Error('a 60-line paste did not offer a bulk import');
const before = calls.length;
importBtn[0].fire('click');
await new Promise((r) => setTimeout(r, 200));
if (store.live().length < 60) throw new Error(`bulk import added ${store.live().length - 1}`);
if (!calls.slice(before).some((c) => c.includes('/api/enrich'))) throw new Error('bulk import did not start the fill-in pass');
if (calls.slice(before).some((c) => c.includes('/api/resolve'))) throw new Error('bulk import resolved line by line');

console.log(`ok — single link resolved and added, ${store.live().length - 1} bulk titles imported, fill-in pass started`);
console.log('   api calls:', calls.filter((c) => !c.includes('library')).slice(0, 6).join(' | '));

/* ---- a result the server is not sure about is offered, not applied ---- */
globalThis.fetch = async (url, init) => {
  calls.push(`${(init && init.method) || 'GET'} ${url}`);
  const body = url.includes('/resolve')
    ? {
        via: 'search', confident: false, query: 'Sunrise', year: null, best: null,
        note: 'more than one title matches — pick the right one',
        candidates: [
          { title: 'Sunrise', year: 1927, type: 'movie', poster: '/api/img?u=a', creator: 'F. W. Murnau' },
          { title: 'Sunrise', year: 2014, type: 'movie', poster: '/api/img?u=b' },
        ],
      }
    : { ok: true };
  return { ok: true, status: 200, text: async () => JSON.stringify(body) };
};

area.value = 'Sunrise';
area.fire('paste');
await new Promise((r) => setTimeout(r, 250));

let row = panel.find((n) => n.classList.has('result'));
if (row.length !== 1) throw new Error(`unsure: expected one row, got ${row.length}`);
if (!row[0].text().includes('best guess')) throw new Error(`unsure row said: ${row[0].text()}`);

const pick = row[0].find((n) => n.tagName === 'BUTTON' && n.textContent === 'Pick');
if (!pick.length) throw new Error('no Pick button on an unsure row');

// A guess is shown with its artwork, so it can be seen and corrected — and
// taken if it is left alone. The strict rule belongs to the background pass,
// which writes with nobody watching; see enrich_resolve in server/enrich.py.
if (!row[0].find((n) => n.tagName === 'IMG' && n.src).length) {
  throw new Error('an unsure row showed no artwork at all');
}
let add = panel.find((n) => n.tagName === 'BUTTON' && /^Add \d/.test(n.textContent));
add[0].fire('click');
await new Promise((r) => setTimeout(r, 120));
const guessed = store.live()[store.live().length - 1];
if (guessed.title !== 'Sunrise') throw new Error(`guessed title: ${guessed.title}`);
if (guessed.year !== 1927) throw new Error(`the guess on screen was 1927, added ${guessed.year}`);
if (guessed.poster !== '/api/img?u=a') throw new Error(`guessed poster: ${guessed.poster}`);

/* ---- picking one applies it ---- */
area.value = 'Sunrise';
area.fire('paste');
await new Promise((r) => setTimeout(r, 250));
row = panel.find((n) => n.classList.has('result'));
row[0].find((n) => n.tagName === 'BUTTON' && n.textContent === 'Pick')[0].fire('click');
// the sheet lists the candidates; the first is the 1927 film
// The pick list is mounted in the sheet host, wherever ui.js puts it.
const sheetItems = Object.values(document._byId)
  .flatMap((n) => n.find((x) => x.classList.has('menu-item')))
  .concat(document.body.find((x) => x.classList.has('menu-item')));
if (sheetItems.length < 3) throw new Error(`pick sheet had ${sheetItems.length} options`);
sheetItems[1].fire('click');            // the 2014 one, not the default
await new Promise((r) => setTimeout(r, 60));
add = panel.find((n) => n.tagName === 'BUTTON' && /^Add \d/.test(n.textContent));
add[0].fire('click');
await new Promise((r) => setTimeout(r, 120));
const picked = store.live()[store.live().length - 1];
if (picked.year !== 2014) throw new Error(`picked year: ${picked.year}`);
if (picked.poster !== '/api/img?u=b') throw new Error(`picked poster: ${picked.poster}`);

/* ---- the same title twice does not double ---- */
const count = store.live().length;
area.value = 'Sunrise';
area.fire('paste');
await new Promise((r) => setTimeout(r, 250));
panel.find((n) => n.tagName === 'BUTTON' && /^Add \d/.test(n.textContent))[0].fire('click');
await new Promise((r) => setTimeout(r, 120));
if (store.live().length !== count) throw new Error(`a duplicate was added (${store.live().length} vs ${count})`);

console.log('ok — a guess is shown with artwork and taken, picking overrides it, duplicates are skipped');
console.log(`   ${store.live().length} items in the library at the end`);
