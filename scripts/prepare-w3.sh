#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

if [[ $# -ne 1 || ! "$1" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "usage: $0 <trial-id>" >&2
  exit 2
fi

target="$BENCH_ROOT/workspaces/w3-$1"
if [[ -e "$target" ]]; then
  echo "refusing to overwrite existing trial workspace: $target" >&2
  exit 2
fi

cp -a "$BENCH_ROOT/workspaces/w3-template" "$target"
find "$target" -type d \( -name .pytest_cache -o -name __pycache__ \) -prune -exec rm -r -- {} +
git -C "$target" init -q
git -C "$target" config user.name "Harness Benchmark"
git -C "$target" config user.email "benchmark@localhost"
git -C "$target" add .
git -C "$target" commit -qm "W3 baseline"
printf '%s\n' "$target"
