# W2 Bug Fix comparison (n=5 pairs)

All valid trials used `deepseek-v4-flash`, high reasoning effort, the same prompt,
fresh Git workspaces, and the same external verifier. Trials were interleaved in
DSH/OpenClaw pairs.

| Metric | DeepSeek Harness | OpenClaw |
| --- | ---: | ---: |
| Hidden-verifier success | 4/5 (80%) | 5/5 (100%) |
| Wall time mean | 56.92 s | 58.01 s |
| Wall time median | 58.44 s | 54.11 s |
| Wall time range | 40.09–64.50 s | 44.12–78.15 s |
| Interaction-step median | 14 | 11 |
| Tool-call median | 15 | 15 |
| Input-token median | 23,769 | 22,685 |
| Output-token median | 4,452 | 4,193 |

The single DSH correctness failure passed all visible tests but used `strptime`
with `%Z`, accepting the visible `GMT` example while rejecting the verifier's
valid numeric-zone HTTP date. OpenClaw passed that hidden case in all five runs.

The wall-time distributions overlap substantially, and five samples per runtime
are not enough to claim a statistically reliable speed difference. Native token
counters are retained but not assumed equivalent across runtimes, particularly
for cache accounting.

Two earlier DSH trials were infrastructure-invalid and are excluded: one ended
after gateway transport retries, and one was interrupted by the outer command
transport during a streamed tool call. They remain useful evidence about failure
and recovery semantics but are not agent outcomes.

The exact changed files for all ten valid final workspaces and their normalized
pair summaries are frozen under `evidence/W2/`. The repository reproduction
script rebuilds each workspace from the committed template, reruns this external
verifier, and regenerates the n=5 aggregate; model reasoning and provider
transcripts remain deliberately omitted.
