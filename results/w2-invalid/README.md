# W2 excluded infrastructure trials

- `w2-pilot-001/dsh.raw.json`: the gateway was unreachable from the restricted
  execution context. DSH retried five times and ended with `finish_reason=error`.
  The old wrapper returned process exit code 0; the wrapper now maps this state
  to a non-zero exit code.
- `dsh-w2-002`: the outer command transport ended while DSH was streaming a tool
  call, leaving an incomplete JSONL trace and no completed raw process record.

Neither trial received a completed agent outcome, so neither is included in W2
success rates or timing aggregates. The artifacts are retained for recovery and
failure-semantics analysis.
