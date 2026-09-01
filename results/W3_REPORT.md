# W3 repository feature comparison (n=5 pairs)

W3 required understanding a multi-module Python package, adding weighted quota
consumption across the service/store boundary, preserving atomic rejection and
legacy behavior, and adding focused tests. All trials used the same model, prompt,
reasoning effort, fresh Git workspace, and external hidden verifier.

| Metric | DeepSeek Harness | OpenClaw |
| --- | ---: | ---: |
| Runtime completed | 5/5 | 2/5 |
| Hidden-verifier success | 5/5 (100%) | 2/5 (40%) |
| `incomplete_turn` termination | 0/5 | 3/5 |
| All-attempt wall median | 87.95 s | 61.55 s |
| Successful-only wall median | 87.95 s | 73.78 s |
| All-attempt tool-call median | 20 | 15 |

The all-attempt OpenClaw time is censored by three early failures and must not be
read as a speed advantage. Its two successful runs took 68.06 and 79.50 seconds.
DSH completed every run in 63.12–119.86 seconds.

All three OpenClaw failures followed the same trajectory: the runtime had already
read and modified `service.py` and `store.py`, then terminated with
`Provider returned an incomplete or malformed tool call` before adding the
required tests or producing a final response. The external verifier consequently
failed the explicit added-test requirement.

The pinned OpenClaw source explains this behavior. The OpenAI-compatible
tool-call finalizer rejects a call when its name or streamed argument buffer is
empty, or when final argument parsing throws
(`packages/ai/src/providers/openai-completions-tool-calls.ts:272`). The embedded
fallback classifier declines fallback for an `incomplete_turn` unless the error
is explicitly marked `fallbackSafe`
(`src/agents/embedded-agent-runner/result-fallback-classifier.ts:207`). This is a
source-backed explanation of the observed termination policy; the raw malformed
provider fragment itself is not persisted by the `agent exec` result, so its
exact malformed field cannot be identified from these artifacts.

The result is directly relevant to harness analysis: on a longer tool trajectory,
the two runtimes differed less in the final code strategy than in whether a
malformed model tool event was recoverable. More models and task families are
needed before generalizing beyond this provider/model/runtime combination.
