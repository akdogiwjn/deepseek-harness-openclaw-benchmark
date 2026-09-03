#!/usr/bin/env python3
"""Rebuild W1-W3 final workspaces and re-run their external verifiers."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


TREE_IGNORES = {".git", ".pytest_cache", "__pycache__"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if any(part in TREE_IGNORES for part in relative.parts):
            continue
        encoded = relative.as_posix().encode("utf-8")
        if path.is_symlink():
            digest.update(b"L\0" + encoded + b"\0" + path.readlink().as_posix().encode("utf-8") + b"\n")
        elif path.is_file():
            executable = b"x" if path.stat().st_mode & 0o111 else b"-"
            digest.update(b"F" + executable + b"\0" + encoded + b"\0" + sha256(path).encode("ascii") + b"\n")
        elif path.is_dir():
            digest.update(b"D\0" + encoded + b"\n")
    return digest.hexdigest()


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def init_baseline(workspace: Path) -> None:
    for generated in (".git", ".pytest_cache", "__pycache__"):
        path = workspace / generated
        if path.is_dir():
            shutil.rmtree(path)
    completed = run("git", "init", "-q", cwd=workspace)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    for key, value in (("user.name", "Evidence Verifier"), ("user.email", "evidence@localhost")):
        completed = run("git", "config", key, value, cwd=workspace)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
    for command in (("git", "add", "."), ("git", "commit", "-qm", "baseline")):
        completed = run(*command, cwd=workspace)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)


def apply_overlay(evidence_dir: Path, workspace: Path, manifest: dict[str, Any]) -> None:
    listed = manifest["changed_or_untracked_files"]
    hashes = manifest["file_sha256"]
    for relative in manifest["deleted_files"]:
        target = workspace / relative
        if target.exists():
            target.unlink()
    for relative, expected_hash in hashes.items():
        if relative not in listed:
            raise ValueError(f"overlay hash is not listed as changed: {relative}")
        source = evidence_dir / "files" / relative
        if sha256(source) != expected_hash:
            raise ValueError(f"overlay hash mismatch: {source}")
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def verify_pair(root: Path, group: str, pair_dir: Path, scratch: Path) -> None:
    summary = load(pair_dir / "summary.json")
    manifest = load(pair_dir / "workspace-manifest.json")
    if manifest.get("schema_version") != 2:
        raise ValueError(f"{group}/{pair_dir.name}: unsupported workspace manifest")
    baseline = manifest["baseline"]
    template = root / baseline["template"]
    verifier = root / baseline["verifier"]
    if tree_sha256(template) != baseline["template_tree_sha256"]:
        raise ValueError(f"{group}/{pair_dir.name}: committed template differs from frozen baseline")
    if sha256(verifier) != baseline["verifier_sha256"]:
        raise ValueError(f"{group}/{pair_dir.name}: verifier differs from frozen provenance")
    manifests = manifest["workspaces"]
    for runtime, manifest in manifests.items():
        workspace = scratch / pair_dir.name / runtime
        shutil.copytree(template, workspace, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        init_baseline(workspace)
        apply_overlay(pair_dir / "workspaces" / runtime, workspace, manifest)
        completed = run(sys.executable, str(verifier), str(workspace))
        runtime_summary = summary[runtime]
        expected = bool(runtime_summary.get("verifier_passed"))
        if (completed.returncode == 0) != expected:
            raise ValueError(
                f"{group}/{pair_dir.name}/{runtime}: verifier outcome differs; "
                f"expected={expected}, exit={completed.returncode}, "
                f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
            )
        expected_diff = runtime_summary.get("diff_stat")
        if expected_diff is not None:
            actual_diff = run("git", "diff", "--stat", cwd=workspace)
            if actual_diff.returncode != 0 or actual_diff.stdout.strip() != expected_diff:
                raise ValueError(f"{group}/{pair_dir.name}/{runtime}: diff stat differs")
        expected_changed = runtime_summary.get("changed_files")
        if expected_changed is not None:
            actual = run("git", "status", "--short", cwd=workspace)
            if actual.returncode != 0 or actual.stdout.splitlines() != expected_changed:
                raise ValueError(f"{group}/{pair_dir.name}/{runtime}: changed-file list differs")
    print(f"[verified] {group}/{pair_dir.name} final workspaces and verifier outcomes")


def verify_aggregate(root: Path, evidence: Path, group: str, scratch: Path) -> None:
    summaries = sorted((evidence / group / "results").glob("*/summary.json"))
    target = root / "results" / f"{group.lower()}-aggregate-n{len(summaries)}.json"
    generated = scratch / f"{group.lower()}-aggregate.json"
    completed = run(
        sys.executable,
        str(root / "scripts" / "aggregate-pairs.py"),
        "--output",
        str(generated),
        *(str(path) for path in summaries),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    if load(generated) != load(target):
        raise ValueError(f"{group}: frozen summaries do not rebuild {target.name}")
    print(f"[verified] {group} frozen summaries rebuild {target.name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    evidence = (args.evidence or root / "evidence").resolve()
    with tempfile.TemporaryDirectory(prefix="harness-behavioral-evidence-") as directory:
        scratch = Path(directory)
        for group in ("W1", "W2", "W3"):
            for pair_dir in sorted((evidence / group / "results").iterdir()):
                if pair_dir.is_dir():
                    verify_pair(root, group, pair_dir, scratch)
        verify_aggregate(root, evidence, "W2", scratch)
        verify_aggregate(root, evidence, "W3", scratch)
    print("[done] W1-W3 behavioral evidence verified")


if __name__ == "__main__":
    main()
