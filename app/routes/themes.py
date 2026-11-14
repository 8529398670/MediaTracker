"""The Appearance screen's routes: someone's own themes, and the defaults an
admin sets for everyone who has not made their own. See app/models/themes.py.
Each save sends the whole list, so an undo is the same call with the list from
before."""
from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

import msgspec
from msgspec import UNSET, Meta, UnsetType
from starlette.requests import Request

from app.apidocs import ADMIN, Reply, route
from app.apidocs import Request as RequestType
from app.core.logs import KIND_ADMIN, KIND_AUTH
from app.core.security import actor_from
from app.models import themes, users
from app.routes.helpers import Refused, get_store
from app.routes.logs import audit

OVERRIDES = "Worked-out colors replaced by name: text, accent, accentFg, second, secondFg, secondText, link, navLink, background, surface, nested, chrome, info, infoBorder, border, and for each button variant V (Secondary, Success, Danger, Warning, Info, Light, Dark) btnV, btnVFg and btnVText. Leaving one out puts the readable color back."


class ThemeButton(Reply, kw_only=True, forbid_unknown_fields=True):
    """Theme.buttonChoices in theme.js; a choice left out is the default."""

    shape: Literal["square", "soft", "rounded", "pill"] | UnsetType = UNSET
    weight: Literal["normal", "medium", "bold"] | UnsetType = UNSET
    depth: Literal["flat", "raised", "glossy"] | UnsetType = UNSET
    case: Literal["normal", "upper"] | UnsetType = UNSET


class ThemeColors(Reply, kw_only=True):
    """One mode's colors."""

    accent: Annotated[str, Meta(description="The main color: what you can press.")]
    second: Annotated[str, Meta(description="Says where you are: active nav item, headings, info.")]
    background: Annotated[str, Meta(description="The page. Left out: the mode's own.")] | UnsetType = UNSET
    surface: Annotated[str, Meta(description="Cards. Left out: the mode's own.")] | UnsetType = UNSET
    overrides: Annotated[dict[str, str], Meta(description=OVERRIDES)] | UnsetType = UNSET


class Theme(ThemeColors, kw_only=True):
    """A theme as it is stored and sent. The model (themes.check) checks the
    rest: ids, names, colors, overrides."""

    api_name: ClassVar[str] = "Theme"
    api_doc: ClassVar[str] = "A color scheme on the Appearance screen. Colors are #rrggbb. Anything not given is worked out by static/js/theme.js at readable contrast."
    id: Annotated[str, Meta(description="Lower-case letters, digits, - and _, up to 32.")]
    name: Annotated[str, Meta(description="1 to 60 characters.")]
    mode: Literal["light", "dark"]
    button: Annotated[ThemeButton | None, Meta(description="How the theme's buttons look. A choice left out is the default (rounded, normal, raised, normal).")] | UnsetType = UNSET
    # The colors kept for the mode not in use (Theme.setMode in theme.js): a
    # light theme's dark, a dark theme's light. Switching mode swaps them in.
    light: Annotated[ThemeColors | None, Meta(description="A dark theme's colors for light mode, kept while it is dark. Switching the theme to light swaps them in.")] | UnsetType = UNSET
    dark: Annotated[ThemeColors | None, Meta(description="A light theme's colors for dark mode, kept while it is light. Switching the theme to dark swaps them in. A light theme's light (or a dark theme's dark) is dropped.")] | UnsetType = UNSET


def theme_list(stored: list[dict[str, Any]] | None) -> list[Theme] | None:
    """A stored list (already checked by themes.check) as replies carry it."""
    return None if stored is None else msgspec.convert(stored, list[Theme])


def _plain(wanted: list[Theme] | None) -> list[dict[str, Any]] | None:
    """A requested list as themes.check reads it."""
    return None if wanted is None else msgspec.to_builtins(wanted)


class SetMyThemes(RequestType):
    themes: Annotated[list[Theme] | None, Meta(description="Your whole list, 1 to 40 themes. null goes back to following the app's defaults.")] = None
    theme_id: Annotated[str, Meta(description="The theme you use.")] = ""


class SetMyThemesReply(Reply):
    ok: bool
    themes: Annotated[list[Theme] | None, Meta(description="What you now see; null while the built-in themes apply.")]
    themes_custom: bool
    theme_id: str


@route(
    "POST /api/account/themes", summary="Replace your own themes",
    tag="Account", feature="appearance",
    description="Replace your whole list of color themes (1 to 40) and pick the one you use. themes: null "
    "goes back to following the app's defaults. A theme is the Theme schema in the API reference "
    "(config/openapi.json): id, name, mode light|dark, accent, second, and optional colors as #rrggbb.",
    mcp_note="whoami shows the current list.",
    mcp="set_themes",
)
def set_my_themes(request: Request, body: SetMyThemes) -> SetMyThemesReply:
    """Replaces the caller's own list and pick, over HTTP or the MCP
    set_themes tool. themes null (or left out) goes back to following the
    defaults."""
    store = get_store(request)
    user_id = actor_from(request).user.id
    wanted = _plain(body.themes)
    try:
        found = themes.set_user_themes(store, user_id, wanted, body.theme_id)
    except themes.ThemesError as invalid:
        raise Refused(400, str(invalid)) from None
    if not found:
        raise Refused.internal("themes: the signed-in account has no record")
    user = users.get_user(store, user_id)
    listed, custom = themes.mine(store, user.themes if user else None)
    audit(request, KIND_AUTH, "changed own themes", {"count": len(wanted or []), "custom": custom})
    return SetMyThemesReply(ok=True, themes=theme_list(listed), themes_custom=custom, theme_id=user.theme_id if user else "")


class SetMyTheme(RequestType):
    theme_id: Annotated[str, Meta(description="A theme's id. Empty for the first in the list.")]


class SetMyThemeReply(Reply):
    ok: bool
    theme_id: str


@route(
    "POST /api/account/theme", summary="Pick your theme",
    tag="Account", feature="appearance",
    description="Switch to another theme from your list (or the defaults), by its id.",
    mcp="set_theme",
)
def set_my_theme(request: Request, body: SetMyTheme) -> SetMyThemeReply:
    """Changes only which theme the caller uses, over HTTP or the MCP
    set_theme tool."""
    try:
        found = themes.set_user_theme_id(get_store(request), actor_from(request).user.id, body.theme_id)
    except themes.ThemesError as invalid:
        raise Refused(400, str(invalid)) from None
    if not found:
        raise Refused.internal("themes: the signed-in account has no record")
    return SetMyThemeReply(ok=True, theme_id=body.theme_id)


class ThemeDefaultsReply(Reply):
    themes: Annotated[list[Theme] | None, Meta(description="null while the built-in themes apply.")]


@route(
    "GET /api/admin/theme-defaults", summary="Default themes",
    tag="Admin", role=ADMIN, feature="appearance", errors=(404,),
    description="The theme list everyone without their own list sees. themes is null while the built-in "
    "ones apply.",
    mcp="admin_get_theme_defaults", read_only=True,
)
def get_theme_defaults(request: Request) -> ThemeDefaultsReply:
    """themes is null while the built-in ones apply. Over HTTP and as the MCP
    admin_get_theme_defaults tool."""
    return ThemeDefaultsReply(themes=theme_list(themes.get_defaults(get_store(request))))


class SetThemeDefaults(RequestType):
    themes: Annotated[list[Theme] | None, Meta(description="1 to 40 themes. null goes back to the built-in ones.")] = None


class SetThemeDefaultsReply(Reply):
    ok: bool
    themes: list[Theme] | None


@route(
    "POST /api/admin/theme-defaults", summary="Replace the default themes",
    tag="Admin", role=ADMIN, feature="appearance", errors=(404,),
    description="Replace the theme list everyone without their own list sees, 1 to 40 themes in the Theme "
    "schema of the API reference. null puts the built-in themes back.",
    mcp="admin_set_theme_defaults",
)
def set_theme_defaults(request: Request, body: SetThemeDefaults) -> SetThemeDefaultsReply:
    """Replaces the list everyone without their own list sees, over HTTP or
    the MCP admin_set_theme_defaults tool. null goes back to the built-in
    themes."""
    try:
        saved = themes.set_defaults(get_store(request), _plain(body.themes))
    except themes.ThemesError as invalid:
        raise Refused(400, str(invalid)) from None
    audit(request, KIND_ADMIN, "changed the default themes", {"count": len(saved or []), "built_in": saved is None})
    return SetThemeDefaultsReply(ok=True, themes=theme_list(saved))
