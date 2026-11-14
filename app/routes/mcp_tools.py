"""The tools /mcp offers (see app/mcp for the protocol and the rules a tool
follows). A tool is declared with its route, by mcp="tool_name" in the
handler's @route(...), and build_registry makes each one with Tool.for_route:
its arguments are the route's own request type, and it runs the route's own
handler, so the two doors answer the same way and refuse for the same
reasons. A tool that adds to its route's answer (where to send a file's bytes)
names a call that does; those live here and in mcp_tools_accounts.py.

The rule: every route an API key may call has a tool, or an mcp_http reason
in its @route(...) for staying HTTP only. app/tests/test_mcp_parity.py fails
until that holds. What a key may not call -- managing API keys, setting your
own password, PIN or two-factor, other people's files, and the owner's
screens -- needs a browser session (access=SESSION_ONLY), so it has no tool
either.

After adding or changing a tool, run scripts/api_docs.sh to rewrite
config/mcp.json and config/api.md; app/tests/test_api_docs.py fails until
they are current.

An app's tools that stand for no route are registered in build_registry,
from a new module in this package (mcp_tools_<feature>.py).
"""
from __future__ import annotations



from app.apidocs import ADMIN
from app.mcp.registry import Registry, Tool


def build_registry() -> Registry:
    """A tool for every route with mcp=, by name. Its title is mcp_title, or
    else the route's summary, with " (admin)" for an admin-only tool; its
    description is mcp_description, or else the route's description, then
    mcp_note. Go's generator (server/apidoc/routegen) has the same rules."""
    from app.routes import declared_routes

    registry = Registry()
    declared = [route for route in declared_routes() if route.tool is not None]
    for route in sorted(declared, key=lambda route: route.tool["name"]):
        keys = dict(route.tool)
        admin_only = keys.pop("admin_only", route.op.role == ADMIN)
        title = keys.pop("mcp_title", "") or (route.op.summary + " (admin)" if admin_only else route.op.summary)
        note = keys.pop("mcp_note", "")
        description = keys.pop("mcp_description", "") or " ".join(part for part in (route.op.description, note) if part)
        if not title or not description:
            raise TypeError(f"{route.method} {route.path}: tool {keys['name']} needs a summary (or mcp_title) and a description, mcp_note or mcp_description")
        registry.register(Tool.for_route(route.endpoint, title=title, description=description, admin_only=admin_only, **keys))
    return registry
