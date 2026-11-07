"""Where reference data lives under the storage directory. One place, so the
importer, the jobs and the routes cannot disagree about a path."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def reference(self) -> Path:
        return self.root / "reference"

    @property
    def lists(self) -> Path:
        return self.reference / "lists"

    @property
    def certs(self) -> Path:
        return self.reference / "certs.json"

    @property
    def imdb(self) -> Path:
        return self.reference / "imdb"

    @property
    def images(self) -> Path:
        return self.root / "cache" / "img"

    @property
    def legacy(self) -> Path:
        return self.root / "legacy"

    def ensure(self) -> None:
        for folder in (self.lists, self.imdb, self.images, self.legacy):
            folder.mkdir(parents=True, exist_ok=True)


_paths: Paths | None = None


def configure(storage_dir: Path) -> Paths:
    global _paths
    _paths = Paths(storage_dir)
    _paths.ensure()
    return _paths


def get() -> Paths:
    if _paths is None:
        raise RuntimeError("reference.paths.configure() was not called")
    return _paths
