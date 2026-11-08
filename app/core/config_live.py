"""The running configuration, and the one way it changes.

config.yaml can change under a running server two ways: the owner saves the
Settings screen (Holder.save), or someone edits the file -- by hand, with
`config set`, from another machine -- and the watcher notices (Holder.poll).
Both end in Holder.apply, which validates the whole file and either swaps in
a new Config or changes nothing. A file that does not validate is reported
and ignored; the server keeps running on the last version that did.

Only [live] keys (see config_schema.py) change in the running Config. A
[restart] key is saved and shown as pending, but the server keeps the value
it started with -- live_config copies the boot Config and overwrites only
the live fields, so a restart-only setting cannot leak in half-applied.

Everything that reads configuration per request reads Holder.get(), never a
Config it was handed at startup. That is what makes a change live: the next
request sees the new object.

server/config/live.go is the same for the Go template.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.core import config, config_schema
from app.core.config import Config, ConfigError, ValidationError
from app.core.config_schema import MODE_LIVE, MODE_SCRIPTS
from app.core.config_schema import MODE_RESTART
from app.core.layout import PINNED, in_container


class StaleError(ConfigError):
    """The container's mounted config.yaml was replaced on the host (an
    editor that saves by writing a new file and renaming it over the old
    one). The mount still shows the old file, so neither reading nor writing
    it means anything until the container restarts."""

    def __init__(self) -> None:
        super().__init__("config.yaml was replaced on the host; restart the container to see the new one")


class ReadOnlyError(ConfigError):
    """This process cannot write config.yaml."""

    def __init__(self) -> None:
        super().__init__("config.yaml is not writable by the server")


class LockedError(ConfigError):
    """A key that cannot be changed from here -- docker.* inside the
    container, and what the image pins."""


class ConflictError(ConfigError):
    """config.yaml changed since the client read it."""

    def __init__(self, version: str) -> None:
        super().__init__("config.yaml changed since it was loaded")
        self.version = version


class UnknownSettingError(ConfigError):
    def __init__(self, key: str) -> None:
        super().__init__(f"unknown setting {key!r}")
        self.key = key


def version(raw: str) -> str:
    """Identifies one exact config.yaml: the client sends back the one it
    loaded, and a save is refused if the file is no longer that one."""
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_raw(path: Path) -> str:
    """The file exactly as it is -- line endings included, which read_text
    would normalise and the in-place editor must keep."""
    return Path(path).read_bytes().decode("utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def live_config(boot: Config, boot_file: config.File, file: config.File) -> Config:
    """boot with the [live] keys taken from file. Every live key in
    defaults.yaml must be copied here; test_config_schema.py checks that a
    live key changes the result and a restart key does not."""
    # The link address follows server.public_url, but host, port and the
    # docker section are whatever the server and container started with.
    effective = replace(
        file,
        server=replace(file.server, host=boot_file.server.host, port=boot_file.server.port),
        docker=boot_file.docker,
    )
    url, url_source = config.server_url(effective)
    return replace(
        boot,
        url=url,
        url_source=url_source,
        secure_cookies=file.server.secure_cookies,
        rate_limit_max=file.server.rate_limit_max,
        rate_limit_window_seconds=file.server.rate_limit_window_seconds,
        rate_limit_signin_max=file.server.rate_limit_signin_max,
        mcp_enabled=file.server.mcp,
        maintenance=file.server.maintenance,
        announcement=file.server.announcement,
        trust_proxy=file.server.trust_proxy,
        trusted_proxies=tuple(entry.strip() for entry in file.server.trusted_proxies),
        proxy_header=file.server.proxy_header,
        session_ttl_seconds=file.auth.session_ttl_seconds,
        session_max_age_seconds=file.auth.session_max_age_seconds,
        login_token_ttl_seconds=file.auth.login_token_ttl_seconds,
        multi_use_login_token_ttl_seconds=file.auth.multi_use_login_token_ttl_seconds,
        api_keys_enabled=file.auth.api_keys,
        passwords_enabled=file.auth.passwords,
        two_factor_enabled=file.auth.two_factor,
        invite_links_enabled=file.auth.invite_links,
        api_key_ttl_seconds=file.auth.api_key_ttl_seconds,
        logs=replace(
            boot.logs,
            retention_days=file.logs.retention_days,
            max_total_bytes=file.logs.max_total_mb * 1024 * 1024,
            max_file_bytes=file.logs.max_file_mb * 1024 * 1024,
            compress_after_days=file.logs.compress_after_days,
            static_assets=file.logs.static_assets,
            ui_clicks=file.logs.ui_clicks,
            echo=file.logs.echo,
        ),
        file=file,
    )


def edit_changes(raw: str, changes: dict[str, Any], label: str, from_server: bool) -> tuple[str, list[str]]:
    """The part of save() that turns submitted changes into a new
    config.yaml, without writing it. `config set` uses it too.

    Each value is checked against the schema, written in place by
    edit_yaml, and then the whole result is parsed back as a check on the
    editor itself: every changed key must read back as exactly what was
    asked, and every other key as exactly what it was. Anything else is a
    bug in the editor, and nothing is written."""
    from app.core.yaml_edit import edit_yaml

    before = config_schema.flatten(config.decode_over_defaults(raw, label))
    for path in changes:
        if config_schema.schema_key(path) is None:
            raise UnknownSettingError(path)
    wanted: dict[str, Any] = {}
    edits = []
    unchanged = []
    # Schema order, so keys added to a section land in a sensible order.
    for section in config_schema.schema():
        for key in section.keys:
            if key.path not in changes:
                continue
            if from_server and locked(key):
                raise LockedError(f"{key.path}: this setting cannot be changed from inside the container")
            try:
                typed = config_schema.coerce(key, changes[key.path])
            except ConfigError as error:
                raise ValidationError([str(error)]) from None
            if typed == before[key.path]:
                unchanged.append(key.path)
                continue
            wanted[key.path] = typed
            edits.append((key.path, typed))
    if not edits:
        return raw, unchanged
    edited = edit_yaml(raw, edits, [], config_schema.schema_comments)

    after = config_schema.flatten(config.parse(edited, label))
    for path, value in after.items():
        expected = wanted.get(path, before[path])
        if value != expected:
            raise RuntimeError(
                f"internal error: editing config.yaml would have changed {path} from {expected!r} to {value!r} -- nothing was written"
            )
    return edited, unchanged


def locked(key: config_schema.KeySchema) -> bool:
    """True for a key that cannot be changed from inside the container:
    docker.* (a compromised container must not be able to choose what
    docker/run.sh mounts and chowns on the host next time), and the keys the
    image pins."""
    if not in_container():
        return False
    return key.mode == MODE_SCRIPTS or _pinned_key(key.path)


def _pinned_key(path: str) -> bool:
    return (path == "server.host" and bool(PINNED.host)) or (path == "server.app_dir" and bool(PINNED.app_dir))


def _stat(path: Path) -> tuple[int, int, int] | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size, info.st_nlink)


class Holder:
    """Owns the running Config."""

    def __init__(self, boot: Config) -> None:
        self._boot = boot
        self._current = boot
        # The File the server started on: a [restart] key whose value
        # differs from it is pending a restart.
        self._boot_file = boot.file if boot.file is not None else config.defaults()
        self._file = self._boot_file
        self.path = Path(boot.config_file)
        # The container's config.yaml is a single-file bind mount: renaming a
        # new file over it fails, so it is rewritten in place, with the old
        # version kept in the (writable) app directory first.
        self.in_place = in_container() and str(self.path) == PINNED.config_file
        self.backup_path = Path(boot.app_dir) / config.BACKUP_FILE_NAME if self.in_place else None

        # Serialises apply, save and poll. get() never takes it.
        self._lock = threading.Lock()
        self._last_error: dict[str, str] | None = None
        self._error_hash = ""
        self._seen_hash = version(boot.raw)
        self._pending = ""
        self._stat = _stat(self.path)
        self._stale = False
        self._subscribers: list[Callable[[Config, Config], None]] = []
        # Tells the operator about a reload or a rejected edit: main.py points
        # it at stdout and the activity log.
        self.report: Callable[[str, str, dict[str, Any]], None] | None = None

    @classmethod
    def static(cls, cfg: Config) -> "Holder":
        """A Holder that never changes, for tests and tools that need one
        without a config.yaml behind it."""
        holder = cls.__new__(cls)
        holder._boot = holder._current = cfg
        holder._lock = threading.Lock()
        holder._subscribers = []
        holder.report = None
        return holder

    def get(self) -> Config:
        """The current Config. Read it once per request and use that copy
        throughout, so one request never sees half of an edit."""
        return self._current

    def boot(self) -> Config:
        """The Config the server started on: what [restart] settings and
        anything set up once at startup (the listener, the database) run with."""
        return self._boot

    def on_change(self, subscriber: Callable[[Config, Config], None]) -> None:
        """Called after every applied change, with the lock held -- keep it
        quick."""
        with self._lock:
            self._subscribers.append(subscriber)

    def _apply(self, raw: str, persist: Callable[[], None] | None) -> dict[str, Any]:
        file = config.parse(raw, str(self.path))
        legacy = file.server.secret_key
        if legacy and legacy != self._boot.secret_key:
            raise ValidationError(["server.secret_key does not belong in config.yaml any more -- the key is in secret.key"])
        if persist is not None:
            persist()
        new = live_config(self._boot, self._boot_file, file)
        changes = config_schema.diff(self._file, file)
        result: dict[str, Any] = {
            "changes": changes,
            "applied": [c["key"] for c in changes if c["apply"] == MODE_LIVE],
            "restart": [c["key"] for c in changes if c["apply"] not in (MODE_LIVE, MODE_SCRIPTS)],
            "scripts": [c["key"] for c in changes if c["apply"] == MODE_SCRIPTS],
            "unchanged": [],
            "version": version(raw),
        }
        self._file = file
        self._last_error = None
        self._error_hash = ""
        old, self._current = self._current, new
        for subscriber in self._subscribers:
            subscriber(old, new)
        return result

    def save(self, expected_version: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply changes from the Settings screen: check them, rewrite only
        those values in config.yaml, validate the whole result, write it, and
        apply it. expected_version is the version() the client loaded; if
        config.yaml is not that file any more the save is refused with a
        ConflictError, so a hand edit made meanwhile is never silently
        overwritten."""
        with self._lock:
            if self._stale:
                raise StaleError()
            raw = read_raw(self.path)
            current = version(raw)
            if current != expected_version:
                raise ConflictError(current)
            if not self._writable():
                raise ReadOnlyError()
            edited, unchanged = edit_changes(raw, changes, str(self.path), True)
            result = self._apply(edited, lambda: write_config_file(self.path, edited, self.in_place, self.backup_path))
            result["unchanged"] = unchanged
            # The watcher will see this write; it is not news.
            self._seen_hash = result["version"]
            self._pending = ""
            self._stat = _stat(self.path)
            return result

    def poll(self) -> None:
        """Check config.yaml for a change made outside save() and apply it. A
        change is applied once two polls in a row have seen the same content,
        so an editor caught half way through writing the file is never
        applied."""
        with self._lock:
            stat = _stat(self.path)
            if stat is None:
                self._fail("", f"cannot read {self.path} -- still running on the last good version")
                return
            if stat[2] == 0 and not self._stale:
                self._stale = True
                self._report("warn", "config.yaml was replaced on the host; restart the container to pick it up", {"file": str(self.path)})
            if stat == self._stat:
                return
            try:
                raw = read_raw(self.path)
            except (OSError, UnicodeDecodeError):
                return
            current = version(raw)
            if current == self._seen_hash:
                self._stat = stat
                self._pending = ""
                return
            if current != self._pending:
                self._pending = current
                return
            self._stat = stat
            self._seen_hash = current
            self._pending = ""
            try:
                result = self._apply(raw, None)
            except ConfigError as error:
                self._fail(current, f"{self.path} is invalid; still running on the last good version: {error}")
                return
            if not result["changes"]:
                return
            self._report("info", "config.yaml reloaded: " + _describe(result), {
                "origin": "file",
                "changes": result["changes"],
                "applied": result["applied"],
                "restart": result["restart"],
                "scripts": result["scripts"],
            })

    def _fail(self, file_hash: str, message: str) -> None:
        """Record an error, reporting it once per distinct file content."""
        repeat = self._last_error is not None and self._last_error["message"] == message and self._error_hash == file_hash
        self._last_error = {"message": message, "at": _now(), "origin": "file"}
        self._error_hash = file_hash
        if not repeat:
            self._report("warn", message, {"file": str(self.path), "origin": "file"})

    def _report(self, level: str, message: str, detail: dict[str, Any]) -> None:
        if self.report is not None:
            self.report(level, message, detail)

    def _writable(self) -> bool:
        """Whether save() could write config.yaml: the file itself when it is
        rewritten in place, otherwise the folder the replacement is created
        in. Probing writes nothing."""
        if self.in_place:
            try:
                os.close(os.open(self.path, os.O_WRONLY))
            except OSError:
                return False
            return True
        try:
            descriptor, name = tempfile.mkstemp(dir=self.path.parent, prefix=".config.yaml.", suffix=".tmp")
        except OSError:
            return False
        os.close(descriptor)
        os.unlink(name)
        return True

    def snapshot(self) -> dict[str, Any]:
        """The whole Settings screen, read from config.yaml as it is on disk.
        When that does not validate, the values shown are the last good ones
        and error says why. It never includes the secret key: it is built
        from the schema, which does not have it."""
        with self._lock:
            shown = self._file
            raw = ""
            try:
                raw = read_raw(self.path)
                try:
                    shown = config.parse(raw, str(self.path))
                except ConfigError as error:
                    if self._last_error is None or self._error_hash != version(raw):
                        self._last_error = {"message": str(error), "at": _now(), "origin": "file"}
                        self._error_hash = version(raw)
            except (OSError, UnicodeDecodeError):
                pass
            values = config_schema.flatten(shown)
            running = config_schema.flatten(self._boot_file)
            present = config_schema.keys_in_file(raw)
            sections = []
            for section in config_schema.schema():
                keys = []
                for key in section.keys:
                    pending = (
                        key.mode == MODE_RESTART
                        and not _pinned_key(key.path)
                        and values[key.path] != running[key.path]
                    )
                    keys.append({
                        "key": key.path,
                        "name": key.name,
                        "type": key.type,
                        "value": values[key.path],
                        "default": key.default,
                        "in_file": key.path in present,
                        "help": key.help,
                        "apply": key.mode,
                        "pending_restart": pending,
                        "running": running[key.path],
                        "locked": locked(key),
                    })
                sections.append({"name": section.name, "help": section.help, "keys": keys})
            return {
                "file": str(self.path),
                "secret_file": str(self.path.parent / config.SECRET_FILE_NAME),
                "version": version(raw),
                "writable": not self._stale and self._writable(),
                "stale": self._stale,
                "in_container": in_container(),
                "error": self._last_error,
                "sections": sections,
            }


def _describe(result: dict[str, Any]) -> str:
    """A reload in one line: "live server.rate_limit_max; on restart
    server.port"."""
    parts = []
    for label, keys in (("live", result["applied"]), ("on restart", result["restart"]), ("for the scripts", result["scripts"])):
        if keys:
            parts.append(label + " " + ", ".join(keys))
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# writing config.yaml
# ---------------------------------------------------------------------------


def write_config_file(path: Path, content: str, in_place: bool, backup_path: Path | None) -> None:
    """Replace config.yaml's content.

    Normally that is a new file renamed over the old one: a crash leaves one
    version or the other, never half of each. The container cannot do that.
    Its config.yaml is a single file bind-mounted from the host, and renaming
    over a mount point fails (EBUSY); its folder is root's and read-only
    anyway. So there it is rewritten in place -- after the old version is
    copied to backup_path in the app directory, which is writable -- and
    written from the start before the tail is cut, so the file is never
    empty."""
    path = Path(path)
    data = content.encode("utf-8")
    info = os.stat(path)
    if in_place:
        if backup_path is not None:
            try:
                _write_atomic(Path(backup_path), path.read_bytes(), 0o600)
            except OSError as error:
                raise ConfigError(f"could not keep a backup of config.yaml at {backup_path}: {error.strerror}") from None
        descriptor = os.open(path, os.O_WRONLY)
        try:
            os.pwrite(descriptor, data, 0)
            os.ftruncate(descriptor, len(data))
            os.fsync(descriptor)
        except OSError as error:
            note = f" (the previous config.yaml is at {backup_path})" if backup_path else ""
            raise ConfigError(f"could not write {path}: {error.strerror}{note}") from None
        finally:
            os.close(descriptor)
        return
    _write_atomic(path, data, info.st_mode & 0o777)
    # Keep the group docker/run.sh gave it, so the container can still read
    # and write it. Best effort: only the owner or root can.
    if hasattr(os, "chown"):
        try:
            os.chown(path, -1, info.st_gid)
        except OSError:
            pass


def _write_atomic(path: Path, data: bytes, mode: int) -> None:
    """Write path through a temporary file in the same folder."""
    from app.core.config_secret import sync_dir

    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.chmod(temp_name, mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    sync_dir(path.parent)
