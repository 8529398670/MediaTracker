"""Round 3 of the security fixes (S19-S20): who handed out a way into an
account, and what stays of it once that person loses the right. Go's twin is
server/routes/ways_in_test.go."""
from __future__ import annotations

import time
from typing import Any

from app.core import encryption
from app.core import logs
from app.core.security import decrypt_cookie
from app.models import login_tokens, sessions, users
from app.models import api_keys
from app.tests.route_support import RoutesTestCase, TestClient

def code_for(secret: str, step_offset: int = 0) -> str:
    step = int(time.time()) // encryption.TOTP_PERIOD_SECONDS + step_offset
    return encryption.totp_code(secret, step)


class WaysInTest(RoutesTestCase):
    def browser(self) -> TestClient:
        # https, or the Secure session cookie is dropped and the browser was
        # never signed in at all.
        return TestClient(self.app, base_url="https://testserver", raise_server_exceptions=False)

    def redeem(self, client: TestClient, login_path: str) -> tuple[int, Any]:
        return self.call("POST", "/api/login", body={"credential": login_path.removeprefix("/login/")}, client=client)

    def send(self, who: str | TestClient, path: str, **body: Any) -> tuple[int, Any]:
        """POST as a person (a cookie) or a browser (a client with its own
        cookie jar), with the CSRF token that goes with it."""
        if isinstance(who, str):
            return self.call("POST", path, cookie=who, body={**body, "csrf_token": self.csrf(who)})
        token = self.call("GET", "/api/me", client=who)[1]["csrf_token"]
        return self.call("POST", path, body={**body, "csrf_token": token}, client=who)

    def signed_in(self, client: TestClient) -> bool:
        return self.call("GET", "/api/me", client=client)[0] == 200

    @staticmethod
    def user_path(user_id: int, verb: str) -> str:
        return f"/api/admin/users/{user_id}/{verb}"

    def test_losing_the_right_ends_what_the_keys_made(self) -> None:
        """S20: disabling an admin, or taking their admin role away, ends what
        their keys made: links not yet used stop working, and browsers signed
        in through them are signed out. Before, both outlived the admin's
        right to make them."""
        for how in ("disable", "demote"):
            with self.subTest(how):
                # Bob's key reissues Alice a link that never runs out, and it
                # signs a browser in.
                bob = users.create_user(self.store, "Bob " + how, users.ROLE_ADMIN)
                key, _ = api_keys.issue_api_key(self.store, bob.id, "ops", users.ROLE_ADMIN, 3600)
                body = {"max_uses": 0, "expires_in_minutes": 0}
                status, reply = self.call("POST", self.user_path(self.user.id, "reissue-login"), key=key, body=body)
                self.assertEqual(status, 200, reply)
                link = reply["login_path"]
                early = self.browser()
                self.assertEqual(self.redeem(early, link)[0], 200)
                person = self.session(self.user.id)

                if how == "disable":
                    status, reply = self.send(self.owner_cookie, self.user_path(bob.id, "disabled"), disabled=True)
                else:
                    status, reply = self.send(self.owner_cookie, self.user_path(bob.id, "role"), role="user")
                self.assertEqual(status, 200, reply)
                self.assertFalse(self.signed_in(early), "the browser Bob's key signed in is still signed in")
                self.assertNotEqual(self.redeem(self.browser(), link)[0], 200, "the link Bob's key made still signs in")
                self.assertEqual(self.call("GET", "/api/me", cookie=person)[0], 200, "a session nobody's key made was signed out")

    def test_revoking_or_deleting_ends_what_the_keys_made(self) -> None:
        """S22: revoking an account's access, or deleting it, ends what its
        keys made in other accounts too, as disabling does (S20). Before, both
        stopped the keys themselves but left their links and the browsers
        those signed in."""
        for how in ("revoke-access", "delete"):
            with self.subTest(how):
                bob = users.create_user(self.store, "Bob " + how, users.ROLE_ADMIN)
                key, _ = api_keys.issue_api_key(self.store, bob.id, "ops", users.ROLE_ADMIN, 3600)
                body = {"max_uses": 0, "expires_in_minutes": 0}
                status, reply = self.call("POST", self.user_path(self.user.id, "reissue-login"), key=key, body=body)
                self.assertEqual(status, 200, reply)
                link = reply["login_path"]
                early = self.browser()
                self.assertEqual(self.redeem(early, link)[0], 200)
                person = self.session(self.user.id)

                status, reply = self.send(self.owner_cookie, self.user_path(bob.id, how))
                self.assertEqual(status, 200, reply)
                self.assertFalse(self.signed_in(early), "the browser Bob's key signed in is still signed in")
                self.assertNotEqual(self.redeem(self.browser(), link)[0], 200, "the link Bob's key made still signs in")
                self.assertEqual(self.call("GET", "/api/me", cookie=person)[0], 200, "a session nobody's key made was signed out")

    def test_signing_in_through_an_admins_link_is_logged(self) -> None:
        """S19: an admin can sign in as anyone below them, by resetting
        two-factor and reissuing a link. That is how links work, so it is made
        visible: the session records who issued its link, and the account's
        own log says so. A link from a shell, or the account's own, names
        nobody."""
        with TestClient(self.app):  # runs the lifespan, which writes the log
            status, reply = self.send(self.owner_cookie, self.user_path(self.user.id, "reissue-login"))
            self.assertEqual(status, 200, reply)
            alice = self.browser()
            self.assertEqual(self.redeem(alice, reply["login_path"])[0], 200)
            self.assertEqual(self.session_of(alice).issued_by, self.owner.id)
            self.assertEqual(self.redeem(self.browser(), "/login/" + login_tokens.issue_login_token(self.store, self.user.id, 3600))[0], 200)
            status, reply = self.send(alice, "/api/account/login-link")
            self.assertEqual(status, 200, reply)
            self.assertEqual(self.redeem(self.browser(), reply["login_path"])[0], 200)
            # Through a two-factor code, the finished sign-in says it too.
            secret = self.send(alice, "/api/account/two-factor/start")[1]["secret"]
            self.assertEqual(self.send(alice, "/api/account/two-factor/confirm", code=code_for(secret))[0], 200)
            reply = self.send(self.owner_cookie, self.user_path(self.user.id, "reissue-login"))[1]
            later = self.browser()
            status, reply = self.redeem(later, reply["login_path"])
            self.assertEqual(status, 200, reply)
            status, reply = self.call("POST", "/api/login/two-factor", body={"challenge": reply["challenge"], "code": code_for(secret, 1)}, client=later)
            self.assertEqual(status, 200, reply)
            self.assertEqual((reply, self.session_of(later).issued_by), ({"ok": True}, self.owner.id))
        logger = self.app.state.logs
        entries, _ = logger.read_day(logger.today(), logs.Query("kind:auth"))
        mine = [entry for entry in entries if entry.get("actor", {}).get("user_id") == self.user.id]
        issued = [entry for entry in mine if entry.get("msg") == "signed in with a link issued by Owner"]
        plain = [entry for entry in mine if entry.get("msg") == "signed in with a login link"]
        self.assertEqual([entry.get("detail") for entry in issued], [{"issued_by": self.owner.id}])
        self.assertEqual([entry.get("detail") for entry in plain], [None, None])
        coded = [entry for entry in mine if entry.get("msg") == "signed in with a two-factor code, through a link issued by Owner"]
        self.assertEqual([entry.get("detail") for entry in coded], [{"issued_by": self.owner.id}])

    def session_of(self, client: TestClient) -> Any:
        """The session record behind a browser's cookie."""
        credential = decrypt_cookie(self.cfg, client.cookies.get(self.cfg.session_cookie_name))
        return sessions.load_session(self.store, credential)[0]
