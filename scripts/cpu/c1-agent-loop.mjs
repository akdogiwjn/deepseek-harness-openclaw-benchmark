#!/usr/bin/env node
/** C1 in-process deterministic Agent Loop CPU fixture. */

import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
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

class DeterministicAdapter extends LlmAdapter {
  requestMessageCounts = []
  requestToolCounts = []
  requests = 0

  resolveModel(provider, model) {
    return Promise.resolve({ provider, id: model, name: model })
  }

  async * stream(options) {
    this.requests += 1
    this.requestMessageCounts.push(options.messages.length)
    this.requestToolCounts.push(options.tools.length)
    if (this.requests <= toolSteps) {
      const id = `c1-call-${String(this.requests).padStart(6, '0')}`
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
const agent = ctx.agentLoop.create(SessionId(`c1-${process.pid}`), {
  provider: 'c1-in-process',
  model: 'deterministic',
})

const beforeCpu = process.cpuUsage()
const beforeResource = process.resourceUsage()
const started = process.hrtime.bigint()
agent.followup(createUserMessage({
  content: [{ type: 'text', text: 'Run the deterministic C1 sequence.' }],
  source: { kind: 'user' },
}))
await agent.whenIdle()
const ended = process.hrtime.bigint()
const cpu = process.cpuUsage(beforeCpu)
const afterResource = process.resourceUsage()

const eventCounts = {}
for (const event of agent.session.events) {
  eventCounts[event.type] = (eventCounts[event.type] ?? 0) + 1
}
const expectedRequests = toolSteps + 1
const checks = {
  provider_requests: adapter.requests === expectedRequests,
  tool_invocations: toolInvocations === toolSteps,
  tool_calls: (eventCounts['tool/call'] ?? 0) === toolSteps,
  tool_results: (eventCounts['tool/result'] ?? 0) === toolSteps,
  step_starts: eventCounts['step/start'] === expectedRequests,
  step_ends: eventCounts['step/end'] === expectedRequests,
  one_completed_turn: eventCounts['turn/start'] === 1 && eventCounts['turn/end'] === 1,
}
if (!Object.values(checks).every(Boolean)) {
  throw new Error(`C1 invariant failure: ${JSON.stringify({ checks, eventCounts })}`)
}

const wallNs = Number(ended - started)
const cpuTotalUs = cpu.user + cpu.system
const output = {
  benchmark: 'C1 in-process deterministic Agent Loop',
  measurement_scope: 'after context/agent setup, from prompt enqueue through idle',
  tool_steps: toolSteps,
  agent_steps: expectedRequests,
  payload_bytes: payloadBytes,
  provider_requests: adapter.requests,
  tool_invocations: toolInvocations,
  session_event_count: agent.session.events.length,
  event_counts: eventCounts,
  request_message_counts: adapter.requestMessageCounts,
  request_tool_counts: adapter.requestToolCounts,
  timing: {
    wall_ns: wallNs,
    cpu_user_us: cpu.user,
    cpu_system_us: cpu.system,
    cpu_total_us: cpuTotalUs,
    cpu_utilization: wallNs === 0 ? null : cpuTotalUs * 1000 / wallNs,
  },
  resources: {
    max_rss_kb: afterResource.maxRSS,
    minor_page_faults_delta: afterResource.minorPageFault - beforeResource.minorPageFault,
    major_page_faults_delta: afterResource.majorPageFault - beforeResource.majorPageFault,
    voluntary_context_switches_delta: afterResource.voluntaryContextSwitches - beforeResource.voluntaryContextSwitches,
    involuntary_context_switches_delta: afterResource.involuntaryContextSwitches - beforeResource.involuntaryContextSwitches,
  },
  checks,
}

await ctx.fiber.dispose()
console.log(JSON.stringify(output))
