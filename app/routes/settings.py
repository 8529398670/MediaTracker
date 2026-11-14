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

from typing import Annotated, Any, ClassVar

import msgspec
from msgspec import Meta
from starlette.requests import Request

from app.apidocs import OWNER, Reply, route
from app.apidocs import Request as RequestType
from app.core import config_live
from app.core.config import ValidationError
from app.core.logs import KIND_ADMIN
from app.core.yaml_edit import HandEditError
from app.routes.admin import DateTime
from app.routes.helpers import Refused
from app.routes.helpers import get_settings as holder
from app.routes.logs import audit


class SettingsError(Reply):
    """Why config.yaml on disk is not what is running."""

    message: str
    at: DateTime
    origin: str


class SettingKey(Reply):
    key: str
    name: str
    type: str
    value: Any
    default: Any
    in_file: bool
    help: str
    apply: str
    pending_restart: bool
    running: Any
    locked: bool
    file_only: Annotated[bool, Meta(description="A path: change it in config.yaml, never here.")]


class SettingsSection(Reply):
    name: str
    help: str
    keys: list[SettingKey]


class SettingsSnapshot(Reply):
    """config_live.Holder.snapshot, as the Settings screen reads it."""

    api_name: ClassVar[str] = "SettingsSnapshot"
    file: str
    secret_file: str
    version: Annotated[str, Meta(description="Send it back when saving: a changed file is refused with a 409.")]
    writable: bool
    stale: bool
    in_container: bool
    error: SettingsError | None
    sections: list[SettingsSection]


class SettingsResult(Reply):
    """What a save changed (config_live.Holder.save)."""

    api_name: ClassVar[str] = "SettingsResult"
    changes: list[dict[str, Any]] | None
    applied: list[str] | None
    restart: list[str] | None
    scripts: list[str] | None
    unchanged: list[str] | None
    version: str


@route(
    "GET /api/owner/settings", summary="config.yaml, as a form",
    tag="Owner", role=OWNER, feature="settings",
)
def get_settings(request: Request) -> SettingsSnapshot:
    return msgspec.convert(holder(request).snapshot(), SettingsSnapshot)


class SaveSettings(RequestType):
    version: str
    changes: Annotated[dict[str, Any], Meta(description="Setting paths and their new values.", extra={"error": "malformed request body"})]


@route(
    "POST /api/owner/settings", summary="Save settings",
    tag="Owner", role=OWNER, feature="settings", errors=(409,),
)
def save_settings(request: Request, body: SaveSettings) -> SettingsResult:
    """Apply {version, changes: {"section.key": value}}. version is the one
    get_settings returned; a file changed since is a 409 with the current
    version, so the page can offer to reload rather than overwrite."""
    try:
        result = holder(request).save(body.version, body.changes)
    except config_live.ConflictError as changed:
        raise Refused(409, "settings_changed", version=changed.version) from None
    except config_live.StaleError:
        raise Refused(409, "settings_stale") from None
    except config_live.ReadOnlyError:
        raise Refused(409, "settings_read_only") from None
    except config_live.FileOnlyError:
        raise Refused(403, "settings_file_only") from None
    except config_live.LockedError:
        raise Refused(403, "settings_locked") from None
    except config_live.UnknownSettingError as unknown:
        raise Refused(400, "unknown_setting", key=unknown.key) from None
    except HandEditError as refusal:
        raise Refused(400, "settings_hand_edit", problems=[str(refusal)]) from None
    except ValidationError as invalid:
        raise Refused(400, "invalid_settings", problems=invalid.problems) from None
    if result["changes"]:
        audit(request, KIND_ADMIN, "settings changed", {
            "changes": result["changes"],
            "restart": result["restart"],
            "scripts": result["scripts"],
        })
    return msgspec.convert(result, SettingsResult)
