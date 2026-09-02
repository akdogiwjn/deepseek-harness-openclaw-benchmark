# C2 Session/Event Log event-count CPU pilot

C2 isolates five DeepSeek Harness Session primitives while a deterministic
fixture removes model, network, and tool execution. It scales completed
user-only turns and measures in-memory append, message derivation, prefix fork,
uncompressed JSONL persistence, and fresh-backend load from the warm host page
cache.

## Design

- Turns: 1, 10, 100, 1,000, 5,000.
- Events: 3 per turn, or 3 through 15,000 total events.
- Event shape: `turn/start`, `user/message`, `turn/end`.
- User payload: fixed at 256 bytes per turn.
- Repetitions: 5 per point, randomly interleaved with seed 20260902.
- Affinity: logical CPU 0.
- Persistence: uncompressed JSONL with chunk packing disabled.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 2 sockets, 4 NUMA nodes.
- PMU: Linux perf 6.6; all observed event labels carried `:u` because
  `perf_event_paranoid=2`.

The fixture constructs messages before timing append. Every sample verifies the
exact event and derived-message counts, all payloads, the complete fork prefix
and seed boundary, and byte-for-object equivalence of all reloaded events and
the relevant header fields.

## Median observations

| Events | Append CPU (ms) | Derive CPU (ms) | Fork CPU (ms) | JSONL write CPU (ms) | Warm load CPU (ms) | Log (MiB) | Max RSS (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 1.24 | 0.11 | 0.88 | 4.82 | 5.18 | 0.001 | 55.27 |
| 30 | 3.13 | 0.14 | 1.61 | 5.54 | 8.14 | 0.006 | 57.52 |
| 300 | 14.57 | 0.18 | 8.30 | 9.46 | 16.27 | 0.063 | 66.62 |
| 3,000 | 79.77 | 0.47 | 72.61 | 61.30 | 57.58 | 0.633 | 87.02 |
| 15,000 | 320.42 | 1.89 | 252.80 | 212.99 | 127.11 | 3.186 | 159.78 |

Ordinary least-squares fits over the five event-count medians produced these
descriptive marginal slopes for this host and event shape:

- in-memory append: 21.05 microseconds of CPU per event;
- `deriveMessages()`: 0.117 microseconds of CPU per event;
- prefix fork: 16.66 microseconds of CPU per event;
- uncompressed JSONL write: 13.80 microseconds of CPU per event;
- warm-page-cache JSONL load: 7.78 microseconds of CPU per event;
- serialized log growth: 222.75 bytes per event;
- whole-process instructions: 365,624 per event;
- whole-process cycles: 182,279 per event;
- process maximum RSS: 6.85 KiB per event.

The operation timings are scoped measurements, whereas instructions, cycles,
and maximum RSS cover the entire Node process: V8 startup, Harness composition,
all five operations, cleanup, and teardown. Those whole-process slopes cannot
be attributed to one Session primitive.

`deriveMessages()` is inexpensive in this fixture relative to append, fork, and
persistence. This is evidence only for completed user-only turns. Tool calls,
tool results, streaming chunks, compaction events, and surface mutations can
have different derivation behavior and remain separate conditions.

Load creates a fresh persistence backend so it does not reuse the writer's
prepared-session cache, but the host page cache is intentionally warm. The
result is not a cold-storage latency measurement. Likewise, the event-count
sweep fixes payload size at 256 bytes and cannot establish cycles per context
byte; payload-size scaling belongs in the context/serialization condition.

The fitted intercepts are material, the smallest points are dominated by fixed
setup work, and the five medians are not perfectly linear. Treat the slopes as
compact descriptions of this pilot rather than universal constants. The `:u`
perf restriction also excludes kernel execution and makes zero-valued
scheduling counters non-interpretable.

This is an n=5 mechanism pilot, not a processor comparison. The complete
samples, exact perf labels, host metadata, medians, ranges, checks, and fits are
retained in `results/c2-session-count-pilot.json`.
