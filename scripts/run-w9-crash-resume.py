#!/usr/bin/env python3
"""Supervise a real sdk-minimal crash and resume the same persisted session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


def records(path: Path) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            output.append(value)
    return output


def session_file(root: Path, session_id: str) -> Path | None:
    matches = list((root / "sessions" / "dsh-home" / "sessions").glob(
        f"*/{session_id}/session.jsonl"
    ))
    if len(matches) > 1:
        raise RuntimeError(f"multiple session logs found for {session_id}")
    return matches[0] if matches else None


def find_crash_call(events: list[dict[str, Any]]) -> tuple[str | None, bool]:
    call_id: str | None = None
    for event in events:
        if event.get("type") != "tool/call":
            continue
        data = event.get("data", {})
        if "W9_EFFECT_002_STARTED" in str(data.get("arguments", "")):
            call_id = str(data.get("callId"))
    if call_id is None:
        return None, False
    has_result = any(
        event.get("type") == "tool/result"
        and event.get("data", {}).get("message", {}).get("source", {}).get("callId") == call_id
        for event in events
    )
    return call_id, has_result


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("session_id")
    parser.add_argument("result_dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    workspace = args.workspace.resolve()
    result_dir = args.result_dir.resolve()
    result_dir.mkdir(parents=True, exist_ok=False)
    command = [
        str(root / "scripts" / "run-dsh-minimal.sh"),
        str(workspace),
        args.session_id,
        "Execute the deterministic provider instructions until the task completes.",
    ]

    started = time.monotonic()
    crashed = subprocess.Popen(
        command,
        cwd=root,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    deadline = time.monotonic() + 45
    log_path: Path | None = None
    crash_call_id: str | None = None
    while time.monotonic() < deadline:
        if crashed.poll() is not None:
            stdout, stderr = crashed.communicate()
            raise RuntimeError(f"runtime exited before crash point: {stdout}\n{stderr}")
        log_path = session_file(root, args.session_id)
        effects = (workspace / "effects.log").read_text(encoding="utf-8").splitlines() \
            if (workspace / "effects.log").exists() else []
        if log_path is not None:
            crash_call_id, has_result = find_crash_call(records(log_path))
            if crash_call_id is not None and not has_result and "W9_EFFECT_002_STARTED" in effects:
                break
        time.sleep(0.05)
    else:
        os.killpg(crashed.pid, signal.SIGKILL)
        crashed.wait()
        raise TimeoutError("did not observe durable dangling tool/call crash point")

    assert log_path is not None and crash_call_id is not None
    crash_bytes = log_path.read_bytes()
    shutil.copyfile(log_path, result_dir / "crash-prefix.jsonl")
    os.killpg(crashed.pid, signal.SIGKILL)
    crash_stdout, crash_stderr = crashed.communicate(timeout=10)
    crash_seconds = time.monotonic() - started

    resume_started = time.monotonic()
    resumed = subprocess.run(
        [
            str(Path(os.environ["BENCH_NODE_DIR"]) / "bin" / "node"),
            str(root / "scripts" / "resume-w9-session.mjs"),
            args.session_id,
            str(root / "sessions" / "dsh-home" / "sessions"),
            str(result_dir / "resume-observation.json"),
        ],
        cwd=root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    resume_seconds = time.monotonic() - resume_started
    if resumed.returncode != 0:
        raise RuntimeError(f"resume failed: {resumed.stdout}\n{resumed.stderr}")

    final_bytes = log_path.read_bytes()
    final_events = records(log_path)
    event_types = [event.get("type") for event in final_events[1:]]
    seqs = [event.get("seq") for event in final_events[1:]]
    synthetic = [
        event for event in final_events
        if event.get("type") == "tool/result"
        and event.get("data", {}).get("message", {}).get("source", {}).get("callId") == crash_call_id
    ]
    interrupted = [
        event for event in final_events
        if event.get("type") == "turn/end"
        and event.get("data", {}).get("reason", {}).get("kind") == "interrupted"
    ]
    effects = (workspace / "effects.log").read_text(encoding="utf-8").splitlines()
    resume_json = json.loads(resumed.stdout.strip().splitlines()[-1])
    resume_observation = json.loads((result_dir / "resume-observation.json").read_text(encoding="utf-8"))
    checks = {
        "committed_prefix_byte_identical": final_bytes.startswith(crash_bytes),
        "seq_contiguous": seqs == list(range(len(seqs))),
        "session_end_seed_present": "session/end-seed" in event_types,
        "interrupted_turn_closed": len(interrupted) == 1,
        "synthetic_unknown_result": len(synthetic) == 1
        and synthetic[0].get("data", {}).get("error", {}).get("code") == "TOOL_OUTCOME_UNKNOWN",
        "effect_001_once": effects.count("W9_EFFECT_001") == 1,
        "effect_002_started_once": effects.count("W9_EFFECT_002_STARTED") == 1,
        "resume_completed": resume_json.get("final_response") == "COMPLETED_W9_CRASH_RESUME",
        "crash_history_visible_to_resumed_model": resume_json.get("prior_history_visible") is True,
    }
    if not all(checks.values()):
        raise RuntimeError(f"W9 crash/resume verification failed: {checks}")

    shutil.copyfile(log_path, result_dir / "resumed-session.jsonl")
    (result_dir / "runtime.raw.json").write_text(json.dumps({
        "crash": {
            "returncode": crashed.returncode,
            "wall_seconds": crash_seconds,
            "stdout": crash_stdout,
            "stderr": crash_stderr,
        },
        "resume": {
            "returncode": resumed.returncode,
            "wall_seconds": resume_seconds,
            "stdout": resumed.stdout,
            "stderr": resumed.stderr,
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "scenario": "W9-A crash/resume",
        "session_id": args.session_id,
        "crash_call_id": crash_call_id,
        "crash_prefix_sha256": sha256(crash_bytes),
        "final_session_sha256": sha256(final_bytes),
        "event_count_before_crash": len(records(result_dir / "crash-prefix.jsonl")) - 1,
        "event_count_after_resume": len(final_events) - 1,
        "synthetic_error_code": synthetic[0]["data"]["error"]["code"],
        "event_order_tail": event_types[-14:],
        "effects": effects,
        "resumed_model_calls": resume_json.get("model_calls"),
        "resume_seed_event_types": resume_observation["before_followup_event_types"],
        "checks": checks,
    }
    (result_dir / "case.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    run()
