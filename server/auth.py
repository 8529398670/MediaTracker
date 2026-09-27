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

A bot gets in another way: an API key, made for one person and acting as
them, sent as ``Authorization: Bearer <key>``. It reaches the library and
everything around it, but not the people — a key cannot add anyone, remove
anyone, or make a link or another key, so one that leaks cannot turn itself
into a sign-in that outlives revoking it. A key is full or read-only.

What is kept, in ``data/users.json``:

    users     id -> name, and who added them
    sessions  sha256(token) -> whose, since when, last seen
    links     sha256(token) -> whose, until when
    keys      sha256(key) -> whose, what for, full or read, last used

Only hashes are written down. A copy of the file — a backup, a paste into a
bug report — lets nobody in; the tokens themselves exist only in the browsers
holding them, in the one link that was sent, and in the bot given the key.

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
MAX_KEYS = 200
NAME_MAX = 32

TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{20,128}")

# An API key says what it is, so a secret scanner — or a person reading a
# config file — can tell it from a session. The rest is 256 random bits.
KEY_PREFIX = "mt_"
KEY_HINT = 7                        # how much of it is kept to recognise it by
ACCESS = ("full", "read")

# What each kind of token notes when it is used: a session is "seen", a key
# is "used". Both go through the same batching, so neither costs a disk write
# per request.
SEEN_FIELD = {"sessions": "seenAt", "keys": "usedAt"}


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
    return {"schema": 1, "users": {}, "sessions": {}, "links": {}, "keys": {}}


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
    for kind in ("sessions", "links", "keys"):
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
        self.seen: dict[str, str] = {}      # session or key -> last used, not yet written

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
        """Fold in who has been seen and which keys used, and drop links that
        have lapsed."""
        changed = False
        for key, when in self.seen.items():
            for kind, field in SEEN_FIELD.items():
                entry = self.data[kind].get(key)
                if entry and (entry.get(field) or "") < when:
                    entry[field] = when
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

    def _holder(self, kind: str, token: str) -> tuple[dict, dict] | None:
        """The session or key this token is, and whose it is — noting that it
        was used. Asked on every request."""
        if not _well_formed(token):
            return None
        key = _hash(token)
        field = SEEN_FIELD[kind]
        with self.lock:
            self._fresh()
            entry = self.data[kind].get(key)
            user = self.data["users"].get(entry["user"]) if entry else None
            if not user:
                return None
            now = now_iso()
            self.seen[key] = now
            stale = _age(entry.get(field)) > SEEN_EVERY
            if stale:
                # A page load is a dozen requests at once, and a bot's sweep a
                # hundred; one write is enough.
                entry[field] = now
            found = (dict(entry, id=key[:12]), {"id": entry["user"], "name": user["name"]})
        if stale:
            try:
                self._change(lambda data: (None, False))
            except OSError as exc:
                log(f"!! could not note a {kind[:-1]} as used: {exc}")
        return found

    def user_for(self, token: str) -> dict | None:
        """Whose session this is, or None."""
        held = self._holder("sessions", token)
        return held[1] if held else None

    def key_for(self, token: str) -> dict | None:
        """Whose API key this is, and which key, or None."""
        if not str(token or "").startswith(KEY_PREFIX):
            return None
        held = self._holder("keys", token)
        if not held:
            return None
        entry, user = held
        return {**user, "key": {"id": entry["id"], "label": entry.get("label") or "",
                                "access": entry.get("access") if entry.get("access") in ACCESS
                                else "read"}}

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
        seen, the links made for them that nobody has opened yet, and the API
        keys that act as them."""
        with self.lock:
            self._fresh()
            now = now_iso()
            people = {uid: {"id": uid, "name": user["name"],
                            "createdAt": user.get("createdAt") or "",
                            "createdBy": (self.data["users"].get(user.get("createdBy") or "")
                                          or {}).get("name", ""),
                            "devices": 0, "seenAt": "", "links": [], "keys": []}
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
            for key, entry in self.data["keys"].items():
                person = people.get(entry["user"])
                if person:
                    person["keys"].append({
                        "id": key[:12], "label": entry.get("label") or "",
                        "access": entry.get("access") if entry.get("access") in ACCESS else "read",
                        "hint": entry.get("hint") or "",
                        "createdAt": entry.get("createdAt") or "",
                        "usedAt": max(entry.get("usedAt") or "", self.seen.get(key) or "")})
        for person in people.values():
            person["links"].sort(key=lambda link: link["createdAt"])
            person["keys"].sort(key=lambda made: made["createdAt"])
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
        """Take someone out, and every browser they are signed in on and every
        key that acts as them with them. Their name, or None if there was
        nobody by that id."""
        def drop(data):
            user = data["users"].pop(uid, None)
            if not user:
                return None, False
            for kind in ("sessions", "links", "keys"):
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

    def _revoke(self, kind: str, short: str) -> dict | None:
        """Drop one link or key by the id `users()` gave it. What was dropped,
        or None."""
        short = str(short or "").lower()
        if not re.fullmatch(r"[0-9a-f]{12}", short):
            return None

        def drop(data):
            hits = [key for key in data[kind] if key.startswith(short)]
            if len(hits) != 1:
                return None, False
            return data[kind].pop(hits[0]), True

        return self._change(drop)

    def revoke(self, link_id: str) -> bool:
        """Cancel a link nobody has opened yet."""
        return self._revoke("links", link_id) is not None

    # ----------------------------------------------------------------- keys

    def make_key(self, uid: str, label: object = "", access: str = "full",
                 by: str = "") -> dict | None:
        """A new API key that acts as this person. Like a link, the key is in
        the answer and nowhere else: lost, it is made again, not looked up."""
        label = clean_name(label) or "API key"
        access = access if access in ACCESS else "full"

        def make(data):
            if uid not in data["users"]:
                return None, False
            token = KEY_PREFIX + secrets.token_urlsafe(32)
            key = _hash(token)
            now = now_iso()
            data["keys"][key] = {"user": uid, "label": label, "access": access,
                                 "hint": token[:KEY_HINT], "createdAt": now,
                                 "createdBy": by or ""}
            _cap(data["keys"], MAX_KEYS, "createdAt")
            return {"key": token, "id": key[:12], "label": label, "access": access,
                    "hint": token[:KEY_HINT], "createdAt": now,
                    "name": data["users"][uid]["name"]}, True

        return self._change(make)

    def revoke_key(self, key_id: str) -> dict | None:
        """Stop a key working. Its label and whose it was, or None."""
        gone = self._revoke("keys", key_id)
        if not gone:
            return None
        with self.lock:
            user = self.data["users"].get(gone["user"]) or {}
        return {"label": gone.get("label") or "", "name": user.get("name") or ""}


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


USAGE = ("usage: auth.py link <name>  |  auth.py key [--read] [--label <what for>] <name>"
         "  |  auth.py users")


def _someone(name: str) -> str | None:
    """The id of whoever goes by this name, adding them if nobody does."""
    uid = ACCOUNTS.find(name)
    if uid is None:
        user, why = ACCOUNTS.add(name)
        if not user:
            print(why, file=sys.stderr)
            return None
        uid = user["id"]
    return uid


def main(argv: list[str]) -> int:
    """Make a login link from outside the app — the first one, or the one that
    gets somebody back in when nobody left inside can make it for them — or
    an API key for a bot running on the same machine."""
    if len(argv) >= 2 and argv[0] == "link":
        uid = _someone(" ".join(argv[1:]))
        made = ACCOUNTS.link(uid) if uid else None
        if not made:
            print("could not make a link", file=sys.stderr)
            return 1
        print(made["path"])
        return 0
    if argv[:1] == ["key"]:
        rest, access, label = argv[1:], "full", ""
        while rest and rest[0].startswith("--"):
            flag = rest.pop(0)
            if flag == "--read":
                access = "read"
            elif flag == "--label" and rest:
                label = rest.pop(0)
            else:
                print(USAGE, file=sys.stderr)
                return 2
        if not rest:
            print(USAGE, file=sys.stderr)
            return 2
        uid = _someone(" ".join(rest))
        made = ACCOUNTS.make_key(uid, label, access) if uid else None
        if not made:
            print("could not make a key", file=sys.stderr)
            return 1
        print(made["key"])
        return 0
    if argv[:1] == ["users"]:
        people = ACCOUNTS.users()
        for person in people:
            seen = person["seenAt"] or "never"
            print(f"{person['name']:<{NAME_MAX}}  {person['devices']} signed in"
                  f"  last seen {seen}  {len(person['links'])} unused link(s)"
                  f"  {len(person['keys'])} API key(s)")
        if not people:
            print("nobody yet — ./dockerRun.sh link <name>")
        return 0
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
