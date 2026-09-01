# W5 deterministic automatic compaction

W5 mounts automatic compaction on top of the existing minimal runtimes. DSH adds
only `token-meter` and `compaction-basic` through an official profile patch;
OpenClaw enables default compaction and its mid-turn precheck while leaving Code
Mode, memory flush, context pruning, browser, memory tools, and other capabilities
disabled.

A local OpenAI-compatible mock scripts bounded 4,096-character shell outputs and
returns the same fixed short summary whenever either runtime makes a compaction
request. No real model, external gateway, production credential, or summary
quality variance participates.

## Calibrated main pair

The main pair uses a 32K effective context window, keeps 2K recent tokens, and
executes eight identical tool calls. Numeric thresholds are deliberately not
equal: DSH uses a 4.8K heuristic threshold while OpenClaw's effective prompt
budget is 12K. This calibration is necessary because the runtimes have different
fixed prompt envelopes and token estimators. It aligned all three observed
trigger positions: after agent requests 4, 6, and 8.

| Observation | DeepSeek Harness | OpenClaw |
| --- | ---: | ---: |
| Runtime completed | yes | yes |
| Tool calls | 8 | 8 |
| Agent requests | 9 | 9 |
| Compaction requests | 3 | 3 |
| Total provider requests | 12 | 12 |
| Process wall time | 3.689 s | 7.170 s |
| Start to first request | 0.493 s | 5.410 s |
| First to final request | 2.002 s | 1.542 s |
| Median inter-request interval | 0.185 s | 0.100 s |
| All request-body bytes | 192,522 B | 239,817 B |
| Agent request bytes | 140,106 B | 217,950 B |
| Compaction request bytes | 52,416 B | 21,867 B |
| Maximum agent request | 20,162 B | 30,850 B |
| Final agent request | 15,718 B | 22,442 B |

Both runtimes preserved `ANCHOR_ALPHA`, installed the fixed summary in subsequent
context, and completed the chain. Their payload tradeoff differs:

- OpenClaw sent 1.56 times as many agent-request bytes because its direct runtime
  prompt envelope remained larger before and after compaction.
- DSH sent 2.40 times as many compaction-request bytes. Its compactor replays the
  conversation's system prompt, tool schemas, and selected history to reuse the
  provider prefix cache; OpenClaw's observed summary calls used a separate
  summarization prompt with no tool schemas.
- OpenClaw's first rewrite reduced the next agent body by 8,346 bytes versus
  4,105 for DSH. Later rewrites reduced about 4.4–4.5 KB in both runtimes.

The source-level strategy matches the trace. DSH documents and implements
compaction on every `agent/pre-step` in
`packages/compaction/compaction-basic/src/index.ts:148`, and builds its auxiliary
call by replaying the original request prefix in
`packages/compaction/compaction-basic/src/summarizer.ts:151`. OpenClaw's mid-turn
guard estimates tool-result pressure before the next provider call in
`src/agents/embedded-agent-runner/tool-result-context-guard.ts:478`.

## Same-numeric 16K stress pair

An additional stress case used the same 16K window, 8K trigger, 2K retention,
and planned ten tool calls without trigger calibration.

| Observation | DeepSeek Harness | OpenClaw |
| --- | ---: | ---: |
| Runtime completed | yes | no |
| Agent requests | 11 | 5 |
| Compaction requests | 1 | 3 |
| Final status | completed | `context_overflow` |

OpenClaw's larger fixed envelope crossed the same numeric threshold much earlier.
Each rewrite made progress, but another pair of large tool results crossed the
budget again. After three recovery compactions it returned `Context overflow:
prompt too large for the model (precheck).` The pinned runtime defines the
effective reserve floor and the three-attempt cap in
`src/agents/agent-compaction-constants.ts:6` and `:30`.

This stress result proves a profile-level interaction between prompt envelope,
estimator, recovery budget, and compaction policy. It does not establish that DSH
has universally better compaction or that OpenClaw fails at realistic production
context sizes.

## Scope

The calibrated pair compares compaction mechanics after aligning trigger points;
the stress pair compares the native policies under the same numeric pressure.
Neither is a tool-equivalent or model-quality comparison. Payload bytes are not
tokens, and the single-run timing values are mechanism traces rather than
population-level performance estimates.
