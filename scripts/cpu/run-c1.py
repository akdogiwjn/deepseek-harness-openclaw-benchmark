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


PERF_EVENTS = [
    "task-clock",
    "cycles",
    "instructions",
    "branches",
    "branch-misses",
    "cache-references",
    "cache-misses",
    "context-switches",
    "cpu-migrations",
    "page-faults",
]


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


def parse_perf(stderr: str) -> tuple[dict[str, float | None], dict[str, str]]:
    metrics: dict[str, float | None] = {}
    labels: dict[str, str] = {}
    wanted = set(PERF_EVENTS)
    for line in stderr.splitlines():
        fields = line.split(",")
        if len(fields) < 3:
            continue
        label = fields[2].strip()
        event = label.split(":", 1)[0]
        if event not in wanted:
            continue
        raw = fields[0].strip()
        try:
            metrics[event] = float(raw)
        except ValueError:
            metrics[event] = None
        labels[event] = label
    return metrics, labels


def run_sample(
    node: Path,
    fixture: Path,
    steps: int,
    payload_bytes: int,
    cpu: int | None,
    use_perf: bool,
) -> dict[str, Any]:
    command = [str(node), str(fixture), str(steps), str(payload_bytes)]
    if use_perf:
        command = [
            "perf", "stat", "-x,", "--no-big-num", "-e", ",".join(PERF_EVENTS), "--", *command
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
    perf, perf_event_labels = parse_perf(completed.stderr) if use_perf else ({}, {})
    derived: dict[str, float | None] = {}
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
        derived["internal_cpu_us_per_tool_step"] = fixture_result["timing"]["cpu_total_us"] / steps
        derived["internal_wall_ns_per_tool_step"] = fixture_result["timing"]["wall_ns"] / steps
        if instructions is not None:
            derived["process_instructions_per_tool_step"] = instructions / steps
        if cycles is not None:
            derived["process_cycles_per_tool_step"] = cycles / steps
    return {
        "fixture": fixture_result,
        "perf": perf,
        "perf_event_labels": perf_event_labels,
        "derived": derived,
    }


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


def perf_works() -> bool:
    perf = shutil.which("perf")
    if perf is None:
        return False
    completed = subprocess.run(
        [perf, "stat", "-x,", "-e", "cycles,instructions", "--", "true"],
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0 and "cycles" in completed.stderr


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
    parser.add_argument("--cpu", type=int, default=0, help="logical CPU to pin, or -1 to disable pinning")
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.payload_bytes < 1:
        parser.error("repeats and payload-bytes must be positive")

    root = Path(__file__).resolve().parents[2]
    node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts" / "cpu" / "c1-agent-loop.mjs"
    available = perf_works()
    if args.perf == "on" and not available:
        parser.error("perf was requested but the selected events are unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and available)
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
        "benchmark": "C1 in-process deterministic Agent Loop scaling",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "steps": args.steps,
            "repeats": args.repeats,
            "payload_bytes": args.payload_bytes,
            "randomization_seed": args.seed,
            "cpu_affinity": None if args.cpu < 0 else args.cpu,
            "perf_enabled": use_perf,
            "perf_events": PERF_EVENTS if use_perf else [],
            "observed_perf_event_labels": samples[0]["perf_event_labels"] if samples else {},
            "internal_scope": "prompt enqueue through agent idle; setup and teardown excluded",
            "perf_scope": "whole Node fixture process; startup, setup, measured turn, and teardown included",
            "context_policy": "one in-memory append-only Session whose derived context grows each tool step",
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
            "The Session context grows with tool steps; C1 does not isolate fixed-context loop cost.",
            "Whole-process perf counters include Node/V8 startup and Harness composition; slope estimates amortize that fixed intercept.",
            "No claim of cross-ISA instruction equivalence is made.",
            "A :u event label means the host restricted perf to user space; software scheduling counters may then read zero and must not be interpreted as absence of context switches.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__":
    main()
