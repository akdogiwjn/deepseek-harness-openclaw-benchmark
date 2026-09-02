#!/usr/bin/env python3
"""Run and summarize C6 local-vs-sandbox filesystem scaling."""

from __future__ import annotations

import argparse, json, math, os, platform, random, shutil, statistics, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONDITIONS = [(backend, workload) for backend in ("local", "sandbox") for workload in ("read", "write")]
_PERF_SPLIT_NAMES = frozenset(("cycles", "instructions"))
PERF_EVENTS = ["task-clock", "cycles:u", "cycles:k", "instructions:u", "instructions:k", "branches", "branch-misses", "cache-references",
               "cache-misses", "context-switches", "cpu-migrations", "page-faults"]
PERF_EVENTS_USER_ONLY = ["task-clock", "cycles:u", "instructions:u", "branches", "branch-misses", "cache-references",
                         "cache-misses", "context-switches", "cpu-migrations", "page-faults"]


def parse_counts(raw: str) -> list[int]:
    values = [int(item) for item in raw.split(",")]
    if not values or any(value < 1 for value in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("counts must be unique positive integers")
    return values


def default_node(root: Path) -> Path:
    revisions = dict(line.split("=", 1) for line in (root / "configs/revisions.env").read_text().splitlines()
                     if line and not line.startswith("#"))
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    if arch is None: raise RuntimeError(f"unsupported architecture: {platform.machine()}")
    return root / f"node-v{revisions['NODE_VERSION']}-linux-{arch}/bin/node"


def perf_mode() -> str:
    perf = shutil.which("perf")
    if perf is None: return "off"
    for mode, events, marker in (
        ("full", PERF_EVENTS, "cycles:k"),
        ("user-only", PERF_EVENTS_USER_ONLY, "cycles:u"),
    ):
        completed = subprocess.run([perf, "stat", "-x,", "-e", ",".join(events), "--", "true"],
                                   text=True, capture_output=True, check=False)
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
        if len(fields) < 3: continue
        label = fields[2].strip()
        base = label.split(":", 1)[0]
        if base not in base_names: continue
        key = label.replace(":", "_") if base in _PERF_SPLIT_NAMES else base
        try: metrics[key] = float(fields[0].strip())
        except ValueError: metrics[key] = None
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


def run_sample(node: Path, fixture: Path, backend: str, workload: str, count: int,
               payload: int, cpu: int | None, use_perf: bool, perf_events: list[str]) -> dict[str, Any]:
    command = [str(node), str(fixture), backend, workload, str(count), str(payload)]
    if use_perf: command = ["perf", "stat", "-x,", "--no-big-num", "-e", ",".join(perf_events), "--", *command]
    if cpu is not None: command = ["taskset", "-c", str(cpu), *command]
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"C6 failed for {backend}/{workload}/{count}: {result.returncode}\n{result.stdout}\n{result.stderr}")
    fixture_result = json.loads([line for line in result.stdout.splitlines() if line.strip()][-1])
    perf, labels = parse_perf(result.stderr) if use_perf else ({}, {})
    derived = {}
    instructions, cycles = perf.get("instructions"), perf.get("cycles")
    if instructions and cycles: derived["ipc"] = instructions / cycles
    if instructions and perf.get("cache-misses") is not None: derived["cache_mpki"] = perf["cache-misses"] / instructions * 1000
    if instructions and perf.get("branch-misses") is not None: derived["branch_mpki"] = perf["branch-misses"] / instructions * 1000
    return {"fixture": fixture_result, "perf": perf, "perf_event_labels": labels, "derived": derived}


def value_at(sample: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = sample
    for key in path:
        if not isinstance(value, dict) or key not in value: return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def summarize(samples: list[dict[str, Any]], counts: list[int]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    paths = {"wall_ns": ("fixture", "timing", "wall_ns"), "wall_ns_per_operation": ("fixture", "timing", "wall_ns_per_operation"),
             "cpu_us": ("fixture", "timing", "cpu_total_us"), "cpu_us_per_operation": ("fixture", "timing", "cpu_us_per_operation"),
             "max_rss_kb": ("fixture", "resources", "max_rss_kb"), "cycles": ("perf", "cycles"),
             "instructions": ("perf", "instructions"), "task_clock_ms": ("perf", "task-clock"),
             "page_faults": ("perf", "page-faults"), "ipc": ("derived", "ipc"),
             "cache_mpki": ("derived", "cache_mpki"), "branch_mpki": ("derived", "branch_mpki")}
    aggregates, fits = {}, {}
    for backend, workload in CONDITIONS:
        condition = f"{backend}-{workload}"
        aggregates[condition], fits[condition] = {}, {}
        points = {name: [] for name in paths}
        for count in counts:
            group = [s for s in samples if s["fixture"]["backend"] == backend and s["fixture"]["workload"] == workload
                     and s["fixture"]["operations"] == count]
            row = {"operations": count, "samples": len(group)}
            for name, path in paths.items():
                values = [v for sample in group if (v := value_at(sample, path)) is not None]
                if not values: row[name] = None; continue
                median = statistics.median(values)
                row[name] = {"median": median, "min": min(values), "max": max(values)}
                points[name].append((float(count), median))
            aggregates[condition][str(count)] = row
        for name in ["wall_ns", "cpu_us", "cycles", "instructions", "task_clock_ms", "page_faults"]:
            pairs = points[name]
            if len(pairs) < 2:
                continue
            xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
            xm, ym = statistics.fmean(xs), statistics.fmean(ys)
            denominator = sum((x - xm) ** 2 for x in xs)
            slope = sum((x - xm) * (y - ym) for x, y in pairs) / denominator
            fits[condition][name] = {"intercept": ym - slope * xm, "per_operation_slope": slope}
    comparisons = {}
    for workload in ("read", "write"):
        comparisons[workload] = {}
        for count in counts:
            local, sandbox = aggregates[f"local-{workload}"][str(count)], aggregates[f"sandbox-{workload}"][str(count)]
            comparisons[workload][str(count)] = {"operations": count}
            for metric in ["wall_ns_per_operation", "cpu_us_per_operation", "instructions", "cycles"]:
                left, right = local[metric], sandbox[metric]
                comparisons[workload][str(count)][f"sandbox_over_local_{metric}"] = right["median"] / left["median"] if left and right and left["median"] else None
    return aggregates, fits, comparisons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", type=parse_counts, default=parse_counts("1,10,100,1000"))
    parser.add_argument("--repeats", type=int, default=5); parser.add_argument("--payload-bytes", type=int, default=256)
    parser.add_argument("--cpu", type=int, default=0); parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--node", type=Path); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.payload_bytes < 16: parser.error("repeats positive; payload-bytes at least 16")
    root = Path(__file__).resolve().parents[2]; node = (args.node or default_node(root)).resolve()
    fixture = root / "scripts/cpu/c6-fs-sandbox.mjs"; mode = perf_mode()
    if args.perf == "on" and mode == "off": parser.error("perf requested but unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and mode != "off")
    perf_events = PERF_EVENTS if mode == "full" else (PERF_EVENTS_USER_ONLY if mode == "user-only" else [])
    schedule = [(b, w, n) for b, w in CONDITIONS for n in args.counts for _ in range(args.repeats)]
    random.Random(args.seed).shuffle(schedule); samples = []
    for index, (backend, workload, count) in enumerate(schedule, 1):
        sample = run_sample(node, fixture, backend, workload, count, args.payload_bytes,
                            None if args.cpu < 0 else args.cpu, use_perf, perf_events)
        sample["sample_index"] = index; samples.append(sample)
        print(f"[C6 {index}/{len(schedule)}] {backend}-{workload} operations={count} "
              f"wall_us/op={sample['fixture']['timing']['wall_ns_per_operation']/1000:.1f}", flush=True)
    aggregates, fits, comparisons = summarize(samples, args.counts)
    result = {"benchmark": "C6 DSH local-vs-sandbox filesystem scaling", "created_at": datetime.now(timezone.utc).isoformat(),
              "design": {"conditions": [f"{b}-{w}" for b, w in CONDITIONS], "operations": args.counts,
                         "repeats": args.repeats, "payload_bytes": args.payload_bytes, "randomization_seed": args.seed,
                         "cpu_affinity": None if args.cpu < 0 else args.cpu, "perf_enabled": use_perf,
                         "perf_mode": mode, "perf_events": perf_events if use_perf else [], "observed_perf_event_labels": samples[0]["perf_event_labels"]},
              "host": {"platform": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count(),
                       "node": subprocess.run([str(node), "--version"], text=True, capture_output=True, check=True).stdout.strip(),
                       "perf": subprocess.run(["perf", "--version"], text=True, capture_output=True).stdout.strip(),
                       "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()},
              "aggregates": aggregates, "comparisons": comparisons,
              "linear_fits_over_operation_count_medians": fits, "samples": samples,
              "limitations": ["fs-sandbox is a trusted canonicalize-and-contain policy fence, not a kernel security boundary.",
                 "Reads are an inherited-path negative control; only mutations add sandbox checks.",
                 "Writes use DSH atomic whole-file replacement with a fixed 256-byte payload.",
                 "W10 covers denial semantics; C6 measures allowed workspace operations only.",
                 "Whole-process perf includes Node/V8 startup, composition, workspace setup/cleanup, and teardown.",
                 "cycles:u/cycles:k and instructions:u/instructions:k are sampled directly and summed into cycles/instructions with derived *_kernel_ratio; a perf restriction to user space omits the :k fields."],}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__": main()
