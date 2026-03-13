"""
Ingestion Router — Layer 1 entry point.
Detects file format and routes to the correct parser.

Usage:
    from ingestion.ingestor import ingest
    deck = ingest("path/to/deck.pdf")
    deck = ingest("path/to/deck.pptx", scrub_pii=True)
"""
from pathlib import Path

from ingestion.models import DeckDocument


SUPPORTED_FORMATS = {
    ".pdf":  "pdf",
    ".pptx": "pptx",
    ".ppt":  "pptx",
    ".docx": "docx",
    ".doc":  "docx",
}


def ingest(file_path: str, scrub_pii: bool = False) -> DeckDocument:
    """
    Ingest a pitch deck of any supported format.

    The original file is read ONCE into the DeckDocument structure.
    After this call, the file is no longer needed — the pipeline
    operates entirely on the DeckDocument object.

    Args:
        file_path: Path to the pitch deck (PDF, PPTX, or DOCX).
        scrub_pii: Replace names, emails, URLs with placeholders before
                   any LLM calls. Recommended for sensitive decks.

    Returns:
        DeckDocument — canonical representation of the deck.

    Raises:
        ValueError: If format is unsupported.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{ext}'. "
            f"Supported: {', '.join(SUPPORTED_FORMATS.keys())}"
        )

    fmt = SUPPORTED_FORMATS[ext]

    if fmt == "pdf":
        from ingestion.pdf_parser import parse_pdf
        deck = parse_pdf(file_path, scrub_pii=scrub_pii)

    elif fmt == "pptx":
        from ingestion.pptx_parser import parse_pptx
        deck = parse_pptx(file_path, scrub_pii=scrub_pii)

    elif fmt == "docx":
        from ingestion.docx_parser import parse_docx
        deck = parse_docx(file_path, scrub_pii=scrub_pii)

    print(f"[INGEST] ✅ {deck.source_filename} | {deck.slide_count} slides | ID: {deck.deck_id[:8]}")
    return deck