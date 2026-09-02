# C1 in-process Agent Loop CPU pilot

C1 measures a real DeepSeek Harness Agent Loop driven by an in-process
deterministic adapter. Each tool step emits one fixed-size native `noop` call and
result; one final model step completes the turn. The fixture uses an in-memory
append-only Session and verifies every request, step, tool call, tool result, and
turn boundary before accepting a sample.

## Design

- Tool steps: 0, 1, 4, 16, 64, 256 (`N = 0` is completion-only).
- Repetitions: 5 per point, randomly interleaved with seed 20260902.
- Payload and result: 64 bytes each.
- Affinity: logical CPU 0.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 2 sockets, 4 NUMA nodes.
- PMU: Linux perf 6.6; all observed event labels carried `:u` because
  `perf_event_paranoid=2`.

Internal CPU/wall measurements cover prompt enqueue through agent idle. Perf
counters cover the whole Node process, including V8 startup, Harness
composition, the measured turn, and disposal. Consequently their intercept is
large and must not be confused with prompt-window Agent Loop work.

## Median observations

| Tool steps | Internal CPU (ms) | Internal wall (ms) | Instructions (M) | Cycles (M) | Max RSS (MiB) | IPC | Generic cache MPKI |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 8.34 | 7.86 | 517.86 | 361.40 | 62.99 | 1.44 | 6.57 |
| 1 | 13.22 | 12.48 | 534.12 | 375.05 | 64.99 | 1.43 | 6.69 |
| 4 | 22.52 | 22.51 | 568.06 | 406.84 | 66.99 | 1.40 | 6.76 |
| 16 | 47.61 | 47.71 | 656.94 | 464.24 | 68.99 | 1.41 | 7.16 |
| 64 | 137.45 | 136.86 | 1,031.03 | 716.97 | 72.99 | 1.44 | 7.94 |
| 256 | 470.19 | 471.33 | 2,682.70 | 1,697.74 | 80.99 | 1.58 | 7.97 |

An ordinary least-squares fit over the six step-count medians produced these
descriptive marginal slopes for this host and fixture:

- internal CPU: 1.787 ms per tool step;
- whole-process instructions: 8.424 million per tool step;
- whole-process cycles: 5.172 million per tool step;
- max RSS: 62.6 KiB per tool step.

These slopes combine Agent Loop work with context derivation over a Session that
grows every step. They are not a fixed-context primitive cost and should not be
generalized to other models, adapters, Harness compositions, CPUs, or ISAs.

Generic cache MPKI rose from 6.57 at the completion-only baseline to 7.97 at 256
tool steps. That is consistent with a growing working set, but C1 alone cannot
attribute the change to Session traversal, JSON/object growth, or another V8
effect. A fixed-context loop condition and the planned Session/context
microbenchmarks are required for that attribution.

The `:u` restriction makes zero perf context-switch and migration counts
non-interpretable: kernel-side scheduling was excluded. Prompt-window
`process.resourceUsage()` deltas remain in the raw samples as a separate source.

This is an n=5 mechanism pilot, not a formal processor comparison. The complete
samples, exact perf labels, host topology, medians, ranges, derived metrics, and
linear fits are retained in `results/c1-agent-loop-pilot.json`.
