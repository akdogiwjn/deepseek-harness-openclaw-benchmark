#!/usr/bin/env bash
set -euo pipefail

BENCH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export BENCH_ROOT
export PATH="$BENCH_ROOT/.venv/bin:$BENCH_ROOT/bin:$BENCH_ROOT/node-v24.15.0-linux-arm64/bin:${PATH:-/usr/bin:/bin}"
export COREPACK_HOME="$BENCH_ROOT/.corepack"
export PNPM_HOME="$BENCH_ROOT/.pnpm-home"
export DSH_HOME="$BENCH_ROOT/sessions/dsh-home"
export OPENCLAW_STATE_DIR="$BENCH_ROOT/sessions/openclaw-state"
export OPENCLAW_CONFIG_PATH="$BENCH_ROOT/configs/openclaw-minimal.json"
export DSH_MODEL="${DSH_MODEL:-deepseek-v4-flash}"
export OPENCLAW_MODEL="${OPENCLAW_MODEL:-bench-proxy/deepseek-v4-flash}"
export OPENCLAW_LOG_LEVEL="${OPENCLAW_LOG_LEVEL:-error}"

OPENCODE_CONFIG="${OPENCODE_CONFIG:-/home/lcq/.config/opencode/opencode.json}"
if [[ -f "$OPENCODE_CONFIG" ]]; then
  opencode_provider="$(jq -er '.model | split("/")[0] | select(length > 0)' "$OPENCODE_CONFIG")"
  opencode_key_ref="$(jq -er --arg provider "$opencode_provider" '.provider[$provider].options.apiKey | select(type == "string" and length > 0)' "$OPENCODE_CONFIG")"
  if [[ "$opencode_key_ref" =~ ^\{env:([A-Za-z_][A-Za-z0-9_]*)\}$ ]]; then
    opencode_key_var="${BASH_REMATCH[1]}"
    opencode_key="${!opencode_key_var:-}"
    if [[ -z "$opencode_key" ]]; then
      echo "OpenCode credential environment variable is unset: $opencode_key_var" >&2
      return 2 2>/dev/null || exit 2
    fi
  else
    opencode_key="$opencode_key_ref"
  fi
  export BENCH_API_KEY="${BENCH_API_KEY:-$opencode_key}"
  export BENCH_BASE_URL="${BENCH_BASE_URL:-$(jq -er --arg provider "$opencode_provider" '.provider[$provider].options.baseURL | select(type == "string" and length > 0)' "$OPENCODE_CONFIG")}"
fi
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-${BENCH_API_KEY:-}}"
export DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL:-${BENCH_BASE_URL:-}}"

mkdir -p "$DSH_HOME" "$OPENCLAW_STATE_DIR"
