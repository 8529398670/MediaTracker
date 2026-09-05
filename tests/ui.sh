#!/bin/sh
# Drive the importer panel against a shimmed DOM.
#
# No browser and no node on this host, so it runs in the node image that is
# already pulled. The front end is copied in beside the shim rather than
# mounted, so nothing here can write to public/.
set -e
cd "$(dirname "$0")/.."
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cp public/js/*.js "$work/"
cp tests/ui/dom.mjs "$work/dom.mjs"
cp tests/ui/importer.mjs "$work/run.mjs"

docker run --rm -v "$work:/w" -w /w node:22-alpine node run.mjs
