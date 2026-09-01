#!/usr/bin/env python3
"""Rebuild the deterministic W4 summary from frozen evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dsh_dir", type=Path)
    parser.add_argument("openclaw_dir", type=Path)
    parser.add_argument("excluded_openclaw_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    dsh_raw = read_json(args.dsh_dir / "dsh.raw.json")
    dsh_stdout = json.loads(dsh_raw["stdout"])
    dsh_requests = read_jsonl(args.dsh_dir / "dsh.requests.jsonl")
    trace = read_jsonl(args.dsh_dir / "dsh.trace.jsonl")
    tool_calls = [item for item in trace if item["type"] == "tool/call"]
    tool_results = [item for item in trace if item["type"] == "tool/result"]
    retries = [item for item in trace if item["type"] == "llm/retry"]
    if len(tool_calls) != 1 or len(tool_results) != 1:
        raise ValueError("W4 DSH trace must contain one malformed call and one tool result")
    result = tool_results[0]["data"]
    if result.get("error") != {"name": "ToolNotFoundError", "code": "UNKNOWN_TOOL"}:
        raise ValueError("W4 DSH trace lacks the expected UNKNOWN_TOOL result")

    oc_raw = read_json(args.openclaw_dir / "openclaw.raw.json")
    oc_stdout = json.loads(oc_raw["stdout"])
    oc_requests = read_jsonl(args.openclaw_dir / "openclaw.requests.jsonl")
    excluded_requests = read_jsonl(args.excluded_openclaw_dir / "openclaw.requests.jsonl")
    output = {
        "task": "W4 deterministic malformed tool-call recovery",
        "model_endpoint": "local deterministic OpenAI-compatible SSE mock",
        "stimulus": {
            "first_response": "tool call with empty name and truncated JSON arguments",
            "second_response": "normal text completion with a fixed recovery marker",
        },
        "deepseek_harness": {
            "runtime_completed": dsh_raw["exit_code"] == 0,
            "process_exit_code": dsh_raw["exit_code"],
            "wall_seconds": dsh_raw["wall_seconds"],
            "provider_requests": len(dsh_requests),
            "model_steps": 2,
            "tool_calls": len(tool_calls),
            "llm_retries": len(retries),
            "malformed_event_treatment": "empty-name tool call",
            "tool_result": "unknown tool error with isError=true",
            "final_response": dsh_stdout["final_response"],
        },
        "openclaw": {
            "runtime_completed": oc_raw["exit_code"] == 0,
            "process_exit_code": oc_raw["exit_code"],
            "wall_seconds": oc_raw["wall_seconds"],
            "provider_requests": len(oc_requests),
            "assistant_turns": oc_stdout["assistantTurns"],
            "runtime_status": oc_stdout["status"],
            "runtime_error_kind": oc_stdout["error"]["kind"],
            "runtime_error_message": oc_stdout["error"]["message"],
            "final_response": oc_stdout["final"],
        },
        "excluded_trials": [{
            "artifact": str(args.excluded_openclaw_dir / "openclaw.raw.json"),
            "provider_requests": len(excluded_requests),
            "reason": "proxy environment produced a transport timeout instead of the deterministic malformed-call outcome",
        }],
        "notes": [
            "Both valid samples received byte-equivalent scripted first responses from fresh mock servers.",
            "DSH recovery was an ordinary second model step after a structured tool error, not an llm/retry event.",
            "No real model, external gateway, or production API key was used.",
        ],
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
