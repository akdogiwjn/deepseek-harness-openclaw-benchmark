#!/usr/bin/env python3
"""Verify and summarize W10 local/sandbox/local A-B-A-prime evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tool_projection(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    output: list[dict[str, Any]] = []
    for event in events:
        data = event.get("data", {})
        if event.get("type") == "tool/call":
            calls[str(data.get("callId"))] = {
                "name": data.get("name"),
                "arguments": data.get("arguments"),
            }
        if event.get("type") == "tool/result":
            source = data.get("message", {}).get("source", {})
            call = calls.get(str(source.get("callId")), {})
            output.append({
                **call,
                "is_error": any(
                    block.get("isError") is True
                    for block in data.get("message", {}).get("content", [])
                    if isinstance(block, dict)
                ),
                "error_code": data.get("error", {}).get("code"),
            })
    return output


def summarize(path: Path) -> dict[str, Any]:
    case = read_json(path / "case.json")
    raw = read_json(path / "runtime.raw.json")
    stdout = json.loads(raw["stdout"])
    requests = jsonl(path / "requests.jsonl")
    events = jsonl(path / "session.jsonl")[1:]
    root = Path(__file__).resolve().parent.parent
    workspace = root / "workspaces" / path.name
    # Result and workspace directory names both use w10-<trial-id>.
    frozen_state = path / "workspace-state.json"
    if frozen_state.exists():
        state = read_json(frozen_state)
        inside_text = state["inside"]
        outside_text = state["outside"]
    else:
        inside_text = (workspace / "workspace" / "inside.txt").read_text(encoding="utf-8").strip()
        outside_text = (workspace / "outside" / "outside.txt").read_text(encoding="utf-8").strip()
    projection = tool_projection(events)
    if raw["exit_code"] != 0 or stdout.get("final_response") != "COMPLETED_W10_FS_SEAM":
        raise ValueError(f"{path}: runtime did not complete")
    if len(requests) != 4 or case["provider_requests"] != 4:
        raise ValueError(f"{path}: expected four provider requests")
    if case.get("outside_path_precondition") is not True:
        raise ValueError(f"{path}: outside target was not proven beyond sandbox writable roots")
    if len(projection) != 3:
        raise ValueError(f"{path}: expected three tool results")
    return {
        "artifact": f"results/{path.name}",
        "variant": case["variant"],
        "provider_requests": len(requests),
        "outside_path_precondition": case["outside_path_precondition"],
        "tool_names": requests[0]["tool_names"],
        "tool_schema_sha256": requests[0]["tool_schema_sha256"],
        "edit_properties": requests[0]["edit_properties"],
        "scripted_calls": [
            {"name": item["scripted_tool"], "arguments": item["scripted_arguments"]}
            for item in requests[:3]
        ],
        "tool_results": projection,
        "inside": inside_text,
        "outside": outside_text,
    }


def normalized_local(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in {"artifact"}}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("local_a", type=Path)
    parser.add_argument("sandbox_b", type=Path)
    parser.add_argument("local_aprime", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    local_a = summarize(args.local_a)
    sandbox = summarize(args.sandbox_b)
    local_aprime = summarize(args.local_aprime)
    common_calls = local_a["scripted_calls"] == sandbox["scripted_calls"] == local_aprime["scripted_calls"]
    checks = {
        "a_equals_a_prime": normalized_local(local_a) == normalized_local(local_aprime),
        "scripted_calls_identical": common_calls,
        "outside_path_precondition_all_variants": all(
            item["outside_path_precondition"] is True for item in (local_a, sandbox, local_aprime)
        ),
        "inside_changed_all_variants": all(
            item["inside"] == "INSIDE_CHANGED" for item in (local_a, sandbox, local_aprime)
        ),
        "outside_changed_under_local": local_a["outside"] == local_aprime["outside"] == "OUTSIDE_CHANGED",
        "outside_denied_under_sandbox": sandbox["outside"] == "OUTSIDE_ORIGINAL"
        and sandbox["tool_results"][2]["error_code"] == "FS_SANDBOX_DENIED",
        "native_schema_delta_observed": "sandbox_permissions" not in local_a["edit_properties"]
        and "sandbox_permissions" in sandbox["edit_properties"]
        and "justification" in sandbox["edit_properties"],
    }
    if not all(checks.values()):
        raise ValueError(f"W10 verification failed: {checks}")
    output = {
        "task": "W10 native tool-fs capability seam swap",
        "design": "A/B/A-prime with fresh workspaces and sessions",
        "local_a": local_a,
        "sandbox_b": sandbox,
        "local_a_prime": local_aprime,
        "checks": checks,
        "notes": [
            "The agent loop, deterministic provider script, sandbox-policy mode, and tool-fs consumer package are held constant.",
            "The mounted ctx.fs provider changes from fs-local to fs-sandbox.",
            "Each runner canonicalizes the sibling target and fails before execution if it falls under the workspace, /tmp, or os.tmpdir().",
            "Native tool-fs intentionally adds escalation fields under a confining provider, so full schema hashes are not expected to match.",
            "The post-tool model transcript differs because the third tool result differs.",
        ],
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(checks))


if __name__ == "__main__":
    main()
