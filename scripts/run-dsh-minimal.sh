#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <workspace> <session-id> <prompt>" >&2
  exit 2
fi

exec "$BENCH_ROOT/.venv/bin/python" "$BENCH_ROOT/scripts/dsh_minimal.py" "$1" "$2" "$3"
