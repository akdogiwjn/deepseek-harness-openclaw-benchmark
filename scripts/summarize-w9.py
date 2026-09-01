#!/usr/bin/env python3
"""Combine and validate the three deterministic W9 session-semantics cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def all_checks(value: dict[str, Any], label: str) -> None:
    failed = [name for name, passed in value.get("checks", {}).items() if passed is not True]
    if failed:
        raise ValueError(f"{label} failed checks: {failed}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("crash_dir", type=Path)
    parser.add_argument("fork_json", type=Path)
    parser.add_argument("replay_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    crash = load(args.crash_dir / "case.json")
    fork = load(args.fork_json)
    replay = load(args.replay_dir / "case.json")
    all_checks(crash, "W9-A")
    all_checks(fork, "W9-B")
    all_checks(replay, "W9-C")
    if crash.get("synthetic_error_code") != "TOOL_OUTCOME_UNKNOWN":
        raise ValueError("W9-A did not repair the durable tool/call as outcome unknown")
    crash_rows = load_jsonl(args.crash_dir / "crash-prefix.jsonl")
    resumed_rows = load_jsonl(args.crash_dir / "resumed-session.jsonl")
    if resumed_rows[:len(crash_rows)] != crash_rows:
        raise ValueError("W9-A committed crash prefix was not preserved")
    resumed_events = resumed_rows[1:]
    if [event.get("seq") for event in resumed_events] != list(range(len(resumed_events))):
        raise ValueError("W9-A resumed sequence numbers are not contiguous")
    call_id = crash.get("crash_call_id")
    repair_result = next((
        event for event in resumed_events
        if event.get("type") == "tool/result"
        and event.get("data", {}).get("message", {}).get("source", {}).get("callId") == call_id
    ), None)
    if repair_result is None or repair_result.get("data", {}).get("error", {}).get("code") != "TOOL_OUTCOME_UNKNOWN":
        raise ValueError("W9-A frozen log lacks the expected synthetic result")
    repair_index = resumed_events.index(repair_result)
    later_types = [event.get("type") for event in resumed_events[repair_index + 1:]]
    try:
        step_offset = later_types.index("step/end")
        turn_offset = next(
            index for index, event in enumerate(resumed_events[repair_index + 1:])
            if event.get("type") == "turn/end"
            and event.get("data", {}).get("reason", {}).get("kind") == "interrupted"
        )
        seed_offset = later_types.index("session/end-seed")
    except (ValueError, StopIteration) as error:
        raise ValueError("W9-A frozen log lacks ordered repair boundaries") from error
    if not step_offset < turn_offset < seed_offset:
        raise ValueError("W9-A repair/end-seed ordering is incorrect")
    if fork.get("open_turn_rejection", {}).get("code") != "OPEN_TURN":
        raise ValueError("W9-B open-turn negative case did not reject")
    if replay.get("provider_requests_after_replay") != replay.get("recorded_model_calls"):
        raise ValueError("W9-C contacted the recording provider during replay")
    output = {
        "task": "W9 DSH session state semantics",
        "scope": "DSH white-box mechanism cases; not a DSH-versus-OpenClaw comparison",
        "crash_resume": crash,
        "fork": fork,
        "llm_replay": replay,
        "notes": [
            "W9-A uses sdk-minimal only to create the crash, then invokes the official ctx.agents.resume() path because the Python SDK server creates rather than cold-resumes sessions after process restart.",
            "W9-C uses a completed session; LLM replay does not reproduce crash scheduling or external-world rollback.",
            "Side effects execute independently in fresh recording and replay workspaces.",
        ],
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
