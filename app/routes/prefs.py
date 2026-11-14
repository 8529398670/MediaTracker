"""Per-person settings (card layout, last query per screen) and saved
views. Both take ?user= so an admin acting for someone sees their setup."""
from __future__ import annotations

from typing import Annotated, Any, Callable

from msgspec import UNSET, Meta, UnsetType
from starlette.requests import Request

from app.apidocs import PATH, Reply, route
from app.apidocs import Request as RequestType
from app.core.security import actor_from
from app.mcp.registry import Call
from app.models import RestoreError, prefs, views
from app.models.revision import NotFoundError
from app.routes.helpers import Refused, get_store, restore_refusal
from app.routes.subject import User, given, subject_of

TAG = "Settings"
Section = Annotated[dict[str, Any] | UnsetType, Meta(description="Each key given replaces that key in the section; null removes it.")]


class Personal(RequestType, kw_only=True):
    user: User = None


class Prefs(Reply, kw_only=True):
    cards: Annotated[dict[str, Any], Meta(description="How cards look, per screen.")]
    last_query: Annotated[dict[str, Any], Meta(description="The last query on each screen.")]
    default_view: dict[str, Any]
    ui: dict[str, Any]


@route(
    "GET /api/prefs", summary="Settings",
    tag=TAG,
    description="A person's settings that follow them between devices: cards (layout per screen), "
    "last_query, default_view and ui.",
    mcp="get_prefs", read_only=True,
)
def get_prefs(request: Request, body: Personal) -> Prefs:
    return Prefs(**prefs.get_prefs(get_store(request), subject_of(request, body.user)))


class SavePrefs(RequestType, kw_only=True):
    cards: Section = UNSET
    last_query: Section = UNSET
    default_view: Section = UNSET
    ui: Section = UNSET
    user: User = None


@route(
    "POST /api/prefs", summary="Change settings",
    tag=TAG,
    description="Change settings by section (cards, last_query, default_view, ui): each key given replaces "
    "that key within its section, and null removes it. Returns them all.",
    mcp="save_prefs",
)
def save_prefs(request: Request, body: SavePrefs) -> Prefs:
    subject = subject_of(request, body.user)
    try:
        return Prefs(**prefs.save_prefs(get_store(request), subject, given(body)))
    except ValueError as error:
        raise Refused(400, str(error)) from None


View = dict[str, Any]


def as_views(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of list_views: the list, in an object, as MCP answers are."""
    return {"views": serve(call.request, body)}


@route(
    "GET /api/views", summary="Saved views",
    tag=TAG,
    description="A person's saved views: a named query on the library or Discover screen, in their order.",
    mcp="list_views", read_only=True, call=as_views,
)
def list_views(request: Request, body: Personal) -> list[View]:
    return views.list_views(get_store(request), subject_of(request, body.user))


class ViewFields(RequestType, kw_only=True):
    screen: Annotated[str | UnsetType, Meta(description="library or discover.")] = UNSET
    scope: Annotated[str | UnsetType, Meta(description="The library section it is on.")] = UNSET
    query: Annotated[str | UnsetType, Meta(description="The screen's address, such as #library/all/queue?runtime=..100.")] = UNSET
    card: Annotated[dict[str, Any] | None | UnsetType, Meta(description="How cards look in this view.")] = UNSET
    icon: str | UnsetType = UNSET
    user: User = None


class CreateView(ViewFields, kw_only=True):
    name: Annotated[str, Meta(description="Up to 80 characters.")]


@route(
    "POST /api/views", summary="Save a view",
    tag=TAG, status=201,
    description="Save a named view of a screen.",
    mcp="create_view",
)
def create_view(request: Request, body: CreateView) -> View:
    subject = subject_of(request, body.user)
    try:
        return views.create_view(get_store(request), subject, given(body))
    except ValueError as error:
        raise Refused(400, str(error)) from None


class ViewPath(RequestType, kw_only=True):
    view_id: Annotated[int, PATH, Meta(ge=1, description="A view's id, from GET /api/views.", extra={"error": "no such view"})]
    user: User = None


class UpdateView(ViewFields, kw_only=True):
    view_id: Annotated[int, PATH, Meta(ge=1, description="A view's id, from GET /api/views.", extra={"error": "no such view"})]
    name: str | UnsetType = UNSET


class ViewChange(Reply, kw_only=True):
    view: View
    previous: Annotated[dict[str, Any], Meta(description="What the changed fields were before: send them back to undo.")]


def _view_refusals(error: Exception) -> Refused:
    if isinstance(error, NotFoundError):
        return Refused(404, "no such view")
    if isinstance(error, RestoreError):
        return restore_refusal(error)
    return Refused(400, str(error))


@route(
    "POST /api/views/{view_id}/update", summary="Change a view",
    tag=TAG, errors=(404,),
    description="Change a saved view's name, query, card layout or icon. Returns the previous values.",
    mcp="update_view",
)
def update_view(request: Request, body: UpdateView) -> ViewChange:
    subject = subject_of(request, body.user)
    try:
        record, previous = views.update_view(get_store(request), subject, body.view_id, given(body, "view_id"))
    except (NotFoundError, ValueError) as error:
        raise _view_refusals(error) from None
    return ViewChange(view=record, previous=previous)


class Deleted(Reply, kw_only=True):
    deleted: bool


@route(
    "POST /api/views/{view_id}/delete", summary="Delete a view",
    tag=TAG, errors=(404,),
    description="Delete a saved view. Soft: restoring it brings it back within the undo window.",
    mcp="delete_view", destructive=True,
)
def delete_view(request: Request, body: ViewPath) -> Deleted:
    subject = subject_of(request, body.user)
    try:
        views.delete_view(get_store(request), subject, body.view_id, actor_from(request).user.id)
    except NotFoundError as error:
        raise _view_refusals(error) from None
    return Deleted(deleted=True)


class ViewReply(Reply, kw_only=True):
    view: View


@route(
    "POST /api/views/{view_id}/restore", summary="Restore a view",
    tag=TAG, errors=(403, 404, 409),
    description="Bring back a deleted saved view, within the undo window.",
    mcp="restore_view",
)
def restore_view(request: Request, body: ViewPath) -> ViewReply:
    subject = subject_of(request, body.user)
    actor = actor_from(request)
    try:
        return ViewReply(view=views.restore_view(get_store(request), subject, body.view_id, actor.user.id, actor.is_admin))
    except (NotFoundError, RestoreError) as error:
        raise _view_refusals(error) from None


class Reorder(RequestType, kw_only=True):
    ids: Annotated[list[int], Meta(description="Ids, first to last.")]
    user: User = None


class OkReply(Reply, kw_only=True):
    ok: bool


@route(
    "POST /api/views/reorder", summary="Order views",
    tag=TAG,
    description="Put the saved views in this order (ids: view ids, first to last).",
    mcp="reorder_views",
)
def reorder_views(request: Request, body: Reorder) -> OkReply:
    views.reorder_views(get_store(request), subject_of(request, body.user), body.ids)
    return OkReply(ok=True)
