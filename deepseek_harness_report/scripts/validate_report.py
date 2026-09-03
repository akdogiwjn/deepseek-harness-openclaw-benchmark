#!/usr/bin/env python3
"""Validate generated report inputs, figures, metrics, provenance, and references."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "deepseek_harness_report"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_report import RESULT_FILES, input_fingerprint, load_inputs, source_revision  # noqa: E402


def finite_numbers(value, path="$" ) -> None:
    if isinstance(value, dict):
        for key, child in value.items(): finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value): finite_numbers(child, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite metric at {path}")


def main() -> None:
    report = (REPORT_ROOT / "report.md").read_text(encoding="utf-8")
    html = (REPORT_ROOT / "dist" / "report.html").read_text(encoding="utf-8")
    metrics = json.loads((REPORT_ROOT / "generated" / "metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((REPORT_ROOT / "generated" / "provenance.json").read_text(encoding="utf-8"))
    if re.search(r"\{\{[A-Z0-9_]+\}\}", report):
        raise ValueError("report.md contains unresolved placeholders")
    if "report.md" not in (REPORT_ROOT / "README.md").read_text(encoding="utf-8"):
        raise ValueError("README does not identify report.md")
    figures = re.findall(r"!\[[^]]*\]\((figures/[^)]+)\)", report)
    if not figures or any(not (REPORT_ROOT / path).is_file() for path in figures):
        raise ValueError("referenced report figure missing")
    if len(set(figures)) > 10:
        raise ValueError("report uses too many figures")
    for number in range(12):
        if f"## {number}." not in report:
            raise ValueError(f"missing report chapter {number}")
    if not all(marker in html for marker in ("<!doctype html>", "<nav>", "<table>", "../figures/")):
        raise ValueError("derived HTML is incomplete")
    data = load_inputs()
    for name in RESULT_FILES.values():
        if not (ROOT / "results" / name).is_file(): raise ValueError(f"missing result {name}")
    for key in ("DSH_COMMIT", "OPENCLAW_COMMIT", "NODE_VERSION"):
        source_revision(data, key)
    for directory, expected in (("deepseek-harness", provenance["deepseek_harness_commit"]),
                                ("openclaw", provenance["openclaw_commit"])):
        checkout = ROOT / "sources" / directory
        if checkout.exists():
            actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, text=True,
                                    capture_output=True, check=True).stdout.strip()
            if actual != expected: raise ValueError(f"{directory} checkout is {actual}, expected {expected}")
    protocols = [item.get("protocol") for key, item in data.items() if key.startswith("c")]
    if any(not item or not item.get("protocol_sha256") for item in protocols):
        raise ValueError("C1-C8 protocol provenance incomplete")
    for number in range(2, 11):
        if f"W{number}" not in report: raise ValueError(f"W{number} evidence reference absent")
    for number in range(1, 9):
        if f"C{number}" not in report: raise ValueError(f"C{number} evidence reference absent")
    finite_numbers(metrics)
    if provenance["report_input_sha256"] != input_fingerprint():
        raise ValueError("report input fingerprint mismatch")
    pinned = {provenance["deepseek_harness_commit"], provenance["openclaw_commit"]}
    if any(len(value) != 40 for value in pinned): raise ValueError("pinned revision is not a full SHA")
    if not (ROOT / "evidence" / "manifest.json").is_file(): raise ValueError("evidence manifest missing")
    print(f"report validation PASS: {len(set(figures))} unique figures, {len(RESULT_FILES)} result inputs")


if __name__ == "__main__":
    main()
