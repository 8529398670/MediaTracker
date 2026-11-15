"""Bulk routes. bulk=True in a route's @route(...) gives it a second route,
POST /api/bulk/... (the path less its {params}), that runs the route's own
handler once per item, so one request changes many things:

    {"items": [{"user_id": 3}, {"user_id": 7, "disabled": false}],
     "shared": {"disabled": true}}

An item is the route's request as an MCP tool takes it, URL fields and all.
shared holds body fields every item gets unless it sets its own. Each item is
checked and run as the route would check and run it, in order, one at a time,
so the rules, the audit log and the webhooks are the route's, item by item.
One failing does not stop the rest, and nothing is undone: the reply
(BulkReply) says how each went. The MCP tool <tool>_bulk is the same thing
through /mcp.

Go's server/apidoc/bulk.go is the same, word for word: the two templates
answer and document bulk routes identically.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from typing import Annotated, Any, ClassVar

import msgspec
from msgspec import UNSET, Meta, UnsetType
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request as HTTPRequest
from starlette.responses import Response

from app.apidocs.route import Declared, InputType, PARAMETER, Reply, reply_response, resolve_all

# How many items one bulk request may hold.
BULK_MAX_ITEMS = 100

# The words the bulk shapes are documented with, the same in both templates.
ITEMS_DOC = "One entry per thing to change: its id, and any field that differs from shared."
SHARED_DOC = "Fields every item gets, unless the item sets its own."
CSRF_PROPERTY = {"type": "string", "description": "From GET /api/me. Browser sessions only."}


class BulkResult(Reply, kw_only=True, omit_defaults=True):
    """How one item went."""

    api_name: ClassVar[str] = "BulkResult"
    index: Annotated[int, Meta(description="The item's place in items, from 0.")]
    ok: bool
    status: Annotated[int, Meta(description="When it failed: the status the route would have answered.")] | UnsetType = UNSET
    error: Annotated[str, Meta(description="When it failed: the route's words for why.")] | UnsetType = UNSET
    request_id: Annotated[str, Meta(description="On a 5xx: the reference that finds this failure in the log.")] | UnsetType = UNSET
    reply: Annotated[dict[str, Any], Meta(description="When it worked: the route's own reply, if it has one.")] | UnsetType = UNSET


class BulkReply(Reply, kw_only=True):
    """What a bulk route answers once its request is sound."""

    api_name: ClassVar[str] = "BulkReply"
    done: Annotated[int, Meta(description="How many items worked.")]
    failed: Annotated[int, Meta(description="How many did not.")]
    results: Annotated[list[BulkResult], Meta(description="One per item, in the order they were sent.")]


def bulk_path(path: str, given: str) -> str:
    """Where a route's bulk version goes: given, or the path with /api/ made
    /api/bulk/ and its {params} left out. "" when there is no such place."""
    if given:
        return given
    if not path.startswith("/api/"):
        return ""
    kept = [part for part in path[len("/api/"):].split("/") if not PARAMETER.fullmatch(part)]
    return "/api/bulk/" + "/".join(kept)


def check_bulk(declared: Declared, given_path: str) -> str:
    """The bulk route's path, or TypeError for a route that cannot have one:
    the generator's checks in server/apidoc/routegen."""
    where = f"@route(\"{declared.method} {declared.path}\")"
    op = declared.op
    if declared.method == "GET":
        raise TypeError(f"{where}: bulk=True: a bulk route changes things, so not for a GET")
    if op.reply_type:
        raise TypeError(f"{where}: bulk=True: it writes its own reply; a bulk route needs a JSON one per item")
    if op.raw_body is not None or op.body_type:
        raise TypeError(f"{where}: bulk=True: the route reads its own body; a bulk route needs a JSON one")
    if not any(item.place == "path" for item in declared.input.fields):
        raise TypeError(f"{where}: bulk=True: the route's path has no {{id}} for each item to name")
    if declared.tool and "call" in declared.tool:
        raise TypeError(f"{where}: bulk=True: its tool has call=, and a bulk tool runs the route's handler as it is")
    path = bulk_path(declared.path, given_path)
    if not path:
        raise TypeError(f"{where}: bulk=True: the path does not start /api/: give bulk_path=")
    if not path.startswith("/") or any(char in path for char in "{}:*"):
        raise TypeError(f"{where}: bulk=True: bulk_path={path!r} is a path with no parameters")
    return path


def bulk_declared(single: Declared, path: str) -> Declared:
    """The bulk route of single: its guards, its words made the bulk's, its
    own status and errors left to each item."""
    key = f"{single.method} {single.path}"
    op = replace(
        single.op,
        summary=single.op.summary + ", for many at once" if single.op.summary else "",
        description=(
            f"Runs {key} once per item: items holds each one's id and fields, shared the fields they have in common "
            "(an item's own win). Each runs as that route would, in order, and one failing does not stop the rest; the "
            "reply says how each went. At most 100 items."
        ),
        status=200, errors=(), reply_description="", bulk_of=key,
    )
    tool = None
    if single.tool:
        tool = {name: value for name, value in single.tool.items() if name not in ("mcp_note", "mcp_title", "mcp_description")}
        name = single.tool["name"]
        admin_only = single.tool.get("admin_only", single.op.role == "admin")
        title = single.tool.get("mcp_title", "") or single.op.summary
        title += ", for many at once" + (" (admin)" if admin_only else "")
        tool.update(
            name=f"{name}_bulk", mcp_title=title,
            mcp_description=(
                f"Runs {name} once per item: items holds each call's arguments, shared the arguments they have in common "
                "(an item's own win). In order; one failing does not stop the rest, and the reply says how each went. "
                "At most 100 items."
            ),
        )
    found = Declared(op, single.handler, single.input, BulkReply, single.takes_input, method="POST", path=path,
                     use=single.use, no_switch=single.no_switch, tool=tool, bulk_of=single)

    async def endpoint(request: HTTPRequest) -> Response:
        return await handle_bulk(found, request)

    endpoint.__declared__ = found  # type: ignore[attr-defined]
    endpoint.__qualname__ = f"{single.handler.__qualname__} (bulk)"
    endpoint.__module__ = single.handler.__module__
    found.endpoint = endpoint
    return found


def bulk_input(input_type: InputType, values: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], str, bool]:
    """A bulk body's own shape checked: items, 1 to BULK_MAX_ITEMS objects,
    and shared, an object of the route's body fields. (items, shared, the
    400 message or "", whether it is a fault in the shape)."""
    unknown = sorted(name for name in values if name not in ("items", "shared"))
    if unknown:
        return [], {}, f"unknown field: {unknown[0]}", True
    if "items" not in values:
        return [], {}, "items is required", False
    items = values["items"]
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        return [], {}, "malformed request body", True
    if not 1 <= len(items) <= BULK_MAX_ITEMS:
        return [], {}, f"items must hold 1 to {BULK_MAX_ITEMS} entries", False
    shared = values.get("shared", {})
    if not isinstance(shared, dict):
        return [], {}, "malformed request body", True
    body_fields = {item.name for item in input_type.fields if not item.place}
    unknown = sorted(name for name in shared if name not in body_fields)
    if unknown:
        return [], {}, f"unknown field: shared.{unknown[0]}", True
    return items, shared, "", False


def run_bulk(declared: Declared, request: Any, items: list[dict[str, Any]], shared: dict[str, Any]) -> BulkReply:
    """Every item through the route's handler, in order: shared under the
    item, checked as an MCP tool's arguments are, then served. A plain
    function, run in a worker thread."""
    from app.routes.helpers import Refused

    results: list[BulkResult] = []
    for index, item in enumerate(items):
        body, message, _ = declared.input.decode({**shared, **item}, strict_places=True)
        if message:
            results.append(BulkResult(index=index, ok=False, status=400, error=message))
            continue
        try:
            reply = declared.serve(request, body)
        except Refused as refused:
            if refused.status < 500:
                results.append(BulkResult(index=index, ok=False, status=refused.status, error=refused.message))
                continue
            results.append(failure(request, index, refused.cause))
            continue
        except Exception as error:  # noqa: BLE001  (one item's crash is that item's failure)
            results.append(failure(request, index, repr(error)))
            continue
        result = BulkResult(index=index, ok=True)
        if reply is not None and not isinstance(reply, Response):
            built = msgspec.to_builtins(reply)
            if isinstance(built, dict):
                result.reply = built
        results.append(result)
    done = sum(1 for result in results if result.ok)
    return BulkReply(done=done, failed=len(results) - done, results=results)


def failure(request: Any, index: int, cause: object) -> BulkResult:
    """An item that failed on our side, logged the way a request is, with
    the reference that finds it."""
    from app.core import logs, request_id

    reference = request_id.of(request.scope)
    print(f"[error] {reference} {request.method} {logs.redact(request.url.path)} (bulk item): {cause}", file=sys.stderr, flush=True)
    return BulkResult(index=index, ok=False, status=500, error="internal error", request_id=reference)


async def handle_bulk(declared: Declared, request: HTTPRequest) -> Response:
    from app.apidocs import PUBLIC
    from app.core.security import check_csrf
    from app.routes.helpers import bad_request, forbidden

    values: Any = {}
    raw = (await request.body()).strip()
    if raw:
        try:
            values = msgspec.json.decode(raw)
        except msgspec.DecodeError:
            return bad_request("malformed request body")
        if not isinstance(values, dict):
            return bad_request("malformed request body")
    token = values.pop("csrf_token", None)
    if declared.op.access != PUBLIC and not declared.op.no_csrf and not check_csrf(request, token):
        return forbidden("invalid csrf token")
    items, shared, message, _ = bulk_input(declared.input, values)
    if message:
        return bad_request(message)
    reply = await run_in_threadpool(run_bulk, declared, request, items, shared)
    return reply_response(reply)


def call_bulk(declared: Declared, request: Any, args: Any) -> tuple[BulkReply | None, str, bool]:
    """A bulk route for its MCP tool: the arguments checked as the route
    checks a body, then every item run."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, "malformed request body", True
    items, shared, message, malformed = bulk_input(declared.input, dict(args))
    if message:
        return None, message, malformed
    return run_bulk(declared, request, items, shared), "", False


def bulk_schema(input_type: InputType, property: Any, csrf: bool) -> dict[str, Any]:
    """A bulk route's body: items, each the route's arguments with only its
    path fields required, and shared, its body fields."""
    item_properties = {item.name: property(item) for item in input_type.fields}
    shared_properties = {item.name: property(item) for item in input_type.fields if not item.place}
    item_schema: dict[str, Any] = {"type": "object", "properties": item_properties, "additionalProperties": False}
    required = sorted(item.name for item in input_type.fields if item.place == "path")
    if required:
        item_schema["required"] = required
    properties: dict[str, Any] = {
        "items": {"type": "array", "items": item_schema, "minItems": 1, "maxItems": BULK_MAX_ITEMS, "description": ITEMS_DOC},
        "shared": {"type": "object", "properties": shared_properties, "additionalProperties": False, "description": SHARED_DOC},
    }
    if csrf:
        properties["csrf_token"] = CSRF_PROPERTY
    return {"type": "object", "properties": properties, "required": ["items"], "additionalProperties": False}


def bulk_body_schema(builder: Any, declared: Declared) -> dict[str, Any]:
    """A bulk route's body as config/api.json writes it."""
    from app.apidocs import PUBLIC
    from app.apidocs.reflect import reflected

    source = reflected(builder, declared.input.kind).get("properties", {})
    return bulk_schema(declared.input, lambda item: source[item.name], declared.op.access != PUBLIC and not declared.op.no_csrf)


def bulk_arguments_schema(builder: Any, declared: Declared) -> dict[str, Any]:
    """A bulk tool's input schema: the body, standing alone."""
    from app.apidocs.reflect import reflected

    source = reflected(builder, declared.input.kind).get("properties", {})
    return bulk_schema(declared.input, lambda item: resolve_all(builder, source[item.name]), False)
