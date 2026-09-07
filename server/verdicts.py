"""What you have said about a film you do not own.

Discover is forty-five thousand films nobody asked for, and only half the
judgement was being kept.  Pressing + on one said *yes* and left a library
item behind saying so; passing on the other four hundred said *no* and left
nothing at all — so the page could never get quieter, and the half of the
signal that is most of the signal was thrown away on every scroll.

This is that half, kept.  One line per film: the catalogue key, the verdict,
and when it was given.  Nothing about the film is copied here — the key
reaches the whole record in ``data/lists/``, so a verdict stays a few dozen
bytes and stays true when the merge is rebuilt underneath it.

It is its own file, next to the library rather than inside it, for two
reasons.  These are not things you own, and putting them in the library would
mean four thousand rows of things you have decided you do not want.  And they
have to survive ``data/lists/`` being deleted and re-harvested, which is a
thing that is meant to be safe to do.

``skip`` is the only verdict today.  The shape is deliberately wider than a
boolean, because what this is for is the recommending that comes later, and
that will want *seen it* and *not for me* and *loved it* sitting beside each
other, told apart, with the date each was given.
"""

from __future__ import annotations

import json
import os
import threading

from config import DATA_DIR, log, now_iso

VERDICTS_PATH = DATA_DIR / "verdicts.json"

# Every verdict this file will hold. `skip` is what Discover writes; the rest
# are named so that adding one later is a UI change and not a migration.
VERDICTS = ("skip", "seen", "never")

# A judgement per film in a century of lists is about forty-five thousand.
# The cap is here so a loop somewhere can never fill the volume, not because
# the real number is expected to come near it.
MAX_VERDICTS = 200_000


class Verdicts:
    """The verdict file, guarded by a lock and written atomically.

    Written through on every change rather than batched: a skip is a keypress
    the person expects to survive closing the tab, the file is small, and a
    lost verdict is worse than a millisecond.
    """

    def __init__(self, path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.data: dict[str, dict] = {}
        self.loaded = False

    # ---------------------------------------------------------------- disk

    def load(self) -> None:
        with self.lock:
            if self.loaded:
                return
            self.loaded = True
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            given = (raw or {}).get("verdicts")
            if not isinstance(given, dict):
                return
            for key, entry in given.items():
                if not isinstance(entry, dict):
                    continue
                verdict = str(entry.get("verdict") or "")
                if verdict in VERDICTS and isinstance(key, str):
                    self.data[key] = {"verdict": verdict,
                                      "at": str(entry.get("at") or "")}
            log(f"verdicts: {len(self.data)} loaded")

    def _write(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps(
            {"schema": 1, "updatedAt": now_iso(), "verdicts": self.data},
            ensure_ascii=False, separators=(",", ":"))
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)

    # --------------------------------------------------------------- using

    def set(self, key: str, verdict: str) -> dict:
        """Give a verdict, or take it back with an empty one."""
        self.load()
        key = str(key or "").strip()
        if not key:
            return self.counts()
        with self.lock:
            if verdict in VERDICTS:
                if key not in self.data and len(self.data) >= MAX_VERDICTS:
                    return self.counts()
                self.data[key] = {"verdict": verdict, "at": now_iso()}
            elif key in self.data:
                del self.data[key]
            else:
                return self.counts()
            self._write()
        return self.counts()

    def keys(self, verdict: str = "skip") -> set:
        self.load()
        with self.lock:
            return {key for key, entry in self.data.items()
                    if entry.get("verdict") == verdict}

    def counts(self) -> dict:
        self.load()
        with self.lock:
            out = {name: 0 for name in VERDICTS}
            for entry in self.data.values():
                name = entry.get("verdict")
                if name in out:
                    out[name] += 1
            return out

    def all(self) -> dict:
        self.load()
        with self.lock:
            return dict(self.data)


STORE = Verdicts(VERDICTS_PATH)
