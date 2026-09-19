"""Export a run to a file people can send on.

The marketing-plan skill's own /exportreport step points at a bundled docx
skill path that does not exist on a server, so export is implemented here
instead, to the same spec: cover page, table of contents, numbered sections,
real tables, page footer.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

import markdown as md_lib
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ACCENT = RGBColor(0x1F, 0x3A, 0x5F)
ARABIC = re.compile(r"[\u0600-\u06FF]")

_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_SECTION_MARKER = re.compile(r"<!--section:[^>]*-->")


def _is_rtl(text: str) -> bool:
    return bool(ARABIC.search(text))


def _set_rtl(paragraph) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    pPr.append(bidi)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _write_runs(paragraph, text: str) -> None:
    """Render inline **bold**; everything else goes in as plain text."""
    for index, part in enumerate(_BOLD.split(text)):
        if not part:
            continue
        run = paragraph.add_run(part)
        run.bold = index % 2 == 1


def _add_paragraph(doc: Document, text: str, style: str | None = None):
    paragraph = doc.add_paragraph(style=style)
    _write_runs(paragraph, text)
    if _is_rtl(text):
        _set_rtl(paragraph)
    return paragraph


def _add_footer(doc: Document, label: str) -> None:
    footer = doc.sections[0].footer.paragraphs[0]
    footer.text = label
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run("    ")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    run._r.addnext(fld)


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_to_docx(content: str, title: str, brand: str, subtitle: str = "") -> bytes:
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    # Arabic glyphs need the complex-script font set explicitly.
    normal.element.rPr.rFonts.set(qn("w:cs"), "Arial")

    # --- Cover ---
    for _ in range(5):
        doc.add_paragraph()
    cover = doc.add_paragraph()
    cover.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = cover.add_run(brand)
    run.bold, run.font.size, run.font.color.rgb = True, Pt(30), ACCENT

    heading = doc.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    heading.add_run(title).font.size = Pt(18)

    if subtitle:
        sub = doc.add_paragraph()
        sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        sub.add_run(subtitle).font.size = Pt(12)

    stamp = doc.add_paragraph()
    stamp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    stamp.add_run(f"{date.today():%d %B %Y}  ·  Confidential").font.size = Pt(10)

    doc.add_section(WD_SECTION.NEW_PAGE)
    _add_footer(doc, f"{brand} — {title}")

    # --- Body ---
    lines = _SECTION_MARKER.sub("", content).split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):  # skip fenced blocks (the JSON scorecard)
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                index += 1
            index += 1
            continue

        if match := _HEADING.match(stripped):
            level = min(len(match.group(1)), 4)
            paragraph = doc.add_heading(level=level)
            _write_runs(paragraph, match.group(2))
            if _is_rtl(match.group(2)):
                _set_rtl(paragraph)
            index += 1
            continue

        if _TABLE_ROW.match(line) and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1]):
            header = _split_row(line)
            index += 2
            rows = []
            while index < len(lines) and _TABLE_ROW.match(lines[index]):
                rows.append(_split_row(lines[index]))
                index += 1

            table = doc.add_table(rows=1, cols=len(header))
            table.style = "Light Grid Accent 1"
            table.autofit = True
            for cell, text in zip(table.rows[0].cells, header):
                cell.text = ""
                paragraph = cell.paragraphs[0]
                run = paragraph.add_run(text)
                run.bold = True
                if _is_rtl(text):
                    _set_rtl(paragraph)
            for row in rows:
                cells = table.add_row().cells
                for cell, text in zip(cells, row[: len(header)]):
                    cell.text = ""
                    paragraph = cell.paragraphs[0]
                    _write_runs(paragraph, text)
                    if _is_rtl(text):
                        _set_rtl(paragraph)
            doc.add_paragraph()
            continue

        if match := _BULLET.match(line):
            _add_paragraph(doc, match.group(1), style="List Bullet")
            index += 1
            continue

        if match := _NUMBERED.match(line):
            _add_paragraph(doc, match.group(1), style="List Number")
            index += 1
            continue

        if stripped.startswith(">"):
            paragraph = _add_paragraph(doc, stripped.lstrip("> ").strip(), style="Intense Quote")
            index += 1
            continue

        if set(stripped) <= set("-–—_*") and len(stripped) >= 3:
            index += 1
            continue

        _add_paragraph(doc, stripped)
        index += 1

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


PDF_CSS = """
@page { size: A4; margin: 20mm 16mm; @bottom-center {
  content: counter(page); font-size: 9pt; color: #888; } }
body { font-family: "Noto Naskh Arabic", "Amiri", "DejaVu Sans", sans-serif;
  font-size: 11pt; line-height: 1.85; color: #1a1a1a; direction: rtl; text-align: right; }
h1 { font-size: 20pt; color: #1f3a5f; border-bottom: 2px solid #1f3a5f;
  padding-bottom: 6px; margin-top: 22px; }
h2 { font-size: 15pt; color: #1f3a5f; margin-top: 18px; }
h3 { font-size: 12.5pt; color: #33507a; margin-top: 14px; }
table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 9.5pt;
  page-break-inside: avoid; }
th { background: #1f3a5f; color: #fff; padding: 7px; text-align: right; }
td { border: 1px solid #d6dde6; padding: 7px; vertical-align: top; }
tr:nth-child(even) td { background: #f6f8fa; }
blockquote { border-right: 4px solid #1f3a5f; background: #f6f8fa;
  margin: 12px 0; padding: 9px 14px; }
code, pre { font-family: "DejaVu Sans Mono", monospace; font-size: 9pt;
  background: #f2f4f7; direction: ltr; text-align: left; }
pre { padding: 10px; border-radius: 5px; white-space: pre-wrap; }
.cover { text-align: center; padding-top: 220px; page-break-after: always; direction: rtl; }
.cover .brand { font-size: 32pt; font-weight: 700; color: #1f3a5f; }
.cover .title { font-size: 18pt; margin-top: 14px; }
.cover .meta { font-size: 10pt; color: #666; margin-top: 26px; }
"""


def markdown_to_pdf(content: str, title: str, brand: str, subtitle: str = "") -> bytes:
    from weasyprint import CSS, HTML

    body = md_lib.markdown(
        _SECTION_MARKER.sub("", content),
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
    )
    html = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>{title}</title></head><body>
<div class="cover">
  <div class="brand">{brand}</div>
  <div class="title">{title}</div>
  {f'<div class="title" style="font-size:12pt">{subtitle}</div>' if subtitle else ''}
  <div class="meta">{date.today():%d %B %Y} · Confidential</div>
</div>
{body}
</body></html>"""

    return HTML(string=html).write_pdf(stylesheets=[CSS(string=PDF_CSS)])
