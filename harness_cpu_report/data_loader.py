"""Load the exact benchmark artifacts used by the offline report."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CPU_FILES = {
    "C1": "c1-agent-loop-pilot.json",
    "C2": "c2-session-count-pilot.json",
    "C3": "c3-context-json-pilot.json",
    "C4": "c4-shell-lifecycle-pilot.json",
    "C5": "c5-code-mode-cpu-pilot.json",
    "C6": "c6-fs-sandbox-cpu-pilot.json",
    "C7": "c7-agent-scaleout-pilot.json",
}

C8_FILES = {
    "cold": "c8-token-meter-cold-pilot.json",
    "incremental": "c8-token-meter-incremental-pilot.json",
    "repeat": "c8-token-meter-repeat-pilot.json",
    "shape_schema": "c8-token-meter-shape-schema-pilot.json",
    "shape_text": "c8-token-meter-shape-text-pilot.json",
    "shape_tool_call": "c8-token-meter-shape-tool-call-pilot.json",
    "shape_tool_result": "c8-token-meter-shape-tool-result-pilot.json",
}

WORKLOAD_FILES = {
    "W2": "w2-aggregate-n5.json",
    "W3": "w3-aggregate-n5.json",
    "W4": "w4-recovery-summary.json",
    "W5": "w5-compaction-summary.json",
    "W6": "w6-tool-failure-summary.json",
    "W7": "w7-long-chain-summary.json",
    "W8": "w8-code-mode-summary.json",
    "W9": "w9-session-summary.json",
    "W10": "w10-fs-seam-summary.json",
}


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load required report input {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"required report input is not an object: {path}")
    return value


def artifact(name: str) -> dict:
    path = ROOT / "results" / name
    return {"file": path.relative_to(ROOT).as_posix(), "data": load_json(path)}


def load_cpu_results() -> dict:
    results = {key: artifact(name) for key, name in CPU_FILES.items()}
    results["C8"] = {
        "files": {key: f"results/{name}" for key, name in C8_FILES.items()},
        "data": {key: artifact(name)["data"] for key, name in C8_FILES.items()},
    }
    return results


def load_workload_results() -> dict:
    return {key: artifact(name) for key, name in WORKLOAD_FILES.items()}


def load_evidence_index() -> dict:
    path = ROOT / "evidence" / "manifest.json"
    return {"file": path.relative_to(ROOT).as_posix(), "data": load_json(path)}
