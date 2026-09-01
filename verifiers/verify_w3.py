#!/usr/bin/env python3
"""External verifier for W3 weighted quota consumption."""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from pathlib import Path


def expect_value_error(call, label: str) -> None:
    try:
        call()
    except ValueError:
        return
    except Exception as exc:
        raise SystemExit(f"FAIL: {label} raised {type(exc).__name__}, expected ValueError") from exc
    raise SystemExit(f"FAIL: {label} did not raise ValueError")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise SystemExit(f"FAIL: pytest failed\n{completed.stdout}\n{completed.stderr}")

    changed_tests = subprocess.run(
        ["git", "-C", str(workspace), "diff", "--name-only", "--", "tests"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        ["git", "-C", str(workspace), "ls-files", "--others", "--exclude-standard", "--", "tests"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    if not changed_tests and not untracked:
        raise SystemExit("FAIL: no focused tests were added or changed")

    sys.path.insert(0, str(workspace))
    package = importlib.import_module("quota_guard")
    store = package.MemoryCounterStore()
    policy = package.RateLimitPolicy(default_limit=7, route_limits={"/tight": 5})
    service = package.RateLimitService(policy, store)

    first = service.check("alice", "/tight", cost=3)
    if (first.allowed, first.limit, first.remaining) != (True, 5, 2):
        raise SystemExit(f"FAIL: first weighted decision is incorrect: {first!r}")

    denied = service.check("alice", "/tight", cost=3)
    if (denied.allowed, denied.limit, denied.remaining) != (False, 5, 2):
        raise SystemExit(f"FAIL: weighted denial was not atomic: {denied!r}")

    final = service.check("alice", "/tight", cost=2)
    if (final.allowed, final.limit, final.remaining) != (True, 5, 0):
        raise SystemExit(f"FAIL: rejected request changed stored usage: {final!r}")

    other = service.check("bob", "/tight", cost=5)
    if not other.allowed or other.remaining != 0:
        raise SystemExit(f"FAIL: client counters are not independent: {other!r}")

    invalid_service = package.RateLimitService(package.RateLimitPolicy(4), package.MemoryCounterStore())
    for invalid in (0, -1, 1.5, "2", True, False, None):
        expect_value_error(
            lambda invalid=invalid: invalid_service.check("bad", "/route", cost=invalid),
            f"invalid cost {invalid!r}",
        )
    after_invalid = invalid_service.check("bad", "/route", cost=4)
    if not after_invalid.allowed or after_invalid.remaining != 0:
        raise SystemExit("FAIL: invalid costs mutated the counter")

    compatibility = package.RateLimitService(package.RateLimitPolicy(2), package.MemoryCounterStore())
    if compatibility.check("legacy", "/route").remaining != 1:
        raise SystemExit("FAIL: default cost no longer preserves legacy behavior")

    print("PASS: pytest, added tests, weighted atomicity, validation, and compatibility passed")


if __name__ == "__main__":
    main()
