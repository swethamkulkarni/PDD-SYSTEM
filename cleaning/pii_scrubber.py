"""
PII Scrubber — Layer 2: Cleaning (Optional)
Replaces personal identifiers with anonymized placeholders before LLM calls.
The original values are retained in deck.pii_map (in-memory only).

This module uses pattern matching. For better accuracy, install spaCy:
    pip install spacy && python -m spacy download en_core_web_sm
"""
import re
from ingestion.models import DeckDocument


# ── Regex patterns ────────────────────────────────────────────────────────────
_EMAIL    = re.compile(r"\b[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}\b")
_URL      = re.compile(r"https?://\S+|www\.\S+")
_PHONE    = re.compile(r"\+?\d[\d\s\-().]{7,}\d")
_LINKEDIN = re.compile(r"linkedin\.com/in/[\w\-]+", re.IGNORECASE)


def scrub_deck(deck: DeckDocument) -> DeckDocument:
    """
    Scrub PII from all slide text in a DeckDocument.
    Modifies cleaned_text (or raw_text if cleaned_text is empty) in-place.
    Stores replacement map in deck.pii_map for reference.

    Args:
        deck: DeckDocument to scrub.

    Returns:
        The same DeckDocument with PII replaced.
    """
    # Try to use spaCy for person/org name detection if available
    nlp = _load_spacy()

    email_counter    = [0]
    url_counter      = [0]
    phone_counter    = [0]
    person_counter   = [0]
    company_counter  = [0]

    def replace_email(m):
        key = m.group(0)
        if key not in deck.pii_map:
            email_counter[0] += 1
            deck.pii_map[key] = f"[EMAIL_{email_counter[0]}]"
        return deck.pii_map[key]

    def replace_url(m):
        key = m.group(0)
        if key not in deck.pii_map:
            url_counter[0] += 1
            deck.pii_map[key] = f"[URL_{url_counter[0]}]"
        return deck.pii_map[key]

    def replace_phone(m):
        key = m.group(0).strip()
        if key not in deck.pii_map:
            phone_counter[0] += 1
            deck.pii_map[key] = f"[PHONE_{phone_counter[0]}]"
        return deck.pii_map[key]

    for slide in deck.slides:
        text = slide.cleaned_text if slide.cleaned_text else slide.raw_text

        # Pattern-based replacements
        text = _EMAIL.sub(replace_email, text)
        text = _URL.sub(replace_url, text)
        text = _PHONE.sub(replace_phone, text)

        # spaCy NER for person and org names
        if nlp:
            text = _scrub_named_entities(
                text, nlp, deck.pii_map,
                person_counter, company_counter
            )

        if slide.cleaned_text:
            slide.cleaned_text = text
        else:
            slide.raw_text = text

    return deck


def _scrub_named_entities(text, nlp, pii_map, person_counter, company_counter) -> str:
    """Replace PERSON and ORG entities using spaCy NER."""
    doc = nlp(text)
    result = text

    # Process in reverse order to preserve character positions
    entities = sorted(
        [(ent.start_char, ent.end_char, ent.label_, ent.text)
         for ent in doc.ents if ent.label_ in ("PERSON", "ORG")],
        key=lambda x: x[0], reverse=True
    )

    for start, end, label, entity_text in entities:
        if entity_text not in pii_map:
            if label == "PERSON":
                person_counter[0] += 1
                pii_map[entity_text] = f"[PERSON_{person_counter[0]}]"
            else:
                company_counter[0] += 1
                pii_map[entity_text] = f"[COMPANY_{company_counter[0]}]"
        result = result[:start] + pii_map[entity_text] + result[end:]

    return result


def _load_spacy():
    """Try to load spaCy. Returns None if not installed (graceful degradation)."""
    try:
        import spacy
        return spacy.load("en_core_web_sm")
    except Exception:
        return None