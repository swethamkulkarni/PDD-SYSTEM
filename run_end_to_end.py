import os
from pathlib import Path

from pipeline import run_pipeline
from report_1.report_generator import generate_reports


def run_end_to_end(deck_path: str):
    
    deck_path = Path(deck_path).resolve()

    if not deck_path.exists():
        raise FileNotFoundError(f"Deck not found: {deck_path}")

    print(f"\n🚀 Running end-to-end pipeline for: {deck_path.name}")

    # Step 1 — Run Layers 1–3
    result = run_pipeline(
        file_path=str(deck_path),
        run_llm_pass=False  
    )

    # Step 2 — Run Layers 4–5
    paths = generate_reports(result, output_dir="reports/")

    print("\n✅ Reports generated:")
    print(f"Framework A: {paths['framework_a_path']}")
    print(f"Framework B: {paths['framework_b_path']}")

    return paths


if __name__ == "__main__":
    
    TEST_DECK = "C:/Users/nelld/StartUpScale360/PDD-SYSTEM/deck.pdf"

    run_end_to_end(TEST_DECK)