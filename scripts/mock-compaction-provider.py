#!/usr/bin/env python3
"""Deterministic OpenAI-compatible SSE server for automatic compaction."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SUMMARY_MARKER = "W5_FIXED_COMPACTION_SUMMARY"
FINAL_MARKER = "COMPLETED_W5_AFTER_COMPACTION"
NO_COMPACTION_MARKER = "W5_NO_COMPACTION_TRIGGERED"


def text_chunks(response_id: str, content: str) -> list[dict[str, Any]]:
    return [
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": 999,
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
            "created": 999,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


def tool_chunks(step: int, tool_name: str) -> list[dict[str, Any]]:
    marker = f"W5_STEP_{step:03d}"
    command = (
        f"printf 'ANCHOR_ALPHA {marker}\\n'; "
        "printf '%4096s\\n' '' | tr ' ' x; "
        f"printf 'W5_END_{step:03d}\\n'"
    )
    return [
        {
            "id": f"mock-w5-{step:03d}",
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
                                "id": f"callw5step{step:03d}",
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": json.dumps(
                                        {"command": command}, separators=(",", ":")
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
            "id": f"mock-w5-{step:03d}",
            "object": "chat.completion.chunk",
            "created": step,
            "model": "deepseek-v4-flash",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]


def is_compaction_request(body: dict[str, Any]) -> bool:
    serialized = json.dumps(body, ensure_ascii=False).lower()
    return (
        "you are now acting as a compaction engine" in serialized
        or "you are a context summarization assistant" in serialized
    )


class State:
    def __init__(self, log_path: Path, tool_steps: int) -> None:
        self.log_path = log_path
        self.tool_steps = tool_steps
        self.lock = threading.Lock()
        self.requests = 0
        self.agent_requests = 0
        self.compaction_requests = 0
        self.post_compaction_agent_requests = 0

    def record(self, path: str, raw: bytes, body: dict[str, Any]) -> tuple[str, int]:
        with self.lock:
            self.requests += 1
            compacting = is_compaction_request(body)
            if compacting:
                self.compaction_requests += 1
                kind = "compaction"
                ordinal = self.compaction_requests
            else:
                self.agent_requests += 1
                if self.compaction_requests > 0:
                    self.post_compaction_agent_requests += 1
                kind = "agent"
                ordinal = self.agent_requests
            messages = body.get("messages", [])
            serialized_messages = json.dumps(
                messages, ensure_ascii=False, separators=(",", ":")
            )
            tools = body.get("tools", [])
            record = {
                "request": self.requests,
                "kind": kind,
                "kind_ordinal": ordinal,
                "path": path,
                "time_ns": time.time_ns(),
                "request_body_bytes": len(raw),
                "message_count": len(messages),
                "messages_bytes": len(serialized_messages.encode("utf-8")),
                "tool_schema_bytes": len(
                    json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ),
                "tool_names": [
                    item.get("function", {}).get("name", "")
                    for item in tools
                    if isinstance(item, dict)
                ],
                "summary_marker_present": SUMMARY_MARKER in serialized_messages,
                "anchor_present": "ANCHOR_ALPHA" in serialized_messages,
            }
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            return kind, ordinal


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HarnessCompactionMock/1"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw)
        state: State = self.server.state  # type: ignore[attr-defined]
        kind, ordinal = state.record(self.path, raw, body)

        if kind == "compaction":
            chunks = text_chunks(
                f"mock-w5-summary-{ordinal}",
                f"{SUMMARY_MARKER}\n- Preserve ANCHOR_ALPHA.\n- Continue the scripted chain.",
            )
        elif ordinal <= state.tool_steps:
            chunks = self._tool_response(body, ordinal)
        elif state.compaction_requests > 0:
            chunks = text_chunks("mock-w5-final", FINAL_MARKER)
        else:
            chunks = text_chunks("mock-w5-no-compaction", NO_COMPACTION_MARKER)

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

    def _tool_response(self, body: dict[str, Any], step: int) -> list[dict[str, Any]]:
        declared = {
            item.get("function", {}).get("name", "")
            for item in body.get("tools", [])
            if isinstance(item, dict)
        }
        tool_name = "bash" if "bash" in declared else "exec"
        if tool_name not in declared:
            raise RuntimeError("neither bash nor exec was declared")
        return tool_chunks(step, tool_name)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--tool-steps", type=int, default=10)
    args = parser.parse_args()
    if args.tool_steps < 3 or args.tool_steps > 50:
        parser.error("tool-steps must be between 3 and 50")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.state = State(args.log, args.tool_steps)  # type: ignore[attr-defined]
    print(json.dumps({"ready": True, "port": args.port}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
