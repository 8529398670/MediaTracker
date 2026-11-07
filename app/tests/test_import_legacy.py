"""Bringing the old app's data across: people by name (halo the owner), the
old shared status becoming halo's own, the queue order kept as halo's
"Up next" playlist, posters keeping their cache keys, and running it twice
changing nothing."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core import db
from app.legacy.import_legacy import import_legacy
from app.models import library_cache, playlists, user_state, users
from app.reference.images import key_for
from app.reference.paths import Paths

POSTER = "https://image.tmdb.org/t/p/w342/abc.jpg"


def item(ident: str, title: str, status: str = "queue", order: int | None = None, **extra: object) -> dict:
    return {"id": ident, "title": title, "year": 1930, "type": "movie", "status": status, "order": order, "addedAt": "2026-09-01T00:00:00Z", **extra}


class LegacyImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.old = root / "old"
        (self.old / "cache" / "img").mkdir(parents=True)
        (self.old / "cache" / "img" / f"{key_for(POSTER)}.jpg").write_bytes(b"jpeg")
        items = [
            item("a" * 32, "Second", order=2),
            item("b" * 32, "First", order=1, poster="/api/img?u=" + POSTER.replace(":", "%3A").replace("/", "%2F")),
            item("c" * 32, "Seen", status="watched", watchedAt="2026-09-02T00:00:00Z", heart=True),
            item("d" * 32, "Radio thing", type="radio-drama"),
        ]
        (self.old / "library.json").write_text(json.dumps({"app": "media-tracker", "items": items, "sources": [{"url": "https://example.com/list"}]}))
        (self.old / "users.json").write_text(json.dumps({"users": {"u2": {"name": "Mom", "createdAt": "2026-09-26T00:00:00Z"}, "u1": {"name": "halo", "createdAt": "2026-09-25T00:00:00Z"}}}))
        (self.old / "verdicts.json").write_text(json.dumps({"verdicts": {"w:x": {"verdict": "skip", "at": "2026-09-29"}}}))
        self.store = db.Store(root / "app.db", "", False)
        self.store.initialise()
        self.paths = Paths(root / "storage")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_import(self) -> None:
        report, user_map = import_legacy(self.store, self.paths, self.old)
        halo = users.get_user(self.store, user_map["u1"])
        self.assertEqual((halo.display_name, halo.role, users.get_owner_id(self.store)), ("halo", users.ROLE_ADMIN, halo.id))
        self.assertEqual(users.get_user(self.store, user_map["u2"]).role, users.ROLE_USER)
        self.assertEqual(report.titles, 4)
        self.assertIn("radio-drama", report.types_created)
        mine = playlists.list_playlists(self.store, halo.id)
        self.assertEqual([(playlist["name"], playlist["items"]) for playlist in mine], [("Up next", ["b" * 32, "a" * 32, "d" * 32])])
        seen = user_state.get_state(self.store, halo.id, "c" * 32)
        self.assertEqual((seen["status"], seen["heart"]), ("watched", True))
        self.assertEqual(playlists.list_playlists(self.store, user_map["u2"]), [])
        import_legacy(self.store, self.paths, self.old)
        self.assertEqual(len(playlists.list_playlists(self.store, halo.id)), 1)
        snapshot = library_cache.get(self.store)
        self.assertEqual(snapshot.titles["b" * 32]["poster_url"], POSTER)
        self.assertTrue((self.paths.images / f"{key_for(POSTER)}.jpg").is_file())

    def test_running_twice_changes_nothing(self) -> None:
        import_legacy(self.store, self.paths, self.old)
        report, _ = import_legacy(self.store, self.paths, self.old)
        self.assertEqual(report.users_created, [])
        self.assertEqual(len(users.list_users(self.store)), 2)
        self.assertEqual(len(library_cache.get(self.store).titles), 4)

    def test_adopts_the_first_run_admin(self) -> None:
        bootstrap = users.create_user(self.store, "Admin", users.ROLE_ADMIN)
        _, user_map = import_legacy(self.store, self.paths, self.old)
        self.assertEqual(user_map["u1"], bootstrap.id)
        self.assertEqual(users.get_user(self.store, bootstrap.id).display_name, "halo")


if __name__ == "__main__":
    unittest.main()
