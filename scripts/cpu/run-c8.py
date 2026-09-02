#!/usr/bin/env python3
"""Run and summarize the C8 token-meter / context-pressure CPU scaling fixture."""

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

SUBTESTS = ("cold", "incremental", "repeat", "shape")


def parse_counts(raw: str) -> list[int]:
    values = [int(item) for item in raw.split(",")]
    if not values or any(item < 1 for item in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("sizes must be unique positive comma-separated integers")
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
    subtest: str,
    n: int,
    payload_bytes: int,
    iterations: int,
    cpu: int | None,
    use_perf: bool,
    perf_events: list[str],
    shape: str = "text",
) -> dict[str, Any]:
    command = [str(node), str(fixture), subtest, str(n), str(payload_bytes), str(iterations)]
    if subtest == "shape":
        command.append(shape)
    if use_perf:
        command = ["perf", "stat", "-x,", "--no-big-num", "-e", ",".join(perf_events), "--", *command]
    if cpu is not None:
        command = ["taskset", "-c", str(cpu), *command]
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError(
            f"C8 sample failed for {subtest}/{n}: exit={completed.returncode}\n"
            f"stdout={completed.stdout}\nstderr={completed.stderr}"
        )
    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not stdout_lines:
        raise RuntimeError(f"C8 sample produced no JSON for {subtest}/{n}")
    fixture_result = json.loads(stdout_lines[-1])
    perf, labels = parse_perf(completed.stderr) if use_perf else ({}, {})
    derived: dict[str, float | None] = {}
    measure = fixture_result.get("measure", {})
    if measure.get("wall_ns") is not None:
        derived["internal_wall_ns_per_measure"] = measure["wall_ns"]
        derived["internal_cpu_us_per_measure"] = measure.get("cpu_total_us")
    instructions = perf.get("instructions")
    cycles = perf.get("cycles")
    if instructions is not None and cycles:
        derived["ipc"] = instructions / cycles
    if subtest in ("incremental", "repeat") and iterations > 0:
        if instructions is not None:
            derived["process_instructions_per_measure"] = instructions / iterations
        if cycles is not None:
            derived["process_cycles_per_measure"] = cycles / iterations
    if n > 0:
        if instructions is not None:
            derived["process_instructions_per_event"] = instructions / n
        if cycles is not None:
            derived["process_cycles_per_event"] = cycles / n
    return {
        "fixture": fixture_result,
        "perf": perf,
        "perf_event_labels": labels,
        "derived": derived,
    }


def numeric_path(sample: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = sample
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def x_axis_of(fixture: dict[str, Any]) -> float:
    if fixture.get("schema_bytes") is not None:
        return float(fixture["schema_bytes"])
    return float(fixture.get("effective_surface_nodes", fixture["surface_events"]))


def aggregate(samples: list[dict[str, Any]], sizes: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = {
        "internal_wall_ns_per_measure": ("derived", "internal_wall_ns_per_measure"),
        "internal_cpu_us_per_measure": ("derived", "internal_cpu_us_per_measure"),
        "cycles": ("perf", "cycles"),
        "instructions": ("perf", "instructions"),
        "cycles_kernel_ratio": ("perf", "cycles_kernel_ratio"),
        "instructions_kernel_ratio": ("perf", "instructions_kernel_ratio"),
        "ipc": ("derived", "ipc"),
        "process_cycles_per_measure": ("derived", "process_cycles_per_measure"),
        "process_instructions_per_measure": ("derived", "process_instructions_per_measure"),
        "process_cycles_per_event": ("derived", "process_cycles_per_event"),
        "process_instructions_per_event": ("derived", "process_instructions_per_event"),
        "surface_nodes": ("fixture", "surface_nodes"),
        "surface_tokens": ("fixture", "surface_tokens"),
    }
    by_size: dict[str, Any] = {}
    medians: dict[str, list[tuple[float, float]]] = {name: [] for name in paths}
    is_schema = bool(samples) and samples[0]["fixture"].get("schema_bytes") is not None
    for size in sizes:
        group = [sample for sample in samples if sample["fixture"]["surface_events"] == size]
        row: dict[str, Any] = {"samples": len(group)}
        x = x_axis_of(group[0]["fixture"]) if group else float(size)
        for name, path in paths.items():
            values = [value for sample in group if (value := numeric_path(sample, path)) is not None]
            if not values:
                row[name] = None
                continue
            median = statistics.median(values)
            row[name] = {"median": median, "min": min(values), "max": max(values)}
            medians[name].append((x, median))
        by_size[str(size)] = row

    slope_key = "per_schema_byte_slope" if is_schema else "per_surface_node_slope"
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
        fits[name] = {"intercept": y_mean - slope * x_mean, slope_key: slope}
    return by_size, fits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subtest", choices=SUBTESTS, required=True)
    parser.add_argument("--sizes", type=parse_counts, default=parse_counts("10,100,1000,5000,10000"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--payload-bytes", type=int, default=256)
    parser.add_argument("--shape", choices=("text", "tool-call", "tool-result", "schema"), default="text")
    parser.add_argument("--cpu", type=int, default=0, help="logical CPU to pin, or -1 to disable")
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.iterations < 1 or args.payload_bytes < 1:
        parser.error("repeats, iterations, and payload-bytes must be positive")

    root = Path(__file__).resolve().parents[2]
    node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts" / "cpu" / "c8-token-meter.mjs"
    mode, perf_events = probe_perf()
    if args.perf == "on" and mode == "off":
        parser.error("perf was requested but the selected events are unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and mode != "off")
    schedule = [size for size in args.sizes for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(schedule)
    samples = []

    def iterations_for(size: int) -> int:
        if args.subtest == "cold":
            return 1
        return max(20, args.iterations // max(1, size // 1000))

    for index, size in enumerate(schedule, start=1):
        sample = run_sample(
            node=node,
            fixture=fixture,
            subtest=args.subtest,
            n=size,
            payload_bytes=args.payload_bytes,
            iterations=iterations_for(size),
            cpu=None if args.cpu < 0 else args.cpu,
            use_perf=use_perf,
            perf_events=perf_events,
            shape=args.shape,
        )
        sample["sample_index"] = index
        samples.append(sample)
        print(
            f"[C8 {index}/{len(schedule)}] subtest={args.subtest} size={size} "
            f"cpu_us={sample['fixture']['measure'].get('cpu_total_us')} "
            f"cycles={sample['perf'].get('cycles')}",
            flush=True,
        )

    by_size, fits = aggregate(samples, args.sizes)
    result = {
        "benchmark": "C8 token-meter / context-pressure CPU scaling",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "subtest": args.subtest,
            "shape": args.shape if args.subtest == "shape" else None,
            "surface_events": args.sizes,
            "x_axis": "schema_bytes" if (args.subtest == "shape" and args.shape == "schema")
            else ("effective_surface_nodes" if args.subtest == "incremental" else "surface_events"),
            "repeats": args.repeats,
            "base_iterations": args.iterations,
            "iterations_scaling": "max(20, base // max(1, size // 1000)); cold uses 1",
            "payload_bytes": args.payload_bytes,
            "randomization_seed": args.seed,
            "cpu_affinity": None if args.cpu < 0 else args.cpu,
            "perf_enabled": use_perf,
            "perf_mode": mode,
            "perf_events": perf_events if use_perf else [],
            "observed_perf_event_labels": samples[0]["perf_event_labels"] if samples else {},
            "internal_scope": "TokenMeter.measure() prompt-window timing; construction excluded",
            "perf_scope": "whole Node fixture process; construction, measured calls, and teardown included",
        },
        "host": {
            "platform": platform.platform(),
            "kernel_release": platform.release(),
            "machine": platform.machine(),
            "logical_cpus": os.cpu_count(),
            "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()
            if Path("/proc/sys/kernel/perf_event_paranoid").exists() else None,
            "node": subprocess.run([str(node), "--version"], text=True, capture_output=True, check=True).stdout.strip(),
            "perf": subprocess.run(["perf", "--version"], text=True, capture_output=True, check=False).stdout.strip()
            if shutil.which("perf") else None,
        },
        "aggregates": by_size,
        "linear_fits_over_surface_nodes": fits,
        "samples": samples,
        "limitations": [
            "TokenMeter uses the fixed char/4 heuristic, not a real BPE tokenizer; this measures the context-pressure accounting path, not tokenization.",
            "measure() is O(surface): it reprices every node and deep-clones the result; the repeat subtest isolates that path.",
            "Whole-process perf includes session construction and teardown; only the internal prompt-window timing is construction-free.",
            "cycles/instructions per measure divide whole-process perf by iterations and therefore absorb a fixed construction intercept.",
            "Surface here is text user/message nodes; tool/result and tool-schema shape costs are the C8-D condition.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__":
    main()