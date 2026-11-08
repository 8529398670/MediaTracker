"""The active sessions list (app/routes/sessions.py): every way of signing in
notes the device, the list shows only your own and nothing secret, and signing
another device out is checked against who is asking."""
from __future__ import annotations

import time
import unittest
from datetime import timedelta
from unittest import mock

from app.core import db, encryption, security
from app.core import logs
from app.models import login_tokens, sessions, to_iso, users, utc_now
from app.models import credentials
from app.models import invite_links
from app.models.sign_in import SignInRules
from app.tests.route_support import RoutesTestCase, TestClient

BROWSER = "Mozilla/5.0 (Test) " + "x" * 400


class SessionRecordTest(RoutesTestCase):
    def test_a_record_from_before_these_fields_still_loads(self) -> None:
        now = utc_now()
        secret = "s3cret"
        self.store.put(db.BUCKET_SESSIONS, "old", {
            "user_id": self.owner.id,
            "secret_hash": encryption.sha256_hex(secret),
            "csrf_token": "t",
            "created_at": to_iso(now),
            "expires_at": to_iso(now + timedelta(hours=1)),
        })
        session, user = sessions.load_session(self.store, f"old.{secret}")
        self.assertEqual(user.id, self.owner.id)
        self.assertEqual(session.id, "old")
        self.assertIsNone(session.last_seen_at)
        self.assertEqual((session.ip, session.user_agent), ("", ""))

    def test_the_id_is_never_stored(self) -> None:
        _, _, session = sessions.new_session(self.owner.id, 3600)
        session.id = "transient"
        self.assertNotIn("id", session.to_record())
        self.assertNotIn("ip", session.to_record())

    def test_the_optional_fields_round_trip(self) -> None:
        _, _, session = sessions.new_session(self.owner.id, 3600)
        session.ip, session.user_agent, session.last_seen_at = "10.0.0.1", "curl", utc_now()
        back = sessions.Session.from_record(session.to_record())
        self.assertEqual((back.ip, back.user_agent, back.last_seen_at), (session.ip, session.user_agent, session.last_seen_at))


class TouchTest(RoutesTestCase):
    def record(self, session_id: str) -> dict:
        return self.store.get(db.BUCKET_SESSIONS, session_id)

    def credential(self) -> tuple[str, str]:
        login = login_tokens.issue_login_token(self.store, self.owner.id, 3600)
        credential = login_tokens.redeem_login_token(self.store, login, SignInRules(3600)).session_credential
        return credential, credential.partition(".")[0]

    def test_loading_a_session_is_not_activity(self) -> None:
        credential, session_id = self.credential()
        sessions.load_session(self.store, credential)
        self.assertNotIn("last_seen_at", self.record(session_id))

    def test_a_request_touches_at_most_every_interval(self) -> None:
        credential, session_id = self.credential()
        cookie = {self.cfg.cookie_name: encryption.xchacha_encrypt_string(self.cfg.secret_key, credential)}
        security.resolve_actor(self.store, self.cfg, cookie, "")
        first = self.record(session_id)["last_seen_at"]

        security.resolve_actor(self.store, self.cfg, cookie, "")
        self.assertEqual(self.record(session_id)["last_seen_at"], first)

        stale = to_iso(utc_now() - sessions.SESSION_TOUCH_INTERVAL - timedelta(seconds=1))
        self.store.update_value(db.BUCKET_SESSIONS, session_id, lambda record: record.update(last_seen_at=stale))
        security.resolve_actor(self.store, self.cfg, cookie, "")
        self.assertGreater(self.record(session_id)["last_seen_at"], stale)

    def age(self, session_id: str, signed_in: timedelta, remaining: timedelta) -> None:
        """Backdate a session so the next request counts as use."""
        now = utc_now()
        self.store.update_value(db.BUCKET_SESSIONS, session_id, lambda record: record.update(
            created_at=to_iso(now - signed_in),
            expires_at=to_iso(now + remaining),
            last_seen_at=to_iso(now - timedelta(hours=1)),
        ))

    def sealed(self, credential: str) -> str:
        return f"{self.cfg.cookie_name}={encryption.xchacha_encrypt_string(self.cfg.secret_key, credential)}"

    def session_cookies(self, response) -> list[str]:
        name = self.cfg.cookie_name + "="
        return [value for value in response.headers.get_list("set-cookie") if value.startswith(name)]

    def test_use_extends_the_record_and_the_cookie(self) -> None:
        self.set_config(session_ttl_seconds=3600, session_max_age_seconds=86400)
        credential, session_id = self.credential()
        self.age(session_id, timedelta(hours=2), timedelta(minutes=10))

        client = TestClient(self.app, raise_server_exceptions=False)
        response = client.get("/api/me", headers={"Cookie": self.sealed(credential)})
        cookies = self.session_cookies(response)
        self.assertEqual(len(cookies), 1, "the record moved but the browser would still drop the cookie")
        self.assertIn("httponly", cookies[0].lower())
        max_age = int(cookies[0].lower().partition("max-age=")[2].partition(";")[0])
        self.assertTrue(3500 <= max_age <= 3600, max_age)
        ends = sessions.Session.from_record(self.record(session_id)).expires_at
        self.assertGreater(ends, utc_now() + timedelta(minutes=59))

        again = client.get("/api/me", headers={"Cookie": self.sealed(credential)})
        self.assertEqual(self.session_cookies(again), [], "sent again inside the interval")

    def test_a_session_stops_extending_at_its_limit(self) -> None:
        self.set_config(session_ttl_seconds=3600, session_max_age_seconds=86400)
        credential, session_id = self.credential()
        self.age(session_id, timedelta(hours=23, minutes=50), timedelta(minutes=5))
        client = TestClient(self.app, raise_server_exceptions=False)
        response = client.get("/api/me", headers={"Cookie": self.sealed(credential)})
        self.assertEqual(len(self.session_cookies(response)), 1)
        ends = sessions.Session.from_record(self.record(session_id)).expires_at
        self.assertLess(ends, utc_now() + timedelta(minutes=11), "ran past the limit")

        self.age(session_id, timedelta(hours=25), timedelta(minutes=5))
        response = client.get("/api/me", headers={"Cookie": self.sealed(credential)})
        self.assertEqual(self.session_cookies(response), [], "a session past its limit was extended")

    def test_a_live_stream_check_is_not_use(self) -> None:
        self.set_config(session_ttl_seconds=3600, session_max_age_seconds=86400)
        credential, session_id = self.credential()
        self.age(session_id, timedelta(hours=2), timedelta(minutes=10))
        before = self.record(session_id)["expires_at"]
        self.assertTrue(security.still_owner(self.store, credential))
        self.assertEqual(self.record(session_id)["expires_at"], before)

    def test_logging_out_on_a_request_that_extends_still_clears_the_cookie(self) -> None:
        self.set_config(session_ttl_seconds=3600, session_max_age_seconds=86400)
        credential, session_id = self.credential()
        cookie = self.sealed(credential)
        client = TestClient(self.app, raise_server_exceptions=False)
        csrf = client.get("/api/me", headers={"Cookie": cookie}).json()["csrf_token"]
        self.age(session_id, timedelta(hours=2), timedelta(minutes=10))
        response = client.post("/api/logout", json={"csrf_token": csrf}, headers={"Cookie": cookie})
        self.assertEqual(response.status_code, 200)
        cookies = self.session_cookies(response)
        self.assertEqual(len(cookies), 1, cookies)
        self.assertIn("max-age=0", cookies[0].lower())

    def test_a_failed_touch_does_not_fail_the_request(self) -> None:
        credential, _ = self.credential()
        cookie = {self.cfg.cookie_name: encryption.xchacha_encrypt_string(self.cfg.secret_key, credential)}
        with mock.patch.object(self.store, "update_value", side_effect=RuntimeError("locked")):
            self.assertIsNotNone(security.resolve_actor(self.store, self.cfg, cookie, ""))


class CaptureTest(RoutesTestCase):
    config_changes: dict = {}
    config_changes["passwords_enabled"] = True
    config_changes["two_factor_enabled"] = True

    def new_client(self) -> TestClient:
        return TestClient(self.app, base_url="https://testserver", headers={"user-agent": BROWSER})

    def assert_captured(self, client: TestClient) -> None:
        rows = client.get("/api/account/sessions").json()["sessions"]
        current = next(row for row in rows if row["current"])
        self.assertEqual(current["ip"], "testclient")
        self.assertEqual(len(current["user_agent"]), 256)
        self.assertTrue(current["user_agent"].startswith("Mozilla/5.0 (Test)"))
        self.assertIn("last_seen_at", current)

    def sign_in(self, user_id: int) -> TestClient:
        client = self.new_client()
        credential = login_tokens.issue_login_token(self.store, user_id, 600)
        self.assertEqual(client.post("/api/login", json={"credential": credential}).status_code, 200)
        return client

    def test_a_login_link(self) -> None:
        self.assert_captured(self.sign_in(self.user.id))

    def test_a_password(self) -> None:
        client = self.sign_in(self.user.id)
        token = client.get("/api/me").json()["csrf_token"]
        digest = encryption.sha256_hex("correct horse")[:43]
        self.assertEqual(
            client.post("/api/account/password", json={"username": "user", "password_digest": digest, "csrf_token": token}).status_code,
            200,
        )
        fresh = self.new_client()
        self.assertEqual(fresh.post("/api/login/password", json={"username": "user", "password_digest": digest}).status_code, 200)
        self.assert_captured(fresh)

    def test_two_factor(self) -> None:
        client = self.sign_in(self.user.id)
        token = client.get("/api/me").json()["csrf_token"]
        secret = client.post("/api/account/two-factor/start", json={"csrf_token": token}).json()["secret"]
        code = encryption.totp_code(secret, int(time.time()) // encryption.TOTP_PERIOD_SECONDS)
        self.assertEqual(client.post("/api/account/two-factor/confirm", json={"code": code, "csrf_token": token}).status_code, 200)

        fresh = self.new_client()
        credential = login_tokens.issue_login_token(self.store, self.user.id, 600)
        challenge = fresh.post("/api/login", json={"credential": credential}).json()["challenge"]
        # The session only exists once the code is given, so this is the step
        # that has to capture. The code that confirmed setup cannot be used
        # again; the next window's is accepted.
        next_code = encryption.totp_code(secret, int(time.time()) // encryption.TOTP_PERIOD_SECONDS + 1)
        response = fresh.post("/api/login/two-factor", json={"challenge": challenge, "code": next_code})
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_captured(fresh)

    def test_an_invite_link(self) -> None:
        link, _ = invite_links.issue_invite_link(self.store, "Group", 5, timedelta(days=1), self.owner.id)
        joined = self.new_client()
        response = joined.post("/api/join/create", json={"credential": link, "display_name": "Newcomer"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assert_captured(joined)

        returning = self.new_client()
        user_id = joined.get("/api/me").json()["id"]
        response = returning.post("/api/join/claim", json={"credential": link, "user_id": user_id})
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_captured(returning)

    def test_a_failure_to_note_it_does_not_fail_the_sign_in(self) -> None:
        with mock.patch.object(sessions, "remember_client", side_effect=RuntimeError("locked")):
            client = self.sign_in(self.user.id)
        self.assertEqual(client.get("/api/me").status_code, 200)


class ListTest(RoutesTestCase):
    def rows(self, cookie: str) -> list[dict]:
        status, reply = self.call("GET", "/api/account/sessions", cookie=cookie)
        self.assertEqual(status, 200)
        return reply["sessions"]

    def test_needs_a_session(self) -> None:
        self.assertEqual(self.call("GET", "/api/account/sessions")[0], 401)
        self.assertEqual(self.call("GET", "/api/account/sessions", key=self.admin_key)[0], 403)
        self.assertEqual(self.call("POST", "/api/account/sessions/revoke-others", key=self.admin_key, body={})[0], 403)
        self.assertEqual(self.call("POST", "/api/account/sessions/x/revoke", key=self.admin_key, body={})[0], 403)

    def test_shows_only_your_own_newest_first_and_marks_this_one(self) -> None:
        second = self.session(self.owner.id)
        rows = self.rows(second)
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["current"] for row in rows], [True, False])
        self.assertGreaterEqual(rows[0]["created_at"], rows[1]["created_at"])
        self.assertEqual(len(self.rows(self.user_cookie)), 1)

    def test_shows_nothing_secret(self) -> None:
        response = self.request("GET", "/api/account/sessions", cookie=self.owner_cookie)
        self.assertEqual(set(response.json()["sessions"][0]) - {"id", "current", "created_at", "expires_at", "last_seen_at", "ip", "user_agent"}, set())
        record = self.store.get(db.BUCKET_SESSIONS, response.json()["sessions"][0]["id"])
        self.assertNotIn("secret_hash", response.text)
        self.assertNotIn("csrf_token", response.text)
        self.assertNotIn(record["secret_hash"], response.text)
        self.assertNotIn(record["csrf_token"], response.text)

    def test_leaves_out_what_has_expired(self) -> None:
        session_id, _, session = sessions.new_session(self.owner.id, -10)
        self.store.put(db.BUCKET_SESSIONS, session_id, session.to_record())
        self.assertNotIn(session_id, [row["id"] for row in self.rows(self.owner_cookie)])


class RevokeTest(RoutesTestCase):
    def revoke(self, cookie: str, session_id: str, token: str | None = None) -> tuple[int, dict]:
        token = self.csrf(cookie) if token is None else token
        return self.call("POST", f"/api/account/sessions/{session_id}/revoke", cookie=cookie, body={"csrf_token": token})

    def current_id(self, cookie: str) -> str:
        rows = self.call("GET", "/api/account/sessions", cookie=cookie)[1]["sessions"]
        return next(row["id"] for row in rows if row["current"])

    def test_ends_the_other_device(self) -> None:
        other = self.session(self.owner.id)
        target = self.current_id(other)
        self.assertEqual(self.revoke(self.owner_cookie, target), (200, {"ok": True}))
        self.assertEqual(self.call("GET", "/api/me", cookie=other)[0], 401)
        self.assertEqual(self.call("GET", "/api/me", cookie=self.owner_cookie)[0], 200)

    def test_needs_the_csrf_token(self) -> None:
        other = self.session(self.owner.id)
        self.assertEqual(self.revoke(self.owner_cookie, self.current_id(other), token="wrong")[0], 403)
        self.assertEqual(self.call("GET", "/api/me", cookie=other)[0], 200)

    def test_a_foreign_id_and_an_unknown_id_look_the_same(self) -> None:
        foreign = self.revoke(self.owner_cookie, self.current_id(self.user_cookie))
        unknown = self.revoke(self.owner_cookie, "no-such-session")
        self.assertEqual(foreign, (404, {"error": "not found"}))
        self.assertEqual(unknown, foreign)
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[0], 200)

    def test_refuses_the_session_in_use(self) -> None:
        current = self.current_id(self.owner_cookie)
        self.assertEqual(self.revoke(self.owner_cookie, current), (400, {"error": "use sign out for this device"}))
        self.assertEqual(self.call("GET", "/api/me", cookie=self.owner_cookie)[0], 200)

    def test_revoke_others_keeps_this_one_and_counts(self) -> None:
        others = [self.session(self.owner.id), self.session(self.owner.id)]
        session_id, _, expired = sessions.new_session(self.owner.id, -10)
        self.store.put(db.BUCKET_SESSIONS, session_id, expired.to_record())
        token = self.csrf(self.owner_cookie)
        path = "/api/account/sessions/revoke-others"
        self.assertEqual(self.call("POST", path, cookie=self.owner_cookie, body={})[0], 403)
        status, body = self.call("POST", path, cookie=self.owner_cookie, body={"csrf_token": token})
        self.assertEqual((status, body), (200, {"ok": True, "removed": 2}))
        for cookie in others:
            self.assertEqual(self.call("GET", "/api/me", cookie=cookie)[0], 401)
        self.assertEqual(self.call("GET", "/api/me", cookie=self.owner_cookie)[0], 200)
        self.assertEqual(self.call("GET", "/api/me", cookie=self.user_cookie)[0], 200)

    def test_both_are_audited(self) -> None:
        other = self.session(self.owner.id)
        target = self.current_id(other)
        token = self.csrf(self.owner_cookie)
        with TestClient(self.app) as client:
            self.call("POST", f"/api/account/sessions/{target}/revoke", cookie=self.owner_cookie, body={"csrf_token": token}, client=client)
            self.call("POST", "/api/account/sessions/revoke-others", cookie=self.owner_cookie, body={"csrf_token": token}, client=client)
        logger = self.app.state.logs
        entries, _ = logger.read_day(logger.today(), logs.Query("kind:auth"))
        messages = [entry.get("msg") for entry in entries]
        self.assertIn("session_revoked", messages)
        self.assertEqual(next(entry for entry in entries if entry.get("msg") == "sessions_revoked")["detail"], {"removed": 0})


class LabelTest(RoutesTestCase):
    def post(self, cookie: str, session_id: str, **body: object) -> tuple[int, dict]:
        path = f"/api/account/sessions/{session_id}/label"
        return self.call("POST", path, cookie=cookie, body={**body, "csrf_token": self.csrf(cookie)})

    def rows(self, cookie: str) -> list[dict]:
        return self.call("GET", "/api/account/sessions", cookie=cookie)[1]["sessions"]

    def current(self, cookie: str) -> str:
        return next(row["id"] for row in self.rows(cookie) if row["current"])

    def test_naming_a_device(self) -> None:
        other = self.session(self.user.id)
        session_id = self.current(self.user_cookie)
        status, reply = self.post(self.user_cookie, session_id, label="  Work laptop  ")
        self.assertEqual((status, reply["label"]), (200, "Work laptop"))
        self.assertEqual(self.post(self.user_cookie, session_id, label="a" * 81)[0], 400)
        self.assertEqual(self.post(self.user_cookie, session_id, label=7)[0], 400)

        # An undo that finds a different name leaves it alone, and says what is there.
        status, reply = self.post(self.user_cookie, session_id, label="", expect="stale")
        self.assertEqual((status, reply["label"]), (409, "Work laptop"))

        # Another device of yours sees it, and it lasts through a touch, which
        # rewrites the record.
        for session in sessions.list_sessions(self.store, self.user.id):
            session.last_seen_at = None
            sessions.touch_session(self.store, session, 3600, 86400)
        self.assertIn("Work laptop", [row.get("label") for row in self.rows(other)])

        # Nothing clears it, and the row goes back to having none.
        self.assertEqual(self.post(self.user_cookie, session_id, label="  ", expect="Work laptop")[0], 200)
        self.assertTrue(all("label" not in row for row in self.rows(self.user_cookie)))

    def test_only_you_name_your_devices(self) -> None:
        session_id = self.current(self.user_cookie)

        # Someone else's looks the same as one that does not exist.
        self.assertEqual(self.post(self.owner_cookie, session_id, label="x")[0], 404)
        self.assertEqual(self.post(self.user_cookie, "nope", label="x")[0], 404)

        # An admin looking at the account sees the name.
        self.assertEqual(self.post(self.user_cookie, session_id, label="Phone")[0], 200)
        status, page = self.call("GET", f"/api/admin/users/{self.user.id}/sessions", cookie=self.owner_cookie)
        self.assertEqual((status, page["sessions"][0]["label"]), (200, "Phone"))

    def test_a_key_cannot_name_a_device(self) -> None:
        session_id = self.current(self.user_cookie)
        status, _ = self.call("POST", f"/api/account/sessions/{session_id}/label", key=self.user_key, body={"label": "x"})
        self.assertEqual(status, 403)


class CredentialsStillEndSessionsTest(RoutesTestCase):
    def test_disabling_an_account_empties_its_list(self) -> None:
        credentials.set_user_disabled(self.store, self.user.id, True)
        self.assertEqual(sessions.list_sessions(self.store, self.user.id), [])


if __name__ == "__main__":
    unittest.main()


class AdminSessionTest(RoutesTestCase):
    def route(self, user_id: int) -> str:
        return f"/api/admin/users/{user_id}/sessions"

    def post(self, path: str, cookie: str, csrf: bool = True) -> int:
        body = {"csrf_token": self.csrf(cookie)} if csrf else {}
        return self.call("POST", path, cookie=cookie, body=body)[0]

    def test_an_admin_ends_one_of_someones_devices(self) -> None:
        second = self.session(self.user.id)
        status, page = self.call("GET", self.route(self.user.id), cookie=self.owner_cookie)
        self.assertEqual((status, page["total"]), (200, 2))
        self.assertNotIn("secret_hash", str(page))
        self.assertNotIn("csrf", str(page))

        chosen = page["sessions"][0]["id"]
        self.assertEqual(self.post(f"{self.route(self.user.id)}/{chosen}/revoke", self.owner_cookie), 200)
        alive = [self.call("GET", "/api/me", cookie=cookie)[0] == 200 for cookie in (self.user_cookie, second)]
        self.assertEqual(sorted(alive), [False, True])

    def test_only_the_owner_reaches_the_owners_sessions_and_addresses(self) -> None:
        self.assertEqual(self.call("GET", self.route(self.owner.id), cookie=self.admin_cookie)[0], 403)
        sessions.remember_client(self.store, self.only_session(self.user.id), "10.0.0.1", "curl")
        _, page = self.call("GET", self.route(self.user.id), cookie=self.admin_cookie)
        self.assertNotIn("ip", page["sessions"][0])
        _, page = self.call("GET", self.route(self.user.id), cookie=self.owner_cookie)
        self.assertEqual(page["sessions"][0]["ip"], "10.0.0.1")

    def only_session(self, user_id: int) -> str:
        found = sessions.list_sessions(self.store, user_id)
        self.assertEqual(len(found), 1)
        return found[0].id

    def test_the_routes_refuse(self) -> None:
        path = self.route(self.user.id)
        self.assertEqual(self.call("GET", path, cookie=self.user_cookie)[0], 403)
        self.assertEqual(self.call("GET", path, key=self.admin_key)[0], 403)
        self.assertEqual(self.call("GET", self.route(9999), cookie=self.owner_cookie)[0], 404)
        self.assertEqual(self.post(f"{path}/nothing/revoke", self.owner_cookie), 404)
        theirs = self.only_session(self.user.id)
        self.assertEqual(self.post(f"{path}/{theirs}/revoke", self.owner_cookie, csrf=False), 403)
        mine = self.only_session(self.owner.id)
        self.assertEqual(self.post(f"{self.route(self.owner.id)}/{mine}/revoke", self.owner_cookie), 400)


class UserSearchTest(RoutesTestCase):
    def test_searching_keeps_paging_honest(self) -> None:
        for name in ("Zed One", "zed two", "Zed Three"):
            users.create_user(self.store, name, users.ROLE_USER)
        _, page = self.call("GET", "/api/admin/users?q=ZED&limit=2", cookie=self.owner_cookie)
        self.assertEqual((len(page["users"]), page["total"], page["next"]), (2, 3, 2))
        _, page = self.call("GET", "/api/admin/users?q=nobody", cookie=self.owner_cookie)
        self.assertEqual(page["total"], 0)


class MeFieldsTest(RoutesTestCase):
    config_changes = {"announcement": "Down at noon"}

    def test_me_says_the_version_and_the_announcement(self) -> None:
        _, me = self.call("GET", "/api/me", cookie=self.user_cookie)
        self.assertEqual((me["version"], me["announcement"]), ("dev", "Down at noon"))
