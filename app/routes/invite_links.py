"""Managing invite links (see app/models/invite_links.py; joining through one
is app/routes/join.py). Admin only. The link's credential is returned once,
on creation, as a path -- the browser adds its own origin, like a login
link."""
from __future__ import annotations

from datetime import timedelta
from typing import Annotated, ClassVar, Literal

import msgspec
from msgspec import UNSET, Meta, UnsetType
from starlette.requests import Request

from app.apidocs import ADMIN, PATH, QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from
from app.models import RestoreError, invite_links, users
from app.models.invite_links import INVITE_LINK_MAX_DAYS, INVITE_LINK_MAX_USES, InviteLink
from app.models.users import User
from app.routes.admin import DateTime, OkReply
from app.routes.helpers import Dir, Page, Paged, Refused, get_store, match_rows, restore_refusal, sorted_page
from app.routes.logs import audit
from app.routes.mcp_tools_accounts import invite_links_on, with_join_url


class InviteLinkRow(Reply, kw_only=True):
    """An invite link as the admin list shows it. The link itself is never
    shown again after creation."""

    api_name: ClassVar[str] = "InviteLink"
    id: str
    label: str
    max_uses: int
    used: int
    remaining: int
    live: bool
    expires_at: DateTime
    revoked: bool
    created_by: int
    created_by_name: str | UnsetType = UNSET


def _row(link: InviteLink, creator: User | None) -> InviteLinkRow:
    live = link.live
    # A link outlives its maker's admin rights only on paper: it stops
    # working the moment they lose them (see load_invite_link).
    if creator is None or creator.disabled or not creator.is_admin:
        live = False
    row = InviteLinkRow(
        id=link.id,
        label=link.label,
        max_uses=link.max_uses,
        used=len(link.accounts),
        remaining=link.remaining,
        live=live,
        expires_at=link.expires_at.isoformat(),
        revoked=link.revoked_at is not None,
        created_by=link.created_by,
    )
    if creator is not None:
        row.created_by_name = creator.display_name
    return row


class ListInviteLinks(Page):
    q: Annotated[str, QUERY, Meta(description="Keep links whose label or maker contains this, in any case.")] = ""
    sort: Annotated[Literal["label", "used", "expires_at"], QUERY, Meta(description="Field to sort the whole list by. Rows without it go last.")] = ""  # type: ignore[assignment]
    dir: Dir = ""  # type: ignore[assignment]


class ListInviteLinksReply(Paged):
    invite_links: list[InviteLinkRow]


@route(
    "GET /api/admin/invite-links", summary="List invite links",
    tag="Invite links", role=ADMIN, feature="invite_links",
    description="Group invite links, a page at a time: label, places used and left, expiry, and whether "
    "each still works. The links themselves are never shown again after creation. next is the offset of the "
    "following page, or null on the last one.",
    mcp="admin_list_invite_links", read_only=True, enabled=invite_links_on,
)
def list_invite_links(request: Request, body: ListInviteLinks) -> ListInviteLinksReply:
    """Over HTTP and as the MCP admin_list_invite_links tool."""
    store = get_store(request)
    creators = {user.id: user for user in users.list_users(store)}
    rows = [_row(link, creators.get(link.created_by)) for link in invite_links.list_invite_links(store)]
    page = sorted_page(match_rows(rows, body.q, "label", "created_by_name"), body.sort, body.dir, body)
    return ListInviteLinksReply(invite_links=page.pop("rows"), **page)


INVITE_LINK_LIMITS = "label must be 1-80 characters, uses 1-1000, days 1-365"


class CreateInviteLink(RequestType):
    label: Annotated[str, Meta(min_length=1, max_length=80, extra={"error": INVITE_LINK_LIMITS})]
    max_uses: Annotated[int, Meta(ge=1, le=INVITE_LINK_MAX_USES, extra={"error": INVITE_LINK_LIMITS})]
    days: Annotated[int, Meta(ge=1, le=INVITE_LINK_MAX_DAYS, extra={"error": INVITE_LINK_LIMITS})]


class NewInviteLink(InviteLinkRow, kw_only=True):
    api_name: ClassVar[str] = ""
    join_path: Annotated[str, Meta(description="The link to hand out, shown in this response only. A credential: treat it like a password.")]


@route(
    "POST /api/admin/invite-links", summary="Create an invite link",
    tag="Invite links", role=ADMIN, feature="invite_links", status=201,
    description="One link for a group: each person who opens it joins as a new user, up to max_uses people, "
    "for days days.",
    mcp_note="Answers with join_url (shown only now) and the link's details. Revoking or deleting this API "
    "key switches the link off.",
    mcp="admin_create_invite_link", enabled=invite_links_on, call=with_join_url,
)
def create_invite_link(request: Request, body: CreateInviteLink) -> NewInviteLink:
    """One link for a group (see invite_links.py's module docs), over HTTP or
    the MCP admin_create_invite_link tool."""
    if not invite_links.valid_invite_link(body.label, body.max_uses, body.days):
        raise Refused(400, INVITE_LINK_LIMITS)
    actor = actor_from(request)
    credential, link = invite_links.issue_invite_link(get_store(request), body.label, body.max_uses, timedelta(days=body.days), actor.user.id, actor.key_id)
    audit(request, KIND_ADMIN, "invite link created", {"link_id": link.id, "label": link.label, "max_uses": link.max_uses})
    return NewInviteLink(**msgspec.structs.asdict(_row(link, actor.user)), join_path=f"/join/{credential}")


class LinkIDPath(RequestType):
    """The link a route under /api/admin/invite-links/{link_id} acts on."""

    link_id: Annotated[str, PATH, Meta(description="The link's id, from GET /api/admin/invite-links (admin_list_invite_links over MCP).")]


class RenameInviteLink(LinkIDPath):
    label: Annotated[str, Meta(min_length=1, max_length=80, description="1-80 characters.", extra={"error": "label must be 1-80 characters"})]
    # The label the caller expects to replace, so an undo cannot overwrite a
    # rename made elsewhere.
    expect: Annotated[str | None, Meta(description="The label you think it has. Answers 409 if it has another.")] = None


class RenameInviteLinkReply(Reply):
    ok: bool
    label: str


@route(
    "POST /api/admin/invite-links/{link_id}/rename", summary="Rename an invite link",
    tag="Invite links", role=ADMIN, feature="invite_links", errors=(409,),
    description="Change the label people see on an invite link's join page (1-80 characters). expect, when "
    "given, is the label you think it has now.",
    mcp="admin_rename_invite_link", enabled=invite_links_on,
)
def rename_invite_link(request: Request, body: RenameInviteLink) -> RenameInviteLinkReply:
    """Change a link's label, over HTTP or the MCP admin_rename_invite_link
    tool."""
    if not invite_links.valid_invite_label(body.label):
        raise Refused(400, "label must be 1-80 characters")
    try:
        renamed = invite_links.rename_invite_link(get_store(request), body.link_id, body.label, body.expect)
    except users.RenameConflictError as refusal:
        raise Refused(409, str(refusal), label=refusal.current) from None
    if not renamed:
        raise Refused(404, "no such invite link")
    audit(request, KIND_ADMIN, "invite link renamed", {"link_id": body.link_id, "label": body.label.strip()})
    return RenameInviteLinkReply(ok=True, label=body.label.strip())


INVITE_LIMITS = "uses must be 1-1000 and days 1-365"


class SetInviteLinkLimits(LinkIDPath):
    max_uses: Annotated[int, Meta(ge=1, le=INVITE_LINK_MAX_USES, description="Not fewer than have joined.", extra={"error": INVITE_LIMITS})]
    days: Annotated[Annotated[int, Meta(ge=1, le=INVITE_LINK_MAX_DAYS, extra={"error": INVITE_LIMITS})] | None, Meta(description="Counted from now. Leave out to keep the expiry.")] = None


@route(
    "POST /api/admin/invite-links/{link_id}/limits", summary="Change an invite link's places and expiry",
    tag="Invite links", role=ADMIN, feature="invite_links",
    description="Set how many people the link may take in (never fewer than have joined) and, when days is "
    "given, a new expiry counted from now. The link then counts as this key's: revoking the key switches it "
    "off.",
    mcp="admin_set_invite_link_limits", enabled=invite_links_on,
)
def set_invite_link_limits(request: Request, body: SetInviteLinkLimits) -> InviteLinkRow:
    """Change a link's places, and its expiry when days is given; leaving days
    out keeps the expiry. Over HTTP or the MCP admin_set_invite_link_limits
    tool. Through an API key the link becomes that key's: revoking the key
    switches it off (see invite_links.set_invite_link_limits)."""
    if not invite_links.valid_invite_limits(body.max_uses, body.days):
        raise Refused(400, INVITE_LIMITS)
    store = get_store(request)
    ttl = None if body.days is None else timedelta(days=body.days)
    try:
        link = invite_links.set_invite_link_limits(store, body.link_id, body.max_uses, ttl, actor_from(request).key_id)
    except invite_links.InvitePlacesError as refusal:
        raise Refused(400, str(refusal)) from None
    if link is None:
        raise Refused(404, "no such invite link")
    audit(request, KIND_ADMIN, "invite link limits changed", {"link_id": link.id, "max_uses": link.max_uses, "expires_at": link.expires_at.isoformat()})
    return _row(link, users.get_user(store, link.created_by))


@route(
    "POST /api/admin/invite-links/{link_id}/switch-on", summary="Switch an invite link back on",
    tag="Invite links", role=ADMIN, feature="invite_links",
    mcp_note="Undo admin_revoke_invite_link: anyone still holding the link can use it again. The link then "
    "counts as this key's: revoking the key switches it off.",
    mcp="admin_switch_on_invite_link", enabled=invite_links_on,
)
def switch_on_invite_link(request: Request, body: LinkIDPath) -> InviteLinkRow:
    """Undo revoke_invite_link, over HTTP or the MCP
    admin_switch_on_invite_link tool. A key that switches a link on takes it
    over, so revoking that key closes it again."""
    store = get_store(request)
    link = invite_links.switch_on_invite_link(store, body.link_id, actor_from(request).key_id)
    if link is None:
        raise Refused(404, "no such invite link")
    audit(request, KIND_ADMIN, "invite link switched back on", {"link_id": link.id})
    return _row(link, users.get_user(store, link.created_by))


@route(
    "POST /api/admin/invite-links/{link_id}/revoke", summary="Switch off an invite link",
    tag="Invite links", role=ADMIN, feature="invite_links",
    description="Stop an invite link from letting anyone else join or sign in through it. Accounts it "
    "already made keep working. Cannot be switched back on.",
    mcp="admin_revoke_invite_link", destructive=True, enabled=invite_links_on,
)
def revoke_invite_link(request: Request, body: LinkIDPath) -> OkReply:
    """Switch a link off, over HTTP or the MCP admin_revoke_invite_link tool.
    The accounts it made keep working."""
    if not invite_links.revoke_invite_link(get_store(request), body.link_id):
        raise Refused(404, "no such invite link")
    audit(request, KIND_ADMIN, "invite link revoked", {"link_id": body.link_id})
    return OkReply(ok=True)


@route(
    "POST /api/admin/invite-links/{link_id}/delete", summary="Delete an invite link",
    tag="Invite links", role=ADMIN, feature="invite_links",
    description="Take an invite link off the list and stop it working. The accounts it made stay.",
    mcp_note="admin_restore_invite_link undoes it for a few minutes.",
    mcp="admin_delete_invite_link", destructive=True, enabled=invite_links_on,
)
def delete_invite_link(request: Request, body: LinkIDPath) -> OkReply:
    """Drop a link from the list, over HTTP or the MCP admin_delete_invite_link
    tool. The accounts it made stay; they just can no longer sign in on a new
    device through it. restore_invite_link undoes it for a few minutes."""
    if not invite_links.delete_invite_link(get_store(request), body.link_id, actor_from(request).user.id):
        raise Refused(404, "no such invite link")
    audit(request, KIND_ADMIN, "invite link deleted", {"link_id": body.link_id})
    return OkReply(ok=True)


@route(
    "POST /api/admin/invite-links/{link_id}/restore", summary="Undo deleting an invite link",
    tag="Invite links", role=ADMIN, feature="invite_links", errors=(409,),
    description="Bring back an invite link deleted in the last few minutes, working as before. The link "
    "then counts as this key's: revoking the key switches it off.",
    mcp="admin_restore_invite_link", enabled=invite_links_on,
)
def restore_invite_link(request: Request, body: LinkIDPath) -> InviteLinkRow:
    """Undo delete_invite_link, within RESTORE_WINDOW, over HTTP or the MCP
    admin_restore_invite_link tool. The link works again exactly as before,
    uses and expiry included."""
    store, actor = get_store(request), actor_from(request)
    try:
        link = invite_links.restore_invite_link(store, body.link_id, actor.user.id, actor.user.is_admin, actor.key_id)
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None
    audit(request, KIND_ADMIN, "invite link restored", {"link_id": body.link_id})
    return _row(link, users.get_user(store, link.created_by))
