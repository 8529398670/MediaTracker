"""Themes: the colour schemes on the Appearance screen. There are two lists:

- the app's defaults, which an admin edits. Nothing stored means the built-in
  themes in static/js/theme.js.
- each person's own, on their account. None means they follow the defaults,
  including later changes to them; the first time they change something the
  browser saves the whole list, and from then on it is theirs.

A theme is a mode and a few colours, from which theme.js works out the rest
(text, links, borders, tints) at readable contrast. Overrides replace any of
those worked-out colours by name; dropping one puts the safe colour back.

The server checks the shape only. It does not know the list of built-in
themes, and it does not judge contrast -- an unreadable colour is the person's
own choice, and the screen warns them."""
from __future__ import annotations

import re
from typing import Any

from app.core.db import BUCKET_META, BUCKET_USERS, Record, Store

MAX_THEMES = 40
MAX_THEME_NAME = 60
META_THEME_DEFAULTS_KEY = "theme_defaults"

_ID = re.compile(r"[a-z0-9_-]{1,32}")
_COLOUR = re.compile(r"#[0-9a-f]{6}")
# The fields of Theme.colours() in theme.js that an override may replace.
OVERRIDE_FIELDS = frozenset({
    "text", "accent", "accentFg", "second", "secondFg", "secondText", "link", "navLink",
    "background", "surface", "nested", "chrome", "info", "infoBorder", "border",
})


class ThemesError(ValueError):
    """What is wrong with a list of themes, worded for the caller."""


def valid_id(theme_id: object) -> bool:
    return isinstance(theme_id, str) and _ID.fullmatch(theme_id) is not None


def _colour(value: object, where: str, optional: bool = False) -> str:
    text = value.lower() if isinstance(value, str) else None
    if optional and (value is None or text == ""):
        return ""
    if text is None or _COLOUR.fullmatch(text) is None:
        raise ThemesError(f"{where} is not a #rrggbb colour")
    return text


def check(themes: object) -> list[dict[str, Any]]:
    """The list, checked before it replaces a stored one, and tidied: names
    trimmed, colours in lower case. ThemesError if it cannot be stored."""
    if not isinstance(themes, list) or not themes:
        raise ThemesError("at least one theme")
    if len(themes) > MAX_THEMES:
        raise ThemesError(f"at most {MAX_THEMES} themes")
    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    for theme in themes:
        if not isinstance(theme, dict):
            raise ThemesError("each theme must be an object")
        theme_id = theme.get("id")
        if not valid_id(theme_id):
            raise ThemesError(f"theme id {theme_id!r}: letters, digits, - and _, up to 32")
        if theme_id in seen:
            raise ThemesError(f"theme id {theme_id!r} used twice")
        seen.add(theme_id)
        name = theme.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name or len(name) > MAX_THEME_NAME:
            raise ThemesError(f"theme {theme_id}: a name of 1 to {MAX_THEME_NAME} characters")
        mode = theme.get("mode")
        if mode not in ("light", "dark"):
            raise ThemesError(f"theme {theme_id}: mode is light or dark")
        tidy: dict[str, Any] = {
            "id": theme_id,
            "name": name,
            "mode": mode,
            "accent": _colour(theme.get("accent"), f"theme {theme_id}: accent"),
            "second": _colour(theme.get("second"), f"theme {theme_id}: second"),
        }
        for optional in ("background", "surface"):
            value = _colour(theme.get(optional), f"theme {theme_id}: {optional}", optional=True)
            if value:
                tidy[optional] = value
        overrides = theme.get("overrides") or {}
        if not isinstance(overrides, dict):
            raise ThemesError(f"theme {theme_id}: overrides must be an object")
        kept: dict[str, str] = {}
        for field, value in overrides.items():
            if field not in OVERRIDE_FIELDS:
                raise ThemesError(f"theme {theme_id}: no colour called {field!r}")
            kept[field] = _colour(value, f"theme {theme_id}: {field}")
        if kept:
            tidy["overrides"] = kept
        cleaned.append(tidy)
    return cleaned


def get_defaults(store: Store) -> list[dict[str, Any]] | None:
    """The admin's list, or None when none has been saved and the built-in
    themes apply."""
    record = store.get(BUCKET_META, META_THEME_DEFAULTS_KEY)
    return None if record is None else record.get("themes")


def set_defaults(store: Store, themes: object) -> list[dict[str, Any]] | None:
    """Replaces the admin's list. None goes back to the built-in themes."""
    if themes is None:
        store.delete(BUCKET_META, META_THEME_DEFAULTS_KEY)
        return None
    cleaned = check(themes)
    store.put(BUCKET_META, META_THEME_DEFAULTS_KEY, {"themes": cleaned})
    return cleaned


def _theme_id(theme_id: object) -> str:
    if theme_id is None or theme_id == "":
        return ""
    if not valid_id(theme_id):
        raise ThemesError("not a theme id")
    return str(theme_id)


def set_user_themes(store: Store, user_id: int, themes: object, theme_id: object) -> bool:
    """Replaces someone's own list and pick. None themes go back to following
    the defaults. False if there is no such account."""
    cleaned = None if themes is None else check(themes)
    chosen = _theme_id(theme_id)

    def mutate(record: Record) -> None:
        if cleaned is None:
            record.pop("themes", None)
        else:
            record["themes"] = cleaned
        record["theme_id"] = chosen

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None


def set_user_theme_id(store: Store, user_id: int, theme_id: object) -> bool:
    """Changes only which theme someone uses. The id is not checked against
    their list: a list that follows the defaults can change under it, and the
    browser falls back to the first theme for an id it cannot find."""
    chosen = _theme_id(theme_id)

    def mutate(record: Record) -> None:
        record["theme_id"] = chosen

    return store.update_value(BUCKET_USERS, user_id, mutate) is not None


def mine(store: Store, user_themes: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]] | None, bool]:
    """What /api/me says about someone's themes: their own list, else the
    defaults, else None for the built-in ones; and whether it is their own."""
    if user_themes is not None:
        return user_themes, True
    return get_defaults(store), False
