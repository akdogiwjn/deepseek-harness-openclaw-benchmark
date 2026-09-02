# CPU-oriented benchmark

The CPU suite starts after W1-W10 established the runtime and mechanism cases.
It does not add another agent capability workload. Its purpose is to attribute
Host CPU work to the Agent Loop, Session/context processing, tool execution,
code runtimes, and isolation layers while deterministic adapters remove live
model and network variance.

## C1 in-process Agent Loop scaling

C1 runs one real DSH Agent Loop over an in-process deterministic adapter. For
each requested tool step, the adapter emits one native `noop` call with a fixed
payload; the tool returns a fixed-size result. One final model request completes
the turn. Therefore `N` means `N` tool calls and `N + 1` Agent steps.

The fixture checks the exact provider-request, tool-call, tool-result, step, and
turn counts before emitting a sample. It intentionally retains the growing
in-memory append-only Session, so this first condition measures the combined
loop plus growing-context path rather than claiming a fixed-context loop cost.

Run a short smoke test:

```bash
scripts/cpu/run-c1.py \
  --steps 0,1,4,16 \
  --repeats 2 \
  --cpu 0 \
  --output results/c1-agent-loop-smoke.json
```

Run the initial scaling design:

```bash
scripts/cpu/run-c1.py \
  --steps 0,1,4,16,64,256 \
  --repeats 5 \
  --cpu 0 \
  --output results/c1-agent-loop-pilot.json
```

`N = 0` is the completion-only baseline: it opens one turn and performs one
final model step without a tool call. It anchors the fixed loop cost instead of
requiring the regression to infer that intercept only from positive step counts.

`--perf auto` is the default. When the host permits user-space PMU access, the
runner records task clock, cycles, instructions, branches, branch misses,
generic cache references/misses, context switches, migrations, and page faults.
Use `--perf off` for functional runs on restricted hosts. Use `--cpu -1` only
when affinity cannot be controlled.

Two measurement scopes are deliberately kept separate:

- internal prompt-to-idle timing excludes Context/agent setup and teardown;
- `perf stat` covers the whole Node process, including V8 startup, Harness
  composition, the measured turn, and disposal.

Linear fits over per-step-count medians report an intercept and marginal slope.
The slope is more useful than dividing a single run by its step count because
the process-level intercept contains substantial fixed startup work.

Generic perf events are a portable first layer, not proof that PMU semantics are
identical across processors or ISAs. Record the CPU, kernel, Node, perf, affinity,
and event mapping before making hardware comparisons. Later CPU cases should add
PMU-specific LLC, DTLB, stall, and memory-bandwidth events per target platform.
The result preserves the exact event labels returned by perf. A `:u` suffix
means kernel execution was excluded; under such permissions, zero-valued
context-switch/migration software events are not evidence that scheduling did
not occur. The fixture's prompt-window `resourceUsage()` deltas remain separate.

## C2 Session/Event Log event-count scaling

C2 removes the Agent Loop and measures DSH Session primitives directly. Each
turn contributes a valid three-event sequence: `turn/start`, one fixed-size
`user/message`, and `turn/end`. The event-count condition separately times:

- append into an in-memory Session;
- `deriveMessages()` over that Session;
- a full-prefix Session fork;
- writing the events to uncompressed JSONL with chunk packing disabled;
- loading the JSONL through a fresh persistence backend.

Message construction is outside append timing. The load backend is fresh, but
the host page cache remains warm. Whole-process perf still includes every
operation plus Node/V8 startup, setup, cleanup, and teardown.

Run a short functional smoke test without perf:

```bash
scripts/cpu/run-c2.py \
  --turns 1,10,100 \
  --repeats 1 \
  --cpu 0 \
  --perf off \
  --output /tmp/c2-session-smoke.json
```

Run the initial event-count scaling design:

```bash
scripts/cpu/run-c2.py \
  --turns 1,10,100,1000,5000 \
  --repeats 5 \
  --payload-bytes 256 \
  --cpu 0 \
  --output results/c2-session-count-pilot.json
```

The fixture verifies exact event/message counts, every derived payload, fork
prefix and seed-boundary semantics, and the complete reloaded event sequence.
This first C2 condition fixes payload size and uses completed user-only turns.
It does not represent tool-heavy histories, streaming chunks, compaction
events, cold storage, or payload-size scaling. See `results/C2_REPORT.md` for
the pilot observations and their interpretation limits.

## C3 fixed-shape context and JSON scaling

C3 holds event count, message count, block count, system prompt, and tool schema
constant while growing one ASCII user text block from 4 KiB to 16 MiB. It
separately times:

- Session `deriveMessages()`;
- the pinned DSH DeepSeek `serializeRequest()` wire assembly;
- request `JSON.stringify()` and `JSON.parse()`;
- the pinned DSH `parseSse()` plus JSON decoding of one response data event.

Each scoped operation repeats three times in the same process. The fixture
validates the complete request and response payload round trips. SSE data is
pre-encoded outside timing and supplied in 16 KiB transport chunks; stream
construction, framing, decoding, and response `JSON.parse()` remain inside the
SSE measurement.

Run a short functional smoke test:

```bash
scripts/cpu/run-c3.py \
  --sizes 4K,64K,1M \
  --repeats 1 \
  --iterations 2 \
  --cpu 0 \
  --perf off \
  --output /tmp/c3-context-smoke.json
```

Run the initial scaling design:

```bash
scripts/cpu/run-c3.py \
  --sizes 4K,16K,64K,256K,1M,4M,16M \
  --repeats 5 \
  --iterations 3 \
  --stream-chunk-bytes 16384 \
  --cpu 0 \
  --output results/c3-context-json-pilot.json
```

Growing response content with request context supplies a common byte axis for
the pilot; it does not claim those sizes are coupled in production. The SSE
condition includes framing and JSON decode, not the complete adapter translation
state machine. See `results/C3_REPORT.md` for results and interpretation limits.
