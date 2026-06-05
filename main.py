"""
DD System — CLI Entry Point

Usage:
    python main.py --deck path/to/deck.pdf
    python main.py --deck deck.pptx --no-llm          # deterministic only
    python main.py --deck deck.pdf --pii               # enable PII scrubbing
    python main.py --deck deck.pdf --provider ollama   # use local model
"""
import argparse
import sys
import os
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(
        description="AI-Powered Preliminary Due Diligence System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --deck pitch.pdf
  python main.py --deck pitch.pptx --provider claude
  python main.py --deck pitch.pdf --no-llm
  python main.py --deck pitch.pdf --pii --provider ollama
        """
    )

    parser.add_argument("--deck", required=True, help="Path to pitch deck (PDF, PPTX, or DOCX)")
    parser.add_argument("--config", default=None, help="Path to anomaly_config.yaml (optional)")
    parser.add_argument("--provider", default=None, choices=["claude", "openai", "ollama"],
                        help="LLM provider (overrides LLM_PROVIDER env var)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Run deterministic checks only — no LLM calls (fast mode)")
    parser.add_argument("--pii", action="store_true",
                        help="Enable PII scrubbing before LLM calls")
    parser.add_argument("--output", default=None,
                        help="Output directory for the PDF report (default: ./reports/)")

    args = parser.parse_args()

    # Validate deck file
    if not os.path.exists(args.deck):
        print(f"❌ Error: Deck file not found: {args.deck}")
        sys.exit(1)

    from pipeline import run_pipeline
    result = run_pipeline(
        file_path=args.deck,
        config_path=args.config,
        scrub_pii=args.pii,
        run_llm_pass=not args.no_llm,
        llm_provider=args.provider,
    )
 

    # Print full findings as JSON
    output = []
    for f in result.all_findings:
        output.append({
            "id": f.anomaly_id,
            "category": f.category,
            "severity": f.severity,
            "status": f.status,
            "label": f.label,
            "evidence": f.evidence,
            "slide_reference": f.slide_reference,
            "ic_memo_flag": f.ic_memo_flag,
            "generated_question": f.generated_question,
            "pass": f.check_pass,
        })

    with open("pipeline_output.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\n✅ Full JSON output saved to pipeline_output.json")
    # Save slide data as JSON
    slides_output = []
    for slide in result.deck.slides:
        slides_output.append({
            "slide_number": slide.slide_number,
            "detected_section": slide.detected_section,
            "raw_text": slide.raw_text,
            "cleaned_text": slide.cleaned_text,
            "has_charts": slide.has_charts,
            "image_count": slide.image_count,
            "tables": [
                {"headers": t.headers, "rows": t.rows}
                for t in slide.tables
            ],
        })

    with open("slides_output.json", "w", encoding="utf-8") as sf:
        json.dump(slides_output, sf, indent=2, ensure_ascii=False)

    print("✅ Slide data saved to slides_output.json")

    # Report generation (Layer 4+5) — coming in next build phase
    print("\n📋 Pipeline complete. Report generation module coming next.")
    print(f"   Flagged: {len(result.flagged())} | Unclear: {len(result.unclear())}")
    print(f"   IC Memo risks: {len(result.ic_memo_risks())}")

    if result.questions_by_category():
        print("\n📌 Investor Questions Generated:")
        for category, questions in result.questions_by_category().items():
            print(f"\n  {category}:")
            for q in questions:
                print(f"    • {q}")


if __name__ == "__main__":
    main()