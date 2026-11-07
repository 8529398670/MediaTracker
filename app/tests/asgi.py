"""A tiny ASGI client for route tests: the template ships no HTTP client
library, and a request through the real app -- middleware, guards, route
groups -- is what a permission test has to exercise."""
from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.core import config, db, language
from app.core.config import Config, ImagesSection, JobsSection, LibrarySection, ProvidersSection
from app.core.static_files import StaticServer
from app.main import build_app
from app.models import types

CODE_ROOT = Path(__file__).resolve().parent.parent.parent


def test_config(directory: Path) -> Config:
    return Config(
        project_name="Test",
        project_dir=directory,
        url="http://127.0.0.1:1",
        url_source="test",
        config_file=directory / "config.yaml",
        config_created=False,
        config_warning="",
        app_dir=directory,
        database_path=directory / "app.db",
        storage_dir=directory / "storage",
        static_dir=str(CODE_ROOT / "static"),
        language_file="",
        host="127.0.0.1",
        port=1,
        secure_cookies=False,
        cookie_name="test_session",
        session_ttl_seconds=3600,
        login_token_ttl_seconds=600,
        api_keys_enabled=True,
        api_key_ttl_seconds=3600,
        secret_key="0" * 64,
        rate_limit_max=10_000,
        providers=ProvidersSection(False, "", "", "test", 5, 1000),
        images=ImagesSection(16, 10_000, ["image.tmdb.org"]),
        library=LibrarySection(30, 1000),
        jobs=JobsSection(24, 720, 24, False),
    )


class Client:
    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.cfg = test_config(root)
        self.store = db.open_store(self.cfg.database_path, self.cfg.secret_key, False)
        types.ensure_builtin(self.store)
        lang = language.parse((CODE_ROOT / "config" / "language.yaml").read_bytes())
        self.app = build_app(self.cfg, self.store, lang, StaticServer(CODE_ROOT / "static"))

    def close(self) -> None:
        self.directory.cleanup()

    def request(self, method: str, path: str, key: str = "", body: Any = None) -> tuple[int, Any]:
        return asyncio.run(self._request(method, path, key, body))

    async def _request(self, method: str, path: str, key: str, body: Any) -> tuple[int, Any]:
        raw = b"" if body is None else json.dumps(body).encode()
        route, _, query = path.partition("?")
        headers = [(b"host", b"127.0.0.1"), (b"content-type", b"application/json")]
        if key:
            headers.append((b"authorization", f"Bearer {key}".encode()))
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
            "scheme": "http", "path": route, "raw_path": route.encode(), "query_string": query.encode(),
            "headers": headers, "client": ("127.0.0.1", 5000), "server": ("127.0.0.1", 1), "root_path": "",
            "app": self.app,
        }
        sent = False
        chunks: list[bytes] = []
        status = 0

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": raw, "more_body": False}
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await self.app(scope, receive, send)
        data = b"".join(chunks)
        try:
            return status, json.loads(data) if data else None
        except ValueError:
            return status, data
