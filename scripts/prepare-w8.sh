#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "usage: $0 <trial-id>" >&2
  exit 2
fi

target="$BENCH_ROOT/workspaces/w8-$1"
if [[ -e "$target" ]]; then
  echo "refusing to overwrite existing trial workspace: $target" >&2
  exit 2
fi

cp -a "$BENCH_ROOT/workspaces/w8-template" "$target"
printf '%s\n' "$target"
