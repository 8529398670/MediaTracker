#!/bin/sh
# The two copies of the outline parser must agree.
#
# server/seed.py imports the Markdown lists on start; public/js/porting.js
# parses what you paste. They are the same rules written twice, so a change to
# one is a bug in the other until this passes. Needs a JS runtime; it uses the
# node image rather than expecting node on the host.
set -e
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cp public/js/porting.js public/js/importer.js "$work/"

# Stubs for the modules porting.js imports: the parser touches none of them.
cat > "$work/store.js" <<'EOF'
export const state={items:[],sources:[],config:null};
export const TYPES=[{id:'movie'},{id:'tv'},{id:'anime'},{id:'doc'},{id:'book'}];
export const STATUSES=[{id:'queue'},{id:'watching'},{id:'watched'},{id:'dropped'}];
export const TYPE_LABEL={};export const STATUS_LABEL={};
export const live=()=>[];export const newItem=(x)=>x;export const titleKey=(t,y)=>`${t}|${y}`;
export const addMany=()=>{};export const replaceAll=()=>{};export const addSource=()=>{};
export const checkpoint=()=>{};export const api=async()=>({});export const addItem=(x)=>x;
EOF
cat > "$work/ui.js" <<'EOF'
export const el=()=>({append(){},replaceChildren(){},style:{setProperty(){}},addEventListener(){}});
export const field=()=>({});export const openSheet=()=>({close(){}});export const toast=()=>{};
export const download=()=>{};export const copyText=async()=>true;export const segmented=()=>({});
export const fmtDate=()=>'';export const icon=()=>({});
EOF

# The lines to compare are the ones tests/test_parser.py already lists.
python3 - "$work" <<'EOF'
import importlib.util, json, pathlib, sys
spec = importlib.util.spec_from_file_location("cases", "tests/test_parser.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
pathlib.Path(sys.argv[1], "cases.json").write_text(
    json.dumps([c[0] for c in module.CASES]))
EOF

cat > "$work/run.mjs" <<'EOF'
import { readFileSync } from 'node:fs';
import { parseOutline } from './porting.js';
const out = [];
for (const line of JSON.parse(readFileSync('./cases.json', 'utf8'))) {
  const { items } = parseOutline(`- [ ] ${line}`, { type: 'movie', status: 'queue' });
  const it = items[0] || {};
  out.push([line, it.title ?? null, it.year ?? null, it.notes ?? '']);
}
console.log(JSON.stringify(out));
EOF

docker run --rm -v "$work:/w" -w /w node:22-alpine node run.mjs > "$work/js.json"

python3 - "$work" <<'EOF'
import json, sys
sys.path.insert(0, "server")
from seed import split_title
rows = json.load(open(sys.argv[1] + "/js.json"))
bad = 0
for line, jt, jy, jn in rows:
    pt, py, pn = split_title(line)
    if [pt, py, pn] != [jt, jy, jn]:
        bad += 1
        print(f"DIFFER {line!r}\n  seed.py    {[pt, py, pn]}\n  porting.js {[jt, jy, jn]}")
print(f"{len(rows) - bad}/{len(rows)} identical between server/seed.py and public/js/porting.js")
sys.exit(1 if bad else 0)
EOF
