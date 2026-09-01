#!/usr/bin/env node
/** Deterministic W9-B live SessionStore fork semantics fixture. */

import { writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { Context } from '../sources/deepseek-harness/vendor/cordis/lib/index.js'
import SessionStore, {
  SessionForkError,
  SessionId,
} from '../sources/deepseek-harness/packages/core/session/lib/index.js'
import { createUserMessage } from '../sources/deepseek-harness/packages/llm/llm/lib/index.js'

function appendTurn(session, turn, text) {
  session.append('turn/start', { turn })
  session.append('user/message', createUserMessage({
    content: [{ type: 'text', text }],
    source: { kind: 'user' },
  }), { surfaceOp: 'append' })
  session.append('turn/end', { turn, reason: { kind: 'completed' } })
}

function normalizeMessages(messages) {
  return messages.map(message => ({
    role: message.role,
    content: message.content,
    source: message.source,
  }))
}

const outputPath = process.argv[2]
if (outputPath === undefined) {
  throw new Error('usage: run-w9-fork.mjs <output-json>')
}

const ctx = new Context()
await ctx.plugin(SessionStore)
const parent = ctx.sessions.create(SessionId('w9-parent'), {
  meta: { cwd: '/deterministic/w9-workspace' },
})
appendTurn(parent, 1, 'SEED_TURN_1')
appendTurn(parent, 2, 'SEED_TURN_2')
const boundary = parent.events.at(-1).seq
const parentPrefix = structuredClone(parent.events)
const prefixMessages = normalizeMessages(parent.deriveMessages())

const child = ctx.sessions.fork(parent, boundary, SessionId('w9-child'))
const childSeed = child.events.slice(0, -1)
const childAtForkMessages = normalizeMessages(child.deriveMessages())

appendTurn(parent, 3, 'PARENT_ONLY')
appendTurn(child, 3, 'CHILD_ONLY')

const open = ctx.sessions.create(SessionId('w9-open'))
open.append('turn/start', { turn: 1 })
let openTurnRejection
try {
  ctx.sessions.fork(open, open.events.at(-1).seq, SessionId('w9-invalid-child'))
  throw new Error('fork inside open turn unexpectedly succeeded')
} catch (error) {
  if (!(error instanceof SessionForkError)) throw error
  openTurnRejection = { code: error.code, message: error.message }
}

const checks = {
  parent_prefix_equals_child_seed: JSON.stringify(parentPrefix) === JSON.stringify(childSeed),
  parent_lineage_recorded: child.header.parentSession === parent.id,
  seed_length_exact: child.header.seedLength === parentPrefix.length,
  cwd_preserved: child.header.cwd === parent.header.cwd,
  end_seed_after_prefix: child.events[parentPrefix.length]?.type === 'session/end-seed',
  derive_messages_equal_at_boundary: JSON.stringify(prefixMessages) === JSON.stringify(childAtForkMessages),
  parent_does_not_contain_child_only: !JSON.stringify(parent.events).includes('CHILD_ONLY'),
  child_does_not_contain_parent_only: !JSON.stringify(child.events).includes('PARENT_ONLY'),
  open_turn_rejected: openTurnRejection.code === 'OPEN_TURN',
}
if (!Object.values(checks).every(Boolean)) {
  throw new Error(`W9 fork checks failed: ${JSON.stringify(checks)}`)
}

const output = {
  scenario: 'W9-B fork',
  boundary,
  parent_header: {
    id: parent.header.id,
    cwd: parent.header.cwd,
  },
  child_header: {
    id: child.header.id,
    cwd: child.header.cwd,
    parentSession: child.header.parentSession,
    seedLength: child.header.seedLength,
  },
  parent_prefix_length: parentPrefix.length,
  child_first_live_seq: child.firstLiveSeq,
  open_turn_rejection: openTurnRejection,
  parent_messages: normalizeMessages(parent.deriveMessages()),
  child_messages: normalizeMessages(child.deriveMessages()),
  checks,
}
await writeFile(resolve(outputPath), `${JSON.stringify(output, null, 2)}\n`, 'utf8')
console.log(JSON.stringify(output))
