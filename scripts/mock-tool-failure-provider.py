#!/usr/bin/env python3
"""Deterministic OpenAI-compatible SSE server for tool-failure handling."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


FINAL_MARKERS = {
    "nonzero": "RECOVERED_AFTER_NONZERO_EXIT",
    "invalid-args": "RECOVERED_AFTER_INVALID_TOOL_ARGUMENTS",
}


def completion_chunks(response_id: str, content: str) -> list[dict[str, Any]]:
    return [
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": 2,
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": 2,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24},
        },
    ]


def tool_chunks(tool_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": "mock-tool-failure",
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
                                "id": "call_tool_failure",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(arguments, separators=(",", ":")),
                                },
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": "mock-tool-failure",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    ]


class State:
    def __init__(self, log_path: Path, scenario: str) -> None:
        self.log_path = log_path
        self.scenario = scenario
        self.lock = threading.Lock()
        self.requests = 0

    def record(self, path: str, body: dict[str, Any]) -> int:
        with self.lock:
            self.requests += 1
            number = self.requests
            tools = body.get("tools", [])
            tool_names = [
                item.get("function", {}).get("name", "")
                for item in tools
                if isinstance(item, dict)
            ]
            record = {
                "request": number,
                "path": path,
                "time_ns": time.time_ns(),
                "tool_names": tool_names,
                "messages": body.get("messages", []),
            }
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            return number


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarnessToolFailureMock/1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        state: State = self.server.state  # type: ignore[attr-defined]
        request_number = state.record(self.path, body)

        if request_number == 1:
            declared = {
                item.get("function", {}).get("name", "")
                for item in body.get("tools", [])
                if isinstance(item, dict)
            }
            tool_name = "bash" if "bash" in declared else "exec"
            if tool_name not in declared:
                self.send_error(400, "neither bash nor exec was declared")
                return
            if state.scenario == "nonzero":
                arguments = {
                    "command": (
                        "sh -c \"printf 'W6_STDOUT\\\\n'; "
                        "printf 'W6_STDERR\\\\n' >&2; exit 17\""
                    )
                }
            else:
                arguments = {}
            chunks = tool_chunks(tool_name, arguments)
        else:
            chunks = completion_chunks(
                "mock-tool-failure-recovery", FINAL_MARKERS[state.scenario]
            )

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
    parser.add_argument("--scenario", choices=sorted(FINAL_MARKERS), required=True)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state = State(args.log, args.scenario)  # type: ignore[attr-defined]
    print(json.dumps({"ready": True, "port": args.port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
