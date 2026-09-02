#!/usr/bin/env python3
"""Run and summarize C4 shell lifecycle scaling."""

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


CONDITIONS = ["dsh-managed", "raw-oneshot", "persistent"]
_PERF_SPLIT_NAMES = frozenset(("cycles", "instructions"))
PERF_EVENTS = [
    "task-clock", "cycles:u", "cycles:k", "instructions:u", "instructions:k", "branches", "branch-misses",
    "cache-references", "cache-misses", "context-switches", "cpu-migrations", "page-faults",
]
PERF_EVENTS_USER_ONLY = [
    "task-clock", "cycles:u", "instructions:u", "branches", "branch-misses",
    "cache-references", "cache-misses", "context-switches", "cpu-migrations", "page-faults",
]


def parse_counts(raw: str) -> list[int]:
    values = [int(item) for item in raw.split(",")]
    if not values or any(item < 1 for item in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("counts must be unique positive comma-separated integers")
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


def perf_mode() -> str:
    perf = shutil.which("perf")
    if perf is None:
        return "off"
    for mode, events, marker in (
        ("full", PERF_EVENTS, "cycles:k"),
        ("user-only", PERF_EVENTS_USER_ONLY, "cycles:u"),
    ):
        completed = subprocess.run(
            [perf, "stat", "-x,", "-e", ",".join(events), "--", "true"],
            text=True, capture_output=True, check=False,
        )
        if completed.returncode == 0 and marker in completed.stderr:
            return mode
    return "off"


def parse_perf(stderr: str) -> tuple[dict[str, float | None], dict[str, str]]:
    metrics: dict[str, float | None] = {}
    labels: dict[str, str] = {}
    base_names = {
        "task-clock", "branches", "branch-misses", "cache-references", "cache-misses",
        "context-switches", "cpu-migrations", "page-faults",
    } | set(_PERF_SPLIT_NAMES)
    for line in stderr.splitlines():
        fields = line.split(",")
        if len(fields) < 3:
            continue
        label = fields[2].strip()
        base = label.split(":", 1)[0]
        if base not in base_names:
            continue
        key = label.replace(":", "_") if base in _PERF_SPLIT_NAMES else base
        try:
            metrics[key] = float(fields[0].strip())
        except ValueError:
            metrics[key] = None
        labels[key] = label
    for base in _PERF_SPLIT_NAMES:
        user = metrics.get(f"{base}_u")
        kernel = metrics.get(f"{base}_k")
        if user is not None:
            total = user + (kernel or 0.0)
            metrics[base] = total
            if kernel is not None and total:
                metrics[f"{base}_kernel_ratio"] = kernel / total
    return metrics, labels


def run_sample(
    node: Path, fixture: Path, condition: str, count: int, cpu: int | None, use_perf: bool,
    perf_events: list[str],
) -> dict[str, Any]:
    command = [str(node), str(fixture), condition, str(count)]
    if use_perf:
        command = ["perf", "stat", "-x,", "--no-big-num", "-e", ",".join(perf_events), "--", *command]
    if cpu is not None:
        command = ["taskset", "-c", str(cpu), *command]
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"C4 sample failed for {condition}/{count}: exit={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    fixture_result = json.loads([line for line in result.stdout.splitlines() if line.strip()][-1])
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
    for name, value in perf.items():
        if value is not None:
            derived[f"{name}_per_operation"] = value / count
    return {"fixture": fixture_result, "perf": perf, "perf_event_labels": labels, "derived": derived}


def value_at(sample: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = sample
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def summarize(samples: list[dict[str, Any]], counts: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = {
        "wall_ns": ("fixture", "measurement", "wall_ns"),
        "wall_ns_per_operation": ("fixture", "measurement", "wall_ns_per_operation"),
        "controller_cpu_us": ("fixture", "measurement", "controller_cpu_total_us"),
        "controller_cpu_us_per_operation": ("fixture", "measurement", "controller_cpu_us_per_operation"),
        "max_rss_kb": ("fixture", "resources", "max_rss_kb"),
        "cycles": ("perf", "cycles"),
        "instructions": ("perf", "instructions"),
        "task_clock_ms": ("perf", "task-clock"),
        "context_switches": ("perf", "context-switches"),
        "page_faults": ("perf", "page-faults"),
        "cycles_per_operation": ("derived", "cycles_per_operation"),
        "instructions_per_operation": ("derived", "instructions_per_operation"),
        "task_clock_per_operation": ("derived", "task-clock_per_operation"),
        "ipc": ("derived", "ipc"),
        "cache_mpki": ("derived", "cache_mpki"),
        "branch_mpki": ("derived", "branch_mpki"),
    }
    aggregates: dict[str, Any] = {}
    fits: dict[str, Any] = {}
    for condition in CONDITIONS:
        aggregates[condition] = {}
        median_points: dict[str, list[tuple[float, float]]] = {name: [] for name in paths}
        for count in counts:
            group = [sample for sample in samples if sample["fixture"]["condition"] == condition and sample["fixture"]["operations"] == count]
            row: dict[str, Any] = {"operations": count, "samples": len(group)}
            for name, path in paths.items():
                values = [value for sample in group if (value := value_at(sample, path)) is not None]
                if not values:
                    row[name] = None
                    continue
                median = statistics.median(values)
                row[name] = {"median": median, "min": min(values), "max": max(values)}
                median_points[name].append((float(count), median))
            aggregates[condition][str(count)] = row
        fits[condition] = {}
        for name in ["wall_ns", "controller_cpu_us", "cycles", "instructions", "task_clock_ms", "page_faults"]:
            points = median_points[name]
            if len(points) < 2:
                continue
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            x_mean = statistics.fmean(xs)
            y_mean = statistics.fmean(ys)
            denominator = sum((x - x_mean) ** 2 for x in xs)
            slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
            fits[condition][name] = {"intercept": y_mean - slope * x_mean, "per_operation_slope": slope}
    return aggregates, fits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", type=parse_counts, default=parse_counts("1,10,100,1000"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    root = Path(__file__).resolve().parents[2]
    node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts" / "cpu" / "c4-shell-launch.mjs"
    mode = perf_mode()
    if args.perf == "on" and mode == "off":
        parser.error("perf was requested but unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and mode != "off")
    perf_events = PERF_EVENTS if mode == "full" else (PERF_EVENTS_USER_ONLY if mode == "user-only" else [])
    schedule = [(condition, count) for condition in CONDITIONS for count in args.counts for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(schedule)
    samples = []
    for index, (condition, count) in enumerate(schedule, start=1):
        sample = run_sample(node, fixture, condition, count, None if args.cpu < 0 else args.cpu, use_perf, perf_events)
        sample["sample_index"] = index
        samples.append(sample)
        print(
            f"[C4 {index}/{len(schedule)}] condition={condition} operations={count} "
            f"wall_us/op={sample['fixture']['measurement']['wall_ns_per_operation'] / 1000:.1f}",
            flush=True,
        )
    aggregates, fits = summarize(samples, args.counts)
    result = {
        "benchmark": "C4 shell lifecycle scaling",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "conditions": CONDITIONS,
            "operations": args.counts,
            "repeats": args.repeats,
            "command_shape": "bash no-op builtin followed by one fixed-width acknowledgement",
            "randomization_seed": args.seed,
            "cpu_affinity": None if args.cpu < 0 else args.cpu,
            "perf_enabled": use_perf,
            "perf_mode": mode,
            "perf_descendant_inheritance": "perf stat default inheritance; counters cover spawned descendants",
            "perf_events": perf_events if use_perf else [],
            "observed_perf_event_labels": samples[0]["perf_event_labels"] if samples else {},
        },
        "host": {
            "platform": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count(),
            "node": subprocess.run([str(node), "--version"], text=True, capture_output=True, check=True).stdout.strip(),
            "perf": subprocess.run(["perf", "--version"], text=True, capture_output=True, check=False).stdout.strip()
            if shutil.which("perf") else None,
            "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()
            if Path("/proc/sys/kernel/perf_event_paranoid").exists() else None,
        },
        "aggregates": aggregates,
        "linear_fits_over_operation_count_medians": fits,
        "samples": samples,
        "limitations": [
            "Pinned DSH bash-local is managed one-shot bash -c, not a persistent shell.",
            "Raw and persistent conditions are benchmark controls, not OpenClaw implementations.",
            "The persistent condition excludes shell startup from scoped loop timing but whole-process perf includes it.",
            "process.cpuUsage reports the Node controller only; inherited perf counters cover descendant shell processes.",
            "The pilot uses a no-op builtin plus acknowledgement; filesystem and external-command workloads are separate conditions.",
            "cycles:u/cycles:k and instructions:u/instructions:k are sampled directly and summed into cycles/instructions with derived *_kernel_ratio; a perf restriction to user space omits the :k fields.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__":
    main()
