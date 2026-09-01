#!/usr/bin/env python3
"""Normalize one DSH/OpenClaw pair into a secret-free benchmark summary."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_stat(workspace: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(workspace), "diff", "--stat"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def changed_files(workspace: Path) -> list[str]:
    return subprocess.run(
        ["git", "-C", str(workspace), "status", "--short"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--dsh-raw", type=Path, required=True)
    parser.add_argument("--dsh-trace", type=Path, required=True)
    parser.add_argument("--dsh-workspace", type=Path, required=True)
    parser.add_argument("--dsh-verifier", type=Path, required=True)
    parser.add_argument("--openclaw-raw", type=Path, required=True)
    parser.add_argument("--openclaw-workspace", type=Path, required=True)
    parser.add_argument("--openclaw-verifier", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dsh_process = load_json(args.dsh_raw)
    dsh_result = json.loads(dsh_process["stdout"])
    events = [json.loads(line) for line in args.dsh_trace.read_text(encoding="utf-8").splitlines()]
    usages = []
    tool_names: list[str] = []
    native_tool_failures = 0
    nonzero_command_results = 0
    for event in events:
        if event["type"] == "assistant/message":
            data = event.get("data", {})
            usage = data.get("message", {}).get("usage") or data.get("usage")
            if usage:
                usages.append(usage)
        elif event["type"] == "tool/call":
            tool_names.append(event["data"]["name"])
        elif event["type"] == "tool/result":
            content = event.get("data", {}).get("message", {}).get("content", [])
            if content and content[0].get("isError"):
                native_tool_failures += 1
            text_parts = content[0].get("content", []) if content else []
            text = "\n".join(part.get("text", "") for part in text_parts)
            if re.search(r"\[exit code: [1-9][0-9]*\]", text):
                nonzero_command_results += 1

    openclaw_process = load_json(args.openclaw_raw)
    openclaw_result = json.loads(openclaw_process["stdout"])
    dsh_verifier = load_json(args.dsh_verifier)
    openclaw_verifier = load_json(args.openclaw_verifier)

    summary = {
        "task": args.task,
        "model": "deepseek-v4-flash",
        "deepseek_harness": {
            "valid": dsh_result.get("finish_reason") == "completed",
            "verifier_passed": dsh_verifier["exit_code"] == 0,
            "process_exit_code": dsh_process["exit_code"],
            "runtime_status": dsh_result.get("finish_reason"),
            "session_id": dsh_result.get("session_id"),
            "wall_seconds": dsh_process["wall_seconds"],
            "model_steps": sum(event["type"] == "step/start" for event in events),
            "tool_calls": len(tool_names),
            "tools": dict(sorted(Counter(tool_names).items())),
            "native_tool_failures": native_tool_failures,
            "detected_nonzero_command_results": nonzero_command_results,
            "llm_retries": sum(event["type"] == "llm/retry" for event in events),
            "usage": {
                "input": sum(item.get("inputTokens", 0) for item in usages),
                "output": sum(item.get("outputTokens", 0) for item in usages),
                "cache_read": sum(item.get("cacheReadTokens", 0) for item in usages),
                "reasoning": sum(item.get("reasoningTokens", 0) for item in usages),
            },
            "diff_stat": diff_stat(args.dsh_workspace),
            "changed_files": changed_files(args.dsh_workspace),
        },
        "openclaw": {
            "valid": openclaw_result.get("ok") is True,
            "verifier_passed": openclaw_verifier["exit_code"] == 0,
            "process_exit_code": openclaw_process["exit_code"],
            "runtime_status": openclaw_result.get("status"),
            "runtime_error": openclaw_result.get("error"),
            "session_id": openclaw_result.get("sessionId"),
            "wall_seconds": openclaw_process["wall_seconds"],
            "assistant_turns": openclaw_result.get("assistantTurns"),
            "tool_calls": openclaw_result.get("toolSummary", {}).get("calls"),
            "tools": openclaw_result.get("toolSummary", {}).get("tools"),
            "native_tool_failures": openclaw_result.get("toolSummary", {}).get("failures"),
            "usage": openclaw_result.get("usage"),
            "diff_stat": diff_stat(args.openclaw_workspace),
            "changed_files": changed_files(args.openclaw_workspace),
        },
        "notes": [
            "Token counts are native provider/runtime counters and are not assumed to be directly comparable.",
            "DSH native tool errors and detected non-zero Bash results are recorded separately.",
            "No credential or gateway URL is stored in this summary."
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
