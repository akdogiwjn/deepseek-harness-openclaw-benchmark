#!/usr/bin/env python3
"""Run and summarize C2 Session/Event Log event-count scaling."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from perf_utils import parse_perf, probe_perf

OPERATIONS = ["append", "derive_messages", "fork_prefix", "jsonl_write", "jsonl_warm_load"]


def parse_counts(raw: str) -> list[int]:
    values = [int(item) for item in raw.split(",")]
    if not values or any(item < 1 for item in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("turns must be unique positive comma-separated integers")
    return values


def default_node(root: Path) -> Path:
    revisions = dict(
        line.split("=", 1)
        for line in (root / "configs" / "revisions.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(
        platform.machine().lower()
    )
    if arch is None:
        raise RuntimeError(f"unsupported architecture: {platform.machine()}")
    return root / f"node-v{revisions['NODE_VERSION']}-linux-{arch}" / "bin" / "node"


def run_sample(
    node: Path,
    fixture: Path,
    turns: int,
    payload_bytes: int,
    cpu: int | None,
    use_perf: bool,
    perf_events: list[str],
) -> dict[str, Any]:
    command = [str(node), str(fixture), str(turns), str(payload_bytes)]
    if use_perf:
        command = ["perf", "stat", "-x,", "--no-big-num", "-e", ",".join(perf_events), "--", *command]
    if cpu is not None:
        command = ["taskset", "-c", str(cpu), *command]
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"C2 sample failed for turns={turns}: exit={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    fixture_result = json.loads(lines[-1])
    perf, labels = parse_perf(result.stderr) if use_perf else ({}, {})
    instructions = perf.get("instructions")
    cycles = perf.get("cycles")
    derived: dict[str, float] = {}
    if instructions and cycles:
        derived["ipc"] = instructions / cycles
    if instructions and perf.get("cache-misses") is not None:
        derived["cache_mpki"] = perf["cache-misses"] / instructions * 1000
    if instructions and perf.get("branch-misses") is not None:
        derived["branch_mpki"] = perf["branch-misses"] / instructions * 1000
    return {"fixture": fixture_result, "perf": perf, "perf_event_labels": labels, "derived": derived}


def value_at(sample: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = sample
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def aggregate(samples: list[dict[str, Any]], turns: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    paths: dict[str, tuple[str, ...]] = {
        "log_bytes": ("fixture", "log_bytes"),
        "max_rss_kb": ("fixture", "resources", "max_rss_kb"),
        "cycles": ("perf", "cycles"),
        "instructions": ("perf", "instructions"),
        "ipc": ("derived", "ipc"),
        "cache_mpki": ("derived", "cache_mpki"),
        "branch_mpki": ("derived", "branch_mpki"),
    }
    for operation in OPERATIONS:
        paths[f"{operation}_wall_ns"] = ("fixture", "operations", operation, "wall_ns")
        paths[f"{operation}_cpu_us"] = ("fixture", "operations", operation, "cpu_total_us")

    rows: dict[str, Any] = {}
    medians: dict[str, list[tuple[float, float]]] = {name: [] for name in paths}
    for count in turns:
        group = [sample for sample in samples if sample["fixture"]["turns"] == count]
        row: dict[str, Any] = {
            "turns": count,
            "events": count * 3,
            "samples": len(group),
        }
        for name, path in paths.items():
            values = [value for sample in group if (value := value_at(sample, path)) is not None]
            if not values:
                row[name] = None
                continue
            median = statistics.median(values)
            row[name] = {"median": median, "min": min(values), "max": max(values)}
            medians[name].append((float(count * 3), median))
        rows[str(count)] = row

    fits: dict[str, Any] = {}
    for name, points in medians.items():
        if len(points) < 2:
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        x_mean = statistics.fmean(xs)
        y_mean = statistics.fmean(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        if denominator == 0:
            continue
        slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
        fits[name] = {
            "intercept": y_mean - slope * x_mean,
            "per_event_slope": slope,
        }
    return rows, fits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=parse_counts, default=parse_counts("1,10,100,1000,5000"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--payload-bytes", type=int, default=256)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.payload_bytes < 1:
        parser.error("repeats and payload-bytes must be positive")

    root = Path(__file__).resolve().parents[2]
    node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts" / "cpu" / "c2-session-primitives.mjs"
    mode, perf_events = ("off", []) if args.perf == "off" else probe_perf()
    if args.perf == "on" and mode == "off":
        parser.error("perf was requested but unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and mode != "off")
    schedule = [count for count in args.turns for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(schedule)
    samples = []
    for index, count in enumerate(schedule, start=1):
        sample = run_sample(
            node, fixture, count, args.payload_bytes,
            None if args.cpu < 0 else args.cpu, use_perf, perf_events,
        )
        sample["sample_index"] = index
        samples.append(sample)
        operations = sample["fixture"]["operations"]
        print(
            f"[C2 {index}/{len(schedule)}] turns={count} events={count * 3} "
            f"derive_us={operations['derive_messages']['cpu_total_us']} "
            f"load_us={operations['jsonl_warm_load']['cpu_total_us']}",
            flush=True,
        )

    aggregates, fits = aggregate(samples, args.turns)
    result = {
        "benchmark": "C2 append-only Session/Event Log event-count scaling",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "turns": args.turns,
            "events_per_turn": 3,
            "event_counts": [count * 3 for count in args.turns],
            "repeats": args.repeats,
            "payload_bytes": args.payload_bytes,
            "randomization_seed": args.seed,
            "cpu_affinity": None if args.cpu < 0 else args.cpu,
            "persistence": "uncompressed JSONL, packChunks=false",
            "load_cache_state": "fresh persistence backend, warm host page cache",
            "perf_enabled": use_perf,
            "perf_mode": mode,
            "perf_events": perf_events if use_perf else [],
            "observed_perf_event_labels": samples[0]["perf_event_labels"] if samples else {},
        },
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "node": subprocess.run([str(node), "--version"], text=True, capture_output=True, check=True).stdout.strip(),
            "perf": subprocess.run(["perf", "--version"], text=True, capture_output=True, check=False).stdout.strip()
            if shutil.which("perf") else None,
            "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()
            if Path("/proc/sys/kernel/perf_event_paranoid").exists() else None,
        },
        "aggregates": aggregates,
        "linear_fits_over_event_count_medians": fits,
        "samples": samples,
        "limitations": [
            "The event-count sweep fixes payload size at 256 bytes; payload-size scaling is a separate C2 condition.",
            "deriveMessages sees completed user-only turns, not tool-heavy or chunk-heavy event shapes.",
            "JSONL load uses a fresh backend but warm host page cache; this is not a cold-storage measurement.",
            "Whole-process perf includes Node/V8 startup, setup, all five primitives, cleanup, and teardown.",
            "cycles:u/cycles:k and instructions:u/instructions:k are sampled directly and summed into cycles/instructions with derived *_kernel_ratio; a perf restriction to user space omits the :k fields.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__":
    main()
