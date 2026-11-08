"""The activity log: every request the server answers, every sign-in and admin
action, and what people did on the page (sent by static/js/track.js). Only
the owner reads it, on the Logs screen.

It is kept in plain files rather than in the SQLite store, one per UTC day
under <app_dir>/logs/ (2026-11-02.jsonl, then 2026-11-02.1.jsonl once a day
passes logs.max_file_mb, and .jsonl.gz once it is compressed). A log grows
all the time and is read a day at a time, which files do well and an
encrypted key-value table does badly: retention is deleting a file, not
decrypting every record, and app.db stays the size of the app's actual data.

Each line is one entry as JSON or, with server.encrypt_at_rest on, that JSON
encrypted with the server key and base64'd -- so a copy of the logs directory
alone reads as nothing, the same as a copy of app.db. Lines of both kinds can
sit in one file (the setting was changed); the reader tells them apart by the
first character.

What is never written: request bodies, cookies, the Authorization header, the
secret half of an API key, a login or invite credential in a path, and
anything typed into the page. See redact() and track.js.

The day files, the line format, the search grammar and the JSON the Logs
screen reads are the same as the Go template's, so the two frontends are one.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode

import base64
import gzip
import json
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from app.core import encryption
from app.core.config import LogsConfig

# Kinds. The Logs screen has a filter button for each.
KIND_REQUEST = "request"  # every HTTP request (app/core/request_log.py)
KIND_UI = "ui"  # what someone did on the page (track.js)
KIND_AUTH = "auth"  # sign-in, sign-out, joining through an invite link
KIND_ADMIN = "admin"  # accounts, keys and invite links being changed
KIND_ERROR = "error"  # a request that ended in a 5xx
KIND_SYSTEM = "system"  # start, stop, prune, dropped entries

LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"

DAY_FORMAT = "%Y-%m-%d"

# QUEUE_SIZE entries can wait for the writer. Past that, log() drops rather
# than blocks: a slow disk must never slow a request down.
QUEUE_SIZE = 10000
# The writer flushes this often (seconds), or every FLUSH_EVERY lines.
FLUSH_INTERVAL = 1.0
FLUSH_EVERY = 200
# The most often on_flushed is called, in seconds. A quiet server flushes after
# every entry, so without this each one would be a nudge.
NUDGE_INTERVAL = 1.0
# The longest line the reader accepts. Every part of an entry is capped well
# below this, so a longer one is damage.
MAX_LINE_BYTES = 1024 * 1024

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FILE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\.(\d+))?\.jsonl(\.gz)?$")

# The path prefixes whose next segment is a credential: a login link, an
# invite link. Opening one is logged; the credential is not.
_SECRET_PATH_PREFIXES = ("/login/", "/join/")
# Query parameters whose values are never written, whatever route they are on.
_SECRET_QUERY_KEYS = {
    "token", "key", "secret", "code", "credential", "csrf_token", "pin", "password",
    "password_digest", "challenge", "recovery_code",
}
MAX_PATH_LENGTH = 300


class LogsError(Exception):
    """Base for the refusals below; str() is the error code the Logs screen
    words (errors.<code> in language.yaml)."""


class BadDayError(LogsError):
    def __init__(self) -> None:
        super().__init__("bad_day")


class TodayError(LogsError):
    """Deleting the day still being written: it would only start again."""

    def __init__(self) -> None:
        super().__init__("logs_today")


# ---------------------------------------------------------------------------
# entries
# ---------------------------------------------------------------------------


def now_iso(moment: datetime | None = None) -> str:
    moment = moment or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def anonymous() -> dict[str, Any]:
    """The actor of a request nobody signed in made."""
    return {"method": "anon"}


def entry(kind: str, level: str = LEVEL_INFO, **fields: Any) -> dict[str, Any]:
    """One log line: ts, kind, level, then whichever of request_id, actor, ip,
    ua, request, ui, client, msg and detail are given. Empty ones are left
    out."""
    record: dict[str, Any] = {"ts": fields.pop("ts", None) or now_iso(), "kind": kind, "level": level}
    for name in ("request_id", "actor", "ip", "ua", "request", "ui", "client", "msg", "detail"):
        value = fields.get(name)
        if value not in (None, "", {}, []):
            record[name] = value
    return record


def redact(path: str, raw_query: str = "") -> str:
    """A request path safe to keep: the credential in a login or invite link
    becomes "…", secret-looking query values become "…", and the whole is
    capped so a pathological URL cannot bloat a line."""
    result = path
    for prefix in _SECRET_PATH_PREFIXES:
        if result.startswith(prefix) and len(result) > len(prefix):
            result = prefix + "…"
            break
    if raw_query:
        pairs = parse_qsl(raw_query, keep_blank_values=True)
        masked = [(name, "…" if name.lower() in _SECRET_QUERY_KEYS else value) for name, value in pairs]
        result += "?" + urlencode(sorted(masked))
    if len(result) > MAX_PATH_LENGTH:
        result = result[:MAX_PATH_LENGTH] + "…"
    return result


def truncate(value: Any, limit: int) -> str:
    """A string from a browser or a header, capped at limit bytes on a
    character boundary."""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", errors="ignore")


def valid_day(day: str) -> bool:
    if not _DAY.match(day or ""):
        return False
    try:
        datetime.strptime(day, DAY_FORMAT)
    except ValueError:
        return False
    return True


def part_name(day: str, part: int, compressed: bool) -> str:
    name = day if part == 0 else f"{day}.{part}"
    return name + (".jsonl.gz" if compressed else ".jsonl")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

_QUERY_KEYS = {"kind", "level", "user", "status", "method", "path", "ip", "action", "screen"}


@dataclass
class _Term:
    key: str
    values: list[str]
    negate: bool


class Query:
    """The Logs screen's search box, parsed. Every term must hold (AND):

        ana                free text: anywhere in the entry's JSON, any case
        "sign in"          a quoted phrase is one free-text term
        kind:auth,admin    key:value -- a comma means any of these (OR)
        -kind:request      a leading minus means the term must NOT hold

    Keys: kind, level, user (name substring or exact id), status (a code, or
    a class like 5xx), method, path (prefix), ip (prefix, or part of what the
    owner calls it), action, screen. An unknown key is free text, so pasting
    "a:b" from an entry still finds it.

    names says what the owner calls an address. Names are not in the log, so a
    search has to be told them: free text and ip: both find them.
    """

    def __init__(self, text: str = "", names: Callable[[str], str] | None = None) -> None:
        self.names = names
        self.terms: list[_Term] = []
        for word in _split_words(text or ""):
            negate = word.startswith("-") and len(word) > 1
            if negate:
                word = word[1:]
            key, found, value = word.partition(":")
            key = key.lower()
            if found and key in _QUERY_KEYS and value:
                values = [part.strip().lower() for part in value.split(",") if part.strip()]
                term = _Term(key, values, negate)
            else:
                term = _Term("", [word.lower()], negate)
            if term.values:
                self.terms.append(term)

    @property
    def empty(self) -> bool:
        return not self.terms

    def match(self, record: dict[str, Any], text: str) -> bool:
        """text is the entry's JSON, lowercased."""
        name = self.name(str(record.get("ip", ""))).lower()
        for term in self.terms:
            holds = any(_matches(term.key, record, text, name, value) for value in term.values)
            if holds == term.negate:
                return False
        return True


    def name(self, ip: str) -> str:
        return self.names(ip) if self.names is not None else ""


def _split_words(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    quoted = False
    for character in text:
        if character == '"':
            quoted = not quoted
        elif character in " \t" and not quoted:
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(character)
    if current:
        words.append("".join(current))
    return words


def _matches(key: str, record: dict[str, Any], text: str, name: str, value: str) -> bool:
    request = record.get("request") or {}
    ui = record.get("ui") or {}
    if key == "":
        return value in text or value in name
    if key == "kind":
        return str(record.get("kind", "")).lower() == value
    if key == "level":
        return str(record.get("level", "")).lower() == value
    if key == "user":
        actor = record.get("actor") or {}
        if not actor.get("user_id"):
            return False
        return value in str(actor.get("name", "")).lower() or str(actor.get("user_id")) == value
    if key == "status":
        if not request:
            return False
        status = str(request.get("status", ""))
        if len(value) == 3 and value.endswith("xx"):
            return status[:1] == value[:1]
        return status == value
    if key == "method":
        return bool(request) and str(request.get("method", "")).lower() == value
    if key == "path":
        return bool(request) and str(request.get("path", "")).lower().startswith(value)
    if key == "ip":
        return str(record.get("ip", "")).lower().startswith(value) or value in name
    if key == "action":
        return bool(ui) and str(ui.get("action", "")).lower() == value
    if key == "screen":
        return bool(ui) and str(ui.get("screen", "")).lower() == value
    return False


# ---------------------------------------------------------------------------
# the logger
# ---------------------------------------------------------------------------


@dataclass
class DayFile:
    path: Path
    day: str
    part: int
    compressed: bool
    size: int
    modified: float


_STOP = object()


class Logger:
    """Owns the logs directory. log() hands it an entry from any thread or the
    event loop; one writer thread puts them on disk, rotating to a new file at
    the UTC day change and when a part reaches logs.max_file_mb. Readers and
    the pruner share _files_lock with it, so a file is never compressed or
    deleted while it is being written."""

    def __init__(self, settings: LogsConfig, key: str, encrypt: bool) -> None:
        self.settings = settings
        self.key = key
        self.encrypt = encrypt
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=QUEUE_SIZE)
        self._dropped = 0
        self._dropped_lock = threading.Lock()
        self._thread: threading.Thread | None = None

        self._files_lock = threading.Lock()
        # The open part: only touched with _files_lock held.
        self._file: Any = None
        self._day = ""
        self._part = 0
        self._size = 0
        self._pending = 0

        self._counts_lock = threading.Lock()
        self._counts: dict[str, tuple[int, float, int, int]] = {}

        # Called from the writer thread once new lines are on disk, at most
        # every NUDGE_INTERVAL: what tells the Logs screen's live tail to look.
        # It must not block, and it is the callback's job to get to the event
        # loop. _unannounced and _nudged_at belong to the writer thread.
        self.on_flushed: Callable[[], None] | None = None
        self._unannounced = False
        self._nudged_at = 0.0

        # Replaced in tests.
        self.now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    @property
    def enabled(self) -> bool:
        return self.settings.enabled

    def apply(self, settings: LogsConfig) -> None:
        """Take new settings from an edited config.yaml. The directory and
        whether logging happens at all are fixed at startup: the writer and
        the log's routes are set up once, and logs.enabled is a [restart]
        key. Replacing the whole (frozen) object is atomic, so a reader sees
        the old settings or the new, never a mix."""
        self.settings = replace(settings, dir=self.settings.dir, enabled=self.settings.enabled)

    @property
    def dropped(self) -> int:
        """How many entries were thrown away because the queue was full."""
        return self._dropped

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="activity-log", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Write whatever is queued and close the file. The lifespan calls it
        on shutdown, after the server has stopped taking requests."""
        if self._thread is None:
            with self._files_lock:
                self._close_locked()
            return
        self._queue.put(_STOP)
        self._thread.join(timeout=10)
        self._thread = None

    def log(self, record: dict[str, Any]) -> None:
        """Queue an entry. Never blocks: a full queue drops it and counts it,
        and the writer logs the count once it catches up."""
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            with self._dropped_lock:
                self._dropped += 1

    def system(self, level: str, message: str, detail: dict[str, Any] | None = None) -> None:
        """A server event with no request behind it."""
        self.log(entry(KIND_SYSTEM, level, msg=message, detail=detail))

    def _run(self) -> None:
        reported = 0
        while True:
            try:
                item = self._queue.get(timeout=FLUSH_INTERVAL)
            except queue.Empty:
                item = None
            if item is _STOP:
                with self._files_lock:
                    self._close_locked()
                return
            if item is not None:
                self._write(item)
                if not self._queue.empty():
                    continue
            # Report drops from here rather than from log(), which is exactly
            # when the queue has no room for the report.
            dropped = self._dropped
            if dropped > reported:
                self._write(entry(KIND_SYSTEM, LEVEL_WARN, msg=f"{dropped - reported} log entries dropped: the writer fell behind"))
                reported = dropped
            self.flush()
            self._nudge()

    def _nudge(self) -> None:
        """Lines written too soon after the last nudge stay unannounced until
        the next pass: the queue wait above comes round every FLUSH_INTERVAL,
        so the last entry of a burst is never left unseen."""
        callback = self.on_flushed
        if callback is None or not self._unannounced:
            return
        now = time.monotonic()
        if now - self._nudged_at < NUDGE_INTERVAL:
            return
        self._nudged_at = now
        self._unannounced = False
        try:
            callback()
        except Exception as error:  # noqa: BLE001 -- the log must outlive whatever is listening to it
            print(f"[logs] on_flushed failed: {error!r}", flush=True)

    def flush(self) -> None:
        with self._files_lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if self._file is None or self._pending == 0:
            return
        try:
            self._file.flush()
        except OSError as error:
            print(f"[logs] write failed: {error}", flush=True)
        self._pending = 0

    def _close_locked(self) -> None:
        self._flush_locked()
        if self._file is not None:
            self._file.close()
        self._file = None
        self._day = ""

    def _write(self, record: dict[str, Any]) -> None:
        try:
            line = self.encode(record)
        except (TypeError, ValueError) as error:
            print(f"[logs] could not encode an entry: {error}", flush=True)
            return
        day = str(record.get("ts", ""))[:10]
        if not valid_day(day):
            day = self.today()
        with self._files_lock:
            try:
                self._open_locked(day, len(line))
                self._file.write(line)
            except OSError as error:
                print(f"[logs] {error}", flush=True)
                return
            self._size += len(line)
            self._pending += 1
            self._unannounced = True
            if self._pending >= FLUSH_EVERY:
                self._flush_locked()

    def _open_locked(self, day: str, upcoming: int) -> None:
        """Make sure the open part is the right one for day with room for
        upcoming more bytes: a new day starts a new file, a full part the
        next one."""
        if self._file is not None and self._day == day and self._size + upcoming <= self.settings.max_file_bytes:
            return
        if self._file is not None and self._day == day:
            part = self._part + 1
        else:
            # After a restart, carry on in the newest part of the day.
            part = max((f.part for f in self.day_files(day) if not f.compressed), default=0)
        self._close_locked()
        while True:
            path = Path(self.settings.dir) / part_name(day, part, False)
            descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            handle = os.fdopen(descriptor, "ab", buffering=64 * 1024)
            size = os.fstat(descriptor).st_size
            # A part already full from an earlier run: go to the next. An
            # empty one takes the line whatever its size, so one huge line
            # cannot loop.
            if size > 0 and size + upcoming > self.settings.max_file_bytes:
                handle.close()
                part += 1
                continue
            self._file, self._day, self._part, self._size = handle, day, part, size
            return

    def encode(self, record: dict[str, Any]) -> bytes:
        """One line: the entry's JSON, or that encrypted and base64'd."""
        plain = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if not self.encrypt:
            return plain + b"\n"
        return base64.b64encode(encryption.xchacha_encrypt_bytes(self.key, plain)) + b"\n"

    def decode(self, line: bytes) -> bytes:
        """encode reversed, whichever form the line is in."""
        line = line.strip()
        if not line:
            raise ValueError("empty line")
        if line[:1] == b"{":
            return line
        return encryption.xchacha_decrypt_bytes(self.key, base64.b64decode(line, validate=True))

    # -----------------------------------------------------------------------
    # reading
    # -----------------------------------------------------------------------

    def today(self) -> str:
        return self.now().astimezone(timezone.utc).strftime(DAY_FORMAT)

    def files(self) -> dict[str, list[DayFile]]:
        """Every log file on disk, by day, each day's parts in order."""
        by_day: dict[str, list[DayFile]] = {}
        try:
            listing = list(os.scandir(self.settings.dir))
        except FileNotFoundError:
            return by_day
        for item in listing:
            match = _FILE.match(item.name)
            if match is None or not item.is_file():
                continue
            try:
                info = item.stat()
            except OSError:
                continue
            day = match.group(1)
            by_day.setdefault(day, []).append(
                DayFile(Path(item.path), day, int(match.group(2) or 0), bool(match.group(3)), info.st_size, info.st_mtime)
            )
        for parts in by_day.values():
            parts.sort(key=lambda f: f.part)
        return by_day

    def day_files(self, day: str) -> list[DayFile]:
        return self.files().get(day, [])

    def _scan(self, file: DayFile) -> Iterator[tuple[dict[str, Any], str]]:
        """Each entry of one file, decoded, with its JSON lowercased (what a
        free-text search matches against). Lines that do not decode -- a
        half-written last line, a line written under another key -- are
        skipped."""
        opener = gzip.open if file.compressed else open
        try:
            with opener(file.path, "rb") as handle:
                for line in handle:
                    if len(line) > MAX_LINE_BYTES:
                        continue
                    try:
                        plain = self.decode(line)
                        record = json.loads(plain)
                    except (ValueError, encryption.CipherTextError, encryption.BadKeyError):
                        continue
                    if isinstance(record, dict):
                        yield record, plain.decode("utf-8", errors="replace").lower()
        except (OSError, EOFError):
            return

    def _count_file(self, file: DayFile) -> tuple[int, int]:
        """A file's entry and error counts, cached against its size and
        modification time so listing the days does not re-read every file."""
        key = str(file.path)
        with self._counts_lock:
            cached = self._counts.get(key)
        if cached and cached[0] == file.size and cached[1] == file.modified:
            return cached[2], cached[3]
        entries = errors = 0
        for record, _ in self._scan(file):
            entries += 1
            if record.get("level") == LEVEL_ERROR:
                errors += 1
        with self._counts_lock:
            self._counts[key] = (file.size, file.modified, entries, errors)
        return entries, errors

    def days(self, query: Query) -> tuple[list[dict[str, Any]], int]:
        """Every day on disk, newest first, and the total bytes. With a query
        each day also counts its matches, and days without one are left out
        -- which means reading every line, so a search is a pass over the
        whole log."""
        self.flush()
        rows: list[dict[str, Any]] = []
        total = 0
        for day, parts in self.files().items():
            row: dict[str, Any] = {"date": day, "bytes": 0, "parts": len(parts), "compressed": False, "entries": 0, "errors": 0}
            matches = 0
            for file in parts:
                row["bytes"] += file.size
                row["compressed"] = row["compressed"] or file.compressed
                entries, errors = self._count_file(file)
                row["entries"] += entries
                row["errors"] += errors
                if not query.empty:
                    matches += sum(1 for record, text in self._scan(file) if query.match(record, text))
            total += row["bytes"]
            if not query.empty:
                if matches == 0:
                    continue
                row["matches"] = matches
            rows.append(row)
        rows.sort(key=lambda row: row["date"], reverse=True)
        return rows, total

    def read_day(self, day: str, query: Query, before: int = -1, limit: int = 200) -> tuple[list[dict[str, Any]], int | None]:
        """One page of a day, newest first: up to limit entries matching
        query, before line `before` (-1 for the newest). Each carries pos, its
        line number in the day (0-based, across parts), and the second value
        is where the following page starts, or None when there is nothing
        older."""
        if not valid_day(day):
            raise BadDayError()
        self.flush()
        window: list[dict[str, Any]] = []
        more = False
        position = 0
        for file in self.day_files(day):
            for record, text in self._scan(file):
                here = position
                position += 1
                if before >= 0 and here >= before:
                    continue
                if not query.match(record, text):
                    continue
                if len(window) == limit:
                    window.pop(0)
                    more = True
                window.append({**_named(record, query), "pos": here})
        window.reverse()
        return window, (window[-1]["pos"] if more and window else None)

    def download(self, day: str, query: Query | None = None) -> Iterator[bytes]:
        """A day as plain JSON lines, decrypted, oldest first, each with what
        query's names call its address beside the address itself."""
        if not valid_day(day):
            raise BadDayError()
        self.flush()
        for file in self.day_files(day):
            for record, _ in self._scan(file):
                yield json.dumps(_named(record, query or Query()), ensure_ascii=False).encode("utf-8") + b"\n"

    # -----------------------------------------------------------------------
    # deleting and retention
    # -----------------------------------------------------------------------

    def delete_day(self, day: str) -> None:
        """Remove every file of a day. Today is refused: it is still being
        written."""
        if not valid_day(day):
            raise BadDayError()
        if day == self.today():
            raise TodayError()
        with self._files_lock:
            if self._day == day:
                self._close_locked()
            self._remove_day_locked(day)

    def _remove_day_locked(self, day: str) -> None:
        for file in self.day_files(day):
            try:
                file.path.unlink()
            except FileNotFoundError:
                pass
            with self._counts_lock:
                self._counts.pop(str(file.path), None)

    def prune(self) -> dict[str, int]:
        """Apply config.yaml's logs settings: finished days older than
        compress_after_days are gzipped, days older than retention_days are
        deleted, and while the total is still over max_total_mb the oldest day
        is recycled. Today is never touched. The hourly prune-logs job runs
        it, and so does the Logs screen's "Prune now"."""
        result = {"compressed": 0, "deleted": 0, "bytes_before": 0, "bytes_after": 0}
        with self._files_lock:
            today = self.today()
            # Whatever is still open from before midnight is finished now.
            if self._day and self._day != today:
                self._close_locked()
            else:
                self._flush_locked()
            today_date = date.fromisoformat(today)

            by_day = self.files()
            result["bytes_before"] = _total(by_day)
            for day, parts in by_day.items():
                if day == today:
                    continue
                age = (today_date - date.fromisoformat(day)).days
                if age < 1:
                    continue
                if age > self.settings.retention_days:
                    self._remove_day_locked(day)
                    result["deleted"] += 1
                    continue
                if self.settings.compress_after_days > 0 and age >= self.settings.compress_after_days:
                    plain = [file for file in parts if not file.compressed]
                    for file in plain:
                        _compress(file)
                    if plain:
                        result["compressed"] += 1

            by_day = self.files()
            total = _total(by_day)
            for day in sorted(day for day in by_day if day != today):
                if total <= self.settings.max_total_bytes:
                    break
                self._remove_day_locked(day)
                total -= sum(file.size for file in by_day[day])
                result["deleted"] += 1
            result["bytes_after"] = total
        return result


def _named(record: dict[str, Any], query: Query) -> dict[str, Any]:
    """An entry with what the owner calls its address. Worked out on the way out:
    it is never in the file."""
    name = query.name(str(record.get("ip", "")))
    return {**record, "ip_name": name} if name else record


def _total(by_day: dict[str, list[DayFile]]) -> int:
    return sum(file.size for parts in by_day.values() for file in parts)


def rekey_files(directory: Path, staging: Path, old_key: str, new_key: str) -> int:
    """Write a copy of every log file in directory into staging, with each
    line moved from old_key to new_key and every file still gzipped or not as
    it was. Returns how many files it wrote.

    A line that does not open with old_key is copied as it stands: a
    half-written last line, or one left from a time encryption was off or
    another key was in use. Nothing could read those before, so nothing is
    lost, and dropping them would make this a tool that deletes things it does
    not understand."""
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    count = 0
    for item in sorted(os.scandir(directory), key=lambda entry: entry.name):
        if _FILE.match(item.name) is None or not item.is_file(follow_symlinks=False):
            continue
        opener = gzip.open if item.name.endswith(".gz") else open
        descriptor = os.open(staging / item.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as raw:
            with opener(item.path, "rb") as source:
                target = gzip.GzipFile(fileobj=raw, mode="wb") if item.name.endswith(".gz") else raw
                for line in source:
                    target.write(_rekey_line(line, old_key, new_key))
                if target is not raw:
                    target.close()
            raw.flush()
            os.fsync(raw.fileno())
        count += 1
    return count


def _rekey_line(line: bytes, old_key: str, new_key: str) -> bytes:
    trimmed = line.strip()
    if not trimmed or trimmed[:1] == b"{":
        return line
    try:
        plain = encryption.xchacha_decrypt_bytes(old_key, base64.b64decode(trimmed, validate=True))
    except (ValueError, encryption.CipherTextError):
        return line
    return base64.b64encode(encryption.xchacha_encrypt_bytes(new_key, plain)) + b"\n"


def _compress(file: DayFile) -> None:
    """Gzip one part next to itself, then remove the original. The .gz
    appears only once it is complete (a temporary name, then a rename), so a
    crash halfway leaves the original and a stray .tmp, never half a day."""
    target = file.path.with_name(part_name(file.day, file.part, True))
    temporary = target.with_name(target.name + ".tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as zipped, open(file.path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                zipped.write(chunk)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, target)
    file.path.unlink()
