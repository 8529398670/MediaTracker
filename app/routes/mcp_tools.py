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

from typing import Any

from app.mcp.registry import Call, Refusal, Registry, Tool
from app.models import invite_links
from app.routes.account import me_row
from app.routes.admin import RuleRefusal, revoke_access_checked, set_disabled_checked, user_rows
from app.routes.invite_links import invite_link_rows
from app.routes import mcp_tools_library
from app.routes.team import team_rows

USER_ID_SCHEMA = {"type": "integer", "minimum": 1, "description": "The account's id, from list_team or admin_list_users."}


def _schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _no_args(call: Call) -> None:
    call.bind({})


def whoami(call: Call) -> dict[str, Any]:
    _no_args(call)
    return me_row(call.store, call.config, call.actor)


def list_team(call: Call) -> dict[str, Any]:
    _no_args(call)
    return {"members": team_rows(call.store)}


def admin_list_users(call: Call) -> dict[str, Any]:
    _no_args(call)
    return {"users": user_rows(call.store)}


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


def admin_list_invite_links(call: Call) -> dict[str, Any]:
    _no_args(call)
    return {"invite_links": invite_link_rows(call.store)}


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
        description="Everyone with an active account: id and display name. Use the id wherever another tool asks for a user.",
        call=list_team,
        read_only=True,
    ))
    registry.register(Tool(
        name="admin_list_users",
        title="List users (admin)",
        description="Every account, including disabled ones, with its role and which one is the owner.",
        call=admin_list_users,
        read_only=True,
        admin_only=True,
    ))
    registry.register(Tool(
        name="admin_set_user_disabled",
        title="Disable or enable a user (admin)",
        description="Switch an account off (disabled: true) or back on (false). Disabling signs it out everywhere and voids its unused login links; its API keys stop working while it is off. Reversible. The owner and your own account cannot be disabled.",
        call=admin_set_user_disabled,
        input_schema=_schema({"user_id": USER_ID_SCHEMA, "disabled": {"type": "boolean"}}),
        admin_only=True,
    ))
    registry.register(Tool(
        name="admin_revoke_access",
        title="Revoke a user's access (admin)",
        description="For an account that may be compromised: ends every session and voids every unused login link and API key it holds, at once. The account stays enabled; someone with a browser session must issue a new login link to let its owner back in. The owner and your own account cannot be revoked.",
        call=admin_revoke_access,
        input_schema=_schema({"user_id": USER_ID_SCHEMA}),
        destructive=True,
        admin_only=True,
    ))
    registry.register(Tool(
        name="admin_list_invite_links",
        title="List invite links (admin)",
        description="Every group invite link: label, places used and left, expiry, and whether it still works. The links themselves are never shown again after creation.",
        call=admin_list_invite_links,
        read_only=True,
        admin_only=True,
    ))
    registry.register(Tool(
        name="admin_revoke_invite_link",
        title="Switch off an invite link (admin)",
        description="Stop an invite link from letting anyone else join or sign in through it. Accounts it already made keep working. Cannot be switched back on.",
        call=admin_revoke_invite_link,
        input_schema=_schema({"link_id": {"type": "string", "description": "The id from admin_list_invite_links."}}),
        destructive=True,
        admin_only=True,
    ))
    mcp_tools_library.register(registry)
    return registry
