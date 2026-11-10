"""Shared by the config tests: a config.yaml and secret.key in a temporary
folder, a Holder over them, and a way to pretend to be the container."""
from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from app.core import config, config_live, config_secret, layout, yaml_edit

# A project's defaults.yaml says which features it chose. These tests are about
# the features themselves, so they run on the template's choice whatever that was.
TEMPLATE_SWITCHES = [
    ("auth.api_keys", True),
    ("auth.invite_links", True),
    ("auth.two_factor", True),
    ("auth.passwords", False),
    ("server.mcp", True),
    # MediaTracker: a test server that runs its lifespan must not start the
    # media jobs' outbound lookups (IMDb downloads, Wikipedia, ...).
    ("providers.network", False),
]


def pin_switches(path: Path) -> None:
    """Set a test's config.yaml to the template's feature switches."""
    path.write_text(yaml_edit.edit_yaml(path.read_text(encoding="utf-8"), TEMPLATE_SWITCHES, [], None), encoding="utf-8")


def new_holder(test: Any, app_dir: str | None = None) -> tuple[config_live.Holder, Path]:
    """A Holder over config.yaml (the defaults) and a secret.key in a folder
    the test cleans up."""
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "config.yaml"
    config.write_new(path)
    pin_switches(path)
    if app_dir is not None:
        raw = path.read_text(encoding="utf-8").replace('app_dir: ""', f'app_dir: "{app_dir}"', 1)
        path.write_text(raw, encoding="utf-8")
    file = config.read_file(path)
    cfg = config.build_config(file, path, config.resolve_paths(file, path), config_secret.read_secret(config_secret.secret_path_for(path)))
    from dataclasses import replace

    holder = config_live.Holder(replace(cfg, raw=config_live.read_raw(path)))
    return holder, path


@contextlib.contextmanager
def in_container(config_file: Path, app_dir: Path) -> Iterator[None]:
    """InContainer() true for the duration, with the image's layout pointed
    at the test's files."""
    pinned = layout.Layout(config_file=str(config_file), app_dir=str(app_dir), host="0.0.0.0")
    with mock.patch.object(layout, "PINNED", pinned), mock.patch.object(config_live, "PINNED", pinned):
        yield


def sample_value(key: Any) -> Any:
    """A valid value different from the default."""
    special = {
        "server.public_url": "https://app.example.com",
        "app.repo": "https://github.com/you/app",
        "server.trusted_proxies": ["10.0.0.0/8"],
        "server.proxy_header": "X-Real-IP",
        "server.maintenance": "read_only",
        "server.host": "0.0.0.0",
        "server.port": 9999,
        "logs.max_file_mb": 10,
        "docker.image": "other-image",
        "docker.container": "other-container",
        "docker.bind_address": "0.0.0.0",
        "docker.restart": "always",
        "docker.memory": "512m",
        "docker.cpus": "2",
        "docker.tmpfs_size": "32m",
        # MediaTracker: a poster host has to be a host name.
        "images.allow_hosts": ["posters.example.org"],
    }
    if key.path in special:
        return special[key.path]
    if key.type == "bool":
        return not key.default
    if key.type == "int":
        return key.default + 1
    if key.type == "string":
        return key.default + "-changed"
    return ["x"]


def sample_changes(key: Any) -> dict[str, Any]:
    changes = {key.path: sample_value(key)}
    if key.path == "server.trust_proxy":
        # validate() refuses one without the other.
        changes["server.trusted_proxies"] = ["127.0.0.1"]
    return changes
