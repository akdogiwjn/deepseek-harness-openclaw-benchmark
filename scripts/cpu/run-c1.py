#!/usr/bin/env python3
"""Run and summarize the C1 in-process Agent Loop CPU scaling fixture."""

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


def parse_steps(raw: str) -> list[int]:
    values = [int(item) for item in raw.split(",")]
    if not values or any(item < 0 for item in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("steps must be unique non-negative comma-separated integers")
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
    steps: int,
    payload_bytes: int,
    cpu: int | None,
    use_perf: bool,
    perf_events: list[str],
    warm_turns: int = 0,
    warmup_turns: int = 1,
) -> dict[str, Any]:
    warm = warm_turns > 0
    command = [str(node), str(fixture), str(steps), str(payload_bytes)]
    if warm:
        command += [str(warm_turns), str(warmup_turns)]
    if use_perf:
        command = [
            "perf", "stat", "-x,", "--no-big-num", "-e", ",".join(perf_events), "--", *command
        ]
    if cpu is not None:
        command = ["taskset", "-c", str(cpu), *command]
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=300)
    if completed.returncode != 0:
        raise RuntimeError(
            f"C1 sample failed for steps={steps}: exit={completed.returncode}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        raise RuntimeError(f"C1 sample produced no JSON for steps={steps}")
    fixture_result = json.loads(stdout_lines[-1])
    warm_data: dict[str, Any] | None = None
    if warm:
        turns = fixture_result["turns"]
        wall = [t["wall_ns"] for t in turns]
        cpu_total = [t["cpu_total_us"] for t in turns]
        cpu_user = [t["cpu_user_us"] for t in turns]
        warm_data = {"wall_ns": wall, "cpu_total_us": cpu_total, "cpu_user_us": cpu_user}
        fixture_result = {
            "tool_steps": steps,
            "payload_bytes": payload_bytes,
            "measured_turns": warm_turns,
            "warmup_turns": warmup_turns,
            "timing": {
                "wall_ns": statistics.median(wall),
                "cpu_total_us": statistics.median(cpu_total),
                "cpu_user_us": statistics.median(cpu_user),
            },
            "resources": fixture_result["resources"],
        }
    perf, perf_event_labels = parse_perf(completed.stderr) if use_perf else ({}, {})
    derived: dict[str, float | None] = {}
    if steps > 0:
        derived["internal_cpu_us_per_tool_step"] = fixture_result["timing"]["cpu_total_us"] / steps
        derived["internal_wall_ns_per_tool_step"] = fixture_result["timing"]["wall_ns"] / steps
    if not warm:
        instructions = perf.get("instructions")
        cycles = perf.get("cycles")
        branches = perf.get("branches")
        branch_misses = perf.get("branch-misses")
        cache_misses = perf.get("cache-misses")
        if instructions and cycles:
            derived["ipc"] = instructions / cycles
        if instructions and branch_misses is not None:
            derived["branch_mpki"] = branch_misses / instructions * 1000
        if instructions and cache_misses is not None:
            derived["cache_mpki"] = cache_misses / instructions * 1000
        if steps > 0:
            if instructions is not None:
                derived["process_instructions_per_tool_step"] = instructions / steps
            if cycles is not None:
                derived["process_cycles_per_tool_step"] = cycles / steps
    sample = {
        "fixture": fixture_result,
        "derived": derived,
        "perf_event_labels": perf_event_labels,
    }
    if warm:
        sample["perf"] = {}
        sample["diagnostic_whole_process_perf"] = perf
    else:
        sample["perf"] = perf
    if warm_data is not None:
        sample["warm_turns"] = warm_data
    return sample


def numeric_path(sample: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = sample
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def aggregate(samples: list[dict[str, Any]], steps: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = {
        "internal_wall_ns": ("fixture", "timing", "wall_ns"),
        "internal_cpu_total_us": ("fixture", "timing", "cpu_total_us"),
        "max_rss_kb": ("fixture", "resources", "max_rss_kb"),
        "task_clock_ms": ("perf", "task-clock"),
        "cycles": ("perf", "cycles"),
        "instructions": ("perf", "instructions"),
        "branches": ("perf", "branches"),
        "branch_misses": ("perf", "branch-misses"),
        "cache_references": ("perf", "cache-references"),
        "cache_misses": ("perf", "cache-misses"),
        "context_switches": ("perf", "context-switches"),
        "page_faults": ("perf", "page-faults"),
        "ipc": ("derived", "ipc"),
        "branch_mpki": ("derived", "branch_mpki"),
        "cache_mpki": ("derived", "cache_mpki"),
    }
    by_steps: dict[str, Any] = {}
    medians: dict[str, list[tuple[float, float]]] = {name: [] for name in paths}
    for count in steps:
        group = [sample for sample in samples if sample["fixture"]["tool_steps"] == count]
        row: dict[str, Any] = {"samples": len(group)}
        for name, path in paths.items():
            values = [value for sample in group if (value := numeric_path(sample, path)) is not None]
            if not values:
                row[name] = None
                continue
            median = statistics.median(values)
            row[name] = {"median": median, "min": min(values), "max": max(values)}
            medians[name].append((float(count), median))
        by_steps[str(count)] = row

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
        intercept = y_mean - slope * x_mean
        fits[name] = {"intercept": intercept, "per_tool_step_slope": slope}
    return by_steps, fits


def lscpu_metadata() -> dict[str, str]:
    completed = subprocess.run(["lscpu", "-J"], text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        return {}
    rows = json.loads(completed.stdout).get("lscpu", [])
    values = {str(row.get("field", "")).rstrip(":"): str(row.get("data", "")) for row in rows}
    keys = [
        "Architecture", "Vendor ID", "Model name", "CPU(s)", "Thread(s) per core",
        "Core(s) per socket", "Socket(s)", "NUMA node(s)", "L1d cache", "L1i cache",
        "L2 cache", "L3 cache", "CPU max MHz", "CPU min MHz",
    ]
    return {key: values[key] for key in keys if values.get(key)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=parse_steps, default=parse_steps("0,1,4,16,64,256"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--payload-bytes", type=int, default=64)
    parser.add_argument("--warm-turns", type=int, default=0, help="measured turns per step in a single warm process")
    parser.add_argument("--warmup-turns", type=int, default=1, help="unmeasured warmup turns before measurement")
    parser.add_argument("--cpu", type=int, default=0, help="logical CPU to pin, or -1 to disable pinning")
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.payload_bytes < 1 or args.warm_turns < 0 or args.warmup_turns < 0:
        parser.error("repeats and payload-bytes must be positive; warm-turns and warmup-turns must be non-negative")

    root = Path(__file__).resolve().parents[2]
    node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts" / "cpu" / "c1-agent-loop.mjs"
    mode, perf_events = probe_perf()
    if args.perf == "on" and mode == "off":
        parser.error("perf was requested but the selected events are unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and mode != "off")
    schedule = [count for count in args.steps for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(schedule)
    samples = []
    for index, count in enumerate(schedule, start=1):
        sample = run_sample(
            node=node,
            fixture=fixture,
            steps=count,
            payload_bytes=args.payload_bytes,
            cpu=None if args.cpu < 0 else args.cpu,
            use_perf=use_perf,
            perf_events=perf_events,
            warm_turns=args.warm_turns,
            warmup_turns=args.warmup_turns,
        )
        sample["sample_index"] = index
        samples.append(sample)
        print(
            f"[C1 {index}/{len(schedule)}] steps={count} "
            f"cpu_us={sample['fixture']['timing']['cpu_total_us']} "
            f"cycles={sample['perf'].get('cycles')}",
            flush=True,
        )

    aggregates, fits = aggregate(samples, args.steps)
    result = {
        "benchmark": "C1-warm fixed-context Agent Loop scaling" if args.warm_turns > 0 else "C1 in-process deterministic Agent Loop scaling",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "steps": args.steps,
            "repeats": args.repeats,
            "payload_bytes": args.payload_bytes,
            "warm_turns": args.warm_turns,
            "warmup_turns": args.warmup_turns,
            "randomization_seed": args.seed,
            "cpu_affinity": None if args.cpu < 0 else args.cpu,
            "perf_enabled": use_perf,
            "perf_mode": mode,
            "perf_events": perf_events if use_perf else [],
            "observed_perf_event_labels": samples[0]["perf_event_labels"] if samples else {},
            "internal_scope": "prompt enqueue through agent idle; setup and teardown excluded",
            "perf_scope": "whole Node fixture process; startup, setup, measured turn, and teardown included",
            "context_policy": (
                "one in-memory append-only Session whose derived context grows each tool step"
                if args.warm_turns == 0 else
                "fresh Session per turn (fixed context); each step median taken over warm turns"
            ),
        },
        "host": {
            "platform": platform.platform(),
            "kernel_release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
            "lscpu": lscpu_metadata(),
            "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()
            if Path("/proc/sys/kernel/perf_event_paranoid").exists() else None,
            "node": subprocess.run([str(node), "--version"], text=True, capture_output=True, check=True).stdout.strip(),
            "perf": subprocess.run(["perf", "--version"], text=True, capture_output=True, check=False).stdout.strip()
            if shutil.which("perf") else None,
        },
        "aggregates": aggregates,
        "linear_fits_over_step_medians": fits,
        "samples": samples,
        "limitations": [
            "This is an in-process adapter microbenchmark, not an HTTP/SSE provider path.",
            (
                "The Session context grows with tool steps; C1 does not isolate fixed-context loop cost."
                if args.warm_turns == 0 else
                "Warm mode uses a fresh Session per turn, so per-turn context is fixed; only the steady-state turn cost is measured."
            ),
            "Whole-process perf counters include Node/V8 startup and Harness composition; slope estimates amortize that fixed intercept.",
            "No claim of cross-ISA instruction equivalence is made.",
            "cycles:u/cycles:k and instructions:u/instructions:k are sampled directly and summed into cycles/instructions with derived *_kernel_ratio; a perf restriction to user space omits the :k fields.",
            "Warm mode still includes per-step process startup in whole-process perf; only the internal prompt-window timing is steady-state.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__":
    main()
