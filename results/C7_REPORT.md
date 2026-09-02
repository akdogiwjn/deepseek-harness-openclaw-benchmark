# C7 multi-process Agent scale-out CPU pilot

C7 measures host-side scale-out after the single-process C1-C6 mechanism cases.
Each Agent runs in an independent Node process with its own real DSH Context,
Session, deterministic in-process adapter, Agent Loop, and no-op tool. One
controller starts all Agents concurrently and validates every child result.

## Design

- Concurrent Agents: 1, 2, 4, 8, 16, 32.
- Work per Agent: 64 no-op tool steps, 65 provider requests, 64-byte payload/result.
- Repetitions: 5 per point, randomly interleaved with seed 20260902.
- Scope: process launch, DSH composition, measured turn, and process exit.
- CPU selection: first logical CPU for each distinct `(socket, core)` pair;
  nested prefixes produce `0`, `0,2`, ..., `0,2,...,62` on this SMT2 host.
- Placement: all selected cores are on socket 0 / NUMA node 0.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 128 physical cores, 2 sockets,
  4 NUMA nodes.
- PMU: Linux perf 6.6 with descendant inheritance; labels carried `:u`.

Every batch verifies child count and stderr, every C1 semantic invariant,
per-child tool steps and provider requests, and total tool invocations.

## Median observations

| Agents | Batch wall (ms) | Agents/s | Throughput speedup | Parallel efficiency | Avg user CPU cores | Sum child max RSS (MiB) | User instructions/Agent (M) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 282.0 | 3.55 | 1.00x | 100.0% | 1.10 | 75.0 | 1,150.7 |
| 2 | 279.1 | 7.17 | 2.02x | 101.1% | 2.09 | 148.0 | 1,089.9 |
| 4 | 281.3 | 14.22 | 4.01x | 100.3% | 4.00 | 294.1 | 1,062.8 |
| 8 | 290.3 | 27.55 | 7.77x | 97.1% | 7.74 | 590.6 | 1,047.7 |
| 16 | 332.9 | 48.06 | 13.55x | 84.7% | 13.64 | 1,069.9 | 1,039.3 |
| 32 | 365.9 | 87.45 | 24.66x | 77.1% | 25.48 | 2,089.5 | 1,038.5 |

Throughput remains effectively linear through four Agents and retains 97%
parallel efficiency at eight. The knee appears between eight and sixteen on
this placement: batch wall rises from 290 to 333 ms, then to 366 ms at 32.
Despite declining efficiency, 32 Agents still deliver 24.66 times the one-Agent
throughput, or about 5,597 no-op tool steps per second.

The experiment deliberately chooses different physical cores rather than SMT
siblings. It does not spread work across NUMA nodes, so the 16/32-Agent decline
cannot be generalized to the whole 128-core host. Shared loader/storage state,
memory allocation, process launch, controller serialization, frequency changes,
and same-node memory/cache contention can all contribute; C7 does not isolate
them.

Perf covers controller and descendants, but its scope begins before the
controller's own spawn-to-completion timer. Consequently `task-clock / batch
wall` slightly exceeds one core at N=1 and is only an approximate average at
larger N. `:u` also excludes kernel work and makes scheduling counters
non-interpretable. The apparent decline in instructions per Agent partly
amortizes fixed controller/runtime startup counters and should not be read as
individual Agents doing less semantic work.

`sum_child_max_rss_kb` is the sum of each child's independently observed peak,
not a synchronized system-wide peak. It grows from about 75 MiB at one Agent to
2.04 GiB at 32, providing a capacity estimate rather than an exact concurrent
resident-set trace.

This is a same-host n=5 scale-out pilot with a zero-latency mock model and no-op
tools. Real provider concurrency limits, network latency, shared-process Agent
topologies, shell/filesystem tools, cross-NUMA placement, SMT placement, and
sustained steady-state service load remain separate experiments. Complete
samples and topology metadata are in `results/c7-agent-scaleout-pilot.json`.
