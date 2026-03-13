"""
Canonical data models for the DD pipeline.
Uses dataclasses (no pydantic required) for broad compatibility.
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime
import uuid


# Valid slide section labels produced by the classifier
SECTION_LABELS = {
    "COVER", "PROBLEM", "SOLUTION", "TECHNOLOGY", "BUSINESS_MODEL",
    "TRACTION", "TEAM", "MARKET", "COMPETITION", "FINANCIALS",
    "CAP_TABLE", "UNKNOWN", "EMPTY"
}


@dataclass
class SlideTable:
    """A table extracted from a slide."""
    headers: list[str]
    rows: list[list[str]]

    def to_text(self) -> str:
        lines = []
        if self.headers:
            lines.append(" | ".join(self.headers))
            lines.append("-" * 40)
        for row in self.rows:
            lines.append(" | ".join(str(c) for c in row))
        return "\n".join(lines)


@dataclass
class Slide:
    """A single slide extracted from any input format."""
    slide_number: int
    raw_text: str = ""                 # Original text extracted from the slide
    detected_section: str = "UNKNOWN"     # Set by section_classifier.py
    cleaned_text: str = ""                # Set by noise_remover.py
    tables: list[SlideTable] = field(default_factory=list)
    has_charts: bool = False              # True if visual chart detected
    speaker_notes: str = ""              # PPTX only
    image_count: int = 0                 # Number of images on slide

    def is_empty(self) -> bool:
        return not self.raw_text.strip() and not self.tables

    def full_text(self) -> str:
        """Returns cleaned text + table text combined for LLM consumption."""
        parts = [self.cleaned_text or self.raw_text]
        for table in self.tables:
            parts.append(table.to_text())
        return "\n\n".join(p for p in parts if p.strip())


@dataclass
class DeckDocument:
    """
    The canonical representation of a pitch deck after ingestion.
    This is the contract between Layer 1 (Ingestion) and all downstream layers.
    """
    deck_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_format: str = ""              # pdf | pptx | docx
    source_filename: str = ""            # Original filename (not full path)
    ingested_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    slide_count: int = 0
    slides: list[Slide] = field(default_factory=list)
    metadata_hash: str = ""             # SHA-256 of original file (for audit log only)

    # PII scrubbing map — populated by pii_scrubber.py if enabled
    # Maps placeholder -> original value (kept in memory only, never written to disk)
    pii_map: dict = field(default_factory=dict)

    def slides_by_section(self, section: str) -> list[Slide]:
        """Return all slides classified as the given section type."""
        return [s for s in self.slides if s.detected_section == section]

    def has_section(self, section: str) -> bool:
        return any(s.detected_section == section for s in self.slides)

    def sections_present(self) -> set[str]:
        return {s.detected_section for s in self.slides}

    def text_for_sections(self, sections: list[str]) -> str:
        """
        Returns combined full text for a list of section types.
        Used to scope LLM prompts to only the relevant slides.
        """
        parts = []
        for slide in self.slides:
            if slide.detected_section in sections or "ANY" in sections:
                parts.append(f"[Slide {slide.slide_number} — {slide.detected_section}]\n{slide.full_text()}")
        return "\n\n---\n\n".join(parts)

    def summary(self) -> dict:
        """Quick summary for logging."""
        return {
            "deck_id": self.deck_id,
            "format": self.source_format,
            "file": self.source_filename,
            "slides": self.slide_count,
            "sections_found": sorted(self.sections_present()),
        }