#!/usr/bin/env python3
"""Deterministic SSE provider for W8 direct-versus-code-mode ablations."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


FINAL_MARKER = "COMPLETED_W8_CODE_MODE_ABLATION"
STEPS = 8


def shell_command(step: int) -> str:
    return f"printf 'W8_STEP_{step:03d}\\n' >> w8.log"


def tool_chunks(request_number: int, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"mock-w8-{request_number:03d}",
            "object": "chat.completion.chunk",
            "created": request_number,
            "model": "deepseek-v4-flash",
            "choices": [{
                "index": 0,
                "delta": {
                    "role": "assistant",
                    "tool_calls": [{
                        "index": 0,
                        "id": f"callw8{request_number:03d}",
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": json.dumps(arguments, separators=(",", ":")),
                        },
                    }],
                },
                "finish_reason": None,
            }],
        },
        {
            "id": f"mock-w8-{request_number:03d}",
            "object": "chat.completion.chunk",
            "created": request_number,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


def final_chunks() -> list[dict[str, Any]]:
    return [
        {
            "id": "mock-w8-final",
            "object": "chat.completion.chunk",
            "created": 999,
            "model": "deepseek-v4-flash",
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": FINAL_MARKER},
                "finish_reason": None,
            }],
        },
        {
            "id": "mock-w8-final",
            "object": "chat.completion.chunk",
            "created": 999,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


class State:
    def __init__(self, log_path: Path, expected_mode: str) -> None:
        self.log_path = log_path
        self.expected_mode = expected_mode
        self.lock = threading.Lock()
        self.requests = 0
        self.detected_mode: str | None = None
        self.detected_runtime: str | None = None

    def record(self, path: str, raw: bytes, body: dict[str, Any]) -> int:
        with self.lock:
            self.requests += 1
            number = self.requests
            tools = body.get("tools", [])
            schemas = {
                item.get("function", {}).get("name", ""): item.get("function", {}).get("parameters", {})
                for item in tools
                if isinstance(item, dict)
            }
            if number == 1:
                if "run_code" in schemas:
                    self.detected_mode = "code"
                    self.detected_runtime = "dsh"
                elif "exec" in schemas and "code" in schemas["exec"].get("properties", {}):
                    self.detected_mode = "code"
                    self.detected_runtime = "openclaw"
                elif "bash" in schemas:
                    self.detected_mode = "direct"
                    self.detected_runtime = "dsh"
                elif "exec" in schemas and "command" in schemas["exec"].get("properties", {}):
                    self.detected_mode = "direct"
                    self.detected_runtime = "openclaw"
                else:
                    raise ValueError(f"unrecognized tool surface: {sorted(schemas)}")
                if self.detected_mode != self.expected_mode:
                    raise ValueError(
                        f"expected {self.expected_mode}, detected {self.detected_mode}"
                    )
            messages_json = json.dumps(body.get("messages", []), ensure_ascii=False, separators=(",", ":"))
            record = {
                "request": number,
                "path": path,
                "time_ns": time.time_ns(),
                "request_body_bytes": len(raw),
                "message_count": len(body.get("messages", [])),
                "messages_bytes": len(messages_json.encode("utf-8")),
                "tool_schema_bytes": len(json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
                "tool_names": list(schemas),
                "detected_mode": self.detected_mode,
                "detected_runtime": self.detected_runtime,
            }
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            return number

    def response_for(self, request_number: int) -> list[dict[str, Any]]:
        if self.detected_mode == "direct":
            if request_number <= STEPS:
                name = "bash" if self.detected_runtime == "dsh" else "exec"
                return tool_chunks(request_number, name, {"command": shell_command(request_number)})
            return final_chunks()
        if request_number == 1:
            commands = [shell_command(step) for step in range(1, STEPS + 1)]
            if self.detected_runtime == "dsh":
                code = (
                    f"const commands = {json.dumps(commands)}; "
                    "const results = []; "
                    "for (const command of commands) results.push(await tools.bash({ command })); "
                    "return results;"
                )
                return tool_chunks(1, "run_code", {
                    "code": code,
                    "description": "Append eight deterministic markers sequentially",
                })
            code = (
                f"const commands = {json.dumps(commands)}; "
                "const results = []; "
                "for (const command of commands) results.push(await exec({ command })); "
                "return results;"
            )
            return tool_chunks(1, "exec", {"code": code, "language": "javascript"})
        return final_chunks()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarnessCodeModeMock/1"

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            body = json.loads(raw)
            state: State = self.server.state  # type: ignore[attr-defined]
            request_number = state.record(self.path, raw, body)
            chunks = state.response_for(request_number)
        except Exception as error:  # make probe failures visible to the caller
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
    parser.add_argument("--mode", choices=["direct", "code"], required=True)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state = State(args.log, args.mode)  # type: ignore[attr-defined]
    print(json.dumps({"ready": True, "port": args.port, "mode": args.mode}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
