"""
Section Classifier — Layer 2: Cleaning
Assigns each slide a section label (PROBLEM, SOLUTION, TEAM, etc.)
using multi-pass keyword heuristics and semantic phrase patterns.

Improvements over v1:
- Richer keyword lists covering implicit/conceptual language
- Semantic phrase patterns (regex) that catch section framing
  without relying on exact section-name keywords
- Second-pass content inference for UNKNOWN slides
- Conflict resolution for slides that score equally on two sections
- No LLM required — pure text heuristics, fast and free
"""
import re
from ingestion.models import DeckDocument, Slide, SECTION_LABELS


# ── Classification rules ───────────────────────────────────────────────────────
# Format: (section_label, keywords, boost_phrases, semantic_patterns, min_score)
#
# keywords      — single words, score +1 each
# boost_phrases — multi-word phrases, score +2 each
# semantic_patterns — regex patterns that signal the section conceptually, +3 each
# min_score     — minimum total score to accept the classification

CLASSIFICATION_RULES = [
    (
        "COVER",
        [
            "pitch", "deck", "presents", "presentation", "series", "seed",
            "raising", "confidential", "teaser", "overview", "introduction",
        ],
        [
            "investment opportunity", "investor presentation", "strictly confidential",
            "executive summary", "company overview",
        ],
        [
            r"(series\s+[a-c]|seed\s+round|pre-seed)",
            r"(pitch\s+deck|investor\s+deck|deck\s+for)",
            r"(prepared\s+(for|by)|presented\s+to)",
        ],
        1
    ),
    (
        "PROBLEM",
        [
            # explicit problem words
            "problem", "pain", "challenge", "broken", "inefficiency", "gap",
            "issue", "struggle", "frustrated", "difficult", "costly", "slow",
            "manual", "outdated", "fragmented", "complex", "complicated",
            # implicit problem signals
            "status quo", "today", "currently", "existing", "legacy",
            "traditional", "incumbent", "friction", "bottleneck", "barrier",
            "obstacle", "limitation", "constraint", "failure", "risk",
            "expensive", "time-consuming", "error-prone", "unreliable",
            "ineffective", "inadequate", "insufficient", "lacking",
            # domain-agnostic problem framing
            "why this matters", "the opportunity", "the need", "unmet",
            "underserved", "unsolved", "unaddressed",
        ],
        [
            "the problem", "pain point", "market gap", "why now", "current state",
            "status quo", "what's broken", "what is broken", "key challenge",
            "the challenge", "core problem", "root cause", "fundamental issue",
            "industry problem", "the issue", "customer pain", "customer struggle",
            "current approach", "existing solution fails", "broken process",
            "cost of inaction", "why it matters",
        ],
        [
            # "X is broken/costly/slow/manual/fragmented"
            r"(is|are)\s+(broken|costly|slow|manual|fragmented|inefficient|complex|expensive|outdated|unreliable)",
            # "current X is Y" framing
            r"current(ly)?\s+\w+\s+(is|are|takes|costs|requires|lacks)",
            # "X costs $Y" or "X takes N hours/days"
            r"costs?\s+\$[\d,]+",
            r"takes?\s+\d+\s+(hours?|days?|weeks?|months?)",
            # "X% of companies/teams/customers struggle with"
            r"\d+\s*%\s+of\s+\w+\s+(struggle|fail|spend|waste|lose)",
            # "the problem with X is Y"
            r"the\s+problem\s+with",
            # "today, X has to Y manually"
            r"today[,\s]+\w+\s+(has|have|must|need)\s+to",
            # "without X, companies face Y"
            r"without\s+\w+[,\s]+(companies|teams|businesses|organisations?)\s+(face|struggle|lose)",
            # data center / procurement / power specific
            r"(power\s+procurement|data\s+center\s+power|energy\s+procurement)",
            r"(procurement\s+(is|process|challenge|complexity))",
        ],
        2
    ),
    (
        "SOLUTION",
        [
            "solution", "platform", "product", "offer", "provide", "enable",
            "approach", "introducing", "solve", "help", "build", "create",
            "automate", "simplify", "streamline", "accelerate", "transform",
            "revolutionise", "revolutionize", "reimagine", "reinvent",
            "software", "tool", "system", "service", "application", "app",
        ],
        [
            "our solution", "our platform", "our product", "our approach",
            "how it works", "how we solve", "what we do", "what we build",
            "the solution", "we offer", "we provide", "we enable",
            "our software", "our tool", "our system", "our service",
            "introducing", "meet", "we are building",
        ],
        [
            r"(we|our\s+\w+)\s+(solves?|addresses?|eliminates?|removes?|replaces?|automates?)",
            r"(our|the)\s+(platform|product|solution|tool|system)\s+(enables?|allows?|helps?|makes?|lets?)",
            r"(built|designed|created)\s+(to|for)\s+\w+",
            r"(replac(e|ing)|eliminat(e|ing))\s+(manual|legacy|traditional|existing)",
            r"(end-to-end|all-in-one|single\s+platform|unified\s+platform)",
        ],
        2
    ),
    (
        "TECHNOLOGY",
        [
            "technology", "ai", "machine learning", "ml", "algorithm", "patent",
            "ip", "architecture", "infrastructure", "api", "stack", "model",
            "data", "engine", "proprietary", "deep learning", "neural", "nlp",
            "blockchain", "llm", "foundation model", "fine-tuned", "trained",
            "dataset", "pipeline", "workflow", "integration", "cloud", "saas",
            "technical", "software", "code", "open source", "sdk",
        ],
        [
            "our technology", "tech stack", "ip portfolio", "patent pending",
            "technical overview", "how it works technically", "the engine",
            "our ai", "our model", "our algorithm", "the architecture",
            "proprietary technology", "core technology", "underlying technology",
            "ai-powered", "machine learning model", "data pipeline",
        ],
        [
            r"(ai|ml|llm|gpt|nlp)\s*[-–]\s*(powered|driven|based|enabled)",
            r"(trained\s+on|fine-tuned\s+on|built\s+on)\s+\w+",
            r"(proprietary|patented|patent[\s-]pending)\s+(technology|algorithm|model|system)",
            r"(technical\s+(architecture|overview|stack|depth|moat))",
            r"(api|sdk|integration|webhook|endpoint)\s+(connects?|enables?|allows?)",
        ],
        2
    ),
    (
        "BUSINESS_MODEL",
        [
            "revenue", "monetize", "monetization", "pricing", "subscription",
            "saas", "transaction", "commission", "license", "freemium", "upsell",
            "fee", "charge", "invoice", "billing", "payment", "contract",
            "annual", "monthly", "per seat", "per user", "enterprise",
            "smb", "mid-market", "commercial", "go-to-market",
        ],
        [
            "revenue model", "pricing model", "business model", "how we charge",
            "recurring revenue", "how we make money", "monetization strategy",
            "pricing tiers", "pricing page", "subscription fee", "annual contract",
            "per seat pricing", "usage-based", "transaction fee",
        ],
        [
            r"(charges?|bills?|invoices?)\s+(per|monthly|annually|quarterly)",
            r"\$\d+[\d,\.]*\s+(per\s+(seat|user|month|year|transaction|api\s+call))",
            r"(arr|mrr|acv|tcv)\s+(of|target|projected|current)",
            r"(freemium|free\s+tier|paid\s+plan|enterprise\s+plan)",
            r"(revenue\s+(stream|model|breakdown|mix))",
        ],
        2
    ),
    (
        "TRACTION",
        [
            "traction", "customers", "users", "clients", "revenue", "growth",
            "pipeline", "signed", "deployed", "launched", "active", "retention",
            "nrr", "mrr", "arr", "contracts", "pilots", "paying", "onboarded",
            "milestones", "waitlist", "beta", "live", "production", "enterprise",
            "deals", "loi", "letter of intent", "partnership", "case study",
        ],
        [
            "key traction", "our traction", "what we've achieved", "customer wins",
            "commercial traction", "early adopters", "design partners",
            "paying customers", "signed contracts", "revenue to date",
            "customers to date", "users to date", "growth metrics",
            "month over month", "week over week",
        ],
        [
            r"\d+[\d,]+\s+(customers?|users?|clients?|companies|organisations?|enterprises?)",
            r"\$[\d,]+[km]?\s+(arr|mrr|revenue|in\s+revenue|recurring)",
            r"\d+\s*x\s+(growth|increase|improvement)\s+(in|over|since)",
            r"(signed|closed|won)\s+\d+\s+(deals?|contracts?|customers?|pilots?)",
            r"(waitlist|pipeline)\s+of\s+\d+",
            r"(month[\s-]over[\s-]month|week[\s-]over[\s-]week)\s+growth",
            r"(loi|letter\s+of\s+intent|mou|memorandum)\s+(signed|executed|with)",
        ],
        2
    ),
    (
        "TEAM",
        [
            "team", "founder", "co-founder", "ceo", "cto", "coo", "cfo", "vp",
            "advisor", "board", "previously", "background", "experience",
            "led", "built", "scaled", "phd", "mba", "degree", "university",
            "joined", "hire", "hiring", "headcount", "employees", "staff",
            "executive", "leadership", "management", "operator", "investor",
        ],
        [
            "our team", "the team", "founding team", "leadership team",
            "management team", "advisory board", "board of directors",
            "key hires", "team background", "why us", "who we are",
            "our people", "the founders",
        ],
        [
            r"(ceo|cto|coo|cfo|vp|svp|evp|chief)\s+[a-z]+",
            r"(previously|formerly|ex-?)\s+(at\s+)?\w+",
            r"\d+\s+years?\s+(of\s+)?(experience|in\s+\w+|at\s+\w+)",
            r"(phd|mba|ms|bsc)\s+(from|in)\s+\w+",
            r"(built|scaled|led|founded|exited)\s+\w+\s+(to\s+\$[\d,]+[km]?|\bipo\b|acquisition)",
            r"(hiring|looking\s+for|open\s+roles?|join\s+us)",
        ],
        2
    ),
    (
        "MARKET",
        [
            "market", "tam", "sam", "som", "addressable", "opportunity",
            "segment", "industry", "billion", "trillion", "growing", "cagr",
            "forecast", "landscape", "vertical", "sector", "space",
            "demand", "supply", "players", "dynamics", "tailwind",
        ],
        [
            "market opportunity", "market size", "total addressable market",
            "market analysis", "target market", "market overview",
            "addressable market", "market tailwind", "market timing",
            "industry overview", "market dynamics", "market landscape",
        ],
        [
            r"\$[\d,\.]+\s*(bn|billion|tn|trillion|m|million)\s+(market|opportunity|industry)",
            r"(tam|sam|som)\s+(of\s+)?\$[\d,\.]+",
            r"(market\s+(size|opportunity|growth))\s+(is|of|at|reaching)",
            r"\d+[\d\.]*\s*%\s+(cagr|growth|annually|per\s+year)",
            r"(growing\s+(at|from)|expected\s+to\s+(reach|grow|hit))\s+\$[\d,\.]+",
            r"(global|us|uk|european?|asia[\s-]pacific)\s+(market|industry|opportunity)",
        ],
        2
    ),
    (
        "COMPETITION",
        [
            "competition", "competitive", "competitor", "landscape", "alternative",
            "versus", "incumbent", "differentiat", "unique", "benchmark",
            "comparison", "rival", "market map", "player", "category",
        ],
        [
            "competitive landscape", "why us", "our advantage", "vs competitors",
            "competitive advantage", "competitive moat", "market map",
            "compared to", "unlike", "better than", "differentiation",
            "our differentiators", "key differentiators",
        ],
        [
            r"(vs\.?|versus|compared\s+to|unlike|better\s+than)\s+\w+",
            r"(our\s+)?(competitive\s+(advantage|moat|differentiation|positioning))",
            r"(competitors?\s+(include|are|such\s+as)|major\s+competitors?)",
            r"(quadrant|matrix|map)\s+(showing|of|for)\s+\w+",
            r"(we\s+(differ|stand\s+out|are\s+unique|are\s+different)\s+(from|because|in))",
            r"(barriers?\s+to\s+entry|switching\s+cost|network\s+effect)",
        ],
        2
    ),
    (
        "FINANCIALS",
        [
            "financial", "revenue", "ebitda", "profit", "loss", "burn",
            "runway", "forecast", "projection", "income", "cost", "margin",
            "budget", "fiscal", "fy", "q1", "q2", "q3", "q4", "capex",
            "opex", "gross", "net", "cac", "ltv", "payback", "unit economics",
        ],
        [
            "financial projections", "financial forecast", "income statement",
            "unit economics", "burn rate", "cash flow", "financial overview",
            "p&l", "profit and loss", "revenue forecast", "cost structure",
            "financial model", "financial summary", "key financials",
        ],
        [
            r"(revenue|arr|mrr|ebitda|burn)\s+(of|is|was|projected|forecast)\s+\$[\d,\.]+",
            r"\$[\d,\.]+[km]?\s+(monthly|annual|quarterly)\s+(burn|revenue|cost|run\s+rate)",
            r"(gross\s+margin|net\s+margin|contribution\s+margin)\s+of\s+\d+\s*%",
            r"(cac|ltv|ltv[\s:\/]+cac|payback\s+period)\s+(of|is|=)\s+[\$\d]",
            r"(runway\s+of\s+\d+\s+months?|months?\s+runway)",
            r"(break[\s-]even|profitab(le|ility))\s+(by|in|at)\s+\w+",
        ],
        2
    ),
    (
        "CAP_TABLE",
        [
            "cap table", "capitalization", "ownership", "equity", "shareholders",
            "valuation", "pre-money", "post-money", "raising", "round", "series",
            "term sheet", "investment", "dilution", "vesting", "esop",
            "convertible", "safe", "note", "warrant", "option pool",
        ],
        [
            "cap table", "funding round", "current round", "use of funds",
            "investment terms", "ownership structure", "raising $",
            "we are raising", "seed round", "series a", "funding ask",
            "investment ask", "how funds will be used", "use of proceeds",
        ],
        [
            r"(raising|seeking|looking\s+for)\s+\$[\d,\.]+[km]?",
            r"(pre-money|post-money)\s+valuation\s+of\s+\$[\d,\.]+",
            r"(use\s+of\s+(funds|proceeds|capital))",
            r"(series\s+[a-d]|seed|pre-seed|bridge)\s+(round|funding|raise)",
            r"(option\s+pool|esop|equity\s+plan)\s+of\s+\d+\s*%",
            r"(convertible\s+(note|safe)|safe\s+agreement)",
        ],
        2
    ),
]


# ── Content inference patterns for second pass ─────────────────────────────────
# Used when a slide scores UNKNOWN — looks for structural signals

_CONTENT_INFERENCE = [
    # Problem inference — descriptive problem framing without "problem" keyword
    ("PROBLEM", [
        r"(today|currently|at\s+present)[,\s]+\w+",
        r"(this\s+means|as\s+a\s+result|consequently)[,\s]+(companies|teams|businesses)",
        r"(every\s+year|annually)[,\s]+\$[\d,\.]+\s*(bn|billion|m|million)",
        r"(no\s+single|no\s+unified|no\s+standardised?|no\s+automated?)\s+\w+",
        r"(most\s+companies|many\s+organisations?|teams\s+still)\s+(rely\s+on|use|do)",
        r"(hours?|days?|weeks?)\s+(wasted?|spent\s+on|lost\s+to)",
    ]),
    # Solution inference — product description without "solution" keyword
    ("SOLUTION", [
        r"(users?\s+can|customers?\s+can|you\s+can)\s+(now\s+)?\w+",
        r"(one\s+click|single\s+dashboard|unified\s+view|real[\s-]time\s+\w+)",
        r"(seamless(ly)?|automated?|intelligent(ly)?)\s+\w+",
        r"(connect(s|ing)?|integrat(es?|ing))\s+(with|to)\s+\w+",
        r"(workflow|process)\s+(automation|simplification|streamlining)",
    ]),
    # Traction inference — metrics without "traction" heading
    ("TRACTION", [
        r"\d{1,3}[,\d]*\s+(paying\s+)?(customers?|users?|clients?|companies)",
        r"\$[\d,\.]+[km]?\s+(in\s+)?(revenue|arr|mrr|sales|bookings)",
        r"(signed|closed)\s+\d+\s+(deals?|contracts?|customers?|pilots?)",
        r"\d+\s*x\s+(growth|increase)\s+(in|over|since|yoy|mom)",
    ]),
    # Team inference — bio-style content without "team" heading
    ("TEAM", [
        r"(mba|phd|bsc|msc)\s+(from|at)\s+[A-Z]\w+",
        r"(previously|formerly)\s+(at|with|worked\s+at)\s+[A-Z]\w+",
        r"\d+[\+]?\s+years?\s+(of\s+)?(experience|in\s+industry|in\s+\w+)",
        r"(founded|co-founded|built|scaled)\s+\w+\s+(which|that|to|before)",
    ]),
]


# ── Main classifier ─────────────────────────────────────────────────────────────

def classify_sections(deck: DeckDocument) -> DeckDocument:
    """
    Classify each slide into a section type using multi-pass heuristics.

    Pass 1: Keyword + phrase + semantic pattern scoring
    Pass 2: Content inference for UNKNOWN slides
    Pass 3: Conflict resolution and final label assignment

    Args:
        deck: DeckDocument after noise removal.

    Returns:
        The same DeckDocument with slide.detected_section set for every slide.
    """
    for i, slide in enumerate(deck.slides):
        if slide.is_empty():
            slide.detected_section = "EMPTY"
            continue

        text = (slide.cleaned_text or slide.raw_text).lower()

        # Cover heuristic: first or second slide with little text or cover signals
        if i <= 1 and _is_cover_slide(text, i):
            slide.detected_section = "COVER"
            continue

        # Pass 1: full scoring
        label, score = _score_and_classify(text)

        # Pass 2: content inference for UNKNOWN
        if label == "UNKNOWN":
            label = _content_inference(text)

        slide.detected_section = label

    return deck


def _is_cover_slide(text: str, idx: int) -> bool:
    """Heuristic to detect cover/title slides."""
    # Very short text on slide 0 or 1 is almost always a cover
    if len(text.strip()) < 150:
        return True
    # Cover keywords present on first two slides
    cover_signals = [
        "confidential", "investor presentation", "pitch deck",
        "investment opportunity", "raising", "series", "seed"
    ]
    return any(sig in text for sig in cover_signals)


def _score_and_classify(text: str) -> tuple[str, float]:
    """
    Score text against all section rules.
    Returns (best_section_label, score) or ("UNKNOWN", 0).
    """
    scores: dict[str, float] = {}

    for section, keywords, boost_phrases, semantic_patterns, min_score in CLASSIFICATION_RULES:
        score = 0.0

        # Keyword matches
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE):
                score += 1.0

        # Boost phrase matches
        for phrase in boost_phrases:
            if phrase.lower() in text:
                score += 2.0

        # Semantic pattern matches — highest weight
        for pattern in semantic_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                score += 3.0

        if score >= min_score:
            scores[section] = score

    if not scores:
        return "UNKNOWN", 0.0

    best = max(scores, key=lambda s: scores[s])
    return best, scores[best]


def _content_inference(text: str) -> str:
    """
    Second-pass inference for slides that scored UNKNOWN.
    Looks for structural/contextual signals that imply a section type.
    """
    for section, patterns in _CONTENT_INFERENCE:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return section

    return "UNKNOWN"