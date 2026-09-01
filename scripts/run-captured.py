#!/usr/bin/env python3
"""Run a benchmark command and persist its raw process result as JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("a command is required")

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    completed = subprocess.run(args.command, text=True, capture_output=True)
    record = {
        "started_at": started_at,
        "wall_seconds": time.monotonic() - started,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("started_at", "wall_seconds", "exit_code")}))
    if completed.returncode:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
