"""Media types (sections of the library) and sources (the lists titles were
found on). Shared by the family, editable by anyone signed in."""
from __future__ import annotations

from typing import Annotated, Any, Callable

from msgspec import UNSET, Meta, UnsetType
from starlette.requests import Request

from app.apidocs import PATH, Reply, route
from app.apidocs import Request as RequestType
from app.core.security import actor_from
from app.mcp.registry import Call
from app.models import RestoreError, sources, types
from app.models.revision import NotFoundError
from app.routes.helpers import Refused, get_store, restore_refusal
from app.routes.prefs import Deleted
from app.routes.subject import given

TAG = "Library"
Record = dict[str, Any]


def in_object(key: str) -> Callable[[Call, Any, Callable[[Any, Any], Any]], dict[str, Any]]:
    """The call of a tool whose route answers a list: the list, in an object,
    as MCP answers are."""
    def call(tool_call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
        return {key: serve(tool_call.request, body)}
    return call


@route(
    "GET /api/types", summary="Media types",
    tag=TAG,
    description="The library's sections (Movies, TV, and any the family added), in order.",
    mcp="list_types", read_only=True, call=in_object("types"),
)
def list_types(request: Request) -> list[Record]:
    return types.list_types(get_store(request))


class SaveType(RequestType, kw_only=True):
    id: Annotated[str, Meta(description="a-z, 0-9 and -, up to 32; never changes once made.")]
    label: Annotated[str, Meta(description="Up to 40 characters.")]
    icon: str = ""
    lookup: Annotated[str, Meta(description="What titles of this type are looked up as: movie, tv, book, ... or other.")] = "other"
    position: int | None = None


@route(
    "POST /api/types", summary="Add or change a type",
    tag=TAG,
    description="Create a media type, or change one by its id. Movies and TV keep their lookup.",
    mcp="save_type",
)
def save_type(request: Request, body: SaveType) -> Record:
    raw = given(body)
    if raw.get("position") is None:
        raw.pop("position", None)
    try:
        return types.save_type(get_store(request), raw)
    except ValueError as error:
        raise Refused(400, str(error)) from None


TypeID = Annotated[str, PATH, Meta(description="A type's id, from GET /api/types.")]


class TypePath(RequestType, kw_only=True):
    type_id: TypeID


class DeleteType(TypePath, kw_only=True):
    reassign_to: Annotated[str | None, Meta(description="The type its titles move to. Needed while it holds any.")] = None


class TypeDeleted(Reply, kw_only=True):
    moved: Annotated[int, Meta(description="Titles moved to reassign_to.")]


@route(
    "POST /api/types/{type_id}/delete", summary="Delete a type",
    tag=TAG, errors=(404, 409),
    description="Delete a media type. One that still holds titles needs reassign_to, the type they move to "
    "(409 type_in_use with their count otherwise). Movies and TV cannot be deleted. Soft: restoring it "
    "brings it back.",
    mcp="delete_type", destructive=True,
)
def delete_type(request: Request, body: DeleteType) -> TypeDeleted:
    try:
        moved = types.delete_type(get_store(request), body.type_id, body.reassign_to, actor_from(request).user.id)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except types.TypeInUseError as error:
        raise Refused(409, "type_in_use", count=error.count) from None
    except types.BuiltinTypeError as error:
        raise Refused(400, str(error)) from None
    return TypeDeleted(moved=moved)


@route(
    "POST /api/types/{type_id}/restore", summary="Restore a type",
    tag=TAG, errors=(403, 404, 409),
    description="Bring back a deleted media type, within the undo window.",
    mcp="restore_type",
)
def restore_type(request: Request, body: TypePath) -> Record:
    actor = actor_from(request)
    try:
        return types.restore_type(get_store(request), body.type_id, actor.user.id, actor.is_admin)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None


@route(
    "GET /api/sources", summary="Sources",
    tag=TAG,
    description="The lists and pages titles were found on, newest first.",
    mcp="list_sources", read_only=True, call=in_object("sources"),
)
def list_sources(request: Request) -> list[Record]:
    return sources.list_sources(get_store(request))


class SourceFields(RequestType, kw_only=True):
    title: Annotated[str | UnsetType, Meta(description="Up to 300 characters.")] = UNSET
    note: Annotated[str | UnsetType, Meta(description="Up to 2000 characters.")] = UNSET
    tags: Annotated[list[str] | UnsetType, Meta(description="Up to 20.")] = UNSET


class CreateSource(SourceFields, kw_only=True):
    url: Annotated[str, Meta(description="An http(s) link.")]


@route(
    "POST /api/sources", summary="Add a source",
    tag=TAG, status=201,
    description="Remember a list or page titles were found on.",
    mcp="create_source",
)
def create_source(request: Request, body: CreateSource) -> Record:
    try:
        return sources.create_source(get_store(request), given(body), actor_from(request).user.id)
    except ValueError as error:
        raise Refused(400, str(error)) from None


SourceID = Annotated[str, PATH, Meta(description="A source's id, from GET /api/sources.")]


class SourcePath(RequestType, kw_only=True):
    source_id: SourceID


class UpdateSource(SourceFields, kw_only=True):
    source_id: SourceID
    url: Annotated[str | UnsetType, Meta(description="An http(s) link.")] = UNSET


class SourceChange(Reply, kw_only=True):
    source: Record
    previous: Annotated[Record, Meta(description="What the changed fields were before.")]


@route(
    "POST /api/sources/{source_id}/update", summary="Change a source",
    tag=TAG, errors=(404,),
    description="Change a source's link, title, note or tags. Returns the previous values.",
    mcp="update_source",
)
def update_source(request: Request, body: UpdateSource) -> SourceChange:
    try:
        record, previous = sources.update_source(get_store(request), body.source_id, given(body, "source_id"))
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except ValueError as error:
        raise Refused(400, str(error)) from None
    return SourceChange(source=record, previous=previous)


@route(
    "POST /api/sources/{source_id}/delete", summary="Delete a source",
    tag=TAG, errors=(404,),
    description="Delete a source. Soft: restoring it brings it back within the undo window.",
    mcp="delete_source", destructive=True,
)
def delete_source(request: Request, body: SourcePath) -> Deleted:
    try:
        sources.delete_source(get_store(request), body.source_id, actor_from(request).user.id)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    return Deleted(deleted=True)


@route(
    "POST /api/sources/{source_id}/restore", summary="Restore a source",
    tag=TAG, errors=(403, 404, 409),
    description="Bring back a deleted source, within the undo window.",
    mcp="restore_source",
)
def restore_source(request: Request, body: SourcePath) -> Record:
    actor = actor_from(request)
    try:
        return sources.restore_source(get_store(request), body.source_id, actor.user.id, actor.is_admin)
    except NotFoundError as error:
        raise Refused(404, str(error)) from None
    except RestoreError as refusal:
        raise restore_refusal(refusal) from None
