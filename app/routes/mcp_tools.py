"""The tools /mcp offers (see app/mcp for the protocol and the rules a tool
follows). Each one is a thin wrapper over the helper its HTTP route uses --
me_row, team_rows, set_disabled_checked, ... -- so the two doors answer the
same way and refuse for the same reasons.

What is deliberately missing: creating accounts, login links, invite links,
PINs or keys, and deleting anything. Those routes need a browser session, and
/mcp only takes API keys. See RequireSession for why.

An app's own tools go in a new module in this package (mcp_tools_<feature>.py)
with a register(registry) function called from build_registry below.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import Config
from app.core.db import Store
from app.mcp.registry import Call, Refusal, Registry, Tool
from app.models import invite_links
from app.routes.account import me_row
from app.routes.admin import RuleRefusal, revoke_access_checked, set_disabled_checked, user_rows
from app.routes.helpers import PAGE_DEFAULT, PAGE_LIMIT_MESSAGE, PAGE_MAX, PAGE_OFFSET_MESSAGE, page_body
from app.routes.invite_links import invite_link_rows
from app.routes import mcp_tools_library
from app.routes.team import team_rows

USER_ID_SCHEMA = {"type": "integer", "minimum": 1, "description": "The account's id, from list_team or admin_list_users."}


# Both optional, so a paged tool still works with no arguments.
PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "minimum": 1, "maximum": PAGE_MAX, "description": "Rows to return. Default 200."},
        "offset": {"type": "integer", "minimum": 0, "description": "Rows to skip: the next value of the previous page."},
    },
    "additionalProperties": False,
}


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _no_args(call: Call) -> None:
    call.bind({})


def _page(call: Call, name: str, load: Callable[[Store], list[Any]]) -> dict[str, Any]:
    """send_page for a tool, so the two doors page the same way."""
    args = call.bind({}, optional={"limit": int, "offset": int})
    limit, offset = args.get("limit", PAGE_DEFAULT), args.get("offset", 0)
    if not 1 <= limit <= PAGE_MAX:
        raise Refusal(PAGE_LIMIT_MESSAGE)
    if offset < 0:
        raise Refusal(PAGE_OFFSET_MESSAGE)
    return page_body(name, load(call.store), limit, offset)


def whoami(call: Call) -> dict[str, Any]:
    _no_args(call)
    return me_row(call.store, call.config, call.actor, call.request.app.state.version)


def list_team(call: Call) -> dict[str, Any]:
    return _page(call, "members", team_rows)


def admin_list_users(call: Call) -> dict[str, Any]:
    return _page(call, "users", user_rows)


def admin_set_user_disabled(call: Call) -> dict[str, Any]:
    args = call.bind({"user_id": int, "disabled": bool})
    refused = set_disabled_checked(call.store, call.actor.user.id, args["user_id"], args["disabled"])
    if refused is not None:
        raise Refusal(refused.message)
    return {"ok": True}


def admin_revoke_access(call: Call) -> dict[str, Any]:
    args = call.bind({"user_id": int})
    revoked = revoke_access_checked(call.store, call.actor.user.id, args["user_id"])
    if isinstance(revoked, RuleRefusal):
        raise Refusal(revoked.message)
    return {"ok": True, "revoked": revoked.to_dict()}


def _invite_links_on(cfg: Config) -> bool:
    return cfg.invite_links_enabled


def admin_list_invite_links(call: Call) -> dict[str, Any]:
    return _page(call, "invite_links", invite_link_rows)


def admin_revoke_invite_link(call: Call) -> dict[str, Any]:
    args = call.bind({"link_id": str})
    if not invite_links.revoke_invite_link(call.store, args["link_id"]):
        raise Refusal("no such invite link")
    return {"ok": True}


def build_registry() -> Registry:
    registry = Registry()
    registry.register(Tool(
        name="whoami",
        title="Who am I",
        description="The account this API key belongs to, the role it acts with (role -- never higher than the key's own scope), and the account's own role.",
        call=whoami,
        read_only=True,
    ))
    registry.register(Tool(
        name="list_team",
        title="List team",
        description="People with an active account, a page at a time: id and display name. Use the id wherever another tool asks for a user. next is the offset of the following page, or null on the last one.",
        call=list_team,
        input_schema=PAGE_SCHEMA,
        read_only=True,
    ))
    registry.register(Tool(
        name="admin_list_users",
        title="List users (admin)",
        description="Accounts, a page at a time, including disabled ones, with each one's role and which is the owner. next is the offset of the following page, or null on the last one.",
        call=admin_list_users,
        input_schema=PAGE_SCHEMA,
        read_only=True,
        admin_only=True,
    ))
    registry.register(Tool(
        name="admin_set_user_disabled",
        title="Disable or enable a user (admin)",
        description="Switch an account off (disabled: true) or back on (false). Disabling signs it out everywhere and voids its live login link; its API keys stop working while it is off. Reversible. The owner and your own account cannot be disabled.",
        call=admin_set_user_disabled,
        input_schema=_schema({"user_id": USER_ID_SCHEMA, "disabled": {"type": "boolean"}}),
        admin_only=True,
    ))
    registry.register(Tool(
        name="admin_revoke_access",
        title="Revoke a user's access (admin)",
        description="For an account that may be compromised: ends every session and voids its live login link and every API key it holds, at once. The account stays enabled; someone with a browser session must issue a new login link to let its owner back in. The owner and your own account cannot be revoked.",
        call=admin_revoke_access,
        input_schema=_schema({"user_id": USER_ID_SCHEMA}),
        destructive=True,
        admin_only=True,
    ))
    registry.register(Tool(
        name="admin_list_invite_links",
        title="List invite links (admin)",
        description="Group invite links, a page at a time: label, places used and left, expiry, and whether each still works. The links themselves are never shown again after creation. next is the offset of the following page, or null on the last one.",
        call=admin_list_invite_links,
        input_schema=PAGE_SCHEMA,
        read_only=True,
        admin_only=True,
        enabled=_invite_links_on,
    ))
    registry.register(Tool(
        name="admin_revoke_invite_link",
        title="Switch off an invite link (admin)",
        description="Stop an invite link from letting anyone else join or sign in through it. Accounts it already made keep working. Cannot be switched back on.",
        call=admin_revoke_invite_link,
        input_schema=_schema({"link_id": {"type": "string", "description": "The id from admin_list_invite_links."}}),
        destructive=True,
        admin_only=True,
        enabled=_invite_links_on,
    ))
    mcp_tools_library.register(registry)
    return registry
