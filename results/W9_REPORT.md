# W9 DSH session state semantics

W9 is a DSH white-box mechanism study, not a DSH-versus-OpenClaw ranking. Three
deterministic cases test whether the persisted Session event log supports cold
recovery, prefix forking, and model-stream replay without a live provider credential.

## W9-A crash and resume

The provider first issued a completed bash call, then a second call that wrote a
started marker and blocked. An external supervisor waited until the second
`tool/call` was present in the uncompressed JSONL and its `tool/result` was
absent, then killed the complete sdk-minimal process group.

The crash prefix contained 25 events. `ctx.agents.resume()` preserved that
prefix byte-for-byte and cold repair appended a synthetic result with
`TOOL_OUTCOME_UNKNOWN`, followed by `step/end`, `turn/end { interrupted }`, and
`session/end-seed`. A new turn then completed with one deterministic model call.
Sequence numbers remained contiguous, and both external markers appeared
exactly once. The resume runtime also mounted an executable `bash` probe with
the same public command shape; its invocation count remained zero, directly
showing that the old side-effecting call was not automatically dispatched.

The resumed model request was checked structurally rather than by marker text
alone. It contained the original prompt, completed call/result pair, dangling
call, matching synthetic error result, and final follow-up prompt in order.

The Python SDK carrier was used to create the crash but not to resume it. Its
stdio server creates a session for a new process-level `session/prompt`; the
official programmatic `ctx.agents.resume()` API is the cold-resume entry point
tested here. This carrier boundary is recorded rather than hidden.

## W9-B fork

The live parent completed two turns and forked through inclusive boundary seq 5.
The six-event parent prefix equaled the child's seed exactly. The child recorded
`parentSession`, `seedLength: 6`, the same cwd, and a following
`session/end-seed`. Parent-only and child-only third turns remained isolated.

An explicit boundary inside an open turn rejected with `OPEN_TURN`; the closed
`turn/end` boundary succeeded.

## W9-C credential-free LLM replay

A separate normally completed session recorded two model calls: one bash call
and one final text response. The recording provider was then stopped. The
`llm-replay` adapter booted a fresh real agent loop and reproduced both calls
without increasing the provider request count beyond two. The carrier still
received a non-production placeholder environment value because its startup
validation requires the variable to exist; the replay adapter replaced the live
provider and the endpoint was deliberately unreachable.

The normalized turn, step, assistant message, tool call, and tool result
projections matched. The complete normalized `assistant/chunk` projections also
matched, including block boundaries, deltas, usage, finish reasons, and tool-call
IDs. Recording and replay used fresh workspaces, each producing its side effect
exactly once. This demonstrates model-stream replay from the Session log; it
does not claim rollback or automatic replay of external state.
