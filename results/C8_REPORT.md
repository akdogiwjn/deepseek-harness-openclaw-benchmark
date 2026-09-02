# C8 token-meter / context-pressure CPU pilot

C8 measures the pinned DeepSeek Harness `TokenMeter.measure(session)` path, not a
tokenizer. The pinned `token-meter` prices ordinary text with a fixed `char/4`
density heuristic; C8 does not measure a provider tokenizer. It attributes Host
CPU to the context-pressure accounting mechanism W5 establishes: how much CPU
goes into replaying, repricing, and cloning the model-visible session surface as
it grows.

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
- Scope: `process.cpuUsage()` and `hrtime` are read once around the whole
  measure batch and divided by iterations, so timer overhead is amortized and
  construction is excluded; whole-process `perf stat` runs from Node startup
  through teardown and therefore includes construction.

## Results

`internal_cpu_us_per_measure` is the clean, construction-free per-call cost.
Linear fits over the node-count medians give these marginal slopes:

| Subtest | slope (us/node) | intercept (us) | meaning |
| ---: | ---: | ---: | --- |
| cold | 18.95 | 4113 | first measure replays the whole tail |
| incremental | 1.26 | 87 | append one turn + measure (effective surface) |
| repeat | 1.15 | 15 | repricing + clone only |

Repeat medians at each node count:

| Nodes | internal CPU (us) | wall (us) | IPC | kernel cycle ratio |
| ---: | ---: | ---: | ---: | ---: |
| 10 | 51 | 51 | 1.51 | 0.13 |
| 100 | 139 | 137 | 1.92 | 0.09 |
| 1,000 | 1,073 | 1,073 | 2.56 | 0.04 |
| 5,000 | 5,853 | 5,875 | 2.19 | 0.07 |
| 10,000 | 11,457 | 11,508 | 1.64 | 0.30 |

Shape at 1,000 surface nodes shows the content type is nearly free:

| Shape | internal CPU (us) | heur. tokens/node | IPC |
| ---: | ---: | ---: | ---: |
| text | 1062 | 74.0 | 2.35 |
| tool-call | 1088 | 79.0 | 2.30 |
| tool-result | 1071 | 76.0 | 2.29 |

Schema cost scales with the JSON byte count of `header.tools`, not the node
count, because `estimateHeader` re-runs `JSON.stringify(tools)` on every measure:

| Tools | schema bytes | internal CPU (us) |
| ---: | ---: | ---: |
| 8 | 4,865 | 135 |
| 32 | 19,479 | 139 |
| 128 | 77,971 | 198 |
| 512 | 312,211 | 591 |

## Interpretation

1. **Surface length stays linear.** Repeat measure is 1.15 us of CPU per node
   with a near-zero intercept, so context-pressure accounting scales linearly
   with the session surface.

2. **Cold replay dominates the one-time cost.** The first measure on a full
   history costs ~16x per node (18.95 vs 1.15 us) because `_sync` folds every
   event; repeated measure afterwards is repricing + clone only. The expensive
   part of recovery is replay, not the steady-state surface scan. In this fixture
   each text surface node corresponds to three durable session events
   (`turn/start`, `user/message`, `turn/end`), so the cold slope is a
   per-surface-node cost for this fixed log shape, not a universal per-event
   figure.

3. **Incremental re-measure is not cheap; it is the full O(surface) again.**
   Appending one turn adds an O(1) fold, but the following measure reprices the
   whole surface, so `incremental` (1.26 us/node) tracks `repeat` (1.15 us/node)
   rather than trending to O(1). The incremental x-axis is the effective
   mid-range surface size `N + (K+1)/2`, not the initial `N`.

4. **Surface shape is a minor term.** At 1,000 nodes the three surface shapes
   differ by <2% CPU despite different heuristic token prices, so event count,
   not message shape, drives the accounting cost for this fixed 256 B payload and
   simple text/tool blocks. Reasoning, image, and provider-image-pricing blocks
   were not measured.

5. **Schema cost stayed sub-millisecond through the measured ~312 KB.**
   `JSON.stringify(tools)` fits to ~1.5 us per KB on this host; a KB-scale schema
   is under 0.1 ms of measure cost, and the observed slope only predicts (it does
   not measure) that megabyte-scale schemas reach millisecond-level cost.

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
- Whole-process IPC changes with node count (1.51 -> 2.56 -> 1.64), but it cannot
  currently be attributed to `TokenMeter.measure()` because `perf stat` includes
  Session construction.
- Text payload is ASCII; reasoning/image blocks and provider-route image pricing
  are separate conditions.

Complete samples, perf labels, host metadata, medians, and fits are in the
corresponding `results/c8-token-meter-*-pilot.json` files.