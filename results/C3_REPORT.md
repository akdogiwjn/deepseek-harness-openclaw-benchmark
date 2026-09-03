# C3 fixed-shape context serialization CPU pilot

C3 separates context-byte growth from C2's event-count growth. Every sample
contains exactly one completed user turn, one message, one ASCII text block,
one fixed system prompt, and one fixed tool schema. Only the text length grows.
The fixture calls the pinned DeepSeek Harness Session and DeepSeek adapter code,
then the same Node/V8 JSON primitives used at the adapter's transport boundary.

## Design

- Logical text: 4 KiB, 16 KiB, 64 KiB, 256 KiB, 1 MiB, 4 MiB, 16 MiB.
- Repetitions: 5 per point, randomly interleaved with seed 20260902.
- Scoped-operation repetitions within each process: 3.
- Session shape: `turn/start`, `user/message`, `turn/end`.
- Request path: `deriveMessages()` -> DSH DeepSeek `serializeRequest()` ->
  `JSON.stringify()` -> `JSON.parse()`.
- Response path: DSH `parseSse()` framing plus `JSON.parse()` of one valid
  chat-completions delta, followed by `[DONE]`.
- SSE transport chunks: 16 KiB.
- Affinity: logical CPU 0.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 2 sockets, 4 NUMA nodes.
- PMU: Linux perf 6.6 with user+kernel counting (`perf_event_paranoid=-1`).

Every sample verifies the three-event Session, exact derived and wire payloads,
request JSON round trip, one decoded SSE data event, and exact response payload.
Request JSON adds a constant 444 bytes to the logical text; the response JSON
and framed SSE add 164 and 186 bytes respectively.

## Median observations

| Context | Derive CPU (us) | Wire assembly CPU (us) | JSON encode CPU (ms) | JSON decode CPU (ms) | SSE + JSON CPU (ms) | Max RSS (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 KiB | 41.7 | 99.7 | 0.015 | 0.015 | 2.103 | 50.99 |
| 16 KiB | 41.0 | 99.7 | 0.025 | 0.020 | 2.259 | 50.99 |
| 64 KiB | 41.3 | 99.7 | 0.075 | 0.056 | 2.956 | 52.98 |
| 256 KiB | 41.0 | 100.3 | 0.319 | 0.520 | 3.608 | 54.98 |
| 1 MiB | 40.3 | 100.7 | 1.444 | 0.816 | 5.901 | 68.99 |
| 4 MiB | 41.7 | 103.7 | 4.642 | 2.337 | 17.156 | 142.45 |
| 16 MiB | 41.3 | 105.0 | 15.430 | 10.706 | 41.940 | 336.71 |

Ordinary least-squares fits over the seven context-size medians give these
descriptive slopes on this host:

- JSON request encoding: 0.917 ns of CPU per logical context byte;
- JSON request decoding: 0.630 ns of CPU per logical context byte;
- SSE framing plus response JSON decoding: 2.362 ns of CPU per logical byte;
- whole-process instructions: 110.99 per logical context byte;
- whole-process cycles: 45.18 per logical context byte;
- process maximum RSS: 17.95 bytes per logical context byte.

The scoped operations are each repeated three times. Whole-process perf and
maximum RSS include all repetitions across all operations, Node/V8 startup,
Harness setup, stream construction, cleanup, and teardown. Therefore the
whole-process instruction, cycle, and RSS slopes are not the cost of one
request and cannot be assigned to an individual stage.

For this fixed one-block shape, `deriveMessages()` stayed near 41-45 us and
wire request assembly near 100-105 us across 4 KiB through 16 MiB. Inspection
of the measured path explains the result: these stages construct arrays and
objects while retaining the existing JavaScript string, rather than copying or
scanning every character. This is a useful negative result, not evidence that
all context preparation is constant-time. Increasing message/block/event
counts, flattening multiple text blocks, images, tool results, compaction, or
token counting can force different work.

SSE has a substantial fixed per-stream cost at the small sizes, so dividing the
4 KiB sample by bytes produces a misleading per-byte value. The fitted slope and
large-size values better describe the byte-dependent component. The response
payload is deliberately grown with request context only to provide the same
byte axis; request and response sizes are independent in real workloads. The
fixture exercises DSH SSE framing and JSON decode, but not the adapter's full
translation state machine.

This is an n=5 mechanism pilot, not a processor comparison. The complete
samples, exact perf labels, host metadata, medians, ranges, checks, normalized
metrics, and fits are retained in `results/c3-context-json-pilot.json`.
`scripts/cpu/verify-cpu-results.py` independently checks the committed protocol
hashes, sample invariants, aggregates, and fitted slopes.
