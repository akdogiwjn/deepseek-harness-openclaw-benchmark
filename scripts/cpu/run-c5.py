#!/usr/bin/env python3
"""Run and summarize C5 DSH native-vs-PTC scaling."""

from __future__ import annotations

import argparse, json, math, os, platform, random, shutil, statistics, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MODES = ["native", "ptc"]
_PERF_SPLIT_NAMES = frozenset(("cycles", "instructions"))
PERF_EVENTS = ["task-clock", "cycles:u", "cycles:k", "instructions:u", "instructions:k", "branches", "branch-misses",
               "cache-references", "cache-misses", "context-switches", "cpu-migrations", "page-faults"]
PERF_EVENTS_USER_ONLY = ["task-clock", "cycles:u", "instructions:u", "branches", "branch-misses",
                         "cache-references", "cache-misses", "context-switches", "cpu-migrations", "page-faults"]


def parse_counts(raw: str) -> list[int]:
    values = [int(item) for item in raw.split(",")]
    if not values or any(value < 0 for value in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("counts must be unique non-negative integers")
    return values


def default_node(root: Path) -> Path:
    revisions = dict(line.split("=", 1) for line in (root / "configs/revisions.env").read_text().splitlines()
                     if line and not line.startswith("#"))
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    if arch is None:
        raise RuntimeError(f"unsupported architecture: {platform.machine()}")
    return root / f"node-v{revisions['NODE_VERSION']}-linux-{arch}/bin/node"


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
    metrics, labels = {}, {}
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


def run_sample(node: Path, fixture: Path, mode: str, count: int, payload: int,
               cpu: int | None, use_perf: bool, perf_events: list[str]) -> dict[str, Any]:
    command = [str(node), str(fixture), mode, str(count), str(payload)]
    if use_perf:
        command = ["perf", "stat", "-x,", "--no-big-num", "-e", ",".join(perf_events), "--", *command]
    if cpu is not None:
        command = ["taskset", "-c", str(cpu), *command]
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"C5 failed for {mode}/{count}: {result.returncode}\n{result.stdout}\n{result.stderr}")
    fixture_result = json.loads([line for line in result.stdout.splitlines() if line.strip()][-1])
    perf, labels = parse_perf(result.stderr) if use_perf else ({}, {})
    derived = {}
    instructions, cycles = perf.get("instructions"), perf.get("cycles")
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


def summarize(samples: list[dict[str, Any]], counts: list[int]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = {
        "provider_requests": ("fixture", "provider_requests"), "session_event_count": ("fixture", "session_event_count"),
        "internal_wall_ns": ("fixture", "timing", "wall_ns"), "internal_cpu_us": ("fixture", "timing", "cpu_total_us"),
        "max_rss_kb": ("fixture", "resources", "max_rss_kb"), "cycles": ("perf", "cycles"),
        "instructions": ("perf", "instructions"), "task_clock_ms": ("perf", "task-clock"),
        "page_faults": ("perf", "page-faults"), "ipc": ("derived", "ipc"),
        "cache_mpki": ("derived", "cache_mpki"), "branch_mpki": ("derived", "branch_mpki"),
    }
    aggregates, fits = {}, {}
    for mode in MODES:
        aggregates[mode], fits[mode] = {}, {}
        points = {name: [] for name in paths}
        for count in counts:
            group = [s for s in samples if s["fixture"]["mode"] == mode and s["fixture"]["operations"] == count]
            row = {"operations": count, "samples": len(group)}
            for name, path in paths.items():
                values = [value for sample in group if (value := value_at(sample, path)) is not None]
                if not values:
                    row[name] = None
                    continue
                median = statistics.median(values)
                row[name] = {"median": median, "min": min(values), "max": max(values)}
                points[name].append((float(count), median))
            aggregates[mode][str(count)] = row
        for name, pairs in points.items():
            if len(pairs) < 2:
                continue
            xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
            xm, ym = statistics.fmean(xs), statistics.fmean(ys)
            denominator = sum((x - xm) ** 2 for x in xs)
            slope = sum((x - xm) * (y - ym) for x, y in pairs) / denominator
            fits[mode][name] = {"intercept": ym - slope * xm, "per_operation_slope": slope}
    comparisons = {}
    for count in counts:
        native, ptc = aggregates["native"][str(count)], aggregates["ptc"][str(count)]
        comparisons[str(count)] = {"operations": count}
        for name in ["internal_wall_ns", "internal_cpu_us", "cycles", "instructions", "max_rss_kb"]:
            n = native[name]["median"] if native[name] else None
            p = ptc[name]["median"] if ptc[name] else None
            comparisons[str(count)][f"ptc_over_native_{name}"] = p / n if n and p else None
    return aggregates, fits, comparisons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", type=parse_counts, default=parse_counts("0,1,4,16,64,256,1024"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--payload-bytes", type=int, default=16)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.payload_bytes < 0:
        parser.error("repeats must be positive and payload-bytes non-negative")
    root = Path(__file__).resolve().parents[2]
    node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts/cpu/c5-code-mode.mjs"
    mode_ = perf_mode()
    if args.perf == "on" and mode_ == "off":
        parser.error("perf requested but unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and mode_ != "off")
    perf_events = PERF_EVENTS if mode_ == "full" else (PERF_EVENTS_USER_ONLY if mode_ == "user-only" else [])
    schedule = [(mode, count) for mode in MODES for count in args.counts for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(schedule)
    samples = []
    for index, (mode, count) in enumerate(schedule, 1):
        sample = run_sample(node, fixture, mode, count, args.payload_bytes,
                            None if args.cpu < 0 else args.cpu, use_perf, perf_events)
        sample["sample_index"] = index
        samples.append(sample)
        print(f"[C5 {index}/{len(schedule)}] mode={mode} operations={count} "
              f"wall_ms={sample['fixture']['timing']['wall_ns'] / 1e6:.2f}", flush=True)
    aggregates, fits, comparisons = summarize(samples, args.counts)
    result = {
        "benchmark": "C5 DSH native-vs-PTC Agent Loop scaling", "created_at": datetime.now(timezone.utc).isoformat(),
        "design": {"modes": MODES, "operations": args.counts, "repeats": args.repeats,
                   "payload_bytes": args.payload_bytes, "randomization_seed": args.seed,
                   "cpu_affinity": None if args.cpu < 0 else args.cpu, "perf_enabled": use_perf,
                   "perf_mode": mode_, "perf_events": perf_events if use_perf else [],
                   "observed_perf_event_labels": samples[0]["perf_event_labels"] if samples else {}},
        "host": {"platform": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count(),
                 "node": subprocess.run([str(node), "--version"], text=True, capture_output=True, check=True).stdout.strip(),
                 "perf": subprocess.run(["perf", "--version"], text=True, capture_output=True, check=False).stdout.strip()
                 if shutil.which("perf") else None,
                 "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()},
        "aggregates": aggregates, "comparisons": comparisons,
        "linear_fits_over_operation_count_medians": fits, "samples": samples,
        "limitations": [
            "This is a DSH internal native-vs-PTC comparison, not DSH-vs-OpenClaw.",
            "The deterministic in-process adapter removes network and real-model latency; provider request reduction is semantic, not timed remote savings.",
            "PTC uses the real fresh-worker-per-program WorkerThreadCodeRuntime and sequential nested tool calls.",
            "The no-op tool excludes shell, filesystem, and payload-dependent work.",
            "Whole-process perf includes Node/V8 startup, composition, measured turn, worker lifecycle, and teardown.",
            "cycles:u/cycles:k and instructions:u/instructions:k are sampled directly and summed into cycles/instructions with derived *_kernel_ratio; a perf restriction to user space omits the :k fields.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__": main()
