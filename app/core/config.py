"""The single source of truth for everything this app can be told to do
differently: the server and the Docker container. All of it lives in one
config.yaml.

Nothing reads environment variables. A setting that could come from the
environment, a file, or a default has to be hunted for in three places; one
that can only come from config.yaml is answered by reading one file. The
shell scripts follow the same rule -- they ask this module for their values
(`python -m app config shell docker`, see config_command.py) rather than
parsing YAML themselves, so there is exactly one parser and one set of
validation rules.

Defaults are not written in Python. They live in config/defaults.yaml, which
ships with the code, documents every key, and is what `config init` writes out.
A config.yaml is decoded on top of it, strictly: an unknown key is an error,
because a typo that is silently ignored is a setting that silently is not
applied.

The secret key is not in config.yaml. It is in secret.key beside it (see
config_secret.py), which is what lets config.yaml be edited while the server
runs -- from the owner's Settings screen or by hand -- without either path
ever touching the key. config_live.py holds the running configuration and
applies those edits; yaml_edit.py rewrites single values in place so the
file's comments survive; config_schema.py reads which keys can change live
from the tags in defaults.yaml.
"""
from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlsplit
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

from app.core.layout import PINNED, in_container

# APP_SLUG names the application on disk. It is what turns into
# ~/.config/<slug>/, so it is deliberately the lowercase, filesystem-safe form
# of the project name rather than the display name. It is a constant rather
# than a setting because it is how config.yaml itself is found.
APP_SLUG = "media-tracker"

# What everything but the rotation itself says when one was left half way
# inside the container.
ROTATION_PENDING_MESSAGE = "a key rotation was cut short -- run docker/rotate-key.sh on the host to finish it"

# Filenames this app uses. Everything it persists lives under the app
# directory -- see default_app_dir for why.
# The folder of a source checkout that holds config.yaml, config.example.yaml,
# language.yaml and the defaults.
CONFIG_DIR_NAME = "config"
CONFIG_FILE_NAME = "config.yaml"
DATABASE_FILE_NAME = "app.db"
STORAGE_DIR_NAME = "storage"
LOGS_DIR_NAME = "logs"
BACKUPS_DIR_NAME = "backups"
# Held by the running server. See app/core/server_lock.py.
SERVER_LOCK_NAME = "server.lock"
LANGUAGE_FILE_NAME = "language.yaml"
# Beside config.yaml. See config_secret.secret_path_for.
SECRET_FILE_NAME = "secret.key"
# The previous config.yaml, kept in the app directory whenever the container
# rewrites its mounted copy in place. See config_live.write_config_file.
BACKUP_FILE_NAME = "config.yaml.bak"

# The folder holding app/ -- the project root in a checkout, /app in the image.
CODE_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULTS_PATH = CODE_ROOT / CONFIG_DIR_NAME / "defaults.yaml"
# What turns defaults.yaml into config.example.yaml: a note on how to copy it
# into place. See example_file_content.
EXAMPLE_HEADER_PATH = CODE_ROOT / CONFIG_DIR_NAME / "example_header.yaml"
# The committed copy of the defaults that a fresh clone copies to
# config.yaml. Nothing reads it.
EXAMPLE_FILE_NAME = "config.example.yaml"


class ConfigError(Exception):
    """config.yaml is missing, malformed, or holds a value that would fail
    later in a confusing way. The message is meant to be shown as-is."""


class ValidationError(ConfigError):
    """Everything wrong with a config.yaml at once. Each problem starts with
    the key it is about ("server.port must be ..."), which is how the
    Settings screen puts it under the right field."""

    def __init__(self, problems: list[str], label: str = "") -> None:
        self.problems = list(problems)
        text = "; ".join(self.problems)
        super().__init__(f"{label}: {text}" if label else text)


# ---------------------------------------------------------------------------
# config.yaml, section by section
# ---------------------------------------------------------------------------
#
# The dataclasses below are the schema. Every key in defaults.yaml must be a
# field here and every field must be in defaults.yaml, so the two cannot drift
# silently. The docker section is decoded and validated too even though the
# server never reads it: that is what lets docker/run.sh fail on a typo before
# it starts anything.


@dataclass
class AppSection:
    name: str


@dataclass
class ServerSection:
    host: str
    port: int
    public_url: str
    app_dir: str
    static_dir: str
    language_file: str
    encrypt_at_rest: bool
    secure_cookies: bool
    cookie_name: str
    trust_proxy: bool
    trusted_proxies: list[str]
    proxy_header: str
    body_limit_bytes: int
    rate_limit_max: int
    rate_limit_window_seconds: int
    rate_limit_signin_max: int
    mcp: bool
    maintenance: str
    announcement: str
    # Deprecated: the key lives in secret.key. This is read only so that a
    # config.yaml from before the move can be migrated
    # (config_secret.migrate_legacy_secret); defaults.yaml has no such key,
    # so nothing else ever sees it.
    secret_key: str = ""


@dataclass
class AuthSection:
    session_ttl_seconds: int
    session_max_age_seconds: int
    login_token_ttl_seconds: int
    multi_use_login_token_ttl_seconds: int
    api_keys: bool
    api_key_ttl_seconds: int
    passwords: bool
    two_factor: bool
    invite_links: bool


@dataclass
class LogsSection:
    enabled: bool
    retention_days: int
    max_total_mb: int
    max_file_mb: int
    compress_after_days: int
    static_assets: bool
    ui_clicks: bool
    echo: bool




@dataclass
class ProvidersSection:
    network: bool
    tmdb_api_key: str
    omdb_api_key: str
    user_agent: str
    timeout_seconds: int
    lookups_per_minute: int


@dataclass
class ImagesSection:
    cache_mb: int
    rate_limit_max: int
    allow_hosts: list[str]


@dataclass
class LibrarySection:
    restore_days: int
    max_titles: int


@dataclass
class JobsSection:
    imdb_refresh_hours: int
    imdb_genres_refresh_hours: int
    appletv_hours: int
    enrich_on_add: bool


@dataclass
class DockerSection:
    image: str
    container: str
    bind_address: str
    host_port: int
    data_dir: str
    restart: str
    memory: str
    cpus: str
    pids_limit: int
    tmpfs_size: str


@dataclass
class File:
    app: AppSection
    server: ServerSection
    auth: AuthSection
    providers: ProvidersSection
    images: ImagesSection
    library: LibrarySection
    jobs: JobsSection
    logs: LogsSection
    docker: DockerSection


# Fields that may be absent from defaults.yaml: kept only so an older
# config.yaml still decodes.
DEPRECATED = {"server": {"secret_key"}}

SECTIONS: dict[str, type] = {
    "app": AppSection,
    "server": ServerSection,
    "auth": AuthSection,
    "providers": ProvidersSection,
    "images": ImagesSection,
    "library": LibrarySection,
    "jobs": JobsSection,
    "logs": LogsSection,
    "docker": DockerSection,
}


# ---------------------------------------------------------------------------
# the resolved configuration the server runs on
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LogsConfig:
    """config.yaml's logs section, resolved: sizes in bytes, and the directory
    the day files go in (<app_dir>/logs, created 0700 by load). See
    app/core/logs.py."""

    enabled: bool = True
    dir: Path = Path(LOGS_DIR_NAME)
    retention_days: int = 30
    max_total_bytes: int = 500 * 1024 * 1024
    max_file_bytes: int = 50 * 1024 * 1024
    compress_after_days: int = 1
    static_assets: bool = False
    ui_clicks: bool = True
    echo: bool = True


@dataclass(frozen=True)
class BackupsConfig:
    """config.yaml's backups section, resolved. dir is where every backup
    goes unless `manage backup --out` says otherwise (<app_dir>/backups,
    created 0700 the first time something is written there). See
    app/core/backup.py."""

    dir: Path = Path(BACKUPS_DIR_NAME)


@dataclass(frozen=True)
class Config:
    """config.yaml after resolution: paths made absolute, container overrides
    applied. The rest of the app reads this, never File, so a change to the
    file's shape stays inside this module."""

    project_name: str

    # What relative paths in config.yaml are resolved against. See
    # project_dir_for.
    project_dir: Path

    # Where a browser reaches this server, for the links it prints:
    # server.public_url when set, otherwise one worked out from the listen
    # address (see server_url). url_source names which, so a printed link can
    # say how much to trust it.
    url: str
    url_source: str

    # The config.yaml this was loaded from.
    config_file: Path
    # True when this run wrote config_file because none existed.
    config_created: bool
    # Non-empty when secret.key is readable by other users, or config.yaml
    # writable by them. A warning rather than an error so a misconfigured
    # mode never stops a server that was working, but it does get logged on
    # every start.
    config_warning: str

    # The one directory this application owns: the database and any uploaded
    # or generated files. Defaulting to ~/.config/<slug> rather than ./data
    # means the app finds the same state whatever directory it is started
    # from.
    app_dir: Path
    database_path: Path
    # For application files -- exports, generated artifacts. Finished uploads
    # are in storage/files (see files.dir); the rest exists so that features
    # added later have an obvious, backed-up place to put files instead of
    # inventing one.
    storage_dir: Path

    # Used when they exist; otherwise the copies shipped with the code (see
    # app/core/assets.py). Empty means "not configured".
    static_dir: str
    language_file: str

    host: str
    port: int

    # Must stay true anywhere a real browser talks to this over the internet.
    # Only false for plain-http://localhost work, because a Secure cookie is
    # silently dropped over http and the login flow would appear to succeed
    # and then do nothing.
    secure_cookies: bool
    cookie_name: str

    session_ttl_seconds: int
    session_max_age_seconds: int
    login_token_ttl_seconds: int
    # The default expiry of a link that works more than once (see
    # login_tokens.resolve_link).
    multi_use_login_token_ttl_seconds: int

    # Whether the Authorization: Bearer header is believed at all, and whether
    # the endpoints that mint keys exist. Off stops existing keys from
    # authenticating too -- the rows stay, so switching it back on restores
    # them.
    api_keys_enabled: bool
    # How long a new key lasts when the request does not say. Bounded so a
    # forgotten key eventually stops being a live credential.
    api_key_ttl_seconds: int

    # Whether a password is believed at all, and whether an account can set
    # one. Off keeps the hashes, so switching it back on restores them.
    passwords_enabled: bool
    # Whether 2FA is offered and asked for. Off keeps the secrets, the same way.
    two_factor_enabled: bool
    # Whether /join and every invite route answer, and whether a PIN can be
    # set. Off keeps the links and PINs, the same way.
    invite_links_enabled: bool

    # Encrypts session cookie payloads and, when encrypt_at_rest is on, every
    # record written to the database. Losing it means losing the data.
    secret_key: str = field(repr=False)
    encrypt_at_rest: bool = True

    rate_limit_max: int = 120
    rate_limit_window_seconds: int = 60
    # The separate budget for signing in and joining.
    rate_limit_signin_max: int = 60
    body_limit_bytes: int = 1048576

    # proxy_header is believed only when trust_proxy is on *and* the
    # connection comes from an address in trusted_proxies (IPs or CIDR
    # ranges). The switch alone would let any client that reaches the server
    # directly name its own IP and walk past the rate limiter, so validate()
    # refuses one without the other.
    trust_proxy: bool = False
    trusted_proxies: tuple[str, ...] = ()
    proxy_header: str = "X-Forwarded-For"

    # server.maintenance: see app/core/maintenance.py.
    maintenance: str = "none"
    # server.announcement: one line on every signed-in page.
    announcement: str = ""

    # Whether POST /mcp exists. It answers only API keys, so with
    # api_keys_enabled off it is not registered either.
    mcp_enabled: bool = True

    # The media side: outbound lookups, the poster cache, the shared library
    # and the background jobs. Grouped in their own frozen sections so the
    # rest of the app reads cfg.providers.tmdb_api_key rather than a dozen
    # loose fields here.
    providers: ProvidersSection = field(default_factory=lambda: ProvidersSection(True, "", "", "MediaTracker/2.0", 12, 180), repr=False)
    images: ImagesSection = field(default_factory=lambda: ImagesSection(256, 4000, []))
    library: LibrarySection = field(default_factory=lambda: LibrarySection(30, 20000))
    jobs: JobsSection = field(default_factory=lambda: JobsSection(24, 24, True))


    # The activity log's settings; see app/core/logs.py.
    logs: LogsConfig = field(default_factory=LogsConfig)

    # The scheduled backup's settings; see app/core/backup.py.
    backups: BackupsConfig = field(default_factory=BackupsConfig)

    # secret.key, beside config_file: the one file besides the app directory
    # that a backup must include. secret_created is true when this run
    # generated the key, secret_migrated when it moved server.secret_key out
    # of config.yaml into it. The startup log says so either way.
    secret_file: Path = Path(SECRET_FILE_NAME)
    secret_created: bool = False
    secret_migrated: bool = False

    # rotation_finished is true when this load completed a key rotation that
    # had been cut short. rotation_pending is the same discovery inside the
    # container, which cannot complete one: docker/rotate-key.sh does, on the
    # host. See config_secret.py.
    rotation_finished: bool = False
    rotation_pending: bool = False

    # What this was built from, for config_live.Holder.
    file: Any = field(default=None, repr=False, compare=False)
    raw: str = field(default="", repr=False, compare=False)

    @property
    def listen_address(self) -> str:
        return f"{self.host}:{self.port}"


# ---------------------------------------------------------------------------
# where things live
# ---------------------------------------------------------------------------


def default_app_dir() -> Path:
    """~/.config/<slug>. Everything lands in one directory rather than being
    split across XDG's config/data/state roots: this app's state is small, and
    one directory to back up is worth more here than strict adherence to a
    layout designed for larger, more separable applications."""
    try:
        home = Path.home()
    except (RuntimeError, KeyError):
        home = None
    if home is not None and str(home) not in ("", "/"):
        return home / ".config" / APP_SLUG
    # No usable home directory (some minimal environments). Fall back to the
    # working directory rather than failing to start.
    return Path(".") / f"{APP_SLUG}-data"


def locate() -> tuple[Path, bool]:
    """Find the config.yaml in use: the pinned path inside the container
    image, otherwise ./config/config.yaml, otherwise the one in the default
    app directory. When none exists, the path is where one would be created.

    ./config/config.yaml comes first because that is a source checkout, which
    is also where the scripts read it. Run from anywhere else, the app falls
    through to ~/.config/<slug>/ and finds the same file every time."""
    if PINNED.config_file:
        path = Path(PINNED.config_file)
        return path, path.is_file()
    local = (Path(CONFIG_DIR_NAME) / CONFIG_FILE_NAME).absolute()
    if local.is_file():
        return local, True
    path = (default_app_dir() / CONFIG_FILE_NAME).absolute()
    return path, path.is_file()


def project_dir_for(config_path: Path) -> Path:
    """The directory relative paths in config.yaml resolve against. In a
    checkout (and in the container image, /app) config.yaml sits in config/,
    and paths like ./static and ./data mean the project folder around it, so
    that is the parent. Anywhere else -- ~/.config/<slug>/ -- it is the folder
    holding config.yaml."""
    folder = config_path.parent
    return folder.parent if folder.name == CONFIG_DIR_NAME else folder


def resolve_path(base: Path, value: str) -> str:
    """Make a config path absolute against the project directory
    (project_dir_for), so the same file means the same thing whatever
    directory the process was started from."""
    if value == "" or os.path.isabs(value):
        return value
    return str(base / value)


# ---------------------------------------------------------------------------
# strict decoding
# ---------------------------------------------------------------------------

_INT_TAG = "tag:yaml.org,2002:int"
_BOOL_TAG = "tag:yaml.org,2002:bool"
_NULL_TAG = "tag:yaml.org,2002:null"
_constructor = yaml.constructor.SafeConstructor()


def _scalar(node: yaml.Node, wanted: type, key: str, label: str) -> Any:
    line = node.start_mark.line + 1
    where = f"{label}: line {line}: {key}"
    if not isinstance(node, yaml.ScalarNode):
        raise ConfigError(f"{where} must be a single value, not a list or mapping")
    if wanted is str:
        # Any scalar is accepted as text -- `cpus: 1` means "1" -- and an empty
        # value means an empty string, which is what `app_dir:` reads as.
        return "" if node.tag == _NULL_TAG else str(node.value)
    if node.tag == _NULL_TAG:
        raise ConfigError(f"{where} has no value (delete the line to use the default)")
    if wanted is bool:
        if node.tag != _BOOL_TAG:
            raise ConfigError(f"{where} must be true or false, got {node.value!r}")
        return _constructor.construct_yaml_bool(node)
    if wanted is int:
        if node.tag != _INT_TAG:
            raise ConfigError(f"{where} must be a whole number, got {node.value!r}")
        return _constructor.construct_yaml_int(node)
    raise ConfigError(f"{where} has an unsupported type")  # pragma: no cover


def _string_list(node: yaml.Node, key: str, label: str) -> list[str]:
    """A YAML list of plain values, each read as text."""
    if isinstance(node, yaml.ScalarNode) and node.tag == _NULL_TAG:
        return []
    if not isinstance(node, yaml.SequenceNode):
        raise ConfigError(f"{label}: line {node.start_mark.line + 1}: {key} must be a list, like [127.0.0.1]")
    return [_scalar(item, str, key, label) for item in node.value]


def _mapping_pairs(node: yaml.Node, path: str, label: str) -> list[tuple[str, int, yaml.Node]]:
    """The key/value pairs of a mapping node, refusing duplicate keys -- a
    YAML parser keeps the last one silently, which is another way for a
    setting to quietly not be the one you wrote."""
    line = node.start_mark.line + 1
    if not isinstance(node, yaml.MappingNode):
        raise ConfigError(f"{label}: line {line}: {path or 'the file'} must be a mapping of keys to values")
    seen: set[str] = set()
    pairs = []
    for key_node, value_node in node.value:
        key = str(key_node.value)
        dotted = f"{path}.{key}" if path else key
        if key in seen:
            raise ConfigError(f"{label}: line {key_node.start_mark.line + 1}: {dotted} appears twice")
        seen.add(key)
        pairs.append((key, key_node.start_mark.line + 1, value_node))
    return pairs


def decode_strict(raw: str, label: str) -> dict[str, dict[str, Any]]:
    """Decode a config.yaml into {section: {key: value}}, holding every key
    to the schema. An empty file is a valid file that sets nothing."""
    try:
        root = yaml.compose(raw, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise ConfigError(f"{label}: {error}") from None
    result: dict[str, dict[str, Any]] = {}
    if root is None or (isinstance(root, yaml.ScalarNode) and root.tag == _NULL_TAG):
        return result
    for section_name, section_line, section_node in _mapping_pairs(root, "", label):
        schema = SECTIONS.get(section_name)
        if schema is None:
            known = ", ".join(SECTIONS)
            raise ConfigError(f"{label}: line {section_line}: unknown section {section_name!r} (known: {known})")
        values: dict[str, Any] = {}
        result[section_name] = values
        if isinstance(section_node, yaml.ScalarNode) and section_node.tag == _NULL_TAG:
            continue
        types = {f.name: f.type for f in fields(schema)}
        for key, key_line, value_node in _mapping_pairs(section_node, section_name, label):
            dotted = f"{section_name}.{key}"
            if key not in types:
                raise ConfigError(f"{label}: line {key_line}: unknown key {dotted}")
            if types[key] == "list[str]":
                values[key] = _string_list(value_node, dotted, label)
                continue
            wanted = {"str": str, "int": int, "bool": bool}[types[key]]
            values[key] = _scalar(value_node, wanted, dotted, label)
    return result


def _build(values: dict[str, dict[str, Any]]) -> File:
    sections = {}
    for name, schema in SECTIONS.items():
        given = values.get(name, {})
        missing = [f.name for f in fields(schema) if f.name not in given and f.name not in DEPRECATED.get(name, set())]
        if missing:
            raise ConfigError(f"defaults.yaml is missing {', '.join(f'{name}.{key}' for key in missing)}")
        sections[name] = schema(**given)
    return File(**sections)


def defaults() -> File:
    """defaults.yaml on its own: the configuration a missing key falls back
    to."""
    try:
        return _build(decode_strict(DEFAULTS_PATH.read_text(encoding="utf-8"), "defaults.yaml"))
    except ConfigError as error:
        raise ConfigError(f"the shipped defaults.yaml is invalid: {error}") from None


def decode_over_defaults(raw: str, label: str) -> File:
    """parse() without validate(): the file's values over the defaults,
    strictly decoded. The secret-key migration uses it because moving the key
    must not depend on every other setting being right."""
    merged = decode_strict(DEFAULTS_PATH.read_text(encoding="utf-8"), "defaults.yaml")
    for section, values in decode_strict(raw, label).items():
        merged.setdefault(section, {}).update(values)
    return _build(merged)


def parse(raw: str, label: str) -> File:
    """Decode a config.yaml over the defaults and validate the result."""
    file = decode_over_defaults(raw, label)
    problems = validate(file)
    if problems:
        raise ValidationError(problems, label)
    return file


def read_file(path: Path) -> File:
    """Read and validate one config.yaml without touching anything else on
    disk."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"could not read {path}: {error.strerror}") from None
    return parse(raw, str(path))


def current() -> tuple[File, Path, bool]:
    """The file the server would use, or the defaults when there is no file
    yet. It never writes anything, which is what the shell-facing commands
    and the healthcheck need."""
    path, exists = locate()
    if exists:
        return read_file(path), path, True
    return defaults(), path, False


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

_IMAGE = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?(:[0-9]+)?(/[a-z0-9]([a-z0-9._-]*[a-z0-9])?)*$")
_CONTAINER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_RESTART = re.compile(r"^(no|always|unless-stopped|on-failure(:[0-9]+)?)$")
_SIZE = re.compile(r"^[0-9]+[bkmgBKMG]?$")
_CPUS = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_HOST_PATTERN = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_SECRET = re.compile(r"^[0-9a-fA-F]{64}$")


def _valid_public_url(value: str) -> bool:
    if value == "":
        return True
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
        and parts.username is None
    )


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _proxy_network(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    try:
        return ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return None


def trusted_proxy_networks(cfg: "Config") -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """server.trusted_proxies parsed, for the rate limiter. validate() has
    already refused anything that does not parse."""
    return [network for network in (_proxy_network(entry) for entry in cfg.trusted_proxies) if network is not None]


def validate(file: File) -> list[str]:
    """Reject values that would fail later in a confusing way -- a port out
    of range, a Docker size the daemon would refuse. The docker values also
    end up in shell commands, so they are held to strict patterns rather than
    trusted."""
    problems: list[str] = []

    def check(ok: bool, message: str) -> None:
        if not ok:
            problems.append(message)

    def path_ok(value: str) -> bool:
        return value.strip() != "" and not any(c in value for c in ":\n\r")

    check(file.app.name.strip() != "", "app.name must not be empty")

    server = file.server
    check(server.host.strip() != "", "server.host must not be empty")
    check(1 <= server.port <= 65535, f"server.port must be 1-65535, got {server.port}")
    check(
        _valid_public_url(server.public_url),
        f"server.public_url {server.public_url!r} must be empty or a bare origin like "
        "https://app.example.com (http or https, no path)",
    )
    check(server.cookie_name.strip() != "", "server.cookie_name must not be empty")
    check(server.proxy_header.strip() != "", "server.proxy_header must not be empty")
    check(
        not server.trust_proxy or len(server.trusted_proxies) > 0,
        "server.trust_proxy is true but server.trusted_proxies is empty -- "
        "list the address or CIDR range your reverse proxy connects from",
    )
    for entry in server.trusted_proxies:
        network = _proxy_network(entry)
        check(network is not None, f"server.trusted_proxies entry {entry!r} must be an IP address or a CIDR range like 10.0.0.0/8")
        check(
            network is None or network.prefixlen > 0,
            f"server.trusted_proxies entry {entry!r} trusts every address, which lets any client forge its own IP",
        )
    check(server.body_limit_bytes > 0, "server.body_limit_bytes must be positive")
    check(server.rate_limit_max > 0, "server.rate_limit_max must be positive")
    check(server.rate_limit_window_seconds > 0, "server.rate_limit_window_seconds must be positive")
    check(server.rate_limit_signin_max > 0, "server.rate_limit_signin_max must be positive")
    check(server.maintenance in ("none", "read_only", "full"), "server.maintenance must be none, read_only or full")
    check(len(server.announcement) <= 500, "server.announcement must be 500 characters or fewer")

    providers = file.providers
    check(1 <= providers.timeout_seconds <= 120, "providers.timeout_seconds must be 1-120")
    check(providers.lookups_per_minute > 0, "providers.lookups_per_minute must be positive")
    check(providers.user_agent.strip() != "", "providers.user_agent must not be empty")
    images = file.images
    check(images.cache_mb > 0, "images.cache_mb must be positive")
    check(images.rate_limit_max > 0, "images.rate_limit_max must be positive")
    for host in images.allow_hosts:
        check(bool(_HOST_PATTERN.match(host)), f"images.allow_hosts entry {host!r} must be a host name, optionally starting with *.")
    check(file.library.restore_days > 0, "library.restore_days must be positive")
    check(file.library.max_titles > 0, "library.max_titles must be positive")
    check(file.jobs.imdb_refresh_hours > 0, "jobs.imdb_refresh_hours must be positive")
    check(file.jobs.imdb_genres_refresh_hours > 0, "jobs.imdb_genres_refresh_hours must be positive")
    check(file.jobs.appletv_hours > 0, "jobs.appletv_hours must be positive")

    auth = file.auth
    check(auth.session_ttl_seconds > 0, "auth.session_ttl_seconds must be positive")
    check(
        auth.session_max_age_seconds >= auth.session_ttl_seconds,
        "auth.session_max_age_seconds must be at least auth.session_ttl_seconds",
    )
    check(auth.login_token_ttl_seconds > 0, "auth.login_token_ttl_seconds must be positive")
    check(auth.multi_use_login_token_ttl_seconds > 0, "auth.multi_use_login_token_ttl_seconds must be positive")
    check(auth.api_key_ttl_seconds > 0, "auth.api_key_ttl_seconds must be positive")

    logs = file.logs
    check(1 <= logs.retention_days <= 3650, f"logs.retention_days must be 1-3650, got {logs.retention_days}")
    check(logs.max_total_mb >= 1, "logs.max_total_mb must be positive")
    check(1 <= logs.max_file_mb <= logs.max_total_mb, "logs.max_file_mb must be positive and no more than logs.max_total_mb")
    check(logs.compress_after_days >= 0, "logs.compress_after_days must be 0 (never) or more")



    docker = file.docker
    check(bool(_IMAGE.match(docker.image)), f"docker.image {docker.image!r} is not a valid lowercase image name")
    check(bool(_CONTAINER.match(docker.container)), f"docker.container {docker.container!r} is not a valid container name")
    check(_valid_ip(docker.bind_address), f"docker.bind_address {docker.bind_address!r} must be an IP address")
    check(1 <= docker.host_port <= 65535, f"docker.host_port must be 1-65535, got {docker.host_port}")
    check(path_ok(docker.data_dir), "docker.data_dir must be a path with no ':' in it")
    check(bool(_RESTART.match(docker.restart)), f"docker.restart must be no, always, unless-stopped or on-failure[:N], got {docker.restart!r}")
    check(bool(_SIZE.match(docker.memory)), f"docker.memory must look like 256m, got {docker.memory!r}")
    check(bool(_CPUS.match(docker.cpus)), f"docker.cpus must be a number like 1 or 0.5, got {docker.cpus!r}")
    check(docker.pids_limit > 0, "docker.pids_limit must be positive")
    check(bool(_SIZE.match(docker.tmpfs_size)), f"docker.tmpfs_size must look like 16m, got {docker.tmpfs_size!r}")

    return problems


def check_secret_key(key: str, label: str) -> None:
    """Separate from validate() because only a process that will actually use
    the key needs one. label says where the key came from, for the message.

    An empty key is refused rather than filled in. A secret.key that exists
    was written with a key, so an empty one means it was emptied -- and
    quietly generating a replacement would make every existing record
    permanently unreadable."""
    key = key.strip()
    if key == "":
        raise ConfigError(
            f"{label} is empty\n"
            "  If this app already has data, put back the key it was written with -- a new key cannot read it.\n"
            "  For a fresh install, delete the empty file and the server writes a new one."
        )
    if not _SECRET.match(key):
        raise ConfigError(f"{label} must hold 64 hex characters (32 bytes), got {len(key)} characters")


def permission_warning(config_path: Path, secret_path: Path) -> str:
    """Flag a secret.key other users can read or anyone but its owner can
    change, and a config.yaml anyone on the machine can write -- the server
    applies an edit to that within seconds. Group read on secret.key is
    allowed: it is how the container's user reads it (see docker/run.sh)."""
    if os.name == "nt":
        return ""
    problems = []
    try:
        mode = secret_path.stat().st_mode & 0o777
        if mode & 0o027:
            problems.append(f"{secret_path} is open to other users (mode {mode:04o}) and holds the secret key -- chmod 600 it")
    except OSError:
        pass
    try:
        mode = config_path.stat().st_mode & 0o777
        if mode & 0o002:
            problems.append(f"{config_path} is writable by every user (mode {mode:04o}), and the server applies edits to it -- chmod 600 it")
    except OSError:
        pass
    return "; ".join(problems)


# ---------------------------------------------------------------------------
# creating a config.yaml
# ---------------------------------------------------------------------------

_SECRET_KEY_IN_DEFAULTS = re.compile(r"^\s*secret_key:", re.MULTILINE)


def _defaults_without_secret() -> str:
    """defaults.yaml, checked to hold no key: every config.yaml and the
    committed example are copies of it."""
    text = DEFAULTS_PATH.read_text(encoding="utf-8")
    if _SECRET_KEY_IN_DEFAULTS.search(text):
        raise ConfigError("defaults.yaml must not contain server.secret_key -- the key lives in secret.key")
    return text


def new_file_content() -> str:
    """defaults.yaml as it is -- the whole file, comments included, so the
    result documents itself. It holds no secret: that is written to
    secret.key separately."""
    return _defaults_without_secret()


def example_file_content() -> str:
    """defaults.yaml with a header explaining how to copy it into place.
    Generated rather than kept by hand so that it cannot drift from the
    defaults it documents."""
    return EXAMPLE_HEADER_PATH.read_text(encoding="utf-8") + _defaults_without_secret()


def write_example(path: Path) -> None:
    """Write config.example.yaml. Unlike write_new it overwrites: the file
    holds no secret, and regenerating it is the point."""
    try:
        path.write_text(example_file_content(), encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"could not write {path}: {error.strerror}") from None


def write_new(path: Path) -> bool:
    """Create path from new_file_content(), refusing to overwrite: an
    existing config.yaml is someone's settings. A secret.key is written
    beside it unless one is already there -- an existing key is what existing
    data depends on, so it is never replaced. Returns whether it wrote one."""
    from app.core import config_secret

    content = new_file_content()
    try:
        # 0700 because secret.key lives in here too.
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise ConfigError(f"could not create {path}: {error.strerror}") from None
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    secret_path = config_secret.secret_path_for(path)
    if secret_path.is_file():
        return False
    config_secret.write_secret(secret_path, config_secret.generate_secret())
    return True


# ---------------------------------------------------------------------------


def load() -> Config:
    """Find config.yaml (creating it, and secret.key, if there is none), move
    a secret key out of an older config.yaml (see
    config_secret.resolve_secret), validate it, and make sure the app
    directory exists. The server and the manage CLI both start here."""
    path, exists = locate()
    return load_path(path, exists)


def load_path(path: Path, exists: bool) -> Config:
    """load() for a config.yaml whose path is already known: the one locate()
    found, or a test's."""
    from app.core import config_secret

    created = False
    if not exists:
        if in_container():
            raise ConfigError(f"no config at {path} -- docker/run.sh mounts the project's config/config.yaml there")
        write_new(path)
        created = True

    file = read_file(path)
    paths = resolve_paths(file, path)

    # A key rotation cut short: the data may already be on the new key, so
    # this has to finish before the key is read. Inside the container
    # secret.key cannot be written, so it is left for docker/rotate-key.sh.
    rotation_pending = False
    rotation_finished = False
    if config_secret.rotation_pending(paths.app_dir):
        if in_container():
            rotation_pending = True
        else:
            try:
                config_secret.finish_rotation(paths.app_dir, paths.database_path, path)
            except OSError as error:
                raise ConfigError(f"could not finish an interrupted key rotation: {error}") from None
            rotation_finished = True

    secret = config_secret.resolve_secret(file, path, paths.database_path)
    if secret.rewrote:
        # The migration took the key's line out of config.yaml: build from
        # the file as it now is, which is also what the Holder starts from.
        file = read_file(path)
    raw = path.read_bytes().decode("utf-8")

    for directory, purpose in (
        (paths.app_dir, "app directory"),
        (paths.app_dir / STORAGE_DIR_NAME, "storage directory"),
        (paths.app_dir / LOGS_DIR_NAME, "logs directory"),
    ):
        try:
            # 0700 because the database lives in here.
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as error:
            raise ConfigError(f"could not create {purpose} {str(directory)!r}: {error.strerror}") from None

    secret_path = config_secret.secret_path_for(path)
    warning = "; ".join(part for part in (permission_warning(path, secret_path), secret.warning) if part)
    return replace(
        build_config(file, path, paths, secret.key),
        config_created=created,
        config_warning=warning,
        secret_created=secret.created,
        secret_migrated=secret.migrated,
        rotation_pending=rotation_pending,
        rotation_finished=rotation_finished,
        raw=raw,
    )


def build_config(file: File, path: Path, paths: "Paths", secret_key: str) -> Config:
    """config.yaml resolved into the Config the server runs on. It creates
    nothing, which is what lets the Holder rebuild the live part of it on
    every edit (see config_live.live_config)."""
    from app.core import config_secret

    url, url_source = server_url(file)
    return Config(
        project_name=file.app.name,
        project_dir=paths.project_dir,
        url=url,
        url_source=url_source,
        config_file=path,
        config_created=False,
        config_warning="",
        app_dir=paths.app_dir,
        database_path=paths.database_path,
        storage_dir=paths.app_dir / STORAGE_DIR_NAME,
        static_dir=paths.static_dir,
        language_file=paths.language_file,
        host=PINNED.host or file.server.host,
        port=file.server.port,
        secure_cookies=file.server.secure_cookies,
        cookie_name=file.server.cookie_name,
        session_ttl_seconds=file.auth.session_ttl_seconds,
        session_max_age_seconds=file.auth.session_max_age_seconds,
        login_token_ttl_seconds=file.auth.login_token_ttl_seconds,
        multi_use_login_token_ttl_seconds=file.auth.multi_use_login_token_ttl_seconds,
        api_keys_enabled=file.auth.api_keys,
        passwords_enabled=file.auth.passwords,
        two_factor_enabled=file.auth.two_factor,
        invite_links_enabled=file.auth.invite_links,
        api_key_ttl_seconds=file.auth.api_key_ttl_seconds,
        secret_key=secret_key,
        encrypt_at_rest=file.server.encrypt_at_rest,
        rate_limit_max=file.server.rate_limit_max,
        rate_limit_window_seconds=file.server.rate_limit_window_seconds,
        rate_limit_signin_max=file.server.rate_limit_signin_max,
        body_limit_bytes=file.server.body_limit_bytes,
        trust_proxy=file.server.trust_proxy,
        trusted_proxies=tuple(entry.strip() for entry in file.server.trusted_proxies),
        proxy_header=file.server.proxy_header,
        mcp_enabled=file.server.mcp,
        providers=file.providers,
        images=file.images,
        library=file.library,
        jobs=file.jobs,
        maintenance=file.server.maintenance,
        announcement=file.server.announcement,
        logs=LogsConfig(
            enabled=file.logs.enabled,
            dir=paths.app_dir / LOGS_DIR_NAME,
            retention_days=file.logs.retention_days,
            max_total_bytes=file.logs.max_total_mb * 1024 * 1024,
            max_file_bytes=file.logs.max_file_mb * 1024 * 1024,
            compress_after_days=file.logs.compress_after_days,
            static_assets=file.logs.static_assets,
            ui_clicks=file.logs.ui_clicks,
            echo=file.logs.echo,
        ),
        backups=BackupsConfig(
            dir=paths.app_dir / BACKUPS_DIR_NAME,
        ),
        secret_file=config_secret.secret_path_for(path),
        file=file,
    )


@dataclass(frozen=True)
class Paths:
    """Where everything config.yaml names actually is, resolved the one way
    the server resolves it. `config shell server` prints the same values, so
    the scripts never work out a path on their own."""

    project_dir: Path
    app_dir: Path
    database_path: Path
    static_dir: str
    language_file: str


def resolve_paths(file: File, config_path: Path) -> Paths:
    """Work the paths out without creating anything."""
    base = project_dir_for(config_path)
    app_dir = default_app_dir()
    if file.server.app_dir:
        app_dir = Path(resolve_path(base, file.server.app_dir))
    if PINNED.app_dir:
        app_dir = Path(PINNED.app_dir)
    app_dir = app_dir.absolute()

    # An operator can drop a language.yaml into the app directory to reword
    # the UI without touching the code. Failing that, the one beside
    # config.yaml (config/language.yaml in a checkout) is used, and failing
    # that the copy that ships with the code (app/core/assets.py decides).
    language_file = resolve_path(base, file.server.language_file)
    if language_file == "":
        candidate = app_dir / LANGUAGE_FILE_NAME
        language_file = str(candidate if candidate.is_file() else config_path.parent / LANGUAGE_FILE_NAME)

    return Paths(
        project_dir=base,
        app_dir=app_dir,
        database_path=app_dir / DATABASE_FILE_NAME,
        static_dir=resolve_path(base, file.server.static_dir),
        language_file=language_file,
    )


def server_url(file: File) -> tuple[str, str]:
    """The address printed links start with, and where it came from.
    server.public_url wins: only the operator knows what sits in front.
    Without it, the container's answer is the address Docker publishes
    (docker.bind_address:docker.host_port), and anywhere else it is the
    listen address -- with a wildcard host shown as loopback, since 0.0.0.0
    is not somewhere a browser can go."""
    if file.server.public_url:
        return file.server.public_url.rstrip("/"), "server.public_url"
    if in_container():
        return docker_url(file)
    return (
        "http://" + _host_port(file.server.host, file.server.port),
        "server.host and server.port; this machine only -- set server.public_url for the address people use",
    )


def docker_url(file: File) -> tuple[str, str]:
    """server_url for the container as seen from the host."""
    if file.server.public_url:
        return file.server.public_url.rstrip("/"), "server.public_url"
    return (
        "http://" + _host_port(file.docker.bind_address, file.docker.host_port),
        "docker.bind_address and docker.host_port, the published port -- set server.public_url for the address people use",
    )


def _host_port(host: str, port: int) -> str:
    host = {"0.0.0.0": "127.0.0.1", "": "127.0.0.1", "::": "::1"}.get(host, host)
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
