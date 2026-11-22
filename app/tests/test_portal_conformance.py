"""The portal contract, route by route (portal contract v3, item 7). Keep this
file as it is in every app: an app-specific change that breaks what
ProjectPortal relies on -- an owner-only guard on an account route, a refusal
without its code -- fails the app's own tests here.

ProjectPortal works through an admin account of its own, never the owner's.
The table is run four ways: with the portal's key on an ordinary account, with
an ordinary user's key, with a viewer key, and on the owner and on another
admin, where the ladder must hold."""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import uvicorn

from app.core.error_codes import CODE_NOT_ADMIN, CODE_OWNER_PROTECTED, CODE_OWNER_REQUIRED, CODE_VIEW_ONLY
from app.core.db import BUCKET_API_KEYS
from app.models import api_keys, to_iso, users, utc_now
from app.tests.route_support import RoutesTestCase


@dataclass
class ContractCall:
    """One call ProjectPortal makes. In path, {user} is the account it acts
    on and {key} a key on that account. ladder: the call acts on one account,
    so only the owner may make it on another admin, and nobody on the owner."""

    method: str
    path: str
    body: dict[str, Any] | None
    status: int
    ladder: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def contract_calls() -> list[ContractCall]:
    soon = to_iso(utc_now() + timedelta(hours=1))
    return [
        ContractCall("GET", "/api/admin/users?limit=1", None, 200),
        ContractCall("POST", "/api/admin/users", {"display_name": "Cy", "role": "user", "max_uses": 1, "expires_in_minutes": 15}, 201),
        ContractCall("POST", "/api/admin/users/{user}/reissue-login", {"max_uses": 1, "expires_in_minutes": 15}, 200, True),
        ContractCall("POST", "/api/admin/users/{user}/role", {"role": "viewer"}, 200, True),
        ContractCall("POST", "/api/admin/users/{user}/expiry", {"expires_at": soon}, 200, True),
        ContractCall("POST", "/api/admin/users/{user}/disabled", {"disabled": True}, 200, True),
        ContractCall("POST", "/api/admin/users/{user}/disabled", {"disabled": False}, 200, True),
        ContractCall("GET", "/api/admin/users/{user}/keys", None, 200, True),
        ContractCall("POST", "/api/admin/users/{user}/keys", {"name": "for the portal", "role": "user", "expires_in_days": 30}, 201, True),
        ContractCall("POST", "/api/admin/keys/{key}/revoke", {}, 200, True),
        ContractCall("POST", "/api/admin/users/{user}/revoke-access", {}, 200, True),
        ContractCall("POST", "/api/admin/users/{user}/delete", {}, 200, True),
    ]


class PortalConformance(RoutesTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.set_config(api_keys_enabled=True)
        self.portal_user, self.portal = self.portal_account()

    def portal_account(self) -> tuple[users.User, str]:
        """The account ProjectPortal works through -- an admin that is not the
        owner -- and its admin key, which may make keys. It is what Connect on
        the owner's API keys screen makes (the portal-account upgrade), built
        here by hand so this file stands on its own in any app."""
        user = users.create_user(self.store, "ProjectPortal", users.ROLE_ADMIN)
        credential, key = api_keys.issue_api_key(self.store, user.id, "portal", users.ROLE_ADMIN, 30 * 24 * 3600)
        with self.store.transaction() as tx:
            record = tx.get(BUCKET_API_KEYS, key.id)
            record["may_mint_keys"] = True
            tx.put(BUCKET_API_KEYS, key.id, record)
        return user, credential

    def target(self, user: users.User) -> dict[str, str]:
        """An account to act on, with one key of its own."""
        _, key = api_keys.issue_api_key(self.store, user.id, "its own", user.role, 3600)
        return {"{user}": str(user.id), "{key}": key.id}

    @staticmethod
    def contract_path(call: ContractCall, target: dict[str, str]) -> str:
        path = call.path
        for name, value in target.items():
            path = path.replace(name, value)
        return path

    def test_the_portal_runs_an_ordinary_account(self) -> None:
        target = self.target(users.create_user(self.store, "Cyd", users.ROLE_USER))
        for call in contract_calls():
            path = self.contract_path(call, target)
            status, reply = self.call(call.method, path, key=self.portal, body=call.body)
            self.assertEqual(status, call.status, f"{call.method} {path}: {reply}")

    def test_an_ordinary_key_is_no_portal(self) -> None:
        credential, _ = api_keys.issue_api_key(self.store, self.user.id, "script", users.ROLE_USER, 3600)
        target = self.target(self.user)
        for call in contract_calls():
            path = self.contract_path(call, target)
            status, reply = self.call(call.method, path, key=credential, body=call.body)
            self.assertEqual((status, reply.get("code")), (403, CODE_NOT_ADMIN), f"{call.method} {path}: {reply}")

    def test_a_viewer_key_changes_nothing(self) -> None:
        credential, _ = api_keys.issue_api_key(self.store, self.portal_user.id, "reader", users.ROLE_VIEWER, 3600)
        target = self.target(self.user)
        for call in contract_calls():
            path = self.contract_path(call, target)
            want = CODE_NOT_ADMIN if call.method == "GET" else CODE_VIEW_ONLY
            status, reply = self.call(call.method, path, key=credential, body=call.body)
            self.assertEqual((status, reply.get("code")), (403, want), f"{call.method} {path}: {reply}")

    def test_the_portal_leaves_the_owner_and_other_admins_alone(self) -> None:
        peer = users.create_user(self.store, "Pia", users.ROLE_ADMIN)
        for user, code in ((self.owner, CODE_OWNER_PROTECTED), (peer, CODE_OWNER_REQUIRED)):
            target = self.target(user)
            for call in contract_calls():
                if not call.ladder:
                    continue
                path = self.contract_path(call, target)
                status, reply = self.call(call.method, path, key=self.portal, body=call.body)
                self.assertEqual((status, reply.get("code")), (403, code), f"{call.method} {path} on {user.display_name}: {reply}")


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "contract_check.sh"


@unittest.skipIf(sys.platform == "win32" or shutil.which("curl") is None, "contract_check.sh needs a unix shell and curl")
class ContractCheck(PortalConformance):
    """scripts/contract_check.sh, run against this app: what an owner runs
    against a live one before pasting the key into the portal."""

    def setUp(self) -> None:
        super().setUp()
        users.create_user(self.store, "Cyd", users.ROLE_USER)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        self.base = "http://127.0.0.1:%d" % listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.app, lifespan="off", log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, server, "should_exit", True)
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)

    def check(self, key: str) -> tuple[str, bool]:
        result = subprocess.run(["bash", str(SCRIPT), self.base], input=key + "\n", capture_output=True, text=True, timeout=60)
        output = result.stdout + result.stderr
        self.assertNotIn(key, output, "the key was printed")
        return output, result.returncode == 0

    def test_the_portals_key_passes(self) -> None:
        output, ok = self.check(self.portal)
        self.assertTrue(ok and "FAIL" not in output and "PASS  keys:" in output, output)

    def test_a_user_key_and_a_bad_key_fail_with_their_codes(self) -> None:
        credential, _ = api_keys.issue_api_key(self.store, self.user.id, "script", users.ROLE_USER, 3600)
        output, ok = self.check(credential)
        self.assertFalse(ok)
        self.assertIn("FAIL  accounts: 403 (not_admin)", output)
        output, ok = self.check("nope.nope")
        self.assertFalse(ok)
        self.assertIn("FAIL  me: 401 (not_authenticated)", output)

    # The table's own tests run once, in PortalConformance.
    test_the_portal_runs_an_ordinary_account = None  # type: ignore[assignment]
    test_an_ordinary_key_is_no_portal = None  # type: ignore[assignment]
    test_a_viewer_key_changes_nothing = None  # type: ignore[assignment]
    test_the_portal_leaves_the_owner_and_other_admins_alone = None  # type: ignore[assignment]
