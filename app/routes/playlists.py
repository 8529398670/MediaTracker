"""A person's playlists: named, numbered lists of titles. Every route takes
?user= (see subject.py), so an admin acting for someone edits theirs.

Item changes answer {playlist, previous_items}; previous_items is what the
undo sends back to /set.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import PATH, QUERY, Reply, route
from app.apidocs import Request as RequestType
from app.core.security import actor_from
from app.mcp.registry import Call
from app.models import RestoreError, library_cache, playlists
from app.models.revision import NotFoundError
from app.routes.helpers import Refused, get_store, restore_refusal
from app.routes.library import _row
from app.routes.prefs import Deleted, OkReply, Reorder
from app.routes.subject import User, subject_of

TAG = "Playlists"
Playlist = dict[str, Any]
TitleIDs = Annotated[list[str], Meta(description="Title ids, from GET /api/library (search_library over MCP).")]
Position = Annotated[Annotated[int, Meta(ge=1)] | None, Meta(description="1-based; the end by default.")]


class ListPlaylists(RequestType, kw_only=True):
    playlist_id: Annotated[Annotated[int, Meta(ge=1)] | None, QUERY, Meta(description="Over MCP only: that one playlist's titles, numbered in its order, instead of the list.")] = None
    user: User = None


def playlist_rows(call: Call, body: Any, serve: Callable[[Any, Any], Any]) -> dict[str, Any]:
    """The call of list_playlists: id, name and count for each, or with
    playlist_id that playlist's titles, numbered."""
    mine = serve(call.request, body)
    if body.playlist_id is None:
        return {"playlists": [{"id": record["id"], "name": record["name"], "count": len(record["items"])} for record in mine]}
    found = next((record for record in mine if record["id"] == body.playlist_id), None)
    if found is None:
        raise Refused(404, "no such playlist")
    snapshot = library_cache.get(call.store)
    states = snapshot.states_for(subject_of(call.request, body.user))
    rows = []
    for number, title_id in enumerate(found["items"], start=1):
        title = snapshot.titles.get(title_id)
        if title and not title.get("deleted_at"):
            rows.append({"number": number, **_row(title, states.get(title_id), None)})
    return {"id": found["id"], "name": found["name"], "titles": rows}


@route(
    "GET /api/playlists", summary="Playlists",
    tag=TAG,
    description="A person's playlists, in their order, each with its titles (items).",
    mcp_description="A person's playlists: id, name and how many titles each holds. With playlist_id, that "
    "one playlist's titles instead, numbered in its order.",
    mcp="list_playlists", read_only=True, call=playlist_rows,
)
def list_playlists(request: Request, body: ListPlaylists) -> list[Playlist]:
    return playlists.list_playlists(get_store(request), subject_of(request, body.user))


class CreatePlaylist(RequestType, kw_only=True):
    name: Annotated[str, Meta(description="Up to 80 characters.")]
    items: Annotated[TitleIDs, Meta(description="Title ids, in order.")] = []
    user: User = None


@route(
    "POST /api/playlists", summary="Create a playlist",
    tag=TAG, status=201,
    description="A new playlist, optionally with titles (items: title ids, in order).",
    mcp="create_playlist",
)
def create_playlist(request: Request, body: CreatePlaylist) -> Playlist:
    subject = subject_of(request, body.user)
    try:
        return playlists.create_playlist(get_store(request), subject, body.name, body.items)
    except ValueError as error:
        raise Refused(400, str(error)) from None


@route(
    "POST /api/playlists/reorder", summary="Order playlists",
    tag=TAG,
    description="Put the playlists in this order (ids: every playlist id, first to last).",
    mcp="reorder_playlists",
)
def reorder_playlists(request: Request, body: Reorder) -> OkReply:
    playlists.reorder_playlists(get_store(request), subject_of(request, body.user), body.ids)
    return OkReply(ok=True)


class PlaylistPath(RequestType, kw_only=True):
    playlist_id: Annotated[int, PATH, Meta(ge=1, description="A playlist's id, from GET /api/playlists.", extra={"error": "no such playlist"})]
    user: User = None


def _refusal(error: Exception) -> Refused:
    if isinstance(error, NotFoundError):
        return Refused(404, str(error))
    if isinstance(error, RestoreError):
        return restore_refusal(error)
    return Refused(400, str(error))


def _subject(request: Request, body: PlaylistPath) -> int:
    return subject_of(request, body.user)


class Rename(PlaylistPath, kw_only=True):
    name: Annotated[str, Meta(description="Up to 80 characters.")]


class Renamed(Reply, kw_only=True):
    playlist: Playlist
    previous_name: str


@route(
    "POST /api/playlists/{playlist_id}/update", summary="Rename a playlist",
    tag=TAG, errors=(404,),
    description="Give a playlist a new name. Returns the previous one.",
    mcp="rename_playlist",
)
def update_playlist(request: Request, body: Rename) -> Renamed:
    try:
        record, old_name = playlists.rename_playlist(get_store(request), _subject(request, body), body.playlist_id, body.name)
    except (NotFoundError, ValueError) as error:
        raise _refusal(error) from None
    return Renamed(playlist=record, previous_name=old_name)


@route(
    "POST /api/playlists/{playlist_id}/delete", summary="Delete a playlist",
    tag=TAG, errors=(404,),
    description="Delete a playlist. Soft: restoring it brings it back within the undo window.",
    mcp="delete_playlist", destructive=True,
)
def delete_playlist(request: Request, body: PlaylistPath) -> Deleted:
    try:
        playlists.delete_playlist(get_store(request), _subject(request, body), body.playlist_id, actor_from(request).user.id)
    except NotFoundError as error:
        raise _refusal(error) from None
    return Deleted(deleted=True)


class PlaylistReply(Reply, kw_only=True):
    playlist: Playlist


@route(
    "POST /api/playlists/{playlist_id}/restore", summary="Restore a playlist",
    tag=TAG, errors=(403, 404, 409),
    description="Bring back a deleted playlist, within the undo window.",
    mcp="restore_playlist",
)
def restore_playlist(request: Request, body: PlaylistPath) -> PlaylistReply:
    actor = actor_from(request)
    try:
        return PlaylistReply(playlist=playlists.restore_playlist(get_store(request), _subject(request, body), body.playlist_id, actor.user.id, actor.is_admin))
    except (NotFoundError, RestoreError) as error:
        raise _refusal(error) from None


class ItemsChange(Reply, kw_only=True):
    playlist: Playlist
    previous_items: Annotated[list[str], Meta(description="The items before: what setting the items takes back.")]


class AddItems(PlaylistPath, kw_only=True):
    title_ids: TitleIDs
    position: Position = None


@route(
    "POST /api/playlists/{playlist_id}/add", summary="Add to a playlist",
    tag=TAG, errors=(404,),
    description="Add titles at position (the end by default); the rest renumber. Returns the items before, "
    "which setting the items takes back.",
    mcp="add_to_playlist",
)
def add_items(request: Request, body: AddItems) -> ItemsChange:
    try:
        record, before = playlists.add_items(get_store(request), _subject(request, body), body.playlist_id, body.title_ids, body.position)
    except (NotFoundError, ValueError) as error:
        raise _refusal(error) from None
    return ItemsChange(playlist=record, previous_items=before)


class RemoveItems(PlaylistPath, kw_only=True):
    title_ids: TitleIDs


@route(
    "POST /api/playlists/{playlist_id}/remove", summary="Remove from a playlist",
    tag=TAG, errors=(404,),
    description="Take titles off a playlist; the rest renumber. Returns the items before, which setting the "
    "items takes back.",
    mcp="remove_from_playlist",
)
def remove_items(request: Request, body: RemoveItems) -> ItemsChange:
    try:
        record, before = playlists.remove_items(get_store(request), _subject(request, body), body.playlist_id, body.title_ids)
    except (NotFoundError, ValueError) as error:
        raise _refusal(error) from None
    return ItemsChange(playlist=record, previous_items=before)


class MoveItem(PlaylistPath, kw_only=True):
    title_id: Annotated[str, Meta(description="The title to move.")]
    position: Annotated[int, Meta(ge=1, description="1-based.")]


@route(
    "POST /api/playlists/{playlist_id}/move", summary="Move within a playlist",
    tag=TAG, errors=(404,),
    description="Move one title to position; the rest renumber. Returns the items before, which setting the "
    "items takes back.",
    mcp="move_in_playlist",
)
def move_item(request: Request, body: MoveItem) -> ItemsChange:
    try:
        record, before = playlists.move_item(get_store(request), _subject(request, body), body.playlist_id, body.title_id, body.position)
    except (NotFoundError, ValueError) as error:
        raise _refusal(error) from None
    return ItemsChange(playlist=record, previous_items=before)


class SetItems(PlaylistPath, kw_only=True):
    items: Annotated[TitleIDs, Meta(description="Every title, in order.")]


@route(
    "POST /api/playlists/{playlist_id}/set", summary="Set a playlist's titles",
    tag=TAG, errors=(404,),
    description="Replace a playlist's titles with items, in order: the undo of add, remove and move. Returns "
    "the items before.",
    mcp="set_playlist_items",
)
def set_items(request: Request, body: SetItems) -> ItemsChange:
    try:
        record, before = playlists.set_items(get_store(request), _subject(request, body), body.playlist_id, body.items)
    except (NotFoundError, ValueError) as error:
        raise _refusal(error) from None
    return ItemsChange(playlist=record, previous_items=before)
