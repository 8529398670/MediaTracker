"""One activity-log entry per request: who (LoadActor has run by the time
this does -- it sits inside it in main.build_app), from where, what was
asked, how it ended and how long it took. A 5xx is logged as kind "error"
with the exception's text, which never reaches the client (see
middleware.server_error) but is what the owner needs.

It sits inside RateLimit, so a flood of refused requests costs a 429 and
nothing else. Skipped: the log's own endpoints (reading the log would fill
it; page events arrive as kind "ui" entries of their own), /api/health and
/api/ready (a probe every few seconds is noise), /metrics (so is a scrape), and,
unless logs.static_assets is on, the page's scripts, styles and images.

The settings are read on every request, not once at startup:
logs.static_assets, logs.echo and the proxy settings can change while the
server runs (see config_live.Holder).
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import logs
from app.core.config import Config
from app.core.config_live import Holder
from app.core.middleware import client_ip, static_asset, trusted_for
from app.core.security import log_actor


class RequestLog:
    def __init__(self, app: ASGIApp, settings: Holder, logger: logs.Logger) -> None:
        self.app = app
        self.settings = settings
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.logger.enabled:
            await self.app(scope, receive, send)
            return
        cfg = self.settings.get()
        if self._skip(scope, cfg):
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status = 500
        bytes_out = 0

        async def send_and_measure(message: Message) -> None:
            nonlocal status, bytes_out
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                bytes_out += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, send_and_measure)
        except Exception as error:
            # Logged on its way to server_error, which answers the client. A
            # response already under way keeps its status: the body limit ends
            # a 413 by raising through here, and that is not a crash.
            self._record(scope, cfg, started, status, bytes_out, repr(error) if status >= 500 else "")
            raise
        # A handler that answered 500 itself left its reason here (see
        # middleware.internal_error).
        self._record(scope, cfg, started, status, bytes_out, (scope.get("state") or {}).get("error_cause", ""))

    def _skip(self, scope: Scope, cfg: Config) -> bool:
        path = scope.get("path", "")
        if path in ("/api/logs/events", "/api/health", "/api/ready", "/metrics") or path.startswith("/api/owner/logs"):
            return True
        return not cfg.logs.static_assets and static_asset(scope.get("method", ""), path)

    def _record(self, scope: Scope, cfg: Config, started: float, status: int, bytes_out: int, message: str) -> None:
        headers = Headers(scope=scope)
        state = scope.get("state") or {}
        record = logs.entry(
            logs.KIND_REQUEST,
            logs.LEVEL_INFO,
            request_id=state.get("request_id"),
            actor=log_actor(state.get("actor")),
            ip=client_ip(scope, cfg, trusted_for(cfg)),
            ua=logs.truncate(headers.get("user-agent", ""), 300),
            request={
                "method": scope.get("method", ""),
                "path": logs.redact(scope.get("path", ""), scope.get("query_string", b"").decode("latin-1")),
                "status": status,
                "ms": round((time.perf_counter() - started) * 1000, 2),
                "bytes_out": bytes_out,
                **({"referer": referer} if (referer := _redact_referer(headers.get("referer", ""))) else {}),
            },
            msg=logs.truncate(message, 500),
        )
        if status >= 500:
            record["kind"] = logs.KIND_ERROR
            record["level"] = logs.LEVEL_ERROR
        elif status >= 400:
            record["level"] = logs.LEVEL_WARN
        self.logger.log(record)
        if cfg.logs.echo:
            request = record["request"]
            name = record["actor"].get("name") or "-"
            print(f"[req] {request['method']} {request['path']} {status} {request['ms']:.1f}ms {record.get('ip', '')} {name}", flush=True)


def _redact_referer(value: str) -> str:
    """Where a visitor came from, without a login or invite link they came
    from."""
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    return logs.truncate(f"{parts.scheme}://{parts.netloc}{logs.redact(parts.path, parts.query)}", 300)
