"""Getting lists in and out.

In: a Markdown or Google Docs outline (headings become tags, and "Watched" or
"TV shows" headings set the status and type of what is under them -- see
outline.py), a CSV with a header row, or JSON (this app's export, or the old
app's). Each becomes rows of {title, year, type, status, rating, heart, tags,
notes, links}; the import route turns rows into titles.

Out: JSON (titles plus one person's state, re-importable), CSV, or a Markdown
outline grouped by type and status.

Pure: text in, rows out; titles in, text out.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.media import normalize
from app.media.outline import parse_outline

FORMATS = ("auto", "outline", "csv", "json")
CSV_FIELDS = ("title", "year", "type", "status", "rating", "heart", "tags", "genres", "runtime", "certification", "creator", "imdb_id", "wiki_url", "notes", "note", "added_at", "watched_at")


def detect(text: str) -> str:
    head = text.lstrip()[:1]
    if head in ("{", "["):
        return "json"
    first = text.strip().splitlines()[0] if text.strip() else ""
    if "," in first and "title" in first.lower().split(",")[0:3] or first.lower().startswith("title,"):
        return "csv"
    return "outline"


def row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """One import row, cleaned: title fields plus the importer's own state."""
    fields = normalize.clean_title_fields(
        {
            **raw,
            # Old-app and export spellings.
            "imdb_id": raw.get("imdb_id") or raw.get("imdbId"),
            "wiki_url": raw.get("wiki_url") or raw.get("wikiUrl"),
            "poster_url": raw.get("poster_url") or "",
            "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else [tag for tag in str(raw.get("tags") or "").replace(";", ",").split(",")],
            "genres": raw.get("genres") if isinstance(raw.get("genres"), list) else [genre for genre in str(raw.get("genres") or "").replace(";", ",").split(",")],
        }
    )
    if not fields.get("title"):
        return None
    status = raw.get("status") if raw.get("status") in normalize.STATUSES else None
    heart = raw.get("heart")
    return {
        "fields": fields,
        "state": {
            "status": status,
            "rating": normalize.bounded_int(raw.get("rating"), 1, 10),
            "heart": heart is True or str(heart).lower() in ("1", "true", "yes", "♥"),
            "note": normalize.text(raw.get("note"), 4000),
            "watched_at": normalize.iso(raw.get("watched_at") or raw.get("watchedAt")),
        },
    }


def parse(text: str, fmt: str = "auto", default_type: str = "movie", default_status: str = "queue") -> dict[str, Any]:
    fmt = detect(text) if fmt == "auto" else fmt
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    if fmt == "json":
        try:
            data = json.loads(text)
        except ValueError as error:
            raise ValueError(f"that is not valid JSON: {error}") from None
        items = data if isinstance(data, list) else (data.get("items") or data.get("titles") or [])
        states = data.get("states") or {} if isinstance(data, dict) else {}
        for item in items:
            if not isinstance(item, dict):
                continue
            merged = {**item, **(states.get(item.get("id")) or {})}
            if "poster" in merged and str(merged["poster"]).startswith("http"):
                merged["poster_url"] = merged["poster"]
            parsed = row(merged)
            if parsed:
                rows.append(parsed)
        sources = (data.get("sources") or []) if isinstance(data, dict) else []
    elif fmt == "csv":
        reader = csv.DictReader(io.StringIO(text))
        for raw in reader:
            parsed = row({(key or "").strip().lower(): value for key, value in raw.items()})
            if parsed:
                rows.append(parsed)
    else:
        outline = parse_outline(text, type=default_type, status=default_status)
        rows = [parsed for parsed in (row(item) for item in outline["items"]) if parsed]
        sources = outline.get("sources") or []
    return {"format": fmt, "rows": rows, "sources": sources}


def export(titles: list[dict[str, Any]], states: dict[str, dict[str, Any]], types: list[dict[str, Any]], fmt: str, who: str) -> tuple[bytes, str, str]:
    """(body, media type, file extension)."""
    live = sorted((t for t in titles if not t.get("deleted_at")), key=lambda t: ((t.get("type") or ""), (t.get("title") or "").lower()))
    if fmt == "json":
        payload = {
            "app": "media-tracker",
            "schema": 2,
            "person": who,
            "count": len(live),
            "types": types,
            "titles": live,
            "states": {t["id"]: states[t["id"]] for t in live if t["id"] in states},
        }
        return json.dumps(payload, indent=1, ensure_ascii=False).encode("utf-8"), "application/json", "json"
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(CSV_FIELDS)
        for t in live:
            s = states.get(t["id"]) or {}
            writer.writerow(
                [
                    t.get("title"), t.get("year") or "", t.get("type"), s.get("status") or "", s.get("rating") or "",
                    "yes" if s.get("heart") else "", ", ".join(t.get("tags") or []), ", ".join(t.get("genres") or []),
                    t.get("runtime") or "", t.get("certification") or "", t.get("creator") or "", t.get("imdb_id") or "",
                    t.get("wiki_url") or "", t.get("notes") or "", s.get("note") or "", t.get("added_at") or "", s.get("watched_at") or "",
                ]
            )
        return out.getvalue().encode("utf-8"), "text/csv", "csv"
    labels = {entry["id"]: entry["label"] for entry in types}
    sections = (("watching", "Watching"), ("queue", "Up next"), ("watched", "Watched"), ("dropped", "Not for me"), (None, "In the library"))
    lines = [f"# Media Tracker — {who}", ""]
    for type_id in dict.fromkeys(t.get("type") for t in live):
        lines.append(f"## {labels.get(type_id, type_id)}")
        for status, heading in sections:
            chosen = [t for t in live if t.get("type") == type_id and ((states.get(t["id"]) or {}).get("status") or None) == status]
            if not chosen:
                continue
            lines.append(f"### {heading}")
            for t in chosen:
                s = states.get(t["id"]) or {}
                extra = " ♥" if s.get("heart") else ""
                extra += f" ★{s['rating']}" if s.get("rating") else ""
                link = t.get("wiki_url") or (f"https://www.imdb.com/title/{t['imdb_id']}/" if t.get("imdb_id") else "")
                name = f"[{t['title']}]({link})" if link else t["title"]
                lines.append(f"- {name}" + (f" ({t['year']})" if t.get("year") else "") + extra)
            lines.append("")
    return "\n".join(lines).encode("utf-8"), "text/markdown", "md"
