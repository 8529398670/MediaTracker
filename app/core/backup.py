"""One file that holds a whole deployment's data, made while the server runs,
and putting one back. server/backup/backup.go is the same thing for the Go
template.

A backup is a .tar.gz holding:

    manifest.json   when it was made, and which key reads it
    app.db          a consistent copy, taken with VACUUM INTO
    config.yaml     this deployment's settings
    storage/        application files
    secret.key      only with --include-key

The activity log is left out: it can be far larger than everything else, and
losing it loses history rather than data.

secret.key stays out by default, so that a leaked backup cannot be read. The
manifest carries the key's fingerprint instead, which is what lets a restore
say "this needs a different key" before it touches anything. Keeping a copy of
the key is the operator's job, and every backup says so.

Restoring a backup made under another key -- from before a rotation, or from
another machine -- moves the restored data onto the key in use now, so
secret.key itself is never rewritten here. That matters in the container,
where it is mounted read-only.
"""
from __future__ import annotations

import gzip
import io
import json
import os
import posixpath
import shutil
import sqlite3
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Callable

from app.core import config, config_secret, db, encryption, server_lock
from app.models import sealed

# Goes up when an older restore could no longer read a backup correctly.
FORMAT_VERSION = 1

MANIFEST_NAME = "manifest.json"
DATABASE_NAME = config.DATABASE_FILE_NAME
CONFIG_NAME = config.CONFIG_FILE_NAME
KEY_NAME = config.SECRET_FILE_NAME
STORAGE_NAME = config.STORAGE_DIR_NAME

# Scheduled backups are the only ones prune may delete, and the prefix is how
# it tells: one made by hand stays until someone removes it.
AUTO_PREFIX = "auto-"
MANUAL_PREFIX = "backup-"
SUFFIX = ".tar.gz"
STAMP_FORMAT = "%Y%m%d-%H%M%S"

# A scheduled backup is due this much before its interval is up, so the hourly
# job's drift cannot push a daily backup back by a whole hour.
DUE_SLACK = timedelta(minutes=5)

# How old a temporary file has to be before it counts as left behind by a
# crash, rather than belonging to a backup still running.
STALE_AFTER_SECONDS = 24 * 60 * 60

# Here so a test can make two backups with different names.
now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


class BackupError(Exception):
    """A backup that cannot be made or restored. The message says why."""


class ServerRunningError(BackupError):
    def __init__(self) -> None:
        super().__init__("the server is running -- stop it first, restore replaces the database under it")


@dataclass
class Manifest:
    format: int
    app: str
    created_at: str
    encrypt_at_rest: bool
    key_fingerprint: str
    contains_key: bool
    schema_version: int = 0


@dataclass
class Result:
    path: Path
    size: int
    manifest: Manifest


@dataclass
class RestoreResult:
    manifest: Manifest
    rekeyed: bool = False
    saved_database: Path | None = None
    saved_storage: Path | None = None
    saved_config: Path | None = None


def create(store: db.Store, cfg: config.Config, out: str = "", include_key: bool = False, auto: bool = False) -> Result:
    """Write a backup. out is a file to write or an existing folder to write
    into; empty means the backups folder. Nothing appears at the final path
    until the whole file is written and on disk, so a backup that fails half
    way leaves nothing that looks like a backup."""
    created = now()
    target = _target_path(cfg, out, auto, created)
    directory = target.parent
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists():
        raise BackupError(f"{target} already exists")

    token = encryption.random_hex(12)
    snapshot = directory / f".snapshot-{token}"
    partial = directory / f".backup-{token}"
    manifest = Manifest(
        format=FORMAT_VERSION,
        app=cfg.project_name,
        created_at=created.isoformat(),
        encrypt_at_rest=cfg.encrypt_at_rest,
        key_fingerprint=encryption.key_fingerprint(cfg.secret_key),
        contains_key=include_key,
        schema_version=store.schema_version(),
    )
    try:
        try:
            store.snapshot(snapshot)
        except sqlite3.Error as error:
            raise BackupError(f"could not copy the database: {error}") from None
        _write_archive(partial, snapshot, cfg, manifest)
        os.replace(partial, target)
    finally:
        snapshot.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)
    return Result(path=target, size=target.stat().st_size, manifest=manifest)


def _target_path(cfg: config.Config, out: str, auto: bool, created: datetime) -> Path:
    name = f"{AUTO_PREFIX if auto else MANUAL_PREFIX}{created.strftime(STAMP_FORMAT)}{SUFFIX}"
    if not out:
        return cfg.backups.dir / name
    target = Path(out).absolute()
    return target / name if target.is_dir() else target


def _write_archive(destination: Path, snapshot: Path, cfg: config.Config, manifest: Manifest) -> None:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=1) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                _add_bytes(archive, MANIFEST_NAME, json.dumps(asdict(manifest), indent=2).encode("utf-8"))
                _add_file(archive, DATABASE_NAME, snapshot)
                _add_bytes(archive, CONFIG_NAME, Path(cfg.config_file).read_bytes())
                if manifest.contains_key:
                    _add_bytes(archive, KEY_NAME, (cfg.secret_key + "\n").encode("utf-8"))
                _add_storage(archive, Path(cfg.storage_dir))
        output.flush()
        os.fsync(output.fileno())


def _member(name: str, size: int = 0, mtime: float | None = None, directory: bool = False) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = time.time() if mtime is None else mtime
    info.mode = 0o700 if directory else 0o600
    info.type = tarfile.DIRTYPE if directory else tarfile.REGTYPE
    return info


def _add_bytes(archive: tarfile.TarFile, name: str, body: bytes) -> None:
    archive.addfile(_member(name, len(body)), io.BytesIO(body))


def _add_file(archive: tarfile.TarFile, name: str, source: Path) -> None:
    """Copy a file into the archive at the size it had when opened. A file
    that shrinks while it is read fails the backup rather than ending up in it
    cut short, and one that grows is taken as far as that size."""
    with open(source, "rb") as handle:
        info = os.fstat(handle.fileno())
        try:
            archive.addfile(_member(name, info.st_size, info.st_mtime), handle)
        except OSError as error:
            raise BackupError(f"{source} changed while it was being read: {error}") from None


def _add_storage(archive: tarfile.TarFile, root: Path) -> None:
    """Walk the app's files. Only files and folders go in: a symlink could
    point anywhere, and following one would put something in the backup nobody
    asked for. Storage is copied as it stands, not at the database's moment,
    so a file written during a backup may or may not be in it."""
    if not root.is_dir():
        return
    archive.addfile(_member(STORAGE_NAME, directory=True))
    for folder, folders, files in os.walk(root):
        relative = Path(folder).relative_to(root)
        for name in sorted(folders):
            if not (Path(folder) / name).is_symlink():
                archive.addfile(_member((Path(STORAGE_NAME) / relative / name).as_posix(), directory=True))
        for name in sorted(files):
            source = Path(folder) / name
            if source.is_symlink() or not source.is_file():
                continue
            try:
                _add_file(archive, (Path(STORAGE_NAME) / relative / name).as_posix(), source)
            except FileNotFoundError:
                pass  # Deleted during the walk: simply not in this backup.




# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------


def restore(cfg: config.Config, source: str, key_file: str = "") -> RestoreResult:
    """Replace the database and storage with a backup's. It needs the server
    stopped, and does everything that can fail in a staging folder first: the
    backup is unpacked, its key found, and every record decoded before
    anything in place is touched. What was there is kept beside it, so a
    restore can itself be undone by hand.

    config.yaml is not replaced. Settings belong to the deployment, and the
    container's copy is a mounted file; the backup's copy is left beside the
    database to compare. key_file is a key that reads the backup, for one made
    under a key this deployment no longer uses.

    A backup from an older schema needs nothing here: the next start migrates
    it like any other older database. One from a newer schema is refused."""
    _ensure_stopped(cfg)
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=cfg.app_dir))
    try:
        _unpack(Path(source), staging)
        manifest = _read_manifest(staging)
        result = RestoreResult(manifest=manifest)
        if manifest.encrypt_at_rest != cfg.encrypt_at_rest:
            raise BackupError(
                f"this backup has encrypt_at_rest {manifest.encrypt_at_rest} and config.yaml says "
                f"{cfg.encrypt_at_rest} -- set server.encrypt_at_rest to match it first"
            )
        source_key = _find_key(manifest, staging, cfg, key_file)
        staged_database = staging / DATABASE_NAME
        try:
            if source_key != cfg.secret_key:
                rewrite = sealed.rekey_record(source_key, cfg.secret_key)
                db.rekey(staged_database, source_key, cfg.secret_key, cfg.encrypt_at_rest, rewrite)
                result.rekeyed = True
            db.check_file(staged_database, cfg.secret_key, cfg.encrypt_at_rest)
        except (db.DecodeError, encryption.CipherTextError, sqlite3.Error) as error:
            raise BackupError(f"this backup does not read back, nothing was changed: {error}") from None
        # Again, because unpacking a big backup takes long enough for a
        # server to have been started in the meantime.
        _ensure_stopped(cfg)
        _swap_in(cfg, staging, now().strftime(STAMP_FORMAT), result)
        return result
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _ensure_stopped(cfg: config.Config) -> None:
    if server_lock.held(cfg.app_dir / config.SERVER_LOCK_NAME):
        raise ServerRunningError()


def _swap_in(cfg: config.Config, staging: Path, stamp: str, result: RestoreResult) -> None:
    """The only step that changes anything in place. Everything it does is a
    rename, and a failure half way puts back what it moved. The -wal and -shm
    files belong to the database they sit beside, so they move with it."""
    database = Path(cfg.database_path)
    saved = database.with_name(f"{database.name}.before-restore-{stamp}")
    moved: list[tuple[Path, Path]] = []
    for extension in ("", "-wal", "-shm"):
        current = database.with_name(database.name + extension)
        if current.exists():
            kept = saved.with_name(saved.name + extension)
            os.replace(current, kept)
            moved.append((kept, current))
    if moved:
        result.saved_database = saved
    try:
        os.replace(staging / DATABASE_NAME, database)
    except OSError:
        for kept, current in moved:
            os.replace(kept, current)
        result.saved_database = None
        raise

    storage = Path(cfg.storage_dir)
    if storage.exists():
        kept_storage = storage.with_name(f"{storage.name}.before-restore-{stamp}")
        os.replace(storage, kept_storage)
        result.saved_storage = kept_storage
    if (staging / STORAGE_NAME).exists():
        os.replace(staging / STORAGE_NAME, storage)
    else:
        storage.mkdir(mode=0o700, parents=True, exist_ok=True)

    if (staging / CONFIG_NAME).exists():
        kept_config = Path(cfg.app_dir) / f"{CONFIG_NAME}.from-backup-{stamp}"
        os.replace(staging / CONFIG_NAME, kept_config)
        result.saved_config = kept_config


def member_path(name: str) -> str | None:
    """Check one archive entry's name. A backup can come from anywhere by the
    time it is restored, so an entry only gets to be one of the names a backup
    contains: nothing absolute, nothing with a "..", nothing else."""
    trimmed = name.removesuffix("/")
    if not trimmed or "\\" in trimmed or trimmed.startswith("/") or posixpath.normpath(trimmed) != trimmed:
        return None
    if trimmed in (MANIFEST_NAME, DATABASE_NAME, CONFIG_NAME, KEY_NAME, STORAGE_NAME):
        return trimmed
    return trimmed if trimmed.startswith(STORAGE_NAME + "/") else None


def _unpack(source: Path, staging: Path) -> None:
    try:
        with tarfile.open(source, mode="r:gz") as archive:
            for member in archive:
                name = member_path(member.name)
                if name is None:
                    raise BackupError(f"{source} holds an entry a backup never contains: {member.name!r}")
                destination = staging / name
                if member.isdir():
                    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
                elif member.isreg():
                    reader = archive.extractfile(member)
                    assert reader is not None
                    _extract(reader, destination)
                else:
                    raise BackupError(f"{source} holds {member.name!r}, which is neither a file nor a folder")
    except (tarfile.TarError, EOFError, gzip.BadGzipFile) as error:
        raise BackupError(f"{source} is not a backup, or it is damaged: {error}") from None
    except OSError as error:
        raise BackupError(f"could not read {source}: {error.strerror}") from None


def _extract(reader: IO[bytes], destination: Path) -> None:
    """Refuses to write over anything: a name that appears twice in an archive
    is not something a backup does."""
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        shutil.copyfileobj(reader, output)


def _read_manifest(staging: Path) -> Manifest:
    try:
        raw = json.loads((staging / MANIFEST_NAME).read_text(encoding="utf-8"))
    except OSError:
        raise BackupError("this file has no manifest.json, so it is not a backup") from None
    except ValueError as error:
        raise BackupError(f"this backup's manifest cannot be read: {error}") from None
    version = raw.get("format", 0) if isinstance(raw, dict) else 0
    if not isinstance(version, int) or version < 1 or version > FORMAT_VERSION:
        raise BackupError(f"this backup is format {version} and this app reads up to {FORMAT_VERSION} -- restore it with the version that made it")
    try:
        manifest = Manifest(**{name: raw[name] for name in Manifest.__dataclass_fields__})
    except KeyError as error:
        raise BackupError(f"this backup's manifest has no {error}") from None
    if manifest.schema_version > db.latest_schema_version():
        raise BackupError(
            f"this backup is at schema version {manifest.schema_version} and this code only knows "
            f"{db.latest_schema_version()} -- it came from a newer version of this app; upgrade first"
        )
    if not (staging / DATABASE_NAME).is_file():
        raise BackupError("this backup has no app.db in it")
    return manifest


def _find_key(manifest: Manifest, staging: Path, cfg: config.Config, key_file: str) -> str:
    """Work out which key reads the backup: one named on the command line, the
    one in use, or the one packed inside it. The fingerprint settles it, so a
    wrong key is refused by name rather than by a decryption failure."""
    if key_file:
        key = config_secret.read_secret(Path(key_file))
        if encryption.key_fingerprint(key) != manifest.key_fingerprint:
            raise BackupError(f"{key_file} is not the key for this backup: it needs the key with fingerprint {manifest.key_fingerprint}")
        return key
    if encryption.key_fingerprint(cfg.secret_key) == manifest.key_fingerprint:
        return cfg.secret_key
    packed = staging / KEY_NAME
    if packed.is_file():
        try:
            key = config_secret.read_secret(packed)
        except config.ConfigError:
            key = ""
        if key and encryption.key_fingerprint(key) == manifest.key_fingerprint:
            return key
    raise BackupError(
        f"this backup was made with a different key (fingerprint {manifest.key_fingerprint}) and secret.key is "
        f"{encryption.key_fingerprint(cfg.secret_key)}.\n  Pass the key it was made with: --key-file path/to/secret.key.retired-<date>"
    )
