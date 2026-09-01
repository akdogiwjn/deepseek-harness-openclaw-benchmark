# W10 native filesystem capability seam swap

W10 is a DSH white-box capability-seam study. It runs an A/B/A-prime sequence
with fresh sessions and workspaces while holding the agent loop, deterministic
provider script, `workspace-write` policy, prompt, and native `tool-fs` consumer
constant.

| Observation | A: fs-local | B: fs-sandbox | A′: fs-local |
| --- | --- | --- | --- |
| Provider requests | 4 | 4 | 4 |
| Read `inside.txt` | success | success | success |
| Edit `inside.txt` | success | success | success |
| Edit `../outside/outside.txt` | success | `FS_SANDBOX_DENIED` | success |
| Final inside state | `INSIDE_CHANGED` | `INSIDE_CHANGED` | `INSIDE_CHANGED` |
| Final outside state | `OUTSIDE_CHANGED` | `OUTSIDE_ORIGINAL` | `OUTSIDE_CHANGED` |

A and A′ were equal after removing artifact paths, and the three scripted call
names and arguments were identical. This isolates the outside-write behavior to
provider substitution rather than workspace contamination.

The native schemas intentionally differ. Under `fs-local`, `edit` advertises
`file_path`, `old_string`, `new_string`, and `replace_all`. Under the confining
provider it additionally advertises `sandbox_permissions` and `justification`;
the complete schema hashes therefore differ. Likewise the model transcript
after the third result cannot be identical because one result succeeds and the
other is a structured denial.

The defensible conclusion is that the same native consumer and loop can run over
two implementations of `ctx.fs`, while the consumer also adapts its advertised
escalation surface to provider capability. This is not a runtime performance
comparison and does not establish superiority over OpenClaw.
