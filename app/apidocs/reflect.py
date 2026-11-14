"""How a msgspec type becomes JSON Schema. msgspec.json.schema does the work;
this only puts its answer in the shape the docs use, the same shape Go's
server/apidoc gets from invopop/jsonschema, so both templates write the same
bytes.

A Struct field is required unless it has a default. T | None may also be
null. Annotated[T, Meta(...)] carries the rest, the way msgspec reads it:

    Meta(min_length=1, max_length=80)      string limits
    Meta(ge=0, le=1000)                    number limits
    Literal["admin", "user"]               the values it may take
    Meta(pattern="^[a-z]+$")               a regular expression it matches
    Meta(description="what it is")         its description
    Meta(examples=["10.0.0.0/24"])         an example
    Meta(extra_json_schema={"format": "uri"})  anything else for the docs
    Meta(extra={"error": "..."})           the 400 a request field answers
                                           when it is missing or breaks a limit

A default is documented unless it is empty (None, "", 0, False, [] or {}),
the way Go documents only a default tag. A Struct with api_name (a ClassVar)
is a named schema in components, referred to by $ref; every other Struct is
written out where it is used. api_doc (a ClassVar) is its description; a
docstring is for the code and stays out of the docs. one_of("SignIn", A, B)
is a named schema that is one of A or B.
"""
from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from typing import Any

import msgspec
from msgspec import inspect as msgspec_inspect

SCALARS = {"string", "integer", "number", "boolean"}


@dataclass(frozen=True)
class OneOf:
    """A named schema that is one of several shapes, such as SignIn: signed
    in, or a two-factor code still wanted."""

    name: str
    shapes: tuple
    doc: str = ""


def one_of(name: str, *shapes: Any, doc: str = "") -> OneOf:
    """one_of("SignIn", SignedIn, TwoFactorChallenge, doc="..."): a reply
    that is one of these, named in components. A handler's return annotation
    may be one."""
    return OneOf(name, shapes, doc)


class Schemas:
    """The named schemas a build has written out so far: components/schemas
    in openapi.json."""

    def __init__(self) -> None:
        self.components: dict[str, Any] = {}
        self.building: set[str] = set()

    def named(self, kind: Any) -> dict[str, Any]:
        """A $ref to a named type, written into components the first time."""
        return named(self, kind)


def api_name(kind: Any) -> str:
    if isinstance(kind, OneOf):
        return kind.name
    return getattr(kind, "api_name", "") if is_struct(kind) else ""


def is_struct(kind: Any) -> bool:
    return isinstance(kind, type) and issubclass(kind, msgspec.Struct)


def typed(builder: Any, kind: Any) -> dict[str, Any]:
    """The schema for a type: a $ref for a named one."""
    if isinstance(kind, OneOf):
        return named_one_of(builder, kind)
    if api_name(kind):
        return named(builder, kind)
    return reflected(builder, kind)


def named(builder: Any, kind: Any) -> dict[str, Any]:
    from app.apidocs import ref

    name = api_name(kind)
    if name not in builder.building:
        builder.building.add(name)
        builder.components[name] = reflected(builder, kind)
    return ref(name)


def named_one_of(builder: Any, kind: OneOf) -> dict[str, Any]:
    from app.apidocs import ref

    if kind.name not in builder.building:
        builder.building.add(kind.name)
        result: dict[str, Any] = {"oneOf": [typed(builder, shape) for shape in kind.shapes]}
        if kind.doc:
            result["description"] = kind.doc
        builder.components[kind.name] = result
    return ref(kind.name)


def reflected(builder: Any, kind: Any) -> dict[str, Any]:
    """A type's own schema, never a $ref to itself."""
    (_, ), defs = msgspec.json.schema_components([kind], ref_template="#/$defs/{name}")
    raw = defs.get(kind.__name__) if is_struct(kind) else msgspec.json.schema(kind)
    if raw is None:
        raw = msgspec.json.schema(kind)
    result = Normalizer(builder, defs).node(raw, msgspec_inspect.type_info(kind), top=True)
    return result


class Normalizer:
    def __init__(self, builder: Any, defs: dict[str, Any]) -> None:
        self.builder = builder
        self.defs = defs

    def node(self, raw: Any, info: Any, top: bool = False) -> dict[str, Any]:
        while isinstance(info, msgspec_inspect.Metadata):
            info = info.type
        if not isinstance(raw, dict):
            return {}
        target = raw.get("$ref", "")
        if target:
            cls = info.cls if isinstance(info, msgspec_inspect.StructType) else None
            if cls is not None and api_name(cls):
                result = named(self.builder, cls)
            elif cls is not None and not top:
                result = reflected(self.builder, cls)
            else:
                result = self.node(self.defs[target.rsplit("/", 1)[-1]], info, top=True)
            if "description" in raw:
                result = {**result, "description": raw["description"]}
            return result
        if "anyOf" in raw and isinstance(info, msgspec_inspect.UnionType) and info.includes_none:
            variants = [variant for variant in raw["anyOf"] if variant != {"type": "null"}]
            others = [kind for kind in info.types if not isinstance(kind, msgspec_inspect.NoneType)]
            inner = self.node(variants[0], others[0]) if len(variants) == 1 and len(others) == 1 else {}
            for key in ("description", "default", "examples"):
                if key in raw:
                    inner[key] = raw[key]
            return nullable(clean_default(inner))
        result: dict[str, Any] = {}
        for key, value in raw.items():
            if key in ("$defs", "title", "additionalProperties", "properties", "required", "items", "anyOf"):
                continue
            if key == "examples":
                if value:
                    result["example"] = value[0]
                continue
            if key == "description" and isinstance(info, msgspec_inspect.StructType):
                continue  # a docstring; api_doc is the description
            result[key] = value
        if isinstance(info, msgspec_inspect.DateTimeType):
            result["format"] = "date-time"
        if isinstance(info, msgspec_inspect.LiteralType) and "type" not in result:
            kinds = {type(value) for value in info.values}
            result["type"] = "string" if kinds == {str} else "integer" if kinds == {int} else result.get("type")
        if "items" in raw:
            item = info.item_type if hasattr(info, "item_type") else None
            result["items"] = self.node(raw["items"], item)
        if isinstance(raw.get("additionalProperties"), dict):
            value = info.value_type if isinstance(info, msgspec_inspect.DictType) else None
            if not isinstance(value, msgspec_inspect.AnyType):
                result["additionalProperties"] = self.node(raw["additionalProperties"], value)
        if "properties" in raw:
            fields = {field.encode_name: field for field in info.fields} if isinstance(info, msgspec_inspect.StructType) else {}
            hints = typing.get_type_hints(info.cls, include_extras=True) if isinstance(info, msgspec_inspect.StructType) else {}
            own = {}
            for name, value in raw["properties"].items():
                field = fields.get(name)
                own[name] = clean_default(self.node(value, field.type if field else None))
                declared = literal_args(hints.get(field.name)) if field else ()
                if declared:
                    in_order(own[name], declared)
            if own:
                result["properties"] = own
        if raw.get("required"):
            result["required"] = sorted(raw["required"])
        if isinstance(info, msgspec_inspect.StructType) and getattr(info.cls, "api_doc", ""):
            result["description"] = info.cls.api_doc
        return clean_default(result)


def literal_args(hint: Any) -> tuple:
    """A Literal's values in the order they were written (msgspec sorts
    them), through Annotated, | None and | UnsetType."""
    while hint is not None:
        origin = typing.get_origin(hint)
        if origin is typing.Literal:
            return typing.get_args(hint)
        if origin is typing.Annotated:
            hint = typing.get_args(hint)[0]
        elif origin in (typing.Union, types.UnionType):
            others = [arg for arg in typing.get_args(hint) if arg not in (type(None), msgspec.UnsetType)]
            hint = others[0] if len(others) == 1 else None
        else:
            return ()
    return ()


def in_order(schema: dict[str, Any], values: tuple) -> None:
    """Puts an enum back in its written order, wherever it sits."""
    if "enum" in schema:
        schema["enum"] = list(values)
    for variant in schema.get("oneOf", []):
        in_order(variant, values)


def clean_default(schema: dict[str, Any]) -> dict[str, Any]:
    """An empty default is left out, the way Go documents only a tag's."""
    if "default" in schema and not schema["default"] and schema["default"] is not True:
        del schema["default"]
    return schema


def nullable(schema: dict[str, Any]) -> dict[str, Any]:
    """Lets a schema be null too: a scalar's type becomes [type, "null"],
    anything else is oneOf it or null. A description stays outside."""
    kind = schema.get("type")
    if isinstance(kind, str) and kind in SCALARS:
        return {**schema, "type": [kind, "null"]}
    if isinstance(kind, list) and kind[-1:] == ["null"]:
        return schema
    inner = {key: value for key, value in schema.items() if key != "description"}
    result: dict[str, Any] = {"oneOf": [inner, {"type": "null"}]}
    if "description" in schema:
        result["description"] = schema["description"]
    return result
