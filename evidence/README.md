# Frozen benchmark evidence

For W1-W3, this directory retains each normalized pair summary plus the exact
changed/untracked files needed to reconstruct both final workspaces from the
committed templates. The reproduction script initializes a fresh Git baseline,
applies each overlay, reruns the external verifier, checks the changed-file/diff
metadata, and rebuilds the W2/W3 n=5 aggregates.

For deterministic W4-W10, it contains the minimal redacted input closure used to
rebuild the committed summaries. It excludes API headers, credentials, server
readiness logs, and full DSH sessions. Selected DSH tool-call/result and Code Mode
dispatch events are retained only where a report depends on structured trace
semantics.

Absolute benchmark paths, host names, and ephemeral OpenClaw config directories
are replaced with stable placeholders. W6 provider requests retain only assistant
tool calls and tool results instead of the large runtime system prompt.

Verify file integrity and reproduce every summary with:

```bash
scripts/reproduce-evidence.sh
```

`manifest.json` documents the revisions, redactions, and deliberate omissions.
`MANIFEST.sha256` binds every frozen file, including the manifest itself.

W9 retains the sanitized crash prefix, repaired Session, resume observation,
fork result, and completed recording/replay Sessions. W10 retains sanitized
Session logs, compact request metadata, and final workspace state for all three
A/B/A-prime conditions.
