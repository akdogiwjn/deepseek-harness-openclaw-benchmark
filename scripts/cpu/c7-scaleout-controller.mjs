#!/usr/bin/env node
/** C7 concurrent multi-process DSH Agent controller. */

import { execFile } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

function positiveInteger(raw, name) {
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`)
  return value
}

const agents = positiveInteger(process.argv[2], 'agents')
const toolSteps = positiveInteger(process.argv[3] ?? '64', 'tool-steps')
const payloadBytes = positiveInteger(process.argv[4] ?? '64', 'payload-bytes')
const fixture = join(dirname(fileURLToPath(import.meta.url)), 'c1-agent-loop.mjs')
const cpuList = (process.argv[5] ?? '').split(',').filter(Boolean).map(Number)
const placement = process.argv[6] === 'pin' ? 'pin' : 'shared'

function runAgent(index) {
  return new Promise((resolve, reject) => {
    const cpuset = placement === 'pin' ? String(cpuList[index]) : cpuList.join(',')
    execFile('taskset', ['-c', cpuset, process.execPath, fixture, String(toolSteps), String(payloadBytes)], {
      cwd: process.cwd(), env: process.env, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
    }, (error, output, errorText) => {
      if (error !== null) {
        reject(new Error(`C7 agent ${index + 1} failed: ${error.message}\n${output}\n${errorText}`))
        return
      }
      try {
        const lines = output.split(/\r?\n/).filter(Boolean)
        resolve({ index: index + 1, result: JSON.parse(lines.at(-1)), stderr: errorText })
      } catch (error) {
        reject(new Error(`C7 agent ${index + 1} emitted invalid JSON: ${error.message}\n${output}`))
      }
    })
  })
}

const beforeCpu = process.cpuUsage()
const started = process.hrtime.bigint()
const children = await Promise.all(Array.from({ length: agents }, (_, index) => runAgent(index)))
const ended = process.hrtime.bigint()
const cpu = process.cpuUsage(beforeCpu)
const wallNs = Number(ended - started)
const totalToolSteps = agents * toolSteps
const checks = {
  agent_count_exact: children.length === agents,
  child_stderr_empty: children.every(child => child.stderr === ''),
  child_checks_all: children.every(child => Object.values(child.result.checks).every(Boolean)),
  child_tool_steps_exact: children.every(child => child.result.tool_steps === toolSteps),
  child_provider_requests_exact: children.every(child => child.result.provider_requests === toolSteps + 1),
  total_tool_steps_exact: children.reduce((sum, child) => sum + child.result.tool_invocations, 0) === totalToolSteps,
}
if (!Object.values(checks).every(Boolean)) throw new Error(`C7 invariant failure: ${JSON.stringify(checks)}`)

const resources = process.resourceUsage()
console.log(JSON.stringify({
  benchmark: 'C7 multi-process DSH Agent scale-out',
  agents, tool_steps_per_agent: toolSteps, payload_bytes: payloadBytes,
  total_tool_steps: totalToolSteps,
  total_provider_requests: agents * (toolSteps + 1),
  placement,
  cpu_binding: cpuList.slice(0, agents),
  hard_pin: placement === 'pin',
  timing: {
    wall_ns: wallNs,
    controller_cpu_user_us: cpu.user,
    controller_cpu_system_us: cpu.system,
    controller_cpu_total_us: cpu.user + cpu.system,
    agents_per_second: agents * 1e9 / wallNs,
    tool_steps_per_second: totalToolSteps * 1e9 / wallNs,
  },
  memory: {
    controller_max_rss_kb: resources.maxRSS,
    sum_child_max_rss_kb: children.reduce((sum, child) => sum + child.result.resources.max_rss_kb, 0),
    max_child_max_rss_kb: Math.max(...children.map(child => child.result.resources.max_rss_kb)),
  },
  child_internal_wall_ns: children.map(child => child.result.timing.wall_ns),
  child_internal_cpu_us: children.map(child => child.result.timing.cpu_total_us),
  checks,
}))