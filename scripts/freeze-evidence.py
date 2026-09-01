#!/usr/bin/env python3
"""Freeze the minimal, redacted input closure for deterministic W4-W8 summaries."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import socket
from pathlib import Path
from typing import Any


GROUPS = {
    "W4": ["w4-recovery-001", "w4-recovery-002"],
    "W5": [
        "w5-dsh-compaction-001",
        "w5-openclaw-compaction-001",
        "w5-dsh-compaction-002",
        "w5-openclaw-compaction-002",
        "w5-dsh-compaction-003",
        "w5-openclaw-compaction-003",
        "w5-dsh-compaction-004",
        "w5-openclaw-compaction-004",
        "w5-dsh-compaction-005",
        "w5-openclaw-compaction-005",
    ],
    "W6": [
        "w6-dsh-nonzero-001",
        "w6-openclaw-nonzero-001",
        "w6-dsh-nonzero-002",
        "w6-openclaw-nonzero-002",
        "w6-dsh-invalid-args-001",
        "w6-openclaw-invalid-args-001",
    ],
    "W7": ["w7-dsh-chain-002", "w7-openclaw-chain-002"],
    "W8": [
        "w8-dsh-direct-01",
        "w8-dsh-code-01",
        "w8-openclaw-direct-01",
        "w8-openclaw-code-01",
    ],
}

TRACE_SESSION_IDS = {
    "w4-recovery-001": "dsh-w4-001",
    "w6-dsh-nonzero-001": "dsh-w6-dsh-nonzero-001",
    "w6-dsh-nonzero-002": "dsh-w6-dsh-nonzero-002",
    "w6-dsh-invalid-args-001": "dsh-w6-dsh-invalid-args-001",
}

TRACE_TYPES = {"assistant/message", "tool/call", "tool/result", "llm/retry", "turn/end"}


def sanitize_string(value: str, root: Path) -> str:
    value = value.replace(str(root), "$BENCH_ROOT")
    value = value.replace(f"~/{root.name}", "$BENCH_ROOT")
    value = value.replace(socket.gethostname(), "$HOST")
    return re.sub(r"/tmp/openclaw-agent-exec-[^/\s;)]+", "$OPENCLAW_TEMP", value)


def sanitize(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return sanitize_string(value, root)
    if isinstance(value, list):
        return [sanitize(item, root) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item, root) for key, item in value.items()}
    return value


def compact_w6_request(record: dict[str, Any]) -> dict[str, Any]:
    messages = record.pop("messages", [])
    record["message_count"] = len(messages)
    record["assistant_tool_calls"] = [
        call
        for message in messages
        if isinstance(message, dict) and message.get("role") == "assistant"
        for call in message.get("tool_calls", [])
        if isinstance(call, dict)
    ]
    record["tool_results"] = [
        message
        for message in messages
        if isinstance(message, dict) and message.get("role") == "tool"
    ]
    return record


def copy_json(source: Path, target: Path, root: Path) -> None:
    value = sanitize(json.loads(source.read_text(encoding="utf-8")), root)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_jsonl(source: Path, target: Path, root: Path, compact_w6: bool) -> None:
    records = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if compact_w6:
            record = compact_w6_request(record)
        records.append(sanitize(record, root))
    target.write_text(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records),
        encoding="utf-8",
    )


def find_session(root: Path, session_id: str) -> Path:
    matches = list((root / "sessions" / "dsh-home" / "sessions").glob(f"*/{session_id}/session.jsonl"))
    if len(matches) != 1:
        raise ValueError(f"expected one session for {session_id}, found {len(matches)}")
    return matches[0]


def freeze_trace(root: Path, session_id: str, target: Path) -> None:
    source = find_session(root, session_id)
    records = [
        sanitize(json.loads(line), root)
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("type") in TRACE_TYPES
    ]
    target.write_text(
        "".join(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n" for item in records),
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    evidence = root / "evidence"
    if evidence.exists() and not args.refresh:
        parser.error("evidence already exists; pass --refresh to overwrite the known artifact set")
    evidence.mkdir(exist_ok=True)

    for group, names in GROUPS.items():
        group_root = evidence / group
        result_root = group_root / "results"
        result_root.mkdir(parents=True, exist_ok=True)
        for name in names:
            source_dir = root / "results" / name
            if not source_dir.is_dir():
                raise FileNotFoundError(source_dir)
            target_dir = result_root / name
            target_dir.mkdir(parents=True, exist_ok=True)
            for source in sorted(source_dir.iterdir()):
                if not source.is_file() or source.name == "server.log":
                    continue
                target = target_dir / source.name
                if source.suffix == ".json":
                    copy_json(source, target, root)
                elif source.suffix == ".jsonl":
                    copy_jsonl(source, target, root, compact_w6=group == "W6")
            session_id = TRACE_SESSION_IDS.get(name)
            if session_id:
                freeze_trace(root, session_id, target_dir / "dsh.trace.jsonl")

        if group == "W8":
            workspace_root = group_root / "workspaces"
            for name in names:
                target = workspace_root / name
                target.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / "workspaces" / name / "w8.log", target / "w8.log")

    revisions: dict[str, str] = {}
    for line in (root / "configs" / "revisions.env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            key, value = line.split("=", 1)
            revisions[key] = value
    manifest = {
        "format_version": 1,
        "scope": "minimal redacted input closure for deterministic W4-W8 summaries",
        "source_revisions": revisions,
        "redactions": [
            "benchmark absolute root -> $BENCH_ROOT",
            "OpenClaw temporary config directory -> $OPENCLAW_TEMP",
            "host name -> $HOST",
            "W6 request messages compacted to assistant tool calls and tool results",
        ],
        "omitted": ["API keys and HTTP headers", "server readiness logs", "full DSH sessions"],
    }
    (evidence / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    files = sorted(path for path in evidence.rglob("*") if path.is_file() and path.name != "MANIFEST.sha256")
    (evidence / "MANIFEST.sha256").write_text(
        "".join(f"{sha256(path)}  {path.relative_to(evidence)}\n" for path in files),
        encoding="utf-8",
    )
    print(f"froze {len(files)} evidence files under {evidence}")


if __name__ == "__main__":
    main()
