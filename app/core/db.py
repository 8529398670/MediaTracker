"""The database: one SQLite file, used as a store of records.

Every model goes through this module and nothing else touches SQLite. Each
record is a JSON document, and with server.encrypt_at_rest on (the default)
it is XChaCha-encrypted with the key in secret.key before it is written. Doing
that here, in encode/decode, is what makes at-rest encryption a single switch
instead of something each model has to remember -- and it means the answer to
"where does data get written" is one file.

The shape mirrors a key/value store on purpose: a "bucket" is a table of
(key, value) rows. Encrypted values cannot be queried with SQL, so models look
records up by key and scan a bucket for anything else -- the same trade the
Go template makes with bolt, and fine at the size of app this template is for.
A feature that genuinely needs SQL over its data can add its own table through
connect(); its columns are then not encrypted at rest, and that is a decision
to make deliberately (see references/architecture.md).

SQLite runs in WAL mode, so the server and a `manage` command can both have
the file open: readers never block, and a writer waits (up to the busy
timeout) for another writer rather than failing.

Everything here is synchronous. Call it from a thread, never directly from an
async handler -- see run_in_threadpool in app/routes/helpers.py.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from app.core import encryption, server_lock

# Bucket names. Add new ones here and to BUCKETS so their tables are created
# at startup -- a table that only gets created on first write is an
# "no such table" error waiting for the first reader.
BUCKET_USERS = "users"
BUCKET_SESSIONS = "sessions"
BUCKET_LOGIN_TOKENS = "login_tokens"
BUCKET_API_KEYS = "api_keys"
BUCKET_INVITE_LINKS = "invite_links"
BUCKET_SIGN_IN_CHALLENGES = "sign_in_challenges"
BUCKET_JOBS = "jobs"
BUCKET_WEBHOOKS = "webhooks"
# The outbox: see app/core/webhooks.py.
BUCKET_WEBHOOK_DELIVERIES = "webhook_deliveries"
# Describes uploads; the bytes are on disk. See app/models/files.py.
BUCKET_FILES = "files"
BUCKET_META = "meta"

# The media library. Titles are shared by everyone; user_state is one
# person's relationship with one title, keyed "<user id>:<title id>". See
# app/models/titles.py and app/models/user_state.py.
BUCKET_TITLES = "titles"
BUCKET_USER_STATE = "user_state"
BUCKET_TYPES = "types"
BUCKET_SOURCES = "sources"
# Per person: card layout and last query per screen, saved views, and the
# Discover verdicts ("skip this one").
BUCKET_PREFS = "prefs"
BUCKET_VIEWS = "views"
BUCKET_PLAYLISTS = "playlists"
BUCKET_VERDICTS = "verdicts"
# Book-keeping for undo: "these two are not duplicates", what a merge
# replaced, which titles an import created.
BUCKET_DUPE_DISMISSALS = "dupe_dismissals"
BUCKET_MERGES = "merges"
BUCKET_IMPORT_BATCHES = "import_batches"

BUCKETS = (
    BUCKET_USERS,
    BUCKET_SESSIONS,
    BUCKET_LOGIN_TOKENS,
    BUCKET_API_KEYS,
    BUCKET_INVITE_LINKS,
    BUCKET_SIGN_IN_CHALLENGES,
    BUCKET_JOBS,
    BUCKET_WEBHOOKS,
    BUCKET_WEBHOOK_DELIVERIES,
    BUCKET_FILES,
    BUCKET_META,
    BUCKET_TITLES,
    BUCKET_USER_STATE,
    BUCKET_TYPES,
    BUCKET_SOURCES,
    BUCKET_PREFS,
    BUCKET_VIEWS,
    BUCKET_PLAYLISTS,
    BUCKET_VERDICTS,
    BUCKET_DUPE_DISMISSALS,
    BUCKET_MERGES,
    BUCKET_IMPORT_BATCHES,
)

# How long a writer waits for another writer before giving up. Without it a
# second process (a `manage` command during a busy moment) fails at once with
# "database is locked" instead of simply waiting its turn.
BUSY_TIMEOUT_SECONDS = 5.0

Record = dict[str, Any]
Key = int | str


class DecodeError(Exception):
    """A stored record that cannot be read back -- almost always a
    secret.key that is not the one the record was written with."""


def _table(bucket: str) -> str:
    # Table names cannot be bound as parameters, so only the names declared
    # above are ever interpolated into SQL.
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r} -- add it to BUCKETS in app/core/db.py")
    return f'"{bucket}"'


class Store:
    def __init__(self, path: Path, secret_key: str, encrypt_at_rest: bool) -> None:
        self.path = path
        self._secret_key = secret_key
        self._encrypt_at_rest = encrypt_at_rest

    # -- connections -------------------------------------------------------

    def connect(self) -> sqlite3.Connection:
        """A fresh connection in autocommit mode; transactions are opened
        explicitly where they are needed. One connection per operation keeps
        this safe to call from any thread."""
        connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
        connection.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_SECONDS * 1000)}")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        """A write transaction taken up front (BEGIN IMMEDIATE). Taking the
        write lock before the first read is what closes the lost-update gap:
        two callers cannot both read the old row and then both write."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    def initialise(self) -> None:
        with self._connection() as connection:
            # WAL is a property of the file, so setting it once is enough;
            # doing it on every start is harmless and keeps it true.
            connection.execute("PRAGMA journal_mode = WAL")
            for bucket in BUCKETS:
                # The key column is deliberately untyped: integer keys (user
                # ids) stay integers and sort numerically, string keys
                # (credential ids) stay strings.
                connection.execute(
                    f"CREATE TABLE IF NOT EXISTS {_table(bucket)} (key PRIMARY KEY NOT NULL, value BLOB NOT NULL)"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sequences (bucket TEXT PRIMARY KEY NOT NULL, value INTEGER NOT NULL)"
            )

    def schema_version(self) -> int:
        """The version this database is at. See "data migrations" below."""
        with self._connection() as connection:
            return connection.execute("PRAGMA user_version").fetchone()[0]

    def snapshot(self, path: Path) -> None:
        """Write a consistent copy of the database to path while the server
        goes on working: VACUUM INTO reads one fixed moment, and picks up what
        is still in the -wal file, which copying app.db would miss. The file
        keeps its encryption, so it needs the same key to read. Made 0600 up
        front, because SQLite would otherwise use the umask."""
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        with self._connection() as connection:
            connection.execute("VACUUM INTO ?", (str(path),))

    # -- encoding ----------------------------------------------------------

    def encode(self, record: Record) -> bytes:
        raw = json.dumps(record, separators=(",", ":"), sort_keys=True).encode("utf-8")
        if not self._encrypt_at_rest:
            return raw
        return encryption.xchacha_encrypt_bytes(self._secret_key, raw)

    def decode(self, raw: bytes) -> Record:
        plain = raw
        if self._encrypt_at_rest:
            try:
                plain = encryption.xchacha_decrypt_bytes(self._secret_key, bytes(raw))
            except encryption.CipherTextError:
                raise DecodeError(
                    "could not decrypt a stored record -- is secret.key "
                    "the same key it was written with?"
                ) from None
        try:
            return json.loads(plain)
        except (ValueError, UnicodeDecodeError):
            raise DecodeError(
                "a stored record is not valid JSON -- was server.encrypt_at_rest changed after data was written?"
            ) from None

    # -- the record API ----------------------------------------------------

    def put(self, bucket: str, key: Key, record: Record) -> None:
        encoded = self.encode(record)
        with self._connection() as connection:
            connection.execute(f"INSERT OR REPLACE INTO {_table(bucket)} (key, value) VALUES (?, ?)", (key, encoded))

    def get(self, bucket: str, key: Key) -> Record | None:
        """None means "no such record", which callers need to tell apart from
        a record that exists."""
        with self._connection() as connection:
            row = connection.execute(f"SELECT value FROM {_table(bucket)} WHERE key = ?", (key,)).fetchone()
        return None if row is None else self.decode(row[0])

    def delete(self, bucket: str, key: Key) -> None:
        with self._connection() as connection:
            connection.execute(f"DELETE FROM {_table(bucket)} WHERE key = ?", (key,))

    def all(self, bucket: str) -> list[tuple[Key, Record]]:
        """Every record in a bucket, in key order."""
        with self._connection() as connection:
            rows = connection.execute(f"SELECT key, value FROM {_table(bucket)} ORDER BY key").fetchall()
        return [(key, self.decode(value)) for key, value in rows]

    def next_sequence(self, bucket: str) -> int:
        """Monotonic ids handed out inside a write transaction, so two
        concurrent creates can never collide on the same id."""
        _table(bucket)
        with self._write() as connection:
            connection.execute(
                "INSERT INTO sequences (bucket, value) VALUES (?, 1) "
                "ON CONFLICT (bucket) DO UPDATE SET value = value + 1",
                (bucket,),
            )
            return connection.execute("SELECT value FROM sequences WHERE bucket = ?", (bucket,)).fetchone()[0]

    def update_value(self, bucket: str, key: Key, mutate: Callable[[Record], None]) -> Record | None:
        """Read a record, hand it to mutate (which changes it in place), and
        write the result back inside one write transaction. Returns the
        updated record, or None if there was no such record.

        The obvious alternative -- get, change, put -- has a lost update
        hiding in the gap between the two: two concurrent callers both read
        the old record and the second put silently discards the first one's
        change. Anything that edits an existing record should come through
        here."""
        table = _table(bucket)
        with self._write() as connection:
            row = connection.execute(f"SELECT value FROM {table} WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            record = self.decode(row[0])
            mutate(record)
            connection.execute(f"UPDATE {table} SET value = ? WHERE key = ?", (self.encode(record), key))
            return record

    def delete_where(self, bucket: str, match: Callable[[Key, Record], bool]) -> int:
        """Remove every record match() accepts, inside one write transaction.

        Encrypted values cannot be filtered in SQL, so this decodes each row.
        Doing the scan and the deletes in one transaction matters: a record
        that starts matching between a separate read pass and the deletes
        would be missed, which for session revocation means a session created
        mid-sweep outlives the account it belongs to."""
        table = _table(bucket)
        with self._write() as connection:
            rows = connection.execute(f"SELECT key, value FROM {table}").fetchall()
            doomed = [(key,) for key, value in rows if match(key, self.decode(value))]
            connection.executemany(f"DELETE FROM {table} WHERE key = ?", doomed)
            return len(doomed)

    @contextmanager
    def transaction(self) -> Iterator["Transaction"]:
        """A write transaction with the same record API, for the operations
        that have to be atomic across several records or buckets: turning a
        login link into a session, disabling an account together with every
        credential it holds, checking an API key quota and inserting the key.

        It takes the write lock up front (BEGIN IMMEDIATE), so no other write
        interleaves with it. That is the point -- and the cost: keep slow work
        (bcrypt, network calls) outside, because every other writer waits."""
        with self._write() as connection:
            yield Transaction(self, connection)


class Transaction:
    def __init__(self, store: Store, connection: sqlite3.Connection) -> None:
        self._store = store
        self._connection = connection

    def set_schema_version(self, version: int) -> None:
        """In this transaction, so a migration and its version commit together."""
        self._connection.execute(f"PRAGMA user_version = {int(version)}")

    def get(self, bucket: str, key: Key) -> Record | None:
        row = self._connection.execute(f"SELECT value FROM {_table(bucket)} WHERE key = ?", (key,)).fetchone()
        return None if row is None else self._store.decode(row[0])

    def put(self, bucket: str, key: Key, record: Record) -> None:
        self._connection.execute(
            f"INSERT OR REPLACE INTO {_table(bucket)} (key, value) VALUES (?, ?)", (key, self._store.encode(record))
        )

    def delete(self, bucket: str, key: Key) -> None:
        self._connection.execute(f"DELETE FROM {_table(bucket)} WHERE key = ?", (key,))

    def all(self, bucket: str) -> list[tuple[Key, Record]]:
        rows = self._connection.execute(f"SELECT key, value FROM {_table(bucket)} ORDER BY key").fetchall()
        return [(key, self._store.decode(value)) for key, value in rows]

    def next_sequence(self, bucket: str) -> int:
        """Store.next_sequence inside this transaction, for a record that has
        to be created together with something else -- a user and the owner
        marker that names it, for one."""
        _table(bucket)
        self._connection.execute(
            "INSERT INTO sequences (bucket, value) VALUES (?, 1) "
            "ON CONFLICT (bucket) DO UPDATE SET value = value + 1",
            (bucket,),
        )
        return self._connection.execute("SELECT value FROM sequences WHERE bucket = ?", (bucket,)).fetchone()[0]

    def delete_where(self, bucket: str, match: Callable[[Key, Record], bool]) -> int:
        doomed = [(key,) for key, record in self.all(bucket) if match(key, record)]
        self._connection.executemany(f"DELETE FROM {_table(bucket)} WHERE key = ?", doomed)
        return len(doomed)


# ---------------------------------------------------------------------------
# data migrations
#
# How a stored record changes shape in a deployed app. Records are JSON, so
# most changes need nothing here: a new optional field reads as absent from
# older records (use record.get), and a new bucket is created at startup. A
# migration is for the rest: a field renamed or split, a value changed to a new
# meaning, records moved between buckets.
#
# The database's version (PRAGMA user_version) is how many of MIGRATIONS have
# run on it. open_store runs whatever is missing, in order, before anything
# else sees the data:
#
#   - A new database has nothing to migrate, so it is stamped with the latest
#     version and none of them run.
#   - An existing one is copied first, to app.db.before-migration-v<N>-<time>,
#     so a migration that turns out wrong can be undone by hand.
#   - Each migration runs in one transaction with the version bump, so a
#     failure leaves the database exactly as the last one left it, the server
#     refuses to start and says which one failed, and the next start tries it
#     again.
#   - A database newer than this code is refused rather than read: old code
#     would not know what the new shape means, and could write it back wrong.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Migration:
    """One step. up gets the same record API as Store.transaction."""

    name: str
    up: Callable[["Transaction"], None]


# Every step this app has ever needed. Add to the end, and never edit, reorder
# or remove one that has shipped: a database's version is a position in this
# list. references/architecture.md has a worked example.
MIGRATIONS: list[Migration] = []


def latest_schema_version() -> int:
    return len(MIGRATIONS)


def _migrate(store: Store, fresh: bool, steps: Sequence[Migration], server_lock_path: Path | None) -> None:
    version = store.schema_version()
    latest = len(steps)
    if version > latest:
        raise RuntimeError(
            f"the database is at schema version {version} and this code only knows {latest} -- it was written by a "
            "newer version of this app; run that version, or restore a backup"
        )
    if fresh:
        with store._connection() as connection:
            connection.execute(f"PRAGMA user_version = {latest}")
        return
    if version == latest:
        return

    # manage shares the database with a running server, which would carry on
    # with the old shape in memory if the file changed under it.
    if server_lock_path is not None and server_lock.held(server_lock_path):
        raise RuntimeError(
            f"the database is at schema version {version} and this code expects {latest}, and a server is running on "
            "it -- restart the server, which upgrades the database itself"
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    kept = store.path.with_name(f"{store.path.name}.before-migration-v{version}-{stamp}")
    try:
        store.snapshot(kept)
    except (OSError, sqlite3.Error) as error:
        raise RuntimeError(f"could not copy the database before migrating it: {error}") from None
    print(f"[migrate] schema version {version} to {latest}, the previous database is kept at {kept}", flush=True)

    for index in range(version, latest):
        step = steps[index]
        try:
            with store.transaction() as tx:
                step.up(tx)
                tx.set_schema_version(index + 1)
        except Exception as error:  # noqa: BLE001 -- whatever a migration raises is reported the same way
            raise RuntimeError(f"migration {index + 1} ({step.name}) failed, the database is unchanged by it: {error}") from error
        print(f"[migrate] {index + 1}: {step.name}", flush=True)


def _buckets_in(connection: sqlite3.Connection) -> list[str]:
    """The buckets this file has a table for. A file a backup brought back can
    be older than the code: it has no table for a bucket added since, and that
    means empty, not damaged -- open_store creates the table once it is live."""
    tables = {name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    return [bucket for bucket in BUCKETS if bucket in tables]


def check_file(path: Path, secret_key: str, encrypt_at_rest: bool) -> None:
    """Decode every record in a database file nothing is using, so a backup
    can be proved readable before it replaces anything. Raises DecodeError, or
    sqlite3.Error for a file that is not a database."""
    store = Store(path, secret_key, encrypt_at_rest)
    with store._connection() as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise DecodeError(f"the file fails SQLite's integrity check: {result}")
        for bucket in _buckets_in(connection):
            for (value,) in connection.execute(f"SELECT value FROM {_table(bucket)}"):
                store.decode(value)


def rekey(path: Path, old_key: str, new_key: str, encrypt_at_rest: bool, rewrite: Callable[[str, Record], None]) -> None:
    """Rewrite a database file nothing is using from old_key to new_key, in
    one transaction, so it is all or nothing. Every record goes through
    rewrite, which changes it in place, for the fields a model encrypts a
    second time on its own (see sealed.rekey_record). With encrypt_at_rest
    off only rewrite has anything to change. Tables an app added through
    connect() are not encrypted by this module, so they are left alone."""
    reader = Store(path, old_key, encrypt_at_rest)
    writer = Store(path, new_key, encrypt_at_rest)
    with reader._write() as connection:
        for bucket in _buckets_in(connection):
            table = _table(bucket)
            for key, value in connection.execute(f"SELECT key, value FROM {table}").fetchall():
                record = reader.decode(value)
                rewrite(bucket, record)
                connection.execute(f"UPDATE {table} SET value = ? WHERE key = ?", (writer.encode(record), key))


def open_store(
    database_path: Path,
    secret_key: str,
    encrypt_at_rest: bool,
    server_lock_path: Path | None = None,
    migrations: Sequence[Migration] | None = None,
) -> Store:
    """Create the file if needed, make sure every bucket's table exists, and
    bring it up to the latest schema. server_lock_path is for a caller that
    is not the server: it stops that caller migrating under a running one.
    migrations is for a test to bring its own."""
    store = Store(database_path, secret_key, encrypt_at_rest)
    fresh = not database_path.exists() or database_path.stat().st_size == 0
    try:
        # Created 0600 up front: SQLite would otherwise use the umask, and it
        # gives the -wal and -shm files the database file's own mode.
        if not database_path.exists():
            os.close(os.open(database_path, os.O_WRONLY | os.O_CREAT, 0o600))
        store.initialise()
        _migrate(store, fresh, MIGRATIONS if migrations is None else migrations, server_lock_path)
    except OSError as error:
        raise RuntimeError(f"could not create the database at {database_path}: {error.strerror}") from None
    except sqlite3.Error as error:
        raise RuntimeError(f"could not open the database at {database_path}: {error}") from None
    return store
