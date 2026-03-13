"""
Noise Remover — Layer 2: Cleaning
Strips decorative and structural noise from slide text before LLM processing.
"""
import re
from collections import Counter

from ingestion.models import DeckDocument, Slide


# ── Patterns to strip ────────────────────────────────────────────────────────

# Page/slide numbers: "1", "Page 1", "Slide 3 of 10", "1 / 10"
_PAGE_NUMBER = re.compile(
    r"^\s*(?:page|slide)?\s*\d+\s*(?:of|/)\s*\d+\s*$"
    r"|^\s*\d+\s*$",
    re.IGNORECASE
)

# Copyright lines
_COPYRIGHT = re.compile(
    r"©|copyright|all rights reserved|confidential(?:\s+and\s+proprietary)?",
    re.IGNORECASE
)

# Separator lines: "----", "....", "____", "====="
_SEPARATOR = re.compile(r"^[\-\.\_\=\*]{3,}\s*$")

# Encoding artifacts: replacement chars, null bytes
_ENCODING_ARTIFACT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")

# URLs (replaced with placeholder for LLM calls)
_URL = re.compile(r"https?://\S+|www\.\S+")

# Email addresses
_EMAIL_LOOSE = re.compile(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b")


def remove_noise(deck: DeckDocument, redact_urls: bool = True) -> DeckDocument:
    """
    Clean all slides in a DeckDocument.
    Populates slide.cleaned_text for every slide.
    Original slide.raw_text is preserved unchanged.

    Args:
        deck: DeckDocument after ingestion.
        redact_urls: Replace URLs with [URL_REDACTED] (recommended before LLM calls).

    Returns:
        The same DeckDocument with cleaned_text populated on each slide.
    """
    # First pass: collect boilerplate (text on >60% of slides)
    boilerplate = _detect_boilerplate(deck)

    for slide in deck.slides:
        slide.cleaned_text = _clean_slide(
            slide.raw_text,
            boilerplate=boilerplate,
            redact_urls=redact_urls
        )

    return deck


def _clean_slide(text: str, boilerplate: set[str], redact_urls: bool) -> str:
    """Clean a single slide's text."""
    lines = text.splitlines()
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # Skip page numbers
        if _PAGE_NUMBER.match(stripped):
            continue

        # Skip copyright/confidential footers
        if _COPYRIGHT.search(stripped) and len(stripped) < 120:
            continue

        # Skip separator lines
        if _SEPARATOR.match(stripped):
            continue

        # Skip boilerplate repeated across slides
        if stripped in boilerplate:
            continue

        # Clean encoding artifacts
        stripped = _ENCODING_ARTIFACT.sub(" ", stripped)

        # Redact URLs
        if redact_urls:
            stripped = _URL.sub("[URL_REDACTED]", stripped)

        # Normalize whitespace
        stripped = re.sub(r"\s{2,}", " ", stripped).strip()

        if stripped:
            cleaned_lines.append(stripped)

    return "\n".join(cleaned_lines)


def _detect_boilerplate(deck: DeckDocument) -> set[str]:
    """
    Identify text lines that appear on more than 60% of slides.
    These are likely headers/footers/branding and add noise to LLM analysis.
    """
    if not deck.slides:
        return set()

    threshold = 0.6
    min_slides = max(3, int(len(deck.slides) * threshold))

    # Count line frequency across all slides
    line_counter: Counter = Counter()
    for slide in deck.slides:
        seen_in_slide = set()
        for line in slide.raw_text.splitlines():
            stripped = line.strip()
            if stripped and len(stripped) > 3:
                if stripped not in seen_in_slide:
                    line_counter[stripped] += 1
                    seen_in_slide.add(stripped)

    return {line for line, count in line_counter.items() if count >= min_slides}