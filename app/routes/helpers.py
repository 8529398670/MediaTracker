"""Small pieces every route module uses: the shared dependencies, the one
error shape, and the rule for calling synchronous code.

The rule: SQLite and bcrypt are synchronous, and an async handler that calls
them directly stalls every other request while it waits. A plain-function
@route handler already runs in a worker thread and calls the models directly;
an async one reaches them through `await run(...)`, which runs the call in a
worker thread.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from msgspec import Meta

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.apidocs.route import QUERY, Reply, Request as RequestType
from app.core.config import Config
from app.core.config_live import Holder
from app.core.db import Store
from app.core.middleware import internal_error
from app.models import RestoreError, RestoreForbiddenError, RestoreGoneError, RestoreOutrankedError
from app.models.users import OwnerProtectedError, OwnerRequiredError

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
# only ever holds a page of it. See Page, sorted_page and match_rows.
PAGE_DEFAULT = 200
PAGE_MAX = 1000
PAGE_LIMIT_MESSAGE = "limit must be 1-1000"
PAGE_OFFSET_MESSAGE = "offset must be 0 or more"


# A date and time, as ISO text in UTC.
DateTime = Annotated[str, Meta(extra_json_schema={"format": "date-time"})]


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_settings(request: Request) -> Holder:
    return request.app.state.settings


def get_config(request: Request) -> Config:
    """The running configuration. config.yaml can change while the server
    runs (see app/core/config_live.py), so read it once per request and use
    that copy throughout -- never keep one from an earlier request."""
    return request.app.state.settings.get()


def field_of(row: Any, name: str) -> Any:
    """A row's field: a dict's key or a Struct's attribute."""
    return row.get(name) if isinstance(row, dict) else getattr(row, name, None)


def match_rows(rows: list[Any], query: str, *fields: str) -> list[Any]:
    """The rows with query in one of fields, in any case. An empty query keeps
    them all. Here rather than in the browser, like sorting."""
    wanted = query.strip().lower()
    if not wanted:
        return rows
    return [row for row in rows if any(isinstance(field_of(row, field), str) and wanted in field_of(row, field).lower() for field in fields)]


def sort_rows(rows: list[dict[str, Any]], field: str, descending: bool) -> list[dict[str, Any]]:
    """Order rows by one field. Rows without it go last whichever way the list
    runs, because "never used" is not the oldest date. Rows that tie stay in
    the list's own order, so a page holds still. Dates are ISO text in UTC,
    which sorts as they read."""

    def value(row: Any) -> Any:
        found = field_of(row, field)
        return found.lower() if isinstance(found, str) else found

    present = [row for row in rows if field_of(row, field) not in (None, "")]
    absent = [row for row in rows if field_of(row, field) in (None, "")]
    return sorted(present, key=value, reverse=descending) + absent


# Page's two fields, for a request that cannot take Page as its base because
# it already has one (a path type): limit: Limit = PAGE_DEFAULT, offset:
# Offset = 0, written where Go embeds Page.
Limit = Annotated[int, QUERY, Meta(ge=1, le=PAGE_MAX, description="Rows to return. Default 200.", extra={"error": PAGE_LIMIT_MESSAGE})]
Offset = Annotated[int, QUERY, Meta(ge=0, description="Rows to skip: the next value of the previous page.", extra={"error": PAGE_OFFSET_MESSAGE})]


class Page(RequestType):
    """The query every paged list takes, and an MCP list tool's arguments."""

    limit: Limit = PAGE_DEFAULT
    offset: Offset = 0


# The ?dir= of a list a screen can sort, declared last on its request, after
# the list's own sort field: dir: Dir = "".
Dir = Annotated[Literal["asc", "desc"], QUERY, Meta(description="Default asc.", extra={"error": "dir must be asc or desc"})]


class Paged(Reply):
    """What every paged reply carries beside its rows."""

    next: Annotated[int | None, Meta(description="Offset of the next page, or null on the last one.")]
    total: int


def cut_page(rows: list[Any], page: Page) -> dict[str, Any]:
    """One page of rows, which must already be in their final order: the
    rows, next and total, for a reply's constructor."""
    total = len(rows)
    start = min(page.offset, total)
    end = min(start + page.limit, total)
    return {"rows": rows[start:end], "next": end if end < total else None, "total": total}


def sorted_page(rows: list[Any], field: str, direction: str, page: Page) -> dict[str, Any]:
    """cut_page for a list a screen can sort: field is a row field by name,
    already checked against the route's sort Literal."""
    if field:
        rows = sort_rows(rows, field, direction == "desc")
    return cut_page(rows, page)


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
        # Only a 500 is ours to log; a deliberate 503 (MediaTracker's
        # lookups_off) is answered as itself.
        if self.status == 500 and request is not None:
            return server_error(request, self.cause)
        return JSONResponse({"error": self.message, **self.extra}, status_code=self.status)


@contextmanager
def act_on_refusals(what: str) -> Iterator[None]:
    """Turns users.may_act_on_tx's refusals into the 403 every account route
    gives, with the same wording. what is the action, worded to follow
    "cannot": "reissue a login link for"."""
    try:
        yield
    except OwnerProtectedError:
        raise Refused(403, f"nobody can {what} the owner account") from None
    except OwnerRequiredError:
        raise Refused(403, f"only the owner can {what} an admin account") from None


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def bad_request(message: str) -> JSONResponse:
    return error(400, message)


def forbidden(message: str) -> JSONResponse:
    return error(403, message)


def not_found(message: str) -> JSONResponse:
    return error(404, message)


def restore_refusal(refusal: RestoreError) -> Refused:
    """The refusal for each way a restore can be refused."""
    if isinstance(refusal, RestoreGoneError):
        return Refused(404, str(refusal))
    if isinstance(refusal, (RestoreForbiddenError, RestoreOutrankedError)):
        return Refused(403, str(refusal))
    return Refused(409, str(refusal))


def server_error(request: Request, cause: object) -> JSONResponse:
    """A 500 a handler decided on. cause says why: it is what the log line
    shows, and the client never sees it."""
    return internal_error(request, cause)
