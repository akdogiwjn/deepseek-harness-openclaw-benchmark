#!/usr/bin/env node
/** Cold-resume one persisted W9 session through the official AgentRegistry API. */

import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { Context } from '../sources/deepseek-harness/vendor/cordis/lib/index.js'
import LlmRuntime, { createUserMessage, LlmAdapter } from '../sources/deepseek-harness/packages/llm/llm/lib/index.js'
import SessionStore, { SessionId } from '../sources/deepseek-harness/packages/core/session/lib/index.js'
import SessionProjectionRegistry from '../sources/deepseek-harness/packages/session/session-projection/lib/index.js'
import SystemPrompt from '../sources/deepseek-harness/packages/core/system-prompt/lib/index.js'
import ToolRuntime, { defineTool } from '../sources/deepseek-harness/packages/core/tools/lib/index.js'
import AgentRegistry from '../sources/deepseek-harness/packages/core/agent/lib/index.js'
import AgentLoop from '../sources/deepseek-harness/packages/core/agent-loop/lib/index.js'
import JsonlSessionPersistence from '../sources/deepseek-harness/packages/session/session-persistence-jsonl/lib/index.js'

class ResumeAdapter extends LlmAdapter {
  requests = []

  resolveModel(provider, model) {
    return Promise.resolve({ provider, id: model, name: model })
  }

  async * stream(options) {
    this.requests.push(options)
    const text = 'COMPLETED_W9_CRASH_RESUME'
    yield { type: 'block-start', index: 0, blockType: 'text' }
    yield { type: 'text-delta', index: 0, text }
    yield { type: 'block-end', index: 0, block: { type: 'text', text } }
    yield { type: 'usage', usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0 } }
    yield { type: 'finish', reason: { kind: 'stop' } }
  }
}

function waitForIdle(ctx, agent) {
  return new Promise(resolvePromise => {
    const dispose = ctx.on('agent/status', ({ agent: subject, status }) => {
      if (subject === agent && status === 'idle') {
        dispose()
        resolvePromise()
      }
    })
  })
}

const [sessionIdRaw, persistenceRoot, outputPath, crashCallId] = process.argv.slice(2)
if (sessionIdRaw === undefined || persistenceRoot === undefined || outputPath === undefined || crashCallId === undefined) {
  throw new Error('usage: resume-w9-session.mjs <session-id> <persistence-root> <output-json> <crash-call-id>')
}

const ctx = new Context()
await ctx.plugin(LlmRuntime)
await ctx.plugin(SessionStore)
await ctx.plugin(SessionProjectionRegistry)
await ctx.plugin(SystemPrompt, {
  includeHarnessIdentity: false,
  includeRuntimeContext: false,
  persona: 'You are a helpful software engineer assistant.',
})
await ctx.plugin(ToolRuntime)
let bashProbeInvocations = 0
ctx.tools.register(defineTool({
  name: 'bash',
  description: 'Executable W9 resume probe with the same public command shape as persistent bash.',
  parameters: {
    command: { type: 'string', required: true },
  },
  output: {
    schema: { type: 'string' },
    render: (_args, value) => [{ type: 'text', text: value }],
  },
  async execute() {
    bashProbeInvocations += 1
    return 'W9_RESUME_BASH_PROBE_EXECUTED'
  },
}))
await ctx.plugin(AgentRegistry)
await ctx.plugin(AgentLoop, { agents: [] })
await ctx.plugin(JsonlSessionPersistence, { root: resolve(persistenceRoot), compression: 'none' })
const adapter = new ResumeAdapter()
ctx.llm.registerAdapter(['w9-resume'], adapter)

const handle = await ctx.agents.resume({
  resumeSessionId: SessionId(sessionIdRaw),
  agentOptions: { provider: 'w9-resume', model: 'deterministic' },
})
const beforeFollowup = structuredClone(handle.agent.session.events)
const idle = waitForIdle(ctx, handle.agent)
handle.agent.followup(createUserMessage({
  content: [{ type: 'text', text: 'Continue the task. Inspect existing state before performing any side effect.' }],
  source: { kind: 'user' },
}))
await idle
await ctx.sessions.flush(handle.agent.session)
const afterFollowup = structuredClone(handle.agent.session.events)
const requestMessages = adapter.requests.map(request => request.messages)
const resumedMessages = requestMessages[0] ?? []
const contentBlocks = message => Array.isArray(message?.content) ? message.content : []
const toolCall = (message, callId) => contentBlocks(message).some(block =>
  block?.type === 'tool-call' && block.id === callId && block.name === 'bash')
const toolResult = (message, callId, isError) => message?.source?.kind === 'tool'
  && message.source.callId === callId
  && contentBlocks(message).some(block => block?.type === 'tool-result'
    && block.toolCallId === callId && block.isError === isError)
const messageText = message => JSON.stringify(contentBlocks(message))
const firstCallIndex = resumedMessages.findIndex(message => toolCall(message, 'callw9001'))
const firstResultIndex = resumedMessages.findIndex(message => toolResult(message, 'callw9001', false))
const crashCallIndex = resumedMessages.findIndex(message => toolCall(message, crashCallId))
const repairResultIndex = resumedMessages.findIndex(message => toolResult(message, crashCallId, true)
  && messageText(message).includes('outcome is unknown'))
const followupIndex = resumedMessages.findIndex(message => message?.role === 'user'
  && message?.source?.kind === 'user' && messageText(message).includes('Continue the task.'))
const resumeContextChecks = {
  original_user_prompt_first: resumedMessages[0]?.role === 'user'
    && messageText(resumedMessages[0]).includes('Execute the deterministic provider instructions'),
  completed_call_present: firstCallIndex >= 0,
  completed_result_present: firstResultIndex >= 0,
  dangling_call_present: crashCallIndex >= 0,
  synthetic_unknown_result_present: repairResultIndex >= 0,
  followup_prompt_last: followupIndex === resumedMessages.length - 1,
  repaired_context_ordered: firstCallIndex < firstResultIndex
    && firstResultIndex < crashCallIndex
    && crashCallIndex < repairResultIndex
    && repairResultIndex < followupIndex,
}
const output = {
  session_id: sessionIdRaw,
  before_followup_event_types: beforeFollowup.map(event => event.type),
  after_followup_event_types: afterFollowup.map(event => event.type),
  request_messages: requestMessages,
  final_messages: handle.agent.session.deriveMessages(),
  bash_probe: {
    registered: ctx.tools.get('bash') !== undefined,
    invocations: bashProbeInvocations,
  },
  resume_context_checks: resumeContextChecks,
}
const bashProbeRegistered = ctx.tools.get('bash') !== undefined
const resumeContextComplete = Object.values(resumeContextChecks).every(Boolean)
await writeFile(resolve(outputPath), `${JSON.stringify(output, null, 2)}\n`, 'utf8')
await handle.dispose()
await ctx.fiber.dispose()
console.log(JSON.stringify({
  final_response: 'COMPLETED_W9_CRASH_RESUME',
  model_calls: adapter.requests.length,
  bash_probe_registered: bashProbeRegistered,
  bash_probe_invocations: bashProbeInvocations,
  resume_context_complete: resumeContextComplete,
}))
