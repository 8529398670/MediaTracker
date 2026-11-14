"""The API reference is written from the code: config/openapi.json and
config/api.md from each handler's @route(...) declaration and its request and
reply types, and config/mcp.json from the registered MCP tools. scripts/api_docs.sh
(python -m app.apidocs) rewrites them; these fail while a committed file is
out of date, or a route has no docs. Go's twin is
server/routes/api_docs_test.go, and the two write the same bytes.

Every reply a route test gets is also held against its docs: see check_reply
in route_support.py."""
from __future__ import annotations

import unittest

from app.apidocs.generate import CONFIG, documents, spec


class APIDocs(unittest.TestCase):
    def test_every_route_is_documented(self) -> None:
        self.assertEqual(spec()[1], [])

    def test_the_api_docs_are_current(self) -> None:
        stale = []
        for name, want in documents().items():
            path = CONFIG / name
            if not path.is_file() or path.read_text(encoding="utf-8") != want:
                stale.append(f"config/{name} is out of date: run scripts/api_docs.sh")
        self.assertEqual(stale, [])


if __name__ == "__main__":
    unittest.main()
