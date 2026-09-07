#!/usr/bin/env python3
"""Media Tracker — application server.

Two jobs:

  1. Serve the front end.  Everything is gzip-compressed on the wire and
     served with `no-store`, so a refresh always fetches the current file.
  2. Expose a small JSON API over one file on a mounted volume
     (``/data/library.json``), plus a proxy for free metadata providers so
     the browser never talks to third parties directly (no CORS, no leaked
     referrers, and a strict CSP stays intact).

Standard library only, on purpose: the image ships CPython and nothing else.

This module is only the entry point.  The work lives next door, and the
modules import in this order — each one only ever reaches leftwards:

    config → normalize → library ─────────────┐
    config → netio → providers ─┐             │
    match ──────────────────────┴→ resolve ───┴→ enrich → httpd
    wiki → lists ─────────────────────────────────────────┘
    config → certs ──┘  (and verdicts beside it, the same way)

`match` imports nothing at all: it is the measures, with no provider and no
network anywhere near them.  `wiki` is the same idea one level up: it turns
Wikipedia's markup into tables and links and knows nothing of what they mean,
which `lists` decides and then goes and fetches.
"""

from __future__ import annotations

import mimetypes
import signal
import sys
import threading

from config import (ENV_COUNT, ENV_FILE, EXTRA_TYPES, HOST, LIBRARY_PATH,
                    NET_ENABLED, OMDB_KEY, PORT, PUBLIC_DIR, SEED_DIR,
                    SEED_ENABLED, TMDB_KEY, TOKEN, VERSION, log)
from httpd import Handler, Server
from library import LIBRARY
import lists


def main() -> int:
    for suffix, ctype in EXTRA_TYPES.items():
        mimetypes.add_type(ctype.split(";")[0], suffix)

    if not PUBLIC_DIR.is_dir():
        log(f"!! public directory not found: {PUBLIC_DIR}")
        return 1

    if SEED_ENABLED:
        try:
            LIBRARY.seed_from(SEED_DIR)
        except Exception as exc:  # a bad document must not stop the server
            log(f"!! seed import failed: {type(exc).__name__}: {exc}")

    httpd = Server((HOST, PORT), Handler)

    def shutdown(signum: int, _frame: object) -> None:
        log(f"signal {signum} — shutting down")
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    meta = LIBRARY.meta()
    log(f"Media Tracker {VERSION}")
    log(f"  listening   http://{HOST}:{PORT}")
    log(f"  public      {PUBLIC_DIR}")
    log(f"  library     {LIBRARY_PATH} ({meta['items']} items, rev {meta['rev']})")
    log(f"  seeds       {SEED_DIR}"
        f" ({'on' if SEED_ENABLED else 'off'}, {len(LIBRARY.data.get('seeds') or {})} imported)")
    log(f"  lookups     {'on' if NET_ENABLED else 'off'}"
        f"{' (tmdb key)' if TMDB_KEY else ''}{' (omdb key)' if OMDB_KEY else ''}")
    listed = lists.coverage()
    log(f"  lists       {listed['films']} films over {len(listed['years'])} years"
        f" from {len(listed['pages'])} pages")
    rated = lists.CERTIFIER.status()
    log(f"  ratings     {rated['rated']} rated, {rated['asked'] - rated['rated']} with none"
        f", {rated['unknown']} not looked up")
    log(f"  auth        {'token required' if TOKEN else 'open'}")
    if ENV_COUNT:
        log(f"  settings    {ENV_FILE} ({ENV_COUNT} read)")
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
