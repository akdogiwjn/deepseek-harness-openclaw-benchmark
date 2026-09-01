# W8 direct tool calling versus code mode

W8 is a within-runtime executor-collapse ablation. A deterministic local
OpenAI-compatible SSE provider supplies eight sequential shell commands. Every
command appends a unique marker to `w8.log`, and an external check requires the
eight markers to appear exactly once and in order.

The direct conditions issue eight model-visible shell calls. DSH PTC exposes
only `run_code`, while OpenClaw Code Mode exposes only its `exec`/`wait` control
surface; one program then dispatches the same eight underlying shell calls. No
real model, external gateway, production credential, compaction, or context
pruning participates.

## Results

| Observation | DSH native | DSH PTC | OpenClaw direct | OpenClaw Code Mode |
| --- | ---: | ---: | ---: | ---: |
| Runtime completed | yes | yes | yes | yes |
| Underlying shell calls | 8 | 8 | 8 | 8 |
| Exact ordered markers | yes | yes | yes | yes |
| Provider requests | 9 | 2 | 9 | 2 |
| Model-visible tool calls | 8 | 1 | 8 | 1 |
| Process wall time | 3.734 s | 3.942 s | 6.314 s | 6.715 s |
| First request body | 6,349 B | 9,293 B | 17,501 B | 19,766 B |
| Sum of request bodies | 66,069 B | 19,455 B | 167,337 B | 43,329 B |
| First tool schema | 4,016 B | 975 B | 3,266 B | 5,563 B |

DSH PTC reduced the scripted turn from 9 to 2 provider requests and from 8 to 1
model-visible tool calls. Total serialized request traffic fell by 46,614 bytes
(70.6%). OpenClaw Code Mode produced the same 9-to-2 and 8-to-1 collapse; total
request traffic fell by 124,008 bytes (74.1%). OpenClaw's own result metadata
reported `codeModeEngaged: true`, two assistant turns, and eight bridge calls,
which independently confirms that the single outer control call dispatched all
eight hidden tools. DSH's persisted session likewise contains one outer
`tool/call`, eight `tool/code-dispatch-start` records, and eight matching
`tool/code-dispatch` records.

## Interpretation

The result directly demonstrates the mechanism both code modes target: repeated
`LLM -> tool -> LLM` transitions can become one `LLM -> program` transition with
multiple internal tool dispatches. This reduces provider round trips and repeated
context transmission without reducing the underlying work.

The first code-mode request was larger than its direct counterpart in both
runtimes because it includes SDK/catalog instructions. Amortization occurred
only because eight calls were collapsed. The tool-schema direction differed:
DSH's single `run_code` schema was smaller than its two native schemas, whereas
OpenClaw's two richly documented control schemas were larger than its five
minimal direct schemas. Prompt bytes and schema bytes therefore need separate
accounting.

Code mode was slightly slower in these single cold-process local runs: +0.208 s
for DSH and +0.400 s for OpenClaw. That does not contradict executor collapse.
The mock has effectively zero network/model latency, so it removes the cost that
fewer provider requests normally saves while retaining code-runtime startup and
bridge overhead. These wall times are useful mechanism traces, not evidence that
either mode is generally faster or slower.

This experiment also is not a DSH-versus-OpenClaw ranking. The defensible
comparison is native versus code within each runtime. The runtimes still have
different prompts, native tool surfaces, code engines, startup paths, and result
rendering.
