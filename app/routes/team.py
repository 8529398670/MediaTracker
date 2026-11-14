"""A non-admin view of who else uses the app.

It exists so that ordinary features -- an assignee dropdown, an owner picker,
an @mention list -- do not need admin rights just to render a list of names.
It returns id and display name only; role and disabled status stay behind the
admin endpoint, because those are facts about who administers the app rather
than about who you can hand work to.
"""
from __future__ import annotations

from typing import ClassVar

from starlette.requests import Request

from app.apidocs import Reply, route
from app.models import users
from app.routes.helpers import Page, Paged, cut_page, get_store


class Member(Reply):
    """Someone with an active account, as anyone signed in may see them."""

    api_name: ClassVar[str] = "Member"
    id: int
    display_name: str


class ListTeamReply(Paged):
    members: list[Member]


@route(
    "GET /api/team", summary="List team",
    tag="Account",
    description="People with an active account, a page at a time: id and display name.",
    mcp_note="Use the id wherever another tool asks for a user. next is the offset of the following page, "
    "or null on the last one.",
    mcp="list_team", read_only=True,
)
def list_team(request: Request, body: Page) -> ListTeamReply:
    """Over HTTP and as the MCP list_team tool."""
    rows = [Member(id=user.id, display_name=user.display_name) for user in users.list_users(get_store(request)) if not user.disabled]
    page = cut_page(rows, body)
    return ListTeamReply(members=page.pop("rows"), **page)
