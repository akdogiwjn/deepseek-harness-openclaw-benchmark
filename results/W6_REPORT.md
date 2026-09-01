# W6 deterministic tool-failure handling

W6 sends each runtime a byte-deterministic two-response sequence through a local
OpenAI-compatible SSE provider. The first response calls the runtime's native
shell tool (`bash` for DSH, `exec` for OpenClaw); the second is a fixed completion
returned only if the runtime requests another model step. No real model, gateway,
production credential, or network latency participates.

## Results

| Scenario and observation | DeepSeek Harness | OpenClaw |
| --- | ---: | ---: |
| Nonzero: provider requests | 2 | 2 |
| Nonzero: runtime completed | yes | yes |
| Nonzero: structured tool failure | no (`isError=false`) | no (`failures=0`) |
| Nonzero: process wall time | 2.491 s | 6.021 s |
| Invalid args: provider requests | 2 | 2 |
| Invalid args: runtime completed | yes | yes |
| Invalid args: structured tool failure | yes (`INVALID_ARGS`) | yes (`failures=1`) |
| Invalid args: process wall time | 0.561 s | 5.704 s |

The corrected nonzero stimulus runs this child process without terminating the
runtime's outer shell:

```sh
sh -c "printf 'W6_STDOUT\\n'; printf 'W6_STDERR\\n' >&2; exit 17"
```

Both runtimes preserved stdout, stderr, and exit code in the next provider
request. DSH rendered `[exit code: 17]`; OpenClaw rendered
`(Command exited with code 17)`. Both treated the completed nonzero child as a
normal tool result rather than a structured tool error. OpenClaw's pinned source
makes this explicit: completed exits other than shell-launch failures 126/127
remain `status: "completed"` in `src/agents/bash-tools.exec-runtime.ts:558`, and
the failure classifier test at `src/agents/tool-result-error.test.ts:237` asserts
that a completed nonzero exit is not a failure.

When the mock omitted the required `command`, both runtimes returned a structured
validation failure to the model and continued to the fixed second completion.
DSH emitted `ToolArgsError`, code `INVALID_ARGS`, and `isError=true`; OpenClaw
reported `Validation failed for tool "exec"` and counted one tool failure. DSH's
pinned schema raises this error in `packages/core/tools/src/schema.ts:461`.

## Interpretation

Together with W4, this locates the behavioral boundary more precisely:

- a syntactically valid tool call that fails argument validation is recoverable
  through a normal second agent step in both runtimes;
- an executed command returning a conventional nonzero code is observable but is
  not structurally classified as a tool failure by either native shell surface;
- the W4 divergence occurs earlier, while finalizing a malformed provider tool
  event, before OpenClaw has a valid tool call to execute or report back.

The wall-time values are single deterministic mechanism samples, not performance
claims. They include different runtime startup costs and are useful only as trace
metadata.

One preliminary nonzero sample per runtime is excluded. Its stimulus used the
shell builtin `exit 17` directly, which terminated DSH's persistent shell but only
the one-shot shell used by OpenClaw. Replacing it with a child `sh -c` removed
that tool-lifecycle asymmetry.
