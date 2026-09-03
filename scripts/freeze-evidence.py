#!/usr/bin/env python3
"""Freeze redacted behavioral and deterministic benchmark evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import socket
import subprocess
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
    "W9": ["w9-crash-003", "w9-replay-008"],
    "W10": ["w10-local-a-003", "w10-sandbox-b-004", "w10-local-aprime-003"],
}

BEHAVIORAL_PAIRS = {
    "W1": {
        "w1-pilot-001": {
            "deepseek_harness": "w1-dsh-001",
            "openclaw": "w1-openclaw-001",
        },
    },
    "W2": {
        # The first two attempts were infrastructure-invalid. The first valid
        # OpenClaw workspace retained the earlier numeric suffix, so record the
        # historical mapping explicitly instead of inferring it from pair ids.
        "w2-pilot-003": {"deepseek_harness": "w2-dsh-003", "openclaw": "w2-openclaw-002"},
        "w2-pilot-004": {"deepseek_harness": "w2-dsh-004", "openclaw": "w2-openclaw-003"},
        "w2-pilot-005": {"deepseek_harness": "w2-dsh-005", "openclaw": "w2-openclaw-004"},
        "w2-pilot-006": {"deepseek_harness": "w2-dsh-006", "openclaw": "w2-openclaw-005"},
        "w2-pilot-007": {"deepseek_harness": "w2-dsh-007", "openclaw": "w2-openclaw-006"},
    },
    "W3": {
        **{
            f"w3-pilot-{number:03d}": {
                "deepseek_harness": f"w3-dsh-{number:03d}",
                "openclaw": f"w3-openclaw-{number:03d}",
            }
            for number in range(1, 6)
        },
    },
}

TRACE_SESSION_IDS = {
    "w4-recovery-001": "dsh-w4-001",
    "w6-dsh-nonzero-001": "dsh-w6-dsh-nonzero-001",
    "w6-dsh-nonzero-002": "dsh-w6-dsh-nonzero-002",
    "w6-dsh-invalid-args-001": "dsh-w6-dsh-invalid-args-001",
    "w8-dsh-direct-01": "dsh-w8-dsh-direct-01",
    "w8-dsh-code-01": "dsh-w8-dsh-code-01",
}

TRACE_TYPES = {
    "assistant/message", "tool/call", "tool/result", "llm/retry", "turn/end",
    "tool/code-dispatch-start", "tool/code-dispatch",
}

TREE_IGNORES = {".git", ".pytest_cache", "__pycache__"}


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


def git_paths(workspace: Path, *args: str) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(workspace), *args, "-z"],
        check=True,
        capture_output=True,
    )
    return [item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]


def tree_sha256(root: Path) -> str:
    """Hash the copied baseline tree, including paths, file bytes, and symlink targets."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if any(part in TREE_IGNORES for part in relative.parts):
            continue
        encoded = relative.as_posix().encode("utf-8")
        if path.is_symlink():
            digest.update(b"L\0" + encoded + b"\0" + path.readlink().as_posix().encode("utf-8") + b"\n")
        elif path.is_file():
            executable = b"x" if path.stat().st_mode & 0o111 else b"-"
            digest.update(b"F" + executable + b"\0" + encoded + b"\0" + sha256(path).encode("ascii") + b"\n")
        elif path.is_dir():
            digest.update(b"D\0" + encoded + b"\n")
    return digest.hexdigest()


def freeze_workspace_overlay(workspace: Path, target: Path) -> dict[str, Any]:
    changed = git_paths(workspace, "diff", "--name-only", "HEAD")
    untracked = git_paths(workspace, "ls-files", "--others", "--exclude-standard")
    paths = sorted(set(changed + untracked))
    deleted: list[str] = []
    hashes: dict[str, str] = {}
    files_root = target / "files"
    for relative in paths:
        source = workspace / relative
        if not source.exists():
            deleted.append(relative)
            continue
        if not source.is_file():
            raise ValueError(f"behavioral evidence supports files only: {source}")
        destination = files_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        hashes[relative] = sha256(destination)
    return {
        "workspace": workspace.name,
        "changed_or_untracked_files": paths,
        "deleted_files": deleted,
        "file_sha256": hashes,
    }


def freeze_behavioral_groups(root: Path, evidence: Path, refresh: bool) -> None:
    for group, pairs in BEHAVIORAL_PAIRS.items():
        group_slug = group.lower()
        template_relative = Path("workspaces") / f"{group_slug}-template"
        verifier_relative = Path("verifiers") / f"verify_{group_slug}.py"
        template = root / template_relative
        verifier = root / verifier_relative
        group_root = evidence / group
        if refresh and group_root.exists():
            shutil.rmtree(group_root)
        for pair_name, workspaces in pairs.items():
            source_summary = root / "results" / pair_name / "summary.json"
            if not source_summary.is_file():
                raise FileNotFoundError(source_summary)
            target = group_root / "results" / pair_name
            target.mkdir(parents=True, exist_ok=True)
            copy_json(source_summary, target / "summary.json", root)
            workspace_manifest = {
                "schema_version": 2,
                "baseline": {
                    "template": template_relative.as_posix(),
                    "template_tree_sha256": tree_sha256(template),
                    "verifier": verifier_relative.as_posix(),
                    "verifier_sha256": sha256(verifier),
                },
                "workspaces": {
                    runtime: freeze_workspace_overlay(
                        root / "workspaces" / workspace_name,
                        target / "workspaces" / runtime,
                    )
                    for runtime, workspace_name in workspaces.items()
                },
            }
            (target / "workspace-manifest.json").write_text(
                json.dumps(workspace_manifest, ensure_ascii=False, indent=2) + "\n",
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

    freeze_behavioral_groups(root, evidence, args.refresh)

    for group, names in GROUPS.items():
        group_root = evidence / group
        if args.refresh and group_root.exists():
            shutil.rmtree(group_root)
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
                if group == "W9" and source.name not in {
                    "case.json", "crash-prefix.jsonl", "resumed-session.jsonl",
                    "resume-observation.json", "recorded-session.jsonl", "replayed-session.jsonl",
                }:
                    continue
                target = target_dir / source.name
                if source.suffix == ".json":
                    copy_json(source, target, root)
                elif source.suffix == ".jsonl":
                    copy_jsonl(source, target, root, compact_w6=group == "W6" or (group == "W10" and source.name == "requests.jsonl"))
            session_id = TRACE_SESSION_IDS.get(name)
            if session_id:
                freeze_trace(root, session_id, target_dir / "dsh.trace.jsonl")

        if group == "W8":
            workspace_root = group_root / "workspaces"
            for name in names:
                target = workspace_root / name
                target.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / "workspaces" / name / "w8.log", target / "w8.log")
        if group == "W9":
            copy_json(root / "results" / "w9-fork-001.json", group_root / "w9-fork-001.json", root)
        if group == "W10":
            for name in names:
                workspace = root / "workspaces" / name
                state = {
                    "inside": (workspace / "workspace" / "inside.txt").read_text(encoding="utf-8").strip(),
                    "outside": (workspace / "outside" / "outside.txt").read_text(encoding="utf-8").strip(),
                }
                (group_root / "results" / name / "workspace-state.json").write_text(
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )

    revisions: dict[str, str] = {}
    for line in (root / "configs" / "revisions.env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            key, value = line.split("=", 1)
            revisions[key] = value
    manifest = {
        "format_version": 2,
        "scope": "final-workspace/verifier closure for W1-W3 plus minimal redacted input closure for deterministic W4-W10 summaries",
        "source_revisions": revisions,
        "redactions": [
            "benchmark absolute root -> $BENCH_ROOT",
            "OpenClaw temporary config directory -> $OPENCLAW_TEMP",
            "host name -> $HOST",
            "W6 request messages compacted to assistant tool calls and tool results",
        ],
        "omitted": [
            "API keys and HTTP headers",
            "server readiness logs",
            "full DSH sessions",
            "W1-W3 provider transcripts and reasoning; normalized summaries and exact changed-file overlays are retained",
        ],
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
