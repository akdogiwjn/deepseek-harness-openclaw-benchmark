# DeepSeek Harness vs OpenClaw pilot

This directory contains source-pinned local builds and isolated experiment state for a first native-minimal comparison.

## Research reports

- [DeepSeek Harness 新型 Agent Harness 机制调研](deepseek_harness_report/report.md)：以 DSH Feature 为主线，串联 pinned source、W1–W10 行为证据与 C1–C8 Host CPU 影响。
- [Harness CPU interactive report](harness_cpu_report/dist/index.html)：以 Runtime/CPU workload decomposition 为主的离线长页。

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

### Bootstrap from a fresh clone

The repository pins the upstream revisions and local toolchain in
`configs/revisions.env`. On Linux ARM64 or x64, install and build everything
from a fresh benchmark checkout with:

```bash
scripts/bootstrap.sh
scripts/bootstrap.sh --verify-only
```

Bootstrap clones both upstream repositories at their exact commits, verifies
the pinned Node archive checksum from `SHASUMS256.txt`, installs each repository
with its frozen pnpm lockfile, builds both runtimes, creates `.venv`, and installs
the DSH Python SDK from the pinned checkout. It refuses to change dirty upstream
checkouts or replace an unexpected existing path. Network access is required for
the initial installation; deterministic W4–W8 runs use only their loopback mock.

The runners automatically read the selected provider's `apiKey` and `baseURL`
from `${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json` without copying
or printing the secret. OpenCode `{env:VARIABLE}` credential references are
resolved from the current process environment. Override `OPENCODE_CONFIG`,
`BENCH_API_KEY`, or `BENCH_BASE_URL` only when needed.

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

The five valid final-workspace overlays and normalized summaries are frozen under
`evidence/W2/`. `scripts/reproduce-evidence.sh` reconstructs every workspace,
reruns the external verifier, and rebuilds the committed n=5 aggregate.

The completed W2 run contains five valid interleaved pairs. See
`results/W2_REPORT.md` and `results/w2-aggregate-n5.json` for the report and
machine-readable aggregate.

## W3 repository feature fixture

W3 adds weighted, atomic quota consumption to a multi-module Python package and
requires the agent to add focused tests. Five interleaved pairs are complete.
See `results/W3_REPORT.md` and `results/w3-aggregate-n5.json`. Its ten final
workspaces are likewise reconstructible from the overlays under `evidence/W3/`.

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

## W9 DSH session state semantics

W9 is a DSH white-box mechanism suite with three independent deterministic
cases: a real hard crash followed by `ctx.agents.resume()` repair, a live Session
prefix fork with an open-turn negative case, and credential-free `llm-replay`
without a live provider credential for a normally completed session. See
`results/W9_REPORT.md` and
`results/w9-session-summary.json`.

The Python sdk-minimal carrier creates rather than cold-resumes a Session when a
new runtime receives `session/prompt`, so W9-A deliberately invokes the official
programmatic resume API after creating the crash through sdk-minimal.

## W10 DSH filesystem capability seam

W10 swaps `ctx.fs` between `fs-local` and `fs-sandbox` in an A/B/A-prime
sequence while retaining native `tool-fs` and the same deterministic call
script. The sandbox variant permits the inside edit and rejects the sibling-path
edit with `FS_SANDBOX_DENIED`. Native mutation schemas are expected to differ by
the sandbox escalation fields. See `results/W10_REPORT.md` and
`results/w10-fs-seam-summary.json`.

Run W10 from a checkout outside `/tmp` and the platform `os.tmpdir()`. Its
runner canonicalizes the sibling target and fails before execution when that
target falls under any filesystem-sandbox writable root, preventing a temporary
checkout from silently changing the expected denial into an allowed write.

W9 and W10 complement the cross-runtime workloads as DSH white-box mechanism
case studies. They must not be interpreted as DSH-versus-OpenClaw rankings.

## CPU-oriented benchmark

The next phase stops adding Harness feature cases and measures Host CPU work.
C1 scales a real in-process deterministic Agent Loop. C2 removes that loop and
scales append-only Session/Event Log primitives. C3 holds the Session/message
shape fixed while scaling context bytes through request assembly, JSON
encode/decode, and SSE parsing. C4 audits the pinned shell implementation and
compares its real managed one-shot path with raw one-shot and persistent
benchmark controls. C5 measures the DSH Native-to-PTC CPU crossover using its
real worker-thread code runtime and a deterministic Agent Loop. C6 measures the
allowed-operation overhead of swapping DSH's local filesystem capability for
its canonicalize-and-contain sandbox provider. All use exact semantic invariants,
randomized repetitions, scoped CPU timing, and optional whole-process
`perf stat`. C7 then scales independent deterministic DSH Agent processes from
1 to 32 physical cores. See
`CPU_BENCHMARK.md` for the designs and commands; the first ARM64 pilots are
documented in `results/C1_REPORT.md`, `results/C2_REPORT.md`, and
`results/C3_REPORT.md` through `results/C7_REPORT.md`, with complete samples in
the corresponding JSON files. `run-c1.py --warm-turns` provides a warm
steady-state fixed-context variant, and `run-c7.py --hard-pin` separates core
scaling from scheduler migration. C8 measures the token-meter / context-pressure
path (`TokenMeter.measure`) rather than a tokenizer, with cold, incremental,
repeat, and surface-shape subtests under `run-c8.py`; see
`results/C8_REPORT.md` for the pilot. That report is generated from the seven
validated pilot JSON files by `scripts/cpu/render-c8-report.py`, rather than from
hand-copied measurements. Every C1-C8 JSON also binds itself to the exact runner,
fixture, shared perf helper, and pinned upstream revisions through a protocol
hash. Validate those hashes and every sample invariant, then recompute
aggregates/fits from raw samples using the protocol-bound runner logic with:

```bash
scripts/cpu/verify-cpu-results.py
```

These remain same-host n=5 mechanism pilots. Protocol validation closes
code/result drift; it does not justify cross-processor rankings or statistical
claims about broader workloads.

After bootstrap, run the complete source/evidence/CPU/syntax audit with one
command:

```bash
scripts/verify-repository.sh
```

## Frozen evidence

The redacted evidence for W1-W10 is committed under `evidence/`. W1-W3 retain
normalized summaries and exact final-workspace overlays; W4-W10 retain request
logs, process records, case metadata, required workspace outputs, and selected
structured trace events. Verify the SHA256 manifest, rerun W1-W3 external
verifiers, rebuild their aggregates, and rebuild every W4-W10 summary with:

```bash
scripts/reproduce-evidence.sh
```

See `evidence/README.md` for the redaction and omission policy.

## Interpretation boundary

- W1-W3 compare the two native-minimal runtime packages under intentionally
  different tool surfaces; they do not isolate pure Harness overhead.
- W4-W8 are deterministic mechanism cases. Their conclusions apply to the
  injected protocol path and pinned revisions, not universal model quality or
  runtime robustness.
- W9-W10 are DSH-only white-box cases and provide no cross-runtime ranking.
- C1-C8 attribute local host mechanisms on one ARM64 host with five repetitions
  per point. Treat slopes, crossovers, and scale-out knees as pilot observations.
- W2/W3 final-state correctness is publicly reconstructible, but provider
  reasoning/transcripts are intentionally omitted; W3 therefore cannot identify
  the exact malformed streamed field from frozen evidence.

For W1-W3, “reconstructible” specifically means that the frozen manifest binds
the committed template tree and external verifier by SHA256, then applies the
frozen final-state overlay. Final files, changed paths/diff, and verifier outcome
are reproducible outcome evidence. Wall time, model/tool-call counts, and native
token counters are frozen run metadata copied from normalized summaries; they
cannot be independently derived without the deliberately omitted transcripts.

## State

- `sources/`: upstream source checkouts
- `configs/`: benchmark configuration templates
- `workspaces/`: disposable task copies only
- `sessions/`: isolated runtime state and DSH JSONL traces
- `results/`: benchmark result artifacts

The OpenClaw runner pins both `OPENCLAW_CONFIG_PATH` and an experiment-local `OPENCLAW_STATE_DIR`; it does not read the normal user state directory. Current `agent exec` rejects combining `--config` with `--auth-env-only`, so credential isolation is provided by that empty experiment-local state plus an environment-backed SecretRef. The OpenClaw custom provider uses `maxTokens: 256000` and `thinking: high` to match the DSH request header observed in the minimal trace.
