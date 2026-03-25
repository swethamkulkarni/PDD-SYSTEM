"""
report_generator.py
Layer 4 & 5 of the AI Due Diligence Pipeline — orchestrator.

Imports Framework A and Framework B builders and writes both Word documents
to the specified output directory.

Usage:
    from report_generator import generate_reports
    paths = generate_reports(result, output_dir="reports/")
    print(paths["framework_a_path"])
    print(paths["framework_b_path"])

Project layout expected:
    report_generator.py   ← this file
    framework_a.py        ← 11-section DD Report builder
    framework_b.py        ← 8-section IC Memo builder
    doc_helpers.py        ← shared utilities, colours, and Word helpers

Dependencies:
    pip install python-docx
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from report_1.framework_a import build_framework_a
from report_1.framework_b import build_framework_b


def generate_reports(result, output_dir: str = "reports/") -> dict:
    """
    Generate Framework A (DD Report) and Framework B (IC Memo) Word documents.

    Parameters
    ----------
    result : PipelineResult
        Output of the Layer 1-3 pipeline.
    output_dir : str
        Directory to write the two .docx files into (created if absent).

    Returns
    -------
    dict
        {
            "framework_a_path": "<output_dir>/dd_report_<stem>_<timestamp>.docx",
            "framework_b_path": "<output_dir>/ic_memo_<stem>_<timestamp>.docx",
        }
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    source_stem = re.sub(
        r"[^\w\-]", "_",
        Path(
            getattr(getattr(result, "deck", object()), "source_filename", "deck")
        ).stem,
    )

    a_path = out / f"dd_report_{source_stem}_{ts}.docx"
    b_path = out / f"ic_memo_{source_stem}_{ts}.docx"

    provider = os.environ.get("LLM_PROVIDER", "groq")
    build_framework_a(result, provider=provider).save(str(a_path))
    build_framework_b(result, provider=provider).save(str(b_path))

    return {
        "framework_a_path": str(a_path),
        "framework_b_path": str(b_path),
    }