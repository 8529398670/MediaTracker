"""The API reference -- config/api.json and config/api.md -- written from
the code, so nobody edits either by hand.

Every route is declared once, by @route(...) on its handler (see route.py): a
summary, who may call it, and the types of what it takes and gives back,
which are msgspec Structs (see reflect.py for how a type becomes JSON Schema).
The same types check every request before the handler sees it. build() walks
the routes the app really registers, so the paths and methods come from the
route table, and a route whose handler was not declared is reported.

Nothing here runs while the server is up. scripts/api_docs.sh runs
app/tests/test_api_docs.py with --update, which writes the files; the same
test fails while a committed file is out of date. Go's twin is server/apidoc,
and the two write the same bytes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Annotated, Any, ClassVar, Literal

from msgspec import UNSET, Meta, UnsetType

from app.apidocs.reflect import OneOf, Schemas, one_of  # noqa: F401  (the public names)
from app.apidocs.route import NoInput, PATH, QUERY, Reply, Request, declared_of, route  # noqa: F401  (the public names)

TITLE = "Media Tracker API"
VERSION = "1.0.0"
ABOUT = (
    "Every route this server answers, apart from the pages at /login/*, /join/* and /docs/*. Generated from the code by "
    "scripts/api_docs.sh: an app's own routes get their docs the same way, and a test fails until they do."
)

# Who may call a route. SIGNED, the default, is anyone signed in, by a browser
# session or an API key.
SIGNED = "signed"
PUBLIC = "public"  # no sign-in at all
SESSION_ONLY = "session"  # a browser session: an API key is turned away
KEY_ONLY = "key"  # an API key

# Roles for Op.role. Empty is any signed-in user.
ADMIN = "admin"
OWNER = "owner"


@dataclass
class Op:
    """One route's docs, given to @route(...). The fields match Go's
    apidoc.Op."""

    summary: str = ""
    tag: str = ""
    description: str = ""
    access: str = SIGNED
    role: str = ""
    # feature is the optional part of the template the route belongs to; it
    # becomes x-feature on the path, which scaffold.py's prune step reads.
    feature: str = ""
    # mcp_http is why a route an API key may call has no MCP tool.
    mcp_http: str = ""
    # bulk_of, on a bulk route, is the route it runs once per item:
    # x-bulk-of in api.json (see app/apidocs/bulk.py).
    bulk_of: str = ""
    # no_csrf lets a browser session's POST through without its csrf_token.
    # Only for a route the page calls before it has one.
    no_csrf: bool = False
    # raw_body is the type of a JSON body the handler reads itself (a
    # JSON-RPC message, say): documented, but neither parsed nor checked, and
    # no csrf_token is looked for in it.
    raw_body: Any = None
    # body_type is the request body's content type when it is not JSON: raw
    # bytes the handler reads itself. A browser session's csrf token then
    # comes in the X-CSRF-Token header.
    body_type: str = ""
    # status is the success status. reply_type is its content type when it
    # is not JSON: text, or bytes for application/octet-stream, which the
    # handler returns as its own Response.
    status: int = 200
    reply_type: str = ""
    reply_description: str = ""
    # errors are the error statuses the route can answer with, besides 429
    # and 503, which every route can.
    errors: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        # The owner signs in from a browser: role=OWNER is SESSION_ONLY too.
        if self.role == OWNER:
            if self.access not in (SIGNED, SESSION_ONLY):
                raise TypeError("role=OWNER is a browser session: give it no access")
            self.access = SESSION_ONLY


def handler_name(handler: Any) -> str:
    """The function behind a handler, for saying which one is undeclared."""
    function = getattr(handler, "__func__", handler)
    return f"{getattr(function, '__module__', '')}.{getattr(function, '__qualname__', '')}"


ROUTE_PARAMETER = re.compile(r"\{(\w+):\w+\}")
SPEC_PARAMETER = re.compile(r"\{(\w+)\}")
NOT_WORD = re.compile(r"[^a-z0-9]+")


def spec_path(path: str) -> str:
    """A route's path the way the spec writes it: /users/{user_id}."""
    return ROUTE_PARAMETER.sub(r"{\1}", path)


def build(routes: list[tuple[str, str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """api.json for these (method, path, endpoint) routes, and what is
    wrong with the docs: a route whose handler was not declared with @route."""
    builder = Schemas()
    paths: dict[str, Any] = {}
    tags: set[str] = set()
    problems: list[str] = []
    for method, raw_path, handler in routes:
        path = spec_path(raw_path)
        label = f"{method} {path}"
        declared = declared_of(handler)
        if declared is None:
            problems.append(f"{label}: no docs; declare {handler_name(handler)} with @route(...)")
            continue
        item = paths.setdefault(path, {})
        if declared.op.feature:
            item["x-feature"] = declared.op.feature
        found, operation_problems = operation(builder, method, path, declared)
        problems += [f"{label}: {problem}" for problem in operation_problems]
        item[method.lower()] = found
        tags.add(declared.op.tag)
    problems.sort()
    builder.named(ErrorReply)
    builder.named(MaintenanceReply)
    responses = {}
    for status in ERROR_STATUSES:
        target = "Maintenance" if status == 503 else "Error"
        responses[f"E{status}"] = {"description": ERROR_MEANINGS[status], "content": json_content(ref(target))}
    spec = {
        "openapi": "3.1.0",
        "info": {"title": TITLE, "version": VERSION, "description": ABOUT},
        "tags": [{"name": name} for name in tag_order(tags)],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "sessionCookie": {
                    "type": "apiKey", "in": "cookie", "name": "session",
                    "description": "A browser session. Its POSTs carry csrf_token in the body. The cookie's name is server.cookie_name, with the __Host- prefix while server.secure_cookies is on.",
                },
                "apiKey": {"type": "http", "scheme": "bearer", "description": "An API key, as Authorization: Bearer <id>.<secret>."},
            },
            "responses": responses,
            "schemas": builder.components,
        },
    }
    return spec, problems


def operation(builder: Schemas, method: str, path: str, declared: Any) -> tuple[dict[str, Any], list[str]]:
    """One operation of api.json, and what is wrong with its docs."""
    from app.apidocs.reflect import typed
    from app.apidocs.route import body_schema

    op = declared.op
    problems: list[str] = []
    result: dict[str, Any] = {"summary": op.summary, "operationId": operation_id(method, path), "tags": [op.tag]}
    if not op.summary:
        problems.append("no summary")
    if not op.tag:
        problems.append("no tag")
    if op.description:
        result["description"] = op.description
    if op.access == PUBLIC:
        result["security"] = []
    elif op.access == SESSION_ONLY:
        result["security"] = [{"sessionCookie": []}]
    elif op.access == KEY_ONLY:
        result["security"] = [{"apiKey": []}]
    else:
        result["security"] = [{"sessionCookie": []}, {"apiKey": []}]
    if op.role:
        result["x-required-role"] = op.role
    if op.mcp_http:
        result["x-mcp-http"] = op.mcp_http
    if op.bulk_of:
        result["x-bulk-of"] = op.bulk_of
    if declared.bulk_of is None:
        found, parameter_problems = parameters(builder, path, declared)
        problems += parameter_problems
        if found:
            result["parameters"] = found
    if declared.bulk_of is not None:
        from app.apidocs.bulk import bulk_body_schema

        result["requestBody"] = {"required": True, "content": json_content(bulk_body_schema(builder, declared))}
    elif op.body_type:
        result["requestBody"] = {"required": True, "content": {op.body_type: {"schema": raw_schema(op.body_type)}}}
    elif op.raw_body is not None:
        result["requestBody"] = {"required": True, "content": json_content(typed(builder, op.raw_body))}
    elif method != "GET":
        body, has_body = body_schema(builder, declared)
        if has_body:
            result["requestBody"] = {"required": True, "content": json_content(body)}
    reply: dict[str, Any] = {"description": op.reply_description or "Success"}
    if op.reply_type:
        reply["content"] = {op.reply_type: {"schema": raw_schema(op.reply_type)}}
    elif declared.reply not in (None, type(None)):
        # A route whose handler returns None answers with its status alone.
        reply["content"] = json_content(typed(builder, declared.reply))
    responses: dict[str, Any] = {str(op.status): reply}
    for code in (429, 503, *(declared.errors or op.errors)):
        if code not in ERROR_MEANINGS:
            problems.append(f"error status {code} has no shared response")
            continue
        responses[str(code)] = ref(f"E{code}", "responses")
    result["responses"] = responses
    return result, problems


def parameters(builder: Schemas, path: str, declared: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The route's path parameters in the path's order, then its query
    parameters in the request type's field order. A path parameter the type
    leaves out is a plain string."""
    from app.apidocs.route import url_parameters

    problems: list[str] = []
    found, order = url_parameters(builder, declared)
    result = []
    for name in SPEC_PARAMETER.findall(path):
        key = f"path {name}"
        if key in found:
            result.append(found.pop(key))
            continue
        result.append({"name": name, "in": "path", "required": True, "schema": {"type": "string"}})
    for key in order:
        if key in found:
            if key.startswith("path "):
                problems.append(f"path parameter {key[5:]} is not in the path")
                continue
            result.append(found[key])
    op = declared.op
    if op.body_type and op.access != PUBLIC and not op.no_csrf:
        result.append(CSRF_HEADER)
    return result, problems


# Where a browser session's csrf token rides on a route whose body is raw
# bytes.
CSRF_HEADER = {"name": "X-CSRF-Token", "in": "header", "description": "From GET /api/me. Browser sessions only.", "schema": {"type": "string"}}


# The order tags appear in, in both files. A tag not listed here comes after
# these, alphabetically.
TAG_ORDER = ["Account", "Sign-in", "API keys", "Files", "Admin", "Invite links", "Owner", "Webhooks", "Monitoring"]


def tag_order(used: set[str]) -> list[str]:
    return [name for name in TAG_ORDER if name in used] + sorted(name for name in used if name not in TAG_ORDER)


ERROR_STATUSES = (400, 401, 403, 404, 409, 429, 503)
ERROR_MEANINGS = {
    400: "The request was refused as it stands.",
    401: "Not signed in.",
    403: "Not allowed, or a bad csrf_token.",
    404: "No such thing, or this feature is switched off.",
    409: "The record has moved on: an undo too late, or a stale edit.",
    429: "Too many requests.",
    503: "In maintenance mode. Retry-After says when to try again.",
}


class ErrorReply(Reply, kw_only=True):
    """The body of every error."""

    api_name: ClassVar[str] = "Error"
    error: str
    request_id: Annotated[str, Meta(description="On a 5xx: the reference that finds this failure in the log.")] | UnsetType = UNSET


class MaintenanceReply(Reply):
    """The body of a 503 in maintenance mode."""

    api_name: ClassVar[str] = "Maintenance"
    error: str
    maintenance: Literal["read_only", "full"]


def json_content(schema_: dict[str, Any]) -> dict[str, Any]:
    return {"application/json": {"schema": schema_}}


def raw_schema(content_type: str) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "string"}
    if content_type == "application/octet-stream":
        result["format"] = "binary"
    return result


def ref(name: str, section: str = "schemas") -> dict[str, Any]:
    return {"$ref": f"#/components/{section}/{name}"}


def operation_id(method: str, path: str) -> str:
    return NOT_WORD.sub("_", f"{method} {path}".lower()).strip("_")


def encode(document: Any) -> str:
    """How every generated JSON file is written: keys sorted, two-space
    indent, and a newline at the end -- the bytes Go's apidoc.Encode writes."""
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
