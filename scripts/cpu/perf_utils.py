#!/usr/bin/env python3
"""Shared perf capability probe and CSV parsing for the CPU runners.

Keeps the probe (which events are collectable on this host) and the parser
(user/kernel split plus derived ratios) in one place so the C1-C8 runners do not
drift. Events are split into required versus optional: a CPU or kernel that lacks
an optional event only drops that counter instead of disabling perf entirely.
"""

from __future__ import annotations

import math
import shutil
import subprocess

REQUIRED_EVENTS = ["task-clock", "cycles:u", "instructions:u"]
KERNEL_SPLIT_EVENTS = ["cycles:k", "instructions:k"]
OPTIONAL_EVENTS = [
    "branches", "branch-misses", "cache-references", "cache-misses",
    "context-switches", "cpu-migrations", "page-faults",
]
_SPLIT_NAMES = frozenset(("cycles", "instructions"))


def _run(perf: str, events: list[str]) -> bool:
    completed = subprocess.run(
        [perf, "stat", "-x,", "-e", ",".join(events), "--", "true"],
        text=True, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        return False
    numeric_labels: set[str] = set()
    for line in completed.stderr.splitlines():
        fields = line.split(",")
        if len(fields) < 3:
            continue
        label = fields[2].strip()
        try:
            if math.isfinite(float(fields[0].strip())):
                numeric_labels.add(label)
        except ValueError:
            continue
    return all(
        event in numeric_labels if ":" in event
        else any(label.split(":", 1)[0] == event for label in numeric_labels)
        for event in events
    )


def _probe_optional(perf: str) -> list[str]:
    available: list[str] = []
    for event in OPTIONAL_EVENTS:
        if _run(perf, [event]):
            available.append(event)
    return available


def probe_perf() -> tuple[str, list[str]]:
    """Return (mode, events): mode in user-kernel/user-only/off plus the event list to pass to perf."""
    perf = shutil.which("perf")
    if perf is None:
        return "off", []
    full_events = REQUIRED_EVENTS + KERNEL_SPLIT_EVENTS
    if _run(perf, full_events):
        return "user-kernel", full_events + _probe_optional(perf)
    if _run(perf, REQUIRED_EVENTS):
        return "user-only", REQUIRED_EVENTS + _probe_optional(perf)
    return "off", []


def parse_perf(stderr: str) -> tuple[dict[str, float | None], dict[str, str]]:
    metrics: dict[str, float | None] = {}
    labels: dict[str, str] = {}
    base_names = {event.split(":", 1)[0] for event in REQUIRED_EVENTS + KERNEL_SPLIT_EVENTS + OPTIONAL_EVENTS}
    for line in stderr.splitlines():
        fields = line.split(",")
        if len(fields) < 3:
            continue
        label = fields[2].strip()
        base = label.split(":", 1)[0]
        if base not in base_names:
            continue
        key = label.replace(":", "_") if base in _SPLIT_NAMES else base
        try:
            metrics[key] = float(fields[0].strip())
        except ValueError:
            metrics[key] = None
        labels[key] = label
    for base in _SPLIT_NAMES:
        user = metrics.get(f"{base}_u")
        kernel = metrics.get(f"{base}_k")
        if user is not None:
            total = user + (kernel or 0.0)
            metrics[base] = total
            if kernel is not None and total:
                metrics[f"{base}_kernel_ratio"] = kernel / total
    return metrics, labels
