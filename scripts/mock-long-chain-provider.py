#!/usr/bin/env python3
"""Deterministic OpenAI-compatible SSE server for a sequential tool chain."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


FINAL_MARKER = "COMPLETED_W7_LONG_TOOL_CHAIN"


def chunks_for_tool(step: int, tool_name: str) -> list[dict[str, Any]]:
    marker = f"W7_STEP_{step:03d}"
    return [
        {
            "id": f"mock-w7-{step:03d}",
            "object": "chat.completion.chunk",
            "created": step,
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": f"callw7step{step:03d}",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(
                                        {"command": f"printf '{marker}\\n'"},
                                        separators=(",", ":"),
                                    ),
                                },
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": f"mock-w7-{step:03d}",
            "object": "chat.completion.chunk",
            "created": step,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


def final_chunks() -> list[dict[str, Any]]:
    return [
        {
            "id": "mock-w7-final",
            "object": "chat.completion.chunk",
            "created": 999,
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": FINAL_MARKER},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "mock-w7-final",
            "object": "chat.completion.chunk",
            "created": 999,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


class State:
    def __init__(self, log_path: Path, steps: int) -> None:
        self.log_path = log_path
        self.steps = steps
        self.lock = threading.Lock()
        self.requests = 0

    def record(self, path: str, raw: bytes, body: dict[str, Any]) -> int:
        with self.lock:
            self.requests += 1
            number = self.requests
            messages = body.get("messages", [])
            tools = body.get("tools", [])
            expected_previous = f"W7_STEP_{number - 1:03d}" if number > 1 else None
            messages_json = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
            record = {
                "request": number,
                "path": path,
                "time_ns": time.time_ns(),
                "request_body_bytes": len(raw),
                "message_count": len(messages),
                "messages_bytes": len(messages_json.encode("utf-8")),
                "tool_schema_bytes": len(
                    json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ),
                "tool_names": [
                    item.get("function", {}).get("name", "")
                    for item in tools
                    if isinstance(item, dict)
                ],
                "expected_previous_marker": expected_previous,
                "previous_marker_present": (
                    expected_previous in messages_json if expected_previous is not None else None
                ),
            }
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            return number


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarnessLongChainMock/1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw)
        state: State = self.server.state  # type: ignore[attr-defined]
        request_number = state.record(self.path, raw, body)

        if request_number <= state.steps:
            declared = {
                item.get("function", {}).get("name", "")
                for item in body.get("tools", [])
                if isinstance(item, dict)
            }
            tool_name = "bash" if "bash" in declared else "exec"
            if tool_name not in declared:
                self.send_error(400, "neither bash nor exec was declared")
                return
            chunks = chunks_for_tool(request_number, tool_name)
        else:
            chunks = final_chunks()

        payload = "".join(
            f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n" for chunk in chunks
        ) + "data: [DONE]\n\n"
        encoded = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()
    if args.steps < 1 or args.steps > 100:
        parser.error("steps must be between 1 and 100")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state = State(args.log, args.steps)  # type: ignore[attr-defined]
    print(json.dumps({"ready": True, "port": args.port, "steps": args.steps}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
