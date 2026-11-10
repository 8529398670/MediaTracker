"""Small pieces every route module uses: the shared dependencies, the one
error shape, and the rule for calling synchronous code.

The rule: SQLite and bcrypt are synchronous, and an async handler that calls
them directly stalls every other request while it waits. So handlers reach the
models through `await run(...)`, which runs the call in a worker thread.
"""
from __future__ import annotations

from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import Config
from app.core.config_live import Holder
from app.core.db import Store
from app.core.middleware import internal_error
from app.models import RestoreError, RestoreForbiddenError, RestoreGoneError

run = run_in_threadpool

# Every list the API hands out is paged the same way: ?limit= and ?offset= in,
# and {"<rows>": [...], "next": <offset of the next page, or null>, "total":
# <rows in all>} out.
#
# An offset rather than a cursor, on purpose. Most of these lists sort on a
# field that is encrypted at rest, so every page has to read the whole list
# anyway and a cursor would save nothing; and the natural cursor for a key or
# a session is its record id, which has no business in a URL. The cost is that
# a row deleted between two pages shifts the next one by a row. The screens
# reload from the first page after any change, so they never see that.
#
# Paging here bounds the response, not the read. See Known limits in
# references/architecture.md.
#
# A list a screen can sort also takes ?sort=<field>&dir=asc|desc, and one it can
# search takes ?q=, both on the whole list before it is cut, since the browser
# only ever holds a page of it. See send_page and match_rows.
PAGE_DEFAULT = 200
PAGE_MAX = 1000
PAGE_LIMIT_MESSAGE = "limit must be 1-1000"
PAGE_OFFSET_MESSAGE = "offset must be 0 or more"


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_settings(request: Request) -> Holder:
    return request.app.state.settings


def get_config(request: Request) -> Config:
    """The running configuration. config.yaml can change while the server
    runs (see app/core/config_live.py), so read it once per request and use
    that copy throughout -- never keep one from an earlier request."""
    return request.app.state.settings.get()


async def read_json(request: Request) -> dict[str, Any] | None:
    """The request body as a JSON object, or None if it is not one -- every
    endpoint answers that the same way (bad_request "malformed request
    body")."""
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def whole_number(raw: str | None, default: int) -> int | None:
    """A query parameter as an int: default when it is absent, None when it
    is not a number."""
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return None


def page_body(name: str, rows: list[Any], limit: int, offset: int) -> dict[str, Any]:
    """One page cut out of rows, which must already be in their final order.
    name is the field the rows go under."""
    total = len(rows)
    start = min(offset, total)
    end = min(start + limit, total)
    return {name: rows[start:end], "next": end if end < total else None, "total": total}


def match_rows(rows: list[dict[str, Any]], query: str, *fields: str) -> list[dict[str, Any]]:
    """The rows with query in one of fields, in any case. An empty query keeps
    them all. Here rather than in the browser, like sorting."""
    wanted = query.strip().lower()
    if not wanted:
        return rows
    return [row for row in rows if any(isinstance(row.get(field), str) and wanted in row[field].lower() for field in fields)]


def sort_rows(rows: list[dict[str, Any]], field: str, descending: bool) -> list[dict[str, Any]]:
    """Order rows by one field. Rows without it go last whichever way the list
    runs, because "never used" is not the oldest date. Rows that tie stay in
    the list's own order, so a page holds still. Dates are ISO text in UTC,
    which sorts as they read."""

    def value(row: dict[str, Any]) -> Any:
        found = row[field]
        return found.lower() if isinstance(found, str) else found

    present = [row for row in rows if row.get(field) not in (None, "")]
    absent = [row for row in rows if row.get(field) in (None, "")]
    return sorted(present, key=value, reverse=descending) + absent


def send_page(request: Request, name: str, rows: list[Any], sort_fields: tuple[str, ...] = ()) -> JSONResponse:
    """The answer to a list route: the page its query asks for. sort_fields
    are the row fields a screen may sort it by, and anything else is refused
    rather than ignored, so a typo does not look like a list in its own order."""
    if sort_fields:
        direction = request.query_params.get("dir", "")
        if direction not in ("", "asc", "desc"):
            return bad_request("dir must be asc or desc")
        field = request.query_params.get("sort", "")
        if field:
            if field not in sort_fields:
                return bad_request("sort must be one of: " + ", ".join(sort_fields))
            rows = sort_rows(rows, field, direction == "desc")
    limit = whole_number(request.query_params.get("limit"), PAGE_DEFAULT)
    if limit is None or not 1 <= limit <= PAGE_MAX:
        return bad_request(PAGE_LIMIT_MESSAGE)
    offset = whole_number(request.query_params.get("offset"), 0)
    if offset is None or offset < 0:
        return bad_request(PAGE_OFFSET_MESSAGE)
    return JSONResponse(page_body(name, rows, limit, offset))


# One error shape for the whole API, so the frontend has one thing to handle
# and no handler accidentally leaks internal detail.


class Refused(Exception):
    """A rule saying no, kept apart from how it is delivered: a route sends it
    as a status and an error body (response), an MCP tool as a tool error with
    the same words. A helper both doors call raises it, so the rule is written
    once. extra is more for the caller, such as the current value a 409 was
    about. Refused.internal is a failure on our side: a 500 whose cause goes
    to the log, never to the caller."""

    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status, self.message, self.extra = status, message, extra
        self.cause: object = message

    @classmethod
    def internal(cls, cause: object) -> Refused:
        refused = cls(500, "internal error")
        refused.cause = cause
        return refused

    def response(self, request: Request | None = None) -> JSONResponse:
        if self.status >= 500 and request is not None:
            return server_error(request, self.cause)
        return JSONResponse({"error": self.message, **self.extra}, status_code=self.status)


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def bad_request(message: str) -> JSONResponse:
    return error(400, message)


def forbidden(message: str) -> JSONResponse:
    return error(403, message)


def not_found(message: str) -> JSONResponse:
    return error(404, message)


def conflict(message: str, **extra: Any) -> JSONResponse:
    """409: the request was fine but the record has moved on -- an undo whose
    window has passed, or a rename that expected a name someone else has
    since changed. extra carries the current state, so the caller can show
    it."""
    return JSONResponse({"error": message, **extra}, status_code=409)


def restore_refused(refusal: RestoreError) -> JSONResponse:
    """The answer for each way a restore can be refused."""
    return restore_refusal(refusal).response()


def restore_refusal(refusal: RestoreError) -> Refused:
    """restore_refused for a helper an MCP tool shares."""
    if isinstance(refusal, RestoreGoneError):
        return Refused(404, str(refusal))
    if isinstance(refusal, RestoreForbiddenError):
        return Refused(403, str(refusal))
    return Refused(409, str(refusal))


def server_error(request: Request, cause: object) -> JSONResponse:
    """A 500 a handler decided on. cause says why: it is what the log line
    shows, and the client never sees it."""
    return internal_error(request, cause)


def parse_id(raw: str) -> int | None:
    """A positive integer path parameter, or None."""
    return int(raw) if raw.isascii() and raw.isdigit() and int(raw) > 0 else None
