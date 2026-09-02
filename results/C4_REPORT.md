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
- PMU: Linux perf 6.6; all observed labels carried `:u` because
  `perf_event_paranoid=2`.

Every sample verifies the exact output count, marker sequence, empty stderr,
and successful shell termination.

## Median observations at 1,000 operations

| Condition | Wall/op (ms) | Controller CPU/op (ms) | User cycles/op (M) | User instructions/op (M) | Perf task-clock/op (ms) | Page faults/op |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DSH managed one-shot | 3.842 | 1.407 | 2.712 | 3.640 | 3.765 | 313.2 |
| Raw one-shot | 2.690 | 1.012 | 1.877 | 2.627 | 2.692 | 278.6 |
| Persistent bash | 0.064 | 0.042 | 0.269 | 0.361 | 0.134 | 6.5 |

The controller CPU column comes from Node `process.cpuUsage()` and excludes
child CPU. Perf uses its default descendant inheritance and therefore covers
the controller and spawned shell descendants, subject to the `:u` restriction.

Ordinary least-squares fits over the operation-count medians produced these
descriptive marginal slopes:

| Condition | Wall/op (ms) | User cycles/op (M) | User instructions/op (M) | Perf task-clock/op (ms) |
| --- | ---: | ---: | ---: | ---: |
| DSH managed one-shot | 3.832 | 2.515 | 3.355 | 3.684 |
| Raw one-shot | 2.682 | 1.712 | 2.384 | 2.621 |
| Persistent bash | 0.063 | 0.114 | 0.127 | 0.062 |

For this no-op command, the DSH managed path used about 1.43x the marginal wall
time and 1.41x the user-space instructions of raw one-shot spawn. That delta
includes DSH subprocess process-group ownership, bounded collection, deadlines,
environment handling, result projection, and related lifecycle machinery; C4
does not isolate those components individually.

Raw one-shot used about 42.7x the marginal wall time and 18.8x the user-space
instructions of the persistent control. This demonstrates the potential scale
of launch amortization for tiny builtins. It does not predict the same ratio for
long commands, external executables, large output, filesystem work, concurrent
tools, or failure/timeout paths. Persistent startup is also amortized rather
than included in scoped loop time.

The PMU restriction is especially important here. `cycles:u`,
`instructions:u`, and `task-clock:u` exclude kernel execution, although process
creation, pipes, scheduling, and teardown are central to this workload.
Zero-valued context-switch counters are non-interpretable. Wall time remains an
end-to-end observation, but a privileged rerun with user+kernel counters is
required before making claims about total CPU or syscall cost.

This is an n=5 mechanism pilot, not an OpenClaw comparison or processor study.
The complete samples, exact event labels, checks, medians, ranges, normalized
metrics, and fits are retained in `results/c4-shell-lifecycle-pilot.json`.
