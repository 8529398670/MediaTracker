"""The Appearance screen's routes: someone's own themes, and the defaults an
admin sets for everyone who has not made their own. See app/models/themes.py.
Each save sends the whole list, so an undo is the same call with the list from
before."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logs import KIND_ADMIN, KIND_AUTH
from app.core.security import actor_from, check_csrf
from app.models import themes, users
from app.routes.helpers import Refused, bad_request, forbidden, get_store, read_json, run
from app.routes.logs import audit


async def _body(request: Request) -> dict[str, Any] | Response:
    """The JSON body, or the refusal when it or its csrf token will not do."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    return body


async def _answer(helper: Any, request: Request, *args: Any) -> Response:
    """A shared helper's answer as a response, or its refusal."""
    try:
        return JSONResponse(await run(helper, request, *args))
    except Refused as refused:
        return refused.response(request)


async def set_my_themes(request: Request) -> Response:
    """Replaces the caller's own list and pick. themes null (or left out) goes
    back to following the defaults."""
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await _answer(set_my_themes_checked, request, body.get("themes"), body.get("theme_id"))


def set_my_themes_checked(request: Request, wanted: Any, theme_id: Any) -> dict[str, Any]:
    """set_my_themes after the request is read, for it and the MCP set_themes
    tool."""
    store = get_store(request)
    user_id = actor_from(request).user.id
    try:
        found = themes.set_user_themes(store, user_id, wanted, theme_id)
    except themes.ThemesError as invalid:
        raise Refused(400, str(invalid)) from None
    if not found:
        raise Refused.internal("themes: the signed-in account has no record")
    user = users.get_user(store, user_id)
    listed, custom = themes.mine(store, user.themes if user else None)
    audit(request, KIND_AUTH, "changed own themes", {"count": len(wanted or []), "custom": custom})
    return {"ok": True, "themes": listed, "themes_custom": custom, "theme_id": user.theme_id if user else ""}


async def set_my_theme(request: Request) -> Response:
    """Changes only which theme the caller uses."""
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await _answer(set_my_theme_checked, request, body.get("theme_id"))


def set_my_theme_checked(request: Request, theme_id: Any) -> dict[str, Any]:
    """set_my_theme after the request is read, for it and the MCP set_theme
    tool."""
    try:
        found = themes.set_user_theme_id(get_store(request), actor_from(request).user.id, theme_id)
    except themes.ThemesError as invalid:
        raise Refused(400, str(invalid)) from None
    if not found:
        raise Refused.internal("themes: the signed-in account has no record")
    return {"ok": True, "theme_id": theme_id or ""}


async def get_theme_defaults(request: Request) -> Response:
    """themes is null while the built-in ones apply."""
    return await _answer(theme_defaults, request)


def theme_defaults(request: Request) -> dict[str, Any]:
    """get_theme_defaults, for it and the MCP admin_get_theme_defaults tool."""
    return {"themes": themes.get_defaults(get_store(request))}


async def set_theme_defaults(request: Request) -> Response:
    """Replaces the list everyone without their own list sees. null goes back
    to the built-in themes."""
    body = await _body(request)
    if isinstance(body, Response):
        return body
    return await _answer(set_theme_defaults_checked, request, body.get("themes"))


def set_theme_defaults_checked(request: Request, wanted: Any) -> dict[str, Any]:
    """set_theme_defaults after the request is read, for it and the MCP
    admin_set_theme_defaults tool."""
    try:
        saved = themes.set_defaults(get_store(request), wanted)
    except themes.ThemesError as invalid:
        raise Refused(400, str(invalid)) from None
    audit(request, KIND_ADMIN, "changed the default themes", {"count": len(saved or []), "built_in": saved is None})
    return {"ok": True, "themes": saved}
