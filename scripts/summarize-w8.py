#!/usr/bin/env python3
"""Summarize the four deterministic W8 direct/code artifacts."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


FINAL_MARKER = "COMPLETED_W8_CODE_MODE_ABLATION"
EXPECTED_MARKERS = [f"W8_STEP_{step:03d}" for step in range(1, 9)]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_dsh_trace(result_dir: Path, mode: str) -> dict[str, Any]:
    trace_path = result_dir / "dsh.trace.jsonl"
    if not trace_path.is_file():
        raise ValueError(f"{result_dir}: frozen DSH trace is missing")
    rows = read_jsonl(trace_path)
    calls = [row for row in rows if row.get("type") == "tool/call"]
    starts = [row for row in rows if row.get("type") == "tool/code-dispatch-start"]
    dispatches = [row for row in rows if row.get("type") == "tool/code-dispatch"]
    if mode == "direct":
        if len(calls) != 8 or any(row.get("data", {}).get("name") != "bash" for row in calls):
            raise ValueError(f"{result_dir}: direct DSH trace does not contain eight bash calls")
        if starts or dispatches:
            raise ValueError(f"{result_dir}: direct DSH trace unexpectedly contains code dispatches")
    else:
        if len(calls) != 1 or calls[0].get("data", {}).get("name") != "run_code":
            raise ValueError(f"{result_dir}: PTC trace does not contain one outer run_code call")
        if len(starts) != 8 or len(dispatches) != 8:
            raise ValueError(f"{result_dir}: PTC trace does not contain eight dispatch pairs")
        start_ids = [row.get("data", {}).get("subCallId") for row in starts]
        dispatch_ids = [row.get("data", {}).get("subCallId") for row in dispatches]
        if start_ids != dispatch_ids or len(set(start_ids)) != 8:
            raise ValueError(f"{result_dir}: PTC dispatch correlation is incomplete")
        if any(row.get("data", {}).get("name") != "bash" for row in starts + dispatches):
            raise ValueError(f"{result_dir}: PTC dispatch used an unexpected tool")
        if any(row.get("data", {}).get("isError") is not False for row in dispatches):
            raise ValueError(f"{result_dir}: a PTC dispatch failed")
        markers = []
        for row in starts:
            command = row.get("data", {}).get("arguments", {}).get("command", "")
            match = re.search(r"W8_STEP_\d{3}", command)
            markers.append(match.group(0) if match else None)
        if markers != EXPECTED_MARKERS:
            raise ValueError(f"{result_dir}: PTC dispatch order differs from the workspace markers")
    return {
        "outer_tool_calls": len(calls),
        "code_dispatch_starts": len(starts),
        "code_dispatches": len(dispatches),
        "dispatch_pairs_correlated": mode == "direct" or len(starts) == len(dispatches) == 8,
    }


def summarize(result_dir: Path) -> dict[str, Any]:
    case = read_json(result_dir / "case.json")
    raw = read_json(result_dir / "runtime.raw.json")
    stdout = json.loads(raw["stdout"])
    requests = [
        json.loads(line)
        for line in (result_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Result names are w8-<trial-id>, exactly matching their workspace names.
    workspace = result_dir.parent.parent / "workspaces" / result_dir.name
    markers = (workspace / "w8.log").read_text(encoding="utf-8").splitlines()
    final_response = stdout.get("final_response", stdout.get("final", ""))
    expected_requests = 9 if case["mode"] == "direct" else 2
    if raw["exit_code"] != 0 or case["runtime_exit_code"] != 0:
        raise ValueError(f"{result_dir}: runtime did not complete")
    if len(requests) != expected_requests or case["provider_requests"] != expected_requests:
        raise ValueError(f"{result_dir}: expected {expected_requests} provider requests")
    if case["marker_count"] != 8 or markers != EXPECTED_MARKERS:
        raise ValueError(f"{result_dir}: underlying shell operations differ")
    if final_response != FINAL_MARKER:
        raise ValueError(f"{result_dir}: final marker is missing")
    if requests[0]["detected_mode"] != case["mode"]:
        raise ValueError(f"{result_dir}: provider detected the wrong mode")
    if requests[0]["detected_runtime"] != case["runtime"]:
        raise ValueError(f"{result_dir}: provider detected the wrong runtime")
    dsh_trace = validate_dsh_trace(result_dir, case["mode"]) if case["runtime"] == "dsh" else None

    process_started = datetime.fromisoformat(raw["started_at"]).timestamp()
    first_request = requests[0]["time_ns"] / 1_000_000_000
    final_request = requests[-1]["time_ns"] / 1_000_000_000
    process_ended = process_started + raw["wall_seconds"]
    return {
        "artifact": str(result_dir),
        "runtime": case["runtime"],
        "mode": case["mode"],
        "runtime_completed": True,
        "wall_seconds": raw["wall_seconds"],
        "provider_requests": len(requests),
        "model_visible_tool_calls": len(requests) - 1,
        "underlying_shell_calls": 8,
        "markers_exact_and_ordered": True,
        "provider_visible_tools": requests[0]["tool_names"],
        "request_payload": {
            "first_body_bytes": requests[0]["request_body_bytes"],
            "final_body_bytes": requests[-1]["request_body_bytes"],
            "total_body_bytes": sum(item["request_body_bytes"] for item in requests),
            "first_tool_schema_bytes": requests[0]["tool_schema_bytes"],
        },
        "phase_seconds": {
            "process_start_to_first_request": first_request - process_started,
            "first_to_final_request": final_request - first_request,
            "final_request_to_process_end": process_ended - final_request,
        },
        "reported": {
            "code_mode_engaged": stdout.get("codeModeEngaged"),
            "assistant_turns": stdout.get("assistantTurns"),
            "bridge_calls": stdout.get("bridgeCalls"),
            "tool_summary": stdout.get("toolSummary"),
        },
        **({"dsh_trace": dsh_trace} if dsh_trace is not None else {}),
    }


def reduction(direct: dict[str, Any], code: dict[str, Any]) -> dict[str, Any]:
    direct_bytes = direct["request_payload"]["total_body_bytes"]
    code_bytes = code["request_payload"]["total_body_bytes"]
    return {
        "provider_request_reduction": direct["provider_requests"] - code["provider_requests"],
        "provider_request_reduction_percent": 100 * (1 - code["provider_requests"] / direct["provider_requests"]),
        "model_visible_tool_call_reduction": direct["model_visible_tool_calls"] - code["model_visible_tool_calls"],
        "total_request_body_reduction_bytes": direct_bytes - code_bytes,
        "total_request_body_reduction_percent": 100 * (1 - code_bytes / direct_bytes),
        "wall_seconds_change": code["wall_seconds"] - direct["wall_seconds"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dsh_direct", type=Path)
    parser.add_argument("dsh_code", type=Path)
    parser.add_argument("openclaw_direct", type=Path)
    parser.add_argument("openclaw_code", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    dsh_direct = summarize(args.dsh_direct)
    dsh_code = summarize(args.dsh_code)
    openclaw_direct = summarize(args.openclaw_direct)
    openclaw_code = summarize(args.openclaw_code)
    output = {
        "task": "W8 deterministic direct tool calling versus code mode",
        "model_endpoint": "local deterministic OpenAI-compatible SSE mock",
        "underlying_operations_per_condition": 8,
        "deepseek_harness": {
            "direct": dsh_direct,
            "code": dsh_code,
            "paired_change": reduction(dsh_direct, dsh_code),
        },
        "openclaw": {
            "direct": openclaw_direct,
            "code": openclaw_code,
            "paired_change": reduction(openclaw_direct, openclaw_code),
        },
        "notes": [
            "The provider scripted every outer call; no real model or production credential participated.",
            "Code conditions execute the same eight shell commands through one model-visible program call.",
            "Single cold-process wall times are mechanism traces, not population performance estimates.",
            "Payload bytes are exact serialized HTTP request sizes, not tokenizer counts.",
        ],
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
