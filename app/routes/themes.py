"""The Appearance screen's routes: someone's own themes, and the defaults an
admin sets for everyone who has not made their own. See app/models/themes.py.
Each save sends the whole list, so an undo is the same call with the list from
before."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logs import KIND_ADMIN, KIND_AUTH
from app.core.security import actor_from, check_csrf
from app.models import themes, users
from app.routes.helpers import bad_request, forbidden, get_store, read_json, run, server_error
from app.routes.logs import audit


async def set_my_themes(request: Request) -> Response:
    """Replaces the caller's own list and pick. themes null (or left out) goes
    back to following the defaults."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    store = get_store(request)
    user_id = actor_from(request).user.id
    try:
        found = await run(themes.set_user_themes, store, user_id, body.get("themes"), body.get("theme_id"))
    except themes.ThemesError as invalid:
        return bad_request(str(invalid))
    if not found:
        return server_error(request, "themes: the signed-in account has no record")
    user = await run(users.get_user, store, user_id)
    listed, custom = await run(themes.mine, store, user.themes if user else None)
    audit(request, KIND_AUTH, "changed own themes", {"count": len(body.get("themes") or []), "custom": custom})
    return JSONResponse({"ok": True, "themes": listed, "themes_custom": custom, "theme_id": user.theme_id if user else ""})


async def set_my_theme(request: Request) -> Response:
    """Changes only which theme the caller uses."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    try:
        found = await run(themes.set_user_theme_id, get_store(request), actor_from(request).user.id, body.get("theme_id"))
    except themes.ThemesError as invalid:
        return bad_request(str(invalid))
    if not found:
        return server_error(request, "themes: the signed-in account has no record")
    return JSONResponse({"ok": True, "theme_id": body.get("theme_id") or ""})


async def get_theme_defaults(request: Request) -> Response:
    """themes is null while the built-in ones apply."""
    return JSONResponse({"themes": await run(themes.get_defaults, get_store(request))})


async def set_theme_defaults(request: Request) -> Response:
    """Replaces the list everyone without their own list sees. null goes back
    to the built-in themes."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    try:
        saved = await run(themes.set_defaults, get_store(request), body.get("themes"))
    except themes.ThemesError as invalid:
        return bad_request(str(invalid))
    audit(request, KIND_ADMIN, "changed the default themes", {"count": len(saved or []), "built_in": saved is None})
    return JSONResponse({"ok": True, "themes": saved})
