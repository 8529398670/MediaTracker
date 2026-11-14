"""The route list comes from the declarations (app/routes/__init__.py): each
route at the path its @route(...) gives, the most specific first, behind the
guards its access, role and feature imply. Go writes the same table with its
generator (server/apidoc/routegen), whose tests hold it to the same rules."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.apidocs import ADMIN, PUBLIC
from app.apidocs.route import Reply, declared_of, route
from app.core.security import RequireAdmin, RequireOwner
from app.routes import _ambiguous, _order, admin, declared_routes, guards_of, meta
from app.routes import RequireTwoFactor, two_factor
from app.routes import RequirePasswords, passwords
from app.routes.auth import SameOriginLogin


class Nothing(Reply):
    pass


def declared(where: str) -> SimpleNamespace:
    """What the ordering reads of a route: its method and path."""
    method, _, path = where.partition(" ")
    return SimpleNamespace(method=method, path=path)


class RouteListTest(unittest.TestCase):
    def test_the_most_specific_path_comes_first(self) -> None:
        for first, second in [("/a/b", "/a/{x}"), ("/a/{x}/b", "/a/{x}/{y}"), ("/a", "/a/b"), ("/a/b", "/a/c")]:
            with self.subTest(first=first, second=second):
                self.assertLess(_order(declared("GET " + first)), _order(declared("GET " + second)))

    def test_two_routes_that_can_match_one_request_clash(self) -> None:
        self.assertFalse(_ambiguous(declared("GET /a/b"), declared("GET /a/{x}")), "the literal wins")
        self.assertFalse(_ambiguous(declared("GET /a/{x}"), declared("POST /a/{y}")), "two methods never clash")
        self.assertTrue(_ambiguous(declared("GET /a/{x}"), declared("GET /a/{y}")))
        self.assertTrue(_ambiguous(declared("GET /a/{x}/b"), declared("GET /a/b/{y}")))

    def test_a_path_names_the_requests_path_fields(self) -> None:
        def handler(request: object) -> Nothing:
            return Nothing()

        route("GET /a", summary="x", tag="x")(handler)
        for where in ("GET /a/{user_id}", "/a"):
            with self.subTest(where), self.assertRaises(TypeError):
                route(where, summary="x", tag="x")(handler)

    def test_the_guards_follow_from_the_declaration(self) -> None:
        cases = [
            (admin.list_users, (RequireAdmin,)),
            (meta.get_health, ()),
            (admin.reset_two_factor, (RequireTwoFactor, RequireAdmin)),
            (two_factor.finish_sign_in, (SameOriginLogin,)),
            (passwords.login_options, ()),
            (passwords.set_password_access, (RequirePasswords, RequireOwner)),
        ]
        for endpoint, guards in cases:
            with self.subTest(endpoint.__name__):
                self.assertEqual(guards_of(declared_of(endpoint)), guards)
        self.assertEqual(declared_of(admin.list_users).op.role, ADMIN)
        self.assertEqual(declared_of(meta.get_health).op.access, PUBLIC)

    def test_every_route_is_listed_once_in_order(self) -> None:
        listed = declared_routes()
        self.assertEqual(len({(route.method, route.path) for route in listed}), len(listed))
        self.assertEqual(listed, sorted(listed, key=_order))
        self.assertEqual(declared_of(admin.create_user).guards, (RequireAdmin,))
        self.assertEqual(declared_of(admin.create_user).errors, (400, 401, 403))


if __name__ == "__main__":
    unittest.main()
