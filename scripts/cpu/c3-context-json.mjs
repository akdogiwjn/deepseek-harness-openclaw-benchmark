#!/usr/bin/env node
/** C3 fixed-shape context serialization and SSE parsing CPU fixture. */

import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
import { createUserMessage } from '../../sources/deepseek-harness/packages/llm/llm/lib/index.js'
import SessionStore, { SessionId } from '../../sources/deepseek-harness/packages/core/session/lib/index.js'
import { serializeRequest } from '../../sources/deepseek-harness/packages/llm/llm-deepseek/lib/types/serialize.js'
import { DONE, parseSse } from '../../sources/deepseek-harness/packages/llm/llm-deepseek/lib/types/sse.js'

function positiveInteger(raw, name) {
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`)
  return value
}

async function measure(iterations, operation) {
  const beforeCpu = process.cpuUsage()
  const started = process.hrtime.bigint()
  let value
  for (let index = 0; index < iterations; index += 1) value = await operation()
  const ended = process.hrtime.bigint()
  const cpu = process.cpuUsage(beforeCpu)
  return {
    value,
    measurement: {
      iterations,
      wall_ns: Number(ended - started),
      cpu_user_us: cpu.user,
      cpu_system_us: cpu.system,
      cpu_total_us: cpu.user + cpu.system,
    },
  }
}

function byteStream(bytes, chunkBytes) {
  return new ReadableStream({
    start(controller) {
      for (let offset = 0; offset < bytes.byteLength; offset += chunkBytes) {
        controller.enqueue(bytes.subarray(offset, Math.min(offset + chunkBytes, bytes.byteLength)))
      }
      controller.close()
    },
  })
}

const contextBytes = positiveInteger(process.argv[2], 'context-bytes')
const iterations = positiveInteger(process.argv[3] ?? '3', 'iterations')
const streamChunkBytes = positiveInteger(process.argv[4] ?? '16384', 'stream-chunk-bytes')
const payload = 'x'.repeat(contextBytes)

// One completed turn fixes the event/message shape while only text bytes grow.
const ctx = new Context()
await ctx.plugin(SessionStore)
const session = ctx.sessions.create(SessionId(`c3-${process.pid}`), {
  meta: { cwd: process.cwd(), createdAt: 0 },
})
const message = createUserMessage({
  content: [{ type: 'text', text: payload }],
  source: { kind: 'user' },
  metadata: { c3: true },
})
session.append('turn/start', { turn: 1 })
session.append('user/message', message, { surfaceOp: 'append' })
session.append('turn/end', { turn: 1, reason: { kind: 'completed' } })

const derive = await measure(iterations, () => session.deriveMessages())
const requestOptions = {
  model: 'c3-context-json-mock',
  messages: derive.value,
  system: 'C3 fixed system prompt',
  tools: [{
    name: 'noop',
    description: 'C3 fixed tool schema',
    parameters: {
      type: 'object',
      properties: { value: { type: 'string' } },
      required: ['value'],
      additionalProperties: false,
    },
  }],
  maxTokens: 16,
}
const assemble = await measure(iterations, () => serializeRequest(requestOptions, { thinking: 'disabled' }))
const encode = await measure(iterations, () => JSON.stringify(assemble.value))
const requestJson = encode.value
const requestBytes = Buffer.byteLength(requestJson, 'utf8')
const decode = await measure(iterations, () => JSON.parse(requestJson))

// The response axis carries the same logical text bytes in one valid
// chat-completions delta. Encoding/chunk construction stays outside timing.
const responseObject = {
  id: 'c3-response',
  object: 'chat.completion.chunk',
  created: 0,
  model: 'c3-context-json-mock',
  choices: [{ index: 0, delta: { content: payload }, finish_reason: null }],
}
const responseJson = JSON.stringify(responseObject)
const sseBytes = new TextEncoder().encode(`data: ${responseJson}\n\ndata: ${DONE}\n\n`)
const sse = await measure(iterations, async () => {
  const decoded = []
  for await (const data of parseSse(byteStream(sseBytes, streamChunkBytes))) {
    if (data !== DONE) decoded.push(JSON.parse(data))
  }
  return decoded
})

const derivedText = derive.value[0]?.content?.find(block => block.type === 'text')?.text
const wireText = assemble.value.messages.find(item => item.role === 'user')?.content
const parsedText = decode.value.messages.find(item => item.role === 'user')?.content
const sseText = sse.value[0]?.choices?.[0]?.delta?.content
const checks = {
  event_count_exact: session.events.length === 3,
  derived_message_count_exact: derive.value.length === 1,
  derived_payload_exact: derivedText === payload,
  request_wire_payload_exact: wireText === payload,
  request_json_utf8_size_exact: requestBytes === Buffer.byteLength(requestJson, 'utf8'),
  request_decode_payload_exact: parsedText === payload,
  sse_event_count_exact: sse.value.length === 1,
  sse_payload_exact: sseText === payload,
}
if (!Object.values(checks).every(Boolean)) {
  throw new Error(`C3 invariant failure: ${JSON.stringify(checks)}`)
}

const operations = {
  derive_messages: derive.measurement,
  assemble_wire_request: assemble.measurement,
  json_encode_request: encode.measurement,
  json_decode_request: decode.measurement,
  sse_frame_and_json_decode: sse.measurement,
}
for (const measurement of Object.values(operations)) {
  measurement.cpu_us_per_iteration = measurement.cpu_total_us / iterations
  measurement.wall_ns_per_iteration = measurement.wall_ns / iterations
}

const resources = process.resourceUsage()
const output = {
  benchmark: 'C3 fixed-shape context serialization and SSE parsing',
  context_bytes: contextBytes,
  request_json_bytes: requestBytes,
  response_json_bytes: Buffer.byteLength(responseJson, 'utf8'),
  sse_wire_bytes: sseBytes.byteLength,
  iterations,
  stream_chunk_bytes: streamChunkBytes,
  operations,
  resources: {
    max_rss_kb: resources.maxRSS,
    minor_page_faults: resources.minorPageFault,
    major_page_faults: resources.majorPageFault,
    voluntary_context_switches: resources.voluntaryContextSwitches,
    involuntary_context_switches: resources.involuntaryContextSwitches,
  },
  checks,
}

await ctx.fiber.dispose()
console.log(JSON.stringify(output))
