"""config/mcp.json -- the MCP reference -- built from the registered tools.

It is what tools/list says, for every tool and any key, with the HTTP route
each one stands for and the routes a key may call that stay HTTP only (their
mcp_http reason in the API docs). It names no features: scaffold.py's prune
step cuts a tool out by its route. scripts/api_docs.sh writes it, and
app/tests/test_api_docs.py fails while the committed file is out of date.
"""
from __future__ import annotations

import json
from typing import Any

from app.mcp.protocol import SUPPORTED_VERSIONS
from app.mcp.registry import Registry

DESCRIPTION = (
    "Every tool POST /mcp offers. Written by scripts/api_docs.sh from the registered tools; do not edit by hand. "
    "A key sees the tools its role allows (adminOnly ones need an admin key), and a tool whose feature is switched off "
    "answers like one that does not exist. route is the HTTP route the tool stands for, with the same rules; http_only "
    "are the routes a key may call that have no tool, and why."
)


def http_only(spec: dict[str, Any]) -> list[dict[str, str]]:
    """The operations with an x-mcp-http reason, as "METHOD /path"."""
    found = []
    for path, item in spec.get("paths", {}).items():
        for method, operation in item.items():
            if method.startswith("x-") or not isinstance(operation, dict):
                continue
            reason = operation.get("x-mcp-http")
            if reason:
                found.append({"reason": reason, "route": f"{method.upper()} {path}"})
    return sorted(found, key=lambda entry: entry["route"])


def build(registry: Registry, spec: dict[str, Any] | None) -> str:
    """The file's text: two-space JSON with sorted keys, the shape the Go
    template writes too. spec is openapi.json, as app.apidocs.build makes it."""
    tools = [{**tool.listing(), "adminOnly": tool.admin_only, "route": tool.route_name()} for tool in registry.tools()]
    document = {
        "auth": "Authorization: Bearer <API key>",
        "description": DESCRIPTION,
        "endpoint": "/mcp",
        "http_only": http_only(spec or {}),
        "protocolVersions": list(SUPPORTED_VERSIONS),
        "tools": tools,
        "transport": "Streamable HTTP, stateless: one JSON-RPC message per POST, a JSON reply",
    }
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
