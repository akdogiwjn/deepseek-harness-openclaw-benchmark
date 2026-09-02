#!/usr/bin/env node
/** C5 DSH native-vs-PTC Agent Loop CPU fixture. */

import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
import LlmRuntime, { createUserMessage, LlmAdapter } from '../../sources/deepseek-harness/packages/llm/llm/lib/index.js'
import SessionStore, { SessionId } from '../../sources/deepseek-harness/packages/core/session/lib/index.js'
import SessionProjectionRegistry from '../../sources/deepseek-harness/packages/session/session-projection/lib/index.js'
import SystemPrompt from '../../sources/deepseek-harness/packages/core/system-prompt/lib/index.js'
import ToolRuntime, { defineTool, RUN_CODE_NAME } from '../../sources/deepseek-harness/packages/core/tools/lib/index.js'
import WorkerThreadCodeRuntime from '../../sources/deepseek-harness/packages/code-runtime/code-runtime-worker-thread/lib/index.js'
import AgentRegistry from '../../sources/deepseek-harness/packages/core/agent/lib/index.js'
import AgentLoop from '../../sources/deepseek-harness/packages/core/agent-loop/lib/index.js'

function nonNegativeInteger(raw, name) {
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < 0) throw new Error(`${name} must be a non-negative integer`)
  return value
}

const mode = process.argv[2]
if (mode !== 'native' && mode !== 'ptc') throw new Error('mode must be native or ptc')
const operations = nonNegativeInteger(process.argv[3], 'operations')
const payloadBytes = nonNegativeInteger(process.argv[4] ?? '16', 'payload-bytes')
const payload = 'x'.repeat(payloadBytes)
const resultText = 'r'.repeat(payloadBytes)
const program = `const results = []; for (let i = 0; i < ${operations}; i += 1) results.push(await tools.noop({ payload: ${JSON.stringify(payload)} })); return results.length;`

class DeterministicAdapter extends LlmAdapter {
  requests = 0
  requestToolNames = []

  resolveModel(provider, model) {
    return Promise.resolve({ provider, id: model, name: model })
  }

  async * stream(options) {
    this.requests += 1
    this.requestToolNames.push(options.tools.map(tool => tool.name))
    const shouldCall = mode === 'native' ? this.requests <= operations : this.requests === 1
    if (shouldCall) {
      const id = `c5-${mode}-${String(this.requests).padStart(6, '0')}`
      const name = mode === 'native' ? 'noop' : RUN_CODE_NAME
      const args = mode === 'native'
        ? { payload }
        : { code: program, description: `Execute ${operations} sequential no-op tools` }
      const argumentsJson = JSON.stringify(args)
      yield { type: 'block-start', index: 0, blockType: 'tool-call' }
      yield { type: 'tool-call-delta', index: 0, id, name, argumentsDelta: argumentsJson }
      yield { type: 'block-end', index: 0, block: { type: 'tool-call', id, name, arguments: argumentsJson } }
      yield { type: 'usage', usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 } }
      yield { type: 'finish', reason: { kind: 'tool-calls' } }
      return
    }
    const text = 'C5_COMPLETED'
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
  persona: 'Deterministic C5 CPU fixture.',
})
await ctx.plugin(ToolRuntime, { mode })
if (mode === 'ptc') {
  await ctx.plugin(WorkerThreadCodeRuntime, {
    computeMs: 60_000,
    maxWallMs: 120_000,
    maxOutputBytes: 1_048_576,
    maxOldGenerationSizeMb: 128,
  })
}
let toolInvocations = 0
const invocationPayloads = []
ctx.tools.register(defineTool({
  name: 'noop',
  description: 'Return a fixed deterministic result without I/O.',
  parameters: { payload: { type: 'string', required: true } },
  output: {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: value }],
  },
  async execute(args) {
    toolInvocations += 1
    invocationPayloads.push(args.payload)
    return resultText
  },
}))
await ctx.plugin(AgentRegistry)
await ctx.plugin(AgentLoop, { agents: [] })
const adapter = new DeterministicAdapter()
ctx.llm.registerAdapter(['c5-in-process'], adapter)
const agent = ctx.agentLoop.create(SessionId(`c5-${mode}-${process.pid}`), {
  provider: 'c5-in-process', model: 'deterministic',
})

const beforeCpu = process.cpuUsage()
const beforeResource = process.resourceUsage()
const started = process.hrtime.bigint()
agent.followup(createUserMessage({
  content: [{ type: 'text', text: 'Run the deterministic C5 sequence.' }],
  source: { kind: 'user' },
}))
await agent.whenIdle()
const ended = process.hrtime.bigint()
const cpu = process.cpuUsage(beforeCpu)
const afterResource = process.resourceUsage()

const eventCounts = {}
for (const event of agent.session.events) eventCounts[event.type] = (eventCounts[event.type] ?? 0) + 1
const expectedRequests = mode === 'native' ? operations + 1 : 2
const expectedOuterCalls = mode === 'native' ? operations : 1
const expectedDispatches = mode === 'ptc' ? operations : 0
const expectedPresented = mode === 'native' ? 'noop' : RUN_CODE_NAME
const checks = {
  provider_requests_exact: adapter.requests === expectedRequests,
  presented_tool_exact: adapter.requestToolNames.every(names => names.length === 1 && names[0] === expectedPresented),
  tool_invocations_exact: toolInvocations === operations,
  payloads_exact: invocationPayloads.every(value => value === payload),
  outer_tool_calls_exact: (eventCounts['tool/call'] ?? 0) === expectedOuterCalls,
  outer_tool_results_exact: (eventCounts['tool/result'] ?? 0) === expectedOuterCalls,
  code_dispatch_starts_exact: (eventCounts['tool/code-dispatch-start'] ?? 0) === expectedDispatches,
  code_dispatches_exact: (eventCounts['tool/code-dispatch'] ?? 0) === expectedDispatches,
  steps_exact: eventCounts['step/start'] === expectedRequests && eventCounts['step/end'] === expectedRequests,
  one_completed_turn: eventCounts['turn/start'] === 1 && eventCounts['turn/end'] === 1,
}
if (!Object.values(checks).every(Boolean)) throw new Error(`C5 invariant failure: ${JSON.stringify({ checks, eventCounts, requestToolNames: adapter.requestToolNames })}`)

const wallNs = Number(ended - started)
const cpuTotalUs = cpu.user + cpu.system
console.log(JSON.stringify({
  benchmark: 'C5 DSH native-vs-PTC Agent Loop',
  mode,
  operations,
  payload_bytes: payloadBytes,
  provider_requests: adapter.requests,
  tool_invocations: toolInvocations,
  session_event_count: agent.session.events.length,
  event_counts: eventCounts,
  request_tool_names: adapter.requestToolNames,
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
}))

await ctx.fiber.dispose()
