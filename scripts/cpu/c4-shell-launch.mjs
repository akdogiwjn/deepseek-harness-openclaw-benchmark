#!/usr/bin/env node
/** C4 shell lifecycle fixture: DSH managed one-shot, raw spawn, persistent bash. */

import { spawn } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createInterface } from 'node:readline'
import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
import LocalSubprocessRuntime from '../../sources/deepseek-harness/packages/subprocess/subprocess-local/lib/index.js'
import { LocalBashExecutor } from '../../sources/deepseek-harness/packages/shell/bash-local/lib/index.js'

const CONDITIONS = new Set(['dsh-managed', 'raw-oneshot', 'persistent'])

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
      controller_cpu_user_us: cpu.user,
      controller_cpu_system_us: cpu.system,
      controller_cpu_total_us: cpu.user + cpu.system,
    },
  }
}

function marker(index) {
  return `C4_${String(index).padStart(8, '0')}`
}

function command(index) {
  return `:; printf '${marker(index)}\\n'`
}

async function rawOneShot(source) {
  return await new Promise((resolve, reject) => {
    const child = spawn('bash', ['--noprofile', '--norc', '-c', source], {
      cwd: process.cwd(),
      env: { ...process.env, NO_COLOR: '1', TERM: 'dumb', PAGER: 'cat', GIT_PAGER: 'cat' },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const stdout = []
    const stderr = []
    child.stdout.on('data', chunk => stdout.push(chunk))
    child.stderr.on('data', chunk => stderr.push(chunk))
    child.on('error', reject)
    child.on('close', (exitCode, signal) => resolve({
      exitCode,
      signal,
      stdout: Buffer.concat(stdout).toString('utf8'),
      stderr: Buffer.concat(stderr).toString('utf8'),
    }))
  })
}

async function runDsh(count, spillDir) {
  const ctx = new Context()
  await ctx.plugin(LocalSubprocessRuntime)
  ctx.subprocess.internals = { spillDir }
  await ctx.plugin(LocalBashExecutor, {
    cwd: process.cwd(),
    timeoutMs: 30_000,
    maxTimeoutMs: 30_000,
    maxOutputBytes: 4096,
    maxSpillBytes: 4096,
    graceMs: 200,
  })
  const outputs = []
  const measured = await measure(async () => {
    for (let index = 1; index <= count; index += 1) {
      const result = await ctx.shell.run(ctx.shell.resolve({ command: command(index) }))
      outputs.push({ exitCode: result.exitCode, signal: result.signal, stdout: result.stdout.text, stderr: result.stderr.text })
    }
  })
  await ctx.fiber.dispose()
  return { outputs, measurement: measured.measurement, setup: 'DSH LocalBashExecutor + LocalSubprocessRuntime' }
}

async function runRaw(count) {
  const outputs = []
  const measured = await measure(async () => {
    for (let index = 1; index <= count; index += 1) outputs.push(await rawOneShot(command(index)))
  })
  return { outputs, measurement: measured.measurement, setup: 'node:child_process spawn per command' }
}

async function runPersistent(count) {
  const child = spawn('bash', ['--noprofile', '--norc'], {
    cwd: process.cwd(),
    env: { ...process.env, NO_COLOR: '1', TERM: 'dumb', PAGER: 'cat', GIT_PAGER: 'cat' },
    stdio: ['pipe', 'pipe', 'pipe'],
  })
  const lines = createInterface({ input: child.stdout, crlfDelay: Infinity })[Symbol.asyncIterator]()
  let stderr = ''
  child.stderr.setEncoding('utf8')
  child.stderr.on('data', chunk => { stderr += chunk })
  const startup = await measure(async () => {
    child.stdin.write("printf 'C4_READY\\n'\n")
    return await lines.next()
  })
  if (startup.value.done || startup.value.value !== 'C4_READY') throw new Error('persistent shell readiness failed')

  const outputs = []
  const measured = await measure(async () => {
    for (let index = 1; index <= count; index += 1) {
      child.stdin.write(`${command(index)}\n`)
      const line = await lines.next()
      outputs.push({ exitCode: null, signal: null, stdout: line.value === undefined ? '' : `${line.value}\n`, stderr: '' })
    }
  })
  child.stdin.end('exit\n')
  const exit = await new Promise((resolve, reject) => {
    child.on('error', reject)
    child.on('close', (exitCode, signal) => resolve({ exitCode, signal }))
  })
  return {
    outputs,
    measurement: measured.measurement,
    startup: startup.measurement,
    exit,
    persistent_stderr: stderr,
    setup: 'one node:child_process bash with line-framed acknowledgements',
  }
}

const condition = process.argv[2]
if (!CONDITIONS.has(condition)) throw new Error(`condition must be one of: ${[...CONDITIONS].join(', ')}`)
const operations = positiveInteger(process.argv[3], 'operations')
const spillDir = await mkdtemp(join(tmpdir(), 'dsh-c4-spill-'))
try {
  const result = condition === 'dsh-managed'
    ? await runDsh(operations, spillDir)
    : condition === 'raw-oneshot'
      ? await runRaw(operations)
      : await runPersistent(operations)
  const checks = {
    output_count_exact: result.outputs.length === operations,
    markers_exact: result.outputs.every((output, index) => output.stdout === `${marker(index + 1)}\n`),
    stderr_empty: result.outputs.every(output => output.stderr === '') && (result.persistent_stderr ?? '') === '',
    exits_successful: condition === 'persistent'
      ? result.exit?.exitCode === 0 && result.exit.signal === null
      : result.outputs.every(output => output.exitCode === 0 && output.signal === null),
  }
  if (!Object.values(checks).every(Boolean)) throw new Error(`C4 invariant failure: ${JSON.stringify(checks)}`)
  const resources = process.resourceUsage()
  console.log(JSON.stringify({
    benchmark: 'C4 shell lifecycle scaling',
    condition,
    operations,
    command_shape: "bash no-op builtin followed by one fixed-width acknowledgement",
    setup: result.setup,
    measurement: {
      ...result.measurement,
      wall_ns_per_operation: result.measurement.wall_ns / operations,
      controller_cpu_us_per_operation: result.measurement.controller_cpu_total_us / operations,
    },
    ...result.startup === undefined ? {} : { persistent_startup: result.startup },
    resources: {
      max_rss_kb: resources.maxRSS,
      minor_page_faults: resources.minorPageFault,
      major_page_faults: resources.majorPageFault,
      voluntary_context_switches: resources.voluntaryContextSwitches,
      involuntary_context_switches: resources.involuntaryContextSwitches,
    },
    checks,
  }))
} finally {
  await rm(spillDir, { recursive: true, force: true })
}
