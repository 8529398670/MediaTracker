"""A small .xlsx writer: one sheet per (name, header, rows), nothing else.

Hand-written SpreadsheetML so the app needs no spreadsheet package. Each sheet
has a bold, frozen header row, an autofilter and set column widths. Strings are
inline; numbers stay numbers; a cell given as ("link", url, text) becomes a
hyperlink. Pure: data in, bytes out.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Any
from xml.sax.saxutils import escape, quoteattr

Cell = Any  # str | int | float | None | ("link", url, text)

_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")


def _text(value: Any) -> str:
    return escape(_BAD_XML.sub("", str(value)))


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _quoted(name: str) -> str:
    """A sheet name as a formula reference: 'Watched – TV'."""
    return "'" + name.replace("'", "''") + "'"


def sheet_name(name: str, taken: set[str]) -> str:
    base = _BAD_SHEET.sub(" ", name).strip()[:31] or "Sheet"
    out, n = base, 2
    while out.lower() in taken:
        suffix = f" ({n})"
        out, n = base[: 31 - len(suffix)] + suffix, n + 1
    taken.add(out.lower())
    return out


def _sheet(header: list[str], rows: list[list[Cell]], widths: list[int]) -> tuple[str, str]:
    """(sheet XML, its relationships XML)."""
    links: list[tuple[str, str]] = []
    out = []
    for r, values in enumerate([header, *rows], start=1):
        cells = []
        for c, value in enumerate(values):
            ref = f"{_col(c)}{r}"
            style = ' s="1"' if r == 1 else ""
            if isinstance(value, tuple) and value and value[0] == "link":
                _, url, label = value
                if url:
                    links.append((ref, url))
                    style = ' s="2"'
                value = label
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                value = "yes" if value else ""
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"{style}><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}"{style} t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>')
        out.append(f'<row r="{r}">{"".join(cells)}</row>')
    last = f"{_col(len(header) - 1)}{len(rows) + 1}"
    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths))
    hyperlinks = ""
    rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    if links:
        items = []
        for i, (ref, url) in enumerate(links, start=1):
            items.append(f'<hyperlink ref="{ref}" r:id="rId{i}"/>')
            rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target={quoteattr(_BAD_XML.sub("", url))} TargetMode="External"/>')
        hyperlinks = f"<hyperlinks>{''.join(items)}</hyperlinks>"
    rels.append("</Relationships>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(out)}</sheetData>"
        f'<autoFilter ref="A1:{last}"/>{hyperlinks}</worksheet>'
    )
    return xml, "".join(rels)


_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def workbook(sheets: list[tuple[str, list[str], list[list[Cell]]]], widths: list[int]) -> bytes:
    """sheets: (name, header, rows). An empty list still makes one empty sheet."""
    if not sheets:
        sheets = [("Empty", [], [])]
    taken: set[str] = set()
    names = [sheet_name(name, taken) for name, _h, _r in sheets]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        z.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            f"{overrides}</Types>"
        ))
        z.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ))
        entries = "".join(f'<sheet name={quoteattr(name)} sheetId="{i}" r:id="rId{i}"/>' for i, name in enumerate(names, start=1))
        defined = "".join(
            f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">{escape(_quoted(name))}!$A$1:${_col(max(len(h), 1) - 1)}${len(r) + 1}</definedName>'
            for i, (name, (_n, h, r)) in enumerate(zip(names, sheets))
        )
        z.writestr("xl/workbook.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<sheets>{entries}</sheets><definedNames>{defined}</definedNames></workbook>"
        ))
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        n = len(sheets) + 1
        z.writestr("xl/_rels/workbook.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{rels}<Relationship Id="rId{n}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ))
        z.writestr("xl/styles.xml", _STYLES)
        for i, (_name, header, rows) in enumerate(sheets, start=1):
            xml, sheet_rels = _sheet(header or [""], rows, widths)
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
            z.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels", sheet_rels)
    return buffer.getvalue()
