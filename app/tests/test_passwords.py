"""Password sign-in and two-factor, through the real routes: the toggles, the
per-account block, every way of signing in being asked for a code, and the
answers that must not say which part was wrong."""
from __future__ import annotations

import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

try:
    from starlette.testclient import TestClient
except (ImportError, RuntimeError) as missing:  # Starlette raises RuntimeError
    raise unittest.SkipTest(f"needs httpx2 (pip install httpx2): {missing}")

from app.core import assets, db, encryption, language
from app.core.static_files import StaticServer
from app.main import build_app
from app.models import credentials, login_tokens, users
from app.models import invite_links
from app.models import passwords
from app.models import two_factor
from app.routes import join as join_routes
from app.routes import passwords as password_routes
from app.routes import two_factor as two_factor_routes
from app.models.attempts import AttemptGuard
from app.tests.support import new_holder

BASE_URL = "https://testserver"


def digest(text: str) -> str:
    """Stands in for what password.js derives: 43 base64url characters."""
    return encryption.sha256_hex(text)[:43]


def code_for(secret: str, step_offset: int = 0) -> str:
    step = int(time.time()) // encryption.TOTP_PERIOD_SECONDS + step_offset
    return encryption.totp_code(secret, step)


class AuthRoutesTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.holder, _ = new_holder(self, app_dir=str(Path(directory.name) / "data"))
        self.cfg = self.holder.boot()
        self.cfg.app_dir.mkdir(parents=True, exist_ok=True)
        (self.cfg.app_dir / "logs").mkdir(exist_ok=True)
        self.set_config(rate_limit_max=100000, rate_limit_signin_max=100000)
        self.set_config(passwords_enabled=True)
        self.set_config(two_factor_enabled=True)
        # encrypt_at_rest off, so a test can see what a record really holds.
        self.store = db.open_store(self.cfg.database_path, self.cfg.secret_key, False)
        bundle = assets.resolve(self.cfg.static_dir, self.cfg.language_file)
        app = build_app(self.holder, self.store, language.parse(bundle.language_yaml), StaticServer(bundle.static_dir))
        self.owner = users.create_user(self.store, "Owner", users.ROLE_ADMIN)
        self.alice = users.create_user(self.store, "Alice", users.ROLE_USER)
        self.app = app
        self.client = self.new_client()
        # Guards are per process, so each test starts with clean counts.
        password_routes.NAMES = AttemptGuard()
        password_routes.ADDRESSES = AttemptGuard(max_failures=30)
        two_factor_routes.CODES = AttemptGuard()
        password_routes.CODES = two_factor_routes.CODES
        join_routes.PINS = AttemptGuard()

    def set_config(self, **changes: object) -> None:
        self.holder._current = replace(self.holder.get(), **changes)

    def new_client(self) -> TestClient:
        return TestClient(self.app, base_url=BASE_URL)

    def sign_in_with_link(self, user_id: int, client: TestClient | None = None) -> TestClient:
        client = client or self.new_client()
        credential = login_tokens.issue_login_token(self.store, user_id, 600)
        response = client.post("/api/login", json={"credential": credential})
        self.assertEqual(response.status_code, 200)
        return client

    def csrf(self, client: TestClient) -> str:
        return client.get("/api/me").json()["csrf_token"]

    def set_password(self, client: TestClient, username: str, text: str, code: str = "") -> object:
        return client.post("/api/account/password", json={
            "username": username, "password_digest": digest(text), "code": code, "csrf_token": self.csrf(client),
        })

    def enrol(self, client: TestClient) -> tuple[str, list[str]]:
        token = self.csrf(client)
        secret = client.post("/api/account/two-factor/start", json={"csrf_token": token}).json()["secret"]
        response = client.post("/api/account/two-factor/confirm", json={"code": code_for(secret), "csrf_token": token})
        self.assertEqual(response.status_code, 200)
        return secret, response.json()["recovery_codes"]

    def login(self, client: TestClient, username: str, text: str) -> object:
        return client.post("/api/login/password", json={"username": username, "password_digest": digest(text)})


class PasswordTest(AuthRoutesTestCase):
    def test_set_then_sign_in(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        self.assertEqual(self.set_password(alice, "Alice", "correct horse").status_code, 200)
        stored = users.get_user(self.store, self.alice.id)
        self.assertEqual(stored.username, "alice")
        self.assertTrue(stored.password_hash.startswith("$2"))

        fresh = self.new_client()
        self.assertEqual(self.login(fresh, "ALICE", "correct horse").status_code, 200)
        self.assertEqual(fresh.get("/api/me").json()["id"], self.alice.id)

    def test_every_failure_answers_the_same(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        self.set_password(alice, "alice", "correct horse")
        owner = self.sign_in_with_link(self.owner.id)
        self.set_password(owner, "owner", "correct horse")
        passwords.set_blocked(self.store, self.owner.id, True)
        users_with_disabled = users.create_user(self.store, "Dee", users.ROLE_USER)
        dee = self.sign_in_with_link(users_with_disabled.id)
        self.set_password(dee, "dee", "correct horse")
        credentials.set_user_disabled(self.store, users_with_disabled.id, True)

        answers = {
            "wrong": self.login(self.new_client(), "alice", "wrong"),
            "unknown": self.login(self.new_client(), "nobody", "correct horse"),
            "blocked": self.login(self.new_client(), "owner", "correct horse"),
            "disabled": self.login(self.new_client(), "dee", "correct horse"),
        }
        for name, response in answers.items():
            self.assertEqual((response.status_code, response.json()), (400, {"error": "invalid_login"}), name)

    def test_a_raw_password_is_refused(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        response = alice.post("/api/account/password", json={
            "username": "alice", "password_digest": "hunter2", "csrf_token": self.csrf(alice),
        })
        self.assertEqual(response.json(), {"error": "bad_digest"})

    def test_lockout_treats_unknown_names_alike(self) -> None:
        for name in ("alice", "nobody"):
            for _ in range(5):
                self.login(self.new_client(), name, "wrong")
            self.assertEqual(self.login(self.new_client(), name, "wrong").json(), {"error": "login_locked"})

    def test_usernames_are_unique(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        owner = self.sign_in_with_link(self.owner.id)
        self.set_password(alice, "same", "correct horse")
        self.assertEqual(self.set_password(owner, "Same", "correct horse").json(), {"error": "username_taken"})

    def test_changing_it_ends_other_sessions_only(self) -> None:
        first = self.sign_in_with_link(self.alice.id)
        second = self.sign_in_with_link(self.alice.id)
        self.set_password(first, "alice", "correct horse")
        self.assertEqual(first.get("/api/me").status_code, 200)
        self.assertEqual(second.get("/api/me").status_code, 401)

    def test_the_toggle_closes_and_restores(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        self.set_password(alice, "alice", "correct horse")

        self.set_config(passwords_enabled=False)
        self.assertEqual(self.login(self.new_client(), "alice", "correct horse").status_code, 404)
        self.assertEqual(self.set_password(alice, "alice", "another one").status_code, 404)
        self.assertEqual(self.client.get("/api/login/options").json(), {"passwords": False, "two_factor": True})

        self.set_config(passwords_enabled=True)
        self.assertEqual(self.login(self.new_client(), "alice", "correct horse").status_code, 200)
        self.assertNotEqual(self.client.get("/api/login/options").json().get("salt", ""), "")

    def test_the_owner_blocks_one_account(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        owner = self.sign_in_with_link(self.owner.id)
        self.set_password(alice, "alice", "correct horse")

        path = f"/api/owner/users/{self.alice.id}/password-access"
        self.assertEqual(alice.post(path, json={"allowed": False, "csrf_token": self.csrf(alice)}).status_code, 404)
        self.assertEqual(owner.post(path, json={"allowed": False, "csrf_token": self.csrf(owner)}).status_code, 200)

        self.assertEqual(self.login(self.new_client(), "alice", "correct horse").status_code, 400)
        self.assertEqual(self.set_password(alice, "alice", "another one").json(), {"error": "password_blocked"})
        self.assertEqual(alice.get("/api/me").status_code, 200, "a block is not a sign-out")

        owner.post(path, json={"allowed": True, "csrf_token": self.csrf(owner)})
        self.assertEqual(self.login(self.new_client(), "alice", "correct horse").status_code, 200)

    def test_revoking_access_removes_the_password(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        self.set_password(alice, "alice", "correct horse")
        revoked = credentials.revoke_all_credentials(self.store, self.alice.id)
        self.assertEqual(revoked.passwords, 1)
        self.assertEqual(self.login(self.new_client(), "alice", "correct horse").status_code, 400)

    def test_an_api_key_cannot_set_one(self) -> None:
        from app.models import api_keys

        credential, _ = api_keys.issue_api_key(self.store, self.alice.id, "bot", users.ROLE_USER, 3600)
        response = self.new_client().post(
            "/api/account/password",
            headers={"Authorization": f"Bearer {credential}"},
            json={"username": "alice", "password_digest": digest("x")},
        )
        self.assertEqual(response.status_code, 403)


class InviteClaimTest(AuthRoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.credential, _ = invite_links.issue_invite_link_as(self.store, self.owner.id, "Club", 10, 1)
        joined = self.new_client()
        response = joined.post("/api/join/create", json={"credential": self.credential, "display_name": "Bob"})
        self.assertEqual(response.status_code, 201)
        self.bob_client = joined
        self.bob_id = joined.get("/api/me").json()["id"]

    def claim(self, pin: str = "") -> object:
        return self.new_client().post("/api/join/claim", json={"credential": self.credential, "user_id": self.bob_id, "pin": pin})

    def test_a_password_closes_the_claim(self) -> None:
        self.assertEqual(self.claim().status_code, 200)
        self.set_password(self.bob_client, "bob", "correct horse")
        self.assertEqual(self.claim().json(), {"error": "use_password"})

    def test_a_pin_keeps_the_claim_open(self) -> None:
        self.set_password(self.bob_client, "bob", "correct horse")
        self.bob_client.post("/api/account/pin", json={"pin": "1234", "csrf_token": self.csrf(self.bob_client)})
        self.assertEqual(self.claim("1234").status_code, 200)

    def test_two_factor_still_applies_to_a_claim(self) -> None:
        secret, _ = self.enrol(self.bob_client)
        fresh = self.new_client()
        response = fresh.post("/api/join/claim", json={"credential": self.credential, "user_id": self.bob_id, "pin": ""})
        self.assertTrue(response.json()["two_factor"])
        self.assertEqual(fresh.get("/api/me").status_code, 401)
        finished = fresh.post("/api/login/two-factor", json={"challenge": response.json()["challenge"], "code": code_for(secret, 1)})
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(fresh.get("/api/me").json()["id"], self.bob_id)


class TwoFactorTest(AuthRoutesTestCase):
    def test_rfc_6238_vector(self) -> None:
        # Appendix B of the RFC, seed "12345678901234567890", t = 59. The RFC
        # shows eight digits, 94287082; six is the same value's tail.
        self.assertEqual(encryption.totp_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59 // 30), "287082")

    def test_the_secret_is_encrypted_on_its_own(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        secret, _ = self.enrol(alice)
        # This store has encrypt_at_rest off, so the record is plain JSON.
        record = self.store.get(db.BUCKET_USERS, self.alice.id)
        self.assertNotIn(secret, str(record))
        self.assertEqual(encryption.xchacha_decrypt_string(self.cfg.secret_key, record["totp_secret"]), secret)

    def test_a_login_link_asks_for_the_code(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        secret, _ = self.enrol(alice)
        fresh = self.new_client()
        credential = login_tokens.issue_login_token(self.store, self.alice.id, 600)
        response = fresh.post("/api/login", json={"credential": credential}).json()
        self.assertTrue(response["two_factor"])
        self.assertEqual(fresh.get("/api/me").status_code, 401)

        wrong = fresh.post("/api/login/two-factor", json={"challenge": response["challenge"], "code": "000000"})
        self.assertEqual(wrong.json(), {"error": "two_factor_wrong"})
        right = fresh.post("/api/login/two-factor", json={"challenge": response["challenge"], "code": code_for(secret, 1)})
        self.assertEqual(right.status_code, 200)
        self.assertEqual(fresh.get("/api/me").json()["id"], self.alice.id)

    def test_a_password_asks_for_the_code(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        self.set_password(alice, "alice", "correct horse")
        secret, _ = self.enrol(alice)
        fresh = self.new_client()
        response = self.login(fresh, "alice", "correct horse").json()
        self.assertTrue(response["two_factor"])
        self.assertEqual(fresh.get("/api/me").status_code, 401)
        fresh.post("/api/login/two-factor", json={"challenge": response["challenge"], "code": code_for(secret, 1)})
        self.assertEqual(fresh.get("/api/me").status_code, 200)

    def test_a_code_works_once(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        secret, _ = self.enrol(alice)
        code = code_for(secret, 1)
        for expected in (200, 403):
            challenge = login_tokens.redeem_login_token(
                self.store, login_tokens.issue_login_token(self.store, self.alice.id, 600),
                login_rules(self.cfg),
            ).challenge
            response = self.new_client().post("/api/login/two-factor", json={"challenge": challenge, "code": code})
            self.assertEqual(response.status_code, expected)

    def test_a_challenge_works_once(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        _, recovery = self.enrol(alice)
        challenge = self.new_challenge()
        self.assertEqual(self.finish(challenge, recovery[0]).status_code, 200)
        self.assertEqual(self.finish(challenge, recovery[1]).json(), {"error": "challenge_invalid"})

    def new_challenge(self) -> str:
        return login_tokens.redeem_login_token(
            self.store, login_tokens.issue_login_token(self.store, self.alice.id, 600), login_rules(self.cfg)
        ).challenge

    def finish(self, challenge: str, code: str) -> object:
        return self.new_client().post("/api/login/two-factor", json={"challenge": challenge, "code": code})

    def test_a_recovery_code_works_once(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        _, recovery = self.enrol(alice)
        self.assertEqual(len(recovery), two_factor.RECOVERY_CODE_COUNT)
        self.assertEqual(self.finish(self.new_challenge(), recovery[0].lower()).status_code, 200)
        self.assertEqual(self.finish(self.new_challenge(), recovery[0]).status_code, 403)

    def test_wrong_codes_lock(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        secret, _ = self.enrol(alice)
        challenge = self.new_challenge()
        for _ in range(5):
            self.finish(challenge, "000000")
        self.assertEqual(self.finish(challenge, code_for(secret, 1)).json(), {"error": "two_factor_locked"})

    def test_turning_it_off_needs_a_code(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        secret, _ = self.enrol(alice)
        token = self.csrf(alice)
        refused = alice.post("/api/account/two-factor/disable", json={"code": "", "csrf_token": token})
        self.assertEqual(refused.status_code, 403)
        done = alice.post("/api/account/two-factor/disable", json={"code": code_for(secret, 1), "csrf_token": token})
        self.assertEqual(done.status_code, 200)
        self.sign_in_with_link(self.alice.id)

    def test_changing_a_password_needs_a_code(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        secret, _ = self.enrol(alice)
        self.assertEqual(self.set_password(alice, "alice", "correct horse").json(), {"error": "two_factor_wrong"})
        self.assertEqual(self.set_password(alice, "alice", "correct horse", code_for(secret, 1)).status_code, 200)

    def test_the_toggle_stops_asking_and_restores(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        self.enrol(alice)
        self.set_config(two_factor_enabled=False)
        self.sign_in_with_link(self.alice.id)
        token = self.csrf(alice)
        self.assertEqual(alice.post("/api/account/two-factor/start", json={"csrf_token": token}).status_code, 404)
        self.set_config(two_factor_enabled=True)
        credential = login_tokens.issue_login_token(self.store, self.alice.id, 600)
        self.assertTrue(self.new_client().post("/api/login", json={"credential": credential}).json()["two_factor"])

    def test_disabling_the_account_ends_a_sign_in_in_progress(self) -> None:
        alice = self.sign_in_with_link(self.alice.id)
        secret, _ = self.enrol(alice)
        challenge = self.new_challenge()
        credentials.set_user_disabled(self.store, self.alice.id, True)
        self.assertEqual(self.finish(challenge, code_for(secret, 1)).json(), {"error": "challenge_invalid"})

    def test_reset_rules(self) -> None:
        second_admin = users.create_user(self.store, "Second", users.ROLE_ADMIN)
        admin_client = self.sign_in_with_link(second_admin.id)
        owner_client = self.sign_in_with_link(self.owner.id)
        alice = self.sign_in_with_link(self.alice.id)
        self.enrol(alice)
        self.enrol(owner_client)
        self.enrol(admin_client)

        def reset(client: TestClient, user_id: int) -> int:
            path = f"/api/admin/users/{user_id}/reset-two-factor"
            return client.post(path, json={"csrf_token": self.csrf(client)}).status_code

        self.assertEqual(reset(admin_client, self.owner.id), 403)
        self.assertEqual(reset(admin_client, second_admin.id), 400)
        self.assertEqual(reset(owner_client, self.owner.id), 400)
        self.assertEqual(reset(admin_client, self.alice.id), 200)
        self.assertEqual(reset(owner_client, second_admin.id), 200)
        self.assertFalse(two_factor.is_on(users.get_user(self.store, self.alice.id)))
        # The CLI may do what the web may not.
        self.assertTrue(credentials.reset_two_factor(self.store, self.owner.id, None))
        self.assertFalse(two_factor.is_on(users.get_user(self.store, self.owner.id)))


def login_rules(cfg: object) -> object:
    from app.routes.auth import sign_in_rules

    return sign_in_rules(cfg)
