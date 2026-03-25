"""
section_writer.py
LLM-powered prose generator for the DD report and IC memo.

Uses the project's existing LLM adapter (llm/adapter.py) to write each
report section as polished, VC-grade prose from raw slide content and
anomaly findings.

All public functions follow the same safe contract:
  - Never raise — on any LLM failure they return a fallback string.
  - Accept only plain Python types so callers need no special setup.

Usage:
    from section_writer import SectionWriter
    writer = SectionWriter()                    # uses LLM_PROVIDER env var
    writer = SectionWriter(provider="groq")     # explicit provider

    text = writer.write_section(
        section_name="Product Description",
        slide_texts=["Low-Qem will be Qatar's first battery..."],
        unknown_texts=["Greg Bogie bio...", "disclaimer..."],
        findings_summary="2 HIGH, 1 MEDIUM findings",
        framework="A",   # "A" = factual DD tone, "B" = skeptical IC memo tone
    )
"""

from __future__ import annotations

import sys
import os
from typing import Optional

# ---------------------------------------------------------------------------
# LLM adapter import — handles llm/adapter.py subdirectory layout
# ---------------------------------------------------------------------------

def _load_adapter():
    """
    Import get_llm from llm/adapter.py regardless of how the project is run.
    Adds the parent of the llm/ package to sys.path if needed.
    """
    # Try direct import first (works if project root is already on sys.path)
    try:
        from llm.adapter import get_llm
        return get_llm
    except ImportError:
        pass

    # Walk up from this file's directory looking for llm/adapter.py
    base = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):  # search up to 4 levels up
        candidate = os.path.join(base, "llm", "adapter.py")
        if os.path.exists(candidate):
            if base not in sys.path:
                sys.path.insert(0, base)
            from llm.adapter import get_llm
            return get_llm
        base = os.path.dirname(base)

    raise ImportError(
        "Could not find llm/adapter.py. "
        "Ensure the llm/ directory is on your Python path."
    )


# ---------------------------------------------------------------------------
# Shared prompt building utilities
# ---------------------------------------------------------------------------

_FALLBACK_NOTE = "[LLM unavailable — review and complete this section manually.]"

_BOILERPLATE_SIGNALS = [
    "disclaimer", "this presentation has been prepared",
    "does not purport to be complete", "forward looking statements",
    "not constitute financial advice", "greg@", "@", "chief executive",
    "contacts", "low qem consulting", "low-qem consulting",
]


def _is_boilerplate(text: str) -> bool:
    """Return True if a text block looks like a disclaimer / contact slide."""
    lower = text.lower()
    hits = sum(1 for s in _BOILERPLATE_SIGNALS if s in lower)
    return hits >= 2


def _format_table(table) -> str:
    """
    Format a slide table as labelled plain text.
    Adds explicit row-boundary markers so the LLM cannot misread a value
    from one row (e.g. Seed IRR) as applying to the project as a whole.
    Accepts list-of-lists or list-of-dicts.
    """
    if not table:
        return ""
    lines = ["[TABLE — read each row independently, values do not apply across rows]"]
    try:
        if isinstance(table[0], dict):
            headers = list(table[0].keys())
            lines.append(" | ".join(str(h) for h in headers))
            lines.append("-" * 60)
            for row in table:
                lines.append(" | ".join(str(row.get(h, "")) for h in headers))
        else:
            for row in table:
                lines.append(" | ".join(str(cell) for cell in row))
    except Exception:
        lines.append(str(table))
    lines.append("[END TABLE]")
    return "\n".join(lines)

def _build_slide_context(
    slide_texts: list[str],
    unknown_texts: list[str],
    slide_tables: list = None,
) -> str:
    """
    Combine named-section slides, their tables, and UNKNOWN slides into a
    single context block for the LLM. Tables are formatted with explicit
    row-boundary labels so the LLM cannot misread values across rows.
    """
    parts: list[str] = []

    for t in slide_texts:
        t = t.strip()
        if t and not _is_boilerplate(t):
            parts.append(t)

    for tbl in (slide_tables or []):
        formatted = _format_table(tbl)
        if formatted:
            parts.append(formatted)

    for t in unknown_texts:
        t = t.strip()
        if t and not _is_boilerplate(t):
            parts.append(f"[Additional slide content]\n{t}")

    return "\n\n---\n\n".join(parts) if parts else ""


def _findings_bullets(findings_summary: str) -> str:
    return f"\nAnomaly findings summary:\n{findings_summary}" if findings_summary else ""


# ---------------------------------------------------------------------------
# Per-section system prompts
# ---------------------------------------------------------------------------

_SYSTEM_A = """\
You are a senior associate at a venture capital firm writing a formal due diligence report.
Your tone is professional, factual, and analytical — similar to a McKinsey or Goldman Sachs
style memo. Write in clear paragraphs (no markdown, no bullet points in your output).
Synthesise the provided slide content into coherent prose for the requested section.
If key information is missing, note the gap explicitly rather than fabricating details.

GROUNDING RULES — these are absolute and override all other instructions:
1. ONLY state facts that are explicitly present in the provided slide content.
   Do not infer, extrapolate, or assume anything beyond what is written.
2. NEVER attribute a specific benefit or relationship to the company unless the
   slides explicitly state it. If a slide says X is available in Qatar generally,
   do NOT say the company will specifically receive X.
3. When reading tables, read each row independently. Do not apply a value (e.g.
   an IRR figure) labelled for one funding stage to a different stage or the
   project as a whole.
4. If information is genuinely absent from the slides, say "the deck does not
   address X" and move on. Do NOT invent what that information might be.
5. Only flag a gap or concern if you can point to specific slide text that is
   missing or contradictory. Do not invent concerns about topics the slides
   simply did not cover.

Keep each section to 2–4 paragraphs unless the content warrants more.
Do not repeat the section heading in your response."""

_SYSTEM_B = """\
You are a skeptical senior VC partner writing a confidential IC memo for your investment committee.
Your tone is direct, critical, and unimpressed by hype — you have seen hundreds of decks.
Write in tight, opinionated paragraphs. Flag missing evidence, unverified claims, and structural
risks proactively. Use phrases like "the company claims", "management asserts", "unverified by
independent sources". Do not use bullet points or markdown in your output.

GROUNDING RULES — these are absolute and override all other instructions:
1. ONLY state facts that are explicitly present in the provided slide content.
   Do not infer, extrapolate, or assume anything beyond what is written.
2. NEVER attribute a specific benefit to the company unless the slides say so
   explicitly. If a slide says X is available in Qatar, say "Qatar offers X to
   businesses in the free zone" — not "the company will receive X."
3. When reading tables, read each row independently. Do not apply a figure (e.g.
   Seed IRR) labelled for one stage to a different stage or the project overall.
4. You may flag missing evidence — but ONLY if you can identify specific slide
   text that is absent or contradictory. Do not invent concerns about topics the
   slides simply did not discuss.
5. Use phrases like "the company claims", "management asserts", "the deck states"
   to attribute claims to their source rather than presenting them as verified.

Keep each section to 2–3 paragraphs. Do not repeat the section heading in your response."""


# ---------------------------------------------------------------------------
# Section-specific user prompt templates
# ---------------------------------------------------------------------------

_USER_PROMPTS: dict[str, str] = {

    "product_description": """\
Write the Product Description section. Cover: what the company does, the problem it addresses,
its core value proposition, and target customers. Use only the slide content provided.

Slide content:
{context}
{findings}""",

    "technology_solution": """\
Write the Technology Solution section. Cover: what the technology does, how it works at a high
level, key innovations, and any claims about competitive advantage. Note any gaps or unverified
technical claims.

Slide content:
{context}
{findings}""",

    "business_model": """\
Write the Business Model section. Cover: how the company makes money, revenue streams, pricing
model (if mentioned), key partnerships, and customer acquisition approach.

Slide content:
{context}
{findings}""",

    "technology_overview": """\
Write the Technology Overview section covering technical architecture, IP, and defensibility.
Be specific about what is known from the deck and what is absent or unverified.

Slide content:
{context}
{findings}""",

    "team": """\
Write the Team section. Summarise each key person's background, relevant experience, and role.
Note if team information is sparse or if key roles appear unfilled.

Slide content:
{context}
{findings}""",

    "cap_table": """\
Write the Cap Table and Funding section. Cover: current ownership structure, funding history,
amount being raised, valuation (if stated), and use of proceeds. Flag any unusual terms or gaps.

IMPORTANT: If the slides include a table of IRR or valuation figures across multiple funding
stages, report each stage's figure separately with its explicit stage label. Do NOT apply a
figure from one stage (e.g. Seed >100x IRR) to the project as a whole or to later stages.

Slide content:
{context}
{findings}""",

    "traction": """\
Write the Traction section. Cover: key metrics (ARR, MRR, customers, growth rate), milestones
achieved, and evidence of product-market fit. Be explicit about what is verified vs. claimed.

Slide content:
{context}
{findings}""",

    "market_opportunity": """\
Write the Market Opportunity section. Cover: TAM/SAM/SOM, market dynamics, demand drivers,
and the company's positioning within the market.

IMPORTANT: When mentioning government bodies, funds, or programmes (e.g. QIA, QFZ, NDS3),
only state what the slides say they offer to businesses in general. Do NOT state that the
company will specifically receive those benefits unless the slides say so explicitly.
Note any unsourced market size claims.

Slide content:
{context}
{findings}""",

    "competitive_landscape": """\
Write the Competitive Landscape section. Identify named competitors if present, assess the
company's differentiation claims, and flag if competitive analysis is absent or superficial.

Slide content:
{context}
{findings}""",

    "investment_rationale": """\
Write the Investment Rationale section. Summarise the bull case: key strengths, market timing,
strategic advantages, and reasons to invest. Ground every positive claim in specific slide evidence.

Slide content:
{context}
{findings}""",

    "areas_to_watch": """\
Write the Areas to Watch section. Identify the key risks and concerns: execution risks, market
risks, financial risks, regulatory risks, and anything missing from the deck that a serious
investor would expect to see.

Slide content:
{context}
{findings}""",

    "comments_technology": """\
Write a Technology observations paragraph for the Comments & Observations section.
Focus on: technical credibility, IP defensibility, scalability concerns, and any red flags
in the technology claims.

Slide content:
{context}
{findings}""",

    "comments_financials": """\
Write a Financials observations paragraph for the Comments & Observations section.
Focus on: quality of financial data presented, revenue model clarity, unit economics,
burn rate, runway, and any anomalies flagged by the pipeline.

Slide content:
{context}
{findings}""",

    "comments_regulations": """\
Write a Regulatory observations paragraph for the Comments & Observations section.
Consider: industry-specific regulatory requirements, geographic compliance risks,
and anything in the deck that suggests regulatory exposure.

Slide content:
{context}
{findings}""",

    "comments_gtm": """\
Write a GTM (Go-to-Market) observations paragraph for the Comments & Observations section.
Focus on: clarity of GTM strategy, evidence of sales pipeline, channel strategy,
customer acquisition approach, and early traction evidence.

Slide content:
{context}
{findings}""",

    "comments_competition": """\
Write a Competition observations paragraph for the Comments & Observations section.
Focus on: depth of competitive analysis, named competitors, differentiation claims,
and whether the competitive moat is credible.

Slide content:
{context}
{findings}""",

    "final_call_a": """\
Write the Final Call / Recommendation section of a due diligence report.
Provide a balanced assessment: summarise the bull case and bear case, then give a clear
recommendation (Pass / Conditional Proceed / Proceed to Full Diligence) with 2–3 specific
conditions or next steps.

All slide content:
{context}
{findings}""",

    "executive_summary_b": """\
Write the Executive Summary for an IC memo. In 2–3 tight paragraphs: (1) what the company does
and the opportunity, (2) the headline investment thesis, (3) the two or three things that would
make or break this deal. Be direct and sceptical.

Slide content:
{context}
{findings}""",

    "ic_summary_positive": """\
Write 3–5 bullet-style sentences (as plain prose, one per line) describing the positive signals
from this deal — things that are genuinely encouraging. Be specific and grounded in the deck.
Do not use bullet characters, just one sentence per line.

Slide content:
{context}
{findings}""",

    "ic_summary_risks": """\
Write 3–5 bullet-style sentences (as plain prose, one per line) describing the key risks and
red flags in this deal. Be direct and specific. Do not soften concerns.
Do not use bullet characters, just one sentence per line.

Slide content:
{context}
{findings}""",

    "ic_recommendation": """\
Write a single, decisive sentence recommending what the IC should do with this deal.
Choose from: Pass / Request Further Information / Proceed to Full Diligence.
Include the single most important condition attached to that recommendation.
Output only the one sentence — nothing else.

Slide content:
{context}
{findings}""",
}


# ---------------------------------------------------------------------------
# SectionWriter class
# ---------------------------------------------------------------------------

class SectionWriter:
    """
    Generates LLM-written prose for each report section.

    Parameters
    ----------
    provider : str, optional
        LLM provider override ("groq", "claude", "openai", "ollama").
        Falls back to LLM_PROVIDER env var, then defaults to "groq".
    """

    def __init__(self, provider: str = None):
        try:
            get_llm = _load_adapter()
            resolved_provider = provider or os.environ.get("LLM_PROVIDER", "groq")
            self._llm = get_llm(resolved_provider)
            self._available = True
        except Exception as e:
            print(f"[SectionWriter] LLM unavailable: {e}. Reports will use placeholders.")
            self._llm = None
            self._available = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write_section(
        self,
        section_key: str,
        slide_texts: list[str],
        unknown_texts: list[str],
        findings_summary: str = "",
        framework: str = "A",
        max_tokens: int = 600,
        slide_tables: list = None,
    ) -> str:
        """
        Generate prose for a named report section.

        Parameters
        ----------
        section_key : str
            Key into _USER_PROMPTS (e.g. "product_description", "team").
        slide_texts : list[str]
            Cleaned text from slides classified to this section.
        unknown_texts : list[str]
            Cleaned text from UNKNOWN slides (boilerplate is auto-filtered).
        findings_summary : str
            One-line or multi-line summary of relevant anomaly findings.
        framework : str
            "A" = factual DD tone, "B" = skeptical IC partner tone.
        max_tokens : int
            Cap on LLM output length.

        Returns
        -------
        str
            Generated prose, or a fallback string if LLM is unavailable.
        """
        if not self._available:
            return _FALLBACK_NOTE

        context = _build_slide_context(slide_texts, unknown_texts, slide_tables)
        if not context:
            context = "[No slide content available for this section.]"

        template = _USER_PROMPTS.get(section_key)
        if not template:
            return _FALLBACK_NOTE

        user_prompt = template.format(
            context=context,
            findings=_findings_bullets(findings_summary),
        )
        system_prompt = _SYSTEM_A if framework == "A" else _SYSTEM_B

        try:
            response = self._llm.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=max_tokens,
            )
            return response.text.strip()
        except Exception as e:
            print(f"[SectionWriter] LLM call failed for '{section_key}': {e}")
            return _FALLBACK_NOTE

    def write_lines(
        self,
        section_key: str,
        slide_texts: list[str],
        unknown_texts: list[str],
        findings_summary: str = "",
        framework: str = "B",
        max_tokens: int = 400,
    ) -> list[str]:
        """
        Like write_section but returns a list of lines (for bullet-style output).
        Used for ic_summary_positive, ic_summary_risks.
        """
        text = self.write_section(
            section_key, slide_texts, unknown_texts,
            findings_summary, framework, max_tokens,
        )
        if text == _FALLBACK_NOTE:
            return [_FALLBACK_NOTE]
        # Split on newlines and strip empty lines
        return [line.strip() for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Helper: extract all slide texts from result for a given section key
# ---------------------------------------------------------------------------

def collect_slide_texts(result, section_name: str) -> list[str]:
    """
    Return cleaned_text (or raw_text) for all slides matching section_name.
    Normalises pipeline labels (CAP_TABLE → cap table) before matching.
    """
    try:
        slides = result.deck.slides
    except AttributeError:
        return []

    needle = section_name.lower().replace("_", " ")
    texts = []
    for s in slides:
        raw = getattr(s, "detected_section", "") or ""
        norm = raw.lower().replace("_", " ")
        if norm == "unknown":
            continue
        if needle in norm or norm in needle:
            txt = getattr(s, "cleaned_text", "") or getattr(s, "raw_text", "") or ""
            if txt.strip():
                texts.append(txt.strip())
    return texts


def collect_unknown_texts(result) -> list[str]:
    """Return cleaned_text for all UNKNOWN slides."""
    try:
        slides = result.deck.slides
    except AttributeError:
        return []
    texts = []
    for s in slides:
        raw = getattr(s, "detected_section", "") or ""
        if raw.upper() == "UNKNOWN":
            txt = getattr(s, "cleaned_text", "") or getattr(s, "raw_text", "") or ""
            if txt.strip():
                texts.append(txt.strip())
    return texts



def collect_slide_tables(result, section_name: str) -> list:
    """
    Return all tables from slides matching section_name.
    Pass these to write_section(slide_tables=...) so structured data
    (e.g. IRR tables across funding stages) is presented with row labels
    that prevent the LLM from misreading values across rows.
    """
    try:
        slides = result.deck.slides
    except AttributeError:
        return []

    needle = section_name.lower().replace("_", " ")
    tables = []
    for s in slides:
        raw  = getattr(s, "detected_section", "") or ""
        norm = raw.lower().replace("_", " ")
        if norm == "unknown":
            continue
        if needle in norm or norm in needle:
            for tbl in (getattr(s, "tables", None) or []):
                if tbl:
                    tables.append(tbl)
    return tables

def findings_summary_for(result, *category_keywords: str) -> str:
    """
    Build a short findings summary string for a given set of category keywords.
    Passes to the LLM as context so it can reference flagged issues.
    """
    try:
        findings = result.all_findings or []
    except AttributeError:
        return ""

    if not category_keywords:
        relevant = findings
    else:
        relevant = [
            f for f in findings
            if any(
                kw.lower() in (getattr(f, "category", "") or "").lower()
                for kw in category_keywords
            )
        ]

    if not relevant:
        return ""

    lines = []
    for f in relevant:
        sev    = getattr(f, "severity", "")
        status = getattr(f, "status", "")
        label  = getattr(f, "label", "")
        ev     = (getattr(f, "evidence", "") or "")[:100]
        lines.append(f"[{sev}/{status}] {label} — {ev}")
    return "\n".join(lines)


def all_findings_summary(result) -> str:
    """Full findings summary — used for final call / IC summary sections."""
    return findings_summary_for(result)