# W10 capability seam swap

The deterministic provider reads and edits `inside.txt`, then attempts to edit
`../outside/outside.txt`. Only the mounted `ctx.fs` provider changes.
