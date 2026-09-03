#!/usr/bin/env bash
set -euo pipefail

BENCH_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BENCH_ROOT"
evidence="evidence"
temp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$temp_dir"
}
trap cleanup EXIT

(cd "$evidence" && sha256sum --check MANIFEST.sha256)

python="$BENCH_ROOT/.venv/bin/python"
if [[ ! -x "$python" ]]; then
  python="$(command -v python3)"
fi

"$python" "$BENCH_ROOT/scripts/verify-behavioral-evidence.py" \
  --root "$BENCH_ROOT" --evidence "$BENCH_ROOT/$evidence"

"$python" "$BENCH_ROOT/scripts/summarize-w4.py" \
  "$evidence/W4/results/w4-recovery-001" \
  "$evidence/W4/results/w4-recovery-002" \
  "$evidence/W4/results/w4-recovery-001" \
  "$temp_dir/w4.json"
"$python" "$BENCH_ROOT/scripts/summarize-w5.py" \
  "$evidence/W5/results/w5-dsh-compaction-005" \
  "$evidence/W5/results/w5-openclaw-compaction-005" \
  "$evidence/W5/results/w5-dsh-compaction-003" \
  "$evidence/W5/results/w5-openclaw-compaction-003" \
  "$temp_dir/w5.json"
"$python" "$BENCH_ROOT/scripts/summarize-w6.py" \
  "$evidence/W6/results/w6-dsh-nonzero-002" \
  "$evidence/W6/results/w6-openclaw-nonzero-002" \
  "$evidence/W6/results/w6-dsh-invalid-args-001" \
  "$evidence/W6/results/w6-openclaw-invalid-args-001" \
  "$evidence/W6/results/w6-dsh-nonzero-001" \
  "$evidence/W6/results/w6-openclaw-nonzero-001" \
  "$temp_dir/w6.json"
"$python" "$BENCH_ROOT/scripts/summarize-w7.py" \
  "$evidence/W7/results/w7-dsh-chain-002" \
  "$evidence/W7/results/w7-openclaw-chain-002" \
  "$temp_dir/w7.json"
"$python" "$BENCH_ROOT/scripts/summarize-w8.py" \
  "$evidence/W8/results/w8-dsh-direct-01" \
  "$evidence/W8/results/w8-dsh-code-01" \
  "$evidence/W8/results/w8-openclaw-direct-01" \
  "$evidence/W8/results/w8-openclaw-code-01" \
  "$temp_dir/w8.json"
"$python" "$BENCH_ROOT/scripts/summarize-w9.py" \
  "$evidence/W9/results/w9-crash-003" \
  "$evidence/W9/w9-fork-001.json" \
  "$evidence/W9/results/w9-replay-008" \
  "$temp_dir/w9.json"
"$python" "$BENCH_ROOT/scripts/summarize-w10.py" \
  "$evidence/W10/results/w10-local-a-003" \
  "$evidence/W10/results/w10-sandbox-b-004" \
  "$evidence/W10/results/w10-local-aprime-003" \
  "$temp_dir/w10.json"

compare_json() {
  local generated="$1"
  local committed="$2"
  jq --sort-keys . "$generated" >"$temp_dir/generated.sorted.json"
  jq --sort-keys . "$committed" >"$temp_dir/committed.sorted.json"
  diff -u "$temp_dir/committed.sorted.json" "$temp_dir/generated.sorted.json"
  echo "[verified] $(basename "$committed")"
}

compare_json "$temp_dir/w4.json" "$BENCH_ROOT/results/w4-recovery-summary.json"
compare_json "$temp_dir/w5.json" "$BENCH_ROOT/results/w5-compaction-summary.json"
compare_json "$temp_dir/w6.json" "$BENCH_ROOT/results/w6-tool-failure-summary.json"
compare_json "$temp_dir/w7.json" "$BENCH_ROOT/results/w7-long-chain-summary.json"
compare_json "$temp_dir/w8.json" "$BENCH_ROOT/results/w8-code-mode-summary.json"
compare_json "$temp_dir/w9.json" "$BENCH_ROOT/results/w9-session-summary.json"
compare_json "$temp_dir/w10.json" "$BENCH_ROOT/results/w10-fs-seam-summary.json"
echo "[done] frozen evidence verifies W1-W3 outcomes and reproduces all W4-W10 summaries"
