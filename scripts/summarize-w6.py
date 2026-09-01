#!/usr/bin/env python3
"""Rebuild the deterministic W6 summary from frozen evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarize(result_dir: Path) -> dict[str, Any]:
    case = read_json(result_dir / "case.json")
    raw = read_json(result_dir / "runtime.raw.json")
    stdout = json.loads(raw["stdout"])
    requests = read_jsonl(result_dir / "requests.jsonl")
    if len(requests) != 2 or case["provider_requests"] != 2:
        raise ValueError(f"{result_dir}: expected two provider requests")
    tool_results = requests[-1]["tool_results"]
    if len(tool_results) != 1:
        raise ValueError(f"{result_dir}: expected one model-visible tool result")
    observation = tool_results[0]["content"]
    result: dict[str, Any] = {
        "artifact": str(result_dir),
        "runtime_completed": raw["exit_code"] == 0,
        "process_exit_code": raw["exit_code"],
        "wall_seconds": raw["wall_seconds"],
        "provider_requests": len(requests),
    }
    if case["runtime"] == "dsh":
        trace = read_jsonl(result_dir / "dsh.trace.jsonl")
        event = next(item for item in trace if item["type"] == "tool/result")
        content = event["data"]["message"]["content"][0]
        result["tool_is_error"] = content["isError"]
        if case["scenario"] == "invalid-args":
            result["error_name"] = event["data"]["error"]["name"]
            result["error_code"] = event["data"]["error"]["code"]
    else:
        result["tool_summary_failures"] = stdout["toolSummary"]["failures"]
    if case["scenario"] == "nonzero":
        if "W6_STDOUT" not in observation or "W6_STDERR" not in observation or "17" not in observation:
            raise ValueError(f"{result_dir}: nonzero exit observation is incomplete")
        result["observation"] = (
            "W6_STDOUT; W6_STDERR; [exit code: 17]"
            if case["runtime"] == "dsh"
            else "W6_STDOUT; W6_STDERR; (Command exited with code 17)"
        )
        result["final_response"] = stdout.get("final_response", stdout.get("final"))
    else:
        if "command" not in observation.lower():
            raise ValueError(f"{result_dir}: invalid-argument observation is incomplete")
        if case["runtime"] == "openclaw":
            result["error"] = "Validation failed for tool exec: command is required"
        result["final_response"] = stdout.get("final_response", stdout.get("final"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dsh_nonzero", type=Path)
    parser.add_argument("openclaw_nonzero", type=Path)
    parser.add_argument("dsh_invalid", type=Path)
    parser.add_argument("openclaw_invalid", type=Path)
    parser.add_argument("excluded_dsh", type=Path)
    parser.add_argument("excluded_openclaw", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = {
        "task": "W6 deterministic tool-failure handling",
        "model_endpoint": "local deterministic OpenAI-compatible SSE mock",
        "scenarios": {
            "nonzero_child_exit": {
                "stimulus": "child shell prints stdout and stderr, then exits 17",
                "deepseek_harness": summarize(args.dsh_nonzero),
                "openclaw": summarize(args.openclaw_nonzero),
            },
            "missing_required_argument": {
                "stimulus": "valid shell tool name with empty argument object",
                "deepseek_harness": summarize(args.dsh_invalid),
                "openclaw": summarize(args.openclaw_invalid),
            },
        },
        "excluded_trials": [{
            "artifacts": [str(args.excluded_dsh), str(args.excluded_openclaw)],
            "reason": "direct exit builtin terminated DSH persistent shell but only OpenClaw's one-shot shell",
        }],
        "notes": [
            "Each valid sample used a fresh workspace, session, result directory, and mock server.",
            "Both runtimes requested the fixed second completion for both valid scenarios.",
            "Wall times are single mechanism-trace metadata, not performance estimates.",
        ],
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
