#!/usr/bin/env python3
"""Aggregate normalized pair summaries without assuming token equivalence."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def describe(values: list[float | int]) -> dict:
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("summaries", nargs="+", type=Path)
    args = parser.parse_args()
    pairs = [json.loads(path.read_text(encoding="utf-8")) for path in args.summaries]

    output: dict = {
        "task": pairs[0]["task"],
        "model": pairs[0]["model"],
        "paired_attempts": len(pairs),
        "deepseek_harness": {},
        "openclaw": {},
        "notes": [
            "Success means the external hidden verifier passed.",
            "Wall-time distributions include every attempted runtime invocation, including runtime and verifier failures.",
            "Provider/runtime token counters are reported separately and are not treated as equivalent."
        ],
    }
    mappings = {
        "deepseek_harness": {
            "interaction_steps": "model_steps",
            "input": "input",
            "output": "output",
            "cache_read": "cache_read",
            "reasoning": "reasoning",
        },
        "openclaw": {
            "interaction_steps": "assistant_turns",
            "input": "input",
            "output": "output",
            "cache_read": "cacheRead",
            "reasoning": "reasoningTokens",
        },
    }
    for runtime, mapping in mappings.items():
        rows = [pair[runtime] for pair in pairs]
        successful = [row for row in rows if row["verifier_passed"]]
        output[runtime] = {
            "runtime_completed": sum(row["valid"] for row in rows),
            "successes": len(successful),
            "attempts": len(rows),
            "success_rate": len(successful) / len(rows),
            "wall_seconds": describe([row["wall_seconds"] for row in rows]),
            "successful_wall_seconds": describe([row["wall_seconds"] for row in successful]) if successful else None,
            "interaction_steps": describe([row[mapping["interaction_steps"]] for row in rows]),
            "tool_calls": describe([row["tool_calls"] for row in rows]),
            "runtime_status_counts": dict(sorted(Counter(row.get("runtime_status", "unknown") for row in rows).items())),
            "runtime_error_kinds": dict(
                sorted(
                    Counter(
                        error["kind"]
                        for row in rows
                        if isinstance((error := row.get("runtime_error")), dict) and error.get("kind")
                    ).items()
                )
            ),
            "usage": {
                key: describe([row["usage"][source] for row in rows])
                for key, source in mapping.items()
                if key != "interaction_steps"
            },
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
