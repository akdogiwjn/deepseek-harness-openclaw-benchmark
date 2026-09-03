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
- CPU selection: the controller is unbound; worker processes receive nested
  prefixes `0`, `0,2`, ..., `0,2,...,62`, one logical thread per physical core.
- Placement: all selected worker cores are on socket 0 / NUMA node 0.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 128 physical cores, 2 sockets,
  4 NUMA nodes.
- PMU: Linux perf 6.6 with descendant inheritance and user+kernel counting
  (`perf_event_paranoid=-1`).

Every batch verifies child count and stderr, every C1 semantic invariant,
per-child tool steps and provider requests, and total tool invocations.

## Median observations

| Agents | Batch wall (ms) | Agents/s | Throughput speedup | Parallel efficiency | Avg CPU cores | Sum child max RSS (MiB) | Instructions/Agent (M) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 280.0 | 3.57 | 1.00x | 100.0% | 1.11 | 75.0 | 1,240.7 |
| 2 | 278.2 | 7.19 | 2.01x | 100.7% | 2.09 | 150.0 | 1,174.4 |
| 4 | 283.6 | 14.10 | 3.95x | 98.7% | 3.99 | 288.5 | 1,139.8 |
| 8 | 293.1 | 27.29 | 7.64x | 95.5% | 7.68 | 578.5 | 1,122.5 |
| 16 | 361.2 | 44.30 | 12.40x | 77.5% | 12.84 | 1,063.8 | 1,129.0 |
| 32 | 384.7 | 83.17 | 23.29x | 72.8% | 24.69 | 2,122.3 | 1,137.2 |

Throughput remains effectively linear through four Agents and retains 95.5%
parallel efficiency at eight. The knee appears between eight and sixteen on
this placement: batch wall rises from 293 to 361 ms, then to 385 ms at 32.
Despite declining efficiency, 32 Agents still deliver 23.29 times the one-Agent
throughput, or about 5,323 no-op tool steps per second.

The experiment deliberately chooses different physical cores rather than SMT
siblings. It does not spread work across NUMA nodes, so the 16/32-Agent decline
cannot be generalized to the whole 128-core host. Shared loader/storage state,
memory allocation, process launch, controller serialization, frequency changes,
and same-node memory/cache contention can all contribute; C7 does not isolate
them.

Perf covers controller and descendants, but its scope begins before the
controller's own spawn-to-completion timer. Consequently `task-clock / batch
wall` slightly exceeds one core at N=1 and is only an approximate average at
larger N. It includes user and kernel work in this rerun. The apparent decline
in instructions per Agent partly
amortizes fixed controller/runtime startup counters and should not be read as
individual Agents doing less semantic work.

`sum_child_max_rss_kb` is the sum of each child's independently observed peak,
not a synchronized system-wide peak. It grows from about 75 MiB at one Agent to
2.07 GiB at 32, providing a capacity estimate rather than an exact concurrent
resident-set trace.

This is a same-host n=5 scale-out pilot with a zero-latency mock model and no-op
tools. Real provider concurrency limits, network latency, shared-process Agent
topologies, shell/filesystem tools, cross-NUMA placement, SMT placement, and
sustained steady-state service load remain separate experiments. Complete
samples and topology metadata are in `results/c7-agent-scaleout-pilot.json`;
`scripts/cpu/verify-cpu-results.py` checks protocol hashes, sample invariants,
aggregates, and scaling calculations.
