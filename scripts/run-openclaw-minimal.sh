#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <workspace> <prompt>" >&2
  exit 2
fi

workspace="$(realpath "$1")"
case "$workspace" in
  "$BENCH_ROOT/workspaces"|"$BENCH_ROOT/workspaces"/*) ;;
  *)
    echo "workspace must be inside $BENCH_ROOT/workspaces" >&2
    exit 2
    ;;
esac

if [[ ! -d "$workspace" ]]; then
  echo "workspace does not exist: $workspace" >&2
  exit 2
fi
if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is not set" >&2
  exit 2
fi

cd "$BENCH_ROOT/sources/openclaw"
exec pnpm openclaw agent exec \
  --code-mode direct \
  --config "$OPENCLAW_CONFIG_PATH" \
  --cwd "$workspace" \
  --model "$OPENCLAW_MODEL" \
  --thinking high \
  --timeout 600 \
  --json \
  "$2"
