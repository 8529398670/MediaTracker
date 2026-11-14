"""What a tool is, how it reads its arguments, and how it says no.

Adding one is the MCP version of adding a route: mcp="tool_name" in the
@route(...) of the route it stands for (build_registry in
app/routes/mcp_tools.py makes it with Tool.for_route). It takes the route's
request type and runs the route's own handler, so a rule enforced there holds
whichever door a change comes through. The rules match the rest of the
template:

- One tool per route an API key may call. test_mcp_parity.py fails until
  every key-callable route in the API docs has a tool, or an mcp_http reason
  in its @route(...) for staying HTTP only (file bytes, for one: MCP messages
  are JSON, and clients cap their size, so uploads and downloads go over
  /api/files with the same key and the tool hands back the addresses).
- Any signed-in key, unless the route is admin only. admin_only hides the
  tool from user-scoped keys entirely.
- Nothing a key cannot do over HTTP. Managing users, keys and sign-in, and
  erasing anything for good, need a browser session (see RequireSession), so
  that revoking a leaked key really ends it and a key can never erase what
  cannot be put back. A tool is a key-authenticated route; the same rule keeps
  those out.
- Mark the hints honestly. read_only and destructive become the spec's
  readOnlyHint / destructiveHint, which a client uses to decide whether to ask
  the person before calling. They are advice to the client, not protection --
  the protection is the role check and the model rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import msgspec
from starlette.requests import Request

from app.core.config import Config
from app.core.db import Store
from app.core.security import Actor


class Refusal(Exception):
    """A tool saying no for a reason the caller should read -- "no such user",
    "the owner account cannot be disabled". It becomes a tool result with
    isError set, worded like the HTTP route's error, so the model sees why and
    can try something else. Any other exception is logged and reported only as
    "internal error"."""


class InvalidArguments(Exception):
    """Arguments that do not match the tool's schema: malformed, or a name
    the route does not take. It becomes a JSON-RPC invalid-params error rather
    than a tool result: the call never ran."""


@dataclass
class Call:
    """What a tool gets: who is calling at which effective role, the store and
    config (tools run in a worker thread), the request /mcp came in on, and
    the raw arguments, which Tool.for_route checks against the route's
    request type."""

    actor: Actor
    store: Store
    config: Config
    request: Request
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    """One thing an agent can do through /mcp, made with for_route. call is
    synchronous -- it runs in a worker thread, so it may use the store
    directly -- and returns a dict, which becomes both the text content and
    structuredContent."""

    name: str
    title: str
    description: str
    # The declared route this tool stands for: its arguments are the route's
    # request type, and mcp.json names its route.
    endpoint: Callable
    call: Callable[[Call], dict[str, Any]]
    read_only: bool = False
    destructive: bool = False
    admin_only: bool = False
    # Asked on every call: a tool for a feature that is switched off answers
    # exactly like one that does not exist. None is always.
    enabled: Callable[[Config], bool] | None = None

    @classmethod
    def for_route(cls, endpoint: Callable, call: Callable[..., Any] | None = None, **fields: Any) -> Tool:
        """The tool that stands for a declared route, as mcp= and the tool keys
        in its @route(...) declare it; build_registry (app/routes/mcp_tools.py)
        makes one for each.

        Its arguments are the route's request type, URL fields and all, so its
        input schema and the checks on what it is sent are the route's;
        nobody writes them for a tool. With no call it answers with the
        route's own handler and reply. A tool that adds to the reply (a full
        URL where the route answers a path) passes call(call, body, serve),
        given the checked request and serve(request, body), the route's
        handler."""
        from app.apidocs.route import declared_of, decode_arguments
        from app.routes.helpers import Refused

        declared = declared_of(endpoint)
        if declared is None:
            raise TypeError(f"{endpoint!r} is not a declared route")

        def answer(tool_call: Call, body: Any) -> Any:
            if call is None:
                return declared.serve(tool_call.request, body)
            return call(tool_call, body, declared.serve)

        def run(tool_call: Call) -> dict[str, Any]:
            body, message, malformed = decode_arguments(endpoint, tool_call.args)
            if message:
                raise InvalidArguments(f"invalid arguments: {message}") if malformed else Refusal(message)
            try:
                result = answer(tool_call, body)
            except Refused as refused:
                if refused.status == 500:
                    raise
                raise Refusal(refused.message) from None
            return msgspec.to_builtins(result) if isinstance(result, msgspec.Struct) else result

        return cls(call=run, endpoint=endpoint, **fields)

    def route_name(self) -> str:
        """The HTTP route the tool stands for, as "METHOD /path/{param}" the
        way config/openapi.json writes it."""
        from app.apidocs.route import route_of

        return route_of(self.endpoint)

    def arguments(self) -> dict[str, Any]:
        """The JSON Schema of the arguments object: the route's request."""
        from app.apidocs.route import input_schema

        return input_schema(self.endpoint)

    def visible_to(self, actor: Actor | None, cfg: Config) -> bool:
        if self.enabled is not None and not self.enabled(cfg):
            return False
        return not self.admin_only or (actor is not None and actor.is_admin)

    def listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.arguments(),
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                # Every tool here acts on this server's own records, never the
                # open internet.
                "openWorldHint": False,
            },
        }


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """A duplicate name is a programming error and fails at startup, where
        it is noticed, rather than one tool silently shadowing another."""
        if tool.name in self._tools:
            raise ValueError(f"mcp: tool {tool.name!r} registered twice")
        self._tools[tool.name] = tool

    def tools(self) -> list[Tool]:
        """Every registered tool, whoever may call it, in registration order:
        what config/mcp.json lists."""
        return list(self._tools.values())

    def visible(self, actor: Actor | None, cfg: Config) -> list[Tool]:
        """tools/list for one actor: the tools its effective role may call, in
        registration order, so a user-scoped key is never even told the admin
        tools exist."""
        return [tool for tool in self._tools.values() if tool.visible_to(actor, cfg)]

    def get(self, name: str, actor: Actor | None, cfg: Config) -> Tool | None:
        tool = self._tools.get(name)
        return tool if tool is not None and tool.visible_to(actor, cfg) else None
