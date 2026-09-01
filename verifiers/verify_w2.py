#!/usr/bin/env python3
"""External verifier for W2, including cases absent from the visible tests."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


VISIBLE_TEST_SHA256 = "d6bfdea85bf05926ae7026eb88c7dcd4328a970e9304a512cc9f5261b9f3a404"


def check_equal(actual: object, expected: object, label: str) -> None:
    if actual != expected:
        raise SystemExit(f"FAIL: {label}: expected {expected!r}, got {actual!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()

    test_file = workspace / "tests" / "test_parser.py"
    digest = hashlib.sha256(test_file.read_bytes()).hexdigest()
    check_equal(digest, VISIBLE_TEST_SHA256, "visible tests were modified")

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise SystemExit(f"FAIL: pytest failed\n{completed.stdout}\n{completed.stderr}")

    sys.path.insert(0, str(workspace))
    module = importlib.import_module("retry_parser.parser")
    parse = module.retry_after_seconds

    utc = timezone.utc
    check_equal(parse("0007"), 7, "leading-zero delta")
    check_equal(parse("+7"), 7, "signed non-negative delta")
    check_equal(parse("1.5"), None, "fractional delta")

    now = datetime(2015, 10, 21, 7, 27, 30, tzinfo=utc)
    check_equal(parse("Wed, 21 Oct 2015 07:28:01 +0000", now=now), 31, "numeric-zone HTTP date")
    check_equal(parse("Wed, 21 Oct 2015 07:20:00 GMT", now=now), 0, "past HTTP date")
    check_equal(
        parse("Wed, 21 Oct 2015 07:28:00 GMT", now=now.replace(tzinfo=None)),
        30,
        "naive now interpreted as UTC",
    )
    plus_two = timezone(timedelta(hours=2))
    check_equal(
        parse("Wed, 21 Oct 2015 07:28:00 GMT", now=datetime(2015, 10, 21, 9, 27, 30, tzinfo=plus_two)),
        30,
        "aware now with non-UTC offset",
    )
    check_equal(parse("not a real date", now=now), None, "malformed HTTP date")

    print("PASS: pytest and hidden Retry-After cases passed; visible tests unchanged")


if __name__ == "__main__":
    main()
