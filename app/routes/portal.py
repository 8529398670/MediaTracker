"""The owner's ProjectPortal card (portal contract v3): connect the portal
through a service account of its own, see its keys, and disconnect it. The
rules are in app/models/portal.py. Keys are never managed over MCP."""
from __future__ import annotations

from typing import Annotated, ClassVar

import msgspec
from msgspec import Meta
from starlette.requests import Request

from app.apidocs import OWNER, Reply, route
from app.apidocs import Request as RequestType
from app.core.error_codes import CODE_OWNER_REQUIRED
from app.core.logs import KIND_ADMIN
from app.core.security import actor_from
from app.models import api_keys, portal
from app.models.users import OwnerRequiredError
from app.routes.api_keys import APIKey, NewAPIKey, api_key_row
from app.routes.helpers import Refused, act_on_refusals, get_store
from app.routes.logs import audit


class PortalAccount(Reply):
    api_name: ClassVar[str] = "PortalAccount"
    id: int
    display_name: str
    keys: Annotated[list[APIKey], Meta(description="Its live keys, newest first.")]


class PortalReply(Reply):
    accounts: Annotated[list[PortalAccount], Meta(description="Every service account, oldest first.")]


@route(
    "GET /api/owner/portal", summary="ProjectPortal's accounts",
    tag="Owner", role=OWNER, feature="api_keys",
    description="The service accounts ProjectPortal works through, each with its live keys and when they expire.",
)
def get_portal(request: Request) -> PortalReply:
    """The card's status: the service accounts and their live keys."""
    return PortalReply(accounts=[
        PortalAccount(id=account.user.id, display_name=account.user.display_name, keys=[api_key_row(key, account.user.display_name) for key in account.keys])
        for account in portal.portal_accounts(get_store(request))
    ])


class PortalConnect(RequestType):
    days: Annotated[int, Meta(ge=1, le=365, description="How long the key lasts, in days.", extra={"error": "days must be 1-365"})]
    name: Annotated[str, Meta(min_length=1, max_length=80, description="The service account's name. Left out: ProjectPortal.", extra={"error": "name must be 1-80 characters"})] = portal.DEFAULT_PORTAL_NAME


@route(
    "POST /api/owner/portal/connect", summary="Connect ProjectPortal",
    tag="Owner", role=OWNER, feature="api_keys", status=201,
    description="Makes the service account named name (ProjectPortal when left out) if there is none, and one admin "
    "key for it, lasting days (1-365), that may make keys for other accounts and never makes sign-in links. Answers "
    "with the key and its credential, shown only now: paste it into ProjectPortal as this app's admin key.",
)
def connect_portal(request: Request, body: PortalConnect) -> NewAPIKey:
    """Make the service account if there is none by that name, and one more
    admin key for it that may make keys and never sign-in links."""
    actor = actor_from(request).user
    try:
        credential, key, user = portal.connect_portal(get_store(request), actor.id, body.name, body.days * 24 * 60 * 60)
    except portal.BadPortalNameError as refusal:
        raise Refused(400, str(refusal)) from None
    except api_keys.APIKeyLimitError:
        raise Refused(400, "that account already has the maximum number of live API keys") from None
    except OwnerRequiredError:
        raise Refused(403, "only the owner connects ProjectPortal", code=CODE_OWNER_REQUIRED) from None
    audit(request, KIND_ADMIN, "portal connected", {"user_id": user.id, "key_id": key.id, "expires_at": key.expires_at.isoformat() if key.expires_at else None})
    return NewAPIKey(**msgspec.structs.asdict(api_key_row(key, user.display_name)), credential=credential)


class PortalDisconnect(RequestType):
    user_id: Annotated[int, Meta(description="The service account.")]


class PortalDisconnectReply(Reply):
    ok: bool
    revoked: Annotated[int, Meta(description="Its keys revoked. The keys and links they made went with them.")]


@route(
    "POST /api/owner/portal/disconnect", summary="Disconnect ProjectPortal",
    tag="Owner", role=OWNER, feature="api_keys", errors=(404,),
    description="Revokes every key of the service account user_id, and with them every key and link those keys "
    "made. The account stays, with no way in, until Connect gives it a key again.",
)
def disconnect_portal(request: Request, body: PortalDisconnect) -> PortalDisconnectReply:
    """Revoke every key of a service account."""
    try:
        with act_on_refusals("disconnect"):
            revoked = portal.disconnect_portal(get_store(request), actor_from(request).user.id, body.user_id)
    except portal.NotServiceError:
        revoked = None
    if revoked is None:
        raise Refused(404, "no such service account")
    audit(request, KIND_ADMIN, "portal disconnected", {"user_id": body.user_id, "revoked": revoked})
    return PortalDisconnectReply(ok=True, revoked=revoked)
