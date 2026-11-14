"""A route is declared once, as a typed handler next to its code:

    class CreateUser(Request):
        display_name: Annotated[str, Meta(min_length=1, max_length=80, extra={"error": "display name must be 1-80 characters"})]
        role: Annotated[Literal["admin", "user"], Meta(extra={"error": "role must be admin or user"})]

    @route(
        "POST /api/admin/users", summary="Create an account",
        tag="Admin", role=ADMIN, status=201,
        description="Make a new account and its first login link, to hand to the person.",
        mcp="admin_create_user", call=with_login_url,
    )
    def create_user(request: Request, body: CreateUser) -> CreateUserReply:
        ...

Go's routes (server/apidoc/routegen) are declared with the same words, in a
comment above each handler, so a declaration reads the same in both.

app/routes/__init__.py mounts every declared route in its modules, behind the
guards its access, role and feature imply.

The handler's second parameter's type is the whole of what the route takes.
A field marked Annotated[T, PATH] or Annotated[T, QUERY] comes from the URL,
every other field from the JSON body, and its name is the same in both and to
MCP. The return type is what it answers. From the two come the route's entry
in config/openapi.json, the input schema of the MCP tool that stands for it,
and the checks every request goes through before the handler sees it:

- The body must be a JSON object ("malformed request body" otherwise), and on
  a signed-in route a browser session's POST must carry its csrf_token (403
  "invalid csrf token"). An API key needs none.
- A field nobody declared is refused: 400 "unknown field: x".
- A body value of the wrong JSON type is "malformed request body".
- A field that is missing, or breaks a limit, answers its own
  Meta(extra={"error": ...}) (or "x is required" / "x is invalid" without one,
  or for a Literal "x must be one of: a, b"). A path or query value that is
  not a number where one is wanted counts as that.

These are the checks Go's declared routes (server/apidoc) make, in the same order, so the two
templates answer the same words. A handler may be a plain function (it runs
in a worker thread, and an MCP tool can call it too) or a coroutine. It
returns its reply, or raises Refused.
"""
from __future__ import annotations

import functools
import inspect
import re
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Sequence

import msgspec
from msgspec import inspect as msgspec_inspect
from starlette.concurrency import run_in_threadpool

from app.apidocs.reflect import literal_args
from starlette.requests import Request as HTTPRequest
from starlette.responses import Response


class Place:
    """Where a request field comes from, when not the body."""

    def __init__(self, where: str) -> None:
        self.where = where

    def __repr__(self) -> str:
        return self.where.upper()


PATH = Place("path")
QUERY = Place("query")


class Request(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    """The base of every request type."""


class Reply(msgspec.Struct, kw_only=True):
    """The base of every reply type. api_name (a ClassVar) makes one a named
    schema; api_doc describes it."""

    api_name: ClassVar[str] = ""
    api_doc: ClassVar[str] = ""


class NoInput(Request):
    """The request of a route that takes nothing."""


@dataclass
class InputField:
    name: str
    place: str  # "path", "query" or "" for the body
    hint: Any  # the field's full type, limits and all
    bare: Any  # the type alone, for reading a URL value
    required: bool
    error: str
    enum: tuple = ()

    def message(self, fault: str) -> str:
        return self.error or f"{self.name} is {fault}"

    def refusal(self) -> str:
        """The 400 for a value that breaks the field's limits."""
        if not self.error and self.enum:
            return f"{self.name} must be one of: " + ", ".join(str(value) for value in self.enum)
        return self.message("invalid")


@dataclass
class InputType:
    kind: Any
    fields: list[InputField] = field(default_factory=list)

    @classmethod
    def of(cls, kind: Any) -> InputType:
        found = cls(kind)
        if kind is None:
            return found
        info = msgspec_inspect.type_info(kind)
        hints = typing.get_type_hints(kind, include_extras=True)
        for item in info.fields:
            hint = hints[item.name]
            place, error = "", ""
            for extra in annotations(hint):
                if isinstance(extra, Place):
                    place = extra.where
                if isinstance(extra, msgspec.Meta) and extra.extra:
                    error = extra.extra.get("error", error)
            kind_info = optional_of(item.type)
            enum = literal_args(hint)
            if place == "query" and item.required:
                raise TypeError(f"{kind.__name__}.{item.name}: a query field needs a default")
            found.fields.append(InputField(item.encode_name, place, hint, bare_type(kind_info), item.required, error, enum))
        return found

    def by_name(self) -> dict[str, InputField]:
        return {item.name: item for item in self.fields}

    def decode(self, values: dict[str, Any], strict_places: bool) -> tuple[Any, str, bool]:
        """The request, checked: (value, "", False), or (None, the 400
        message, whether it is a fault in the request itself rather than one
        field's own refusal). strict_places is MCP's way: every field, URL
        ones included, comes typed from values."""
        known = self.by_name()
        unknown = sorted(name for name in values if name not in known)
        if unknown:
            return None, f"unknown field: {unknown[0]}", True
        for item in self.fields:
            if item.name not in values:
                if item.required:
                    return None, item.message("required"), False
                continue
            try:
                msgspec.convert(values[item.name], item.hint)
            except msgspec.ValidationError as error:
                if wrong_type(str(error)):
                    if item.place and not strict_places:
                        return None, item.message("invalid"), False
                    return None, "malformed request body", True
                return None, item.refusal(), False
        try:
            return msgspec.convert(values, self.kind), "", False
        except msgspec.ValidationError:
            return None, "malformed request body", True

    def arguments_schema(self, builder: Any) -> dict[str, Any]:
        """An MCP tool's arguments: the whole request, URL fields included, as
        one object."""
        from app.apidocs.reflect import reflected

        source = reflected(builder, self.kind).get("properties", {})
        properties = {name: resolve_all(builder, value) for name, value in source.items()}
        schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
        required = sorted(item.name for item in self.fields if item.required)
        if required:
            schema["required"] = required
        return schema


def resolve_all(builder: Any, schema: dict[str, Any], open_names: frozenset[str] = frozenset()) -> dict[str, Any]:
    """A schema with every $ref into the builder's components written out,
    however deep (a list of named types included), so an MCP tool's input
    schema stands alone. A key beside a $ref, such as the field's own
    description, wins over the named schema's. A type that holds itself stays
    a $ref past its first level. Go's resolveAll."""
    target = schema.get("$ref", "")
    if target:
        name = target.rsplit("/", 1)[-1]
        if name in open_names:
            return schema
        merged = {**builder.components.get(name, {}), **{key: value for key, value in schema.items() if key != "$ref"}}
        return resolve_all(builder, merged, open_names | {name})
    result: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            result[key] = resolve_all(builder, value, open_names)
        elif isinstance(value, list):
            result[key] = [resolve_all(builder, item, open_names) if isinstance(item, dict) else item for item in value]
        else:
            result[key] = value
    return result


def annotations(hint: Any) -> list[Any]:
    """Every Annotated extra on a hint, through | None and nested Annotated."""
    found: list[Any] = []
    origin = typing.get_origin(hint)
    if origin is typing.Annotated:
        arguments = typing.get_args(hint)
        found += annotations(arguments[0]) + list(arguments[1:])
    elif origin in (typing.Union, types.UnionType):
        for argument in typing.get_args(hint):
            found += annotations(argument)
    return found


def wrong_type(message: str) -> bool:
    """Whether a msgspec error is about a value's JSON type rather than a
    limit: the line Go's inspect draws between wrongType and outOfBounds."""
    return ("`, got `" in message and message.startswith("Expected `")) or message.startswith("Object contains unknown field")


def optional_of(info: Any) -> Any:
    """A field's type info through Annotated and "| None": what a URL value
    of it is read as."""
    while True:
        if isinstance(info, msgspec_inspect.Metadata):
            info = info.type
        elif isinstance(info, msgspec_inspect.UnionType) and info.includes_none and len(info.types) == 2:
            info = next(kind for kind in info.types if not isinstance(kind, msgspec_inspect.NoneType))
        else:
            return info


def bare_type(info: Any) -> Any:
    """The plain Python type a URL value is read as."""
    if isinstance(info, msgspec_inspect.IntType):
        return int
    if isinstance(info, msgspec_inspect.BoolType):
        return bool
    if isinstance(info, msgspec_inspect.FloatType):
        return float
    return str


@dataclass
class Declared:
    """A declared route as the docs and MCP see it."""

    op: Any
    handler: Callable
    input: InputType
    reply: Any
    takes_input: bool
    method: str = ""
    path: str = ""
    # use are guards beyond the ones the op implies (see app/routes); no_switch
    # is a route that answers while its feature is switched off.
    use: tuple[type, ...] = ()
    no_switch: bool = False
    # tool is the route's MCP tool, from @route(..., mcp="name", ...): its
    # name and the tool keys given (TOOL_KEYS). build_registry makes the Tool.
    tool: dict[str, Any] | None = None
    endpoint: Any = None
    # guards and errors are filled in by app/routes when it builds the route
    # list: the guards in front of the handler, and every error status the
    # docs list (theirs, the request checks' and the handler's own).
    guards: tuple[type, ...] = ()
    errors: tuple[int, ...] = ()

    def serve(self, request: Any, body: Any) -> Any:
        """Runs a plain-function handler: an MCP tool's call."""
        if inspect.iscoroutinefunction(self.handler):
            raise TypeError(f"{self.handler.__qualname__} is a coroutine; an MCP tool needs a plain function")
        return self.handler(request, body) if self.takes_input else self.handler(request)


METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
PARAMETER = re.compile(r"\{(\w+)\}")


# The keys of a route's MCP tool, which mean something only with mcp=.
TOOL_KEYS = ("read_only", "destructive", "admin_only", "enabled", "call", "mcp_note", "mcp_title", "mcp_description")


def route(where: str, *, use: Sequence[type] = (), no_switch: bool = False, mcp: str = "", **fields: Any) -> Callable[[Callable], Callable]:
    """Declares a route: where it is ("POST /api/admin/users/{user_id}/rename",
    with each {param} a PATH field of the request), its docs (the fields of
    Op), and its types from the handler's annotations. Its guards follow from
    access, role and feature (see app/routes); use adds Guard classes after
    them, and no_switch keeps the feature's switch off it.

    mcp="tool_name" gives it an MCP tool (see app/mcp/registry.py), and the
    keys that mean something only with it: read_only, destructive,
    admin_only (on by default for role=ADMIN), enabled, call, and mcp_note,
    words only the tool shows after the description. mcp_title and
    mcp_description replace the tool's words, for one whose words must
    differ from its route's."""
    from app.apidocs import Op

    method, _, path = where.partition(" ")
    if method not in METHODS or not path.startswith("/"):
        raise TypeError(f"@route({where!r}): give METHOD /path, such as POST /api/admin/users")
    tool = {key: fields.pop(key) for key in TOOL_KEYS if key in fields}
    if tool and not mcp:
        raise TypeError(f"@route({where!r}): {', '.join(sorted(tool))} need mcp=\"tool_name\"")
    if mcp:
        tool["name"] = mcp
    op = Op(**fields)

    def mark(handler: Callable) -> Callable:
        hints = typing.get_type_hints(handler, include_extras=True)
        parameters = list(inspect.signature(handler).parameters)
        takes_input = len(parameters) > 1
        kind = hints[parameters[1]] if takes_input else NoInput
        declared = Declared(op, handler, InputType.of(kind), hints.get("return"), takes_input,
                            method=method, path=path, use=tuple(use), no_switch=no_switch,
                            tool=tool or None)
        in_path = {item.name for item in declared.input.fields if item.place == "path"}
        named = set(PARAMETER.findall(path))
        if in_path != named:
            raise TypeError(f"{handler.__qualname__}: the path's {{params}} {sorted(named)} are not the request's PATH fields {sorted(in_path)}")

        @functools.wraps(handler)
        async def endpoint(request: HTTPRequest) -> Response:
            return await handle(declared, request)

        endpoint.__declared__ = declared  # type: ignore[attr-defined]
        declared.endpoint = endpoint
        return endpoint

    return mark


def declared_of(handler: Any) -> Declared | None:
    return getattr(handler, "__declared__", None)


def route_of(handler: Any) -> str:
    """The route a declared handler is at, as the spec writes it:
    "POST /api/admin/users"."""
    declared = declared_of(handler)
    if declared is None:
        return ""
    return f"{declared.method} {declared.path}"


async def handle(declared: Declared, request: HTTPRequest) -> Response:
    from app.apidocs import PUBLIC
    from app.core.security import check_csrf
    from app.routes.helpers import Refused, bad_request, forbidden

    op = declared.op
    values: dict[str, Any] = {}
    token: Any = None
    reads = request.method in ("GET", "HEAD")
    if not op.body_type and op.raw_body is None and not reads:
        raw = (await request.body()).strip()
        if raw:
            try:
                values = msgspec.json.decode(raw)
            except msgspec.DecodeError:
                return bad_request("malformed request body")
            if not isinstance(values, dict):
                return bad_request("malformed request body")
        token = values.pop("csrf_token", None)
    if op.access != PUBLIC and not reads and not op.no_csrf and op.raw_body is None:
        if op.body_type:
            token = request.headers.get("x-csrf-token")
        if not check_csrf(request, token):
            return forbidden("invalid csrf token")
    for item in declared.input.fields:
        if item.place == "path":
            if item.name not in request.path_params:
                continue
            text = request.path_params[item.name]
        elif item.place == "query":
            if item.name not in request.query_params:
                continue
            text = request.query_params[item.name]
        else:
            continue
        try:
            values[item.name] = text if not isinstance(text, str) else msgspec.convert(text, item.bare, strict=False)
        except msgspec.ValidationError:
            return bad_request(item.message("invalid"))
    body, message, _ = declared.input.decode(values, strict_places=False)
    if message:
        return bad_request(message)
    arguments = (request, body) if declared.takes_input else (request,)
    try:
        if inspect.iscoroutinefunction(declared.handler):
            reply = await declared.handler(*arguments)
        else:
            reply = await run_in_threadpool(declared.handler, *arguments)
    except Refused as refused:
        return refused.response(request)
    if isinstance(reply, Response):
        return reply
    if reply is None:
        return Response(status_code=op.status)
    return reply_response(reply, op.status)


def reply_response(reply: Any, status: int = 200) -> Response:
    """A reply as the Response a declared route sends. A handler that has to
    set a cookie on it builds it with this and returns the Response; the docs
    still come from its return annotation."""
    return Response(msgspec.json.encode(reply), status_code=status, media_type="application/json")


def body_schema(builder: Any, declared: Declared) -> tuple[dict[str, Any], bool]:
    """The request body: the request type less its URL fields, and
    csrf_token on a route a browser session signs."""
    from app.apidocs import PUBLIC
    from app.apidocs.reflect import reflected

    source = reflected(builder, declared.input.kind).get("properties", {})
    properties = {item.name: source[item.name] for item in declared.input.fields if not item.place}
    if declared.op.access != PUBLIC and not declared.op.no_csrf:
        properties["csrf_token"] = {"type": "string", "description": "From GET /api/me. Browser sessions only."}
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    required = sorted(item.name for item in declared.input.fields if not item.place and item.required)
    if required:
        schema["required"] = required
    return schema, bool(properties)


def url_parameters(builder: Any, declared: Declared) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """The request type's path and query fields, as the spec's parameters."""
    from app.apidocs.reflect import reflected

    source = reflected(builder, declared.input.kind).get("properties", {})
    found: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in declared.input.fields:
        if not item.place:
            continue
        schema = dict(source[item.name])
        description = schema.pop("description", "")
        parameter: dict[str, Any] = {"name": item.name, "in": item.place, "schema": schema}
        if description:
            parameter["description"] = description
        if item.place == "path":
            parameter["required"] = True
        found[f"{item.place} {item.name}"] = parameter
        order.append(f"{item.place} {item.name}")
    return found, order


def input_schema(handler: Any) -> dict[str, Any]:
    """The JSON Schema of an MCP tool's arguments, for the route it stands
    for. csrf_token is not part of it: a key needs none."""
    from app.apidocs.reflect import Schemas

    declared = declared_of(handler)
    if declared is None:
        raise TypeError(f"{handler!r} is not a declared route")
    return declared.input.arguments_schema(Schemas())


def decode_arguments(handler: Any, args: Any) -> tuple[Any, str, bool]:
    """decode for an MCP tool: the arguments object, checked the way the
    route checks a request."""
    declared = declared_of(handler)
    if declared is None:
        return None, "no such route", True
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return None, "malformed request body", True
    return declared.input.decode(dict(args), strict_places=True)

