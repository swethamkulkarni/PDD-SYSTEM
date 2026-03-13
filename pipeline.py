"""
Pipeline Orchestrator
Chains all 5 layers in sequence for a single pitch deck.

Usage:
    from pipeline import run_pipeline
    result = run_pipeline("deck.pdf")
"""
import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

from ingestion.ingestor import ingest
from ingestion.models import DeckDocument
from cleaning.noise_remover import remove_noise
from cleaning.section_classifier import classify_sections
from anomaly.config_loader import load_config, DDConfig
from anomaly.pass1_deterministic import run_pass1, AnomalyFinding
from anomaly.pass2_llm import run_pass2


@dataclass
class PipelineResult:
    """Complete output from the pipeline — input to report generator."""
    deck: DeckDocument
    config: DDConfig
    all_findings: list[AnomalyFinding]

    def flagged(self) -> list[AnomalyFinding]:
        return [f for f in self.all_findings if f.status == "FLAGGED"]

    def unclear(self) -> list[AnomalyFinding]:
        return [f for f in self.all_findings if f.status == "UNCLEAR"]

    def ic_memo_risks(self) -> list[AnomalyFinding]:
        return [f for f in self.flagged() if f.ic_memo_flag and f.severity == "HIGH"]

    def questions_by_category(self) -> dict[str, list[str]]:
        """Returns investor questions grouped by category for Comments & Observations."""
        grouped: dict[str, list[str]] = {}
        for f in self.all_findings:
            if f.status in ("FLAGGED", "UNCLEAR") and f.generated_question:
                cat = _category_label(f.category)
                grouped.setdefault(cat, []).append(f.generated_question)
        return grouped

    def print_summary(self):
        flagged = self.flagged()
        unclear = self.unclear()
        print("\n" + "="*60)
        print(f"PIPELINE SUMMARY — {self.deck.source_filename}")
        print("="*60)
        print(f"  Slides:          {self.deck.slide_count}")
        print(f"  Sections found:  {sorted(self.deck.sections_present())}")
        print(f"  Total checks:    {len(self.all_findings)}")
        print(f"  Flagged:         {len(flagged)}")
        print(f"  Unclear:         {len(unclear)}")
        print(f"  IC Memo risks:   {len(self.ic_memo_risks())}")
        if flagged:
            print("\n  🚩 FLAGGED ITEMS:")
            for f in flagged:
                print(f"     [{f.severity}] {f.anomaly_id}: {f.label}")
        print("="*60 + "\n")


def run_pipeline(
    file_path: str,
    config_path: Optional[str] = None,
    scrub_pii: bool = False,
    run_llm_pass: bool = True,
    llm_provider: Optional[str] = None,
) -> PipelineResult:
    """
    Run the full DD analysis pipeline on a pitch deck.

    Args:
        file_path:    Path to pitch deck (PDF, PPTX, or DOCX).
        config_path:  Path to anomaly_config.yaml. Defaults to config/anomaly_config.yaml.
        scrub_pii:    Replace names/emails/URLs before LLM calls.
        run_llm_pass: Set False to run deterministic checks only (faster, no API cost).
        llm_provider: "claude" | "openai" | "ollama". Overrides LLM_PROVIDER env var.

    Returns:
        PipelineResult with all findings ready for report generation.
    """
    print(f"\n{'='*60}")
    print(f"DD PIPELINE — {Path(file_path).name}")
    print(f"{'='*60}")

    # ── Layer 1: Ingest ───────────────────────────────────────────────────────
    print("\n[1/5] Ingesting deck...")
    deck = ingest(file_path, scrub_pii=False)  # PII scrubbing done after cleaning

    # ── Layer 2a: Clean ───────────────────────────────────────────────────────
    print("[2/5] Cleaning & normalizing...")
    deck = remove_noise(deck, redact_urls=True)

    # ── Layer 2b: Classify sections ───────────────────────────────────────────
    print("[2/5] Classifying sections...")
    deck = classify_sections(deck)
    print(f"       Sections detected: {sorted(deck.sections_present())}")

    # ── Optional PII scrubbing ────────────────────────────────────────────────
    if scrub_pii:
        print("[2/5] Scrubbing PII...")
        from cleaning.pii_scrubber import scrub_deck
        scrub_deck(deck)
        print(f"       Replaced {len(deck.pii_map)} PII entities")

    # ── Load config ───────────────────────────────────────────────────────────
    print("[3/5] Loading anomaly config...")
    config = load_config(config_path)

    # ── Layer 3a: Pass 1 — Deterministic ─────────────────────────────────────
    print("[3/5] Running Pass 1 (deterministic)...")
    pass1_findings = run_pass1(deck, config)

    # ── Layer 3b: Pass 2 — LLM ───────────────────────────────────────────────
    pass2_findings = []
    if run_llm_pass:
        print("[3/5] Running Pass 2 (LLM)...")
        from llm.adapter import get_llm
        llm = get_llm(llm_provider)
        pass2_findings = run_pass2(deck, config, llm, pass1_findings)
    else:
        print("[3/5] Pass 2 skipped (run_llm_pass=False)")

    all_findings = pass1_findings + pass2_findings

    result = PipelineResult(
        deck=deck,
        config=config,
        all_findings=all_findings,
    )
    result.print_summary()
    return result


def _category_label(code: str) -> str:
    labels = {
        "MS":    "Missing Sections",
        "MKT":   "Market & Problem Validation",
        "TECH":  "Technology",
        "FIN":   "Financials & Commercials",
        "GTM":   "GTM Strategy",
        "COMP":  "Competition",
        "TEAM":  "Team",
        "LEGAL": "Regulations & Legal",
        "IC":    "Other",
    }
    return labels.get(code.upper(), "Other")