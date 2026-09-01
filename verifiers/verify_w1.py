#!/usr/bin/env python3
"""Verify the exact W1 file transformation without third-party dependencies."""

from __future__ import annotations

import argparse
from pathlib import Path


EXPECTED = """service:
  name: demo-api
  timeout: 45  # seconds
  retries:
    count: 3
    timeout: 5

database:
  host: localhost
  timeout: 30
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    actual = (args.workspace / "config.yaml").read_text(encoding="utf-8")
    if actual != EXPECTED:
        raise SystemExit("FAIL: config.yaml does not match the exact expected transformation")
    print("PASS: only service.timeout changed from 30 to 45")


if __name__ == "__main__":
    main()
