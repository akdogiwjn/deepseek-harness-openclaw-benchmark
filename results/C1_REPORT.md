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
- PMU: Linux perf 6.6 with user+kernel counting (`perf_event_paranoid=-1`).

Internal CPU/wall measurements cover prompt enqueue through agent idle. Perf
counters cover the whole Node process, including V8 startup, Harness
composition, the measured turn, and disposal. Consequently their intercept is
large and must not be confused with prompt-window Agent Loop work.

## Median observations

| Tool steps | Internal CPU (ms) | Internal wall (ms) | Instructions (M) | Cycles (M) | Max RSS (MiB) | IPC | Generic cache MPKI |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 8.41 | 7.66 | 568.23 | 425.30 | 64.996 | 1.33 | 7.00 |
| 1 | 12.71 | 12.58 | 589.03 | 440.79 | 66.996 | 1.34 | 7.07 |
| 4 | 23.70 | 23.67 | 624.26 | 465.78 | 68.996 | 1.33 | 7.15 |
| 16 | 46.79 | 46.21 | 704.59 | 524.08 | 71.02 | 1.36 | 7.54 |
| 64 | 138.31 | 138.46 | 1,097.11 | 797.97 | 75.02 | 1.38 | 8.18 |
| 256 | 466.23 | 467.54 | 2,767.15 | 1,805.28 | 85.00 | 1.53 | 8.23 |

An ordinary least-squares fit over the six step-count medians produced these
descriptive marginal slopes for this host and fixture:

- internal CPU: 1.771 ms per tool step;
- whole-process instructions: 8.551 million per tool step;
- whole-process cycles: 5.353 million per tool step;
- max RSS: 70.7 KiB per tool step.

These slopes combine Agent Loop work with context derivation over a Session that
grows every step. They are not a fixed-context primitive cost and should not be
generalized to other models, adapters, Harness compositions, CPUs, or ISAs.

Generic cache MPKI rose from 7.00 at the completion-only baseline to 8.23 at 256
tool steps. That is consistent with a growing working set, but C1 alone cannot
attribute the change to Session traversal, JSON/object growth, or another V8
effect. A fixed-context loop condition and the planned Session/context
microbenchmarks are required for that attribution.

This rerun counts both user and kernel execution, so scheduling and page-fault
counters are no longer discarded solely because of a user-only event suffix.
The generic cache events remain portable aggregate counters rather than an
architecture-specific LLC attribution. Prompt-window `process.resourceUsage()`
deltas remain in the raw samples as a separate source.

This is an n=5 mechanism pilot, not a formal processor comparison. The complete
samples, exact perf labels, host topology, medians, ranges, derived metrics, and
linear fits are retained in `results/c1-agent-loop-pilot.json`; the committed
JSON is protocol-hash checked and aggregate-recomputed by
`scripts/cpu/verify-cpu-results.py`.
