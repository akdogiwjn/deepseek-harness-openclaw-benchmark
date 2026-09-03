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
- PMU: Linux perf 6.6 with user+kernel counting (`perf_event_paranoid=-1`).

The fixture constructs messages before timing append. Every sample verifies the
exact event and derived-message counts, all payloads, the complete fork prefix
and seed boundary, and byte-for-object equivalence of all reloaded events and
the relevant header fields.

## Median observations

| Events | Append CPU (ms) | Derive CPU (ms) | Fork CPU (ms) | JSONL write CPU (ms) | Warm load CPU (ms) | Log (MiB) | Max RSS (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 0.77 | 0.11 | 0.88 | 4.57 | 4.84 | 0.001 | 55.28 |
| 30 | 3.81 | 0.14 | 1.62 | 5.46 | 8.16 | 0.006 | 57.27 |
| 300 | 13.69 | 0.18 | 10.06 | 9.14 | 16.27 | 0.063 | 67.07 |
| 3,000 | 77.11 | 0.43 | 69.92 | 58.58 | 48.93 | 0.633 | 87.19 |
| 15,000 | 315.09 | 1.76 | 233.20 | 216.88 | 128.67 | 3.186 | 172.74 |

Ordinary least-squares fits over the five event-count medians produced these
descriptive marginal slopes for this host and event shape:

- in-memory append: 20.72 microseconds of CPU per event;
- `deriveMessages()`: 0.109 microseconds of CPU per event;
- prefix fork: 15.30 microseconds of CPU per event;
- uncompressed JSONL write: 14.09 microseconds of CPU per event;
- warm-page-cache JSONL load: 7.93 microseconds of CPU per event;
- serialized log growth: 222.75 bytes per event;
- whole-process instructions: 392,568 per event;
- whole-process cycles: 200,860 per event;
- process maximum RSS: 7.75 KiB per event.

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
compact descriptions of this pilot rather than universal constants. This rerun
counts both user and kernel execution; generic cache counters still do not
identify a particular cache level.

This is an n=5 mechanism pilot, not a processor comparison. The complete
samples, exact perf labels, host metadata, medians, ranges, checks, and fits are
retained in `results/c2-session-count-pilot.json`. The verifier also requires
the forked event prefix to be byte-for-object identical to the parent prefix,
and `scripts/cpu/verify-cpu-results.py` checks protocol hashes, all sample
invariants, and recomputed aggregates.
