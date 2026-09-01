#!/usr/bin/env python3
"""Deterministic provider for the W10 native tool-fs capability seam swap."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def chunks(number: int, name: str | None, arguments: dict[str, Any] | None) -> list[dict[str, Any]]:
    if name is None:
        first_delta: dict[str, Any] = {"role": "assistant", "content": "COMPLETED_W10_FS_SEAM"}
        finish = "stop"
    else:
        first_delta = {
            "role": "assistant",
            "tool_calls": [{
                "index": 0,
                "id": f"callw10{number:03d}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, separators=(",", ":")),
                },
            }],
        }
        finish = "tool_calls"
    return [
        {
            "id": f"mock-w10-{number:03d}",
            "object": "chat.completion.chunk",
            "created": number,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": first_delta, "finish_reason": None}],
        },
        {
            "id": f"mock-w10-{number:03d}",
            "object": "chat.completion.chunk",
            "created": number,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


SCRIPT = [
    ("read", {"file_path": "inside.txt"}),
    ("edit", {"file_path": "inside.txt", "old_string": "INSIDE_ORIGINAL", "new_string": "INSIDE_CHANGED"}),
    ("edit", {"file_path": "../outside/outside.txt", "old_string": "OUTSIDE_ORIGINAL", "new_string": "OUTSIDE_CHANGED"}),
    (None, None),
]


class State:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.lock = threading.Lock()
        self.requests = 0

    def handle(self, path: str, raw: bytes, body: dict[str, Any]) -> list[dict[str, Any]]:
        with self.lock:
            self.requests += 1
            number = self.requests
            if number > len(SCRIPT):
                raise ValueError(f"unexpected request {number}")
            tools = body.get("tools", [])
            canonical_tools = json.dumps(tools, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            schemas = {
                item.get("function", {}).get("name"): item.get("function", {}).get("parameters", {})
                for item in tools if isinstance(item, dict)
            }
            expected_name, expected_args = SCRIPT[number - 1]
            record = {
                "request": number,
                "path": path,
                "time_ns": time.time_ns(),
                "request_body_bytes": len(raw),
                "message_count": len(body.get("messages", [])),
                "tool_names": list(schemas),
                "tool_schema_sha256": hashlib.sha256(canonical_tools.encode()).hexdigest(),
                "edit_properties": sorted(schemas.get("edit", {}).get("properties", {})),
                "messages": body.get("messages", []),
                "scripted_tool": expected_name,
                "scripted_arguments": expected_args,
            }
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        return chunks(number, expected_name, expected_args)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarnessW10Mock/1"

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw)
            chunks_out = self.server.state.handle(self.path, raw, body)  # type: ignore[attr-defined]
        except Exception as error:
            self.send_error(400, str(error))
            return
        payload = "".join(
            f"data: {json.dumps(item, separators=(',', ':'))}\n\n" for item in chunks_out
        ) + "data: [DONE]\n\n"
        encoded = payload.encode()
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
