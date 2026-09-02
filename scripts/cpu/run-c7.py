#!/usr/bin/env python3
"""Run and summarize C7 multi-process DSH Agent scale-out."""

from __future__ import annotations

import argparse, json, math, os, platform, random, shutil, statistics, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PERF_EVENTS = ["task-clock", "cycles", "cycles:k", "instructions", "instructions:k", "branches", "branch-misses", "cache-references",
               "cache-misses", "context-switches", "cpu-migrations", "page-faults"]


def parse_counts(raw: str) -> list[int]:
    values = [int(item) for item in raw.split(",")]
    if not values or any(value < 1 for value in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("agent counts must be unique positive integers")
    return values


def default_node(root: Path) -> Path:
    revisions = dict(line.split("=", 1) for line in (root / "configs/revisions.env").read_text().splitlines()
                     if line and not line.startswith("#"))
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    if arch is None: raise RuntimeError(f"unsupported architecture: {platform.machine()}")
    return root / f"node-v{revisions['NODE_VERSION']}-linux-{arch}/bin/node"


def physical_cpu_candidates() -> tuple[list[int], str]:
    raw = subprocess.run(["lscpu", "-p=CPU,CORE,SOCKET,NODE"], text=True, capture_output=True, check=True).stdout
    selected, seen = [], set()
    for line in raw.splitlines():
        if not line or line.startswith("#"): continue
        cpu, core, socket, _node = (int(field) for field in line.split(","))
        key = (socket, core)
        if key not in seen: seen.add(key); selected.append(cpu)
    return selected, raw


def perf_works() -> bool:
    if shutil.which("perf") is None: return False
    run = subprocess.run(["perf", "stat", "-x,", "-e", "cycles,instructions", "--", "true"],
                         text=True, capture_output=True, check=False)
    return run.returncode == 0 and "cycles" in run.stderr


def parse_perf(stderr: str) -> tuple[dict[str, float | None], dict[str, str]]:
    metrics, labels = {}, {}
    for line in stderr.splitlines():
        fields = line.split(",")
        if len(fields) < 3: continue
        label = fields[2].strip()
        if label not in PERF_EVENTS: continue
        key = label.replace(":", "_")
        try: metrics[key] = float(fields[0].strip())
        except ValueError: metrics[key] = None
        labels[key] = label
    for base in ("cycles", "instructions"):
        total = metrics.get(base)
        kernel = metrics.get(f"{base}_k")
        if total is not None and kernel is not None:
            metrics[f"{base}_u"] = total - kernel
            if total:
                metrics[f"{base}_kernel_ratio"] = kernel / total
    return metrics, labels


def run_sample(node: Path, controller: Path, agents: int, steps: int, payload: int,
               cpus: list[int], use_perf: bool, hard_pin: bool) -> dict[str, Any]:
    bound_cpus = cpus[:agents]
    cpu_list = ",".join(str(cpu) for cpu in bound_cpus)
    command = [str(node), str(controller), str(agents), str(steps), str(payload)]
    if use_perf: command = ["perf", "stat", "-x,", "--no-big-num", "-e", ",".join(PERF_EVENTS), "--", *command]
    if hard_pin:
        command.append(cpu_list)
    else:
        command = ["taskset", "-c", cpu_list, *command]
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if result.returncode != 0: raise RuntimeError(f"C7 failed for agents={agents}:\n{result.stdout}\n{result.stderr}")
    fixture = json.loads([line for line in result.stdout.splitlines() if line.strip()][-1])
    perf, labels = parse_perf(result.stderr) if use_perf else ({}, {})
    wall_ms = fixture["timing"]["wall_ns"] / 1e6
    derived = {"cpu_binding": cpu_list, "pin_mode": "hard_pin" if hard_pin else "shared_cpuset"}
    instructions, cycles, task_clock = perf.get("instructions"), perf.get("cycles"), perf.get("task-clock")
    if instructions and cycles: derived["ipc"] = instructions / cycles
    if instructions and perf.get("cache-misses") is not None: derived["cache_mpki"] = perf["cache-misses"] / instructions * 1000
    if instructions and perf.get("branch-misses") is not None: derived["branch_mpki"] = perf["branch-misses"] / instructions * 1000
    if task_clock is not None:
        derived["average_user_cpu_cores"] = task_clock / wall_ms
        derived["user_cpu_affinity_utilization"] = task_clock / wall_ms / agents
    for name, value in (("instructions_per_agent", instructions), ("cycles_per_agent", cycles),
                        ("task_clock_ms_per_agent", task_clock)):
        if value is not None: derived[name] = value / agents
    return {"fixture": fixture, "perf": perf, "perf_event_labels": labels, "derived": derived}


def value_at(sample: dict[str, Any], path: tuple[str, ...]) -> float | None:
    value: Any = sample
    for key in path:
        if not isinstance(value, dict) or key not in value: return None
        value = value[key]
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


def summarize(samples: list[dict[str, Any]], counts: list[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    paths = {"wall_ns": ("fixture", "timing", "wall_ns"), "agents_per_second": ("fixture", "timing", "agents_per_second"),
             "tool_steps_per_second": ("fixture", "timing", "tool_steps_per_second"),
             "sum_child_max_rss_kb": ("fixture", "memory", "sum_child_max_rss_kb"),
             "max_child_max_rss_kb": ("fixture", "memory", "max_child_max_rss_kb"),
             "cycles": ("perf", "cycles"), "instructions": ("perf", "instructions"), "task_clock_ms": ("perf", "task-clock"),
             "page_faults": ("perf", "page-faults"), "ipc": ("derived", "ipc"), "cache_mpki": ("derived", "cache_mpki"),
             "branch_mpki": ("derived", "branch_mpki"), "average_user_cpu_cores": ("derived", "average_user_cpu_cores"),
             "user_cpu_affinity_utilization": ("derived", "user_cpu_affinity_utilization"),
             "instructions_per_agent": ("derived", "instructions_per_agent"), "cycles_per_agent": ("derived", "cycles_per_agent"),
             "task_clock_ms_per_agent": ("derived", "task_clock_ms_per_agent")}
    aggregates = {}
    for count in counts:
        group = [sample for sample in samples if sample["fixture"]["agents"] == count]
        row = {"agents": count, "samples": len(group), "cpu_binding": group[0]["derived"]["cpu_binding"]}
        for name, path in paths.items():
            values = [v for sample in group if (v := value_at(sample, path)) is not None]
            row[name] = None if not values else {"median": statistics.median(values), "min": min(values), "max": max(values)}
        aggregates[str(count)] = row
    baseline_count = counts[0]
    baseline = aggregates[str(baseline_count)]["agents_per_second"]["median"]
    scaling = {}
    for count in counts:
        throughput = aggregates[str(count)]["agents_per_second"]["median"]
        speedup = throughput / baseline
        scaling[str(count)] = {"agents": count, "throughput_speedup": speedup,
                               "parallel_efficiency": speedup / (count / baseline_count)}
    return aggregates, scaling


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agents", type=parse_counts, default=parse_counts("1,2,4,8,16,32"))
    parser.add_argument("--repeats", type=int, default=5); parser.add_argument("--tool-steps", type=int, default=64)
    parser.add_argument("--payload-bytes", type=int, default=64); parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--perf", choices=("auto", "on", "off"), default="auto")
    parser.add_argument("--hard-pin", action="store_true",
                        help="pin each Agent to a single core via taskset; default shares a cpuset")
    parser.add_argument("--node", type=Path); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or args.tool_steps < 1 or args.payload_bytes < 1: parser.error("repeats, tool-steps, payload-bytes positive")
    root = Path(__file__).resolve().parents[2]; node = (args.node or default_node(root)).resolve()
    controller = root / "scripts/cpu/c7-scaleout-controller.mjs"; cpus, topology = physical_cpu_candidates()
    if max(args.agents) > len(cpus): parser.error(f"need {max(args.agents)} physical cores, found {len(cpus)}")
    available = perf_works()
    if args.perf == "on" and not available: parser.error("perf requested but unavailable")
    use_perf = args.perf == "on" or (args.perf == "auto" and available)
    schedule = [count for count in args.agents for _ in range(args.repeats)]; random.Random(args.seed).shuffle(schedule)
    samples = []
    for index, count in enumerate(schedule, 1):
        sample = run_sample(node, controller, count, args.tool_steps, args.payload_bytes, cpus, use_perf, args.hard_pin)
        sample["sample_index"] = index; samples.append(sample)
        print(f"[C7 {index}/{len(schedule)}] agents={count} wall_ms={sample['fixture']['timing']['wall_ns']/1e6:.1f} "
              f"agents/s={sample['fixture']['timing']['agents_per_second']:.2f}", flush=True)
    aggregates, scaling = summarize(samples, args.agents)
    result = {"benchmark": "C7 multi-process DSH Agent scale-out", "created_at": datetime.now(timezone.utc).isoformat(),
              "design": {"agents": args.agents, "repeats": args.repeats, "tool_steps_per_agent": args.tool_steps,
                         "payload_bytes": args.payload_bytes, "topology": "one independent Node/DSH process per Agent",
"cpu_selection": "first logical CPU for each distinct (socket, core), nested prefixes",
                          "placement": "hard_pin (one core per Agent)" if args.hard_pin else "shared cpuset (scheduler may migrate)",
                          "selected_physical_cpu_ids": cpus[:max(args.agents)], "randomization_seed": args.seed,
                         "perf_enabled": use_perf, "perf_descendant_inheritance": True,
                         "perf_events": PERF_EVENTS if use_perf else [], "observed_perf_event_labels": samples[0]["perf_event_labels"]},
              "host": {"platform": platform.platform(), "machine": platform.machine(), "logical_cpus": os.cpu_count(),
                       "lscpu_parse": topology, "node": subprocess.run([str(node), "--version"], text=True, capture_output=True, check=True).stdout.strip(),
                       "perf": subprocess.run(["perf", "--version"], text=True, capture_output=True).stdout.strip(),
                       "perf_event_paranoid": Path("/proc/sys/kernel/perf_event_paranoid").read_text().strip()},
              "aggregates": aggregates, "scaling": scaling, "samples": samples,
              "limitations": ["Every Agent is an independent process; shared-process concurrency is a separate topology.",
                 "The deterministic adapter removes network/model contention; every Agent performs 64 no-op tool steps.",
                 "Process startup, DSH composition, the measured turn, and teardown are all inside batch wall/perf scope.",
                 "sum_child_max_rss_kb sums per-process maxima and is not a synchronized aggregate peak.",
"CPU sets use one thread per physical core and nested prefixes but do not spread across NUMA nodes.",
                  "In hard_pin mode each Agent is pinned to one core and the controller itself is unpinned.",
                  "Default cycles/instructions are user+kernel totals; cycles:k/instructions:k are sampled separately and derived *_u / *_kernel_ratio split user from kernel. A perf restriction to user space will omit the kernel fields."],}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(result, indent=2)+"\n")
    print(f"[done] wrote {args.output}")


if __name__ == "__main__": main()
