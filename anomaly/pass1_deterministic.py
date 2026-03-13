"""
Pass 1 — Deterministic Anomaly Checks
Runs fast structural checks against the DeckDocument with NO LLM calls.
All findings are binary: FLAGGED or CLEAR.
"""
import re
from dataclasses import dataclass, field
from ingestion.models import DeckDocument
from anomaly.config_loader import DDConfig, AnomalyCheck


# ── Currency pattern for revenue detection ────────────────────────────────────
_CURRENCY = re.compile(
    r"""
    (?:
        \$\s*[\d,]+           |  # $1,000
        £\s*[\d,]+            |  # £500
        €\s*[\d,]+            |  # €200
        ₹\s*[\d,]+            |  # ₹50
        [\d,.]+\s*(?:          
            million|billion|   
            crore|lakh|        
            mn|bn|k            
        )                     |  # 5 million, 2bn
        (?:USD|GBP|EUR|INR)\s*[\d,]+  # USD 10,000
    )
    """,
    re.IGNORECASE | re.VERBOSE
)

_CUSTOMER_COUNT = re.compile(
    r"\b(\d+[\d,]*)\s*(?:\+)?\s*(?:customers?|users?|clients?|accounts?|subscribers?)\b",
    re.IGNORECASE
)


@dataclass
class AnomalyFinding:
    """Result of a single anomaly check."""
    anomaly_id: str
    label: str
    status: str                 # FLAGGED | CLEAR | UNCLEAR
    severity: str               # HIGH | MEDIUM | LOW
    evidence: str               # What triggered the flag (or what cleared it)
    slide_reference: str        # "Slide 4" | "NOT_FOUND" | "N/A"
    check_pass: int             # 1 = deterministic, 2 = LLM
    category: str
    ic_memo_flag: bool
    generates_question: bool
    generated_question: str = ""   # Populated for FLAGGED items if generates_question=True


def run_pass1(deck: DeckDocument, config: DDConfig) -> list[AnomalyFinding]:
    """
    Run all deterministic checks against the deck.

    Args:
        deck: Fully ingested and cleaned DeckDocument.
        config: Loaded DDConfig with anomaly definitions.

    Returns:
        List of AnomalyFinding objects (FLAGGED and CLEAR combined).
    """
    findings = []
    checks = config.deterministic_checks()

    for check in checks:
        finding = _run_check(check, deck)
        findings.append(finding)
        status_icon = "🚩" if finding.status == "FLAGGED" else "✅"
        print(f"[PASS1] {status_icon} {check.id}: {finding.status}")

    flagged = sum(1 for f in findings if f.status == "FLAGGED")
    print(f"[PASS1] Complete — {flagged}/{len(findings)} checks flagged")
    return findings


def _run_check(check: AnomalyCheck, deck: DeckDocument) -> AnomalyFinding:
    """Dispatch to the correct deterministic check function."""
    check_id = check.id

    # ── Missing section checks ─────────────────────────────────────────────
    section_map = {
        "MS_001": "PROBLEM",
        "MS_002": "SOLUTION",
        "MS_003": "TEAM",
        "MS_004": "FINANCIALS",
        "MS_005": "TRACTION",
        "MS_006": "MARKET",
        "MS_007": "CAP_TABLE",
        "MS_008": "COMPETITION",
    }

    if check_id in section_map:
        return _check_missing_section(check, deck, section_map[check_id])

    if check_id == "MS_009":
        return _check_deck_length(check, deck)

    if check_id == "FIN_001":
        return _check_no_revenue_numbers(check, deck)

    # Default: unknown check ID — skip gracefully
    return AnomalyFinding(
        anomaly_id=check.id,
        label=check.label,
        status="CLEAR",
        severity=check.severity,
        evidence=f"No implementation found for check {check_id}",
        slide_reference="N/A",
        check_pass=1,
        category=check.category,
        ic_memo_flag=check.ic_memo_flag,
        generates_question=check.generates_question,
    )


def _check_missing_section(check: AnomalyCheck, deck: DeckDocument, section: str) -> AnomalyFinding:
    present = deck.has_section(section)
    if present:
        slides = deck.slides_by_section(section)
        refs = ", ".join(f"Slide {s.slide_number}" for s in slides)
        return _clear(check, f"Section found at {refs}", refs)
    else:
        q = f"The deck does not contain a {section.replace('_', ' ').title()} section. Can you walk us through {_section_question(section)}?"
        return _flagged(check, f"No slide classified as {section}", "NOT_FOUND", q)


def _check_deck_length(check: AnomalyCheck, deck: DeckDocument) -> AnomalyFinding:
    count = deck.slide_count
    if count >= 8:
        return _clear(check, f"Deck has {count} slides (minimum 8)", "N/A")
    else:
        q = f"The deck has only {count} slides. Is this the complete deck?"
        return _flagged(check, f"Deck has only {count} slides (minimum 8 expected)", "N/A", q)


def _check_no_revenue_numbers(check: AnomalyCheck, deck: DeckDocument) -> AnomalyFinding:
    # Only flag if company claims to have traction/revenue
    has_traction = deck.has_section("TRACTION")
    relevant_slides = deck.slides_by_section("FINANCIALS") + deck.slides_by_section("TRACTION")

    if not relevant_slides:
        return _clear(check, "No financials/traction slides to check", "N/A")

    for slide in relevant_slides:
        text = slide.cleaned_text or slide.raw_text
        if _CURRENCY.search(text):
            return _clear(check, "Revenue/currency figures found", f"Slide {slide.slide_number}")

    if has_traction:
        q = "The deck mentions traction but no specific revenue figures are visible. Can you share your current MRR/ARR and total revenue to date?"
        return _flagged(check, "Traction claimed but no revenue figures found in financial or traction slides", "NOT_FOUND", q)
    else:
        return _clear(check, "Pre-revenue company — no revenue figures expected", "N/A")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _flagged(check: AnomalyCheck, evidence: str, slide_ref: str, question: str = "") -> AnomalyFinding:
    return AnomalyFinding(
        anomaly_id=check.id,
        label=check.label,
        status="FLAGGED",
        severity=check.severity,
        evidence=evidence,
        slide_reference=slide_ref,
        check_pass=1,
        category=check.category,
        ic_memo_flag=check.ic_memo_flag,
        generates_question=check.generates_question,
        generated_question=question if check.generates_question else "",
    )


def _clear(check: AnomalyCheck, evidence: str, slide_ref: str) -> AnomalyFinding:
    return AnomalyFinding(
        anomaly_id=check.id,
        label=check.label,
        status="CLEAR",
        severity=check.severity,
        evidence=evidence,
        slide_reference=slide_ref,
        check_pass=1,
        category=check.category,
        ic_memo_flag=check.ic_memo_flag,
        generates_question=check.generates_question,
    )


def _section_question(section: str) -> dict:
    questions = {
        "PROBLEM": "the core problem you are solving and the evidence you have for this being a real pain point",
        "SOLUTION": "your product and how it addresses the problem",
        "TEAM": "the founding team's backgrounds and relevant experience",
        "FINANCIALS": "your current financial position, burn rate, and projections",
        "TRACTION": "the traction and commercial progress you have achieved to date",
        "MARKET": "the market opportunity and how you sized it",
        "CAP_TABLE": "the current ownership structure and the terms of this round",
        "COMPETITION": "the competitive landscape and how you differentiate from alternatives",
    }
    return questions.get(section, "this area in more detail")