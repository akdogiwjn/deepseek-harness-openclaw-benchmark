# DeepSeek Harness vs OpenClaw pilot

This directory contains source-pinned local builds and isolated experiment state for a first native-minimal comparison.

## Installed revisions

- DeepSeek Harness: `dd6322d604e00eec1ba5e0c8541159906a21094a`
- OpenClaw: `3c1b351555e0ebc1b022842523191691e89c7684` (`2026.8.1`)
- Project-local Node.js: `24.15.0`, Linux ARM64
- DeepSeek Harness pnpm: `11.7.0`
- OpenClaw pnpm: `12.1.0`

## Minimal surfaces

- DeepSeek Harness `sdk-minimal`: persistent Bash and `str_replace_editor`; JSONL sessions; compaction absent.
- OpenClaw: `exec`, `read`, `write`, `edit`, and `apply_patch`; only the DeepSeek provider plugin is loaded; Code Mode, context pruning, and threshold compaction disabled.

The two native tool surfaces are intentionally recorded as different rather than described as tool-equivalent. OpenClaw filesystem tools are workspace-only. Both runners currently execute without an inner sandbox and therefore accept workspaces only below `workspaces/`. Use disposable task copies.

## Run

The runners automatically read the selected provider's `apiKey` and `baseURL` from `/home/lcq/.config/opencode/opencode.json` without copying or printing the secret. OpenCode `{env:VARIABLE}` credential references are resolved from the current process environment. Override `OPENCODE_CONFIG`, `BENCH_API_KEY`, or `BENCH_BASE_URL` only when needed.

Both runtimes use the same OpenAI-compatible proxy route:

```bash
source scripts/env.sh
```

Create or copy a disposable task repository below `workspaces/`, then run:

```bash
scripts/run-dsh-minimal.sh workspaces/task-001 dsh-w1-001 'Make the requested change and verify it.'
scripts/run-openclaw-minimal.sh workspaces/task-001 'Make the requested change and verify it.'
```

The OpenClaw runner's `--code-mode direct` option maps the per-run Code Mode
override to `false`; it selects direct tool calling and does not enable Code Mode.

The first exact-edit fixture is ready. Prepare independent copies with:

```bash
scripts/prepare-w1.sh dsh-001
scripts/prepare-w1.sh openclaw-001
```

Use the prompt in each copy's `TASK.md`, then verify outside the agent runtime:

```bash
.venv/bin/python verifiers/verify_w1.py workspaces/w1-dsh-001
```

Use a fresh workspace copy and a fresh DSH session id for every independent trial. Do not run the two agents sequentially against the same mutated copy.

## W2 bug-fix fixture

W2 is a small Python `Retry-After` parser with one visible failing test and an
external verifier covering additional valid HTTP-date forms. Prepare independent
copies and run the same prompt through each runtime:

```bash
scripts/prepare-w2.sh dsh-001
scripts/prepare-w2.sh openclaw-001
scripts/run-dsh-minimal.sh workspaces/w2-dsh-001 dsh-w2-001 \
  'Read TASK.md and complete the requested bug fix. Run the test suite before and after your change.'
scripts/run-openclaw-minimal.sh workspaces/w2-openclaw-001 \
  'Read TASK.md and complete the requested bug fix. Run the test suite before and after your change.'
.venv/bin/python verifiers/verify_w2.py workspaces/w2-dsh-001
```

Raw process records, verifier records, normalized pair summaries, and aggregates
are stored below `results/`. Infrastructure-invalid runs are retained but excluded
from agent success-rate calculations.

The completed W2 run contains five valid interleaved pairs. See
`results/W2_REPORT.md` and `results/w2-aggregate-n5.json` for the report and
machine-readable aggregate.

## W3 repository feature fixture

W3 adds weighted, atomic quota consumption to a multi-module Python package and
requires the agent to add focused tests. Five interleaved pairs are complete.
See `results/W3_REPORT.md` and `results/w3-aggregate-n5.json`.

## W4 malformed tool-call recovery

W4 uses a deterministic local SSE mock to inject the same malformed tool call
into each runtime. It isolates provider-boundary validation and recovery from
model randomness and gateway latency. See `results/W4_REPORT.md` and
`results/w4-recovery-summary.json`.

## W5 deterministic automatic compaction

W5 adds explicit compaction services to the otherwise minimal runtimes, scripts
large tool results, and returns the same fixed summary to every summarizer call.
The calibrated main pair aligns observed trigger positions rather than pretending
the runtimes' estimators and prompt envelopes use equivalent numeric thresholds.
See `results/W5_REPORT.md` and `results/w5-compaction-summary.json`.

Run the calibrated pair with `scripts/run-w5-case.sh`. Set
`W5_VARIANT=stress` to reproduce the separate same-numeric 16K pressure case.

## W6 deterministic tool failures

W6 uses a local deterministic provider to issue one valid shell tool call and
then a fixed completion. It covers a child process exiting with code 17 and a
tool call missing its required `command` argument. This separates execution and
argument-validation failures from the malformed provider event tested by W4.
See `results/W6_REPORT.md` and `results/w6-tool-failure-summary.json`.

## W7 deterministic long tool chain

W7 scripts twenty sequential native shell calls followed by one fixed completion.
It records exact request-body growth, message growth, provider round trips, and
inter-request timing without assigning fake token counts to the local mock.
See `results/W7_REPORT.md` and `results/w7-long-chain-summary.json`.

## W8 direct calling versus code mode

W8 is a paired within-runtime ablation. A deterministic local provider causes
eight identical sequential shell operations in four conditions: DSH native and
PTC, then OpenClaw direct and Code Mode. Direct conditions expose eight model
tool calls; code conditions expose one model program call that dispatches the
same eight underlying tools. This isolates executor collapse from model choice.
See `results/W8_REPORT.md` and `results/w8-code-mode-summary.json`.

`scripts/run-openclaw-minimal.sh` still defaults to `--code-mode direct` through
`OPENCLAW_CODE_MODE`; W8 overrides it to `code` only for the Code Mode condition.

## State

- `sources/`: upstream source checkouts
- `configs/`: benchmark configuration templates
- `workspaces/`: disposable task copies only
- `sessions/`: isolated runtime state and DSH JSONL traces
- `results/`: benchmark result artifacts

The OpenClaw runner pins both `OPENCLAW_CONFIG_PATH` and an experiment-local `OPENCLAW_STATE_DIR`; it does not read the normal user state directory. Current `agent exec` rejects combining `--config` with `--auth-env-only`, so credential isolation is provided by that empty experiment-local state plus an environment-backed SecretRef. The OpenClaw custom provider uses `maxTokens: 256000` and `thinking: high` to match the DSH request header observed in the minimal trace.
