"""
Section Classifier — Layer 2: Cleaning
Assigns each slide a section label (PROBLEM, SOLUTION, TEAM, etc.)
using keyword heuristics. No LLM required.
"""
import re
from ingestion.models import DeckDocument, Slide, SECTION_LABELS


# ── Keyword rules per section ─────────────────────────────────────────────────
# Each entry: (section_label, required_keywords, boost_keywords, weight)
# Score = matches in required + 2x matches in boost
# Highest scoring section wins. Minimum score of 2 required to classify.

CLASSIFICATION_RULES = [
    (
        "COVER",
        ["pitch", "deck", "presents", "presentation", "series", "seed", "raising"],
        ["confidential", "investment opportunity", "investor presentation"],
        1
    ),
    (
        "PROBLEM",
        ["problem", "pain", "challenge", "broken", "inefficiency", "gap", "issue", "struggle",
         "frustrated", "difficult", "costly", "slow", "manual", "outdated", "fragmented"],
        ["the problem", "pain point", "market gap", "why now", "status quo", "current state"],
        2
    ),
    (
        "SOLUTION",
        ["solution", "platform", "product", "we offer", "we provide", "we enable",
         "our approach", "how it works", "introducing", "we solve", "we help"],
        ["our solution", "our platform", "the solution", "how we solve", "our product"],
        2
    ),
    (
        "TECHNOLOGY",
        ["technology", "ai", "machine learning", "ml", "algorithm", "patent", "ip",
         "architecture", "infrastructure", "api", "stack", "model", "data", "engine",
         "proprietary", "deep learning", "neural", "nlp", "blockchain"],
        ["our technology", "how it works technically", "tech stack", "ip portfolio",
         "patent pending", "patent granted", "technical overview"],
        2
    ),
    (
        "BUSINESS_MODEL",
        ["revenue", "monetize", "monetization", "pricing", "subscription", "saas",
         "transaction fee", "commission", "license", "freemium", "upsell",
         "business model", "how we make money", "fee", "charge"],
        ["revenue model", "pricing model", "business model", "how we charge",
         "recurring revenue", "arr", "mrr"],
        2
    ),
    (
        "TRACTION",
        ["traction", "customers", "users", "clients", "revenue", "growth", "pipeline",
         "signed", "deployed", "launched", "active", "retention", "nrr", "mrr", "arr",
         "contracts", "pilots", "paying", "onboarded", "milestones"],
        ["key traction", "our traction", "what we've achieved", "customer wins",
         "commercial traction", "product traction", "early adopters"],
        2
    ),
    (
        "TEAM",
        ["team", "founder", "co-founder", "ceo", "cto", "coo", "cfo", "vp",
         "advisor", "board", "previously", "ex-", "background", "experience",
         "years at", "led", "built", "scaled"],
        ["our team", "the team", "founding team", "leadership team",
         "management team", "advisory board"],
        2
    ),
    (
        "MARKET",
        ["market", "tam", "sam", "som", "addressable", "opportunity", "segment",
         "industry", "billion", "trillion", "growing", "market size", "total addressable"],
        ["market opportunity", "market size", "total addressable market",
         "market analysis", "target market", "market overview"],
        2
    ),
    (
        "COMPETITION",
        ["competition", "competitive", "competitor", "landscape", "alternative",
         "versus", " vs ", "incumbent", "differentiat", "unique", "benchmark",
         "market map", "comparison"],
        ["competitive landscape", "why us", "our advantage", "vs competitors",
         "competitive advantage", "competitive moat", "market map"],
        2
    ),
    (
        "FINANCIALS",
        ["financial", "revenue", "ebitda", "profit", "loss", "burn", "runway",
         "forecast", "projection", "p&l", "income", "cost", "margin",
         "budget", "fiscal", "fy", "q1", "q2", "q3", "q4"],
        ["financial projections", "financial forecast", "income statement",
         "unit economics", "burn rate", "cash flow", "financial overview"],
        2
    ),
    (
        "CAP_TABLE",
        ["cap table", "capitalization", "ownership", "equity", "shareholders",
         "valuation", "pre-money", "post-money", "raising", "round", "series",
         "term sheet", "investment", "dilution", "vesting", "esop"],
        ["cap table", "funding round", "current round", "use of funds",
         "investment terms", "ownership structure", "raising $"],
        2
    ),
]


def classify_sections(deck: DeckDocument) -> DeckDocument:
    """
    Classify each slide into a section type.
    Populates slide.detected_section for every slide.

    Args:
        deck: DeckDocument after noise removal (uses cleaned_text if available,
              falls back to raw_text).

    Returns:
        The same DeckDocument with section labels applied.
    """
    for i, slide in enumerate(deck.slides):
        if slide.is_empty():
            slide.detected_section = "EMPTY"
            continue

        text = (slide.cleaned_text or slide.raw_text).lower()

        # Cover slide heuristic: first slide with very little text
        if i == 0 and len(text.strip()) < 200:
            slide.detected_section = "COVER"
            continue

        slide.detected_section = _score_and_classify(text)

    return deck


def _score_and_classify(text: str) -> str:
    """Score a slide's text against all section rules and return best match."""
    scores: dict[str, float] = {}

    for section, keywords, boost_keywords, min_score in CLASSIFICATION_RULES:
        score = 0.0

        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE):
                score += 1.0

        for kw in boost_keywords:
            if kw.lower() in text:
                score += 2.0

        if score >= min_score:
            scores[section] = score

    if not scores:
        return "UNKNOWN"

    return max(scores, key=lambda s: scores[s])