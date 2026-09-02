#!/usr/bin/env node
/** C2 append-only Session/Event Log primitive CPU fixture. */

import { mkdtemp, rm, stat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
import { createUserMessage } from '../../sources/deepseek-harness/packages/llm/llm/lib/index.js'
import SessionStore, { SessionId } from '../../sources/deepseek-harness/packages/core/session/lib/index.js'
import JsonlSessionPersistence from '../../sources/deepseek-harness/packages/session/session-persistence-jsonl/lib/index.js'

function positiveInteger(raw, name) {
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`)
  return value
}

async function measure(operation) {
  const beforeCpu = process.cpuUsage()
  const started = process.hrtime.bigint()
  const value = await operation()
  const ended = process.hrtime.bigint()
  const cpu = process.cpuUsage(beforeCpu)
  return {
    value,
    measurement: {
      wall_ns: Number(ended - started),
      cpu_user_us: cpu.user,
      cpu_system_us: cpu.system,
      cpu_total_us: cpu.user + cpu.system,
    },
  }
}

const turns = positiveInteger(process.argv[2], 'turns')
const payloadBytes = positiveInteger(process.argv[3] ?? '256', 'payload-bytes')
const payload = 'x'.repeat(payloadBytes)
const persistenceRoot = await mkdtemp(join(tmpdir(), 'dsh-c2-session-'))
const sessionId = SessionId(`c2-${process.pid}`)

// Message construction is deliberately outside append timing. C2 append then
// measures Session validation/snapshot/event work rather than UUID generation.
const messages = Array.from({ length: turns }, (_, index) => createUserMessage({
  content: [{ type: 'text', text: payload }],
  source: { kind: 'user' },
  metadata: { c2Turn: index + 1 },
}))

const memoryCtx = new Context()
await memoryCtx.plugin(SessionStore)
const parent = memoryCtx.sessions.create(sessionId, { meta: { cwd: process.cwd(), createdAt: 0 } })
const append = await measure(() => {
  for (let index = 0; index < turns; index += 1) {
    const turn = index + 1
    parent.append('turn/start', { turn })
    parent.append('user/message', messages[index], { surfaceOp: 'append' })
    parent.append('turn/end', { turn, reason: { kind: 'completed' } })
  }
})

const derive = await measure(() => parent.deriveMessages())
const boundary = parent.events.at(-1)?.seq
if (boundary === undefined) throw new Error('C2 parent has no fork boundary')
const fork = await measure(() => memoryCtx.sessions.fork(
  parent,
  boundary,
  SessionId(`c2-child-${process.pid}`),
))

const writeCtx = new Context()
await writeCtx.plugin(SessionStore)
await writeCtx.plugin(JsonlSessionPersistence, {
  root: persistenceRoot,
  compression: 'none',
  packChunks: false,
})
const persist = await measure(async () => {
  await writeCtx.sessionPersistence.create(parent.header)
  await writeCtx.sessionPersistence.append(parent.id, parent.events)
})
const location = writeCtx.sessionPersistence.locate(parent.header)
if (location.kind !== 'jsonl') throw new Error(`unexpected C2 persistence location: ${location.kind}`)
const logBytes = (await stat(location.path)).size

// A fresh backend avoids the writer coordinator's prepared-session cache. The
// host page cache remains warm; true cold-cache load is a separate future case.
const loadCtx = new Context()
await loadCtx.plugin(SessionStore)
await loadCtx.plugin(JsonlSessionPersistence, {
  root: persistenceRoot,
  compression: 'none',
  packChunks: false,
})
const load = await measure(() => loadCtx.sessionPersistence.load(parent.id))

const eventCount = parent.events.length
const child = fork.value
const loaded = load.value
const checks = {
  event_count_exact: eventCount === turns * 3,
  derived_message_count_exact: derive.value.length === turns,
  derived_payloads_exact: derive.value.every(message =>
    message.content.some(block => block.type === 'text' && block.text === payload)),
  fork_seed_exact: child.header.seedLength === eventCount
    && child.events.length === eventCount + 1
    && child.events.at(-1)?.type === 'session/end-seed',
  load_event_count_exact: loaded.events.length === eventCount,
  load_prefix_exact: JSON.stringify(loaded.events) === JSON.stringify(parent.events),
  load_header_exact: loaded.meta.id === parent.header.id
    && loaded.meta.cwd === parent.header.cwd,
}
if (!Object.values(checks).every(Boolean)) {
  throw new Error(`C2 invariant failure: ${JSON.stringify(checks)}`)
}

const resources = process.resourceUsage()
const output = {
  benchmark: 'C2 append-only Session/Event Log primitives',
  shape: 'three-event completed user turns: turn/start, user/message, turn/end',
  turns,
  event_count: eventCount,
  payload_bytes: payloadBytes,
  logical_payload_bytes: turns * payloadBytes,
  derived_message_count: derive.value.length,
  log_bytes: logBytes,
  operations: {
    append: append.measurement,
    derive_messages: derive.measurement,
    fork_prefix: fork.measurement,
    jsonl_write: persist.measurement,
    jsonl_warm_load: load.measurement,
  },
  resources: {
    max_rss_kb: resources.maxRSS,
    minor_page_faults: resources.minorPageFault,
    major_page_faults: resources.majorPageFault,
    voluntary_context_switches: resources.voluntaryContextSwitches,
    involuntary_context_switches: resources.involuntaryContextSwitches,
  },
  checks,
}

await loadCtx.fiber.dispose()
await writeCtx.fiber.dispose()
await memoryCtx.fiber.dispose()
await rm(persistenceRoot, { recursive: true, force: true })
console.log(JSON.stringify(output))
