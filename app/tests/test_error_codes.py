"""Every 4xx answer carries a code from one closed list (portal contract v3,
item 4), so a caller branches on code and shows error. These tests walk the
whole route table, so a new route that refuses some other way fails here."""
from __future__ import annotations

import re
import unittest
from typing import Any

from app import apidocs
from app.apidocs.generate import documented_routes
from app.core.error_codes import (
    CODE_FORBIDDEN, CODE_INVALID, CODE_KEY_MINTING_OFF, CODE_NOT_ADMIN, CODE_NOT_AUTHENTICATED, CODE_NOT_FOUND,
    CODE_OWNER_PROTECTED, CODE_OWNER_REQUIRED, CODE_RATE_LIMITED, CODE_SESSION_ONLY, CODE_VIEW_ONLY, ERROR_CODES, status_code,
)
from app.core.security import viewer_may_call
from app.models import users
from app.models import api_keys
from app.tests.route_support import RoutesTestCase

PATH_PARAM = re.compile(r"\{[^}]+\}")


class StatusCodes(unittest.TestCase):
    def test_every_4xx_status_has_a_listed_code(self) -> None:
        for status in range(400, 500):
            self.assertIn(status_code(status), ERROR_CODES, status)
        self.assertEqual((status_code(503), status_code(200)), ("", ""))


class MeListsErrorCodes(RoutesTestCase):
    def test_listed(self) -> None:
        self.assertIn("error_codes", self.call("GET", "/api/me", cookie=self.user_cookie)[1]["capabilities"])


class CodedTestCase(RoutesTestCase):
    def want_code(self, what: str, status: int, reply: Any, want: str = "") -> None:
        if not 400 <= status < 500:
            return
        self.assertIsInstance(reply, dict, f"{what}: {status} {reply}")
        self.assertIn(reply.get("code"), ERROR_CODES, f"{what}: {status} {reply} has no listed code")
        self.assertTrue(reply.get("error"), f"{what}: {status} {reply} has no error")
        if want:
            self.assertEqual(reply["code"], want, f"{what}: {status} {reply}")


class EveryRouteRefusesWithACode(CodedTestCase):
    def test_the_whole_route_table(self) -> None:
        spec, _ = apidocs.build(documented_routes(self.app.routes))
        viewer = users.create_user(self.store, "Vera", users.ROLE_VIEWER)
        viewer_key, _ = api_keys.issue_api_key(self.store, viewer.id, "reader", users.ROLE_VIEWER, 3600)
        user_key, _ = api_keys.issue_api_key(self.store, self.user.id, "script", users.ROLE_USER, 3600)
        csrf = self.csrf(self.owner_cookie)
        for path in sorted(spec["paths"]):
            # MCP's transport answers in JSON-RPC, as its protocol says.
            if path == "/mcp":
                continue
            url = PATH_PARAM.sub("1", path)
            for method, op in spec["paths"][path].items():
                if not isinstance(op, dict):
                    continue
                method = method.upper()
                what = f"{method} {path}"
                public = not op.get("security")
                role = op.get("x-required-role", "")
                # No credential: 401 not_authenticated, unless anyone may
                # call it. The owner's routes answer everyone else 404, so
                # they give nothing away.
                status, reply = self.call(method, url, body={})
                if status == 404 and spec["paths"][path].get("x-feature"):
                    # A part this test app has switched off.
                    self.want_code(f"{what} switched off", status, reply, CODE_NOT_FOUND)
                    continue
                if role == "owner":
                    self.want_code(f"{what} with no credential", status, reply, CODE_NOT_FOUND)
                elif not public:
                    self.assertEqual(status, 401, f"{what} with no credential: {reply}")
                    self.want_code(f"{what} with no credential", status, reply, CODE_NOT_AUTHENTICATED)
                else:
                    self.want_code(f"{what} with no credential", status, reply)
                # An ordinary user's key on an admin's route, a viewer's key writing.
                if role in ("admin", "owner"):
                    status, reply = self.call(method, url, key=user_key, body={})
                    self.want_code(f"{what} with a user key", status, reply, {"admin": CODE_NOT_ADMIN, "owner": CODE_NOT_FOUND}[role])
                if not public and method != "GET" and not viewer_may_call(f"{method} {url}"):
                    status, reply = self.call(method, url, key=viewer_key, body={})
                    self.want_code(f"{what} with a viewer key", status, reply, CODE_VIEW_ONLY)
                # A field no route has, from the owner's own session.
                if method != "GET":
                    status, reply = self.call(method, url, cookie=self.owner_cookie, body={"csrf_token": csrf, "not_a_field": 1})
                    self.want_code(f"{what} with an unknown field", status, reply)


class TheCodesSayWhy(CodedTestCase):
    def test_one_field_is_named(self) -> None:
        csrf = self.csrf(self.owner_cookie)
        status, reply = self.call("POST", "/api/account/rename", cookie=self.owner_cookie, body={"csrf_token": csrf, "display_name": ""})
        self.want_code("an empty name", status, reply, CODE_INVALID)
        self.assertEqual(reply.get("field"), "display_name", reply)
        status, reply = self.call("POST", "/api/account/rename", cookie=self.owner_cookie, body={"csrf_token": csrf, "display_name": "X", "not_a_field": 1})
        self.want_code("an unknown field", status, reply, CODE_INVALID)
        self.assertEqual(reply.get("field"), "not_a_field", reply)

    def test_the_ladder(self) -> None:
        peer = users.create_user(self.store, "Pia", users.ROLE_ADMIN)
        csrf = self.csrf(self.admin_cookie)
        for action, body, target, want in (
            ("disabled", {"disabled": True}, self.owner, CODE_OWNER_PROTECTED),
            ("role", {"role": "user"}, self.owner, CODE_OWNER_PROTECTED),
            ("role", {"role": "user"}, peer, CODE_OWNER_REQUIRED),
            ("delete", {}, peer, CODE_OWNER_REQUIRED),
            ("reissue-login", {}, peer, CODE_OWNER_REQUIRED),
        ):
            status, reply = self.call("POST", f"/api/admin/users/{target.id}/{action}", cookie=self.admin_cookie, body={"csrf_token": csrf, **body})
            self.want_code(f"{action} on {target.display_name}", status, reply, want)

    def test_a_bad_csrf_token_is_forbidden(self) -> None:
        status, reply = self.call("POST", "/api/account/rename", cookie=self.owner_cookie, body={"csrf_token": "nope", "display_name": "X"})
        self.want_code("a bad csrf token", status, reply, CODE_FORBIDDEN)

    def test_keys(self) -> None:
        status, reply = self.call("POST", "/api/keys", key=self.admin_key, body={"name": "x", "role": "user"})
        self.want_code("a key making a key", status, reply, CODE_SESSION_ONLY)
        status, reply = self.call("GET", f"/api/admin/users/{self.user.id}/keys", key=self.admin_key)
        self.want_code("a key that may not mint", status, reply, CODE_KEY_MINTING_OFF)
        self.assertEqual(reply["error"], "key_minting_off")
        status, reply = self.call("GET", "/api/me", key="nope.nope")
        self.want_code("a bad key", status, reply, CODE_NOT_AUTHENTICATED)

    def test_too_many_requests(self) -> None:
        self.set_config(rate_limit_max=1)
        for _ in range(5):
            status, reply = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.want_code("a 429", status, reply, CODE_RATE_LIMITED)

    def test_an_unknown_api_path(self) -> None:
        status, reply = self.call("GET", "/api/no-such-thing", cookie=self.user_cookie)
        self.want_code("an unknown path", status, reply, CODE_NOT_FOUND)
