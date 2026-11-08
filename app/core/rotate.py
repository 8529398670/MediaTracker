"""Move a deployment to a new secret key. server/rotate/rotate.go is the same
thing for the Go template.

The key does four jobs, and each needs something different:

    database records    re-encrypted here (with server.encrypt_at_rest on)
    two-factor secrets  encrypted a second time inside the user record, so
                        re-encrypted here too, always: see
                        sealed.rekey_record
    activity log        every line is encrypted, gzipped days included, so
                        each file is rewritten
    session cookies     sealed with the key and held by browsers, so they stop
                        working: everyone signs in again

Backups are not touched. Each one keeps the key it was made with, which is why
the old key is kept as secret.key.retired-<time>: `manage restore --key-file`
reads an old backup with it.

Why it cannot break half way: the data and secret.key cannot change at the
same instant, so everything is staged and proved first, in <app_dir>/.rotate,
while the live files stay as they are. Failing there changes nothing. Then one
marker file decides it, and the rest is renames that anything can repeat: the
next `manage` command or server start finishes the job before it reads the key
(see config_secret.mark_rotation). So at every moment there is one way forward,
and the key and the data end up matching.

The server has to be stopped, because it holds the old key in memory and would
go on writing with it.
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.core import config, config_secret, db, encryption, server_lock
from app.core import logs
from app.core.layout import in_container
from app.models import sealed


class RotateError(Exception):
    """A rotation that cannot happen. The message says why."""


class ServerRunningError(RotateError):
    def __init__(self) -> None:
        super().__init__("the server is running -- stop it first, it holds the old key in memory and would go on writing with it")


@dataclass
class Result:
    # True when this only finished a rotation already decided.
    resumed: bool = False
    retired_key: Path | None = None
    old_fingerprint: str = ""
    new_fingerprint: str = ""
    log_files: int = 0


def run(cfg: config.Config, new_key_file: str = "") -> Result:
    """Rotate the key. new_key_file is for the container, where secret.key is a
    read-only mount: docker/rotate-key.sh writes the new key on the host and
    passes it in, this moves the data onto it, and the script swaps the key
    file itself. Empty means make a key here."""
    _ensure_stopped(cfg)

    # Only the container gets here with a marker: everywhere else, loading the
    # config already finished the job.
    if config_secret.rotation_pending(cfg.app_dir):
        config_secret.finish_rotation_data(cfg.app_dir, cfg.database_path, cfg.logs.dir)
        return Result(resumed=True)

    new_key = _choose_key(cfg, new_key_file)
    result = Result(
        old_fingerprint=encryption.key_fingerprint(cfg.secret_key),
        new_fingerprint=encryption.key_fingerprint(new_key),
    )
    try:
        result.log_files = stage(cfg, new_key)
        # Staging can take a while, and a server started in the meantime
        # would be writing to the file about to be replaced.
        _ensure_stopped(cfg)
    except BaseException:
        shutil.rmtree(config_secret.rotation_dir(cfg.app_dir), ignore_errors=True)
        raise

    following = cfg.secret_file.with_name(cfg.secret_file.name + config_secret.SECRET_NEXT_SUFFIX)
    if not new_key_file:
        # A .next with no marker is left from a run that never committed.
        following.unlink(missing_ok=True)
        config_secret.write_secret(following, new_key)

    config_secret.mark_rotation(cfg.app_dir)
    config_secret.finish_rotation_data(cfg.app_dir, cfg.database_path, cfg.logs.dir)
    if new_key_file:
        return result
    result.retired_key = config_secret.finish_rotation_key(cfg.secret_file)
    config_secret.clear_rotation(cfg.app_dir)
    return result


def _choose_key(cfg: config.Config, new_key_file: str) -> str:
    if not new_key_file:
        if in_container():
            raise RotateError("secret.key is read-only in here -- run docker/rotate-key.sh on the host")
        return config_secret.generate_secret()
    key = config_secret.read_secret(Path(new_key_file))
    if key == cfg.secret_key:
        raise RotateError("the new key is the key already in use")
    return key


def stage(cfg: config.Config, new_key: str) -> int:
    """Everything that can fail, on copies. Nothing live is touched."""
    directory = config_secret.rotation_dir(cfg.app_dir)
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(mode=0o700, parents=True)

    database = Path(cfg.database_path)
    if database.is_file():
        staged = directory / database.name
        try:
            # VACUUM INTO, not a file copy: it takes in whatever a crash left
            # in app.db-wal.
            db.Store(database, cfg.secret_key, cfg.encrypt_at_rest).snapshot(staged)
            db.rekey(staged, cfg.secret_key, new_key, cfg.encrypt_at_rest, sealed.rekey_record(cfg.secret_key, new_key))
            db.check_file(staged, new_key, cfg.encrypt_at_rest)
        except (db.DecodeError, encryption.CipherTextError, sqlite3.Error) as error:
            raise RotateError(f"nothing was changed: {error}") from None

    if not cfg.encrypt_at_rest:
        return 0
    return logs.rekey_files(Path(cfg.logs.dir), directory / config.LOGS_DIR_NAME, cfg.secret_key, new_key)


def _ensure_stopped(cfg: config.Config) -> None:
    if server_lock.held(cfg.app_dir / config.SERVER_LOCK_NAME):
        raise ServerRunningError()
