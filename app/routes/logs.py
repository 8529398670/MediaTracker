"""The activity log's endpoints (see app/core/logs.py). Reading it is the
owner's alone, under /api/owner/logs (RequireOwner); writing to it from the
page -- what track.js sends -- is any signed-in user's, at /api/logs/events,
since what they do is what gets logged. audit() and audit_as() are how the
other route modules write auth and admin entries."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request

import json
import threading
import time
from collections import deque
from starlette.responses import JSONResponse, Response, StreamingResponse

from app.core import logs, request_id, sse
from app.core.config import trusted_proxy_networks
from app.core.middleware import client_ip
from app.core.security import actor_from, check_csrf, decrypt_cookie, log_actor, still_owner
from app.models import users
from app.routes.helpers import PAGE_DEFAULT, PAGE_LIMIT_MESSAGE, PAGE_MAX, bad_request, conflict, error, forbidden, get_config, get_store, read_json, run, whole_number

# Page events a browser may send per call, and per account per minute.
EVENTS_PER_CALL = 50
EVENTS_PER_MINUTE = 600
DETAIL_MAX_BYTES = 2048

# The page actions track.js sends. Anything else is refused, so the log
# cannot be filled with made-up kinds.
UI_ACTIONS = {"session_start", "nav", "click", "submit", "undo", "redo", "error", "fetch_fail"}


def get_logs(request: Request) -> logs.Logger:
    return request.app.state.logs


def _settings(logger: logs.Logger) -> dict[str, Any]:
    current = logger.settings
    return {
        "enabled": current.enabled,
        "retention_days": current.retention_days,
        "max_total_mb": current.max_total_bytes // 1024 // 1024,
        "max_file_mb": current.max_file_bytes // 1024 // 1024,
        "compress_after_days": current.compress_after_days,
        "static_assets": current.static_assets,
        "ui_clicks": current.ui_clicks,
        "encrypted": logger.encrypt,
    }


async def _query(request: Request, text: str = "") -> logs.Query:
    """A search, as reading a day, searching and downloading all need it."""
    return logs.Query(text)


async def list_log_days(request: Request) -> Response:
    logger = get_logs(request)
    days, total = await run(logger.days, await _query(request, request.query_params.get("q", "")))
    return JSONResponse({"days": days, "total_bytes": total, "dropped": logger.dropped, "settings": _settings(logger)})


async def get_log_day(request: Request) -> Response:
    day = request.path_params["date"]
    if not logs.valid_day(day):
        return bad_request("bad_day")
    before = whole_number(request.query_params.get("before"), -1)
    if before is None or (before < 0 and request.query_params.get("before")):
        return bad_request("before must be a line number")
    limit = whole_number(request.query_params.get("limit"), PAGE_DEFAULT)
    if limit is None or not 1 <= limit <= PAGE_MAX:
        return bad_request(PAGE_LIMIT_MESSAGE)
    query = await _query(request, request.query_params.get("q", ""))
    records, following = await run(get_logs(request).read_day, day, query, before, limit)
    return JSONResponse({"date": day, "entries": records, "next": following})


async def download_log_day(request: Request) -> Response:
    """A day as plain JSON lines, decrypted: the file a person can grep, or
    hand to whatever reads logs. Starlette walks the generator in a worker
    thread, so the file reads stay off the event loop."""
    day = request.path_params["date"]
    if not logs.valid_day(day):
        return bad_request("bad_day")
    return StreamingResponse(
        get_logs(request).download(day, await _query(request)),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="logs-{day}.jsonl"'},
    )


async def delete_log_day(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    day = request.path_params["date"]
    try:
        await run(get_logs(request).delete_day, day)
    except logs.BadDayError as refusal:
        return bad_request(str(refusal))
    except logs.TodayError as refusal:
        return conflict(str(refusal))
    audit(request, logs.KIND_ADMIN, "log day deleted", {"date": day})
    return JSONResponse({"deleted": True})


async def prune_logs(request: Request) -> Response:
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    result = await run(get_logs(request).prune)
    audit(request, logs.KIND_ADMIN, "logs pruned", {"compressed": result["compressed"], "deleted": result["deleted"]})
    return JSONResponse(result)


async def stream_log_changes(request: Request) -> Response:
    """The Logs screen's live tail: "something changed" nudges, and logs.js
    runs its normal refresh. Sending the entries themselves would need a
    second filter and paging path through the same data. This route is under
    /api/owner/logs, so RequestLog skips it and the stream cannot feed itself.

    RequireOwner let this in once. The cookie is kept to ask again every tick,
    because the session can end while the stream stays open."""
    if request.method == "HEAD":
        return Response(headers=sse.HEADERS)
    cfg, store = get_config(request), get_store(request)
    credential = decrypt_cookie(cfg, request.cookies.get(cfg.cookie_name, ""))
    hub: sse.Hub = request.app.state.log_hub
    client = hub.join()
    if client is None:
        return error(503, "too many live streams")

    async def allowed() -> bool:
        return await run(still_owner, store, credential)

    return sse.EventStream(hub, client, allowed, opening=(sse.retry(sse.RETRY_MS), sse.CHANGED))


class _EventBudget:
    """The per-account cap on page events: a minute's worth, in a sliding
    window, so a stuck loop in a browser cannot fill the disk."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[int, deque[float]] = {}

    def take(self, user_id: int, wanted: int) -> int:
        with self._lock:
            now = time.monotonic()
            recent = self._seen.setdefault(user_id, deque())
            while recent and now - recent[0] >= 60:
                recent.popleft()
            allowed = max(0, min(wanted, EVENTS_PER_MINUTE - len(recent)))
            recent.extend([now] * allowed)
            if not recent:
                del self._seen[user_id]
            return allowed


_budget = _EventBudget()


def _cap_fields(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [logs.truncate(field, 60) for field in value[:30] if isinstance(field, str)]


def _cap_map(value: Any) -> dict[str, Any]:
    """A browser-sent object, kept only if it is small, with its strings
    capped. Too big, and it is dropped whole rather than cut mid-structure."""
    if not isinstance(value, dict) or not value:
        return {}
    capped = {str(name): logs.truncate(item, 200) if isinstance(item, str) else item for name, item in value.items()}
    try:
        encoded = json.dumps(capped)
    except (TypeError, ValueError):
        return {}
    return capped if len(encoded.encode("utf-8")) <= DETAIL_MAX_BYTES else {}


def _ip(request: Request) -> str:
    cfg = get_config(request)
    return client_ip(request.scope, cfg, trusted_proxy_networks(cfg))


async def record_ui_events(request: Request) -> Response:
    """A batch from track.js. The server stamps each with its own time, the
    signed-in account, the address and the user agent, so a browser can
    describe what it did but not who did it or when it arrived."""
    body = await read_json(request)
    if body is None:
        return bad_request("malformed request body")
    if not check_csrf(request, body.get("csrf_token")):
        return forbidden("invalid csrf token")
    events = body.get("events")
    if not isinstance(events, list):
        return bad_request("events must be a list")
    events = events[:EVENTS_PER_CALL]
    actor = actor_from(request)
    allowed = _budget.take(actor.user.id, len(events))
    logger = get_logs(request)
    tab = logs.truncate(body.get("tab", ""), 32)
    who, ip, ua = log_actor(actor), _ip(request), logs.truncate(request.headers.get("user-agent", ""), 300)
    accepted = 0
    for index, event in enumerate(events):
        if index >= allowed or not isinstance(event, dict) or event.get("action") not in UI_ACTIONS:
            continue
        action = event["action"]
        ui = {
            "action": action,
            "screen": logs.truncate(event.get("screen", ""), 120),
            "target": logs.truncate(event.get("target", ""), 120),
            "fields": _cap_fields(event.get("fields")),
            "detail": _cap_map(event.get("detail")),
            "at": logs.truncate(event.get("at", ""), 40),
        }
        client: dict[str, Any] = {"tab": tab}
        if action == "session_start":
            client.update(_cap_map(event.get("client")))
        level = logs.LEVEL_ERROR if action in ("error", "fetch_fail") else logs.LEVEL_INFO
        logger.log(
            logs.entry(
                logs.KIND_UI,
                level,
                actor=who,
                ip=ip,
                ua=ua,
                ui={name: value for name, value in ui.items() if value not in ("", [], {})},
                client=client,
            )
        )
        accepted += 1
    return JSONResponse({"accepted": accepted})


# ---------------------------------------------------------------------------
# audit entries, for the other route modules
# ---------------------------------------------------------------------------


def audit(request: Request, kind: str, message: str, detail: dict[str, Any] | None = None) -> None:
    """Log an auth or admin action by whoever made this request. detail says
    what it touched: ids and names, never a credential. Never blocks."""
    audit_as(request, log_actor(actor_from(request)), kind, logs.LEVEL_INFO, message, detail)


def audit_as(
    request: Request, actor: dict[str, Any], kind: str, level: str, message: str, detail: dict[str, Any] | None = None
) -> None:
    """audit for a request whose actor is not the signed-in one: a sign-in
    (nobody yet), or a failed one."""
    logger = get_logs(request)
    if not logger.enabled:
        return
    logger.log(
        logs.entry(
            kind,
            level,
            request_id=request_id.of(request.scope),
            actor=actor,
            ip=_ip(request),
            ua=logs.truncate(request.headers.get("user-agent", ""), 300),
            msg=message,
            detail=detail,
        )
    )


def user_actor(store: Any, user_id: int, method: str) -> dict[str, Any]:
    """The actor for an account named by id, for an entry made before the
    request has an actor of its own. Reads SQLite: call it through run()."""
    actor: dict[str, Any] = {"user_id": user_id, "method": method}
    user = users.get_user(store, user_id)
    if user is not None:
        actor["name"] = user.display_name
        actor["role"] = user.role
    return actor
