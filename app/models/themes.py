"""Themes: the color schemes on the Appearance screen. There are two lists:

- the app's defaults, which an admin edits. Nothing stored means the built-in
  themes in static/js/theme.js.
- each person's own, on their account. None means they follow the defaults,
  including later changes to them; the first time they change something the
  browser saves the whole list, and from then on it is theirs.

A theme is a mode and a few colors, from which theme.js works out the rest
(text, links, borders, tints) at readable contrast. It can also keep its colors
for the mode not in use (a light theme's "dark", a dark theme's "light"), which
switching mode swaps in (Theme.setMode in theme.js). Overrides replace any of
those worked-out colors by name; dropping one puts the safe color back.

A saved list also keeps which built-in themes it has seen: the highest
"since" in theme.js's built-in list when it was saved ("builtins"). The
browser adds any built-in theme newer than that to the list it shows, so a
theme added to the app later reaches people with a list of their own, while
one they deleted stays deleted.

The server checks the shape only. It does not know the list of built-in
themes, and it does not judge contrast -- an unreadable color is the person's
own choice, and the screen warns them."""
from __future__ import annotations

import re
from typing import Any

from app.core.db import BUCKET_META, BUCKET_USERS, Record, Store

MAX_THEMES = 40
MAX_THEME_NAME = 60
META_THEME_DEFAULTS_KEY = "theme_defaults"
# Bounds "builtins": far above any real count of built-in themes.
MAX_THEME_BUILTINS = 1000

_ID = re.compile(r"[a-z0-9_-]{1,32}")
_COLOR = re.compile(r"#[0-9a-f]{6}")
# The fields of Theme.colors() in theme.js that an override may replace.
OVERRIDE_FIELDS = frozenset({
    "text", "accent", "accentFg", "accentText", "second", "secondFg", "secondText", "link", "navLink",
    "background", "surface", "nested", "chrome", "info", "infoBorder", "border",
    "rowOdd", "rowEven",
}) | frozenset(
    # Theme.variants: each button variant's fill, label and outline.
    f"btn{variant}{part}"
    for variant in ("Secondary", "Success", "Danger", "Warning", "Info", "Light", "Dark")
    for part in ("", "Fg", "Text")
)
# Theme.buttonChoices in theme.js; a choice left out is the default.
BUTTON_CHOICES = {
    "shape": frozenset({"square", "soft", "rounded", "pill"}),
    "weight": frozenset({"normal", "medium", "bold"}),
    "depth": frozenset({"flat", "raised", "glossy"}),
    "case": frozenset({"normal", "upper"}),
}


class ThemesError(ValueError):
    """What is wrong with a list of themes, worded for the caller."""


def valid_id(theme_id: object) -> bool:
    return isinstance(theme_id, str) and _ID.fullmatch(theme_id) is not None


def _color(value: object, where: str, optional: bool = False) -> str:
    text = value.lower() if isinstance(value, str) else None
    if optional and (value is None or text == ""):
        return ""
    if text is None or _COLOR.fullmatch(text) is None:
        raise ThemesError(f"{where} is not a #rrggbb color")
    return text


def _colors(source: dict[str, Any], where: str) -> dict[str, Any]:
    """One mode's colors, checked and in lower case."""
    tidy: dict[str, Any] = {
        "accent": _color(source.get("accent"), f"{where}: accent"),
        "second": _color(source.get("second"), f"{where}: second"),
    }
    for optional in ("background", "surface"):
        value = _color(source.get(optional), f"{where}: {optional}", optional=True)
        if value:
            tidy[optional] = value
    overrides = source.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ThemesError(f"{where}: overrides must be an object")
    kept: dict[str, str] = {}
    for field, value in overrides.items():
        if field not in OVERRIDE_FIELDS:
            raise ThemesError(f"{where}: no color called {field!r}")
        kept[field] = _color(value, f"{where}: {field}")
    if kept:
        tidy["overrides"] = kept
    return tidy


def _button(value: object, theme_id: str) -> dict[str, str]:
    """A theme's button choices, checked; empty when none is set."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ThemesError(f"theme {theme_id}: button must be an object")
    kept: dict[str, str] = {}
    for key, choice in value.items():
        if key not in BUTTON_CHOICES:
            raise ThemesError(f"theme {theme_id}: no button setting called {key!r}")
        text = choice.strip().lower() if isinstance(choice, str) else None
        if text == "":
            continue
        if text not in BUTTON_CHOICES[key]:
            raise ThemesError(f"theme {theme_id}: button {key} {choice!r} is not one of the choices")
        kept[key] = text
    return kept


def check(themes: object) -> list[dict[str, Any]]:
    """The list, checked before it replaces a stored one, and tidied: names
    trimmed, colors in lower case. ThemesError if it cannot be stored."""
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
        tidy: dict[str, Any] = {"id": theme_id, "name": name, "mode": mode}
        tidy.update(_colors(theme, f"theme {theme_id}"))
        # Only the mode not in use is kept; one for the mode in use means nothing.
        other = "dark" if mode == "light" else "light"
        if theme.get(other) is not None:
            if not isinstance(theme[other], dict):
                raise ThemesError(f"theme {theme_id}: {other} must be an object")
            tidy[other] = _colors(theme[other], f"theme {theme_id} {other}")
        button = _button(theme.get("button"), theme_id)
        if button:
            tidy["button"] = button
        cleaned.append(tidy)
    return cleaned


def check_builtins(builtins: object) -> int:
    """A list's "builtins": 0 to MAX_THEME_BUILTINS."""
    if isinstance(builtins, bool) or not isinstance(builtins, int) or not 0 <= builtins <= MAX_THEME_BUILTINS:
        raise ThemesError(f"builtins is 0 to {MAX_THEME_BUILTINS}")
    return builtins


def get_defaults(store: Store) -> list[dict[str, Any]] | None:
    """The admin's list, or None when none has been saved and the built-in
    themes apply."""
    return get_defaults_seen(store)[0]


def get_defaults_seen(store: Store) -> tuple[list[dict[str, Any]] | None, int]:
    """The admin's list (None: the built-in themes) and which built-in themes
    it has seen. A list saved before builtins existed has 0, the first ones."""
    record = store.get(BUCKET_META, META_THEME_DEFAULTS_KEY)
    if record is None:
        return None, 0
    return record.get("themes"), record.get("builtins", 0)


def set_defaults(store: Store, themes: object, builtins: object = 0) -> list[dict[str, Any]] | None:
    """Replaces the admin's list and which built-in themes it has seen. None
    goes back to the built-in themes."""
    if themes is None:
        store.delete(BUCKET_META, META_THEME_DEFAULTS_KEY)
        return None
    cleaned = check(themes)
    seen = check_builtins(builtins)
    store.put(BUCKET_META, META_THEME_DEFAULTS_KEY, {"themes": cleaned, "builtins": seen})
    return cleaned


def _theme_id(theme_id: object) -> str:
    if theme_id is None or theme_id == "":
        return ""
    if not valid_id(theme_id):
        raise ThemesError("not a theme id")
    return str(theme_id)


def set_user_themes(store: Store, user_id: int, themes: object, theme_id: object, builtins: object = 0) -> bool:
    """Replaces someone's own list, which built-in themes it has seen, and
    their pick. None themes go back to following the defaults. False if there
    is no such account."""
    cleaned = None if themes is None else check(themes)
    seen = 0 if themes is None else check_builtins(builtins)
    chosen = _theme_id(theme_id)

    def mutate(record: Record) -> None:
        if cleaned is None:
            record.pop("themes", None)
            record.pop("themes_builtins", None)
        else:
            record["themes"] = cleaned
            record["themes_builtins"] = seen
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


def mine(store: Store, user_themes: list[dict[str, Any]] | None, user_builtins: int = 0) -> tuple[list[dict[str, Any]] | None, bool, int]:
    """What /api/me says about someone's themes: their own list, else the
    defaults, else None for the built-in ones; whether it is their own; and
    which built-in themes that list has seen."""
    if user_themes is not None:
        return user_themes, True, user_builtins
    listed, seen = get_defaults_seen(store)
    return listed, False, seen
