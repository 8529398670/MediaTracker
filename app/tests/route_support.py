"""Shared by the tests that call real routes: main.build_app over a real
config.yaml and secret.key in a temporary folder, an owner, a second admin, an
admin key and a user key. Importing this skips the importing module without
httpx2, the same way test_settings_routes.py does.

TestClient waits for a response to end, so a stream needs asgi_request below
instead: the whole app, called directly."""
from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    from starlette.testclient import TestClient
except (ImportError, RuntimeError) as missing:  # Starlette raises RuntimeError
    raise unittest.SkipTest(f"needs httpx2 (pip install httpx2): {missing}")

from app import apidocs
from app.apidocs.check import check
from app.apidocs.generate import documented_routes
from app.core import assets, db, encryption, language
from app.core.static_files import StaticServer
from app.main import build_app
from app.models import login_tokens, users
from app.models import api_keys
from app.models.sign_in import SignInRules
from app.tests.support import new_holder


def spec_path(spec: dict[str, Any], method: str, path: str) -> str:
    """The spec's path for a request's: /api/users/7 is /api/users/{user_id}.
    A literal segment wins over a parameter."""
    candidates = []
    for template, item in spec.get("paths", {}).items():
        if method.lower() in item and re.fullmatch(re.sub(r"\\\{\w+\\\}", "[^/]+", re.escape(template)), path):
            candidates.append(template)
    return min(candidates, key=lambda template: template.count("{"), default="")


class RoutesTestCase(unittest.TestCase):
    # Changes to the running Config before the app is built.
    config_changes: dict[str, Any] = {}
    logs_enabled = True

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.holder, self.path = new_holder(self, app_dir=str(Path(directory.name) / "data"))
        self.set_config(rate_limit_max=100000, rate_limit_signin_max=100000, **self.config_changes)
        self.set_config(logs=replace(self.holder.get().logs, enabled=self.logs_enabled))
        cfg = self.holder.get()
        self.holder._boot = cfg
        self.cfg = cfg
        cfg.app_dir.mkdir(parents=True, exist_ok=True)
        (cfg.app_dir / "logs").mkdir(exist_ok=True)
        self.store = db.open_store(cfg.database_path, cfg.secret_key, cfg.encrypt_at_rest)
        self.owner = users.create_user(self.store, "Owner", users.ROLE_ADMIN)
        users.ensure_owner(self.store)
        self.admin = users.create_user(self.store, "Other admin", users.ROLE_ADMIN)
        self.user = users.create_user(self.store, "User", users.ROLE_USER)
        self.admin_key, _ = api_keys.issue_api_key(self.store, self.owner.id, "admin", users.ROLE_ADMIN, 3600)
        self.user_key, _ = api_keys.issue_api_key(self.store, self.owner.id, "user", users.ROLE_USER, 3600)

        bundle = assets.resolve(cfg.static_dir, cfg.language_file)
        self.app = build_app(self.holder, self.store, language.parse(bundle.language_yaml), StaticServer(bundle.static_dir))
        # A crash reaches the client as the 500 it is, rather than the test.
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.owner_cookie = self.session(self.owner.id)
        self.admin_cookie = self.session(self.admin.id)
        self.user_cookie = self.session(self.user.id)

    def set_config(self, **changes: Any) -> None:
        self.holder._current = replace(self.holder.get(), **changes)

    def session(self, user_id: int) -> str:
        login = login_tokens.issue_login_token(self.store, user_id, 3600)
        credential = login_tokens.redeem_login_token(self.store, login, SignInRules(3600)).session_credential
        return f"{self.cfg.cookie_name}={encryption.xchacha_encrypt_string(self.cfg.secret_key, credential)}"

    def csrf(self, cookie: str) -> str:
        return self.call("GET", "/api/me", cookie=cookie)[1]["csrf_token"]

    def request(self, method: str, path: str, cookie: str = "", key: str = "", body: dict | None = None, client: Any = None) -> Any:
        headers = {"content-type": "application/json"}
        if cookie:
            headers["cookie"] = cookie
        if key:
            headers["authorization"] = "Bearer " + key
        content = json.dumps(body) if body is not None else None
        response = (client or self.client).request(method, path, headers=headers, content=content)
        self.check_reply(method, path, response)
        return response

    def check_reply(self, method: str, path: str, response: Any) -> None:
        """Holds every success reply a test gets against the API docs, so docs
        that say something a handler does not do fail a test."""
        if not 200 <= response.status_code < 300 or not response.headers.get("content-type", "").startswith("application/json"):
            return
        if getattr(self, "_api_spec", None) is None:
            self._api_spec, _ = apidocs.build(documented_routes(self.app.routes))
        path = path.split("?", 1)[0]
        template = spec_path(self._api_spec, method, path)
        problems = check(self._api_spec, method, template, response.status_code, response.content)
        self.assertEqual(problems, [], f"{method} {template}")

    def call(self, method: str, path: str, cookie: str = "", key: str = "", body: dict | None = None, client: Any = None) -> tuple[int, Any]:
        response = self.request(method, path, cookie, key, body, client)
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, {}


class Exchange:
    """One raw ASGI request: what the app sent, and a way to hang up."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.received = asyncio.Condition()
        self.disconnected = asyncio.Event()

    @property
    def status(self) -> int:
        return self.messages[0]["status"]

    @property
    def headers(self) -> dict[str, str]:
        return {name.decode(): value.decode() for name, value in self.messages[0]["headers"]}

    @property
    def body(self) -> bytes:
        return b"".join(message.get("body", b"") for message in self.messages[1:])

    async def receive(self) -> dict:
        await self.disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(self, message: dict) -> None:
        async with self.received:
            self.messages.append(message)
            self.received.notify_all()

    async def wait_for(self, check: Callable[[], bool], timeout: float = 5.0) -> None:
        async def wait() -> None:
            async with self.received:
                await self.received.wait_for(check)

        await asyncio.wait_for(wait(), timeout)

    async def wait_for_body(self, wanted: bytes) -> None:
        await self.wait_for(lambda: wanted in self.body)


def asgi_request(
    app: Any, path: str, cookie: str = "", method: str = "GET", send: Callable[[dict], Awaitable[None]] | None = None
) -> tuple[Exchange, asyncio.Task[None]]:
    """Start a request against app, on this event loop. uvicorn's asgi
    spec_version is what makes Starlette's StreamingResponse watch for a
    disconnect, so it is uvicorn's here."""
    exchange = Exchange()
    headers = [(b"cookie", cookie.encode())] if cookie else []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    return exchange, asyncio.create_task(app(scope, exchange.receive, send or exchange.send))
