#!/usr/bin/env python3
"""Run one DeepSeek Harness sdk-minimal turn and emit a compact JSON result."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from deepseek_harness import DeepSeekHarness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    parser.add_argument("session_id")
    parser.add_argument("prompt")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    workspace = args.workspace.resolve()
    allowed_root = (root / "workspaces").resolve()
    if workspace != allowed_root and allowed_root not in workspace.parents:
        parser.error(f"workspace must be inside {allowed_root}")
    if not workspace.is_dir():
        parser.error(f"workspace does not exist: {workspace}")
    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        parser.error("DEEPSEEK_API_KEY is not set")

    started = time.monotonic()
    with DeepSeekHarness(
        provider="deepseek-official",
        model=os.environ.get("DSH_MODEL", "deepseek-v4-flash"),
        cwd=str(workspace),
        runtime_cwd=str(root / "sources" / "deepseek-harness"),
        dsh_home=str(root / "sessions" / "dsh-home"),
        dsh_bin=str(root / "sources" / "deepseek-harness" / "apps" / "cli" / "lib" / "bin.js"),
        profile="sdk-minimal",
    ) as harness:
        result = harness.run(args.prompt, session_id=args.session_id)

    print(
        json.dumps(
            {
                "runtime": "deepseek-harness-sdk-minimal",
                "model": os.environ.get("DSH_MODEL", "deepseek-v4-flash"),
                "session_id": result.session_id,
                "finish_reason": result.finish_reason,
                "wall_seconds": time.monotonic() - started,
                "final_response": result.final_response,
            },
            ensure_ascii=False,
        )
    )
    if result.finish_reason == "error":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
