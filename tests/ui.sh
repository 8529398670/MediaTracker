#!/bin/sh
# Drive the front end against a shimmed DOM.
#
# No browser and no node on this host, so it runs in the node image that is
# already pulled. The front end is copied in beside the shim rather than
# mounted, so nothing here can write to public/.
set -e
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cp public/js/*.js "$work/"
cp tests/ui/*.mjs "$work/"

# Every runner beside the shim, so a new one joins by being written.
for runner in tests/ui/*.mjs; do
  name=$(basename "$runner")
  [ "$name" = "dom.mjs" ] && continue
  echo "== $name"
  docker run --rm -v "$work:/w" -w /w node:22-alpine node "$name"
done
