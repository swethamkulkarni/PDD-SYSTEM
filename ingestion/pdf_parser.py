"""
PDF Parser — Layer 1: Ingestion
Extracts text and tables from PDF pitch decks using pdfplumber.

Optional enhancement (when network available):
  pip install pymupdf
  Uncomment the fitz import below for better layout-aware extraction.
"""
import hashlib
import os
from pathlib import Path

import pdfplumber

from ingestion.models import DeckDocument, Slide, SlideTable

# Optional: better extraction with PyMuPDF
# import fitz  # pip install pymupdf


def parse_pdf(file_path: str, scrub_pii: bool = False) -> DeckDocument:
    """
    Parse a PDF pitch deck into a DeckDocument.

    Args:
        file_path: Absolute path to the PDF file.
        scrub_pii: If True, run PII scrubber after parsing (requires cleaning/pii_scrubber.py).

    Returns:
        DeckDocument with raw slides populated.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected .pdf file, got: {path.suffix}")

    # Hash the file for audit log BEFORE reading content
    file_hash = _hash_file(file_path)

    doc = DeckDocument(
        source_format="pdf",
        source_filename=path.name,   # filename only, no directory path
        metadata_hash=file_hash,
    )

    with pdfplumber.open(file_path) as pdf:
        doc.slide_count = len(pdf.pages)

        for page_num, page in enumerate(pdf.pages, start=1):
            slide = Slide(slide_number=page_num)

            # ── Extract text ──────────────────────────────────────────────
            raw_text = page.extract_text() or ""
            slide.raw_text = raw_text.strip()

            # ── Extract tables ────────────────────────────────────────────
            tables = page.extract_tables() or []
            for table_data in tables:
                if not table_data:
                    continue
                # First row treated as headers if it looks like one
                cleaned_rows = [
                    [str(cell).strip() if cell else "" for cell in row]
                    for row in table_data
                    if any(cell for cell in row)
                ]
                if len(cleaned_rows) >= 2:
                    slide.tables.append(SlideTable(
                        headers=cleaned_rows[0],
                        rows=cleaned_rows[1:]
                    ))
                elif len(cleaned_rows) == 1:
                    slide.tables.append(SlideTable(
                        headers=[],
                        rows=cleaned_rows
                    ))

            # ── Chart detection (heuristic) ───────────────────────────────
            # If there are images on the page but very little text, likely a chart slide
            try:
                image_count = len(page.images or [])
                slide.image_count = image_count
                if image_count > 0 and len(raw_text.strip()) < 100:
                    slide.has_charts = True
            except Exception:
                pass

            doc.slides.append(slide)

    # Apply PII scrubbing if requested
    if scrub_pii:
        from cleaning.pii_scrubber import scrub_deck
        scrub_deck(doc)

    return doc


def _hash_file(file_path: str) -> str:
    """SHA-256 hash of file contents for audit log only."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()