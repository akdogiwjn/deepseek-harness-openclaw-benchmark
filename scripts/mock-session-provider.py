#!/usr/bin/env python3
"""Deterministic OpenAI-compatible SSE provider for W9 session fixtures."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def tool_chunks(number: int, command: str) -> list[dict[str, Any]]:
    call_id = f"callw9{number:03d}"
    return [
        {
            "id": f"mock-w9-{number:03d}",
            "object": "chat.completion.chunk",
            "created": number,
            "model": "deepseek-v4-flash",
            "choices": [{
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "tool_calls": [{
                        "index": 0,
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": "bash",
                            "arguments": json.dumps({"command": command}, separators=(",", ":")),
                        },
                    }],
                },
                "finish_reason": None,
            }],
        },
        {
            "id": f"mock-w9-{number:03d}",
            "object": "chat.completion.chunk",
            "created": number,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


def text_chunks(number: int, text: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"mock-w9-{number:03d}",
            "object": "chat.completion.chunk",
            "created": number,
            "model": "deepseek-v4-flash",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": text},
                "finish_reason": None,
            }],
        },
        {
            "id": f"mock-w9-{number:03d}",
            "object": "chat.completion.chunk",
            "created": number,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


class State:
    def __init__(self, log_path: Path, scenario: str) -> None:
        self.log_path = log_path
        self.scenario = scenario
        self.lock = threading.Lock()
        self.requests = 0

    def handle(self, path: str, raw: bytes, body: dict[str, Any]) -> list[dict[str, Any]]:
        with self.lock:
            self.requests += 1
            number = self.requests
            record = {
                "request": number,
                "path": path,
                "time_ns": time.time_ns(),
                "request_body_bytes": len(raw),
                "model": body.get("model"),
                "messages": body.get("messages", []),
                "tools": body.get("tools", []),
            }
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

        if self.scenario == "crash-resume":
            if number == 1:
                return tool_chunks(number, "printf 'W9_EFFECT_001\\n' >> effects.log")
            if number == 2:
                return tool_chunks(
                    number,
                    "printf 'W9_EFFECT_002_STARTED\\n' >> effects.log; "
                    "while :; do sleep 1; done",
                )
            if number == 3:
                return text_chunks(number, "COMPLETED_W9_CRASH_RESUME")
            raise ValueError(f"unexpected crash/resume request {number}")

        if number == 1:
            return tool_chunks(number, "printf 'W9_REPLAY_EFFECT\\n' >> replay.log")
        if number == 2:
            return text_chunks(number, "COMPLETED_W9_RECORDED_SESSION")
        raise ValueError(f"unexpected completed-session request {number}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarnessW9Mock/1"

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw)
            state: State = self.server.state  # type: ignore[attr-defined]
            chunks = state.handle(self.path, raw, body)
        except Exception as error:
            self.send_error(400, str(error))
            return
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
    parser.add_argument("--scenario", choices=["crash-resume", "completed"], required=True)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state = State(args.log, args.scenario)  # type: ignore[attr-defined]
    print(json.dumps({"ready": True, "port": args.port, "scenario": args.scenario}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
