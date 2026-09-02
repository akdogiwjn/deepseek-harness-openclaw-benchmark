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
- PMU: Linux perf 6.6; observed event labels carried `:u` because
  `perf_event_paranoid=2`.

Every sample verifies the three-event Session, exact derived and wire payloads,
request JSON round trip, one decoded SSE data event, and exact response payload.
Request JSON adds a constant 444 bytes to the logical text; the response JSON
and framed SSE add 164 and 186 bytes respectively.

## Median observations

| Context | Derive CPU (us) | Wire assembly CPU (us) | JSON encode CPU (ms) | JSON decode CPU (ms) | SSE + JSON CPU (ms) | Max RSS (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 KiB | 41.7 | 99.7 | 0.015 | 0.015 | 2.25 | 50.98 |
| 16 KiB | 41.0 | 100.3 | 0.025 | 0.020 | 2.27 | 50.99 |
| 64 KiB | 41.7 | 100.0 | 0.075 | 0.056 | 2.97 | 52.99 |
| 256 KiB | 41.7 | 100.7 | 0.339 | 0.521 | 3.73 | 54.99 |
| 1 MiB | 41.0 | 102.7 | 1.478 | 0.827 | 6.08 | 68.99 |
| 4 MiB | 42.0 | 104.0 | 4.745 | 2.421 | 17.53 | 143.28 |
| 16 MiB | 44.7 | 104.7 | 15.938 | 11.034 | 42.56 | 338.14 |

Ordinary least-squares fits over the seven context-size medians give these
descriptive slopes on this host:

- JSON request encoding: 0.947 ns of CPU per logical context byte;
- JSON request decoding: 0.650 ns of CPU per logical context byte;
- SSE framing plus response JSON decoding: 2.395 ns of CPU per logical byte;
- whole-process instructions: 100.69 per logical context byte;
- whole-process cycles: 36.72 per logical context byte;
- process maximum RSS: 18.04 bytes per logical context byte.

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
4 KiB sample by bytes produces a misleading 548 ns/byte. The fitted slope and
large-size values better describe the byte-dependent component. The response
payload is deliberately grown with request context only to provide the same
byte axis; request and response sizes are independent in real workloads. The
fixture exercises DSH SSE framing and JSON decode, but not the adapter's full
translation state machine.

This is an n=5 mechanism pilot, not a processor comparison. The complete
samples, exact perf labels, host metadata, medians, ranges, checks, normalized
metrics, and fits are retained in `results/c3-context-json-pilot.json`.
