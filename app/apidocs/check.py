"""check(): what is wrong with a JSON reply, held against the docs -- a
required field missing, a field the docs do not list, or a value of the wrong
type. The route tests run every success reply through it, so docs that drift
from what a handler really sends fail there. Go's twin is server/apidoc/check.go."""
from __future__ import annotations

import json
from typing import Any


def check(spec: dict[str, Any], method: str, path: str, status: int, body: bytes) -> list[str]:
    """path is the spec's path, /api/users/{user_id}."""
    operation = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    response = operation.get("responses", {}).get(str(status))
    if not response or "$ref" in response:
        return []
    schema = response.get("content", {}).get("application/json", {}).get("schema")
    if schema is None:
        return []
    try:
        value = json.loads(body)
    except ValueError:
        return ["the reply is not JSON"]
    return validate(spec, schema, value, "reply")


def resolve(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    while schema.get("$ref"):
        schema = spec.get("components", {}).get("schemas", {}).get(schema["$ref"].rsplit("/", 1)[-1], {})
    return schema


def validate(spec: dict[str, Any], schema: dict[str, Any], value: Any, at: str) -> list[str]:
    schema = resolve(spec, schema)
    if schema.get("oneOf"):
        if any(not validate(spec, variant, value, at) for variant in schema["oneOf"]):
            return []
        return [f"{at}: matches none of its documented shapes"]
    properties: dict[str, Any] = {}
    required: list[str] = []
    has_properties = False
    parts = [resolve(spec, part) for part in schema["allOf"]] if schema.get("allOf") else [schema]
    for part in parts:
        if "properties" in part:
            has_properties = True
            properties.update(part["properties"])
        required += part.get("required", [])
    typed = types(schema)
    if typed and kind_of(value) not in typed and not (kind_of(value) == "integer" and "number" in typed):
        return [f"{at}: is {kind_of(value)}, documented as {' or '.join(sorted(typed))}"]
    problems: list[str] = []
    if isinstance(value, dict):
        if has_properties:
            for name in required:
                if name not in value:
                    problems.append(f"{at}.{name}: documented as always there, but missing")
            for name in sorted(value):
                if name not in properties:
                    problems.append(f"{at}.{name}: not in the docs")
                    continue
                problems += validate(spec, properties[name], value[name], f"{at}.{name}")
        elif isinstance(schema.get("additionalProperties"), dict):
            for name in sorted(value):
                problems += validate(spec, schema["additionalProperties"], value[name], f"{at}.{name}")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            problems += validate(spec, schema["items"], item, f"{at}[{index}]")
    return problems


def types(schema: dict[str, Any]) -> set[str]:
    typed = schema.get("type")
    if isinstance(typed, str):
        return {typed}
    if isinstance(typed, list):
        return set(typed)
    return set()


def kind_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "integer" if value.is_integer() else "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return ""
