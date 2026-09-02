# C8 token-meter / context-pressure CPU pilot

C8 measures the pinned DeepSeek Harness `TokenMeter.measure(session)` path, not a
tokenizer. The pinned implementation uses a fixed `char/4` text heuristic. A
measurement synchronizes only unread durable events, reprices every current
surface node, then structured-clones and deep-freezes the detached result.

## Design

- `cold`: first measurement over a complete unread history.
- `incremental`: append one text turn and measure repeatedly after an initial sync.
- `repeat`: fixed, already-synced session; full surface reprice + clone only.
- non-schema `shape`: first cold replay of equal event/node counts containing
  `text`, `tool-call`, or `tool-result` messages, so original block pricing is timed.
- `schema`: repeated header measurement over a pre-synced 32-node surface; exact
  schema, baseline, and total-token invariants are verified.
- Main node counts: 10, 100, 1,000, 5,000, 10,000; payload 256 B.
- Repetitions: 5 per point; affinity CPU 0.
- Runtime: aarch64, v24.15.0, perf mode `user-kernel`.
- Primary metrics are internal `process.cpuUsage()` and `hrtime` around the stated
  measurement window. Whole-process PMU counters are diagnostic only.

## Results

Linear fits over point medians:

| Subtest | CPU slope (us/node) | CPU intercept (us) |
| --- | ---: | ---: |
| cold | 18.31 | 3366 |
| incremental | 1.19 | 140 |
| repeat | 1.20 | -80 |

Repeat medians:

| Surface nodes | internal CPU (us) | wall (us) |
| ---: | ---: | ---: |
| 10 | 51 | 51 |
| 100 | 135 | 132 |
| 1,000 | 1051 | 1051 |
| 5,000 | 5649 | 5664 |
| 10,000 | 12113 | 12149 |

Cold shape replay at 1,000 surface nodes (five durable events per node
in every condition):

| Shape | internal CPU (us) | wall (us) | heuristic tokens/node |
| --- | ---: | ---: | ---: |
| text | 33535 | 33543 | 74.0 |
| tool-call | 34458 | 34487 | 79.0 |
| tool-result | 34644 | 34670 | 76.0 |

Schema header measurement:

| Tools | schema bytes | schema tokens | internal CPU (us) |
| ---: | ---: | ---: | ---: |
| 8 | 4,865 | 1,221 | 142 |
| 32 | 19,479 | 4,874 | 135 |
| 128 | 77,971 | 19,497 | 201 |
| 512 | 312,211 | 78,057 | 572 |

## Interpretation

1. Repeat measurement is linear over this range at 1.20
   us of CPU per retained surface node. This is the steady-state full-surface
   reprice + clone cost, not event replay.

2. Cold first measurement is about 15.2x more expensive per surface
   node for this fixed three-event text-turn log because it must also fold every
   unread event and price the original message.

3. Incremental append + measure tracks repeat scan (1.19
   vs 1.20 us/node). Append synchronizes the new
   tail, but the following measure still reprices and clones the complete surface.

4. Cold replay shape differed by 3.3% peak-to-peak at 1,000
   nodes in this ASCII 256 B fixture. This result includes message derivation and
   heuristic pricing, but does not cover reasoning, images, or provider image pricing.

5. Schema's marginal fitted cost is 1.46 us per decimal KB over
   the measured range. The total measurement also contains the fixed 32-node surface
   scan, represented by the fitted intercept; marginal schema cost must not be confused
   with total `measure()` latency.

## Limitations

- Token counts use a fixed heuristic, not a provider BPE tokenizer.
- Internal CPU timing has no scoped PMU counters. Whole-process perf includes Node
  startup, Session construction, measured calls, and teardown and is diagnostic only.
- Cold and repeat use different replay state by design; their difference is a mechanism
  decomposition, not an interchangeable production latency comparison.
- Linear-fit intercepts are descriptive over the measured points and may be negative;
  they are not physical zero-node cost estimates.
- The incremental x-axis is the midpoint surface size `N + (K+1)/2` of each batch.
- This is a same-host mechanism pilot, not a cross-processor performance claim.

All table values are generated from the corresponding
`results/c8-token-meter-*-pilot.json` files by
`scripts/cpu/render-c8-report.py`; the generator validates sample counts, fixture
checks, and aggregate medians before writing this report.
