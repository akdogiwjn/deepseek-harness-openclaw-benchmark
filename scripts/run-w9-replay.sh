#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"
if [[ $# -ne 2 || ! "$1" =~ ^[A-Za-z0-9._-]+$ || ! "$2" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <trial-id> <port>" >&2
  exit 2
fi
trial_id="$1"
port="$2"
record_id="${trial_id}-record"
replay_id="${trial_id}-replay"
record_workspace="$BENCH_ROOT/workspaces/w9-$record_id"
replay_workspace="$BENCH_ROOT/workspaces/w9-$replay_id"
result_dir="$BENCH_ROOT/results/w9-$trial_id"
[[ -d "$record_workspace" ]] || "$BENCH_ROOT/scripts/prepare-w9.sh" "$record_id" >/dev/null
[[ -d "$replay_workspace" ]] || "$BENCH_ROOT/scripts/prepare-w9.sh" "$replay_id" >/dev/null
if [[ -e "$result_dir" ]]; then
  echo "refusing to overwrite existing result directory: $result_dir" >&2
  exit 2
fi
mkdir -p "$result_dir"
server_log="$result_dir/server.log"
request_log="$result_dir/recording.requests.jsonl"
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/mock-session-provider.py" \
  --port "$port" --scenario completed --log "$request_log" >"$server_log" 2>&1 &
server_pid=$!
cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT
for _ in {1..100}; do
  grep -q '"ready": true' "$server_log" 2>/dev/null && break
  kill -0 "$server_pid" 2>/dev/null || { echo "mock provider exited" >&2; exit 1; }
  sleep 0.05
done
grep -q '"ready": true' "$server_log" || { echo "mock provider not ready" >&2; exit 1; }

export BENCH_API_KEY=w9-local-mock
export DEEPSEEK_API_KEY="$BENCH_API_KEY"
export BENCH_BASE_URL="http://127.0.0.1:$port/v1"
export DEEPSEEK_BASE_URL="$BENCH_BASE_URL"
export HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= http_proxy= https_proxy= all_proxy=
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
prompt="Execute the deterministic provider instructions until completion."
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-captured.py" \
  "$result_dir/recording.raw.json" \
  "$BENCH_ROOT/scripts/run-dsh-minimal.sh" "$record_workspace" "dsh-w9-$record_id" "$prompt"

recorded_session="$(find "$BENCH_ROOT/sessions/dsh-home/sessions" \
  -path "*/dsh-w9-$record_id/session.jsonl" -print -quit)"
[[ -n "$recorded_session" ]] || { echo "recorded session not found" >&2; exit 1; }
cp "$recorded_session" "$result_dir/recorded-session.jsonl"

# Replay must not require a live provider credential or contact the recording provider.
cleanup
trap - EXIT
requests_before="$(wc -l <"$request_log")"
export W9_REPLAY_FILE="$result_dir/recorded-session.jsonl"
export BENCH_DSH_PATCHES="$BENCH_ROOT/configs/dsh-w9-replay.patch.yml"
export DEEPSEEK_API_KEY=w9-replay-no-production-key
export DEEPSEEK_BASE_URL=http://127.0.0.1:1/v1
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-captured.py" \
  "$result_dir/replay.raw.json" \
  "$BENCH_ROOT/scripts/run-dsh-minimal.sh" "$replay_workspace" "dsh-w9-$replay_id" "$prompt"
requests_after="$(wc -l <"$request_log")"
replayed_session="$(find "$BENCH_ROOT/sessions/dsh-home/sessions" \
  -path "*/dsh-w9-$replay_id/session.jsonl" -print -quit)"
[[ -n "$replayed_session" ]] || { echo "replayed session not found" >&2; exit 1; }
cp "$replayed_session" "$result_dir/replayed-session.jsonl"

"$BENCH_ROOT/.venv/bin/python" - "$result_dir" "$record_workspace" "$replay_workspace" \
  "$requests_before" "$requests_after" <<'PY'
import json
import sys
from pathlib import Path

result = Path(sys.argv[1])
record_workspace = Path(sys.argv[2])
replay_workspace = Path(sys.argv[3])
before, after = int(sys.argv[4]), int(sys.argv[5])
record_raw = json.loads((result / "recording.raw.json").read_text())
replay_raw = json.loads((result / "replay.raw.json").read_text())
record_stdout = json.loads(record_raw["stdout"])
replay_stdout = json.loads(replay_raw["stdout"])

def events(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows[1:]

def projection(rows):
    keep = {"assistant/message", "tool/call", "tool/result", "turn/start", "step/start", "step/end", "turn/end"}
    projected = []
    for row in rows:
        if row.get("type") not in keep:
            continue
        data = row.get("data", {})
        item = {"type": row["type"]}
        for key in ("turn", "step", "name", "arguments"):
            if key in data:
                item[key] = data[key]
        if row["type"] == "assistant/message":
            item["content"] = data.get("message", {}).get("content")
        projected.append(item)
    return projected

def stream_projection(rows):
    return [
        {
            "turn": row["data"]["turn"],
            "step": row["data"]["step"],
            "chunk": row["data"]["chunk"],
        }
        for row in rows
        if row.get("type") == "assistant/chunk"
    ]

record_events = events(result / "recorded-session.jsonl")
replay_events = events(result / "replayed-session.jsonl")
checks = {
    "recording_completed": record_stdout.get("final_response") == "COMPLETED_W9_RECORDED_SESSION",
    "replay_completed": replay_stdout.get("final_response") == "COMPLETED_W9_RECORDED_SESSION",
    "provider_not_contacted_during_replay": before == after == 2,
    "record_effect_once": (record_workspace / "replay.log").read_text().splitlines() == ["W9_REPLAY_EFFECT"],
    "replay_effect_once": (replay_workspace / "replay.log").read_text().splitlines() == ["W9_REPLAY_EFFECT"],
    "normalized_execution_projection_equal": projection(record_events) == projection(replay_events),
    "normalized_assistant_chunk_stream_equal": stream_projection(record_events) == stream_projection(replay_events),
}
if not all(checks.values()):
    raise SystemExit(f"W9 replay checks failed: {checks}")
case = {
    "scenario": "W9-C credential-free LLM replay",
    "recorded_model_calls": before,
    "provider_requests_after_replay": after,
    "recorded_projection": projection(record_events),
    "replayed_projection": projection(replay_events),
    "recorded_stream_projection": stream_projection(record_events),
    "replayed_stream_projection": stream_projection(replay_events),
    "checks": checks,
}
(result / "case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(case, ensure_ascii=False))
PY
