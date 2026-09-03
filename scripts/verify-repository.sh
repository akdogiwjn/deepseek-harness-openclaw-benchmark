#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

echo "[1/4] verify pinned source checkouts and local toolchain"
scripts/bootstrap.sh --verify-only

echo "[2/4] verify frozen W1-W10 evidence and reproduce summaries"
scripts/reproduce-evidence.sh

echo "[3/4] verify C1-C8 protocol provenance, samples, and derivations"
scripts/cpu/verify-cpu-results.py

echo "[4/4] check shell/Python syntax and patch whitespace"
bash -n scripts/reproduce-evidence.sh scripts/verify-repository.sh
python3 -m unittest harness_cpu_report/test_report.py
python3 -m py_compile \
  scripts/freeze-evidence.py \
  scripts/verify-behavioral-evidence.py \
  scripts/summarize-w8.py \
  scripts/summarize-w9.py \
  scripts/cpu/perf_utils.py \
  scripts/cpu/run-c1.py \
  scripts/cpu/run-c2.py \
  scripts/cpu/run-c3.py \
  scripts/cpu/run-c4.py \
  scripts/cpu/run-c5.py \
  scripts/cpu/run-c6.py \
  scripts/cpu/run-c7.py \
  scripts/cpu/run-c8.py \
  scripts/cpu/render-c8-report.py \
  scripts/cpu/verify-cpu-results.py \
  harness_cpu_report/build.py \
  harness_cpu_report/content.py \
  harness_cpu_report/data_loader.py \
  harness_cpu_report/derive.py \
  harness_cpu_report/validate.py
node --check harness_cpu_report/static/charts.js
git diff --check

echo "[done] repository verification passed"
