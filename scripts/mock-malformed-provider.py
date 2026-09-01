#!/usr/bin/env python3
"""Deterministic OpenAI-compatible SSE server for malformed tool-call recovery."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


MALFORMED_CHUNKS = [
    {
        "id": "mock-malformed",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_malformed",
                            "type": "function",
                            "function": {"name": "", "arguments": "{"},
                        }
                    ],
                },
                "finish_reason": None,
            }
        ],
    },
    {
        "id": "mock-malformed",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "deepseek-v4-flash",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
    },
]

RECOVERY_CHUNKS = [
    {
        "id": "mock-recovery",
        "object": "chat.completion.chunk",
        "created": 2,
        "model": "deepseek-v4-flash",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "RECOVERED_AFTER_MALFORMED_TOOL_CALL"},
                "finish_reason": None,
            }
        ],
    },
    {
        "id": "mock-recovery",
        "object": "chat.completion.chunk",
        "created": 2,
        "model": "deepseek-v4-flash",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
    },
]


class State:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.lock = threading.Lock()
        self.requests = 0

    def next_request(self, path: str) -> int:
        with self.lock:
            self.requests += 1
            number = self.requests
            record = {"request": number, "path": path, "time_ns": time.time_ns()}
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record) + "\n")
            return number


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarnessRecoveryMock/1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        request_number = self.server.state.next_request(self.path)  # type: ignore[attr-defined]
        chunks = MALFORMED_CHUNKS if request_number == 1 else RECOVERY_CHUNKS
        body = "".join(f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n" for chunk in chunks)
        body += "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
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
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state = State(args.log)  # type: ignore[attr-defined]
    print(json.dumps({"ready": True, "port": args.port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
