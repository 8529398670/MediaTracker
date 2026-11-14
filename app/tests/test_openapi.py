"""GET /api/openapi.json. The file itself is written from the code and kept
current by test_api_docs.py."""
from __future__ import annotations

import unittest

from app.tests.route_support import RoutesTestCase

class OpenAPITest(RoutesTestCase):
    def test_the_spec_is_for_signed_in_callers(self) -> None:
        self.assertEqual(self.call("GET", "/api/openapi.json")[0], 401)
        status, reply = self.call("GET", "/api/openapi.json", cookie=self.user_cookie)
        self.assertEqual((status, reply["openapi"]), (200, "3.1.0"))


if __name__ == "__main__":
    unittest.main()
