"""/api/me says where the API reference is: openapi.json in app.repo when that
is set, else this server's own copy."""
from __future__ import annotations

import unittest

from app.tests.route_support import RoutesTestCase


class MeSaysWhereTheAPIReferenceIs(RoutesTestCase):
    def test_without_and_with_a_repo(self) -> None:
        self.set_config(repo="")
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual((me["openapi_url"], me["repo"]), ("/api/openapi.json", ""))
        self.set_config(repo="https://github.com/you/app", description="Counts things.")
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual(me["openapi_url"], "https://github.com/you/app/blob/HEAD/config/openapi.json")
        self.assertEqual((me["repo"], me["description"]), ("https://github.com/you/app", "Counts things."))


if __name__ == "__main__":
    unittest.main()
