# Frozen deterministic evidence

This directory contains the minimal redacted input closure used to rebuild the
committed W4-W8 summaries. It excludes API headers, credentials, server readiness
logs, and full DSH sessions. Selected DSH tool-call/result events are retained
only where a report depends on structured trace semantics.

Absolute benchmark paths, host names, and ephemeral OpenClaw config directories
are replaced with stable placeholders. W6 provider requests retain only assistant
tool calls and tool results instead of the large runtime system prompt.

Verify file integrity and reproduce every summary with:

```bash
scripts/reproduce-evidence.sh
```

`manifest.json` documents the revisions and redactions. `MANIFEST.sha256` binds
every frozen file, including the manifest itself.
