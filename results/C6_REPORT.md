# C6 DSH filesystem sandbox CPU pilot

C6 directly measures the DSH filesystem capability seam established by W10.
The pinned `SandboxedFileSystem` inherits every `LocalFileSystem` operation and
adds a trusted canonicalize-and-contain policy fence only before mutations. It
is not a kernel sandbox. Four conditions isolate that design:

- local read and sandbox read: identical inherited-path negative controls;
- local write and sandbox write: identical allowed atomic writes, with the
  sandbox condition re-resolving and checking workspace containment.

## Design

- Operations: 1, 10, 100, 1,000.
- Repetitions: 5 per condition and count, randomly interleaved with seed 20260902.
- Total samples: 80.
- Payload: one repeatedly accessed 256-byte file.
- Read operation: resolve, stat, and whole-text read.
- Write operation: resolve and unconditional DSH atomic whole-file replacement.
- Policy: `workspace-write`; workspace deliberately outside platform temp roots.
- Affinity: logical CPU 0.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 2 sockets, 4 NUMA nodes.
- PMU: Linux perf 6.6 with user+kernel counting (`perf_event_paranoid=-1`).

Every sample verifies the exact backend identity, operation checksum, final file
content, and workspace-location precondition.

## Median observations

| Operations | Local read wall/op (us) | Sandbox read wall/op (us) | Local write wall/op (us) | Sandbox write wall/op (us) | Local write CPU/op (us) | Sandbox write CPU/op (us) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,287 | 2,138 | 4,477 | 4,945 | 4,119 | 4,566 |
| 10 | 579 | 614 | 1,912 | 2,148 | 1,616 | 1,847 |
| 100 | 334 | 328 | 1,383 | 1,521 | 1,033 | 1,182 |
| 1,000 | 255 | 266 | 1,179 | 1,255 | 850 | 937 |

The 1,000-operation read medians differ by 4.3%, and the fitted marginal wall
costs are 250.7 us for local versus 262.2 us for sandbox (4.6%). The source says
the read implementation is inherited unchanged, so this difference must not be
reported as sandbox read-policy cost. Instead, the negative control exposes the
size of condition-order, process, V8, or filesystem noise still present at n=5.

At 1,000 allowed writes, the sandbox condition added 6.4% wall time and 10.2%
Node CPU per operation. Fits over count medians give 1.170 ms/write local versus
1.243 ms/write sandbox, an incremental 73 us or 6.3%. Total-PMU slopes were
2.11 versus 2.45 million instructions/write and 2.51 versus 2.76 million
cycles/write. These deltas are compatible with the additional fresh path
resolution, writable-root enumeration, and containment checks, but the read
negative-control spread and small sample size prevent clean causal attribution.

Unlike child-process workloads, all filesystem calls execute in the measured
Node process, so `process.cpuUsage()` includes both its user and system CPU.
Perf includes kernel execution in this rerun. The write path also performs
atomic replacement and contextual-diff basis
work in both conditions; the sandbox percentage is specific to this small-file
mix and will shrink or grow with storage latency, payload size, directory depth,
symlinks, and cache state.

The workload repeatedly touches one hot file and is not a cold-storage or
filesystem-throughput benchmark. It measures only allowed workspace operations;
W10 separately verifies denial and outside-path behavior. Process sandboxing,
read-only denials, symlink-heavy containment, and concurrent mutation remain
separate experiments.

This is an n=5 mechanism pilot, not a processor comparison. Complete samples,
checks, host data, exact perf labels, medians, ranges, ratios, and fits are in
`results/c6-fs-sandbox-cpu-pilot.json`. The protocol hashes, sample checks,
aggregates, comparisons, and fits are independently checked by
`scripts/cpu/verify-cpu-results.py`.
