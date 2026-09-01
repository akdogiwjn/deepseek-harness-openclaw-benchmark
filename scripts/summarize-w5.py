#!/usr/bin/env python3
"""Summarize the calibrated W5 compaction pair and its 16K stress case."""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


FINAL_MARKER = "COMPLETED_W5_AFTER_COMPACTION"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_requests(result_dir: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (result_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def summarize_main(result_dir: Path) -> dict[str, Any]:
    case = read_json(result_dir / "case.json")
    raw = read_json(result_dir / "runtime.raw.json")
    requests = load_requests(result_dir)
    stdout = json.loads(raw["stdout"])
    final_response = stdout.get("final_response", stdout.get("final", ""))
    if raw["exit_code"] != 0 or case["runtime_exit_code"] != 0:
        raise ValueError(f"{result_dir}: calibrated run did not complete")
    if case["agent_requests"] != 9 or case["compaction_requests"] != 3:
        raise ValueError(f"{result_dir}: expected 9 agent and 3 compaction requests")
    if len(requests) != 12 or final_response != FINAL_MARKER:
        raise ValueError(f"{result_dir}: request count or final marker mismatch")
    if [item["request"] for item in requests] != list(range(1, 13)):
        raise ValueError(f"{result_dir}: request sequence is not contiguous")

    boundaries: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        if request["kind"] != "compaction":
            continue
        before = next(item for item in reversed(requests[:index]) if item["kind"] == "agent")
        after = next(item for item in requests[index + 1 :] if item["kind"] == "agent")
        if not after["summary_marker_present"] or not after["anchor_present"]:
            raise ValueError(f"{result_dir}: compacted summary or anchor missing after rewrite")
        boundaries.append(
            {
                "compaction_request": request["request"],
                "after_agent_request_ordinal": before["kind_ordinal"],
                "compaction_request_body_bytes": request["request_body_bytes"],
                "agent_body_before_bytes": before["request_body_bytes"],
                "agent_body_after_bytes": after["request_body_bytes"],
                "agent_body_reduction_bytes": (
                    before["request_body_bytes"] - after["request_body_bytes"]
                ),
            }
        )

    started = datetime.fromisoformat(raw["started_at"]).timestamp()
    ended = started + raw["wall_seconds"]
    first_time = requests[0]["time_ns"] / 1_000_000_000
    final_time = requests[-1]["time_ns"] / 1_000_000_000
    intervals = [
        (right["time_ns"] - left["time_ns"]) / 1_000_000_000
        for left, right in zip(requests, requests[1:])
    ]
    agent_requests = [item for item in requests if item["kind"] == "agent"]
    compaction_requests = [item for item in requests if item["kind"] == "compaction"]
    return {
        "artifact": str(result_dir),
        "runtime": case["runtime"],
        "runtime_completed": True,
        "process_exit_code": 0,
        "wall_seconds": raw["wall_seconds"],
        "provider_requests": len(requests),
        "agent_requests": len(agent_requests),
        "compaction_requests": len(compaction_requests),
        "tool_calls": len(agent_requests) - 1,
        "final_response": final_response,
        "compaction_boundaries": boundaries,
        "payload_bytes": {
            "all_requests": sum(item["request_body_bytes"] for item in requests),
            "agent_requests": sum(item["request_body_bytes"] for item in agent_requests),
            "compaction_requests": sum(
                item["request_body_bytes"] for item in compaction_requests
            ),
            "first_agent_request": agent_requests[0]["request_body_bytes"],
            "maximum_agent_request": max(item["request_body_bytes"] for item in agent_requests),
            "final_agent_request": agent_requests[-1]["request_body_bytes"],
        },
        "phase_seconds": {
            "process_start_to_first_request": first_time - started,
            "first_to_final_request": final_time - first_time,
            "final_request_to_process_end": ended - final_time,
            "median_inter_request": statistics.median(intervals),
        },
    }


def summarize_stress(result_dir: Path) -> dict[str, Any]:
    case = read_json(result_dir / "case.json")
    raw = read_json(result_dir / "runtime.raw.json")
    stdout = json.loads(raw["stdout"])
    return {
        "artifact": str(result_dir),
        "runtime": case["runtime"],
        "runtime_completed": raw["exit_code"] == 0,
        "process_exit_code": raw["exit_code"],
        "wall_seconds": raw["wall_seconds"],
        "provider_requests": case["provider_requests"],
        "agent_requests": case["agent_requests"],
        "compaction_requests": case["compaction_requests"],
        "final_response": stdout.get("final_response", stdout.get("final", "")),
        "error": stdout.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dsh_main", type=Path)
    parser.add_argument("openclaw_main", type=Path)
    parser.add_argument("dsh_stress", type=Path)
    parser.add_argument("openclaw_stress", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    evidence_results = args.dsh_main.parent
    output = {
        "task": "W5 deterministic automatic compaction",
        "model_endpoint": "local deterministic OpenAI-compatible SSE mock",
        "calibrated_main_pair": {
            "shared": {
                "context_window_tokens": 32000,
                "retained_recent_tokens": 2000,
                "tool_calls": 8,
                "tool_output_payload_chars_per_call": 4096,
                "fixed_summary": "W5_FIXED_COMPACTION_SUMMARY",
            },
            "trigger_calibration": {
                "deepseek_harness_heuristic_threshold_tokens": 4800,
                "openclaw_prompt_budget_before_reserve_tokens": 12000,
                "reason": "different prompt envelopes and token estimators require different numeric thresholds to align observed trigger positions",
            },
            "deepseek_harness": summarize_main(args.dsh_main),
            "openclaw": summarize_main(args.openclaw_main),
        },
        "same_numeric_16k_stress_pair": {
            "shared": {
                "context_window_tokens": 16000,
                "trigger_tokens": 8000,
                "retained_recent_tokens": 2000,
                "planned_tool_calls": 10,
            },
            "deepseek_harness": summarize_stress(args.dsh_stress),
            "openclaw": summarize_stress(args.openclaw_stress),
        },
        "excluded_pilots": [
            {
                "artifact": str(evidence_results / "w5-dsh-compaction-001"),
                "reason": "catalog model capacity overrode the intended DSH_CONTEXT_WINDOW fallback"
            },
            {
                "artifact": str(evidence_results / "w5-openclaw-compaction-001"),
                "reason": "env.sh overwrote the requested compaction config path with the minimal config"
            },
            {
                "artifacts": [
                    str(evidence_results / "w5-dsh-compaction-002"),
                    str(evidence_results / "w5-openclaw-compaction-002")
                ],
                "reason": "mock stopped two agent requests after first compaction, producing unequal tool-call counts"
            },
            {
                "artifacts": [
                    str(evidence_results / "w5-dsh-compaction-004"),
                    str(evidence_results / "w5-openclaw-compaction-004")
                ],
                "reason": "same 32K numeric threshold did not trigger DSH within ten calls and exhausted OpenClaw recovery attempts"
            }
        ],
        "notes": [
            "The mock scripted tool calls and returned the same fixed summary; no real model or production credential participated.",
            "The calibrated pair compares compaction mechanics after aligning observed trigger positions, not equal policy parameters.",
            "Single-run wall times are mechanism traces, not population-level performance estimates."
        ]
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
