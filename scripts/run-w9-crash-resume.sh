#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"
if [[ $# -ne 2 || ! "$1" =~ ^[A-Za-z0-9._-]+$ || ! "$2" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <trial-id> <port>" >&2
  exit 2
fi
trial_id="$1"
port="$2"
workspace="$BENCH_ROOT/workspaces/w9-$trial_id"
result_dir="$BENCH_ROOT/results/w9-$trial_id"
if [[ ! -d "$workspace" ]]; then
  "$BENCH_ROOT/scripts/prepare-w9.sh" "$trial_id" >/dev/null
fi
if [[ -e "$result_dir" ]]; then
  echo "refusing to overwrite existing result directory: $result_dir" >&2
  exit 2
fi
mkdir -p "$BENCH_ROOT/results"
temp_dir="$(mktemp -d)"
server_log="$temp_dir/server.log"
request_log="$temp_dir/requests.jsonl"
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/mock-session-provider.py" \
  --port "$port" --scenario crash-resume --log "$request_log" >"$server_log" 2>&1 &
server_pid=$!
cleanup() {
  kill "$server_pid" 2>/dev/null || true
  wait "$server_pid" 2>/dev/null || true
  rm -rf "$temp_dir"
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
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-w9-crash-resume.py" \
  "$workspace" "dsh-w9-$trial_id" "$result_dir"
cp "$request_log" "$result_dir/requests.jsonl"
cp "$server_log" "$result_dir/server.log"
cleanup
trap - EXIT
