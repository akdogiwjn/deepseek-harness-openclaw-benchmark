#!/usr/bin/env node
/** C8 token-meter / context-pressure CPU fixture.

Measures the pinned DeepSeek Harness `TokenMeter.measure(session)` path, which is
O(surface): it replays the durable tail through the session surface, reprices
every node, and deep-clones the resulting measurement. Four subtests isolate the
replay, incremental, repeated-measure, and surface-shape costs.
*/

import { writeSync } from 'node:fs'
import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
import { createAssistantMessage, createToolResultMessage, createUserMessage } from '../../sources/deepseek-harness/packages/llm/llm/lib/index.js'
import SessionStore, { SessionId } from '../../sources/deepseek-harness/packages/core/session/lib/index.js'
import SessionProjectionRegistry from '../../sources/deepseek-harness/packages/session/session-projection/lib/index.js'
import TokenMeter from '../../sources/deepseek-harness/packages/llm/token-meter/lib/index.js'

function positiveInteger(raw, name, { allowZero = false } = {}) {
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < (allowZero ? 0 : 1)) {
    throw new Error(`${name} must be a ${allowZero ? 'non-negative' : 'positive'} integer`)
  }
  return value
}

const subtest = process.argv[2] ?? 'repeat'
const surfaceEvents = positiveInteger(process.argv[3], 'surface-events', { allowZero: true })
const payloadBytes = positiveInteger(process.argv[4] ?? '256', 'payload-bytes')
const iterations = positiveInteger(process.argv[5] ?? '1000', 'iterations')
const shape = process.argv[6] ?? 'text'
const payload = 'x'.repeat(payloadBytes)

function textMessage(turn) {
  return createUserMessage({
    content: [{ type: 'text', text: `c8-${turn}-${payload}` }],
    source: { kind: 'user' },
  })
}

function appendTextTurn(session, turn) {
  session.append('turn/start', { turn })
  session.append('user/message', textMessage(turn), { surfaceOp: 'append' })
  session.append('turn/end', { turn, reason: { kind: 'completed' } })
}

function appendShapeTurn(session, turn, kind) {
  session.append('turn/start', { turn })
  session.append('step/start', { turn, step: 1 })
  if (kind === 'tool-call') {
    session.append('assistant/message', {
      turn,
      step: 1,
      message: createAssistantMessage({
        content: [{ type: 'tool-call', id: `c8-tc-${turn}`, name: 'read_file', arguments: JSON.stringify({ payload }) }],
      }),
    }, { surfaceOp: 'append' })
  } else if (kind === 'tool-result') {
    session.append('tool/result', {
      turn,
      step: 1,
      message: createToolResultMessage({
        callId: `c8-tr-${turn}`,
        content: [{ type: 'text', text: payload }],
        isError: false,
      }),
    }, { surfaceOp: 'append' })
  } else {
    session.append('user/message', textMessage(turn), { surfaceOp: 'append' })
  }
  session.append('step/end', { turn, step: 1 })
  session.append('turn/end', { turn, reason: { kind: 'completed' } })
}

function timeMeasure(fn) {
  const beforeCpu = process.cpuUsage()
  const started = process.hrtime.bigint()
  const value = fn()
  const ended = process.hrtime.bigint()
  const cpu = process.cpuUsage(beforeCpu)
  return {
    value,
    wallNs: Number(ended - started),
    cpuUserUs: cpu.user,
    cpuSystemUs: cpu.system,
    cpuTotalUs: cpu.user + cpu.system,
  }
}

function median(values) {
  if (values.length === 0) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid]
}

const ctx = new Context()
await ctx.plugin(SessionStore)
await ctx.plugin(SessionProjectionRegistry)
await ctx.plugin(TokenMeter)

const session = ctx.sessions.create(SessionId(`c8-${process.pid}`), { meta: { cwd: process.cwd(), createdAt: 0 } })
const meter = ctx.tokenMeter

// Populate the surface with `surfaceEvents` text turns for the non-shape subtests.
if (subtest !== 'shape') {
  for (let turn = 1; turn <= surfaceEvents; turn += 1) {
    appendTextTurn(session, turn)
  }
}

if (subtest === 'cold') {
  // First measure faces the complete history; _sync replays the whole tail.
  const run = timeMeasure(() => meter.measure(session))
  const measurement = run.value
  const output = {
    benchmark: 'C8 token-meter context-pressure',
    subtest: 'cold',
    surface_events: surfaceEvents,
    surface_nodes: measurement.nodes.length,
    surface_tokens: measurement.surfaceTokens,
    payload_bytes: payloadBytes,
    measure: {
      wall_ns: run.wallNs,
      cpu_user_us: run.cpuUserUs,
      cpu_system_us: run.cpuSystemUs,
      cpu_total_us: run.cpuTotalUs,
    },
    checks: {
      surface_nodes_exact: measurement.nodes.length === surfaceEvents,
    },
  }
  await ctx.fiber.dispose()
  writeSync(1, `${JSON.stringify(output)}\n`)
} else if (subtest === 'incremental') {
  // Sync once, then append one new text turn and re-measure each iteration.
  const first = meter.measure(session)
  const wallNs = []
  const cpuTotalUs = []
  for (let it = 0; it < iterations; it += 1) {
    const turn = surfaceEvents + it + 1
    const run = timeMeasure(() => {
      appendTextTurn(session, turn)
      return meter.measure(session)
    })
    wallNs.push(run.wallNs)
    cpuTotalUs.push(run.cpuTotalUs)
  }
  const finalMeasurement = meter.measure(session)
  const output = {
    benchmark: 'C8 token-meter context-pressure',
    subtest: 'incremental',
    surface_events: surfaceEvents,
    surface_events_final: surfaceEvents + iterations,
    surface_nodes: finalMeasurement.nodes.length,
    surface_tokens: finalMeasurement.surfaceTokens,
    payload_bytes: payloadBytes,
    iterations,
    measure: {
      wall_ns: median(wallNs),
      cpu_total_us: median(cpuTotalUs),
    },
    checks: {
      surface_nodes_exact: finalMeasurement.nodes.length === surfaceEvents + iterations,
      initial_nodes_exact: first.nodes.length === surfaceEvents,
    },
  }
  await ctx.fiber.dispose()
  writeSync(1, `${JSON.stringify(output)}\n`)
} else if (subtest === 'repeat') {
  // Session fixed; measure() only reprices + clones, O(surface) per call.
  const first = meter.measure(session)
  const wallNs = []
  const cpuTotalUs = []
  const cpuUserUs = []
  let stableTokens = true
  for (let it = 0; it < iterations; it += 1) {
    const run = timeMeasure(() => meter.measure(session))
    wallNs.push(run.wallNs)
    cpuTotalUs.push(run.cpuTotalUs)
    cpuUserUs.push(run.cpuUserUs)
    if (run.value.surfaceTokens !== first.surfaceTokens) stableTokens = false
  }
  const output = {
    benchmark: 'C8 token-meter context-pressure',
    subtest: 'repeat',
    surface_events: surfaceEvents,
    surface_nodes: first.nodes.length,
    surface_tokens: first.surfaceTokens,
    payload_bytes: payloadBytes,
    iterations,
    measure: {
      wall_ns: median(wallNs),
      cpu_total_us: median(cpuTotalUs),
      cpu_user_us: median(cpuUserUs),
    },
    checks: {
      surface_nodes_exact: first.nodes.length === surfaceEvents,
      stable_surface_tokens: stableTokens,
    },
  }
  await ctx.fiber.dispose()
  writeSync(1, `${JSON.stringify(output)}\n`)
} else if (subtest === 'shape') {
  let header
  let schemaBytes = null
  if (shape === 'schema') {
    for (let turn = 1; turn <= 32; turn += 1) appendTextTurn(session, turn)
    const tools = Array.from({ length: surfaceEvents }, (_, index) => ({
      name: `tool_${index}`,
      description: 's'.repeat(payloadBytes),
      parameters: { type: 'object', properties: {}, required: [] },
    }))
    schemaBytes = JSON.stringify(tools).length
    header = { config: { provider: 'bench', model: 'deterministic' }, tools }
  } else {
    for (let turn = 1; turn <= surfaceEvents; turn += 1) {
      appendShapeTurn(session, turn, shape)
    }
  }
  const measureFn = () => (header === undefined ? meter.measure(session) : meter.measure(session, header))
  const first = measureFn()
  const wallNs = []
  const cpuTotalUs = []
  let stableTokens = true
  for (let it = 0; it < iterations; it += 1) {
    const run = timeMeasure(measureFn)
    wallNs.push(run.wallNs)
    cpuTotalUs.push(run.cpuTotalUs)
    if (run.value.surfaceTokens !== first.surfaceTokens) stableTokens = false
  }
  const output = {
    benchmark: 'C8 token-meter context-pressure',
    subtest: 'shape',
    shape,
    surface_events: surfaceEvents,
    surface_nodes: first.nodes.length,
    surface_tokens: first.surfaceTokens,
    payload_bytes: payloadBytes,
    iterations,
    ...(schemaBytes !== null ? { schema_bytes: schemaBytes } : {}),
    measure: {
      wall_ns: median(wallNs),
      cpu_total_us: median(cpuTotalUs),
    },
    checks: {
      surface_nodes_exact: first.nodes.length === (shape === 'schema' ? 32 : surfaceEvents),
      stable_surface_tokens: stableTokens,
    },
  }
  await ctx.fiber.dispose()
  writeSync(1, `${JSON.stringify(output)}\n`)
} else {
  throw new Error(`unknown C8 subtest: ${subtest}`)
}