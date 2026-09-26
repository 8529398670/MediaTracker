"""Who may use this at all, and the links that let someone in.

Anything that could reach the port used to be able to read the library, edit
it, run an import and take a backup away — and the port is on the internet,
through the tunnel. Now nobody gets anything without a session: not the page,
not a script, not a poster. Somebody without one is sent to Google.

Everybody who has one can do everything. There are no roles, only names: each
person is somebody, and every one of them can add people, remove them, and
make the links that let them in.

The only way in is one of those links. It works once: the first browser to
open it is signed in as that person for good, and the link is spent. There is
no password to forget and none to guess — a token is 256 random bits.

What is kept, in ``data/users.json``:

    users     id -> name, and who added them
    sessions  sha256(token) -> whose, since when, last seen
    links     sha256(token) -> whose, until when

Only hashes are written down. A copy of the file — a backup, a paste into a
bug report — lets nobody in; the tokens themselves exist only in the browsers
holding them and in the one link that was sent.

The file has a second writer: ``python3 auth.py link <name>``, which
``./dockerRun.sh link`` runs inside the container. That is how the first
person gets in, and how anyone gets back in if everyone else has been
removed. So every change takes an flock and re-reads the file before touching
it, and the server notices a file changed under it by its stat.

Imports only config, so httpd can import it and so can a shell.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from config import DATA_DIR, LINK_DAYS, log, now_iso

USERS_PATH = DATA_DIR / "users.json"
LOCK_PATH = DATA_DIR / "users.lock"

# Where anyone without a session is sent.
AWAY = "https://www.google.com/"

# The cookie that carries a session. A browser keeps a cookie at most 400
# days whatever it is told (Chrome clamps anything longer), so it is set again
# every time the app is opened, and only a browser left alone for more than a
# year would lose it. The page keeps the token in localStorage too, and the
# gate puts the cookie back from there if it ever goes.
COOKIE = "mt_session"
COOKIE_AGE = 400 * 86400

# Files a browser without a session may have: the gate's own script, and the
# icon. Nothing else — not the stylesheet, not the app.
OPEN_FILES = frozenset({"/gate.js", "/favicon.svg"})

# How stale a session's "last seen" may get before it is written down. Every
# request would otherwise be a disk write, on a machine with little to spare.
SEEN_EVERY = 3600

# Ceilings, so that nothing can grow the file without end. Every session
# costs someone a link and every link costs someone a click, so the real
# numbers are a handful.
MAX_USERS = 200
MAX_SESSIONS = 2000
MAX_LINKS = 500
NAME_MAX = 32

TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{20,128}")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _well_formed(token: object) -> bool:
    return isinstance(token, str) and bool(TOKEN_SHAPE.fullmatch(token))


def _later(days: float) -> str:
    moment = datetime.now(timezone.utc) + timedelta(days=days)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _age(stamp: str | None) -> float:
    """Seconds since an ISO stamp; forever for one that cannot be read."""
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds()


def clean_name(raw: object) -> str:
    """A name as it will be shown: one line, no control characters, not long.

    Anything printable is allowed, accents and all — it is only ever drawn as
    text, never used as a path or a key.
    """
    text = unicodedata.normalize("NFKC", str(raw or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C")
    text = " ".join(text.split())[:NAME_MAX].strip()
    return text if any(ch.isalnum() for ch in text) else ""


def _blank() -> dict:
    return {"schema": 1, "users": {}, "sessions": {}, "links": {}}


def _clean(raw: object) -> dict:
    """The file as read, with anything malformed dropped rather than trusted."""
    data = _blank()
    if not isinstance(raw, dict):
        return data
    for uid, user in (raw.get("users") or {}).items():
        if isinstance(uid, str) and isinstance(user, dict) and clean_name(user.get("name")):
            data["users"][uid] = {
                "name": clean_name(user.get("name")),
                "createdAt": str(user.get("createdAt") or ""),
                "createdBy": str(user.get("createdBy") or ""),
            }
    for kind in ("sessions", "links"):
        for key, entry in (raw.get(kind) or {}).items():
            if (isinstance(key, str) and len(key) == 64 and isinstance(entry, dict)
                    and entry.get("user") in data["users"]):
                data[kind][key] = {k: str(v) for k, v in entry.items() if isinstance(v, str)}
    return data


def _cap(entries: dict, limit: int, field: str) -> None:
    """Drop the oldest by `field` until there are `limit` left."""
    if len(entries) <= limit:
        return
    for key in sorted(entries, key=lambda k: entries[k].get(field) or "")[:len(entries) - limit]:
        del entries[key]


class Accounts:
    """The users file, shared between the server's threads and a shell.

    Reads come from memory, refreshed whenever the file's stat changes. Every
    change is made under an flock to the file as it is on disk at that
    moment, then written atomically — so a link made from the shell while the
    server is running is in the server a request later, and neither writer
    ever puts back what the other just took out.
    """

    def __init__(self, path, lock_path) -> None:
        self.path = path
        self.lock_path = lock_path
        self.lock = threading.RLock()
        self.data = _blank()
        self.stamp: tuple | None = None
        self.seen: dict[str, str] = {}      # session -> last seen, not yet written

    # ---------------------------------------------------------------- disk

    def _stat(self) -> tuple | None:
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        return (st.st_ino, st.st_mtime_ns, st.st_size)

    def _fresh(self) -> None:
        """Read the file again if anything has written it since last time."""
        stamp = self._stat()
        if stamp is not None and stamp == self.stamp:
            return
        self.stamp = stamp
        if stamp is None:
            self.data = _blank()
            return
        try:
            self.data = _clean(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError) as exc:
            # Keep what was there for whoever looks, and start again. Only a
            # disk fault gets here: every write is a whole file, renamed in.
            broken = self.path.with_name(f"users.corrupt-{int(time.time())}.json")
            log(f"!! {self.path.name} is unreadable ({exc}); moved to {broken.name}")
            try:
                self.path.replace(broken)
            except OSError:
                pass
            self.data = _blank()
            self.stamp = None

    def _write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        payload = json.dumps(self.data, ensure_ascii=False, indent=1)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        self.stamp = self._stat()

    def _tidy(self) -> bool:
        """Fold in who has been seen, and drop links that have lapsed."""
        changed = False
        sessions = self.data["sessions"]
        for key, when in self.seen.items():
            session = sessions.get(key)
            if session and (session.get("seenAt") or "") < when:
                session["seenAt"] = when
                changed = True
        self.seen.clear()
        now = now_iso()
        for key in [k for k, link in self.data["links"].items()
                    if (link.get("expiresAt") or "") <= now]:
            del self.data["links"][key]
            changed = True
        return changed

    def _change(self, fn):
        """Run `fn(data) -> (result, changed)` against the file as it is now."""
        with self.lock:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.lock_path, "a", encoding="utf-8") as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                try:
                    self.stamp = None
                    self._fresh()
                    tidied = self._tidy()
                    result, changed = fn(self.data)
                    if changed or tidied:
                        self._write()
                    return result
                finally:
                    fcntl.flock(held, fcntl.LOCK_UN)

    # ------------------------------------------------------------ sessions

    def user_for(self, token: str) -> dict | None:
        """Whose session this is, or None. Asked on every request."""
        if not _well_formed(token):
            return None
        key = _hash(token)
        with self.lock:
            self._fresh()
            session = self.data["sessions"].get(key)
            user = self.data["users"].get(session["user"]) if session else None
            if not user:
                return None
            now = now_iso()
            self.seen[key] = now
            stale = _age(session.get("seenAt")) > SEEN_EVERY
            if stale:
                # A page load is a dozen requests at once; one write is enough.
                session["seenAt"] = now
            found = {"id": session["user"], "name": user["name"]}
        if stale:
            try:
                self._change(lambda data: (None, False))
            except OSError as exc:
                log(f"!! could not note a session as seen: {exc}")
        return found

    def redeem(self, token: str, agent: str = "") -> tuple[str, dict] | None:
        """Spend a link. A new session for whoever it was made for, or None."""
        if not _well_formed(token):
            return None
        key = _hash(token)
        with self.lock:
            self._fresh()
            if key not in self.data["links"]:
                return None             # nothing to change, so nothing to lock

        def spend(data):
            # Asked again under the lock: two tabs, or two processes, may have
            # opened the same link at once, and only one of them gets it.
            link = data["links"].pop(key, None)
            if not link or link["user"] not in data["users"]:
                return None, link is not None
            session = secrets.token_urlsafe(32)
            now = now_iso()
            data["sessions"][_hash(session)] = {
                "user": link["user"], "createdAt": now, "seenAt": now,
                "agent": str(agent or "")[:200],
            }
            _cap(data["sessions"], MAX_SESSIONS, "seenAt")
            user = data["users"][link["user"]]
            return (session, {"id": link["user"], "name": user["name"]}), True

        return self._change(spend)

    def end(self, token: str) -> bool:
        """Sign one browser out."""
        if not _well_formed(token):
            return False
        key = _hash(token)

        def drop(data):
            gone = data["sessions"].pop(key, None) is not None
            return gone, gone

        return self._change(drop)

    # --------------------------------------------------------------- people

    def users(self) -> list[dict]:
        """Everyone, with how many browsers each is signed in on and when last
        seen, and the links made for them that nobody has opened yet."""
        with self.lock:
            self._fresh()
            now = now_iso()
            people = {uid: {"id": uid, "name": user["name"],
                            "createdAt": user.get("createdAt") or "",
                            "createdBy": (self.data["users"].get(user.get("createdBy") or "")
                                          or {}).get("name", ""),
                            "devices": 0, "seenAt": "", "links": []}
                      for uid, user in self.data["users"].items()}
            for key, session in self.data["sessions"].items():
                person = people.get(session["user"])
                if not person:
                    continue
                person["devices"] += 1
                seen = max(session.get("seenAt") or "", self.seen.get(key) or "")
                person["seenAt"] = max(person["seenAt"], seen)
            for key, link in self.data["links"].items():
                person = people.get(link["user"])
                if person and (link.get("expiresAt") or "") > now:
                    person["links"].append({"id": key[:12], "createdAt": link.get("createdAt") or "",
                                            "expiresAt": link.get("expiresAt") or ""})
        for person in people.values():
            person["links"].sort(key=lambda link: link["createdAt"])
        return sorted(people.values(), key=lambda p: p["name"].casefold())

    def count(self) -> int:
        with self.lock:
            self._fresh()
            return len(self.data["users"])

    def find(self, name: str) -> str | None:
        """The id of whoever goes by this name, ignoring case."""
        wanted = clean_name(name).casefold()
        with self.lock:
            self._fresh()
            for uid, user in self.data["users"].items():
                if user["name"].casefold() == wanted:
                    return uid
        return None

    def add(self, name: object, by: str = "") -> tuple[dict | None, str]:
        """Someone new. Their record, or None and why not."""
        clean = clean_name(name)
        if not clean:
            return None, "a name needs a letter or a number in it"

        def make(data):
            if any(u["name"].casefold() == clean.casefold() for u in data["users"].values()):
                return (None, f"there is already someone called {clean}"), False
            if len(data["users"]) >= MAX_USERS:
                return (None, "that is as many people as this will hold"), False
            uid = secrets.token_hex(6)
            data["users"][uid] = {"name": clean, "createdAt": now_iso(), "createdBy": by or ""}
            return ({"id": uid, "name": clean}, ""), True

        return self._change(make)

    def remove(self, uid: str) -> str | None:
        """Take someone out, and every browser they are signed in on with them.
        Their name, or None if there was nobody by that id."""
        def drop(data):
            user = data["users"].pop(uid, None)
            if not user:
                return None, False
            for kind in ("sessions", "links"):
                data[kind] = {k: v for k, v in data[kind].items() if v["user"] != uid}
            return user["name"], True

        return self._change(drop)

    # ---------------------------------------------------------------- links

    def link(self, uid: str, by: str = "") -> dict | None:
        """A new one-time link for this person. The token is in the answer and
        nowhere else — it cannot be looked up again, only made again."""
        def make(data):
            if uid not in data["users"]:
                return None, False
            token = secrets.token_urlsafe(32)
            key = _hash(token)
            expires = _later(LINK_DAYS)
            data["links"][key] = {"user": uid, "createdAt": now_iso(),
                                  "createdBy": by or "", "expiresAt": expires}
            _cap(data["links"], MAX_LINKS, "createdAt")
            return {"token": token, "id": key[:12], "path": f"/login#{token}",
                    "name": data["users"][uid]["name"], "expiresAt": expires}, True

        return self._change(make)

    def revoke(self, link_id: str) -> bool:
        """Cancel a link nobody has opened yet, by the id `users()` gave it."""
        link_id = str(link_id or "").lower()
        if not re.fullmatch(r"[0-9a-f]{12}", link_id):
            return False

        def drop(data):
            hits = [key for key in data["links"] if key.startswith(link_id)]
            if len(hits) != 1:
                return False, False
            del data["links"][hits[0]]
            return True, True

        return self._change(drop)


class Throttle:
    """A cap on failed attempts to get in, per address.

    A token cannot be guessed, so this is not what keeps anyone out. It keeps
    somebody hammering the door from costing the machine anything.
    """

    def __init__(self, allowance: int = 30, window: float = 600.0) -> None:
        self.allowance = allowance
        self.window = window
        self.fails: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        kept = [t for t in self.fails.get(key, ()) if now - t < self.window]
        if kept:
            self.fails[key] = kept
        else:
            self.fails.pop(key, None)
        return kept

    def blocked(self, key: str) -> bool:
        with self.lock:
            return len(self._recent(key, time.monotonic())) >= self.allowance

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            if len(self.fails) > 4096:
                self.fails.clear()
            self.fails[key] = self._recent(key, now) + [now]


ACCOUNTS = Accounts(USERS_PATH, LOCK_PATH)
THROTTLE = Throttle()


# --------------------------------------------------------------------------
# the shell: ./dockerRun.sh link <name>
# --------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    """Make a login link from outside the app — the first one, or the one that
    gets somebody back in when nobody left inside can make it for them."""
    if len(argv) >= 2 and argv[0] == "link":
        name = " ".join(argv[1:])
        uid = ACCOUNTS.find(name)
        if uid is None:
            user, why = ACCOUNTS.add(name)
            if not user:
                print(why, file=sys.stderr)
                return 1
            uid = user["id"]
        made = ACCOUNTS.link(uid)
        if not made:
            print("could not make a link", file=sys.stderr)
            return 1
        print(made["path"])
        return 0
    if argv[:1] == ["users"]:
        people = ACCOUNTS.users()
        for person in people:
            seen = person["seenAt"] or "never"
            print(f"{person['name']:<{NAME_MAX}}  {person['devices']} signed in"
                  f"  last seen {seen}  {len(person['links'])} unused link(s)")
        if not people:
            print("nobody yet — ./dockerRun.sh link <name>")
        return 0
    print("usage: auth.py link <name>  |  auth.py users", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
