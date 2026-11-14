"""config/api.md: the same reference as api.json, as tables a person
reads, and config/mcp.md, the MCP tools the same way. Go's server/apidoc/markdown.go renders the same bytes from the same
documents, so keep the two in step."""
from __future__ import annotations

from typing import Any

FIELD_HEADER = ["Field", "Type", "Required", "Limits", "Description"]


def render(spec: dict[str, Any], manifest: dict[str, Any] | None) -> str:
    """spec is api.json; manifest is mcp.json, or None without MCP."""
    out: list[str] = []
    write = out.append
    info = spec.get("info", {})
    components = spec.get("components", {})
    paths = spec.get("paths", {})
    tools: dict[str, list[str]] = {}
    if manifest is not None:
        for tool in manifest.get("tools", []):
            tools.setdefault(tool.get("route", ""), []).append(tool.get("name", ""))
    by_tag: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
    for path in sorted(paths):
        item = paths[path]
        for method in ("get", "post", "put", "patch", "delete"):
            if method in item:
                op = item[method]
                by_tag.setdefault(op["tags"][0], []).append((method.upper(), path, op))
    tag_names = [tag["name"] for tag in spec.get("tags", [])]

    write(f"# {info.get('title', '')}\n\n")
    write(f"{info.get('description', '')}\n\n")
    write("This file is generated: do not edit it. Change the docs next to the handlers and run `scripts/api_docs.sh`.\n\n")
    write("## Contents\n\n")
    write("- [Calling the API](#calling-the-api)\n- [Errors](#errors)\n")
    for tag in tag_names:
        write(f"- [{tag}](#{slug(tag)})\n")
    write("- [Schemas](#schemas)\n")
    write("\n## Calling the API\n\n")
    schemes = components.get("securitySchemes", {})
    table(out, ["Way in", "How"], [
        ["Browser session", schemes.get("sessionCookie", {}).get("description", "")],
        ["API key", schemes.get("apiKey", {}).get("description", "")],
    ])
    write("## Errors\n\nAn error reply is a JSON object whose `error` says what went wrong.\n\n")
    responses = components.get("responses", {})
    rows = []
    for name in sorted(responses):
        response = responses[name]
        kind, _, _ = describe(response.get("content", {}).get("application/json", {}).get("schema", {}))
        rows.append([name.removeprefix("E"), response.get("description", ""), kind])
    table(out, ["Status", "Meaning", "Body"], rows)

    for tag in tag_names:
        write(f"## {tag}\n\n")
        table(out, ["Method", "Path", "Summary", "Who may call"], [
            [method, f"[`{path}`](#{slug(method + ' ' + path)})", op.get("summary", ""), who(op)] for method, path, op in by_tag.get(tag, [])
        ])
        for method, path, op in by_tag.get(tag, []):
            write(f"### {method} {path}\n\n")
            write(f"{op.get('summary', '')}\n\n")
            if op.get("description"):
                write(f"{op['description']}\n\n")
            facts = [["Who may call", who(op)]]
            if manifest is not None:
                names = tools.get(f"{method} {path}")
                if names is not None:
                    facts.append(["MCP tool", ", ".join(f"[`{name}`](mcp.md#{slug(name)})" for name in names)])
                elif op.get("x-mcp-http"):
                    facts.append(["MCP tool", "None, HTTP only: " + op["x-mcp-http"]])
            errors, success = [], ""
            for status in sorted(op.get("responses", {})):
                if "$ref" in op["responses"][status]:
                    errors.append(status)
                else:
                    success = status
            facts.append(["Errors", ", ".join(errors)])
            table(out, ["", ""], facts)
            if op.get("parameters"):
                write("**Parameters**\n\n")
                rows = []
                for parameter in op["parameters"]:
                    schema = parameter.get("schema", {})
                    kind, _, _ = describe(schema)
                    rows.append([f"`{parameter.get('name', '')}`", parameter.get("in", ""), kind, yes(parameter.get("required") is True), limits(schema), parameter.get("description", "")])
                table(out, ["Name", "In", "Type", "Required", "Limits", "Description"], rows)
            if op.get("requestBody") is not None:
                write("**Request body**\n\n")
                content(out, op["requestBody"].get("content", {}))
            reply = op.get("responses", {}).get(success, {})
            write(f"**Reply {success}**: {reply.get('description', '')}\n\n")
            content(out, reply.get("content", {}))

    write("## Schemas\n\nThe shapes the routes above refer to by name.\n\n")
    schemas = components.get("schemas", {})
    for name in sorted(schemas):
        write(f"### {name}\n\n")
        block(out, schemas[name])

    return "".join(out).rstrip("\n") + "\n"


def render_mcp(spec: dict[str, Any], manifest: dict[str, Any]) -> str:
    """config/mcp.md: mcp.json as tables a person reads, beside api.md, which
    each tool's route links into. Go's MCPMarkdown renders the same bytes."""
    out: list[str] = []
    write = out.append
    title = spec.get("info", {}).get("title", "").removesuffix(" API")
    write(f"# {title} MCP tools\n\n")
    write("This file is generated: do not edit it. Change the tools next to their handlers and run `scripts/api_docs.sh`. Every route is in [api.md](api.md).\n\n")
    write(f"{manifest.get('description', '')}\n\n")
    table(out, ["", ""], [
        ["Endpoint", f"`POST {manifest.get('endpoint', '')}`"],
        ["Transport", manifest.get("transport", "")],
        ["Auth", manifest.get("auth", "")],
    ])
    table(out, ["Tool", "Route", "Who", "What"], [
        [f"[`{tool.get('name', '')}`](#{slug(tool.get('name', ''))})", route_link(tool.get('route', '')), "admin keys" if tool.get("adminOnly") is True else "any key", tool.get("title", "")]
        for tool in manifest.get("tools", [])
    ])
    for tool in manifest.get("tools", []):
        write(f"## {tool.get('name', '')}\n\n")
        write(f"{tool.get('description', '')}\n\n")
        hints = tool.get("annotations", {})
        table(out, ["", ""], [
            ["Route", route_link(tool.get('route', ''))],
            ["Read only", yes(hints.get("readOnlyHint") is True)],
            ["Destructive", yes(hints.get("destructiveHint") is True)],
        ])
        write("**Arguments**\n\n")
        block(out, tool.get("inputSchema", {}))
    if manifest.get("http_only"):
        write("## HTTP only\n\nRoutes an API key may call that have no tool, and why.\n\n")
        table(out, ["Route", "Why"], [[route_link(entry.get('route', '')), entry.get("reason", "")] for entry in manifest["http_only"]])
    return "".join(out).rstrip("\n") + "\n"


def route_link(route: str) -> str:
    """A tool's route, linked to its section of api.md."""
    return f"[`{route}`](api.md#{slug(route)})"


def content(out: list[str], types: dict[str, Any]) -> None:
    """A request or reply body."""
    for content_type in sorted(types):
        schema = types[content_type].get("schema", {})
        if content_type != "application/json":
            kind = "Raw bytes" if schema.get("format") == "binary" else "Text"
            out.append(f"{kind}, as `{content_type}`.\n\n")
            continue
        block(out, schema)


def block(out: list[str], schema: dict[str, Any]) -> None:
    """A whole schema: a table of its fields, or what it is made of."""
    if "properties" in schema:
        rows: list[list[str]] = []
        fields(schema, "", rows)
        table(out, FIELD_HEADER, rows)
        return
    variants = schema.get("oneOf") or []
    if len(variants) > 1 and non_null(variants) is None:
        out.append("One of these:\n\n")
        for index, variant in enumerate(variants, 1):
            if "properties" in variant:
                out.append(f"{index}. An object:\n\n")
                rows = []
                fields(variant, "", rows)
                table(out, FIELD_HEADER, rows)
                continue
            kind, _, _ = describe(variant)
            out.append(f"{index}. {kind}\n\n")
        return
    parts = schema.get("allOf") or []
    if parts:
        names = [describe(part)[0] for part in parts if part.get("$ref")]
        inline = [part for part in parts if not part.get("$ref")]
        if not inline:
            out.append(f"Every field of {' and '.join(names)}.\n\n")
            return
        out.append(f"Every field of {' and '.join(names)}, plus these:\n\n")
        for part in inline:
            block(out, part)
        return
    kind, children, array = describe(schema)
    if kind == "object" and not children:
        out.append("An empty object.\n\n")
        return
    out.append(f"{kind[:1].upper() + kind[1:] if kind[:1].islower() else kind}.\n\n")
    prefix = "[]." if array else ""
    for child in children:
        rows = []
        fields(child, prefix, rows)
        table(out, FIELD_HEADER, rows)


def fields(schema: dict[str, Any], prefix: str, rows: list[list[str]]) -> None:
    """An object's properties as rows: a nested object's own fields follow it
    as parent.child, and an array's items' as parent[].child."""
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    for name in sorted(properties):
        prop = properties[name]
        kind, children, array = describe(prop)
        rows.append([f"`{prefix}{name}`", kind, yes(name in required), limits(prop), doc(prop)])
        inner = f"{prefix}{name}[]." if array else f"{prefix}{name}."
        for child in children:
            fields(child, inner, rows)


def describe(schema: dict[str, Any]) -> tuple[str, list[dict[str, Any]], bool]:
    """A schema's type in words, the inline objects whose fields belong under
    it, and whether those are an array's items."""
    if schema.get("$ref"):
        name = schema["$ref"].rsplit("/", 1)[-1]
        return f"[`{name}`](#{slug(name)})", [], False
    variants = schema.get("oneOf") or []
    if variants:
        single = non_null(variants)
        if single is not None:
            kind, children, array = describe(single)
            return kind + " or null", children, array
        words, children = [], []
        for variant in variants:
            word, more, _ = describe(variant)
            words.append(word)
            children += more
        return " or ".join(words), children, False
    parts = schema.get("allOf") or []
    if parts:
        words, children = [], []
        for part in parts:
            word, more, _ = describe(part)
            words.append(word)
            children += more
        return " + ".join(words), children, False
    base, nullable = "", False
    typed = schema.get("type")
    if isinstance(typed, str):
        base = typed
    elif isinstance(typed, list):
        for name in typed:
            if name == "null":
                nullable = True
            else:
                base = name
    children: list[dict[str, Any]] = []
    array = False
    if base == "":
        kind = "any"
    elif base == "array":
        inner, children, _ = describe(schema.get("items") or {})
        kind, array = "array of " + inner, True
    elif base == "object":
        kind = "object"
        if "properties" in schema:
            children = [schema]
        elif isinstance(schema.get("additionalProperties"), dict):
            inner, _, _ = describe(schema["additionalProperties"])
            kind = "map of " + inner
    else:
        kind = base + (f" ({schema['format']})" if schema.get("format") else "")
    if nullable:
        kind += " or null"
    return kind, children, array


def non_null(variants: list[Any]) -> dict[str, Any] | None:
    others = [variant for variant in variants if not (variant.get("type") == "null" and len(variant) == 1)]
    nulls = len(variants) - len(others)
    return others[0] if nulls == 1 and len(others) == 1 else None


def limits(schema: dict[str, Any]) -> str:
    """The rules a value must keep to, in words."""
    single = non_null(schema.get("oneOf") or [])
    if single is not None:
        schema = single
    parts = []
    if "minimum" in schema and "maximum" in schema:
        parts.append(f"{value(schema['minimum'])} to {value(schema['maximum'])}")
    elif "minimum" in schema:
        parts.append(f"at least {value(schema['minimum'])}")
    elif "maximum" in schema:
        parts.append(f"at most {value(schema['maximum'])}")
    if "minLength" in schema and "maxLength" in schema:
        parts.append(f"{value(schema['minLength'])} to {value(schema['maxLength'])} characters")
    elif "minLength" in schema:
        parts.append(f"at least {value(schema['minLength'])} characters")
    elif "maxLength" in schema:
        parts.append(f"at most {value(schema['maxLength'])} characters")
    if schema.get("enum"):
        parts.append("one of " + ", ".join(f"`{value(item)}`" for item in schema["enum"]))
    if "default" in schema:
        parts.append(f"default `{value(schema['default'])}`")
    if "example" in schema:
        parts.append(f"e.g. `{value(schema['example'])}`")
    return "; ".join(parts)


def doc(schema: dict[str, Any]) -> str:
    text = schema.get("description", "")
    if not text:
        single = non_null(schema.get("oneOf") or [])
        if single is not None:
            text = single.get("description", "")
    return text if isinstance(text, str) else ""


def who(op: dict[str, Any]) -> str:
    """Who may call an operation, in words."""
    ways = {name for scheme in op.get("security", []) for name in scheme}
    if not ways:
        return "anyone"
    if "sessionCookie" in ways and "apiKey" in ways:
        text = "browser session or API key"
    elif "sessionCookie" in ways:
        text = "browser session only"
    else:
        text = "API key only"
    role = op.get("x-required-role", "")
    return text + {"admin": ", admins", "owner": ", the owner"}.get(role, ", anyone signed in")


def table(out: list[str], header: list[str], rows: list[list[str]]) -> None:
    def line(cells: list[str]) -> None:
        out.append("| " + " | ".join(cell_text(cell) for cell in cells) + " |\n")

    line(header)
    out.append("|" + "|".join("---" for _ in header) + "|\n")
    for row in rows:
        line(row)
    out.append("\n")


def cell_text(text: str) -> str:
    return text.replace("|", "\\|").replace("\r\n", " ").replace("\n", " ")


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    result = []
    for character in heading.lower():
        if "a" <= character <= "z" or "0" <= character <= "9" or character in "_-":
            result.append(character)
        elif character == " ":
            result.append("-")
    return "".join(result)


def yes(flag: bool) -> str:
    return "yes" if flag else "no"


def value(raw: Any) -> str:
    if raw is None:
        return "null"
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        return str(int(raw)) if raw.is_integer() and abs(raw) < 1e15 else repr(raw)
    return str(raw)
