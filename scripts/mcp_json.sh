#!/usr/bin/env bash
# Rewrite config/mcp.json -- the MCP reference: every tool POST /mcp offers,
# its arguments, the route it stands for, and the routes that stay HTTP only --
# from the tools registered in app/routes/mcp_tools.py (see app/mcp/manifest.py).
#
# Run it after adding or changing a tool, and commit the file with the change.
# python -m unittest discover app/tests fails while it is out of date
# (test_mcp_parity.py), the way it does for config/openapi.json.
#
#   scripts/mcp_json.sh
set -euo pipefail
cd "$( dirname "${BASH_SOURCE[0]}" )/.."
python=.venv/bin/python
[ -x "$python" ] || python=python3
"$python" -m app.mcp.manifest
