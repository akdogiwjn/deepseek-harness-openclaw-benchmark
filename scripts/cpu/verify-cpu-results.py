#!/usr/bin/env python3
"""Validate CPU pilot provenance, fixture checks, and aggregate derivations."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_runner(path: Path) -> Any:
    name = path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def false_checks(value: Any, path: str = "$") -> list[str]:
    failures: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key == "checks" and isinstance(item, dict):
                for check, passed in item.items():
                    if isinstance(passed, bool) and not passed:
                        failures.append(f"{child}.{check}")
            failures.extend(false_checks(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            failures.extend(false_checks(item, f"{path}[{index}]"))
    return failures


def verify_protocol(root: Path, result: dict[str, Any], label: str) -> None:
    protocol = result.get("protocol")
    if not isinstance(protocol, dict) or protocol.get("schema_version") != 1:
        raise ValueError(f"{label}: protocol provenance is absent")
    files = protocol.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError(f"{label}: protocol file hashes are absent")
    identity = hashlib.sha256()
    for relative, expected in sorted(files.items()):
        path = root / relative
        actual = sha256(path)
        if actual != expected:
            raise ValueError(f"{label}: protocol file changed: {relative}")
        identity.update(relative.encode("utf-8"))
        identity.update(b"\0")
        identity.update(actual.encode("ascii"))
        identity.update(b"\n")
    if identity.hexdigest() != protocol.get("protocol_sha256"):
        raise ValueError(f"{label}: protocol identity is inconsistent")
    revisions = dict(
        line.split("=", 1)
        for line in (root / "configs/revisions.env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    if protocol.get("source_revisions") != revisions:
        raise ValueError(f"{label}: pinned upstream revisions differ")


def verify_result(
    root: Path,
    path: Path,
    runner_name: str,
    design_key: str,
    summarize: Callable[[Any, list[int]], tuple[Any, ...]],
    expected_keys: tuple[str, ...],
) -> None:
    result = load(path)
    verify_protocol(root, result, path.name)
    failures = false_checks(result.get("samples", []))
    if failures:
        raise ValueError(f"{path.name}: failed fixture checks: {failures}")
    dimensions = result["design"][design_key]
    derived = summarize(result["samples"], dimensions)
    if len(derived) != len(expected_keys):
        raise ValueError(f"{path.name}: unexpected aggregate result count")
    for key, value in zip(expected_keys, derived):
        if result.get(key) != value:
            raise ValueError(f"{path.name}: {key} does not match samples")
    repeats = result["design"]["repeats"]
    conditions = 1
    for key in ("conditions", "modes"):
        if key in result["design"]:
            conditions = len(result["design"][key])
    expected_samples = len(dimensions) * repeats * conditions
    if len(result["samples"]) != expected_samples:
        raise ValueError(f"{path.name}: expected {expected_samples} samples")
    print(f"[verified] {path.name}: protocol, {expected_samples} samples, checks, aggregates")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / "scripts" / "cpu"))
    cases = [
        ("c1-agent-loop-pilot.json", "run-c1.py", "steps", "aggregate", ("aggregates", "linear_fits_over_step_medians")),
        ("c2-session-count-pilot.json", "run-c2.py", "turns", "aggregate", ("aggregates", "linear_fits_over_event_count_medians")),
        ("c3-context-json-pilot.json", "run-c3.py", "context_bytes", "aggregate", ("aggregates", "linear_fits_over_context_byte_medians")),
        ("c4-shell-lifecycle-pilot.json", "run-c4.py", "operations", "summarize", ("aggregates", "linear_fits_over_operation_count_medians")),
        ("c5-code-mode-cpu-pilot.json", "run-c5.py", "operations", "summarize", ("aggregates", "linear_fits_over_operation_count_medians", "comparisons")),
        ("c6-fs-sandbox-cpu-pilot.json", "run-c6.py", "operations", "summarize", ("aggregates", "linear_fits_over_operation_count_medians", "comparisons")),
        ("c7-agent-scaleout-pilot.json", "run-c7.py", "agents", "summarize", ("aggregates", "scaling")),
    ]
    for result_name, runner_name, design_key, function_name, keys in cases:
        module = load_runner(root / "scripts" / "cpu" / runner_name)
        verify_result(
            root,
            root / "results" / result_name,
            runner_name,
            design_key,
            getattr(module, function_name),
            keys,
        )
    c8_names = (
        "c8-token-meter-cold-pilot.json",
        "c8-token-meter-incremental-pilot.json",
        "c8-token-meter-repeat-pilot.json",
        "c8-token-meter-shape-schema-pilot.json",
        "c8-token-meter-shape-text-pilot.json",
        "c8-token-meter-shape-tool-call-pilot.json",
        "c8-token-meter-shape-tool-result-pilot.json",
    )
    c8_runner = load_runner(root / "scripts" / "cpu" / "run-c8.py")
    for name in c8_names:
        path = root / "results" / name
        result = load(path)
        verify_protocol(root, result, path.name)
        failures = false_checks(result.get("samples", []))
        if failures:
            raise ValueError(f"{path.name}: failed fixture checks: {failures}")
        expected_samples = len(result["design"]["input_sizes"]) * result["design"]["repeats"]
        if len(result["samples"]) != expected_samples:
            raise ValueError(f"{path.name}: expected {expected_samples} samples")
        aggregates, fits = c8_runner.aggregate(
            result["samples"], result["design"]["input_sizes"]
        )
        if result.get("aggregates") != aggregates:
            raise ValueError(f"{path.name}: aggregates do not match samples")
        if result.get("linear_fits") != fits:
            raise ValueError(f"{path.name}: linear_fits do not match samples")
        print(
            f"[verified] {path.name}: protocol, {expected_samples} samples, "
            "checks, aggregates"
        )
    print("[done] CPU pilot results are bound to current protocol files and validated")


if __name__ == "__main__":
    main()
