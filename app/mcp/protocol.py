"""JSON-RPC for POST /mcp.

It speaks the Streamable HTTP transport in its simplest legal form: stateless,
one JSON-RPC message per POST, a plain JSON reply. No SSE stream, no
Mcp-Session-Id, no server-initiated messages. A tool call here is an ordinary
request -- authenticate, check, act, answer -- so there is no per-client state
to hold, expire, or leak between keys, and nothing about it needs a second
process or a sticky load balancer.

Written by hand rather than with the `mcp` SDK because the subset is small
(four methods) and the template's rule is no dependency it does not need: the
SDK would bring pydantic, httpx, an SSE library, and transport code for the
half of the spec this server deliberately does not use.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.security import Actor, actor_from
from app.mcp.registry import Call, InvalidArguments, Refusal, Registry

# The protocol revisions this server can answer, newest first. Everything used
# here (tools, JSON responses, annotations) means the same in each of them.
SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

# JSON-RPC error codes. Only these leave the server; anything else that goes
# wrong inside a tool is a tool result with isError set, which is what the
# spec asks for so the model can read the failure and react.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(id_: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}, status_code=status)


def _tool_result(value: dict[str, Any], is_error: bool) -> dict[str, Any]:
    """Both ways the spec offers: JSON text, which every client can show a
    model, and structuredContent, which newer clients read directly. Tools
    return dicts so the second is always valid -- it must be an object."""
    return {
        "content": [{"type": "text", "text": json.dumps(value, separators=(",", ":"), default=str)}],
        "structuredContent": value,
        "isError": is_error,
    }


class Server:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    async def endpoint(self, request: Request) -> Response:
        """POST /mcp. app/routes/__init__.py puts RequireAPIKey in front of
        it, so an actor is always present and always came in through a key."""
        # The spec asks servers to check Origin against DNS rebinding. With a
        # bearer key required that attack has nothing to ride on -- a rebound
        # page carries no key -- but a browser page has no business here
        # either, so a cross-origin one is refused rather than reasoned about.
        origin = request.headers.get("origin")
        if origin is not None and urlsplit(origin).netloc != request.headers.get("host", ""):
            return JSONResponse({"error": "cross-origin requests are not accepted"}, status_code=403)
        # After initialize, a client names the revision it settled on in this
        # header on every request. One we never offered means the two sides
        # disagree about the protocol, which is better said than guessed past.
        version = request.headers.get("mcp-protocol-version")
        if version is not None and version not in SUPPORTED_VERSIONS:
            return JSONResponse({"error": "unsupported MCP-Protocol-Version"}, status_code=400)

        try:
            message = json.loads(await request.body())
        except ValueError:
            return _error(None, PARSE_ERROR, "parse error", 400)
        # JSON-RPC batches were removed from MCP in 2025-06-18; refusing them
        # keeps one message per request, which is what makes the rate limiter
        # and the logs mean something.
        if isinstance(message, list):
            return _error(None, INVALID_REQUEST, "batch requests are not supported", 400)
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return _error(message.get("id") if isinstance(message, dict) else None, INVALID_REQUEST, "invalid request", 400)
        # A notification (no id) gets no answer, only an acknowledgement. The
        # ones a client sends -- initialized, cancelled -- need nothing from a
        # stateless server, so they are all accepted and dropped.
        if "id" not in message:
            return Response(status_code=202)
        id_ = message["id"]
        if id_ is None or isinstance(id_, bool) or not isinstance(id_, (str, int)):
            return _error(None, INVALID_REQUEST, "id must be a string or a number", 400)

        params = message.get("params") or {}
        try:
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            result = await self._dispatch(request, actor_from(request), message["method"], params)
        except RpcError as error:
            return _error(id_, error.code, error.message)
        return JSONResponse({"jsonrpc": "2.0", "id": id_, "result": result})

    async def method_not_allowed(self, request: Request) -> Response:
        """GET and DELETE on /mcp. GET is how a client asks for a
        server-to-client SSE stream and DELETE how it ends a session; this
        server has neither, and 405 is the reply the spec gives for that."""
        return Response(status_code=405, headers={"Allow": "POST"})

    async def _dispatch(self, request: Request, actor: Actor, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(request, params)
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [tool.listing() for tool in self.registry.visible(actor)]}
        if method == "tools/call":
            return await self._call(request, actor, params)
        raise RpcError(METHOD_NOT_FOUND, f"method not found: {method}")

    def _initialize(self, request: Request, params: dict[str, Any]) -> dict[str, Any]:
        """The client's revision if we know it, otherwise our newest, and the
        client decides whether it can live with that."""
        asked = params.get("protocolVersion")
        cfg = request.app.state.config
        return {
            "protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0],
            # listChanged False: the tool list is fixed at startup. It differs
            # between keys (admin tools are hidden from a user-scoped key),
            # but never changes under one.
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": cfg.project_name, "version": getattr(request.app.state, "version", "dev")},
        }

    async def _call(self, request: Request, actor: Actor, params: dict[str, Any]) -> dict[str, Any]:
        name, args = params.get("name"), params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            raise RpcError(INVALID_PARAMS, "tools/call needs a tool name")
        if not isinstance(args, dict):
            raise RpcError(INVALID_PARAMS, "arguments must be an object")
        # An admin tool asked for by a user-scoped key answers exactly like a
        # tool that does not exist: it was never listed to that key, and
        # saying "forbidden" would only confirm the name.
        tool = self.registry.get(name, actor)
        if tool is None:
            raise RpcError(INVALID_PARAMS, f"unknown tool: {name}")

        state = request.app.state
        call = Call(actor=actor, store=state.store, config=state.config, request=request, args=args)
        try:
            # Tools are synchronous and touch SQLite -- the threadpool rule.
            value = await run_in_threadpool(tool.call, call)
        except InvalidArguments as error:
            raise RpcError(INVALID_PARAMS, str(error)) from None
        except Refusal as refusal:
            return _tool_result({"error": str(refusal)}, True)
        except Exception as error:  # noqa: BLE001 -- the detail goes to the log, never to the caller
            print(f"[mcp] tool {name}: {error!r}", flush=True)
            return _tool_result({"error": "internal error"}, True)
        return _tool_result(value, False)
