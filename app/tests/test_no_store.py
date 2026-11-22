"""S11: every route answers with Cache-Control: no-store and Vary: Cookie,
Authorization, so no proxy or CDN in front of the app may keep a copy of a
reply for the next visitor. Static files keep their own rule."""
from __future__ import annotations

import re

from starlette.routing import Route

from app.tests.route_support import RoutesTestCase

STREAMS = {"/api/owner/logs/stream"}  # never end; app/core/sse.py sets no-store itself


class NoStoreTest(RoutesTestCase):
    def test_every_route_says_no_store(self) -> None:
        """GETs are asked by the signed-in owner, so the reply is the real one;
        other methods fail on the csrf token, so they are checked on the error
        path."""
        checked = 0
        for route in self.app.routes:
            if not isinstance(route, Route) or route.path in STREAMS:
                continue
            path = re.sub(r"\{[^}]+\}", "1", route.path)
            for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
                cookie = self.owner_cookie if method == "GET" else ""
                response = self.request(method, path, cookie=cookie, body={} if method != "GET" else None)
                with self.subTest(f"{method} {route.path}", status=response.status_code):
                    self.assertIn("no-store", response.headers.get("cache-control", ""))
                    if route.path.startswith("/api/"):
                        self.assertIn("Cookie", response.headers.get("vary", ""))
                checked += 1
        self.assertGreater(checked, 20)

    def test_static_files_keep_their_own_rule(self) -> None:
        self.assertIn("max-age=", self.client.get("/favicon.ico").headers["cache-control"])
        # index.html is revalidated, not refused: the browser may keep it, a
        # shared cache may not.
        cache = self.client.get("/").headers["cache-control"]
        self.assertIn("private", cache)
        self.assertIn("no-cache", cache)
