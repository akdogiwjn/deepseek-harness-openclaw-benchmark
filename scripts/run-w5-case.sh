#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <dsh|openclaw> <trial-id> <port>" >&2
  exit 2
fi

runtime="$1"
trial_id="$2"
port="$3"
if [[ "$runtime" != "dsh" && "$runtime" != "openclaw" ]]; then
  echo "runtime must be dsh or openclaw" >&2
  exit 2
fi
if [[ ! "$trial_id" =~ ^[A-Za-z0-9._-]+$ || ! "$port" =~ ^[0-9]+$ ]]; then
  echo "invalid trial id or port" >&2
  exit 2
fi

workspace="$BENCH_ROOT/workspaces/w5-$trial_id"
result_dir="$BENCH_ROOT/results/w5-$trial_id"
variant="${W5_VARIANT:-calibrated}"
if [[ "$variant" != "calibrated" && "$variant" != "stress" ]]; then
  echo "W5_VARIANT must be calibrated or stress" >&2
  exit 2
fi
if [[ ! -d "$workspace" ]]; then
  "$BENCH_ROOT/scripts/prepare-w5.sh" "$trial_id" >/dev/null
fi
if [[ -e "$result_dir" ]]; then
  echo "refusing to overwrite existing result directory: $result_dir" >&2
  exit 2
fi
mkdir -p "$result_dir"

if [[ "$variant" == "stress" ]]; then
  tool_steps=10
  context_window=16000
  dsh_patch="$BENCH_ROOT/configs/dsh-compaction-16k-stress.patch.yml"
  openclaw_config="$result_dir/openclaw-compaction-16k-stress.json"
  jq '.models.providers["bench-proxy"].models[0].contextTokens = 16000' \
    "$BENCH_ROOT/configs/openclaw-compaction.json" >"$openclaw_config"
else
  tool_steps=8
  context_window=32000
  dsh_patch="$BENCH_ROOT/configs/dsh-compaction.patch.yml"
  openclaw_config="$BENCH_ROOT/configs/openclaw-compaction.json"
fi

server_log="$result_dir/server.log"
request_log="$result_dir/requests.jsonl"
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/mock-compaction-provider.py" \
  --port "$port" --tool-steps "$tool_steps" --log "$request_log" >"$server_log" 2>&1 &
server_pid=$!
cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
}
trap cleanup EXIT

for _ in {1..100}; do
  if grep -q '"ready": true' "$server_log" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "mock provider exited before becoming ready" >&2
    exit 1
  fi
  sleep 0.05
done
if ! grep -q '"ready": true' "$server_log" 2>/dev/null; then
  echo "mock provider did not become ready" >&2
  exit 1
fi

export BENCH_API_KEY="w5-local-mock"
export DEEPSEEK_API_KEY="$BENCH_API_KEY"
export BENCH_BASE_URL="http://127.0.0.1:$port/v1"
export DEEPSEEK_BASE_URL="$BENCH_BASE_URL"
export DSH_CONTEXT_WINDOW="$context_window"
export DSH_MODEL="w5-compaction-mock"
export BENCH_DSH_PATCHES="$dsh_patch"
export OPENCLAW_CONFIG_PATH="$openclaw_config"
export OPENCLAW_MODEL="bench-proxy/w5-compaction-mock"
export HTTP_PROXY=
export HTTPS_PROXY=
export ALL_PROXY=
export http_proxy=
export https_proxy=
export all_proxy=
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="$NO_PROXY"

prompt="Execute the deterministic tool sequence through automatic compaction and finish the turn."
set +e
if [[ "$runtime" == "dsh" ]]; then
  "$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-captured.py" \
    "$result_dir/runtime.raw.json" \
    "$BENCH_ROOT/scripts/run-dsh-minimal.sh" "$workspace" "dsh-w5-$trial_id" "$prompt"
  runtime_exit=$?
else
  "$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-captured.py" \
    "$result_dir/runtime.raw.json" \
    "$BENCH_ROOT/scripts/run-openclaw-minimal.sh" "$workspace" "$prompt"
  runtime_exit=$?
fi
set -e

cleanup
trap - EXIT
agent_requests="$(jq -s '[.[] | select(.kind == "agent")] | length' "$request_log")"
compaction_requests="$(jq -s '[.[] | select(.kind == "compaction")] | length' "$request_log")"
printf '{"runtime":"%s","variant":"%s","tool_steps":%d,"context_window":%d,"runtime_exit_code":%d,"provider_requests":%s,"agent_requests":%s,"compaction_requests":%s}\n' \
  "$runtime" "$variant" "$tool_steps" "$context_window" "$runtime_exit" \
  "$(wc -l <"$request_log")" "$agent_requests" "$compaction_requests" \
  >"$result_dir/case.json"
cat "$result_dir/case.json"
