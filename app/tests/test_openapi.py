"""config/openapi.json against the route table. A new route that is not in the
spec fails here, and so does an entry for a route that has gone."""
from __future__ import annotations

import json
import re
import unittest

from starlette.routing import Route

from app.core import assets
from app.tests.route_support import RoutesTestCase

# What the route table has that is not an API: the pages a link opens, and the
# catch-alls.
NOT_IN_THE_SPEC = {"/login/{credential:path}", "/join/{credential:path}", "/api/{rest:path}", "/{path:path}"}


def spec_routes() -> set[str]:
    document = json.loads(assets.OPENAPI_SPEC.read_text(encoding="utf-8"))
    return {f"{method.upper()} {path}" for path, methods in document["paths"].items() for method in methods}


class OpenAPITest(RoutesTestCase):
    def registered(self) -> set[str]:
        routes = set()
        for route in self.app.routes:
            if not isinstance(route, Route) or route.path in NOT_IN_THE_SPEC:
                continue
            path = re.sub(r"\{(\w+):\w+\}", r"{\1}", route.path)
            routes |= {f"{method} {path}" for method in route.methods if method in ("GET", "POST", "DELETE")}
        return routes

    def test_the_spec_and_the_route_table_agree(self) -> None:
        registered, spec = self.registered(), spec_routes()
        problems = sorted(
            [f"not in config/openapi.json: {name}" for name in registered - spec]
            + [f"in config/openapi.json but not a route: {name}" for name in spec - registered]
        )
        self.assertEqual(problems, [])

    def test_the_spec_is_for_signed_in_callers(self) -> None:
        self.assertEqual(self.call("GET", "/api/openapi.json")[0], 401)
        status, reply = self.call("GET", "/api/openapi.json", cookie=self.user_cookie)
        self.assertEqual((status, reply["openapi"]), (200, "3.1.0"))


if __name__ == "__main__":
    unittest.main()
