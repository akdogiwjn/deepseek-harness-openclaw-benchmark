# C8 token-meter / context-pressure CPU pilot

C8 measures the pinned DeepSeek Harness `TokenMeter.measure(session)` path, not a
tokenizer. The pinned `token-meter` prices content with a fixed `char/4` density
heuristic until exact tokenization is needed, so C8 attributes Host CPU to the
context-pressure accounting mechanism W5 establishes: how much CPU goes into
replaying, repricing, and cloning the model-visible session surface as it grows.

`measure()` is O(surface). Each call replays the durable tail through the
surface, reprices every positional node, and deep-clones the detached
measurement. Four subtests isolate that path.

## Design

- Subtests: `cold` (first measure on a full history), `incremental` (append one
  text turn then measure), `repeat` (fixed session, measure only), `shape`
  (`text`, `tool-call`, `tool-result`, `schema`).
- Surface node counts: 10, 100, 1,000, 5,000, 10,000. Payload 256 B (about 64
  heuristic tokens per node).
- Repetitions: 5 per point, randomly interleaved with seed 20260902.
- Affinity: logical CPU 0. Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, `perf_event_paranoid` 0, `user-kernel` perf mode.
- Iterations scale down with node count (`max(20, 1000 // max(1, n/1000))`) so
  each run keeps a similar measure-loop duration.
- Scope: `process.cpuUsage()` windows the measured measure calls (construction
  excluded); whole-process `perf stat` runs from Node startup through teardown
  and therefore includes construction.

## Results

`internal_cpu_us_per_measure` is the clean, construction-free per-call cost.
Linear fits over the node-count medians give these marginal slopes:

| Subtest | slope (us/node) | intercept (us) | meaning |
| ---: | ---: | ---: | --- |
| cold | 18.61 | 4066 | first measure replays the whole tail |
| incremental | 1.17 | 172 | append one turn + measure |
| repeat | 1.14 | -58 | repricing + clone only |

Repeat medians at each node count:

| Nodes | internal CPU (us) | wall (us) | IPC | kernel cycle ratio |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 35 | 106 | 1.43 | 0.16 |
| 100 | 120 | 122 | 1.89 | 0.11 |
| 1,000 | 996 | 1,002 | 2.59 | 0.05 |
| 5,000 | 5,530 | 5,556 | 2.15 | 0.10 |
| 10,000 | 11,444 | 11,486 | 1.65 | 0.12 |

Shape at 1,000 surface nodes shows the content type is nearly free:

| Shape | internal CPU (us) | heur. tokens/node | IPC |
| ---: | ---: | ---: | ---: |
| text | 1007 | 74.0 | 2.29 |
| tool-call | 1012 | 79.0 | 2.38 |
| tool-result | 996 | 76.0 | 2.34 |

Schema cost scales with the JSON byte count of `header.tools`, not the node
count, because `estimateHeader` re-runs `JSON.stringify(tools)` on every measure:

| Tools | schema bytes | internal CPU (us) |
| ---: | ---: | ---: |
| 8 | 4,865 | 89 |
| 32 | 19,479 | 99 |
| 128 | 77,971 | 152 |
| 512 | 312,211 | 486 |

## Interpretation

1. **Surface length stays linear.** Repeat measure is 1.14 us of CPU per node
   with a near-zero intercept, so context-pressure accounting scales linearly
   with the session surface.

2. **Cold replay dominates the one-time cost.** The first measure on a full
   history costs ~16x per node (18.61 vs 1.14 us) because `_sync` folds every
   event; repeated measure afterwards is repricing + clone only. The expensive
   part of recovery is replay, not the steady-state surface scan.

3. **Incremental re-measure is not cheap; it is the full O(surface) again.**
   Appending one turn adds an O(1) fold, but the following measure reprices the
   whole surface, so `incremental` (1.17 us/node) tracks `repeat` (1.14 us/node)
   rather than trending to O(1).

4. **Surface shape is a minor term.** At 1,000 nodes the three surface shapes
   differ by <2% CPU despite different heuristic token prices, so event count,
   not message shape, drives the accounting cost.

5. **Tool schema only matters at the MB scale.** `JSON.stringify(tools)` is
   ~1.3 us per KB; a KB-scale schema is under 0.1 ms of measure cost while a
   megabyte-scale schema reaches milliseconds.

## Limitations

- `TokenMeter` uses the fixed `char/4` heuristic, not a real BPE tokenizer.
- Session construction is superlinear in node count on this host (2.7 s to build
  10,000 nodes, 13 s for 25,000), so C8 caps the sweep at 10,000 nodes. This
  behavior is itself a finding but is not C8's target.
- Whole-process perf includes construction and the down-scaling iteration count,
  so whole-process cycles/instructions divide poorly into per-measure slopes (the
  negative intercepts are that artifact). Only internal `process.cpuUsage()`
  timing is construction-free; clean per-measure PMU needs a future scoped
  `perf --control` window.
- The IPC rises then falls with node count (1.43 -> 2.59 -> 1.65), consistent
  with growing clone/serialize working set, but C8 does not separate ILP from
  cache effects.
- Text payload is ASCII; reasoning/image blocks and provider-route image pricing
  are separate conditions.

Complete samples, perf labels, host metadata, medians, and fits are in the
corresponding `results/c8-token-meter-*-pilot.json` files.