"""
Pass 2 — LLM Anomaly Checks
Runs judgment-based checks using the LLM against the CEO's anomaly config.
Each check is an isolated prompt with structured JSON output.
Hallucination is mitigated by: citation enforcement, confidence thresholding,
YES/NO/UNCLEAR constraint, and section-scoped prompts.
"""
import json
from ingestion.models import DeckDocument
from anomaly.config_loader import DDConfig, AnomalyCheck
from anomaly.pass1_deterministic import AnomalyFinding
from llm.adapter import BaseLLMAdapter


# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a due diligence analyst reviewing a startup pitch deck.
You will be given the text content of specific slides and a single yes/no question.

STRICT RULES:
- Answer ONLY based on the provided slide content. Do not use outside knowledge.
- Do NOT infer, assume, or extrapolate beyond what is explicitly stated in the slides.
- If the information is ambiguous or partially present, answer UNCLEAR.
- Your evidence MUST be a verbatim phrase from the slide text, or the string NOT_FOUND.

Respond ONLY with a valid JSON object in this exact format (no other text):
{
  "answer": "YES or NO or UNCLEAR",
  "confidence": 0.0,
  "evidence": "exact phrase from slide text, or NOT_FOUND",
  "slide_reference": "Slide N or NOT_FOUND"
}"""

USER_PROMPT_TEMPLATE = """SLIDE CONTENT:
{slide_text}

QUESTION:
{probe_question}

Remember: respond ONLY with the JSON object. No explanation, no preamble."""

CONFIDENCE_THRESHOLD = 0.6   # Below this → treated as UNCLEAR


def run_pass2(
    deck: DeckDocument,
    config: DDConfig,
    llm: BaseLLMAdapter,
    pass1_findings: list[AnomalyFinding],
) -> list[AnomalyFinding]:
    """
    Run all LLM-based anomaly checks in parallel using a thread pool.
    Skips sections already confirmed missing by Pass 1.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    checks = config.llm_checks()

    # Build set of sections confirmed MISSING by Pass 1
    missing_sections = {
        f.evidence.replace("No slide classified as ", "")
        for f in pass1_findings
        if f.status == "FLAGGED" and f.anomaly_id.startswith("MS_")
    }

    # Pre-filter — separate skippable from runnable before hitting the thread pool
    to_skip = []
    to_run  = []

    for check in checks:
        if _all_sections_missing(check, missing_sections):
            to_skip.append((check, "Target sections confirmed missing by Pass 1"))
            continue
        slide_text = deck.text_for_sections(check.target_sections)
        if not slide_text.strip():
            to_skip.append((check, "No relevant slide content found"))
            continue
        to_run.append((check, slide_text))

    # Build results map — keyed by check ID to reconstruct original order later
    findings_map = {}

    for check, reason in to_skip:
        findings_map[check.id] = _skipped(check, reason)

    # Run LLM checks concurrently — 5 workers is safe for Haiku rate limits
    MAX_WORKERS = 5

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_check = {
            executor.submit(_run_llm_check, check, slide_text, llm): check
            for check, slide_text in to_run
        }

        for future in as_completed(future_to_check):
            check = future_to_check[future]
            try:
                finding = future.result()
            except Exception as e:
                finding = _unclear(check, f"Thread error: {str(e)[:80]}", "NOT_FOUND")

            findings_map[check.id] = finding

            # Print progress as each check completes
            status_icon = {"FLAGGED": "🚩", "CLEAR": "✅", "UNCLEAR": "⚠️"}.get(finding.status, "?")
            ev = finding.evidence or ""
            print(
                f"[PASS2] {status_icon} {check.id}: {finding.status} (confidence: {ev[:60]}...)"
                if len(ev) > 60
                else f"[PASS2] {status_icon} {check.id}: {finding.status}"
            )

    # Reconstruct in original config order — important for consistent report output
    findings = [findings_map[check.id] for check in checks]

    flagged = sum(1 for f in findings if f.status == "FLAGGED")
    unclear = sum(1 for f in findings if f.status == "UNCLEAR")
    print(f"[PASS2] Complete — {flagged} flagged, {unclear} unclear, out of {len(findings)} checks")

    return findings


def _run_llm_check(check: AnomalyCheck, slide_text: str, llm: BaseLLMAdapter) -> AnomalyFinding:
    """Run a single LLM check with full error handling."""
    user_prompt = USER_PROMPT_TEMPLATE.format(
        slide_text=slide_text[:6000],  # Token budget guard
        probe_question=check.probe_question
    )

    for attempt in range(2):  # retry once on bad JSON
        try:
            result = llm.complete_json(SYSTEM_PROMPT, user_prompt, temperature=0.0)
            return _parse_llm_result(check, result)
        except json.JSONDecodeError:
            if attempt == 1:
                return _unclear(check, "LLM returned non-JSON after retry", "NOT_FOUND")
            continue
        except Exception as e:
            err = str(e).lower()
            if "rate" in err or "429" in err or "limit" in err:
                import time
                time.sleep(5)
                try:
                    result = llm.complete_json(SYSTEM_PROMPT, user_prompt, temperature=0.0)
                    return _parse_llm_result(check, result)
                except Exception:
                    pass
            return _unclear(check, f"LLM call failed: {str(e)[:100]}", "NOT_FOUND")

def _parse_llm_result(check: AnomalyCheck, result: dict) -> AnomalyFinding:
    """Parse and validate the LLM's JSON response into an AnomalyFinding."""
    answer     = str(result.get("answer", "UNCLEAR")).upper()
    confidence = float(result.get("confidence", 0.0))
    evidence   = str(result.get("evidence", "NOT_FOUND"))
    slide_ref  = str(result.get("slide_reference", "NOT_FOUND"))

    # Confidence below threshold → UNCLEAR
    if confidence < CONFIDENCE_THRESHOLD and answer != "UNCLEAR":
        answer = "UNCLEAR"
        evidence = f"[Low confidence: {confidence:.2f}] " + evidence

    # For anomaly checks: NO answer means the red flag is present → FLAGGED
    # YES answer means the deck addresses the concern → CLEAR
    if answer == "NO":
        q = _generate_question(check, evidence, slide_ref)
        return AnomalyFinding(
            anomaly_id=check.id,
            label=check.label,
            status="FLAGGED",
            severity=check.severity,
            evidence=evidence,
            slide_reference=slide_ref,
            check_pass=2,
            category=check.category,
            ic_memo_flag=check.ic_memo_flag,
            generates_question=check.generates_question,
            generated_question=q if check.generates_question else "",
        )

    elif answer == "YES":
        return AnomalyFinding(
            anomaly_id=check.id,
            label=check.label,
            status="CLEAR",
            severity=check.severity,
            evidence=evidence,
            slide_reference=slide_ref,
            check_pass=2,
            category=check.category,
            ic_memo_flag=check.ic_memo_flag,
            generates_question=check.generates_question,
        )

    else:  # UNCLEAR
        q = _generate_question(check, evidence, slide_ref)
        return AnomalyFinding(
            anomaly_id=check.id,
            label=check.label,
            status="UNCLEAR",
            severity=check.severity,
            evidence=evidence,
            slide_reference=slide_ref,
            check_pass=2,
            category=check.category,
            ic_memo_flag=check.ic_memo_flag,
            generates_question=check.generates_question,
            generated_question=q if check.generates_question else "",
        )


def _generate_question(check: AnomalyCheck, evidence: str, slide_ref: str) -> str:
    """Generate a clean investor question from a flagged/unclear finding."""
    return check.logic.strip() if check.logic.strip() else check.probe_question.strip()


def _skipped(check: AnomalyCheck, reason: str) -> AnomalyFinding:
    return AnomalyFinding(
        anomaly_id=check.id,
        label=check.label,
        status="CLEAR",
        severity=check.severity,
        evidence=f"SKIPPED: {reason}",
        slide_reference="N/A",
        check_pass=2,
        category=check.category,
        ic_memo_flag=check.ic_memo_flag,
        generates_question=check.generates_question,
    )


def _unclear(check: AnomalyCheck, evidence: str, slide_ref: str) -> AnomalyFinding:
    return AnomalyFinding(
        anomaly_id=check.id,
        label=check.label,
        status="UNCLEAR",
        severity=check.severity,
        evidence=evidence,
        slide_reference=slide_ref,
        check_pass=2,
        category=check.category,
        ic_memo_flag=check.ic_memo_flag,
        generates_question=check.generates_question,
        generated_question=_generate_question(check, evidence, slide_ref) if check.generates_question else "",
    )


def _all_sections_missing(check: AnomalyCheck, missing_sections: set) -> bool:
    """True if all of the check's target sections are confirmed missing."""
    if "ANY" in check.target_sections:
        return False
    return all(s in missing_sections for s in check.target_sections)