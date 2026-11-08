"""Change single values in a config.yaml without re-serialising it.

Decoding into a dict and dumping it back would lose every comment, and the
comments are the documentation: config.yaml starts as a copy of defaults.yaml
precisely so that each setting explains itself where it is set. So instead
the file is composed only to find where each value sits (every PyYAML node
carries start and end marks), and the text there is replaced. Everything
else -- comments, blank lines, ordering, quoting elsewhere -- comes out
character for character as it went in.

What it handles:

    a scalar on its key's line   replaced in place; a trailing comment stays
    an empty value (key:)        the value is written after the colon
    a flow list [a, b]           replaced with a flow list
    a block list (- a lines)     its item lines are rewritten at the same
                                 indentation; an emptied one becomes []
    a key the file lacks         added at the end of its section, with the
                                 comment defaults.yaml has above it
    a section the file lacks     added at the end of the file

What it refuses, asking for a hand edit: anchors and aliases, explicit tags,
| and > block scalars, a value spread over several lines, and a section
written as a {flow: mapping}. None of these appear in a file that started
from defaults.yaml.

server/config/yamledit.go is the same algorithm for the Go template, and the
two are tested against the same cases (app/tests/yaml_edit_cases.json).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

import yaml

from app.core.config import ConfigError

# For a key edit_yaml has to add: the comment lines to put above it (each
# starting with "#", no indentation) and a trailing comment for its line.
CommentsFunc = Callable[[str], "tuple[list[str], str]"]

_NULL_TAG = "tag:yaml.org,2002:null"

# Identifies the comment that used to sit above server.secret_key, so
# deleting the key can take its explanation with it.
LEGACY_SECRET_MARKER = "64 hex characters"


class HandEditError(ConfigError):
    """The value is written in a way this editor does not rewrite; the
    message says which key."""


def edit_yaml(raw: str, edits: list[tuple[str, Any]], deletes: list[str], comments: CommentsFunc | None) -> str:
    """Apply edits ([("section.key", value)], values typed as
    config_schema.flatten types them), then remove the keys in deletes (used
    only to take server.secret_key out of an older config.yaml). Positions
    all come from one compose of the text as given, and the replacements are
    applied from the end of the file backwards so none moves another."""
    text = _Text(raw)
    try:
        root = yaml.compose(text.body, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise HandEditError(f"config.yaml is not valid YAML ({error}) -- edit it by hand") from None
    if root is not None and (not isinstance(root, yaml.MappingNode) or root.flow_style):
        raise HandEditError("config.yaml's top level must be a block mapping of sections -- edit it by hand")

    editor = _Editor(text, root, comments)
    for path, value in edits:
        editor.set(path, value)
    for path in deletes:
        editor.remove(path)
    editor.flush_insertions()
    return editor.apply()


# ---------------------------------------------------------------------------
# the text, with offsets for PyYAML's 0-based marks
# ---------------------------------------------------------------------------


class _Text:
    def __init__(self, raw: str) -> None:
        self.bom = raw.startswith("﻿")
        self.body = raw[1:] if self.bom else raw
        self.eol = "\r\n" if "\r\n" in self.body else "\n"
        self.lines: list[tuple[int, int]] = []
        start = 0
        for index, character in enumerate(self.body):
            if character != "\n":
                continue
            end = index
            if end > start and self.body[end - 1] == "\r":
                end -= 1
            self.lines.append((start, end))
            start = index + 1
        if start < len(self.body):
            self.lines.append((start, len(self.body)))

    def line(self, number: int) -> str:
        if number < 0 or number >= len(self.lines):
            return ""
        start, end = self.lines[number]
        return self.body[start:end]

    def line_end(self, number: int) -> int:
        return self.lines[number][1]


def _refuse(path: str, why: str) -> HandEditError:
    return HandEditError(f"{path} is {why} -- edit it by hand")


def _mapping_get(mapping: Any, name: str) -> tuple[Any, Any]:
    if not isinstance(mapping, yaml.MappingNode):
        return None, None
    for key, value in mapping.value:
        if key.value == name:
            return key, value
    return None, None


def _split(path: str) -> tuple[str, str]:
    parts = path.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ConfigError(f"{path!r} is not a section.key path")
    return parts[0], parts[1]


def _is_null(node: Any) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.tag == _NULL_TAG


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


class _Editor:
    def __init__(self, text: _Text, root: Any, comments: CommentsFunc | None) -> None:
        self.text = text
        self.root = root
        self.comments = comments
        self.ops: list[tuple[int, int, str]] = []
        # Keys to add, gathered per section so several land together and in
        # order: into an existing section, or a new one at the end of the file.
        self.pending: dict[str, list[tuple[str, Any]]] = {}

    # -- setting -------------------------------------------------------------

    def set(self, path: str, value: Any) -> None:
        section_name, key_name = _split(path)
        section_key, section = _mapping_get(self.root, section_name)
        if section_key is None or _is_null(section):
            self.pending.setdefault(section_name, []).append((path, value))
            return
        if not isinstance(section, yaml.MappingNode):
            raise _refuse(section_name, "not a mapping")
        if section.flow_style:
            raise _refuse(section_name, "written as a {flow: mapping}")
        key, node = _mapping_get(section, key_name)
        if key is None:
            self.pending.setdefault(section_name, []).append((path, value))
            return

        colon = self.colon_end(path, key)
        key_line = key.start_mark.line
        rest = self.text.body[colon : self.text.line_end(key_line)].strip()
        self.check_plain(path, rest, node)
        empty = rest == "" or rest.startswith("#")

        if isinstance(value, list):
            self.set_list(path, node, colon, empty, value)
            return
        encoded = encode_scalar(value, getattr(node, "style", None))
        if empty:
            if not _is_null(node):
                raise _refuse(path, "written on the lines below its key")
            self.ops.append((colon, colon, " " + encoded))
            return
        if not isinstance(node, yaml.ScalarNode):
            raise _refuse(path, "not a single value")
        start, end = self.scalar_span(path, node)
        self.ops.append((start, end, encoded))

    def check_plain(self, path: str, rest: str, node: Any) -> None:
        """PyYAML resolves anchors, aliases and tags away, so they are found
        in the text after the colon."""
        if rest.startswith(("&", "*")):
            raise _refuse(path, "written with an anchor or alias")
        if rest.startswith("!"):
            raise _refuse(path, "written with an explicit tag")
        if isinstance(node, yaml.ScalarNode) and node.style in ("|", ">"):
            raise _refuse(path, "a | or > block scalar")

    def set_list(self, path: str, node: Any, colon: int, empty: bool, items: list[str]) -> None:
        if _is_null(node):
            if not empty:
                start, end = self.scalar_span(path, node)
                self.ops.append((start, end, encode_flow_list(items)))
                return
            self.ops.append((colon, colon, " " + encode_flow_list(items)))
            return
        if not isinstance(node, yaml.SequenceNode):
            raise _refuse(path, "not a list")
        if node.flow_style:
            start = node.start_mark.index
            try:
                end = scan_flow_end(self.text.body, start)
            except ValueError as error:
                raise _refuse(path, str(error)) from None
            self.ops.append((start, end, encode_flow_list(items)))
            return
        first = last = -1
        for item in node.value:
            if not isinstance(item, yaml.ScalarNode):
                raise _refuse(path, "a list with items that are not single values")
            line = self.text.line(item.start_mark.line)
            before = line[: item.start_mark.column].rstrip()
            if before.endswith(("&", "*", "!")) or self.text.body[item.start_mark.index] in "&*!":
                raise _refuse(path, "written with an anchor, alias or tag")
            if item.style in ("|", ">"):
                raise _refuse(path, "a | or > block scalar")
            self.scalar_span(path, item)
            if first < 0:
                first = item.start_mark.line
            last = item.start_mark.line
        first_line = self.text.line(first)
        dash = first_line.find("-")
        if first < 0 or dash < 0:
            raise _refuse(path, "a list this editor cannot find the items of")
        prefix = first_line[:dash]
        start = self.text.lines[first][0]
        end = self.text.lines[last][1]
        if not items:
            # Drop the item lines, line endings included, and write [] on the
            # key's line instead.
            self.ops.append((start, self.next_line_start(last), ""))
            self.ops.append((colon, colon, " []"))
            return
        lines = [prefix + "- " + encode_string(item, None) for item in items]
        self.ops.append((start, end, self.text.eol.join(lines)))

    # -- removing ------------------------------------------------------------

    def remove(self, path: str) -> None:
        """Take a key's line out, and with it the comment above it when that
        comment is the one that described server.secret_key. A short note
        goes in its place, so a reader of an older file learns where the key
        went."""
        section_name, key_name = _split(path)
        _, section = _mapping_get(self.root, section_name)
        key, node = _mapping_get(section, key_name)
        if key is None:
            return
        key_line = key.start_mark.line
        if not isinstance(node, yaml.ScalarNode) or (node.value != "" and node.start_mark.line != key_line):
            raise _refuse(path, "not a single value on its key's line")
        if node.value != "":
            self.scalar_span(path, node)

        first = key_line
        above = key_line - 1
        while above >= 0 and self.text.line(above).strip().startswith("#"):
            above -= 1
        block = [self.text.line(number) for number in range(above + 1, key_line)]
        if LEGACY_SECRET_MARKER in "\n".join(block):
            first = above + 1
        indent = _indent_of(self.text.line(key_line))
        note = [
            indent + "# The secret key moved to secret.key, beside this file. Back the two up",
            indent + "# together with the app directory: nothing else can read the database.",
        ]
        self.ops.append((self.text.lines[first][0], self.text.lines[key_line][1], self.text.eol.join(note)))

    # -- adding --------------------------------------------------------------

    def flush_insertions(self) -> None:
        """The queued missing keys as text: appended to the end of their
        section, after its last value line, or as a new section at the end of
        the file."""
        appended: list[str] = []
        for section_name, edits in self.pending.items():
            section_key, section = _mapping_get(self.root, section_name)
            indent = "  "
            at = -1
            if section_key is None:
                pass
            elif isinstance(section, yaml.MappingNode) and section.value:
                indent = _indent_of(self.text.line(section.value[0][0].start_mark.line))
                at = self.text.line_end(self.last_content_line(section_key))
            else:
                # "section:" or "section: ~": drop an explicit null, add below.
                key_line = section_key.start_mark.line
                if section.start_mark.line == key_line and section.value != "":
                    colon = self.colon_end(section_name, section_key)
                    end = scan_plain_end(self.text.body, section.start_mark.index, self.text.line_end(key_line))
                    self.ops.append((colon, end, ""))
                at = self.text.line_end(key_line)
            lines = self.render_keys(edits, indent)
            if at < 0:
                appended += ["", section_name + ":"] + lines
                continue
            self.ops.append((at, at, self.text.eol + self.text.eol.join(lines)))
        if not appended:
            return
        end = len(self.text.body)
        prefix = self.text.eol if end > 0 and not self.text.body.endswith("\n") else ""
        if end == 0:
            appended = appended[1:]
        self.ops.append((end, end, prefix + self.text.eol.join(appended) + self.text.eol))

    def render_keys(self, edits: list[tuple[str, Any]], indent: str) -> list[str]:
        lines = []
        for path, value in edits:
            _, key_name = _split(path)
            above, inline = self.comments(path) if self.comments else ([], "")
            lines += [indent + comment for comment in above]
            encoded = encode_flow_list(value) if isinstance(value, list) else encode_scalar(value, None)
            line = f"{indent}{key_name}: {encoded}"
            if inline:
                line += "  " + inline
            lines.append(line)
        return lines

    def last_content_line(self, section_key: Any) -> int:
        """The last line of a section that is neither blank nor a comment:
        comments just above the next section describe that section."""
        section_line = section_key.start_mark.line
        following = [key.start_mark.line for key, _ in self.root.value if key.start_mark.line > section_line]
        last = (min(following) if following else len(self.text.lines)) - 1
        while last > section_line:
            stripped = self.text.line(last).strip()
            if stripped and not stripped.startswith("#"):
                return last
            last -= 1
        return last

    def next_line_start(self, line: int) -> int:
        if line + 1 < len(self.text.lines):
            return self.text.lines[line + 1][0]
        return len(self.text.body)

    # -- positions -----------------------------------------------------------

    def colon_end(self, path: str, key: Any) -> int:
        """The offset just past the ":" after a key."""
        line_end = self.text.line_end(key.start_mark.line)
        end = key.end_mark.index
        while end < line_end and self.text.body[end] in " \t":
            end += 1
        if end >= line_end or self.text.body[end] != ":":
            raise _refuse(path, "a key this editor cannot read")
        return end + 1

    def scalar_span(self, path: str, node: Any) -> tuple[int, int]:
        """Where a single-line scalar's text starts and ends."""
        start = node.start_mark.index
        line_end = self.text.line_end(node.start_mark.line)
        if node.style in ('"', "'"):
            try:
                return start, scan_quoted_end(self.text.body, start, line_end)
            except ValueError:
                raise _refuse(path, "a quoted value spread over several lines") from None
        end = scan_plain_end(self.text.body, start, line_end)
        if self.text.body[start:end].strip() != node.value:
            raise _refuse(path, "a value spread over several lines")
        return start, end

    def apply(self) -> str:
        ops = sorted(self.ops, key=lambda op: (op[0], op[1]), reverse=True)
        body = self.text.body
        limit = len(body) + 1
        for start, end, replacement in ops:
            if end > limit:
                raise ConfigError("two edits overlap in config.yaml")
            body = body[:start] + replacement + body[end:]
            # An insertion may share its offset with the next op's end.
            limit = start + 1 if start == end else start
        return ("﻿" if self.text.bom else "") + body


# ---------------------------------------------------------------------------
# scanning value text
# ---------------------------------------------------------------------------


def scan_quoted_end(body: str, start: int, line_end: int) -> int:
    """The closing quote of a "..." or '...' scalar starting at start, on
    the same line."""
    quote = body[start]
    index = start + 1
    while index < line_end:
        character = body[index]
        if quote == '"' and character == "\\":
            index += 2
            continue
        if character == quote and quote == "'" and index + 1 < line_end and body[index + 1] == "'":
            index += 2
            continue
        if character == quote:
            return index + 1
        index += 1
    raise ValueError("no closing quote on the same line")


def scan_plain_end(body: str, start: int, line_end: int) -> int:
    """Where a plain scalar ends: before a " #" comment, or at the end of the
    line, trailing spaces trimmed."""
    end = line_end
    for index in range(start, line_end):
        if body[index] == "#" and index > start and body[index - 1] in " \t":
            end = index
            break
    while end > start and body[end - 1] in " \t":
        end -= 1
    return end


def scan_flow_end(body: str, start: int) -> int:
    """The "]" that closes the "[" at start, skipping quoted strings and
    comments; a flow list may run over several lines."""
    depth = 0
    index = start
    while index < len(body):
        character = body[index]
        if character in "\"'":
            line_end = body.find("\n", index)
            index = scan_quoted_end(body, index, len(body) if line_end < 0 else line_end)
            continue
        if character == "#" and index > start and body[index - 1] in " \t\n":
            while index < len(body) and body[index] != "\n":
                index += 1
            continue
        if character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise ValueError("a [list] with no closing bracket")


# ---------------------------------------------------------------------------
# writing values
# ---------------------------------------------------------------------------

# What may be written without quotes: enough for addresses (127.0.0.1,
# 10.0.0.0/8), paths (./static) and names, and nothing YAML would read as
# anything but a string. See plain_safe.
_PLAIN = re.compile(r"^[A-Za-z0-9_./][A-Za-z0-9_./-]*$")
_NUMERIC = re.compile(r"^[-+]?(\.?[0-9][0-9_]*)(\.[0-9_]*)?([eE][-+]?[0-9]+)?$")
_YAML_WORDS = {"y", "yes", "n", "no", "on", "off", "true", "false", "null", "~"}


def plain_safe(value: str) -> bool:
    """True when value can be written bare and read back as the same string
    by both YAML 1.1 and 1.2 parsers -- so "yes", "1.5", "0x1F" and ".inf"
    are quoted even though some parsers would leave them alone."""
    if not _PLAIN.match(value) or value.lower() in _YAML_WORDS or _NUMERIC.match(value):
        return False
    try:
        decoded = yaml.safe_load("v: " + value)
    except yaml.YAMLError:
        return False
    return isinstance(decoded, dict) and decoded.get("v") == value


def encode_string(value: str, style: str | None) -> str:
    """Keep the value's original quoting where that is still safe: single
    quotes stay single, double stay double, bare stays bare when it can."""
    if style == "'" and not any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        return "'" + value.replace("'", "''") + "'"
    if style != '"' and plain_safe(value):
        return value
    # JSON's escapes are all valid YAML double-quoted escapes.
    return json.dumps(value, ensure_ascii=False)


def encode_scalar(value: Any, style: str | None) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return encode_string(value, style)
    raise ConfigError(f"cannot write a {type(value).__name__}")


def encode_flow_list(items: list[str]) -> str:
    return "[" + ", ".join(encode_string(item, None) for item in items) + "]"
