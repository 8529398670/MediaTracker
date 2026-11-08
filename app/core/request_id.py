"""A reference for every request: 16 hex characters, made here and never taken
from the caller, who could otherwise pick what a log search finds. It comes
back in the X-Request-ID header, on the request's log lines, and in a 5xx
body, so "it said ref 3f9a..." finds the line that says why.

Its own middleware, outermost in main.build_app, because RequestLog is skipped
for much of what matters here: with logs off, and on the paths it never logs.
"""
from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import encryption

HEADER = "x-request-id"
LENGTH = 16


def of(scope: Scope) -> str:
    """This request's reference; empty outside RequestID."""
    return (scope.get("state") or {}).get("request_id", "")


class RequestID:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        reference = encryption.random_hex(LENGTH)
        scope.setdefault("state", {})["request_id"] = reference

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER] = reference
            await send(message)

        await self.app(scope, receive, send_with_id)
