"""What a tool is, how it reads its arguments, and how it says no.

Adding one is the MCP version of adding a route: write it next to the others
in app/routes/mcp_tools.py, calling the same helper the matching HTTP handler
calls, so a rule enforced there holds whichever door a change comes through.
The defaults match the rest of the template:

- Any signed-in key, unless the user asked for admin. admin_only hides the
  tool from user-scoped keys entirely.
- Never create a credential or delete anything. /mcp only accepts API keys,
  and those routes need a browser session (see RequireSession) so that
  revoking a leaked key really ends it, and so that a key can never erase what
  cannot be put back. A tool is a key-authenticated route; the same rule
  applies.
- Mark the hints honestly. read_only and destructive become the spec's
  readOnlyHint / destructiveHint, which a client uses to decide whether to ask
  the person before calling. They are advice to the client, not protection --
  the protection is the role check and the model rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

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
    """Arguments that do not match the tool's schema. It becomes a JSON-RPC
    invalid-params error rather than a tool result: the call never ran."""


@dataclass
class Call:
    """What a tool gets: who is calling at which effective role, the store and
    config (tools run in a worker thread, so they get these rather than the
    request), and the raw arguments."""

    actor: Actor
    store: Store
    config: Config
    request: Request
    args: dict[str, Any] = field(default_factory=dict)

    def bind(self, spec: dict[str, type], optional: dict[str, type] | None = None) -> dict[str, Any]:
        """The arguments, checked strictly against {name: type}: every name in
        spec required, the names in optional allowed, nothing else -- the same
        rule config.yaml follows, so a misspelt argument is reported rather
        than silently ignored."""
        allowed = {**spec, **(optional or {})}
        unknown = sorted(set(self.args) - set(allowed))
        if unknown:
            raise InvalidArguments(f"invalid arguments: unknown field {unknown[0]!r}")
        bound: dict[str, Any] = {}
        for name, kind in allowed.items():
            if name not in self.args:
                if name in spec:
                    raise InvalidArguments(f"invalid arguments: {name} is required")
                continue
            value = self.args[name]
            # bool is a subclass of int; true is not a user id.
            if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
                raise InvalidArguments(f"invalid arguments: {name} must be {kind.__name__}")
            bound[name] = value
        return bound


@dataclass
class Tool:
    """One thing an agent can do through /mcp. call is synchronous -- it runs
    in a worker thread, so it may use the store directly -- and returns a
    dict, which becomes both the text content and structuredContent."""

    name: str
    title: str
    description: str
    call: Callable[[Call], dict[str, Any]]
    # The JSON Schema of the arguments object. None means it takes none.
    input_schema: dict[str, Any] | None = None
    read_only: bool = False
    destructive: bool = False
    admin_only: bool = False
    # Asked on every call: a tool for a feature that is switched off answers
    # exactly like one that does not exist. None is always.
    enabled: Callable[[Config], bool] | None = None

    def visible_to(self, actor: Actor | None, cfg: Config) -> bool:
        if self.enabled is not None and not self.enabled(cfg):
            return False
        return not self.admin_only or (actor is not None and actor.is_admin)

    def listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema or {"type": "object", "properties": {}, "additionalProperties": False},
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

    def visible(self, actor: Actor | None, cfg: Config) -> list[Tool]:
        """tools/list for one actor: the tools its effective role may call, in
        registration order, so a user-scoped key is never even told the admin
        tools exist."""
        return [tool for tool in self._tools.values() if tool.visible_to(actor, cfg)]

    def get(self, name: str, actor: Actor | None, cfg: Config) -> Tool | None:
        tool = self._tools.get(name)
        return tool if tool is not None and tool.visible_to(actor, cfg) else None
