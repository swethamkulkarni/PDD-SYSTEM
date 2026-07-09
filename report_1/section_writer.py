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

# ADDED: 24/05
def _strip_gap_sections(text: str) -> str:
    """
    Remove any gap/concerns blocks the LLM generates despite system prompt
    instructions. Strips lines and paragraphs containing gap-related markers.
    """
    _GAP_MARKERS = [
        "gaps / concerns:",
        "gaps/concerns:",
        "gaps:",
        "concerns:",
        "the deck does not address",
        "the deck does not include",
        "the deck does not provide",
        "no data available",
        "information gap:",
        "suggested follow-up:",
        "follow-up question:",
        "not addressed in the deck",
        "absent from the deck",
        "not present in the deck",
        "not explicitly mentioned",
        "not explicitly stated",
        "not disclosed in the deck",
    ]

    lines = text.splitlines()
    cleaned = []
    skip_block = False

    for line in lines:
        lower = line.strip().lower()

        # Detect a gap sub-header — skip it and the lines that follow
        if any(lower.startswith(m) for m in _GAP_MARKERS[:6]):
            skip_block = True
            continue

        # A blank line ends the skip block
        if skip_block and line.strip() == "":
            skip_block = False
            continue

        if skip_block:
            continue

        # Skip individual lines containing gap language anywhere
        if any(m in lower for m in _GAP_MARKERS[6:]):
            continue

        cleaned.append(line)

    # Remove trailing blank lines
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    return "\n".join(cleaned)

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

# Edited: 04/06/26
def extract_company_name_llm(result, llm) -> str:
    """
    Use a single cheap LLM call to extract the company name from cover/first slides.
    Falls back to programmatic extraction if LLM is unavailable or returns nothing.
    """
    # Collect cover slide text only — cheap context
    cover_text = ""
    try:
        for slide in result.deck.slides[:4]:   # only first 4 slides
            txt = (getattr(slide, "cleaned_text", "")
                   or getattr(slide, "raw_text", "") or "").strip()
            if txt and not _is_boilerplate(txt):
                cover_text += txt + "\n"
            if len(cover_text) > 800:           # cap context size
                break
    except AttributeError:
        pass

    if not cover_text.strip():
        return ""

    try:
        response = llm.complete(
            system_prompt=(
                "You extract company names from pitch deck text. "
                "Reply with ONLY the company name — nothing else. "
                "No explanation, no punctuation, no quotes."
            ),
            user_prompt=(
                f"What is the name of the company described in this pitch deck text?\n\n"
                f"{cover_text[:800]}"
            ),
            temperature=0.0,
            max_tokens=15,        # company name is never more than 15 tokens
        )
        name = response.text.strip().strip('"\'')
        # Sanity check — reject if it looks like a sentence
        if name and len(name.split()) <= 6 and len(name) <= 60:
            return name
    except Exception as e:
        print(f"[extract_company_name_llm] LLM call failed: {e}")

    return ""

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
# GAPS/concerns removed: 24/05
# ---------------------------------------------------------------------------

# Edited 2024-06-20: refined system prompts for sharper tone and clearer grounding rules.
_SYSTEM_A = """\
You are a senior associate at a venture capital firm writing a preliminary due diligence report
for internal investment review. Your role is to INTERPRET and ANALYSE — not summarise the deck.
Add investor-grade perspective: assess credibility, flag what needs verification, and draw
inferences that a first-time reader of the deck would miss.

OUTPUT FORMAT — follow this exactly:
- Begin with one SHORT analytical paragraph (2–4 sentences) giving your assessment of the
  section — not a description of what the deck says, but your read of it as an investor.
- Then provide 3–6 bullet points (start each with "• ") giving specific evidence, observations,
  or flagged gaps. Each bullet is one concise sentence. Mix confirmed facts with your assessment
  of their credibility where relevant.
- If there are notable gaps or concerns, add a short "Gaps / Concerns:" sub-header followed
  by 1–3 bullets naming exactly what is missing or unverified.
- Do NOT write long paragraphs. Keep the whole section tight and scannable.
- Do NOT use markdown headers, bold, or any other formatting — plain text only.
- Do NOT repeat the section heading in your response.
- Do NOT begin with phrases like "The deck states" or "The pitch deck covers" — write as
  if you are briefing a partner who has not read the deck.

GROUNDING RULES — absolute, override everything else:
1. Only state facts explicitly present in the provided slide content.
2. Never attribute a specific benefit to the company unless the slides state it directly.
3. Read table rows independently — never apply a figure from one stage to another.
4. If information is absent, say "the deck does not address X" — do not invent it.
5. Do NOT include a Gaps section, "Gaps / Concerns:" sub-header, or any "the deck does not address" statements.
6. Do NOT flag missing information or absent slides — write only about what is present.
7. Distinguish between verified facts and unverified claims using phrases like
   "the company reports", "claimed by management", "as yet unaudited"."""

_SYSTEM_B = """\
You are a skeptical senior VC partner writing a confidential IC memo for your investment committee.
You have seen hundreds of decks. You are direct, critical, and allergic to unsubstantiated claims.

OUTPUT FORMAT — follow this exactly:
- Begin with one SHORT, opinionated paragraph (2–4 sentences) giving your overall read.
  Use phrases like "the company claims", "management asserts", "the deck states".
- Then provide 3–6 bullet points (start each with "• ") covering specific evidence,
  unverified claims, red flags, or structural risks. One sentence per bullet.
- If there are critical risks, add a "Red Flags:" sub-header followed by 1–3 bullets.
  Only include if there are genuine red flags from the slide content.
- Keep the whole section tight. No long paragraphs. Scannable for busy partners.
- Do NOT use markdown headers, bold, or any other formatting — plain text only.
- Do NOT repeat the section heading in your response.

GROUNDING RULES — absolute, override everything else:
1. Only state facts explicitly present in the provided slide content.
2. Never attribute a specific benefit to the company unless the slides state it directly.
3. Read table rows independently — never apply a figure from one stage to another.
4. Do NOT include gap notes, "Red Flags:" sub-headers for missing information, or
   "the deck does not address" statements — write only about what is present.
5. Attribute all claims: "the company claims", "the deck states", "management asserts"."""
#  Edit: 24/05 - changed for gaps/concerns rules 4 and 5
# ---------------------------------------------------------------------------
# Founder-facing suggestion prompt (Company Mode)
# ---------------------------------------------------------------------------

_SYSTEM_SUGGESTION = """\
You are a pitch deck coach helping a startup founder strengthen their fundraising deck
before talking to investors. You are direct and specific, never generic, and always
encouraging — founders should feel motivated to fix the gap, not discouraged by it.

For the flagged issue you are given, write ONE short, specific, actionable suggestion
telling the founder exactly what to add or change. Include a concrete example of what
strong content would look like for their specific situation — not generic advice like
"add more detail" or "be more specific".

RULES:
- 2-3 sentences maximum.
- No markdown, no bullet points, no headers — plain text only.
- Do not restate the problem — the founder already sees the flag. Go straight to the fix.
- Ground your example in the actual slide content provided, where possible.
- Never use investor-facing language like "this is a red flag" or "material gap" —
  speak directly to the founder as a coach, not an auditor."""


_SUGGESTION_PROMPT_TEMPLATE = """\
Flagged issue: {label}
What was found: {evidence}

Relevant slide content:
{context}

Write the founder-facing suggestion now."""
# ---------------------------------------------------------------------------
# Section-specific user prompt templates
# ---------------------------------------------------------------------------

_USER_PROMPTS: dict[str, str] = {

    # ------------------------------------------------------------------
    # Framework A — DD Report sections
    # ------------------------------------------------------------------

    "product_description": """\
Write the Product Description section for a preliminary due diligence report.

Cover ALL of the following — if any are absent from the slides, say so explicitly:
1. What the company does and the specific problem it solves (not generic market pain — the precise pain point)
2. Why existing solutions are inadequate (the "why now" / "why this" framing)
3. The company's specific solution and core value proposition — what makes it different
4. Target customer segments and their profile
5. Stage of the product (concept / MVP / live / scaling)

Format: one short summary paragraph, then bullet points for each of points 1–5 above.

Slide content:
{context}
{findings}""",

    "technology_solution": """\
Write the Technology Solution section for a preliminary due diligence report.

Cover ALL of the following — flag any that are absent:
1. How the technology works — specific mechanism, not just category labels
2. Key technical innovations claimed and the evidence supporting them
3. AI / ML components: what models, training data, outputs (if applicable)
4. Scalability: can it handle 10x or 100x load — what does the deck say?
5. Technical risks or limitations acknowledged in the deck
6. IP position: patents, trade secrets, proprietary data — what is stated vs. implied

The technology section must go beyond restating the product pitch. Identify where the deck
is vague or makes unverified technical claims. Note gaps explicitly.

Slide content:
{context}
{findings}""",

    "business_model": """\
Write the Business Model section for a preliminary due diligence report.

Cover ALL of the following — flag any that are absent or unclear:
1. Revenue streams — how the company charges (SaaS, transaction fee, licence, etc.)
2. Pricing model — specific price points or tiers if mentioned; if not, say so
3. Unit economics: CAC, LTV, gross margin — stated or implied
4. Key commercial relationships: customers, partners, distribution channels
5. Revenue trajectory: current ARR/MRR, growth rate, projections and their basis
6. Monetisation gaps: what is missing that a full DD would require

The business model section should assess commercial viability, not just describe it.
Note where the model is early-stage, unproven, or dependent on assumptions not validated.

Slide content:
{context}
{findings}""",

    "technology_overview": """\
Write the Technology Overview — Technical Architecture sub-section.

Focus on:
1. System architecture at a conceptual level (what components, how they connect)
2. Data infrastructure: sources, pipelines, storage — what is described
3. AI/ML specifics if applicable: approach, training, inference, accuracy claims
4. Integration points with third-party systems or APIs
5. Security, reliability, and compliance considerations mentioned

Be precise about what is explicitly described vs. what is implied or absent.
A vague "proprietary AI platform" claim is not architecture — call it out.

Slide content:
{context}
{findings}""",

    "team": """\
Write the Team section for a preliminary due diligence report.

Cover ALL of the following:
1. Each named team member: role, relevant prior experience, notable achievements
2. Domain expertise: is the team qualified for the specific problem they are solving?
3. Execution track record: have they built and scaled companies before?
4. Team completeness: are there obvious gaps (e.g. missing technical lead, sales lead)?
5. Advisors or board members if mentioned — note if advisory board is used to compensate for team gaps

Be direct about thin team profiles. A single founder with generalist experience is a risk — say so.
Note if the deck over-indexes on logos (Google, Goldman etc.) without specific role context.

Slide content:
{context}
{findings}""",

    "cap_table": """\
Write the Cap Table and Funding section for a preliminary due diligence report.

Cover ALL of the following — flag any that are absent:
1. Current ownership structure: founders, employees, existing investors — percentages if stated
2. Funding history: rounds raised, amounts, investors, dates
3. Current raise: amount, instrument (equity / SAFE / convertible), valuation or cap
4. Use of proceeds: how the raised capital will be deployed (specific allocations if given)
5. Runway: how long the current/proposed raise covers at stated burn rate
6. Red flags: unusual terms, high dilution, missing information on ownership

IMPORTANT: If the slides include IRR or return figures across multiple funding stages,
report each stage's figure with its explicit label. Never apply one stage's figure to another.
If cap table details are absent, say so directly — this is a material gap.

Slide content:
{context}
{findings}""",

    "traction": """\
Write the Traction section for a preliminary due diligence report.

Cover ALL of the following — flag any that are absent or unsubstantiated:
1. Revenue metrics: current ARR/MRR, growth rate (MoM or YoY), trend
2. Customer metrics: number of customers, customer names (if given), retention / churn
3. Pipeline: qualified leads, pilots, LOIs — distinguish signed from verbal commitments
4. Milestones achieved: product launches, partnerships, regulatory approvals
5. Evidence quality: are metrics audited, self-reported, or projection-only?

Traction is the most verifiable section — be explicit about what is concrete vs. claimed.

Slide content:
{context}
{findings}""",

    "market_opportunity": """\
Write the Market Opportunity section for a preliminary due diligence report.

Cover ALL of the following:
1. Total Addressable Market (TAM) — size and source; note if unsourced
2. Serviceable Addressable Market (SAM) and Serviceable Obtainable Market (SOM) if stated
3. Market dynamics: growth drivers, tailwinds, structural shifts
4. Demand evidence: regulatory mandates, corporate ESG commitments, customer pull signals
5. The company's specific positioning within this market
6. Market risk: what could suppress or delay demand

IMPORTANT: Only state that the company will benefit from a government programme or fund
if the slides explicitly say so. If the slides describe general market context, attribute it
as such — "the market offers X" not "the company will receive X".

Slide content:
{context}
{findings}""",

    "competitive_landscape": """\
Write the Competitive Landscape section for a preliminary due diligence report.

Cover ALL of the following — flag where depth is lacking:
1. Named direct competitors: who are they, what do they offer, how big are they?
2. Named indirect competitors or substitutes
3. The company's stated differentiation: what specific claims are made?
4. Competitive moat: proprietary technology, data, contracts, network effects — what is real vs. claimed?
5. Vulnerability: where could a well-funded competitor replicate this in 12–24 months?
6. Competitive analysis quality: is the deck's competitive slide credible or superficial?

If no competitors are named, say so. A "no direct competitor" claim in an established market
is a red flag — note it explicitly. Generic differentiation claims ("faster, cheaper, better")
without evidence should be called out.

Slide content:
{context}
{findings}""",

    "investment_rationale": """\
Write the Investment Rationale section for a preliminary due diligence report.

Provide a structured bull case grounded entirely in slide evidence:
1. Market timing: why is now the right moment?
2. Unique advantage: what does this company have that others do not?
3. Team fit: why is this team positioned to win?
4. Commercial momentum: what early signals support the investment thesis?
5. Strategic value: exit potential, strategic acquirers, market leadership path

Every positive claim must be traceable to specific slide content.
Do not construct a bull case that the slides do not support.

Slide content:
{context}
{findings}""",

    "areas_to_watch": """\
Write the Areas to Watch / Key Risks section for a preliminary due diligence report.

Identify and assess the following risk categories — be specific, not generic:
1. Execution risk: team, timeline, operational complexity
2. Commercial risk: business model unproven, pricing untested, customer concentration
3. Technology risk: technical claims unverified, scalability undemonstrated, IP exposed
4. Financial risk: runway, burn, dependence on further fundraising
5. Regulatory / legal risk: compliance exposure, sector-specific regulation

For each risk, note whether it is addressable (with diligence) or structural.

Slide content:
{context}
{findings}""",

    # ------------------------------------------------------------------
    # Comments & Observations sub-sections
    # ------------------------------------------------------------------

# Edited 2024-06-20: refined prompts for sharper, more specific diligence questions grounded in slide content.
    "comments_technology": """\
Write the Technology sub-section of Comments & Observations.
Output a numbered list of sharp diligence questions a technical investor would ask
based on the gaps and unverified claims in the slide content below.
Each question should be specific to what is actually in (or missing from) the deck —
not generic technology questions. Aim for 5–8 questions.
Format: one introductory sentence, then numbered questions (1. 2. 3. etc.), one per line.

Slide content:
{context}
{findings}""",

    "comments_financials": """\
Write the Financials & Commercials sub-section of Comments & Observations.
Output a numbered list of specific diligence questions covering revenue quality,
unit economics, burn rate, financial projections, and commercial contract evidence.
Base questions on what is stated or notably absent in the slide content below.
Aim for 5–7 questions. Format: one introductory sentence, then numbered questions.

Slide content:
{context}
{findings}""",

    "comments_regulations": """\
Write the Regulations sub-section of Comments & Observations.
Output a numbered list of specific regulatory and compliance diligence questions
relevant to the company's sector, geography, and business model as described below.
Include questions about licences, data handling, cross-border compliance, and any
regulatory risks the deck acknowledges. Aim for 3–5 questions.
Format: one introductory sentence, then numbered questions.

Slide content:
{context}
{findings}""",

    "comments_gtm": """\
Write the GTM Strategy sub-section of Comments & Observations.
Output a numbered list of specific go-to-market diligence questions covering
channel strategy, customer acquisition, geographic expansion, competitive positioning,
and sales pipeline evidence — based on what the slides state or omit.
Aim for 4–6 questions. Format: one introductory sentence, then numbered questions.

Slide content:
{context}
{findings}""",

    "comments_competition": """\
Write the Competition sub-section of Comments & Observations.
Output a numbered list of specific competitive diligence questions covering
named competitors, differentiation credibility, moat defensibility, and benchmarking —
based on the competitive claims in the slide content below.
Aim for 4–6 questions. Format: one introductory sentence, then numbered questions.

Slide content:
{context}
{findings}""",

    # ------------------------------------------------------------------
    # Final Call / Recommendation
    # ------------------------------------------------------------------

# edited 2024-06-20: refined prompt for a clear, actionable final call with specific conditions and a positive outcome statement.
    "final_call_a": """\
Write the Final Call section of a preliminary due diligence report.
Structure your response with exactly three clearly labelled sub-sections:

Assessment Summary:
One short paragraph (3–5 sentences) giving an overall analytical verdict on the company —
what it has demonstrated, why it is interesting, and what the key open questions are.
Write as an investor briefing a partner, not as a summary of the deck.

Areas for Improvement:
3–5 bullet points (start each with "• ") naming the specific items that must be validated,
clarified, or strengthened before a full investment decision can be made.
Be specific — name the claim or gap, not just the category.

Conclusion:
One short paragraph (2–4 sentences) giving a clear disposition:
Pass | Request Further Information | Proceed to Full Diligence — and the key condition
attached to that call. End with one sentence on what a positive outcome would look like.

Use exactly these three sub-headers: "Assessment Summary:", "Areas for Improvement:", "Conclusion:"

All slide content:
{context}
{findings}""",

    # ------------------------------------------------------------------
    # Framework B — IC Memo sections
    # ------------------------------------------------------------------

    "executive_summary_b": """\
Write the Executive Summary for a confidential IC memo.

Cover the following in a tight, sceptical format:
1. What the company does and the problem it addresses (one sentence each)
2. The investment thesis — why this could be a meaningful return opportunity
3. The two or three factors that will make or break this deal
4. Your overall first impression: is this deck investment-ready or does it require further work?

Be direct. If the deck is thin on substance, say so immediately.
Do not soften concerns. The IC needs your honest read, not a summary of the pitch.

Format: one short paragraph + 4–6 bullets.

Slide content:
{context}
{findings}""",

    "ic_summary_positive": """\
List 4–6 specific positive signals from this deal that the IC should weigh.
Each point must be grounded in slide content — do not invent positives.
Write one signal per line, starting each with a dash (- ).
Be concise: one sentence per line.

Slide content:
{context}
{findings}""",

    "ic_summary_risks": """\
List 4–6 key risks and red flags from this deal for the IC to consider.
Each point must be specific — no generic "execution risk" without detail.
Write one risk per line, starting each with a dash (- ).
Be concise and direct: one sentence per line. Do not soften concerns.

Slide content:
{context}
{findings}""",

    "ic_recommendation": """\
Write a single, decisive sentence recommending what the IC should do with this deal.
Choose from: Pass | Request Further Information | Proceed to Full Diligence.
Include the single most important condition or next step attached to that recommendation.
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


    

# Edited: 04/06/26
    def get_company_name(self, result) -> str:
            """
            Extract company name using the LLM if available,
            falling back to programmatic extraction.
            """
            if self._available:
                name = extract_company_name_llm(result, self._llm)
                if name:
                    return name
            # Fallback to programmatic
            from report_1.doc_helpers import extract_company_name
            return extract_company_name(result)

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

# EDIT: 24/05
        try:
            response = self._llm.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=max_tokens,
            )
            return _strip_gap_sections(response.text.strip())
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

    def write_suggestion(
        self,
        finding,
        slide_texts: list[str],
        unknown_texts: list[str] = None,
        max_tokens: int = 150,
    ) -> str:
        """
        Generate a specific, actionable, founder-facing suggestion for one
        flagged or unclear finding. Used in company/founder mode.
        """
        if not self._available:
            return "Review this section with your team and add specific evidence to address the gap."

        context = _build_slide_context(slide_texts, unknown_texts or [], None)
        if not context:
            context = "[No relevant slide content found for this section.]"

        evidence = getattr(finding, "evidence", "") or "Not found in the deck."
        label    = getattr(finding, "label", "")

        user_prompt = _SUGGESTION_PROMPT_TEMPLATE.format(
            label=label,
            evidence=evidence,
            context=context,
        )

        try:
            response = self._llm.complete(
                system_prompt=_SYSTEM_SUGGESTION,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=max_tokens,
            )
            return response.text.strip()
        except Exception as e:
            print(f"[SectionWriter] Suggestion failed for '{getattr(finding, 'anomaly_id', '?')}': {e}")
            return "Review this section with your team and add specific evidence to address the gap."
    
    def write_company_overview(self, result) -> str:
        """
        Generate a 2-3 sentence company overview from cover/problem/solution slides.
        Used for the results screen summary strip.
            """
        if not self._available:
            return ""

        # Collect cover, problem and solution slide text
        context_parts = []
        try:
            for slide in result.deck.slides[:6]:
                section = (getattr(slide, "detected_section", "") or "").upper()
                if section in ("COVER", "PROBLEM", "SOLUTION", "BUSINESS_MODEL"):
                    txt = (getattr(slide, "cleaned_text", "")
                        or getattr(slide, "raw_text", "") or "").strip()
                    if txt and not _is_boilerplate(txt):
                        context_parts.append(txt)
        except AttributeError:
            return ""

        if not context_parts:
            return ""

        context = "\n\n".join(context_parts)[:2000]

        try:
            response = self._llm.complete(
                system_prompt=(
                    "You write concise company descriptions for investor reports. "
                    "Write 2-3 sentences maximum. Be factual and specific — "
                    "include what the company does, who it serves, and one concrete "
                    "fact (product, customer, or metric) if present in the content. "
                    "No hype, no adjectives like 'revolutionary' or 'innovative'. "
                    "Plain professional prose only."
                ),
                user_prompt=(
                    f"Write a 2-3 sentence factual description of this company "
                    f"based on their pitch deck content:\n\n{context}"
                ),
                temperature=0.1,
                max_tokens=120,
            )
            return response.text.strip()
        except Exception as e:
            print(f"[SectionWriter] Overview generation failed: {e}")
            return ""
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