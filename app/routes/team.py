"""A non-admin view of who else uses the app.

It exists so that ordinary features -- an assignee dropdown, an owner picker,
an @mention list -- do not need admin rights just to render a list of names.
It returns id and display name only; role and disabled status stay behind the
admin endpoint, because those are facts about who administers the app rather
than about who you can hand work to.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.db import Store
from app.models import users
from app.routes.helpers import get_store, run


async def list_team(request: Request) -> Response:
    return JSONResponse(await run(team_rows, get_store(request)))


def team_rows(store: Store) -> list[dict[str, Any]]:
    """Shared with the MCP list_team tool."""
    return [{"id": user.id, "display_name": user.display_name} for user in users.list_users(store) if not user.disabled]
