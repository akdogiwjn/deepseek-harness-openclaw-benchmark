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
- PMU: Linux perf 6.6; all observed labels carried `:u`.

Every sample verifies the exact backend identity, operation checksum, final file
content, and workspace-location precondition.

## Median observations

| Operations | Local read wall/op (us) | Sandbox read wall/op (us) | Local write wall/op (us) | Sandbox write wall/op (us) | Local write CPU/op (us) | Sandbox write CPU/op (us) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2,141 | 2,117 | 4,643 | 5,032 | 4,313 | 4,644 |
| 10 | 594 | 599 | 1,847 | 2,095 | 1,559 | 1,810 |
| 100 | 329 | 330 | 1,398 | 1,526 | 1,033 | 1,165 |
| 1,000 | 256 | 258 | 1,211 | 1,307 | 848 | 948 |

The 1,000-operation read medians differ by 0.7%, and the fitted marginal wall
costs are 252.5 us for local versus 254.3 us for sandbox. This is consistent
with the source-level expectation that reads are inherited unchanged and
provides a useful noise/control check.

At 1,000 allowed writes, the sandbox condition added 7.9% wall time and 11.7%
Node CPU per operation. Fits over count medians give 1.202 ms/write local versus
1.297 ms/write sandbox, an incremental 94 us or 7.9%. User-space perf slopes
were 1.14 versus 1.39 million instructions/write and 1.30 versus 1.51 million
cycles/write. Those PMU deltas are consistent with the additional fresh path
resolution, writable-root enumeration, and containment checks, but C6 does not
attribute among them individually.

Unlike child-process workloads, all filesystem calls execute in the measured
Node process, so `process.cpuUsage()` includes both its user and system CPU.
Perf's `:u` events still omit kernel execution and cannot describe total syscall
cost. The write path also performs atomic replacement and contextual-diff basis
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
`results/c6-fs-sandbox-cpu-pilot.json`.
