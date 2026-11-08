"""The secret key, in its own file.

It used to be server.secret_key in config.yaml. It moved out so that
config.yaml could be edited while the server runs -- by the owner's Settings
screen, by hand, by `config set` -- and mounted writable into the container,
without any of that ever being able to read or replace the key. secret.key is
written once and then only read, until a rotation replaces it.

It sits beside config.yaml, wherever that is:

    ./config/secret.key                  a source checkout
    ~/.config/<slug>/secret.key          the app run from anywhere else
    /app/config/secret.key               the container, mounted read-only

server/config/secret.go is the same logic for the Go template.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.core import config
from app.core.config import ConfigError, check_secret_key
from app.core.layout import in_container


def secret_path_for(config_path: Path) -> Path:
    """The secret.key that goes with a config.yaml: the one in the same
    folder. One rule for a checkout, an install under ~/.config and the
    container means there is nothing else to configure, and nothing to get
    wrong when moving a deployment."""
    return Path(config_path).parent / config.SECRET_FILE_NAME


def generate_secret() -> str:
    """A fresh key: 32 random bytes as 64 hex characters."""
    from app.core import encryption  # imported here so `health` stays light

    return encryption.generate_key_hex()


def read_secret(path: Path) -> str:
    """Read and check secret.key."""
    try:
        key = Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ConfigError(f"could not read {path}: {error.strerror}") from None
    check_secret_key(key, str(path))
    return key


def write_secret(path: Path, key: str) -> None:
    """Create secret.key, refusing to overwrite one: an existing key is what
    existing data was written with. The key is read back before this
    returns, so a full disk or a lying filesystem is found now rather than
    the next time the server needs the key. FileExistsError passes through
    untouched, for the migration to tell apart."""
    check_secret_key(key, "the new secret key")
    path = Path(path)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        raise ConfigError(f"could not create {path.parent}: {error.strerror}") from None
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(key + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as error:
        path.unlink(missing_ok=True)
        raise ConfigError(f"could not write {path}: {error.strerror}") from None
    sync_dir(path.parent)
    if read_secret(path) != key:
        raise ConfigError(f"{path} does not read back as the key just written to it")


# ---------------------------------------------------------------------------
# key rotation
#
# A rotation (see app/core/rotate.py) changes two things that cannot change at
# the same instant: the data, and secret.key. So it stages everything first,
# and then writes one marker file. Before the marker, nothing has happened:
# the data and the key still match, and the staging folder can be thrown away.
# After it, the rotation is decided, and everything left is a rename that can
# be repeated: anything that finds the marker finishes the job forward.
#
# That is why this part lives here. The next thing to run after a crash has to
# finish before it reads the key, and load is what reads the key.
# ---------------------------------------------------------------------------

# The staging folder, inside the app directory so the renames out of it stay
# on one filesystem.
ROTATION_DIR_NAME = ".rotate"
ROTATION_MARKER = "pending"
# Beside secret.key.
SECRET_NEXT_SUFFIX = ".next"
SECRET_RETIRED_SUFFIX = ".retired-"


def rotation_dir(app_dir: Path) -> Path:
    return Path(app_dir) / ROTATION_DIR_NAME


def rotation_pending(app_dir: Path) -> bool:
    """A rotation that has been decided but not finished."""
    return (rotation_dir(app_dir) / ROTATION_MARKER).is_file()


def mark_rotation(app_dir: Path) -> None:
    """The point of no return. Everything staged must already be on disk,
    which is why the folder is synced before and after."""
    directory = rotation_dir(app_dir)
    sync_dir(directory)
    descriptor = os.open(directory / ROTATION_MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.fsync(descriptor)
    os.close(descriptor)
    sync_dir(directory)


def finish_rotation_data(app_dir: Path, database_path: Path, logs_dir: Path) -> None:
    """Move the staged database and log files into place. A file already moved
    is simply not there to move, so this can be repeated.

    Any -wal and -shm files go first. They belong to the old database, whose
    contents the staged copy already holds, and SQLite would replay a leftover
    log onto the new file and corrupt it."""
    directory = rotation_dir(app_dir)
    database_path = Path(database_path)
    staged = directory / database_path.name
    if staged.is_file():
        for extension in ("-wal", "-shm"):
            database_path.with_name(database_path.name + extension).unlink(missing_ok=True)
        os.replace(staged, database_path)
        sync_dir(database_path.parent)
    staged_logs = directory / config.LOGS_DIR_NAME
    if staged_logs.is_dir():
        for entry in sorted(staged_logs.iterdir()):
            os.replace(entry, Path(logs_dir) / entry.name)
        sync_dir(Path(logs_dir))


def finish_rotation_key(secret_path: Path) -> Path | None:
    """Retire secret.key and put the new key in its place. The old key is kept
    because every backup made before now still needs it. Returns where it
    went, or None when there was nothing left to do."""
    secret_path = Path(secret_path)
    following = secret_path.with_name(secret_path.name + SECRET_NEXT_SUFFIX)
    if not following.is_file():
        return None
    new_key = read_secret(following)
    old_key = read_secret(secret_path)
    retired = None
    if old_key != new_key:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        retired = secret_path.with_name(f"{secret_path.name}{SECRET_RETIRED_SUFFIX}{stamp}")
        try:
            write_secret(retired, old_key)
        except FileExistsError:
            pass  # A run cut short in this same second wrote it.
    os.replace(following, secret_path)
    sync_dir(secret_path.parent)
    return retired


def clear_rotation(app_dir: Path) -> None:
    """End it. The marker goes first: a folder left without one is only
    something to clear away, which the next rotation does."""
    directory = rotation_dir(app_dir)
    (directory / ROTATION_MARKER).unlink(missing_ok=True)
    sync_dir(directory)
    shutil.rmtree(directory, ignore_errors=True)


def finish_rotation(app_dir: Path, database_path: Path, config_path: Path) -> None:
    """What load does on finding the marker."""
    finish_rotation_data(app_dir, database_path, Path(app_dir) / config.LOGS_DIR_NAME)
    finish_rotation_key(secret_path_for(config_path))
    clear_rotation(app_dir)


@dataclass
class MigrationResult:
    """What migrate_legacy_secret did. moved: the key was copied from
    config.yaml into a new secret.key. removed: server.secret_key's line was
    taken out of config.yaml -- after moved, or because an earlier move was
    interrupted after writing secret.key."""

    secret_file: Path
    moved: bool = False
    removed: bool = False


def migrate_legacy_secret(config_path: Path) -> MigrationResult:
    """Move server.secret_key out of a config.yaml written before secret.key
    existed. Safe to run any number of times, and does nothing to a file that
    has no key in it.

    The order is what makes it safe to interrupt: secret.key is written and
    read back first, and only then is the line removed from config.yaml. Stop
    it in between and the next run finds both holding the same key and just
    removes the line. Find them holding different keys and it stops -- which
    one encrypted the data is not something to guess."""
    from app.core import yaml_edit
    from app.core.config_live import write_config_file

    config_path = Path(config_path)
    result = MigrationResult(secret_file=secret_path_for(config_path))
    try:
        # Bytes, decoded: read_text would turn CRLF into LF and rewrite every line.
        raw = config_path.read_bytes().decode("utf-8")
    except OSError as error:
        raise ConfigError(f"could not read {config_path}: {error.strerror}") from None
    legacy = config.decode_over_defaults(raw, str(config_path)).server.secret_key.strip()
    if legacy == "":
        return result
    check_secret_key(legacy, f"server.secret_key in {config_path}")

    if not result.secret_file.is_file():
        try:
            write_secret(result.secret_file, legacy)
            result.moved = True
        except FileExistsError:
            pass  # Another process got there first; compare with what it wrote.
    if not result.moved:
        existing = read_secret(result.secret_file)
        if existing != legacy:
            raise ConfigError(
                f"{config_path} has server.secret_key, and {result.secret_file} holds a different key.\n"
                f"  Refusing to guess which one encrypted your data. Keep the right one in {result.secret_file}\n"
                f"  and delete the secret_key line from {config_path}."
            )

    try:
        edited = yaml_edit.edit_yaml(raw, [], ["server.secret_key"], None)
        if config.decode_over_defaults(edited, str(config_path)).server.secret_key != "":
            raise ConfigError("server.secret_key is still set after removing it")
    except ConfigError as error:
        raise ConfigError(
            f"the key is safe in {result.secret_file}, but removing server.secret_key from {config_path} "
            f"failed ({error}) -- delete that line by hand"
        ) from None
    write_config_file(config_path, edited, in_place=False, backup_path=None)
    result.removed = True
    return result


@dataclass
class SecretState:
    """What resolve_secret settled on. rewrote: config.yaml was changed (the
    key's line removed)."""

    key: str = ""
    created: bool = False
    migrated: bool = False
    rewrote: bool = False
    warning: str = ""


def resolve_secret(file: config.File, config_path: Path, database_path: Path) -> SecretState:
    """Find the key for the server to run on.

    - secret.key exists: that is the key. A server.secret_key still in
      config.yaml must match it (an interrupted migration) and is removed; a
      different one stops everything.
    - server.secret_key and no secret.key: an older config.yaml. Move it.
    - neither: a fresh install gets a new key. One with a database does not
      -- a new key cannot read it, so the old one has to come back.

    Inside the container nothing is written: config/ belongs to the host, and
    docker/run.sh does the move there before it starts anything."""
    secret_path = secret_path_for(config_path)
    legacy = file.server.secret_key.strip()
    state = SecretState()

    if legacy:
        if in_container():
            if not secret_path.is_file():
                raise ConfigError(
                    f"{config_path} still holds server.secret_key and there is no {secret_path} -- run docker/run.sh "
                    "on the host, which moves the key into config/secret.key and mounts it"
                )
            state.key = read_secret(secret_path)
            if state.key != legacy:
                raise ConfigError(
                    f"{config_path} has server.secret_key, and {secret_path} holds a different key -- refusing to "
                    "guess which one encrypted your data"
                )
            state.warning = f"{config_path} still holds server.secret_key (the same key as {secret_path}); docker/run.sh removes it"
            return state
        moved = migrate_legacy_secret(config_path)
        state.migrated = moved.moved
        state.rewrote = moved.removed
        state.key = read_secret(secret_path)
        return state

    if secret_path.is_file():
        state.key = read_secret(secret_path)
        return state
    if in_container():
        raise ConfigError(f"no secret key at {secret_path} -- docker/run.sh mounts the project's config/secret.key there")
    if Path(database_path).is_file():
        raise ConfigError(
            f"no secret key at {secret_path}, and {database_path} exists.\n"
            "  Restore secret.key from your backup -- a new key cannot read existing data."
        )
    state.key = generate_secret()
    write_secret(secret_path, state.key)
    state.created = True
    return state


def sync_dir(directory: Path) -> None:
    """Make a rename or a new file in directory durable. Windows has no way
    to open a directory for this, and does not need it."""
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)
