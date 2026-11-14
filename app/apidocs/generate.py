"""The files of the API reference, as the code describes them.

The route table is build_routes() itself, so every route the app can have is
there. Nothing is built that a route needs to run: the docs only read the
table."""
from __future__ import annotations

import json
from typing import Any

from starlette.routing import Route

from app import apidocs
from app.apidocs.markdown import render, render_mcp
from app.core import assets

CONFIG = assets.CODE_ROOT / "config"

# What the route table has that is not an API: the pages a link opens, and the
# catch-alls.
NOT_DOCUMENTED = {"/login/{credential:path}", "/join/{credential:path}", "/api/{rest:path}", "/{path:path}"}


def documented_routes(routes: list[Any]) -> list[tuple[str, str, Any]]:
    """A route table, less what is not an API, as (method, path, endpoint)."""
    found = []
    for route in routes:
        if not isinstance(route, Route) or route.path in NOT_DOCUMENTED:
            continue
        for method in sorted(route.methods or ()):
            if method in ("GET", "POST", "DELETE"):
                found.append((method, route.path, route.endpoint))
    return found


def every_route() -> list[tuple[str, str, Any]]:
    from app.core.static_files import StaticServer
    from app.routes import build_routes

    return documented_routes(build_routes(StaticServer(assets.BUNDLED_STATIC)))


def spec() -> tuple[dict[str, Any], list[str]]:
    """api.json, and what is wrong with the docs."""
    return apidocs.build(every_route())


def documents() -> dict[str, str]:
    """File name -> what it should hold. Raises on a route without docs."""
    document, problems = spec()
    if problems:
        raise SystemExit("\n".join(problems))
    files: dict[str, str] = {}
    files["api.json"] = apidocs.encode(document)
    manifest_document = None
    from app.mcp import manifest
    from app.routes.mcp_tools import build_registry

    files["mcp.json"] = manifest.build(build_registry(), document)
    manifest_document = json.loads(files["mcp.json"])
    files["mcp.md"] = render_mcp(document, manifest_document)
    files["api.md"] = render(document, manifest_document)
    return files
