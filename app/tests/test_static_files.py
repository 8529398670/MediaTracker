"""The static server and where it may serve from (app/core/static_files.py,
app/core/assets.py). Go's twins are server/static/static_test.go and
server/assets/assets_test.go."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core import assets
from app.core.static_files import StaticServer


class DotfileTest(unittest.TestCase):
    def test_dotfiles_are_never_served(self) -> None:
        """S2: the static handler never serves a dotfile, whatever directory it
        was pointed at. .well-known/ is public by definition and still served."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("index.html", ".env", ".git/config", "css/.secret.css", ".well-known/security.txt"):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("x")
            server = StaticServer(root)
            for path in (".env", ".git/config", "css/.secret.css", "css/../.env"):
                with self.subTest(path=path):
                    self.assertIsNone(server.resolve(path))
            self.assertEqual(server.resolve(".well-known/security.txt"), (root / ".well-known/security.txt").resolve())
            self.assertEqual(server.resolve("index.html"), (root / "index.html").resolve())


class RevalidateTest(unittest.TestCase):
    def test_text_assets_revalidate(self) -> None:
        """A text asset is revalidated: its tag comes back as a 304 with no
        body while the file is unchanged, and a changed file gets a new tag
        and its bytes."""
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "js").mkdir()
            (root / "js" / "app.js").write_text("one")
            server = StaticServer(root)
            client = TestClient(Starlette(routes=[Route("/{path:path}", server.endpoint)]))

            first = client.get("/js/app.js")
            tag = first.headers["etag"]
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.headers["cache-control"], "private, no-cache")

            again = client.get("/js/app.js", headers={"if-none-match": tag})
            self.assertEqual(again.status_code, 304)
            self.assertEqual(again.content, b"")
            listed = client.get("/js/app.js", headers={"if-none-match": 'W/"0", ' + tag})
            self.assertEqual(listed.status_code, 304)

            (root / "js" / "app.js").write_text("two")
            changed = client.get("/js/app.js", headers={"if-none-match": tag})
            self.assertEqual(changed.status_code, 200)
            self.assertNotEqual(changed.headers["etag"], tag)


class ScreenPathTest(unittest.TestCase):
    def test_screen_paths_get_the_page(self) -> None:
        """Each path index.html declares with data-path, and each signed-out
        reason, is answered with index.html; any other path is still a 404.
        Adding a screen to index.html is enough, with no restart."""
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text(
                '<section class="view" data-view="users" data-path="/admin/users">'
                '<section class="card" id="x" data-path="/account/two-factor">'
            )
            server = StaticServer(root)
            client = TestClient(Starlette(routes=[Route("/{path:path}", server.endpoint)]))
            for path in ("/admin/users", "/admin/users/", "/account/two-factor", "/signed-out/ended"):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("data-view", response.text)
            for path in ("/admin", "/admin/users/x", "/nope", "/signed-out/other", "/users"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 404)

            (root / "index.html").write_text('<section class="view" data-view="logs" data-path="/admin/logs">')
            self.assertEqual(client.get("/admin/logs").status_code, 200)
            self.assertEqual(client.get("/admin/users").status_code, 404)


class StaticDirTest(unittest.TestCase):
    def test_static_dir_may_not_serve_secrets(self) -> None:
        """S2: everything in static_dir is served without signing in, so the
        server refuses to start when it would serve the config folder, the
        state folder, secret.key or the database."""
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            config_dir, app_dir, static_dir = project / "config", project / "state", project / "static"
            for folder in (config_dir, app_dir, static_dir, config_dir / "web"):
                folder.mkdir(parents=True)
            secret, database = config_dir / "secret.key", app_dir / "app.db"
            secret.write_text("key")
            database.write_text("db")
            protected = (config_dir, app_dir, secret, database)

            assets.check_static_dir(str(static_dir), *protected)
            assets.check_static_dir(str(project / "missing"), *protected)

            link = project / "link"
            link.symlink_to(config_dir)
            for name, folder in (
                ("the config dir", config_dir),
                ("the state dir", app_dir),
                ("inside the config dir", config_dir / "web"),
                ("above both", project),
                ("a link to config", link),
            ):
                with self.subTest(name):
                    with self.assertRaisesRegex(RuntimeError, "static_dir"):
                        assets.check_static_dir(str(folder), *protected)


if __name__ == "__main__":
    unittest.main()
