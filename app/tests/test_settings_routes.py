"""The Settings screen's routes (app/routes/settings.py), wired the way
main.build_app wires them, over a real config.yaml and secret.key in a
temporary folder."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

# Starlette's TestClient drives the app through httpx, which the app itself
# does not need, so it is not in requirements.txt. Without it these tests
# skip rather than fail: pip install httpx2 to run them.
try:
    from starlette.testclient import TestClient
except (ImportError, RuntimeError) as missing:  # Starlette raises RuntimeError
    raise unittest.SkipTest(f"needs httpx2 (pip install httpx2): {missing}")

from app.core import assets, db, encryption, language
from app.core import config_live
from app.core.static_files import StaticServer
from app.main import build_app
from app.models import login_tokens, users
from app.models import api_keys
from app.models.sign_in import SignInRules
from app.tests.support import new_holder


class SettingsRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.holder, self.path = new_holder(self, app_dir=str(Path(directory.name) / "data"))
        cfg = self.holder.boot()
        cfg.app_dir.mkdir(parents=True, exist_ok=True)
        (cfg.app_dir / "logs").mkdir(exist_ok=True)
        store = db.open_store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
        owner = users.create_user(store, "Owner", users.ROLE_ADMIN)
        users.ensure_owner(store)
        other = users.create_user(store, "Other admin", users.ROLE_ADMIN)
        self.key, _ = api_keys.issue_api_key(store, owner.id, "admin", users.ROLE_ADMIN, 3600)

        bundle = assets.resolve(cfg.static_dir, cfg.language_file)
        app = build_app(self.holder, store, language.parse(bundle.language_yaml), StaticServer(bundle.static_dir))
        self.client = TestClient(app)
        self.owner = self.session(store, cfg, owner.id)
        self.other = self.session(store, cfg, other.id)
        self.csrf = self.call("GET", "/api/me", cookie=self.owner)[1]["csrf_token"]

    @staticmethod
    def session(store: db.Store, cfg, user_id: int) -> str:
        login = login_tokens.issue_login_token(store, user_id, 3600)
        credential = login_tokens.redeem_login_token(store, login, SignInRules(3600)).session_credential
        return f"{cfg.cookie_name}={encryption.xchacha_encrypt_string(cfg.secret_key, credential)}"

    def call(self, method: str, path: str, cookie: str = "", key: str = "", body: dict | None = None) -> tuple[int, dict]:
        headers = {"content-type": "application/json"}
        if cookie:
            headers["cookie"] = cookie
        if key:
            headers["authorization"] = "Bearer " + key
        response = self.client.request(method, path, headers=headers, content=json.dumps(body) if body is not None else None)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}

    def test_settings_are_the_owners_alone(self) -> None:
        self.assertEqual(self.call("GET", "/api/owner/settings", cookie=self.other)[0], 404)
        self.assertEqual(self.call("GET", "/api/owner/settings", key=self.key)[0], 404)
        status, snapshot = self.call("GET", "/api/owner/settings", cookie=self.owner)
        self.assertEqual(status, 200)
        self.assertNotIn(self.holder.get().secret_key, json.dumps(snapshot))

    def test_save_settings(self) -> None:
        version = self.call("GET", "/api/owner/settings", cookie=self.owner)[1]["version"]
        changes = {"server.rate_limit_max": 7}
        status, _ = self.call("POST", "/api/owner/settings", cookie=self.owner, body={"version": version, "changes": changes})
        self.assertEqual(status, 403)

        body = {"csrf_token": self.csrf, "version": version, "changes": changes}
        status, reply = self.call("POST", "/api/owner/settings", cookie=self.owner, body=body)
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.holder.get().rate_limit_max, 7)

        # The same version again is now out of date.
        status, reply = self.call("POST", "/api/owner/settings", cookie=self.owner, body=body)
        self.assertEqual(status, 409)
        self.assertEqual(reply["error"], "settings_changed")
        self.assertNotEqual(reply["version"], version)

        body = {"csrf_token": self.csrf, "version": reply["version"], "changes": {"server.port": 0}}
        status, reply = self.call("POST", "/api/owner/settings", cookie=self.owner, body=body)
        self.assertEqual(status, 400)
        self.assertEqual(reply["error"], "invalid_settings")
        self.assertTrue(reply["problems"][0].startswith("server.port"))

    def test_mcp_follows_the_setting(self) -> None:
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        self.assertNotEqual(self.call("POST", "/mcp", key=self.key, body=ping)[0], 404)
        self.holder.save(config_live.version(config_live.read_raw(self.path)), {"server.mcp": False})
        self.assertEqual(self.call("POST", "/mcp", key=self.key, body=ping)[0], 404)


if __name__ == "__main__":
    unittest.main()
