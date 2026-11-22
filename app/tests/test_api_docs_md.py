"""GET /api/api.md and the /docs/api page: the readable API reference, for
signed-in callers only, and where /api/me points the API keys card."""
from __future__ import annotations

import unittest

from app.core import assets
from app.tests.route_support import RoutesTestCase


class ReadableReferenceTest(RoutesTestCase):
    def test_the_markdown_is_for_signed_in_callers(self) -> None:
        self.assertEqual(self.call("GET", "/api/api.md")[0], 401)
        response = self.request("GET", "/api/api.md", self.user_cookie)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/markdown"))
        self.assertEqual(response.content, assets.API_DOC.read_bytes())

    def test_the_page_is_served_for_its_paths(self) -> None:
        response = self.request("GET", "/docs/api")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="docs-root"', response.content)
        self.assertEqual(response.headers["x-robots-tag"], "noindex")

    def test_me_says_where_it_is(self) -> None:
        self.set_config(repo="")
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["api_doc_url"], "/docs/api")
        self.set_config(repo="https://github.com/you/app")
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["api_doc_url"], "https://github.com/you/app/blob/HEAD/config/api.md")


if __name__ == "__main__":
    unittest.main()
