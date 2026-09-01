# W7 deterministic 20-call tool chain

W7 uses a local OpenAI-compatible SSE provider to issue twenty sequential native
shell calls (`bash` for DSH, `exec` for OpenClaw), followed by a fixed final
completion. Each tool prints one unique marker. Before every response, the mock
checks that all markers produced so far remain in tool-result messages and that
every assistant tool call has exactly one paired tool result. The final provider
request must contain all twenty markers in twenty paired tool-result messages.

No real model, external gateway, production credential, compaction, or context
pruning participates. Provider token usage is deliberately zeroed because a mock
cannot supply trustworthy tokenizer metrics; the experiment records exact UTF-8
request bytes instead.

## Results

| Observation | DeepSeek Harness | OpenClaw |
| --- | ---: | ---: |
| Runtime completed | yes | yes |
| Provider requests | 21 | 21 |
| Tool calls | 20 | 20 |
| Final request has all 20 tool-result markers | yes | yes |
| Final assistant calls/results paired | 20/20 | 20/20 |
| Process wall time | 6.164 s | 6.543 s |
| Start to first provider request | 0.448 s | 5.374 s |
| First to final provider request | 4.529 s | 0.934 s |
| Median inter-request interval | 0.200 s | 0.029 s |
| Final request to process exit | 1.187 s | 0.235 s |
| First request body | 6,351 B | 17,503 B |
| Final request body | 11,271 B | 22,923 B |
| Request-body growth | 4,920 B | 5,420 B |
| Median growth per tool step | 246 B | 271 B |
| Sum of 21 request bodies | 185,031 B | 424,473 B |
| Tool schema per request | 4,016 B | 3,266 B |

Both runtimes completed the exact chain. All twenty unique tool-result markers
remained represented in separate, paired tool-result messages in the final
provider context. The final message count grew from 2 to 42 in both cases: each
step added one assistant tool call and one tool result, with no observed pruning
or compaction.

## Interpretation

Similar total wall time hides very different phase shapes. OpenClaw spent about
5.37 seconds reaching its first local provider request, then traversed the twenty
tool/agent-loop transitions in about 0.93 seconds. DSH reached the provider in
about 0.45 seconds, but the same transition span took about 4.53 seconds and SDK
turn teardown after the final response took another 1.19 seconds.

The request-volume result points in the opposite direction. OpenClaw transmitted
424,473 bytes across the chain, 2.29 times DSH's 185,031 bytes. Its initial
serialized `messages` array was 14,036 bytes versus 194 bytes for DSH; this is a
runtime prompt/context-shaping difference, not a tool-schema effect, because the
DSH tool schema was actually 750 bytes larger per request. OpenClaw also added
about 25 more request bytes per tool step in this fixture.

This is a mechanism trace, not a general speed ranking. It measures native direct
tool calling against a zero-latency local provider on one machine. With a real
remote model, repeated prompt-token processing and network/model latency can make
request volume more important; with a cold CLI invocation, startup dominates
OpenClaw here. Payload bytes are not tokens, and the tool surfaces and prompt
formats remain intentionally non-equivalent.
