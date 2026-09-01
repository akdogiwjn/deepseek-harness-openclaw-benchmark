#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"
if [[ $# -ne 3 ]]; then
  echo "usage: $0 <local|sandbox> <trial-id> <port>" >&2
  exit 2
fi
variant="$1"
trial_id="$2"
port="$3"
if [[ "$variant" != local && "$variant" != sandbox ]]; then
  echo "variant must be local or sandbox" >&2
  exit 2
fi
if [[ ! "$trial_id" =~ ^[A-Za-z0-9._-]+$ || ! "$port" =~ ^[0-9]+$ ]]; then
  echo "invalid trial id or port" >&2
  exit 2
fi
case_root="$BENCH_ROOT/workspaces/w10-$trial_id"
workspace="$case_root/workspace"
result_dir="$BENCH_ROOT/results/w10-$trial_id"
[[ -d "$workspace" ]] || "$BENCH_ROOT/scripts/prepare-w10.sh" "$trial_id" >/dev/null
if [[ -e "$result_dir" ]]; then
  echo "refusing to overwrite existing result directory: $result_dir" >&2
  exit 2
fi
mkdir -p "$result_dir"
server_log="$result_dir/server.log"
request_log="$result_dir/requests.jsonl"
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/mock-fs-seam-provider.py" \
  --port "$port" --log "$request_log" >"$server_log" 2>&1 &
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

export BENCH_API_KEY=w10-local-mock
export DEEPSEEK_API_KEY="$BENCH_API_KEY"
export BENCH_BASE_URL="http://127.0.0.1:$port/v1"
export DEEPSEEK_BASE_URL="$BENCH_BASE_URL"
export HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= http_proxy= https_proxy= all_proxy=
export NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost
export BENCH_DSH_PATCHES="$BENCH_ROOT/configs/dsh-w10-$variant.patch.yml"
"$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/run-captured.py" \
  "$result_dir/runtime.raw.json" \
  "$BENCH_ROOT/scripts/run-dsh-minimal.sh" "$workspace" "dsh-w10-$trial_id" \
  "Execute the three deterministic filesystem operations supplied by the provider."
cleanup
trap - EXIT
session_file="$(find "$BENCH_ROOT/sessions/dsh-home/sessions" \
  -path "*/dsh-w10-$trial_id/session.jsonl" -print -quit)"
[[ -n "$session_file" ]] || { echo "session log not found" >&2; exit 1; }
cp "$session_file" "$result_dir/session.jsonl"
printf '{"scenario":"W10 native tool-fs provider swap","variant":"%s","provider_requests":%s}\n' \
  "$variant" "$(wc -l <"$request_log")" >"$result_dir/case.json"
cat "$result_dir/case.json"
