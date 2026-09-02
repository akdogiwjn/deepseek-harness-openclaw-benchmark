# C5 DSH native-vs-PTC CPU pilot

C5 evolves W8 from an eight-operation protocol demonstration into a local CPU
scaling experiment. Both conditions use the same real DSH Agent Loop,
in-process deterministic LLM adapter, fixed `noop` tool, Session, and payload.
Only tool presentation and execution topology change:

- `native`: one provider-visible tool call per operation, then completion;
- `ptc`: one provider-visible `run_code` call whose real worker-thread runtime
  invokes all tools sequentially, then completion.

This is a DSH internal A/B, not a DSH-versus-OpenClaw comparison.

## Design

- Tool operations: 0, 1, 4, 16, 64, 256, 1,024.
- Repetitions: 5 per mode and count, randomly interleaved with seed 20260902.
- Tool payload/result: fixed 16-byte strings; no I/O or shell execution.
- PTC runtime: pinned `WorkerThreadCodeRuntime`, one fresh worker per program.
- PTC subcalls: sequential, matching Native's operation order.
- Affinity: logical CPU 0.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 2 sockets, 4 NUMA nodes.
- PMU: Linux perf 6.6; all observed labels carried `:u`.

Every sample verifies provider request count and presented tool name, exact noop
invocation count and payloads, outer tool calls/results, PTC dispatch
start/settle counts, Agent steps, and one completed turn.

## Median observations

| Operations | Native requests | PTC requests | Native wall (ms) | PTC wall (ms) | Native instructions (M) | PTC instructions (M) | Native RSS (MiB) | PTC RSS (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 2 | 9.4 | 100.5 | 524.7 | 1,056.2 | 65.0 | 97.0 |
| 1 | 2 | 2 | 14.4 | 103.9 | 541.3 | 1,066.0 | 65.0 | 98.5 |
| 4 | 5 | 2 | 24.2 | 108.4 | 584.8 | 1,080.2 | 67.0 | 97.9 |
| 16 | 17 | 2 | 46.7 | 135.6 | 675.5 | 1,114.0 | 69.0 | 100.1 |
| 64 | 65 | 2 | 135.8 | 156.5 | 1,095.1 | 1,178.4 | 73.0 | 100.2 |
| 256 | 257 | 2 | 466.7 | 272.7 | 2,687.1 | 1,563.6 | 81.0 | 112.1 |
| 1,024 | 1,025 | 2 | 3,159.0 | 547.4 | 17,380.0 | 2,528.9 | 146.2 | 116.4 |

PTC has a substantial fixed cost: even a zero-subcall program took about 100 ms
and 1.06 billion whole-process user-space instructions, versus 9.4 ms and 0.52
billion for Native completion-only. That fixed cost includes the extra Agent
step, PTC bridge, TypeScript stripping, fresh worker creation, message ports,
and worker teardown.

As operation count grows, Native performs one complete provider/Agent step per
tool while PTC remains at two provider requests. Session event count is exactly
`15 + 10N` for Native and `25 + 2N` for PTC in this fixture. At 64 operations,
PTC was still 15% slower and used 8% more instructions. At 256 it used 42% less
wall time and 42% fewer instructions; at 1,024 it used 83% less wall time and
85% fewer instructions.

The observed crossover therefore lies between 64 and 256 no-op operations for
this host and implementation. It is not a recommended production threshold.
Real model/network latency would make avoided provider requests far more
valuable, while expensive tools would reduce the local-runtime fraction.
Parallel PTC subcalls, nontrivial program computation, large arguments/results,
errors, and shell/filesystem calls are separate conditions.

The 1,024-operation Native point also grows more steeply than the lower points,
consistent with repeatedly deriving and appending a much larger Session. A
single linear slope over all seven points has a negative Native intercept and
is descriptive only; the pointwise medians are the primary result.

Whole-process perf includes Node/V8 startup, Harness composition, the measured
turn, worker lifecycle, and teardown. The `:u` restriction excludes kernel work
and makes zero scheduling counters non-interpretable. This is an n=5 mechanism
pilot, not a real-model performance claim or processor comparison. Complete
samples and fits are in `results/c5-code-mode-cpu-pilot.json`.
