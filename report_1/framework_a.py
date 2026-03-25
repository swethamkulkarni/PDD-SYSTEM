"""
framework_a.py
Framework A — 11-section Due Diligence Report builder.

Each narrative section is written by the LLM (via SectionWriter).
Structured data (findings tables, questions, risk lists) remains rule-based.

Usage:
    from framework_a import build_framework_a
    doc = build_framework_a(result)
    doc.save("dd_report.docx")

    # Explicit LLM provider:
    doc = build_framework_a(result, provider="groq")

Dependencies:
    pip install python-docx
"""

from __future__ import annotations

from docx import Document

from report_1.doc_helpers import (
    configure_styles, cover_page,
    add_heading, add_body, add_bullet, add_labelled_bullet, add_placeholder,
    add_findings_table, add_questions_table,
    safe_call,
    SEVERITY_COLOUR, SEVERITY_LABEL, RED, GREEN, DARK_GREY,
)
from report_1.section_writer import (
    SectionWriter,
    collect_slide_texts,
    collect_unknown_texts,
    collect_slide_tables,
    findings_summary_for,
    all_findings_summary,
)


def _write(writer: SectionWriter, doc: Document, section_key: str,
           slide_texts: list, unknown_texts: list,
           findings_summary: str = "", framework: str = "A",
           max_tokens: int = 600, slide_tables: list = None) -> None:
    """Generate LLM prose and write it to the document as body paragraphs."""
    text = writer.write_section(
        section_key, slide_texts, unknown_texts,
        findings_summary, framework, max_tokens,
        slide_tables=slide_tables,
    )
    for para in text.split("\n"):
        para = para.strip()
        if para:
            add_body(doc, para)


def build_framework_a(result, provider: str = None) -> Document:
    """
    Build the 11-section Due Diligence Report and return a python-docx Document.

    Sections
    --------
    1.  Product Description
    2.  Technology Solution
    3.  Business Model
    4.  Technology Overview
    5.  Team
    6.  Cap Table
    7.  Traction
    8.  Investment Rationale
    9.  Areas to Watch          (LLM narrative + rule-based findings table)
    10. Comments & Observations (LLM per sub-section)
    11. Final Call              (LLM recommendation)
    """
    doc = Document()
    configure_styles(doc)

    source = getattr(getattr(result, "deck", object()), "source_filename", "Unknown")
    cover_page(doc, "Due Diligence Report", "Venture Capital Analysis", source)

    writer   = SectionWriter(provider=provider)
    unknowns = collect_unknown_texts(result)

    all_findings = getattr(result, "all_findings", []) or []
    flagged      = safe_call(result, "flagged")        or []
    unclear      = safe_call(result, "unclear")        or []
    ic_risks     = safe_call(result, "ic_memo_risks")  or []
    questions    = safe_call(result, "questions_by_category") or {}
    total_high   = len([f for f in all_findings if getattr(f, "severity", "") == "HIGH"])
    total_med    = len([f for f in all_findings if getattr(f, "severity", "") == "MEDIUM"])

    # ── 1. Product Description ──────────────────────────────────────────────
    add_heading(doc, "1. Product Description", level=1)
    _write(writer, doc, "product_description",
           slide_texts=collect_slide_texts(result, "cover")
                       + collect_slide_texts(result, "market"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "ms", "product"),
           max_tokens=500)

    # ── 2. Technology Solution ──────────────────────────────────────────────
    add_heading(doc, "2. Technology Solution", level=1)
    _write(writer, doc, "technology_solution",
           slide_texts=collect_slide_texts(result, "solution")
                       + collect_slide_texts(result, "technology"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "tech", "ip"),
           max_tokens=600)

    # ── 3. Business Model ───────────────────────────────────────────────────
    add_heading(doc, "3. Business Model", level=1)
    _write(writer, doc, "business_model",
           slide_texts=collect_slide_texts(result, "financials")
                       + collect_slide_texts(result, "traction"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "financ", "revenue", "business"),
           max_tokens=500)

    # ── 4. Technology Overview ──────────────────────────────────────────────
    add_heading(doc, "4. Technology Overview", level=1)
    add_heading(doc, "4.1 Technical Architecture", level=2)
    _write(writer, doc, "technology_overview",
           slide_texts=collect_slide_texts(result, "technology")
                       + collect_slide_texts(result, "solution"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "tech", "ip"),
           max_tokens=600)

    add_heading(doc, "4.2 IP & Defensibility", level=2)
    _write(writer, doc, "comments_technology",
           slide_texts=collect_slide_texts(result, "technology"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "ip", "competi"),
           max_tokens=400)

    # ── 5. Team ─────────────────────────────────────────────────────────────
    add_heading(doc, "5. Team", level=1)
    _write(writer, doc, "team",
           slide_texts=collect_slide_texts(result, "cover"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "team", "ms"),
           max_tokens=500)

    # ── 6. Cap Table ────────────────────────────────────────────────────────
    add_heading(doc, "6. Cap Table", level=1)
    _write(writer, doc, "cap_table",
           slide_texts=collect_slide_texts(result, "cap_table")
                       + collect_slide_texts(result, "traction"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "cap", "fund", "financ"),
           slide_tables=collect_slide_tables(result, "cap_table")
                        + collect_slide_tables(result, "traction"),
           max_tokens=500)

    # ── 7. Traction ─────────────────────────────────────────────────────────
    add_heading(doc, "7. Traction", level=1)
    add_heading(doc, "7.1 Key Metrics", level=2)
    _write(writer, doc, "traction",
           slide_texts=collect_slide_texts(result, "traction")
                       + collect_slide_texts(result, "financials"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "traction", "metric", "revenue"),
           max_tokens=500)

    add_heading(doc, "7.2 Customer & Revenue Growth", level=2)
    _write(writer, doc, "business_model",
           slide_texts=collect_slide_texts(result, "financials")
                       + collect_slide_texts(result, "traction"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "revenue", "customer", "growth"),
           max_tokens=400)

    # ── 8. Investment Rationale ──────────────────────────────────────────────
    add_heading(doc, "8. Investment Rationale", level=1)
    add_heading(doc, "8.1 Market Opportunity", level=2)
    _write(writer, doc, "market_opportunity",
           slide_texts=collect_slide_texts(result, "market"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "market"),
           max_tokens=500)

    add_heading(doc, "8.2 Competitive Landscape", level=2)
    _write(writer, doc, "competitive_landscape",
           slide_texts=collect_slide_texts(result, "market")
                       + collect_slide_texts(result, "technology"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "competi", "ms"),
           max_tokens=400)

    add_heading(doc, "8.3 Investment Rationale", level=2)
    _write(writer, doc, "investment_rationale",
           slide_texts=(collect_slide_texts(result, "cover")
                        + collect_slide_texts(result, "market")
                        + collect_slide_texts(result, "solution")),
           unknown_texts=unknowns,
           findings_summary=all_findings_summary(result),
           max_tokens=500)

    # ── 9. Areas to Watch ───────────────────────────────────────────────────
    add_heading(doc, "9. Areas to Watch", level=1)
    _write(writer, doc, "areas_to_watch",
           slide_texts=(collect_slide_texts(result, "cover")
                        + collect_slide_texts(result, "market")
                        + collect_slide_texts(result, "financials")),
           unknown_texts=unknowns,
           findings_summary=all_findings_summary(result),
           max_tokens=500)

    if flagged or unclear:
        add_body(doc,
                 f"Pipeline summary: {len(flagged)} flagged, "
                 f"{len(unclear)} unclear, {total_high} HIGH severity, "
                 f"{total_med} MEDIUM severity.",
                 bold=True)
        for f in (flagged + unclear)[:20]:
            sev = getattr(f, "severity", "")
            add_labelled_bullet(
                doc,
                f"{SEVERITY_LABEL.get(sev, sev)} — {getattr(f, 'category', '')}",
                f"  {getattr(f, 'label', '')}",
                colour=SEVERITY_COLOUR.get(sev, DARK_GREY),
            )

    add_heading(doc, "9.1 Full Anomaly Findings", level=2)
    add_findings_table(doc, all_findings)

    add_heading(doc, "9.2 Investor Questions", level=2)
    add_questions_table(doc, questions)

    # ── 10. Comments & Observations ─────────────────────────────────────────
    add_heading(doc, "10. Comments & Observations", level=1)

    obs_map = [
        ("10.1 Technology",  "comments_technology",
         ["technology", "solution"],      ["tech", "ip"]),
        ("10.2 Financials",  "comments_financials",
         ["financials", "cap_table"],     ["financ", "revenue", "valuat"]),
        ("10.3 Regulations", "comments_regulations",
         ["market"],                      ["regulat", "legal", "compliance"]),
        ("10.4 GTM",         "comments_gtm",
         ["traction", "market"],          ["traction", "gtm", "customer"]),
        ("10.5 Competition", "comments_competition",
         ["market", "technology"],        ["competi", "ms"]),
    ]

    for heading_text, key, slide_keys, finding_keys in obs_map:
        add_heading(doc, heading_text, level=2)
        slides = []
        for sk in slide_keys:
            slides += collect_slide_texts(result, sk)
        _write(writer, doc, key,
               slide_texts=slides,
               unknown_texts=unknowns,
               findings_summary=findings_summary_for(result, *finding_keys),
               max_tokens=400)

    add_heading(doc, "10.6 Other", level=2)
    _write(writer, doc, "areas_to_watch",
           slide_texts=collect_slide_texts(result, "cover"),
           unknown_texts=unknowns,
           findings_summary=all_findings_summary(result),
           max_tokens=350)

    # ── 11. Final Call ───────────────────────────────────────────────────────
    add_heading(doc, "11. Final Call", level=1)
    add_body(doc,
             f"Pipeline summary: {len(all_findings)} checks — "
             f"{len(flagged)} flagged, {len(unclear)} unclear, "
             f"{total_high} HIGH severity, {total_med} MEDIUM severity.",
             bold=True)

    if ic_risks:
        add_heading(doc, "IC Memo Risk Flags", level=2)
        for f in ic_risks:
            add_bullet(
                doc,
                f"{getattr(f, 'label', '')} — {(getattr(f, 'evidence', '') or '')[:150]}",
                colour=RED,
            )

    add_heading(doc, "Recommendation", level=2)
    _write(writer, doc, "final_call_a",
           slide_texts=(collect_slide_texts(result, "cover")
                        + collect_slide_texts(result, "market")
                        + collect_slide_texts(result, "financials")
                        + collect_slide_texts(result, "traction")),
           unknown_texts=unknowns,
           findings_summary=all_findings_summary(result),
           max_tokens=600)

    return doc