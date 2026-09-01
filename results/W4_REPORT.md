# W4 deterministic malformed tool-call recovery

W4 isolates the recovery behavior observed in W3. A local OpenAI-compatible SSE
mock returns the same scripted sequence to each runtime:

1. a tool call whose name is empty and whose argument stream is truncated JSON;
2. if the runtime requests the model again, a fixed normal completion.

No real model, external gateway, or production API key participates in this test.

| Observation | DeepSeek Harness | OpenClaw |
| --- | ---: | ---: |
| Provider requests | 2 | 1 |
| Runtime completed | yes | no |
| Tool result emitted | `unknown tool`, `isError=true` | none |
| LLM retry event | 0 | n/a |
| Final marker received | yes | no |

DSH preserved the malformed event as a tool call with an empty name. Its tool
dispatcher returned a structured unknown-tool error to the model, creating a
normal second agent step. The mock's second response then completed the turn.
This recovery is part of the agent loop rather than the request retry policy.

OpenClaw rejected the first streamed response during tool-call finalization and
terminated the turn as `incomplete_turn`; the mock observed no second request.
This matches the pinned source: malformed terminal calls are converted to a
provider error in
`packages/ai/src/providers/openai-completions-tool-calls.ts:272`, while an
`incomplete_turn` not explicitly marked `fallbackSafe` is excluded from fallback
in `src/agents/embedded-agent-runner/result-fallback-classifier.ts:207`.

One preliminary OpenClaw attempt is excluded because inherited proxy variables
produced a transport timeout after one request instead of the deterministic
malformed-call outcome. The corrected sample cleared external proxy variables;
the mock observed exactly one request and OpenClaw returned the expected
malformed-tool error. This infrastructure exclusion does not affect the recovery
comparison.

The behavioral tradeoff is concrete: DSH is permissive at the provider boundary
and lets the model repair through a tool-error observation; OpenClaw is strict at
the provider boundary and avoids executing malformed tool data, but currently
dead-ends this unmarked error instead of requesting a repair turn.
