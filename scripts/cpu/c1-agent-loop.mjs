#!/usr/bin/env node
/** C1 in-process deterministic Agent Loop CPU fixture. */

import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
import { writeSync } from 'node:fs'
import LlmRuntime, { createUserMessage, LlmAdapter } from '../../sources/deepseek-harness/packages/llm/llm/lib/index.js'
import SessionStore, { SessionId } from '../../sources/deepseek-harness/packages/core/session/lib/index.js'
import SessionProjectionRegistry from '../../sources/deepseek-harness/packages/session/session-projection/lib/index.js'
import SystemPrompt from '../../sources/deepseek-harness/packages/core/system-prompt/lib/index.js'
import ToolRuntime, { defineTool } from '../../sources/deepseek-harness/packages/core/tools/lib/index.js'
import AgentRegistry from '../../sources/deepseek-harness/packages/core/agent/lib/index.js'
import AgentLoop from '../../sources/deepseek-harness/packages/core/agent-loop/lib/index.js'

function positiveInteger(raw, name, { allowZero = false } = {}) {
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < (allowZero ? 0 : 1)) {
    throw new Error(`${name} must be a ${allowZero ? 'non-negative' : 'positive'} integer`)
  }
  return value
}

const toolSteps = positiveInteger(process.argv[2], 'tool-steps', { allowZero: true })
const payloadBytes = positiveInteger(process.argv[3] ?? '64', 'payload-bytes')
const payload = 'x'.repeat(payloadBytes)
const resultText = 'r'.repeat(payloadBytes)
const measuredTurns = process.argv[4] !== undefined
  ? positiveInteger(process.argv[4], 'measured-turns', { allowZero: true })
  : 0
const warmupTurns = process.argv[5] !== undefined
  ? positiveInteger(process.argv[5], 'warmup-turns', { allowZero: true })
  : (measuredTurns > 0 ? 1 : 0)

class DeterministicAdapter extends LlmAdapter {
  requestMessageCounts = []
  requestToolCounts = []
  requests = 0
  turnBaseRequests = 0

  resolveModel(provider, model) {
    return Promise.resolve({ provider, id: model, name: model })
  }

  async * stream(options) {
    this.requests += 1
    this.requestMessageCounts.push(options.messages.length)
    this.requestToolCounts.push(options.tools.length)
    const turnRequests = this.requests - this.turnBaseRequests
    if (turnRequests <= toolSteps) {
      const id = `c1-call-${String(turnRequests).padStart(6, '0')}`
      const argumentsJson = JSON.stringify({ payload })
      yield { type: 'block-start', index: 0, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: 0, id, name: 'noop', argumentsDelta: argumentsJson }
      yield {
        type: 'block-end',
        index: 0,
        block: { type: 'tool-call', id, name: 'noop', arguments: argumentsJson },
      }
      yield { type: 'usage', usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 } }
      yield { type: 'finish', reason: { kind: 'tool-calls' } }
      return
    }
    const text = 'C1_COMPLETED'
    yield { type: 'block-start', index: 0, blockType: 'text' }
    yield { type: 'text-delta', index: 0, text }
    yield { type: 'block-end', index: 0, block: { type: 'text', text } }
    yield { type: 'usage', usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 } }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}

const ctx = new Context()
await ctx.plugin(LlmRuntime)
await ctx.plugin(SessionStore)
await ctx.plugin(SessionProjectionRegistry)
await ctx.plugin(SystemPrompt, {
  includeHarnessIdentity: false,
  includeRuntimeContext: false,
  persona: 'Deterministic C1 CPU fixture.',
})
await ctx.plugin(ToolRuntime)
let toolInvocations = 0
ctx.tools.register(defineTool({
  name: 'noop',
  description: 'Return a fixed-size deterministic result without I/O.',
  parameters: {
    payload: { type: 'string', required: true },
  },
  output: {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: value }],
  },
  async execute(args) {
    if (args.payload.length !== payloadBytes) throw new Error('unexpected C1 payload size')
    toolInvocations += 1
    return resultText
  },
}))
await ctx.plugin(AgentRegistry)
await ctx.plugin(AgentLoop, { agents: [] })
const adapter = new DeterministicAdapter()
ctx.llm.registerAdapter(['c1-in-process'], adapter)

const expectedRequests = toolSteps + 1

async function runTurn(turnIndex) {
  const agent = ctx.agentLoop.create(SessionId(`c1-${process.pid}-${turnIndex}`), {
    provider: 'c1-in-process',
    model: 'deterministic',
  })
  const beforeCpu = process.cpuUsage()
  const beforeResource = process.resourceUsage()
  const requestsBefore = adapter.requests
  const invocationsBefore = toolInvocations
  const started = process.hrtime.bigint()
  adapter.turnBaseRequests = adapter.requests
  agent.followup(createUserMessage({
    content: [{ type: 'text', text: 'Run the deterministic C1 sequence.' }],
    source: { kind: 'user' },
  }))
  await agent.whenIdle()
  const ended = process.hrtime.bigint()
  const cpu = process.cpuUsage(beforeCpu)
  const afterResource = process.resourceUsage()
  const requestsDelta = adapter.requests - requestsBefore
  const invocationsDelta = toolInvocations - invocationsBefore
  const eventCounts = {}
  for (const event of agent.session.events) {
    eventCounts[event.type] = (eventCounts[event.type] ?? 0) + 1
  }
  return {
    agent,
    wallNs: Number(ended - started),
    cpuUserUs: cpu.user,
    cpuSystemUs: cpu.system,
    cpuTotalUs: cpu.user + cpu.system,
    beforeResource,
    afterResource,
    requestsDelta,
    invocationsDelta,
    eventCounts,
    sessionEventCount: agent.session.events.length,
  }
}

if (measuredTurns === 0) {
  const turn = await runTurn(0)
  const checks = {
    provider_requests: turn.requestsDelta === expectedRequests,
    tool_invocations: turn.invocationsDelta === toolSteps,
    tool_calls: (turn.eventCounts['tool/call'] ?? 0) === toolSteps,
    tool_results: (turn.eventCounts['tool/result'] ?? 0) === toolSteps,
    step_starts: turn.eventCounts['step/start'] === expectedRequests,
    step_ends: turn.eventCounts['step/end'] === expectedRequests,
    one_completed_turn: turn.eventCounts['turn/start'] === 1 && turn.eventCounts['turn/end'] === 1,
  }
  if (!Object.values(checks).every(Boolean)) {
    throw new Error(`C1 invariant failure: ${JSON.stringify({ checks, eventCounts: turn.eventCounts })}`)
  }
  const output = {
    benchmark: 'C1 in-process deterministic Agent Loop',
    measurement_scope: 'after context/agent setup, from prompt enqueue through idle',
    tool_steps: toolSteps,
    agent_steps: expectedRequests,
    payload_bytes: payloadBytes,
    provider_requests: turn.requestsDelta,
    tool_invocations: turn.invocationsDelta,
    session_event_count: turn.sessionEventCount,
    event_counts: turn.eventCounts,
    request_message_counts: adapter.requestMessageCounts,
    request_tool_counts: adapter.requestToolCounts,
    timing: {
      wall_ns: turn.wallNs,
      cpu_user_us: turn.cpuUserUs,
      cpu_system_us: turn.cpuSystemUs,
      cpu_total_us: turn.cpuTotalUs,
      cpu_utilization: turn.wallNs === 0 ? null : turn.cpuTotalUs * 1000 / turn.wallNs,
    },
    resources: {
      max_rss_kb: turn.afterResource.maxRSS,
      minor_page_faults_delta: turn.afterResource.minorPageFault - turn.beforeResource.minorPageFault,
      major_page_faults_delta: turn.afterResource.majorPageFault - turn.beforeResource.majorPageFault,
      voluntary_context_switches_delta: turn.afterResource.voluntaryContextSwitches - turn.beforeResource.voluntaryContextSwitches,
      involuntary_context_switches_delta: turn.afterResource.involuntaryContextSwitches - turn.beforeResource.involuntaryContextSwitches,
    },
    checks,
  }
  await ctx.fiber.dispose()
  writeSync(1, `${JSON.stringify(output)}\n`)
} else {
  const totalTurns = warmupTurns + measuredTurns
  const sampled = []
  for (let i = 0; i < totalTurns; i++) {
    const turn = await runTurn(i)
    if (i >= warmupTurns) sampled.push(turn)
  }
  const perTurnChecks = sampled.map((turn) => ({
    provider_requests: turn.requestsDelta === expectedRequests,
    tool_invocations: turn.invocationsDelta === toolSteps,
    tool_calls: (turn.eventCounts['tool/call'] ?? 0) === toolSteps,
    tool_results: (turn.eventCounts['tool/result'] ?? 0) === toolSteps,
    step_starts: turn.eventCounts['step/start'] === expectedRequests,
    step_ends: turn.eventCounts['step/end'] === expectedRequests,
    one_completed_turn: turn.eventCounts['turn/start'] === 1 && turn.eventCounts['turn/end'] === 1,
  }))
  const allValid = perTurnChecks.every((checks) => Object.values(checks).every(Boolean))
  if (!allValid) {
    throw new Error(`C1 warm invariant failure: ${JSON.stringify(perTurnChecks)}`)
  }
  const resources = process.resourceUsage()
  const output = {
    benchmark: 'C1-warm fixed-context in-process deterministic Agent Loop',
    measurement_scope: 'fresh Session per turn; fixed context; process warm after warmup turns',
    tool_steps: toolSteps,
    payload_bytes: payloadBytes,
    warmup_turns: warmupTurns,
    measured_turns: measuredTurns,
    session_event_count_per_turn: sampled[0].sessionEventCount,
    turns: sampled.map((turn) => ({
      wall_ns: turn.wallNs,
      cpu_user_us: turn.cpuUserUs,
      cpu_system_us: turn.cpuSystemUs,
      cpu_total_us: turn.cpuTotalUs,
      provider_requests: turn.requestsDelta,
      tool_invocations: turn.invocationsDelta,
    })),
    checks: { all_turns_valid: allValid, per_turn_checks: perTurnChecks },
    resources: { max_rss_kb: resources.maxRSS },
  }
  await ctx.fiber.dispose()
  writeSync(1, `${JSON.stringify(output)}\n`)
}