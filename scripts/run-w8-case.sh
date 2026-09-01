#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

if [[ $# -ne 4 ]]; then
  echo "usage: $0 <dsh|openclaw> <direct|code> <trial-id> <port>" >&2
  exit 2
fi

runtime="$1"
mode="$2"
trial_id="$3"
port="$4"
if [[ "$runtime" != "dsh" && "$runtime" != "openclaw" ]]; then
  echo "runtime must be dsh or openclaw" >&2
  exit 2
fi
if [[ "$mode" != "direct" && "$mode" != "code" ]]; then
  echo "mode must be direct or code" >&2
  exit 2
fi
if [[ ! "$trial_id" =~ ^[A-Za-z0-9._-]+$ || ! "$port" =~ ^[0-9]+$ ]]; then
  echo "invalid trial id or port" >&2
  exit 2
fi

workspace="$BENCH_ROOT/workspaces/w8-$trial_id"
result_dir="$BENCH_ROOT/results/w8-$trial_id"
if [[ ! -d "$workspace" ]]; then
  "$BENCH_ROOT/scripts/prepare-w8.sh" "$trial_id" >/dev/null
fi
if [[ -e "$result_dir" ]]; then
  echo "refusing to overwrite existing result directory: $result_dir" >&2
  exit 2
fi
mkdir -p "$result_dir"

server_log="$result_dir/server.log"
request_log="$result_dir/requests.jsonl"
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/mock-code-mode-provider.py" \
  --port "$port" --mode "$mode" --log "$request_log" >"$server_log" 2>&1 &
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

export BENCH_API_KEY="w8-local-mock"
export DEEPSEEK_API_KEY="$BENCH_API_KEY"
export BENCH_BASE_URL="http://127.0.0.1:$port/v1"
export DEEPSEEK_BASE_URL="$BENCH_BASE_URL"
export HTTP_PROXY=
export HTTPS_PROXY=
export ALL_PROXY=
export http_proxy=
export https_proxy=
export all_proxy=
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="$NO_PROXY"

prompt="Execute the deterministic shell operations supplied by the provider until completion."
set +e
if [[ "$runtime" == "dsh" ]]; then
  if [[ "$mode" == "code" ]]; then
    export BENCH_DSH_PATCHES="$BENCH_ROOT/configs/dsh-ptc.patch.yml"
  else
    export BENCH_DSH_PATCHES=
  fi
  "$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-captured.py" \
    "$result_dir/runtime.raw.json" \
    "$BENCH_ROOT/scripts/run-dsh-minimal.sh" "$workspace" "dsh-w8-$trial_id" "$prompt"
  runtime_exit=$?
else
  if [[ "$mode" == "code" ]]; then
    export OPENCLAW_CODE_MODE=code
    export OPENCLAW_CONFIG_PATH="$BENCH_ROOT/configs/openclaw-code-mode.json"
  else
    export OPENCLAW_CODE_MODE=direct
    export OPENCLAW_CONFIG_PATH="$BENCH_ROOT/configs/openclaw-minimal.json"
  fi
  "$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-captured.py" \
    "$result_dir/runtime.raw.json" \
    "$BENCH_ROOT/scripts/run-openclaw-minimal.sh" "$workspace" "$prompt"
  runtime_exit=$?
fi
set -e

cleanup
trap - EXIT
marker_count=0
if [[ -f "$workspace/w8.log" ]]; then
  marker_count="$(wc -l <"$workspace/w8.log")"
fi
printf '{"runtime":"%s","mode":"%s","steps":8,"runtime_exit_code":%d,"provider_requests":%s,"marker_count":%s}\n' \
  "$runtime" "$mode" "$runtime_exit" "$(wc -l <"$request_log")" "$marker_count" >"$result_dir/case.json"
cat "$result_dir/case.json"
