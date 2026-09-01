#!/usr/bin/env python3
"""Summarize two deterministic W7 runtime artifacts."""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def summarize(result_dir: Path) -> dict[str, Any]:
    case = read_json(result_dir / "case.json")
    raw = read_json(result_dir / "runtime.raw.json")
    requests = [
        json.loads(line)
        for line in (result_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    stdout = json.loads(raw["stdout"])
    final_response = stdout.get("final_response", stdout.get("final", ""))
    expected_requests = case["steps"] + 1
    if len(requests) != expected_requests or case["provider_requests"] != expected_requests:
        raise ValueError(f"{result_dir}: expected {expected_requests} provider requests")
    if [item["request"] for item in requests] != list(range(1, expected_requests + 1)):
        raise ValueError(f"{result_dir}: request sequence is not contiguous")
    if raw["exit_code"] != case["runtime_exit_code"]:
        raise ValueError(f"{result_dir}: inconsistent runtime exit codes")
    if final_response != "COMPLETED_W7_LONG_TOOL_CHAIN":
        raise ValueError(f"{result_dir}: final marker is missing")
    body_sizes = [item["request_body_bytes"] for item in requests]
    message_counts = [item["message_count"] for item in requests]
    request_intervals = [
        (right["time_ns"] - left["time_ns"]) / 1_000_000_000
        for left, right in zip(requests, requests[1:])
    ]
    marker_checks = [item["all_prior_markers_present"] for item in requests]
    tool_result_marker_checks = [
        item["all_prior_markers_in_tool_results"] for item in requests
    ]
    pairing_checks = [
        not item["unpaired_assistant_tool_call_ids"]
        and not item["orphan_tool_result_ids"]
        for item in requests
    ]
    if not all(marker_checks) or not all(tool_result_marker_checks):
        raise ValueError(f"{result_dir}: prior tool-result markers disappeared")
    if not all(pairing_checks):
        raise ValueError(f"{result_dir}: assistant calls and tool results are unpaired")
    final_request = requests[-1]
    expected_final_markers = [f"W7_STEP_{step:03d}" for step in range(1, case["steps"] + 1)]
    if final_request["expected_prior_markers"] != expected_final_markers:
        raise ValueError(f"{result_dir}: final cumulative marker expectation is incomplete")
    if final_request["tool_result_count"] != case["steps"]:
        raise ValueError(f"{result_dir}: final request lacks twenty tool-result messages")
    process_started = datetime.fromisoformat(raw["started_at"]).timestamp()
    first_request_time = requests[0]["time_ns"] / 1_000_000_000
    final_request_time = requests[-1]["time_ns"] / 1_000_000_000
    process_ended = process_started + raw["wall_seconds"]
    body_growth_steps = [right - left for left, right in zip(body_sizes, body_sizes[1:])]
    return {
        "artifact": str(result_dir),
        "runtime": case["runtime"],
        "runtime_completed": raw["exit_code"] == 0,
        "process_exit_code": raw["exit_code"],
        "wall_seconds": raw["wall_seconds"],
        "provider_requests": len(requests),
        "tool_calls": len(requests) - 1,
        "final_response": final_response,
        "all_prior_markers_present_in_every_request": all(marker_checks),
        "all_prior_markers_in_tool_results_in_every_request": all(tool_result_marker_checks),
        "final_request_contains_all_tool_result_markers": True,
        "final_request_tool_result_count": final_request["tool_result_count"],
        "all_tool_calls_and_results_paired": all(pairing_checks),
        "context": {
            "first_request_body_bytes": body_sizes[0],
            "final_request_body_bytes": body_sizes[-1],
            "request_body_growth_bytes": body_sizes[-1] - body_sizes[0],
            "median_request_growth_per_step_bytes": statistics.median(body_growth_steps),
            "total_request_body_bytes": sum(body_sizes),
            "first_message_count": message_counts[0],
            "final_message_count": message_counts[-1],
            "message_count_growth": message_counts[-1] - message_counts[0],
            "first_messages_bytes": requests[0]["messages_bytes"],
            "final_messages_bytes": requests[-1]["messages_bytes"],
            "messages_growth_bytes": (
                requests[-1]["messages_bytes"] - requests[0]["messages_bytes"]
            ),
            "tool_schema_bytes": requests[0]["tool_schema_bytes"],
        },
        "phase_seconds": {
            "process_start_to_first_request": first_request_time - process_started,
            "first_to_final_request": final_request_time - first_request_time,
            "final_request_to_process_end": process_ended - final_request_time,
        },
        "inter_request_seconds": {
            "total": sum(request_intervals),
            "median": statistics.median(request_intervals),
            "minimum": min(request_intervals),
            "maximum": max(request_intervals),
        },
        "reported_tool_summary": stdout.get("toolSummary"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dsh_result", type=Path)
    parser.add_argument("openclaw_result", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = {
        "task": "W7 deterministic 20-call tool chain",
        "model_endpoint": "local deterministic OpenAI-compatible SSE mock",
        "token_metrics": "not reported; payload bytes are measured exactly",
        "deepseek_harness": summarize(args.dsh_result),
        "openclaw": summarize(args.openclaw_result),
        "notes": [
            "The provider scripted every call; no real model or production credential participated.",
            "Inter-request intervals include tool execution plus agent-loop and local transport work.",
            "Single-run wall times are mechanism traces, not population-level performance estimates."
        ],
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
