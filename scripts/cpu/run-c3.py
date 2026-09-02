#!/usr/bin/env python3
"""Run and summarize C3 fixed-shape context-byte scaling."""

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
    "task-clock", "cycles", "instructions", "branches", "branch-misses",
    "cache-references", "cache-misses", "context-switches", "cpu-migrations", "page-faults",
]
OPERATIONS = [
    "derive_messages", "assemble_wire_request", "json_encode_request",
    "json_decode_request", "sse_frame_and_json_decode",
]


def parse_sizes(raw: str) -> list[int]:
    suffixes = {"k": 1024, "m": 1024**2}
    values: list[int] = []
    for item in raw.split(","):
        text = item.strip().lower()
        multiplier = suffixes.get(text[-1:], 1)
        number = text[:-1] if multiplier != 1 else text
        try:
            value = int(number) * multiplier
        except ValueError as error:
            raise argparse.ArgumentTypeError(f"invalid context size: {item}") from error
        values.append(value)
    if not values or any(value < 1 for value in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("sizes must be unique positive comma-separated integers with optional K/M")
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


def perf_works() -> bool:
    perf = shutil.which("perf")
    if perf is None:
        return False
    result = subprocess.run(
        [perf, "stat", "-x,", "-e", "cycles,instructions", "--", "true"],
        text=True, capture_output=True, check=False,
    )
    return result.returncode == 0 and "cycles" in result.stderr


def parse_perf(stderr: str) -> tuple[dict[str, float | None], dict[str, str]]:
    metrics: dict[str, float | None] = {}
    labels: dict[str, str] = {}
    for line in stderr.splitlines():
        fields = line.split(",")
        if len(fields) < 3:
            continue
        label = fields[2].strip()
        event = label.split(":", 1)[0]
        if event not in PERF_EVENTS:
            continue
        try:
            metrics[event] = float(fields[0].strip())
        except ValueError:
            metrics[event] = None
        labels[event] = label
    return metrics, labels


def run_sample(
    node: Path,
    fixture: Path,
    size: int,
    iterations: int,
    stream_chunk_bytes: int,
    cpu: int | None,
    use_perf: bool,
) -> dict[str, Any]:
    command = [str(node), str(fixture), str(size), str(iterations), str(stream_chunk_bytes)]
    if use_perf:
        command = ["perf", "stat", "-x,", "--no-big-num", "-e", ",".join(PERF_EVENTS), "--", *command]
    if cpu is not None:
        command = ["taskset", "-c", str(cpu), *command]
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"C3 sample failed for context_bytes={size}: exit={result.returncode}\n"
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
    for operation in OPERATIONS:
        cpu_us = fixture_result["operations"][operation]["cpu_us_per_iteration"]
        derived[f"{operation}_cpu_ns_per_context_byte"] = cpu_us * 1000 / size
    return {"fixture": fixture_result, "perf": perf, "perf_event_labels": labels, "derived": derived}


def value_at(sample: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = sample
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def aggregate(samples: list[dict[str, Any]], sizes: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    paths: dict[str, tuple[str, ...]] = {
        "request_json_bytes": ("fixture", "request_json_bytes"),
        "response_json_bytes": ("fixture", "response_json_bytes"),
        "sse_wire_bytes": ("fixture", "sse_wire_bytes"),
        "max_rss_kb": ("fixture", "resources", "max_rss_kb"),
        "cycles": ("perf", "cycles"),
        "instructions": ("perf", "instructions"),
        "ipc": ("derived", "ipc"),
        "cache_mpki": ("derived", "cache_mpki"),
        "branch_mpki": ("derived", "branch_mpki"),
    }
    for operation in OPERATIONS:
        paths[f"{operation}_wall_ns"] = ("fixture", "operations", operation, "wall_ns_per_iteration")
        paths[f"{operation}_cpu_us"] = ("fixture", "operations", operation, "cpu_us_per_iteration")
        paths[f"{operation}_cpu_ns_per_context_byte"] = (
            "derived", f"{operation}_cpu_ns_per_context_byte",
        )

    rows: dict[str, Any] = {}
    medians: dict[str, list[tuple[float, float]]] = {name: [] for name in paths}
    for size in sizes:
        group = [sample for sample in samples if sample["fixture"]["context_bytes"] == size]
        row: dict[str, Any] = {"context_bytes": size, "samples": len(group)}
        for name, path in paths.items():
            values = [value for sample in group if (value := value_at(sample, path)) is not None]
            if not values:
                row[name] = None
                continue
            median = statistics.median(values)
            row[name] = {"median": median, "min": min(values), "max": max(values)}
            medians[name].append((float(size), median))
        rows[str(size)] = row

    fits: dict[str, Any] = {}
    for name, points in medians.items():
        if len(points) < 2 or name.endswith("_per_context_byte"):
            continue
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        x_mean = statistics.fmean(xs)
        y_mean = statistics.fmean(ys)
        denominator = sum((x - x_mean) ** 2 for x in xs)
        slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
        fits[name] = {"intercept": y_mean - slope * x_mean, "per_context_byte_slope": slope}
    return rows, fits


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=parse_sizes, default=parse_sizes("4K,16K,64K,256K,1M,4M,16M"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--stream-chunk-bytes", type=int, default=16384)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.iterations < 1 or args.stream_chunk_bytes < 1:
        parser.error("repeats, iterations, and stream-chunk-bytes must be positive")

    root = Path(__file__).resolve().parents[2]
    node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts" / "cpu" / "c3-context-json.mjs"
    available = perf_works()
    if args.perf == "on" and not available:
        parser.error("perf was requested but unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and available)
    schedule = [size for size in args.sizes for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(schedule)
    samples = []
    for index, size in enumerate(schedule, start=1):
        sample = run_sample(
            node, fixture, size, args.iterations, args.stream_chunk_bytes,
            None if args.cpu < 0 else args.cpu, use_perf,
        )
        sample["sample_index"] = index
        samples.append(sample)
        operations = sample["fixture"]["operations"]
        print(
            f"[C3 {index}/{len(schedule)}] bytes={size} "
            f"encode_us={operations['json_encode_request']['cpu_us_per_iteration']:.1f} "
            f"sse_us={operations['sse_frame_and_json_decode']['cpu_us_per_iteration']:.1f}",
            flush=True,
        )

    aggregates, fits = aggregate(samples, args.sizes)
    result = {
        "benchmark": "C3 fixed-shape context-byte scaling",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {
            "context_bytes": args.sizes,
            "repeats": args.repeats,
            "iterations_per_scoped_operation": args.iterations,
            "message_shape": "one completed user turn with one ASCII text block",
            "stream_chunk_bytes": args.stream_chunk_bytes,
            "randomization_seed": args.seed,
            "cpu_affinity": None if args.cpu < 0 else args.cpu,
            "perf_enabled": use_perf,
            "perf_events": PERF_EVENTS if use_perf else [],
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
        "linear_fits_over_context_byte_medians": fits,
        "samples": samples,
        "limitations": [
            "The size sweep fixes event/message/tool-schema counts and uses one ASCII user text block.",
            "Request assembly is the pinned DSH DeepSeek serializer; JSON encode/decode are the Node/V8 primitives used at its transport boundary.",
            "SSE uses the pinned DSH framing parser plus JSON.parse, not the complete adapter translation state machine.",
            "SSE response text grows with request context size only to provide a common byte axis; real request and response sizes are independent.",
            "Whole-process perf includes Node/V8 startup, setup, every scoped operation, cleanup, and teardown.",
            "A :u event label excludes kernel execution and makes zero scheduling counters non-interpretable.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__":
    main()
