"""The MCP side of accounts and sign-in: login links, accounts, devices and
invite links. Each tool stands for its HTTP route and runs the route's own
handler (mcp= in its @route(...)), so the rules (who may touch the owner, what a
narrowed key may not do) hold whichever door a request comes through.

A login link or invite link made here records the key that asked, and revoking
or deleting that key voids it while it can still be used (see
login_tokens.void_links_minted_by_key). That is what keeps revoking a leaked
key meaningful now that a key can hand out ways in.

These are the calls of the tools that add to their route's answer. The Go
template's mcp_tools_accounts.go has the same, and both write the same
config/mcp.json.
"""
from __future__ import annotations

from typing import Any, Callable

import msgspec

from app.core.config import Config
from app.mcp.registry import Call


def base_url(call: Call) -> str:
    """The address this agent reached /mcp at."""
    return str(call.request.base_url).rstrip("/")


def with_full_url(call: Call, reply: Any, path_field: str, url_field: str) -> dict[str, Any]:
    """The route's reply with url_field added beside path_field, the full
    address, from the address this agent reached /mcp at."""
    row = msgspec.to_builtins(reply)
    return {**row, url_field: base_url(call) + row[path_field]}


def with_login_url(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of a tool for a route that mints a login link: the route's
    reply with login_url added. The HTTP routes answer with login_path only
    (see admin.create_user for why)."""
    return with_full_url(call, serve(call.request, body), "login_path", "login_url")


def two_factor_on(cfg: Config) -> bool:
    return cfg.two_factor_enabled


def invite_links_on(cfg: Config) -> bool:
    return cfg.invite_links_enabled


def with_join_url(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """with_login_url for an invite link: join_url beside join_path."""
    return with_full_url(call, serve(call.request, body), "join_path", "join_url")


