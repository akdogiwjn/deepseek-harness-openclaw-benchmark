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
Runners probe perf capability in two levels: they first ask for
`cycles:u`/`cycles:k` and `instructions:u`/`instructions:k`, falling back to
`cycles:u`/`instructions:u` (user-only) only when the `:k` request fails, and
disabling perf if neither works. The probe runs the exact events the benchmark
will use, so a host whose `perf_event_paranoid` or `CAP_PERFMON` restriction
rejects `:k` degrades the mode instead of failing every sample. The parsed
`cycles`/`instructions` totals are the sum of the sampled `:u` and `:k`
components, and each runner records `*_kernel_ratio` when the kernel component
is available. The result also preserves the exact event labels returned by perf;
a `:u` suffix on a plain counter still means kernel execution was excluded and
zero-valued scheduling counters under it must not be read as an absence of
scheduling. The fixture's prompt-window `resourceUsage()` deltas remain separate.

### C1-warm steady-state variant

`run-c1.py` accepts `--warm-turns` and `--warmup-turns`. With `--warm-turns > 0`
the fixture reuses one composed Harness and creates a fresh Session per turn, so
every turn has fixed context. The first `--warmup-turns` turns are discarded and
the runner reports the per-step median over the remaining warm turns. Whole-process
perf still includes process startup, so the cold/warm contrast is visible only in
the internal prompt-window timing; compare by running the same `--steps` sweep
with and without `--warm-turns`.

```bash
scripts/cpu/run-c1.py \
  --steps 0,1,4,16,64,256 \
  --repeats 5 \
  --warm-turns 10 \
  --warmup-turns 2 \
  --cpu 0 \
  --output results/c1-warm-agent-loop-pilot.json
```

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

## C4 shell lifecycle scaling

The pinned DSH source does not implement a persistent local shell. Its
`LocalBashExecutor.run()` launches `bash -c` through the subprocess capability
for every command, and the source retains an explicit stateful-shell TODO.
Accordingly C4 compares three mechanisms:

- the real DSH managed one-shot shell capability;
- a benchmark-control raw one-shot Node spawn;
- a benchmark-control persistent bash with line-framed acknowledgements.

The controls are not OpenClaw implementations. All conditions execute the same
sequential no-op builtin plus a unique marker, and every sample verifies the
complete marker sequence, stderr, and termination status.

Run a functional smoke test:

```bash
scripts/cpu/run-c4.py \
  --counts 1,10 \
  --repeats 1 \
  --cpu 0 \
  --perf off \
  --output /tmp/c4-shell-smoke.json
```

Run the initial scaling design:

```bash
scripts/cpu/run-c4.py \
  --counts 1,10,100,1000 \
  --repeats 5 \
  --cpu 0 \
  --output results/c4-shell-lifecycle-pilot.json
```

Persistent shell startup/readiness is outside its scoped command-loop timing,
but whole-process perf includes it. Node `process.cpuUsage()` measures only the
controller, while perf's default inheritance covers descendants. On a host that
only permits `:u` events, perf omits exactly the kernel work that process-launch
research needs; treat that run as a user-space pilot and rerun with user+kernel
PMU access for total CPU attribution. See `results/C4_REPORT.md`.

## C5 DSH native-vs-PTC scaling

C5 measures the CPU tradeoff behind W8's executor collapse using one real DSH
Agent Loop and a deterministic in-process adapter. Native mode emits one model-
visible `noop` call per operation. PTC emits one `run_code` call; the shipped
worker-thread runtime then invokes the same no-op tool N times sequentially.
Native therefore makes `N + 1` provider requests while PTC always makes two.

Run a smoke test:

```bash
scripts/cpu/run-c5.py \
  --counts 0,4 \
  --repeats 1 \
  --cpu 0 \
  --perf off \
  --output /tmp/c5-code-mode-smoke.json
```

Run the initial scaling design:

```bash
scripts/cpu/run-c5.py \
  --counts 0,1,4,16,64,256,1024 \
  --repeats 5 \
  --payload-bytes 16 \
  --cpu 0 \
  --output results/c5-code-mode-cpu-pilot.json
```

The adapter removes real network/model latency, so the experiment measures
local runtime work rather than the end-to-end value of fewer remote calls. PTC
uses a fresh worker for each program. The no-op tool excludes shell, filesystem,
payload, and useful program-compute costs. See `results/C5_REPORT.md`.

## C6 local-vs-sandbox filesystem scaling

C6 reuses W10's DSH filesystem capability swap without an Agent Loop. The
sandbox backend inherits local reads verbatim and adds a canonicalize-and-
contain policy fence before writes. Four conditions run local/sandbox backends
over read and write workloads; reads are the negative control.

Run a smoke test:

```bash
scripts/cpu/run-c6.py \
  --counts 1,10 \
  --repeats 1 \
  --payload-bytes 256 \
  --cpu 0 \
  --perf off \
  --output /tmp/c6-fs-smoke.json
```

Run the initial scaling design:

```bash
scripts/cpu/run-c6.py \
  --counts 1,10,100,1000 \
  --repeats 5 \
  --payload-bytes 256 \
  --cpu 0 \
  --output results/c6-fs-sandbox-cpu-pilot.json
```

Each read resolves, stats, and reads the same hot file. Each write resolves and
performs DSH's atomic whole-file replacement. The workspace lies outside
platform temp roots, so sandbox writes exercise the configured workspace-root
containment path. This is trusted capability enforcement, not a kernel boundary;
W10 remains the denial-semantics case. See `results/C6_REPORT.md`.

## C7 multi-process Agent scale-out

C7 runs one independent Node/DSH process per Agent. Every Agent reuses the C1
fixture with 64 deterministic tool steps. The controller starts a batch
concurrently, validates all child results, and reports throughput and summed
per-child maximum RSS. Perf's default inheritance covers the controller and all
Agent descendants.

The runner parses `lscpu -p` and chooses the first logical CPU for each distinct
physical `(socket, core)` pair. Each larger condition uses a nested prefix of
that list, avoiding accidental SMT-sibling placement.

Run a smoke test:

```bash
scripts/cpu/run-c7.py \
  --agents 1,2 \
  --repeats 1 \
  --tool-steps 4 \
  --payload-bytes 16 \
  --perf off \
  --output /tmp/c7-scaleout-smoke.json
```

Run the initial scale-out design:

```bash
scripts/cpu/run-c7.py \
  --agents 1,2,4,8,16,32 \
  --repeats 5 \
  --tool-steps 64 \
  --payload-bytes 64 \
  --output results/c7-agent-scaleout-pilot.json
```

The batch scope includes process startup, Harness composition, execution, and
exit. This is a multi-process topology; multiple Agents in one shared runtime
are a separate condition. Selected-core NUMA placement must be inspected before
cross-host interpretation. See `results/C7_REPORT.md`.

### C7-B hard-pin placement

C7 keeps the controller process unbound in both modes and varies only the child
cpuset. The default (`shared`) launches every Agent under `taskset -c <pool>`
for the full selected physical-core pool, so the Linux scheduler may migrate an
Agent between pool cores. `--hard-pin` launches Agent `i` under
`taskset -c <core_i>` instead. The controller placement is identical across the
two conditions, so the sole variable is whether children share the pool or are
pinned one-per-core.

```bash
scripts/cpu/run-c7.py \
  --agents 1,2,4,8,16,32 \
  --repeats 5 \
  --tool-steps 64 \
  --payload-bytes 64 \
  --hard-pin \
  --output results/c7-agent-scaleout-hardpin-pilot.json
```
