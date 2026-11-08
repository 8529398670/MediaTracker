"""The schema: every key config.yaml can hold, in defaults.yaml's order, with
its type, default, help and apply mode. The Settings screen is built from it,
and config_live.Holder.save checks submitted values against it.

None of it is written down twice. The keys and types come from the
dataclasses in config.py, the defaults and the order from defaults.yaml, and
the help and apply mode from defaults.yaml's comments -- so the text a person
reads in config.yaml is the text the Settings screen shows, and the tag that
says a key applies live is the one the server acts on.

Apply modes are tags in those comments:

    [live]     the running server picks it up (see config_live.live_config)
    [restart]  saved, but only read at startup
    [scripts]  read by docker/run.sh, never the server

A tag at the end of a key's line wins; then one in the comment above the key
(or above the run of keys it belongs to); then one in the comment above its
section. An untagged key is treated as [restart], the safe answer, and
test_config_schema.py fails until it is tagged.

server/config/schema.go is the same for the Go template.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from functools import lru_cache
from typing import Any

import yaml

from app.core import config
from app.core.config import ConfigError
from app.core.yaml_edit import HandEditError, _Editor, _Text, scan_flow_end

MODE_LIVE = "live"
MODE_RESTART = "restart"
MODE_SCRIPTS = "scripts"

_TAG = re.compile(r"\[(live|restart|scripts)\]")
_TYPES = {"bool": "bool", "int": "int", "str": "string", "list[str]": "list"}

# Limits on a submitted value, before validate() has its say. They keep a
# request from writing an enormous config.yaml.
MAX_STRING_LENGTH = 1000
MAX_LIST_ITEMS = 100


@dataclass(frozen=True)
class KeySchema:
    path: str  # "server.port"
    section: str
    name: str
    type: str  # bool, int, string or list
    default: Any
    help: str
    mode: str
    # False when no comment gave mode and it fell back to restart.
    tagged: bool
    # The raw comment lines above the key in defaults.yaml and the comment
    # at the end of its line, for edit_yaml when it adds the key to a file.
    comment_above: tuple[str, ...] = field(default=(), repr=False)
    comment_inline: str = field(default="", repr=False)


@dataclass(frozen=True)
class SectionSchema:
    name: str
    help: str
    keys: tuple[KeySchema, ...]


@lru_cache(maxsize=1)
def schema() -> tuple[SectionSchema, ...]:
    """Worked out once, from the shipped defaults."""
    return _build_schema(config.DEFAULTS_PATH.read_text(encoding="utf-8"))


def schema_key(path: str) -> KeySchema | None:
    for section in schema():
        for key in section.keys:
            if key.path == path:
                return key
    return None


def schema_comments(path: str) -> tuple[list[str], str]:
    """edit_yaml's comments function: what defaults.yaml says about a key, so
    a key added to a sparse config.yaml arrives documented."""
    key = schema_key(path)
    if key is None:
        return [], ""
    return list(key.comment_above), key.comment_inline


def field_types() -> dict[str, str]:
    types = {}
    for section_name, section_type in config.SECTIONS.items():
        for item in fields(section_type):
            path = f"{section_name}.{item.name}"
            if item.name in config.DEPRECATED.get(section_name, set()):
                continue
            types[path] = _TYPES[str(item.type)]
    return types


def _build_schema(raw: str) -> tuple[SectionSchema, ...]:
    values = flatten(config.defaults())
    types = field_types()
    text = _Text(raw)
    root = yaml.compose(text.body, Loader=yaml.SafeLoader)
    if not isinstance(root, yaml.MappingNode):
        raise ConfigError("defaults.yaml must be a mapping of sections")
    editor = _Editor(text, root, None)

    sections = []
    for section_key, section in root.value:
        section_line = section_key.start_mark.line
        section_comment = _comment_block(text, section_line - 1, -1)
        section_tag = _find_tag(section_comment)
        keys = []
        for key_node, value_node in section.value:
            path = f"{section_key.value}.{key_node.value}"
            if path not in types:
                raise ConfigError(f"defaults.yaml has {path}, which config.py's dataclasses do not")
            key_line = key_node.start_mark.line
            own = _comment_block(text, key_line - 1, section_line)
            paragraph = own
            if not paragraph:
                # A key in a run of keys under one comment shares it.
                above = key_line - 1
                while above > section_line and _is_content(text.line(above)):
                    above -= 1
                paragraph = _comment_block(text, above, section_line)

            inline = ""
            try:
                colon = editor.colon_end(path, key_node)
                line_end = text.line_end(key_line)
                rest_start = colon
                if isinstance(value_node, yaml.ScalarNode) and value_node.start_mark.line == key_line:
                    rest_start = editor.scalar_span(path, value_node)[1]
                elif isinstance(value_node, yaml.SequenceNode) and value_node.flow_style:
                    end = scan_flow_end(text.body, value_node.start_mark.index)
                    if end <= line_end:
                        rest_start = end
                rest = text.body[rest_start:line_end]
                if "#" in rest:
                    inline = rest[rest.index("#"):].strip()
            except (HandEditError, ValueError):
                pass

            mode = _find_tag([inline]) or _find_tag(paragraph) or section_tag
            keys.append(KeySchema(
                path=path,
                section=section_key.value,
                name=key_node.value,
                type=types[path],
                default=values[path],
                help=_help_text(paragraph, inline),
                mode=mode or MODE_RESTART,
                tagged=bool(mode),
                comment_above=tuple(own),
                comment_inline=inline,
            ))
        sections.append(SectionSchema(name=section_key.value, help=_help_text(section_comment, ""), keys=tuple(keys)))
    return tuple(sections)


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return stripped != "" and not stripped.startswith("#")


def _comment_block(text: _Text, last: int, floor: int) -> list[str]:
    """The run of comment lines ending at line `last`, going up no further
    than line `floor` (exclusive). Stripped, "#" kept."""
    first = last
    while first > floor and text.line(first).strip().startswith("#"):
        first -= 1
    return [text.line(number).strip() for number in range(first + 1, last + 1)]


def _find_tag(lines: list[str]) -> str:
    for line in lines:
        match = _TAG.search(line)
        if match:
            return match.group(1)
    return ""


def _help_text(lines: list[str], inline: str) -> str:
    """Comment lines as the Settings screen shows them: "#" and tags
    removed, and the lines of each paragraph joined, since they were only
    wrapped to fit the file. An indented line (an example) keeps a line of
    its own, and the comment at the end of the key's line goes last, on its
    own."""
    out: list[str] = []
    for line in lines:
        line = line[1:] if line.startswith("#") else line
        line = line[1:] if line.startswith(" ") else line
        line = _TAG.sub("", line).rstrip(" ")
        if line.strip() == "":
            out.append("")
        elif not out or out[-1] == "" or line.startswith(" ") or out[-1].startswith(" "):
            out.append(line)
        else:
            out[-1] += " " + line
    inline = _TAG.sub("", inline[1:] if inline.startswith("#") else inline).strip()
    if inline:
        out.append(inline)
    help_text = "\n".join(out).strip("\n ")
    while "\n\n\n" in help_text:
        help_text = help_text.replace("\n\n\n", "\n\n")
    return help_text


# ---------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------


def flatten(file: config.File) -> dict[str, Any]:
    """A File as "section.key" -> value: bool, int, str or list[str] (a
    copy, never shared). server.secret_key is left out everywhere: it is not
    a setting any more, only something to migrate."""
    values: dict[str, Any] = {}
    for section_name in config.SECTIONS:
        section = getattr(file, section_name)
        for item in fields(section):
            if item.name in config.DEPRECATED.get(section_name, set()):
                continue
            value = getattr(section, item.name)
            values[f"{section_name}.{item.name}"] = list(value) if isinstance(value, (list, tuple)) else value
    return values


def diff(old: config.File, new: config.File) -> list[dict[str, Any]]:
    """What changed from old to new, in schema order."""
    before, after = flatten(old), flatten(new)
    changes = []
    for section in schema():
        for key in section.keys:
            if before[key.path] != after[key.path]:
                changes.append({"key": key.path, "old": before[key.path], "new": after[key.path], "apply": key.mode})
    return changes


def keys_in_file(raw: str) -> set[str]:
    """Which keys a config.yaml sets itself, as opposed to leaving to
    defaults.yaml."""
    try:
        root = yaml.compose(raw.lstrip("﻿"), Loader=yaml.SafeLoader)
    except yaml.YAMLError:
        return set()
    if not isinstance(root, yaml.MappingNode):
        return set()
    present = set()
    for section_key, section in root.value:
        if isinstance(section, yaml.MappingNode):
            present |= {f"{section_key.value}.{key.value}" for key, _ in section.value}
    return present


def coerce(key: KeySchema, value: Any) -> Any:
    """Check a value as decoded from JSON against a key's type, and return it
    typed the way flatten() types it."""

    def bad(want: str) -> ConfigError:
        return ConfigError(f"{key.path} must be {want}")

    if key.type == "bool":
        if not isinstance(value, bool):
            raise bad("true or false")
        return value
    if key.type == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise bad("a whole number")
        if isinstance(value, float):
            if value != int(value):
                raise bad("a whole number")
            value = int(value)
        if not -(1 << 31) <= value <= (1 << 31) - 1:
            raise bad("a whole number in range")
        return value
    if key.type == "string":
        if not isinstance(value, str) or len(value) > MAX_STRING_LENGTH:
            raise bad(f"text of at most {MAX_STRING_LENGTH} characters")
        return value
    if key.type == "list":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise bad("a list of text")
        if len(value) > MAX_LIST_ITEMS:
            raise bad(f"a list of at most {MAX_LIST_ITEMS} items")
        if any(len(item) > MAX_STRING_LENGTH for item in value):
            raise bad(f"a list of items of at most {MAX_STRING_LENGTH} characters")
        return [item.strip() for item in value if item.strip()]
    raise ConfigError(f"{key.path} has unknown type {key.type!r}")


def parse_value(key: KeySchema, text: str) -> Any:
    """A value typed on a command line (`config set`): true or false, a
    number, text, or a list written as [a, b] or a,b ("" or [] for an empty
    one)."""
    if key.type == "bool":
        lowered = text.strip().lower()
        if lowered in ("true", "1", "t"):
            return True
        if lowered in ("false", "0", "f"):
            return False
        raise ConfigError(f"{key.path} must be true or false")
    if key.type == "int":
        try:
            return int(text.strip())
        except ValueError:
            raise ConfigError(f"{key.path} must be a whole number") from None
    if key.type == "list":
        stripped = text.strip()
        if stripped.startswith("["):
            try:
                parsed = yaml.safe_load(stripped)
            except yaml.YAMLError:
                parsed = None
            if not isinstance(parsed, list):
                raise ConfigError(f"{key.path} must be a list like [a, b]")
            items = [str(item) for item in parsed]
        else:
            items = stripped.split(",") if stripped else []
        return coerce(key, items)
    return coerce(key, text)
