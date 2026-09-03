#!/usr/bin/env python3
"""Validate the committed C8 pilots and render their Markdown report."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


FILES = {
    "cold": "c8-token-meter-cold-pilot.json",
    "incremental": "c8-token-meter-incremental-pilot.json",
    "repeat": "c8-token-meter-repeat-pilot.json",
    "text": "c8-token-meter-shape-text-pilot.json",
    "tool-call": "c8-token-meter-shape-tool-call-pilot.json",
    "tool-result": "c8-token-meter-shape-tool-result-pilot.json",
    "schema": "c8-token-meter-shape-schema-pilot.json",
}


def load_and_validate(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    sizes = data["design"]["input_sizes"]
    expected_samples = len(sizes) * data["design"]["repeats"]
    samples = data["samples"]
    if len(samples) != expected_samples:
        raise ValueError(f"{path}: expected {expected_samples} samples, found {len(samples)}")
    for index, sample in enumerate(samples, start=1):
        checks = sample["fixture"]["checks"]
        if not checks or not all(checks.values()):
            raise ValueError(f"{path}: sample {index} has failed checks: {checks}")
    for size in sizes:
        group = [sample for sample in samples if sample["fixture"]["surface_events"] == size]
        actual = statistics.median(
            sample["derived"]["internal_cpu_us_per_measure"] for sample in group
        )
        reported = data["aggregates"][str(size)]["internal_cpu_us_per_measure"]["median"]
        if actual != reported:
            raise ValueError(f"{path}: aggregate mismatch at size {size}: {actual} != {reported}")
    return data


def aggregate_median(data: dict[str, Any], size: int, metric: str) -> float:
    return float(data["aggregates"][str(size)][metric]["median"])


def fit(data: dict[str, Any], metric: str = "internal_cpu_us_per_measure") -> dict[str, float]:
    return data["linear_fits"][metric]


def fixture_for(data: dict[str, Any], size: int) -> dict[str, Any]:
    return next(
        sample["fixture"]
        for sample in data["samples"]
        if sample["fixture"]["surface_events"] == size
    )


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--output", type=Path, default=Path("results/C8_REPORT.md"))
    args = parser.parse_args()

    results = {name: load_and_validate(args.results_dir / filename) for name, filename in FILES.items()}
    cold, incremental, repeat = (results[name] for name in ("cold", "incremental", "repeat"))
    cold_fit, incremental_fit, repeat_fit = (fit(data) for data in (cold, incremental, repeat))
    sizes = repeat["design"]["input_sizes"]
    shape_names = ("text", "tool-call", "tool-result")
    shape_size = results["text"]["design"]["input_sizes"][0]
    shape_cpu = {
        name: aggregate_median(results[name], shape_size, "internal_cpu_us_per_measure")
        for name in shape_names
    }
    shape_spread = (max(shape_cpu.values()) - min(shape_cpu.values())) / min(shape_cpu.values()) * 100
    schema = results["schema"]
    schema_sizes = schema["design"]["input_sizes"]
    schema_fit = fit(schema)
    schema_us_per_kb = schema_fit["per_schema_byte_slope"] * 1000
    replay_ratio = cold_fit["per_surface_node_slope"] / repeat_fit["per_surface_node_slope"]
    host = repeat["host"]

    lines = [
        "# C8 token-meter / context-pressure CPU pilot",
        "",
        "C8 measures the pinned DeepSeek Harness `TokenMeter.measure(session)` path, not a",
        "tokenizer. The pinned implementation uses a fixed `char/4` text heuristic. A",
        "measurement synchronizes only unread durable events, reprices every current",
        "surface node, then structured-clones and deep-freezes the detached result.",
        "",
        "## Design",
        "",
        "- `cold`: first measurement over a complete unread history.",
        "- `incremental`: append one text turn and measure repeatedly after an initial sync.",
        "- `repeat`: fixed, already-synced session; full surface reprice + clone only.",
        "- non-schema `shape`: first cold replay of equal event/node counts containing",
        "  `text`, `tool-call`, or `tool-result` messages, so original block pricing is timed.",
        "- `schema`: repeated header measurement over a pre-synced 32-node surface; exact",
        "  schema, baseline, and total-token invariants are verified.",
        f"- Main node counts: {', '.join(f'{size:,}' for size in sizes)}; payload 256 B.",
        f"- Repetitions: {repeat['design']['repeats']} per point; affinity CPU {repeat['design']['cpu_affinity']}.",
        f"- Runtime: {host['machine']}, {host['node']}, perf mode `{repeat['design']['perf_mode']}`.",
        "- Primary metrics are internal `process.cpuUsage()` and `hrtime` around the stated",
        "  measurement window. Whole-process PMU counters are diagnostic only.",
        "",
        "## Results",
        "",
        "Linear fits over point medians:",
        "",
        "| Subtest | CPU slope (us/node) | CPU intercept (us) |",
        "| --- | ---: | ---: |",
        f"| cold | {fmt(cold_fit['per_surface_node_slope'])} | {fmt(cold_fit['intercept'], 0)} |",
        f"| incremental | {fmt(incremental_fit['per_surface_node_slope'])} | {fmt(incremental_fit['intercept'], 0)} |",
        f"| repeat | {fmt(repeat_fit['per_surface_node_slope'])} | {fmt(repeat_fit['intercept'], 0)} |",
        "",
        "Repeat medians:",
        "",
        "| Surface nodes | internal CPU (us) | wall (us) |",
        "| ---: | ---: | ---: |",
    ]
    for size in sizes:
        cpu = aggregate_median(repeat, size, "internal_cpu_us_per_measure")
        wall = aggregate_median(repeat, size, "internal_wall_ns_per_measure") / 1000
        lines.append(f"| {size:,} | {fmt(cpu, 0)} | {fmt(wall, 0)} |")

    lines += [
        "",
        f"Cold shape replay at {shape_size:,} surface nodes (five durable events per node",
        "in every condition):",
        "",
        "| Shape | internal CPU (us) | wall (us) | heuristic tokens/node |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in shape_names:
        data = results[name]
        cpu = aggregate_median(data, shape_size, "internal_cpu_us_per_measure")
        wall = aggregate_median(data, shape_size, "internal_wall_ns_per_measure") / 1000
        fixture = fixture_for(data, shape_size)
        tokens_per_node = fixture["surface_tokens"] / fixture["surface_nodes"]
        lines.append(f"| {name} | {fmt(cpu, 0)} | {fmt(wall, 0)} | {fmt(tokens_per_node, 1)} |")

    lines += [
        "",
        "Schema header measurement:",
        "",
        "| Tools | schema bytes | schema tokens | internal CPU (us) |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for size in schema_sizes:
        fixture = fixture_for(schema, size)
        cpu = aggregate_median(schema, size, "internal_cpu_us_per_measure")
        lines.append(
            f"| {size:,} | {fixture['schema_bytes']:,} | {fixture['schema_tokens']:,} | {fmt(cpu, 0)} |"
        )

    lines += [
        "",
        "## Interpretation",
        "",
        f"1. Repeat measurement is linear over this range at {fmt(repeat_fit['per_surface_node_slope'])}",
        "   us of CPU per retained surface node. This is the steady-state full-surface",
        "   reprice + clone cost, not event replay.",
        "",
        f"2. Cold first measurement is about {fmt(replay_ratio, 1)}x more expensive per surface",
        "   node for this fixed three-event text-turn log because it must also fold every",
        "   unread event and price the original message.",
        "",
        f"3. Incremental append + measure tracks repeat scan ({fmt(incremental_fit['per_surface_node_slope'])}",
        f"   vs {fmt(repeat_fit['per_surface_node_slope'])} us/node). Append synchronizes the new",
        "   tail, but the following measure still reprices and clones the complete surface.",
        "",
        f"4. Cold replay shape differed by {fmt(shape_spread, 1)}% peak-to-peak at {shape_size:,}",
        "   nodes in this ASCII 256 B fixture. This result includes message derivation and",
        "   heuristic pricing, but does not cover reasoning, images, or provider image pricing.",
        "",
        f"5. Schema's marginal fitted cost is {fmt(schema_us_per_kb)} us per decimal KB over",
        "   the measured range. The total measurement also contains the fixed 32-node surface",
        "   scan, represented by the fitted intercept; marginal schema cost must not be confused",
        "   with total `measure()` latency.",
        "",
        "## Limitations",
        "",
        "- Token counts use a fixed heuristic, not a provider BPE tokenizer.",
        "- Internal CPU timing has no scoped PMU counters. Whole-process perf includes Node",
        "  startup, Session construction, measured calls, and teardown and is diagnostic only.",
        "- Cold and repeat use different replay state by design; their difference is a mechanism",
        "  decomposition, not an interchangeable production latency comparison.",
        "- Linear-fit intercepts are descriptive over the measured points and may be negative;",
        "  they are not physical zero-node cost estimates.",
        "- The incremental x-axis is the midpoint surface size `N + (K+1)/2` of each batch.",
        "- This is a same-host mechanism pilot, not a cross-processor performance claim.",
        "",
        "All table values are generated from the corresponding",
        "`results/c8-token-meter-*-pilot.json` files by",
        "`scripts/cpu/render-c8-report.py`; the generator validates sample counts, fixture",
        "checks, and aggregate medians before writing this report. Run",
        "`scripts/cpu/verify-cpu-results.py` to additionally verify protocol hashes and",
        "recompute every C8 aggregate and linear fit from the committed samples.",
        "",
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
