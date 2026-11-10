"""Playlists, saved views, prefs, media types and sources over /mcp. Like
mcp_tools_library.py (whose argument and refusal helpers these use), each
tool is the door to one HTTP route and calls the helper that route uses.

Playlists, views and prefs are personal and take an optional user_id, the
?user= of the routes. Types and sources are the family's, like titles.
Deletes are the routes' soft deletes, restorable within the undo window.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.mcp.registry import Call, Refusal, Registry, Tool
from app.models import library_cache, playlists, prefs, sources, types, views
from app.routes import media_types as media_types_route
from app.routes import playlists as playlists_route
from app.routes import prefs as prefs_route
from app.routes.mcp_tools_library import TITLE_ID, TITLE_IDS, USER, _args, _body, _row, _shared, _subject, schema

PLAYLIST_ID = {"type": "integer", "minimum": 1, "description": "A playlist id from list_playlists."}
VIEW_ID = {"type": "integer", "minimum": 1, "description": "A view id from list_views."}
VIEW_FIELDS = {
    "name": {"type": "string"},
    "screen": {"type": "string", "enum": list(views.SCREENS)},
    "scope": {"type": "string"},
    "query": {"type": "string", "description": "The screen's address, such as #library/all/queue?runtime=..100."},
    "card": {"type": "object", "description": "How cards look in this view."},
    "icon": {"type": "string"},
}
VIEW_TYPES: dict[str, type] = {"name": str, "screen": str, "scope": str, "query": str, "card": dict, "icon": str}
TYPE_FIELDS = {
    "id": {"type": "string", "description": "a-z, 0-9 and -; never changes once made."},
    "label": {"type": "string"},
    "icon": {"type": "string"},
    "lookup": {"type": "string", "description": "What titles of this type are looked up as: movie, tv, book, ... or other."},
    "position": {"type": "integer"},
}
SOURCE_FIELDS = {
    "url": {"type": "string", "description": "An http(s) link."},
    "title": {"type": "string"},
    "note": {"type": "string"},
    "tags": {"type": "array", "items": {"type": "string"}},
}
SOURCE_TYPES: dict[str, type] = {"url": str, "title": str, "note": str, "tags": list}


def _actor(call: Call) -> tuple[int, bool]:
    return call.actor.user.id, call.actor.is_admin


# --- playlists ---


def list_playlists(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"playlist_id": int, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    mine = playlists.list_playlists(call.store, subject)
    if "playlist_id" not in args:
        return {"playlists": [{"id": record["id"], "name": record["name"], "count": len(record["items"])} for record in mine]}
    found = next((record for record in mine if record["id"] == args["playlist_id"]), None)
    if found is None:
        raise Refusal("no such playlist")
    snapshot = library_cache.get(call.store)
    states = snapshot.states_for(subject)
    rows = []
    for number, title_id in enumerate(found["items"], start=1):
        title = snapshot.titles.get(title_id)
        if title and not title.get("deleted_at"):
            rows.append({"number": number, **_row(title, states.get(title_id), None)})
    return {"id": found["id"], "name": found["name"], "titles": rows}


def create_playlist(call: Call) -> dict[str, Any]:
    args = _args(call, {"name": str}, {"items": list, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(playlists_route.create_checked, call.store, subject, _body(args))


def reorder_playlists(call: Call) -> dict[str, Any]:
    args = _args(call, {"ids": list}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(playlists_route.reorder_checked, call.store, subject, _body(args))


def _playlist_tool(action: str, required: dict[str, type], optional: dict[str, type]) -> Callable[[Call], dict[str, Any]]:
    def tool(call: Call) -> dict[str, Any]:
        args = _args(call, {"playlist_id": int, **required}, {**optional, "user_id": int})
        subject = _subject(call, args.get("user_id"))
        actor_id, is_admin = _actor(call)
        return _shared(playlists_route.action_checked, call.store, subject, actor_id, is_admin, str(args["playlist_id"]), action, _body(args, "playlist_id"))

    return tool


# --- saved views and prefs ---


def list_views(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"user_id": int})
    return {"views": views.list_views(call.store, _subject(call, args.get("user_id")))}


def create_view(call: Call) -> dict[str, Any]:
    args = _args(call, {"name": str}, {**VIEW_TYPES, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(prefs_route.create_view_checked, call.store, subject, _body(args))


def reorder_views(call: Call) -> dict[str, Any]:
    args = _args(call, {"ids": list}, {"user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(prefs_route.reorder_views_checked, call.store, subject, _body(args))


def _view_tool(action: str, optional: dict[str, type]) -> Callable[[Call], dict[str, Any]]:
    def tool(call: Call) -> dict[str, Any]:
        args = _args(call, {"view_id": int}, {**optional, "user_id": int})
        subject = _subject(call, args.get("user_id"))
        actor_id, is_admin = _actor(call)
        return _shared(prefs_route.view_action_checked, call.store, subject, actor_id, is_admin, str(args["view_id"]), action, _body(args, "view_id"))

    return tool


def get_prefs(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {"user_id": int})
    return prefs.get_prefs(call.store, _subject(call, args.get("user_id")))


def save_prefs(call: Call) -> dict[str, Any]:
    args = _args(call, {}, {**{section: dict for section in prefs.SECTIONS}, "user_id": int})
    subject = _subject(call, args.get("user_id"))
    return _shared(prefs_route.save_prefs_checked, call.store, subject, _body(args))


# --- media types and sources ---


def list_types(call: Call) -> dict[str, Any]:
    _args(call, {}, {})
    return {"types": types.list_types(call.store)}


def save_type(call: Call) -> dict[str, Any]:
    args = _args(call, {"id": str, "label": str}, {"icon": str, "lookup": str, "position": int})
    return _shared(media_types_route.save_type_checked, call.store, args)


def delete_type(call: Call) -> dict[str, Any]:
    args = _args(call, {"type_id": str}, {"reassign_to": str})
    return _shared(media_types_route.delete_type_checked, call.store, args["type_id"], _body(args, "type_id"), call.actor.user.id)


def restore_type(call: Call) -> dict[str, Any]:
    args = _args(call, {"type_id": str}, {})
    return _shared(media_types_route.restore_type_checked, call.store, args["type_id"], *_actor(call))


def list_sources(call: Call) -> dict[str, Any]:
    _args(call, {}, {})
    return {"sources": sources.list_sources(call.store)}


def create_source(call: Call) -> dict[str, Any]:
    args = _args(call, {"url": str}, {"title": str, "note": str, "tags": list})
    return _shared(media_types_route.create_source_checked, call.store, args, call.actor.user.id)


def update_source(call: Call) -> dict[str, Any]:
    args = _args(call, {"source_id": str}, SOURCE_TYPES)
    return _shared(media_types_route.update_source_checked, call.store, args["source_id"], _body(args, "source_id"))


def delete_source(call: Call) -> dict[str, Any]:
    args = _args(call, {"source_id": str}, {})
    return _shared(media_types_route.delete_source_checked, call.store, args["source_id"], call.actor.user.id)


def restore_source(call: Call) -> dict[str, Any]:
    args = _args(call, {"source_id": str}, {})
    return _shared(media_types_route.restore_source_checked, call.store, args["source_id"], *_actor(call))


def register(registry: Registry) -> None:
    def add(name: str, route: str, title: str, description: str, call: Callable[[Call], dict[str, Any]], input_schema: dict[str, Any] | None = None, **flags: Any) -> None:
        registry.register(Tool(name=name, route=route, title=title, description=description, call=call, input_schema=input_schema, **flags))

    position = {"type": "integer", "minimum": 1, "description": "1-based; the end by default."}
    # Playlists.
    add(
        "list_playlists", "GET /api/playlists", "Playlists",
        "A person's playlists: id, name and how many titles each holds. With playlist_id, that one playlist's titles instead, numbered in its order.",
        list_playlists, schema({"playlist_id": PLAYLIST_ID, "user_id": USER}), read_only=True,
    )
    add("create_playlist", "POST /api/playlists", "Create a playlist", "A new playlist, optionally with titles (items: title ids, in order).", create_playlist, schema({"name": {"type": "string"}, "items": TITLE_IDS, "user_id": USER}, ("name",)))
    add("reorder_playlists", "POST /api/playlists/reorder", "Order playlists", "Put the playlists in this order (ids: every playlist id, first to last).", reorder_playlists, schema({"ids": {"type": "array", "items": {"type": "integer"}}, "user_id": USER}, ("ids",)))
    add(
        "rename_playlist", "POST /api/playlists/{playlist_id}/update", "Rename a playlist", "Give a playlist a new name. Returns the previous one.",
        _playlist_tool("update", {"name": str}, {}), schema({"playlist_id": PLAYLIST_ID, "name": {"type": "string"}, "user_id": USER}, ("playlist_id", "name")),
    )
    add(
        "delete_playlist", "POST /api/playlists/{playlist_id}/delete", "Delete a playlist", "Delete a playlist. Soft: restore_playlist brings it back within the undo window.",
        _playlist_tool("delete", {}, {}), schema({"playlist_id": PLAYLIST_ID, "user_id": USER}, ("playlist_id",)), destructive=True,
    )
    add(
        "restore_playlist", "POST /api/playlists/{playlist_id}/restore", "Restore a playlist", "Bring back a deleted playlist, within the undo window.",
        _playlist_tool("restore", {}, {}), schema({"playlist_id": PLAYLIST_ID, "user_id": USER}, ("playlist_id",)),
    )
    add(
        "add_to_playlist", "POST /api/playlists/{playlist_id}/add", "Add to a playlist",
        "Add titles at position (the end by default); the rest renumber. Returns the items before, which set_playlist_items takes back.",
        _playlist_tool("add", {"title_ids": list}, {"position": int}), schema({"playlist_id": PLAYLIST_ID, "title_ids": TITLE_IDS, "position": position, "user_id": USER}, ("playlist_id", "title_ids")),
    )
    add(
        "remove_from_playlist", "POST /api/playlists/{playlist_id}/remove", "Remove from a playlist",
        "Take titles off a playlist; the rest renumber. Returns the items before, which set_playlist_items takes back.",
        _playlist_tool("remove", {"title_ids": list}, {}), schema({"playlist_id": PLAYLIST_ID, "title_ids": TITLE_IDS, "user_id": USER}, ("playlist_id", "title_ids")),
    )
    add(
        "move_in_playlist", "POST /api/playlists/{playlist_id}/move", "Move within a playlist",
        "Move one title to position; the rest renumber. Returns the items before, which set_playlist_items takes back.",
        _playlist_tool("move", {"title_id": str, "position": int}, {}), schema({"playlist_id": PLAYLIST_ID, "title_id": TITLE_ID, "position": position, "user_id": USER}, ("playlist_id", "title_id", "position")),
    )
    add(
        "set_playlist_items", "POST /api/playlists/{playlist_id}/set", "Set a playlist's titles",
        "Replace a playlist's titles with items, in order -- the undo of add, remove and move. Returns the items before.",
        _playlist_tool("set", {"items": list}, {}), schema({"playlist_id": PLAYLIST_ID, "items": TITLE_IDS, "user_id": USER}, ("playlist_id", "items")),
    )

    # Saved views and prefs.
    add("list_views", "GET /api/views", "Saved views", "A person's saved views: a named query on the library or Discover screen, in their order.", list_views, schema({"user_id": USER}), read_only=True)
    add("create_view", "POST /api/views", "Save a view", "Save a named view of a screen.", create_view, schema({**VIEW_FIELDS, "user_id": USER}, ("name",)))
    add("reorder_views", "POST /api/views/reorder", "Order views", "Put the saved views in this order (ids: view ids, first to last).", reorder_views, schema({"ids": {"type": "array", "items": {"type": "integer"}}, "user_id": USER}, ("ids",)))
    add(
        "update_view", "POST /api/views/{view_id}/update", "Change a view", "Change a saved view's name, query, card layout or icon. Returns the previous values.",
        _view_tool("update", VIEW_TYPES), schema({"view_id": VIEW_ID, **VIEW_FIELDS, "user_id": USER}, ("view_id",)),
    )
    add(
        "delete_view", "POST /api/views/{view_id}/delete", "Delete a view", "Delete a saved view. Soft: restore_view brings it back within the undo window.",
        _view_tool("delete", {}), schema({"view_id": VIEW_ID, "user_id": USER}, ("view_id",)), destructive=True,
    )
    add("restore_view", "POST /api/views/{view_id}/restore", "Restore a view", "Bring back a deleted saved view, within the undo window.", _view_tool("restore", {}), schema({"view_id": VIEW_ID, "user_id": USER}, ("view_id",)))
    add("get_prefs", "GET /api/prefs", "Settings", "A person's settings that follow them between devices: cards (layout per screen), last_query, default_view and ui.", get_prefs, schema({"user_id": USER}), read_only=True)
    add(
        "save_prefs", "POST /api/prefs", "Change settings",
        "Change settings by section (cards, last_query, default_view, ui): each key given replaces that key within its section, and null removes it. Returns them all.",
        save_prefs, schema({**{section: {"type": "object"} for section in prefs.SECTIONS}, "user_id": USER}),
    )

    # Media types and sources.
    add("list_types", "GET /api/types", "Media types", "The library's sections (Movies, TV, and any the family added), in order.", list_types, read_only=True)
    add("save_type", "POST /api/types", "Add or change a type", "Create a media type, or change one by its id. Movies and TV keep their lookup.", save_type, schema(TYPE_FIELDS, ("id", "label")))
    add(
        "delete_type", "POST /api/types/{type_id}/delete", "Delete a type",
        "Delete a media type. One that still holds titles needs reassign_to, the type they move to. Movies and TV cannot be deleted. Soft: restore_type brings it back.",
        delete_type, schema({"type_id": {"type": "string"}, "reassign_to": {"type": "string"}}, ("type_id",)), destructive=True,
    )
    add("restore_type", "POST /api/types/{type_id}/restore", "Restore a type", "Bring back a deleted media type, within the undo window.", restore_type, schema({"type_id": {"type": "string"}}, ("type_id",)))
    add("list_sources", "GET /api/sources", "Sources", "The lists and pages titles were found on, newest first.", list_sources, read_only=True)
    add("create_source", "POST /api/sources", "Add a source", "Remember a list or page titles were found on.", create_source, schema(SOURCE_FIELDS, ("url",)))
    add(
        "update_source", "POST /api/sources/{source_id}/update", "Change a source", "Change a source's link, title, note or tags. Returns the previous values.",
        update_source, schema({"source_id": {"type": "string"}, **SOURCE_FIELDS}, ("source_id",)),
    )
    add(
        "delete_source", "POST /api/sources/{source_id}/delete", "Delete a source", "Delete a source. Soft: restore_source brings it back within the undo window.",
        delete_source, schema({"source_id": {"type": "string"}}, ("source_id",)), destructive=True,
    )
    add("restore_source", "POST /api/sources/{source_id}/restore", "Restore a source", "Bring back a deleted source, within the undo window.", restore_source, schema({"source_id": {"type": "string"}}, ("source_id",)))
