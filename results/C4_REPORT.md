# C4 shell lifecycle CPU pilot

C4 measures shell lifecycle cost without a model or Agent Loop. Source audit
first established that the pinned DSH `bash-local` provider is not persistent:
each public command runs as a separately managed `bash -c`. The pilot therefore
uses three mechanism conditions rather than presenting a false cross-runtime
comparison:

- `dsh-managed`: real DSH `LocalBashExecutor` over `LocalSubprocessRuntime`;
- `raw-oneshot`: direct Node `child_process.spawn()` for every `bash -c`;
- `persistent`: one direct Node-spawned bash receiving line-framed commands.

The latter two are benchmark controls, not OpenClaw implementations.

## Design

- Operations: 1, 10, 100, 1,000.
- Repetitions: 5 per condition and count, randomly interleaved with seed 20260902.
- Total samples: 60.
- Command: a bash no-op builtin followed by one unique fixed-width marker.
- Execution: strictly sequential; each marker is received before the next command.
- Persistent setup: shell startup/readiness is outside scoped loop timing but
  remains inside whole-process perf.
- Affinity: logical CPU 0 for the controller and inherited children.
- Runtime: pinned Node 24.15.0 and DSH revision.
- Host: ARM64 HiSilicon, 256 logical CPUs, 2 sockets, 4 NUMA nodes.
- PMU: Linux perf 6.6 with user+kernel counting and descendant inheritance
  (`perf_event_paranoid=-1`).

Every sample verifies the exact output count, marker sequence, empty stderr,
and successful shell termination.

## Median observations at 1,000 operations

| Condition | Wall/op (ms) | Controller CPU/op (ms) | Cycles/op (M) | Instructions/op (M) | Perf task-clock/op (ms) | Page faults/op |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DSH managed one-shot | 3.913 | 1.428 | 11.077 | 10.119 | 3.824 | 320.1 |
| Raw one-shot | 2.760 | 1.032 | 7.992 | 7.963 | 2.760 | 288.2 |
| Persistent bash | 0.064 | 0.041 | 0.393 | 0.497 | 0.136 | 6.6 |

The controller CPU column comes from Node `process.cpuUsage()` and excludes
child CPU. Perf uses its default descendant inheritance and therefore covers
the controller and spawned shell descendants, including kernel execution.

Ordinary least-squares fits over the operation-count medians produced these
descriptive marginal slopes:

| Condition | Wall/op (ms) | Cycles/op (M) | Instructions/op (M) | Perf task-clock/op (ms) |
| --- | ---: | ---: | ---: | ---: |
| DSH managed one-shot | 3.905 | 10.849 | 9.803 | 3.745 |
| Raw one-shot | 2.754 | 7.794 | 7.686 | 2.692 |
| Persistent bash | 0.063 | 0.185 | 0.218 | 0.064 |

For this no-op command, the DSH managed path used about 1.42x the marginal wall
time and 1.28x the total instructions of raw one-shot spawn. That delta
includes DSH subprocess process-group ownership, bounded collection, deadlines,
environment handling, result projection, and related lifecycle machinery; C4
does not isolate those components individually.

Raw one-shot used about 44.0x the marginal wall time and 35.3x the total
instructions of the persistent control. This demonstrates the potential scale
of launch amortization for tiny builtins. It does not predict the same ratio for
long commands, external executables, large output, filesystem work, concurrent
tools, or failure/timeout paths. Persistent startup is also amortized rather
than included in scoped loop time.

This rerun includes user and kernel execution, which materially changes the
instruction/cycle comparison for a process-lifecycle workload. It still does
not decompose syscall, scheduler, pipe, V8, and Harness contributions; those
would require tracepoints or a dedicated attribution experiment.

This is an n=5 mechanism pilot, not an OpenClaw comparison or processor study.
The complete samples, exact event labels, checks, medians, ranges, normalized
metrics, and fits are retained in `results/c4-shell-lifecycle-pilot.json`.
`scripts/cpu/verify-cpu-results.py` checks the protocol hashes and independently
recomputes the committed aggregates and fits.
