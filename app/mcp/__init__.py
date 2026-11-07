"""The Model Context Protocol on POST /mcp, so an agent -- Claude Code, or any
MCP client that can send a header -- can use this app through the same API
keys and the same admin/user roles as every other script.

This package is the protocol only (protocol.py) and the shape of a tool
(registry.py). Which tools exist is decided in app/routes/mcp_tools.py, next
to the handlers whose rules they share; who may call /mcp at all is decided
where the route is registered (app/routes/__init__.py).
"""
