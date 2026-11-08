"""The owner's Settings screen: config.yaml, one field per key (see
static/js/settings.js). Both routes are the owner's alone, from a browser
session (RequireOwner, in app/routes/__init__.py), like the activity log.

What is shown and saved comes from config_live.Holder, which owns the file:
get_settings is Holder.snapshot, save_settings is Holder.save. The secret key
is never part of either -- it is not in config.yaml, and the screen only says
where secret.key is.

server/routes/settings.go is the same for the Go template.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import config_live
from app.core.config import ValidationError
from app.core.logs import KIND_ADMIN
from app.core.security import check_csrf
from app.core.yaml_edit import HandEditError
from app.routes.helpers import bad_request, conflict, forbidden, read_json, run
from app.routes.helpers import get_settings as holder
from app.routes.logs import audit


async def get_settings(request: Request) -> Response:
    return JSONResponse(await run(holder(request).snapshot))


async def save_settings(request: Request) -> Response:
    """Apply {version, changes: {"section.key": value}}. version is the one
    get_settings returned; a file changed since is a 409 with the current
    version, so the page can offer to reload rather than overwrite."""
    body = await read_json(request)
    if body is None or not isinstance(body.get("changes"), dict):
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    try:
        result = await run(holder(request).save, str(body.get("version") or ""), body["changes"])
    except config_live.ConflictError as changed:
        return conflict("settings_changed", version=changed.version)
    except config_live.StaleError:
        return conflict("settings_stale")
    except config_live.ReadOnlyError:
        return conflict("settings_read_only")
    except config_live.LockedError:
        return forbidden("settings_locked")
    except config_live.UnknownSettingError as unknown:
        return JSONResponse({"error": "unknown_setting", "key": unknown.key}, status_code=400)
    except HandEditError as refusal:
        return JSONResponse({"error": "settings_hand_edit", "problems": [str(refusal)]}, status_code=400)
    except ValidationError as invalid:
        return JSONResponse({"error": "invalid_settings", "problems": invalid.problems}, status_code=400)
    if result["changes"]:
        audit(request, KIND_ADMIN, "settings changed", {
            "changes": result["changes"],
            "restart": result["restart"],
            "scripts": result["scripts"],
        })
    return JSONResponse(result)

