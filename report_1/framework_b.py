"""
framework_b.py
Framework B — 8-section VC IC Memo builder (skeptical senior partner tone).

Each narrative section is written by the LLM in the voice of a skeptical
senior VC partner. Structured pipeline data (findings tables, risk snapshots)
remains rule-based.

Usage:
    from framework_b import build_framework_b
    doc = build_framework_b(result)
    doc.save("ic_memo.docx")

    # Explicit LLM provider:
    doc = build_framework_b(result, provider="groq")

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
           findings_summary: str = "", framework: str = "B",
           max_tokens: int = 500, slide_tables: list = None) -> None:
    """Generate LLM prose (IC memo tone) and write as body paragraphs."""
    text = writer.write_section(
        section_key, slide_texts, unknown_texts,
        findings_summary, framework, max_tokens,
        slide_tables=slide_tables,
    )
    for para in text.split("\n"):
        para = para.strip()
        if para:
            add_body(doc, para)


def build_framework_b(result, provider: str = None) -> Document:
    """
    Build the 8-section IC Memo and return a python-docx Document.

    Written in the tone of a skeptical senior VC partner.

    Sections
    --------
    1. Executive Summary
    2. Market & Problem
    3. Technology & Product
    4. Financials
    5. GTM & Traction
    6. Competitive Landscape
    7. Comments & Observations
    8. IC Memo Summary  (positive signals / key risks / recommendation)
    """
    doc = Document()
    configure_styles(doc)

    source       = getattr(getattr(result, "deck", object()), "source_filename", "Unknown")
    all_findings = getattr(result, "all_findings", []) or []
    flagged      = safe_call(result, "flagged")            or []
    unclear      = safe_call(result, "unclear")            or []
    ic_risks     = safe_call(result, "ic_memo_risks")      or []
    questions    = safe_call(result, "questions_by_category") or {}
    high_findings = [f for f in all_findings if getattr(f, "severity", "") == "HIGH"]
    med_findings  = [f for f in all_findings if getattr(f, "severity", "") == "MEDIUM"]

    cover_page(doc, "Investment Committee Memo", "Confidential — Internal Use Only", source)

    writer   = SectionWriter(provider=provider)
    unknowns = collect_unknown_texts(result)

    # ── 1. Executive Summary ────────────────────────────────────────────────
    add_heading(doc, "1. Executive Summary", level=1)
    _write(writer, doc, "executive_summary_b",
           slide_texts=(collect_slide_texts(result, "cover")
                        + collect_slide_texts(result, "market")
                        + collect_slide_texts(result, "solution")),
           unknown_texts=unknowns,
           findings_summary=all_findings_summary(result),
           max_tokens=500)

    add_heading(doc, "Headline Risk Snapshot", level=2)
    add_body(doc,
             f"Total checks: 44   |   Flagged: {len(flagged)}   |   "
             f"Unclear: {len(unclear)}   |   HIGH: {len(high_findings)}   |   "
             f"MEDIUM: {len(med_findings)}")
    if high_findings:
        add_body(doc, "HIGH severity issues requiring IC attention:", bold=True, colour=RED)
        for f in high_findings[:5]:
            add_bullet(
                doc,
                f"{getattr(f, 'label', '')} — {(getattr(f, 'evidence', '') or '')[:120]}",
                colour=RED,
            )

    # ── 2. Market & Problem ──────────────────────────────────────────────────
    add_heading(doc, "2. Market & Problem", level=1)
    _write(writer, doc, "market_opportunity",
           slide_texts=collect_slide_texts(result, "market"),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "market", "ms"),
           max_tokens=500)

    market_flags = [
        f for f in all_findings
        if "market" in (getattr(f, "category", "") or "").lower()
        and getattr(f, "severity", "") in ("HIGH", "MEDIUM")
    ]
    if market_flags:
        add_heading(doc, "Market-Related Concerns", level=2)
        for f in market_flags:
            sev = getattr(f, "severity", "")
            add_labelled_bullet(doc, SEVERITY_LABEL.get(sev, sev),
                                f" {getattr(f, 'label', '')}",
                                colour=SEVERITY_COLOUR.get(sev, DARK_GREY))

    # ── 3. Technology & Product ──────────────────────────────────────────────
    add_heading(doc, "3. Technology & Product", level=1)
    _write(writer, doc, "technology_solution",
           slide_texts=(collect_slide_texts(result, "solution")
                        + collect_slide_texts(result, "technology")),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "tech", "ip", "ms"),
           max_tokens=500)

    tech_flags = [
        f for f in all_findings
        if any(k in (getattr(f, "category", "") or "").lower()
               for k in ("tech", "product", "ip"))
        and getattr(f, "severity", "") in ("HIGH", "MEDIUM")
    ]
    if tech_flags:
        add_heading(doc, "Technology Risk Flags", level=2)
        for f in tech_flags:
            sev = getattr(f, "severity", "")
            add_labelled_bullet(doc, SEVERITY_LABEL.get(sev, sev),
                                f" {getattr(f, 'label', '')} — "
                                f"{(getattr(f, 'evidence', '') or '')[:120]}",
                                colour=SEVERITY_COLOUR.get(sev, DARK_GREY))

    # ── 4. Financials ────────────────────────────────────────────────────────
    add_heading(doc, "4. Financials", level=1)
    add_body(doc,
             "All financial data is sourced from the pitch deck and has not been "
             "independently audited. The committee should request supporting schedules "
             "before placing material reliance on these figures.",
             italic=True)
    _write(writer, doc, "comments_financials",
           slide_texts=(collect_slide_texts(result, "financials")
                        + collect_slide_texts(result, "cap_table")
                        + collect_slide_texts(result, "traction")),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "financ", "revenue", "valuat", "cap"),
           slide_tables=collect_slide_tables(result, "financials")
                        + collect_slide_tables(result, "cap_table")
                        + collect_slide_tables(result, "traction"),
           max_tokens=500)

    fin_flags = [
        f for f in all_findings
        if any(k in (getattr(f, "category", "") or "").lower()
               for k in ("financ", "revenue", "valuat", "cap", "funding"))
    ]
    if fin_flags:
        add_heading(doc, "Financial Anomaly Findings", level=2)
        add_findings_table(doc, fin_flags)

    # ── 5. GTM & Traction ────────────────────────────────────────────────────
    add_heading(doc, "5. GTM & Traction", level=1)
    _write(writer, doc, "traction",
           slide_texts=(collect_slide_texts(result, "traction")
                        + collect_slide_texts(result, "financials")),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "traction", "gtm", "customer", "metric"),
           max_tokens=500)

    gtm_flags = [
        f for f in all_findings
        if any(k in (getattr(f, "category", "") or "").lower()
               for k in ("traction", "gtm", "customer", "metric", "growth"))
    ]
    if gtm_flags:
        add_heading(doc, "GTM / Traction Concerns", level=2)
        for f in gtm_flags:
            sev = getattr(f, "severity", "")
            add_labelled_bullet(doc, SEVERITY_LABEL.get(sev, sev),
                                f" {getattr(f, 'label', '')}",
                                colour=SEVERITY_COLOUR.get(sev, DARK_GREY))

    if questions:
        add_heading(doc, "Key Diligence Questions", level=2)
        for cat, qs in list(questions.items())[:3]:
            add_heading(doc, cat, level=3)
            for q in qs[:5]:
                add_bullet(doc, str(q))

    # ── 6. Competitive Landscape ─────────────────────────────────────────────
    add_heading(doc, "6. Competitive Landscape", level=1)
    _write(writer, doc, "competitive_landscape",
           slide_texts=(collect_slide_texts(result, "market")
                        + collect_slide_texts(result, "technology")),
           unknown_texts=unknowns,
           findings_summary=findings_summary_for(result, "competi", "ms"),
           max_tokens=450)

    comp_flags = [
        f for f in all_findings
        if "competi" in (getattr(f, "category", "") or "").lower()
    ]
    if comp_flags:
        add_heading(doc, "Competitive Risk Flags", level=2)
        for f in comp_flags:
            sev = getattr(f, "severity", "")
            add_labelled_bullet(doc, SEVERITY_LABEL.get(sev, sev),
                                f" {getattr(f, 'label', '')}",
                                colour=SEVERITY_COLOUR.get(sev, DARK_GREY))

    # ── 7. Comments & Observations ───────────────────────────────────────────
    add_heading(doc, "7. Comments & Observations", level=1)

    obs_map = [
        ("7.1 Technology",  "comments_technology",
         ["technology", "solution"],      ["tech", "ip"]),
        ("7.2 Financials",  "comments_financials",
         ["financials", "cap_table"],     ["financ", "revenue", "valuat"]),
        ("7.3 Regulations", "comments_regulations",
         ["market"],                      ["regulat", "legal", "compliance"]),
        ("7.4 GTM",         "comments_gtm",
         ["traction", "market"],          ["traction", "gtm", "customer"]),
        ("7.5 Competition", "comments_competition",
         ["market", "technology"],        ["competi", "ms"]),
        ("7.6 Other",       "areas_to_watch",
         ["cover"],                       []),
    ]

    for heading_text, key, slide_keys, finding_keys in obs_map:
        add_heading(doc, heading_text, level=2)
        slides = []
        for sk in slide_keys:
            slides += collect_slide_texts(result, sk)
        _write(writer, doc, key,
               slide_texts=slides,
               unknown_texts=unknowns,
               findings_summary=findings_summary_for(result, *finding_keys) if finding_keys
                                else all_findings_summary(result),
               max_tokens=350)

    # ── 8. IC Memo Summary ───────────────────────────────────────────────────
    add_heading(doc, "8. IC Memo Summary", level=1)

    # 8.1 Positive Signals — LLM generates as one-sentence-per-line
    add_heading(doc, "8.1 Positive Signals", level=2)
    positive_lines = writer.write_lines(
        "ic_summary_positive",
        slide_texts=(collect_slide_texts(result, "cover")
                     + collect_slide_texts(result, "market")
                     + collect_slide_texts(result, "solution")),
        unknown_texts=unknowns,
        findings_summary=all_findings_summary(result),
        framework="B",
        max_tokens=300,
    )
    for line in positive_lines:
        add_bullet(doc, line, colour=GREEN)

    # 8.2 Key Risks — LLM generates as one-sentence-per-line
    add_heading(doc, "8.2 Key Risks", level=2)

    # Always show pipeline HIGH risks as structured bullets first
    key_risks = list(ic_risks) + [f for f in high_findings if f not in ic_risks]
    if key_risks:
        for f in key_risks[:10]:
            sev = getattr(f, "severity", "")
            add_labelled_bullet(doc, SEVERITY_LABEL.get(sev, sev),
                                f" {getattr(f, 'label', '')} — "
                                f"{(getattr(f, 'evidence', '') or '')[:120]}",
                                colour=SEVERITY_COLOUR.get(sev, DARK_GREY))

    # Then LLM-generated risk commentary
    risk_lines = writer.write_lines(
        "ic_summary_risks",
        slide_texts=(collect_slide_texts(result, "cover")
                     + collect_slide_texts(result, "financials")
                     + collect_slide_texts(result, "traction")),
        unknown_texts=unknowns,
        findings_summary=all_findings_summary(result),
        framework="B",
        max_tokens=300,
    )
    for line in risk_lines:
        add_bullet(doc, line, colour=RED)

    # 8.3 One-sentence recommendation
    add_heading(doc, "8.3 Recommendation", level=2)
    rec = writer.write_section(
        "ic_recommendation",
        slide_texts=(collect_slide_texts(result, "cover")
                     + collect_slide_texts(result, "market")
                     + collect_slide_texts(result, "financials")
                     + collect_slide_texts(result, "traction")),
        unknown_texts=unknowns,
        findings_summary=all_findings_summary(result),
        framework="B",
        max_tokens=120,
    )
    add_body(doc, rec, bold=True)

    return doc