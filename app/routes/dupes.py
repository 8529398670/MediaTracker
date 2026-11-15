"""Duplicates: the same work twice under two names. Finding them, merging
them (one undo step for the whole merge), and remembering "these are not the
same" for the whole family."""
from __future__ import annotations

from typing import Annotated, Any

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import PATH, Reply, route
from app.apidocs import Request as RequestType
from app.core.db import Store
from app.core.security import actor_from
from app.media import dupes, normalize
from app.models import library_cache, merges
from app.models.revision import ConflictError, NotFoundError
from app.routes.helpers import Refused, get_store
from app.routes.titles import TAG, Record, TitlePath

TitleIDs = Annotated[list[str], Meta(description="Title ids, from GET /api/library (search_library over MCP).")]


def groups(store: Store) -> list[dict[str, Any]]:
    snapshot = library_cache.get(store)
    found = dupes.duplicate_groups(snapshot.live_titles(), merges.dismissed_pairs(store))
    return [{**group, "titles": [snapshot.titles[ident] for ident in group["ids"]]} for group in found]


class DupeGroups(Reply, kw_only=True):
    groups: Annotated[list[Record], Meta(description="Each group: its ids, why they look alike, and the titles.")]


@route(
    "GET /api/dupes", summary="Possible duplicates",
    tag=TAG,
    description="Groups of library titles that look like the same work, minus pairs marked as different.",
    mcp="list_duplicates", read_only=True,
)
def list_groups(request: Request) -> DupeGroups:
    return DupeGroups(groups=groups(get_store(request)))


class Dismiss(RequestType, kw_only=True):
    ids: TitleIDs


class Pairs(Reply, kw_only=True):
    pairs: Annotated[list[str], Meta(description="The pairs recorded: what undismissing takes back.")]


@route(
    "POST /api/dupes/dismiss", summary="Not duplicates",
    tag=TAG,
    description="Mark two or more titles as not the same, for the whole family. Returns the pairs, which "
    "undismissing takes back.",
    mcp="dismiss_duplicates",
)
def dismiss(request: Request, body: Dismiss) -> Pairs:
    ids = [ident for ident in body.ids if normalize.valid_title_id(ident)]
    if len(ids) < 2:
        raise Refused(400, "two or more titles")
    return Pairs(pairs=merges.dismiss(get_store(request), ids, actor_from(request).user.id))


class Undismiss(RequestType, kw_only=True):
    pairs: Annotated[list[str], Meta(description="Pairs from dismissing.")]


class OkReply(Reply, kw_only=True):
    ok: bool


@route(
    "POST /api/dupes/undismiss", summary="Undo not duplicates",
    tag=TAG,
    description="Forget pairs that dismissing recorded.",
    mcp="undismiss_duplicates",
)
def undismiss(request: Request, body: Undismiss) -> OkReply:
    merges.undismiss(get_store(request), [str(pair) for pair in body.pairs])
    return OkReply(ok=True)


class Merge(TitlePath, kw_only=True):
    drop_ids: TitleIDs


class MergeReply(Reply, kw_only=True):
    merge_id: Annotated[str, Meta(description="What undoing the merge takes.")]
    title: Record
    changed: Annotated[list[str], Meta(description="The kept title's fields the merge filled in.")]


@route(
    "POST /api/titles/{title_id}/merge", summary="Merge duplicates",
    tag=TAG, errors=(404,),
    description="Keep title_id and fold the drop_ids into it: everyone's state, playlists and details move "
    "over and the others are deleted. One undo step: undo the merge with the merge_id returned.",
    mcp="merge_titles", destructive=True,
    bulk=True,
)
def merge(request: Request, body: Merge) -> MergeReply:
    drop = [ident for ident in body.drop_ids if normalize.valid_title_id(ident)]
    try:
        return MergeReply(**merges.merge(get_store(request), body.title_id, drop, actor_from(request).user.id))
    except NotFoundError:
        raise Refused(404, "no such title") from None
    except ValueError as error:
        raise Refused(400, str(error)) from None


class MergePath(RequestType, kw_only=True):
    merge_id: Annotated[str, PATH, Meta(description="From merging titles.")]


@route(
    "POST /api/merges/{merge_id}/undo", summary="Undo a merge",
    tag=TAG, errors=(404, 409),
    description="Put a merge back as it was: the dropped titles, and everyone's state and playlists.",
    mcp="undo_merge",
    bulk=True,
)
def undo_merge(request: Request, body: MergePath) -> OkReply:
    try:
        merges.undo_merge(get_store(request), body.merge_id)
    except NotFoundError:
        raise Refused(404, "no such merge") from None
    except ConflictError as error:
        raise Refused(409, "changed_elsewhere", current=error.current) from None
    return OkReply(ok=True)
