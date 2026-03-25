"""
doc_helpers.py
Shared colours, severity maps, and Word-document utility functions used by
both Framework A and Framework B builders.

Dependencies:
    pip install python-docx
"""

from __future__ import annotations

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from datetime import datetime


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
NAVY       = RGBColor(0x1F, 0x39, 0x64)   # headings
STEEL      = RGBColor(0x2E, 0x75, 0xB6)   # sub-headings / accents
DARK_GREY  = RGBColor(0x40, 0x40, 0x40)   # body text
RED        = RGBColor(0xC0, 0x00, 0x00)   # HIGH severity
AMBER      = RGBColor(0xED, 0x7D, 0x31)   # MEDIUM severity
GREEN      = RGBColor(0x70, 0xAD, 0x47)   # LOW / pass

LIGHT_BLUE_FILL = "D5E3F0"   # table header fill (hex, no #)
ALT_ROW_FILL    = "EBF3FB"   # alternating table row fill


# ---------------------------------------------------------------------------
# Severity helpers
# ---------------------------------------------------------------------------
SEVERITY_COLOUR = {
    "HIGH":   RED,
    "MEDIUM": AMBER,
    "LOW":    GREEN,
    "PASS":   GREEN,
}

SEVERITY_LABEL = {
    "HIGH":   "⚠ HIGH",
    "MEDIUM": "△ MEDIUM",
    "LOW":    "○ LOW",
    "PASS":   "✓ PASS",
}


# ---------------------------------------------------------------------------
# Style configuration
# ---------------------------------------------------------------------------

def configure_styles(doc: Document) -> None:
    """Apply consistent font and colour defaults to built-in Word styles."""
    styles = doc.styles

    normal = styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.font.color.rgb = DARK_GREY

    h1 = styles["Heading 1"]
    h1.font.name = "Arial"
    h1.font.size = Pt(16)
    h1.font.bold = True
    h1.font.color.rgb = NAVY
    h1.paragraph_format.space_before = Pt(18)
    h1.paragraph_format.space_after  = Pt(6)

    h2 = styles["Heading 2"]
    h2.font.name = "Arial"
    h2.font.size = Pt(13)
    h2.font.bold = True
    h2.font.color.rgb = STEEL
    h2.paragraph_format.space_before = Pt(12)
    h2.paragraph_format.space_after  = Pt(4)

    h3 = styles["Heading 3"]
    h3.font.name = "Arial"
    h3.font.size = Pt(11)
    h3.font.bold = True
    h3.font.color.rgb = DARK_GREY
    h3.paragraph_format.space_before = Pt(8)
    h3.paragraph_format.space_after  = Pt(2)


# ---------------------------------------------------------------------------
# Low-level paragraph / run helpers
# ---------------------------------------------------------------------------

def add_page_break(doc: Document) -> None:
    p   = doc.add_paragraph()
    run = p.add_run()
    br  = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    doc.add_heading(text, level=level)


def add_body(doc: Document, text: str, italic: bool = False,
             bold: bool = False, colour: RGBColor = None) -> None:
    p   = doc.add_paragraph(style="Normal")
    run = p.add_run(text)
    run.italic = italic
    run.bold   = bold
    if colour:
        run.font.color.rgb = colour
    p.paragraph_format.space_after = Pt(4)


def add_bullet(doc: Document, text: str, level: int = 0,
               colour: RGBColor = None, bold_prefix: str = None) -> None:
    style = "List Bullet" if level == 0 else "List Bullet 2"
    p = doc.add_paragraph(style=style)
    if bold_prefix:
        r = p.add_run(bold_prefix)
        r.bold = True
        if colour:
            r.font.color.rgb = colour
    r2 = p.add_run(text)
    if colour:
        r2.font.color.rgb = colour


def add_labelled_bullet(doc: Document, label: str, value: str,
                        colour: RGBColor = None) -> None:
    p  = doc.add_paragraph(style="List Bullet")
    r1 = p.add_run(f"{label}: ")
    r1.bold = True
    if colour:
        r1.font.color.rgb = colour
    p.add_run(value)


def add_placeholder(doc: Document, section_hint: str) -> None:
    """Insert a greyed italic placeholder when no slide content is available."""
    p   = doc.add_paragraph(style="Normal")
    run = p.add_run(
        f"[{section_hint} — content extracted from pitch deck. "
        "Review and edit as required.]"
    )
    run.italic = True
    run.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    p.paragraph_format.space_after = Pt(6)


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

def _set_cell_bg(cell, hex_colour: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd   = OxmlElement("w:shd")
    shd.set(qn("w:val"),   "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"),  hex_colour)
    tc_pr.append(shd)


def _set_col_width(cell, width_inches: float) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w  = OxmlElement("w:tcW")
    tc_w.set(qn("w:w"),    str(int(width_inches * 1440)))
    tc_w.set(qn("w:type"), "dxa")
    tc_pr.append(tc_w)


def add_findings_table(doc: Document, findings: list, max_rows: int = 50) -> None:
    """Render a colour-coded anomaly findings table."""
    if not findings:
        add_body(doc, "No findings in this category.", italic=True)
        return

    headers    = ["ID", "Category", "Severity", "Label", "Evidence", "Slide"]
    col_widths = [0.7,   1.1,        0.85,       1.6,     4.0,        0.6]

    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"

    # Header row
    for i, (h, w) in enumerate(zip(headers, col_widths)):
        cell = table.rows[0].cells[i]
        _set_cell_bg(cell, LIGHT_BLUE_FILL)
        _set_col_width(cell, w)
        run = cell.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = NAVY

    for idx, f in enumerate(findings[:max_rows]):
        row = table.add_row()
        sev = getattr(f, "severity", "")
        row_fill = {"HIGH": "FFE0E0", "MEDIUM": "FFF3CD", "LOW": "E8F5E9"}.get(sev, "FFFFFF")

        vals = [
            getattr(f, "anomaly_id",      ""),
            getattr(f, "category",        ""),
            SEVERITY_LABEL.get(sev, sev),
            getattr(f, "label",           ""),
            (getattr(f, "evidence", "") or "")[:200],
            str(getattr(f, "slide_reference", "") or ""),
        ]

        for i, (v, w) in enumerate(zip(vals, col_widths)):
            cell = row.cells[i]
            fill = ALT_ROW_FILL if (idx % 2 == 1 and sev == "") else row_fill
            _set_cell_bg(cell, fill)
            _set_col_width(cell, w)
            run = cell.paragraphs[0].add_run(str(v))
            run.font.size = Pt(8.5)
            if i == 2:  # severity column — coloured text
                run.font.color.rgb = SEVERITY_COLOUR.get(sev, DARK_GREY)
                run.bold = True

    doc.add_paragraph()


def add_questions_table(doc: Document, questions_by_cat: dict) -> None:
    """Render investor questions grouped by category."""
    if not questions_by_cat:
        add_body(doc, "No questions generated.", italic=True)
        return
    for cat, qs in questions_by_cat.items():
        add_heading(doc, cat, level=3)
        for q in qs:
            add_bullet(doc, str(q))


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

def cover_page(doc: Document, title: str, subtitle: str,
               source_filename: str) -> None:
    doc.add_paragraph()
    doc.add_paragraph()

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run(title)
    run.font.name  = "Arial"
    run.font.size  = Pt(28)
    run.bold       = True
    run.font.color.rgb = NAVY

    p2  = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run2 = p2.add_run(subtitle)
    run2.font.name = "Arial"
    run2.font.size = Pt(14)
    run2.font.color.rgb = STEEL

    doc.add_paragraph()

    for line in (f"Source: {source_filename}",
                 f"Generated: {datetime.now().strftime('%d %B %Y  %H:%M')}"):
        p3 = doc.add_paragraph()
        p3.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p3.add_run(line)
        r.font.size = Pt(10)
        r.font.color.rgb = RGBColor(0x70, 0x70, 0x70)

    add_page_break(doc)


# ---------------------------------------------------------------------------
# Slide content extraction
# ---------------------------------------------------------------------------

def _normalise(s: str) -> str:
    """Lowercase and replace underscores with spaces for fuzzy section matching."""
    return (s or "").lower().replace("_", " ")


def slides_for_section(result, section_name: str) -> list:
    """
    Return slides whose detected_section matches section_name.

    Normalises both sides to lowercase-with-spaces before comparing, so
    pipeline labels like 'CAP_TABLE' match search terms like 'cap table',
    and 'SOLUTION' matches 'solution'. Slides classified as UNKNOWN are
    always excluded.
    """
    try:
        slides = result.deck.slides
    except AttributeError:
        return []

    needle = _normalise(section_name)
    matched = []
    for s in slides:
        raw  = getattr(s, "detected_section", "") or ""
        norm = _normalise(raw)
        if norm == "unknown":
            continue
        if needle in norm or norm in needle:
            matched.append(s)
    return matched


def emit_slide_content(doc: Document, result, section_name: str,
                       placeholder_hint: str) -> None:
    """Write slide text as body paragraphs, or a placeholder if nothing found."""
    slides = slides_for_section(result, section_name)
    parts  = []
    for s in slides:
        txt = getattr(s, "cleaned_text", "") or getattr(s, "raw_text", "") or ""
        if txt.strip():
            parts.append(txt.strip())

    if parts:
        for para in "\n\n".join(parts).split("\n"):
            if para.strip():
                add_body(doc, para.strip())
    else:
        add_placeholder(doc, placeholder_hint)


def safe_call(result, method: str, *args, default=None):
    """Call result.method(*args) safely, returning default on any error."""
    try:
        fn = getattr(result, method)
        return fn(*args) if args else fn()
    except Exception:
        return default if default is not None else []