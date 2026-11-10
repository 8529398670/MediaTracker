"""Themes: someone's own list, the admin's defaults everyone else follows, and
only shapes theme.js can paint."""
from __future__ import annotations

from app.tests.route_support import RoutesTestCase


def theme_list(*names: str) -> list[dict]:
    return [{"id": name, "name": name, "mode": "light", "accent": "#1F5FD6", "second": "#0b7a75"} for name in names]


class ThemeRoutesTest(RoutesTestCase):
    def mine(self, cookie: str) -> tuple[object, bool, str]:
        status, me = self.call("GET", "/api/me", cookie=cookie)
        self.assertEqual(status, 200)
        return me["themes"], me["themes_custom"], me["theme_id"]

    def post(self, cookie: str, path: str, body: dict, csrf: bool = True) -> tuple[int, object]:
        if csrf:
            body = dict(body, csrf_token=self.csrf(cookie))
        return self.call("POST", path, cookie=cookie, body=body)

    def test_they_follow_the_defaults_until_changed(self) -> None:
        # Nothing saved anywhere: the browser's built-in themes.
        self.assertEqual(self.mine(self.user_cookie), (None, False, ""))

        # An admin's defaults reach everyone without their own list.
        status, reply = self.post(self.owner_cookie, "/api/admin/theme-defaults", {"themes": theme_list("one", "two")})
        self.assertEqual(status, 200, reply)
        listed, custom, _ = self.mine(self.user_cookie)
        self.assertEqual([theme["id"] for theme in listed], ["one", "two"])
        self.assertFalse(custom)

        # Their own list is theirs; colors come back in lower case.
        status, reply = self.post(self.user_cookie, "/api/account/themes", {"themes": theme_list("mine"), "theme_id": "mine"})
        self.assertEqual(status, 200, reply)
        listed, custom, theme_id = self.mine(self.user_cookie)
        self.assertEqual((len(listed), custom, theme_id), (1, True, "mine"))
        self.assertEqual(listed[0]["accent"], "#1f5fd6")

        # Later defaults no longer reach them.
        self.post(self.owner_cookie, "/api/admin/theme-defaults", {"themes": theme_list("three")})
        self.assertEqual(self.mine(self.user_cookie)[0][0]["id"], "mine")

        # Picking keeps the list.
        self.assertEqual(self.post(self.user_cookie, "/api/account/theme", {"theme_id": "other"})[0], 200)
        listed, _, theme_id = self.mine(self.user_cookie)
        self.assertEqual((len(listed), theme_id), (1, "other"))

        # null goes back to the defaults, and null defaults to the built-in ones.
        self.post(self.user_cookie, "/api/account/themes", {"themes": None})
        listed, custom, _ = self.mine(self.user_cookie)
        self.assertEqual((listed[0]["id"], custom), ("three", False))
        self.post(self.owner_cookie, "/api/admin/theme-defaults", {"themes": None})
        self.assertIsNone(self.mine(self.user_cookie)[0])

    def test_defaults_are_for_admins(self) -> None:
        self.assertNotEqual(self.call("GET", "/api/admin/theme-defaults", cookie=self.user_cookie)[0], 200)
        self.assertNotEqual(self.post(self.user_cookie, "/api/admin/theme-defaults", {"themes": theme_list("x")})[0], 200)

    def test_they_need_the_csrf_token(self) -> None:
        self.assertEqual(self.post(self.user_cookie, "/api/account/themes", {"themes": theme_list("x")}, csrf=False)[0], 403)
        self.assertFalse(self.mine(self.user_cookie)[1])

    def test_bad_shapes_are_refused(self) -> None:
        good = theme_list("a")[0]
        for themes in (
            [],
            "a",
            [dict(good, id="Has Space")],
            [good, good],
            [dict(good, name="  ")],
            [dict(good, mode="dim")],
            [dict(good, accent="red")],
            [dict(good, surface="#fff")],
            [dict(good, overrides={"glow": "#000000"})],
            [dict(good, overrides={"link": "blue"})],
            [dict(good, button={"shape": "blob"})],
            [dict(good, button={"depth": "deep"})],
            [dict(good, button={"glow": "on"})],
            [dict(good, button="pill")],
            [dict(good, dark={"accent": "gold", "second": "#ffffff"})],
            [dict(good, dark={"accent": "#000000", "second": "#ffffff", "overrides": {"glow": "#000000"}})],
            [dict(good, dark="gold")],
        ):
            status, reply = self.post(self.user_cookie, "/api/account/themes", {"themes": themes})
            self.assertEqual(status, 400, (themes, reply))
        self.assertFalse(self.mine(self.user_cookie)[1])

        # Overrides by name are kept.
        status, reply = self.post(self.user_cookie, "/api/account/themes",
                                  {"themes": [dict(good, overrides={"link": "#ABCDEF", "infoBorder": "#000000"})]})
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.mine(self.user_cookie)[0][0]["overrides"], {"link": "#abcdef", "infoBorder": "#000000"})

        # A button style, and a button variant's color, are kept; an empty
        # button is the default and is not stored.
        styled = dict(good, overrides={"btnDanger": "#AA0000", "btnWarningFg": "#000000"},
                      button={"shape": "Pill", "depth": "glossy"})
        plain = dict(theme_list("b")[0], button={})
        status, reply = self.post(self.user_cookie, "/api/account/themes", {"themes": [styled, plain]})
        self.assertEqual(status, 200, reply)
        listed = self.mine(self.user_cookie)[0]
        self.assertEqual(listed[0]["button"], {"shape": "pill", "depth": "glossy"})
        self.assertEqual(listed[0]["overrides"]["btnDanger"], "#aa0000")
        self.assertNotIn("button", listed[1])

        # A light theme keeps its dark colors (switching mode swaps them in);
        # colors kept for the mode already in use mean nothing and are dropped.
        both = dict(good, dark={"accent": "#CBA052", "second": "#F8E08E", "background": "#101820",
                                "overrides": {"link": "#FFFFFF"}},
                    light={"accent": "#000000", "second": "#000000"})
        status, reply = self.post(self.user_cookie, "/api/account/themes", {"themes": [both]})
        self.assertEqual(status, 200, reply)
        listed = self.mine(self.user_cookie)[0]
        self.assertEqual(listed[0]["dark"], {"accent": "#cba052", "second": "#f8e08e", "background": "#101820",
                                             "overrides": {"link": "#ffffff"}})
        self.assertNotIn("light", listed[0])
