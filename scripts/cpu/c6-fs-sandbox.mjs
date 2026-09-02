#!/usr/bin/env node
/** C6 DSH local-vs-sandbox filesystem capability CPU fixture. */

import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { Context } from '../../sources/deepseek-harness/vendor/cordis/lib/index.js'
import SessionProjectionRegistry from '../../sources/deepseek-harness/packages/session/session-projection/lib/index.js'
import SandboxPolicyService from '../../sources/deepseek-harness/packages/sandbox/sandbox-policy/lib/index.js'
import LocalFileSystem from '../../sources/deepseek-harness/packages/fs/fs-local/lib/index.js'
import SandboxedFileSystem from '../../sources/deepseek-harness/packages/fs/fs-sandbox/lib/index.js'

function positiveInteger(raw, name) {
  const value = Number(raw)
  if (!Number.isSafeInteger(value) || value < 1) throw new Error(`${name} must be a positive integer`)
  return value
}

const backend = process.argv[2]
const workload = process.argv[3]
if (backend !== 'local' && backend !== 'sandbox') throw new Error('backend must be local or sandbox')
if (workload !== 'read' && workload !== 'write') throw new Error('workload must be read or write')
const operations = positiveInteger(process.argv[4], 'operations')
const payloadBytes = positiveInteger(process.argv[5] ?? '256', 'payload-bytes')

// Keep the workspace outside platform temporary roots so workspace-write
// containment genuinely reaches the configured workspace root.
const workspace = await mkdtemp(join(process.cwd(), '.c6-fs-workspace-'))
const targetPath = join(workspace, 'fixture.txt')
const initialPayload = 'i'.repeat(payloadBytes)
await writeFile(targetPath, initialPayload)

const ctx = new Context()
await ctx.plugin(SessionProjectionRegistry)
await ctx.plugin(SandboxPolicyService, { mode: 'workspace-write', workspaceRoot: workspace })
if (backend === 'local') await ctx.plugin(LocalFileSystem, { cwd: workspace })
else await ctx.plugin(SandboxedFileSystem, { cwd: workspace })

let checksum = 0
const beforeCpu = process.cpuUsage()
const beforeResource = process.resourceUsage()
const started = process.hrtime.bigint()
if (workload === 'read') {
  for (let index = 0; index < operations; index += 1) {
    const target = await ctx.fs.resolve('fixture.txt')
    const info = await ctx.fs.stat(target)
    const text = await ctx.fs.readText(target)
    checksum += (info?.size ?? -1) + text.length
  }
} else {
  for (let index = 0; index < operations; index += 1) {
    const prefix = `C6_${String(index).padStart(8, '0')}:`
    const content = prefix + String(index % 10).repeat(Math.max(0, payloadBytes - prefix.length))
    const target = await ctx.fs.resolve('fixture.txt')
    const outcome = await ctx.fs.writeText(target, content)
    checksum += outcome.after.length
  }
}
const ended = process.hrtime.bigint()
const cpu = process.cpuUsage(beforeCpu)
const afterResource = process.resourceUsage()

const finalContent = await readFile(targetPath, 'utf8')
const expectedReadChecksum = operations * payloadBytes * 2
const finalPrefix = `C6_${String(operations - 1).padStart(8, '0')}:`
const expectedFinal = finalPrefix + String((operations - 1) % 10).repeat(Math.max(0, payloadBytes - finalPrefix.length))
const checks = {
  backend_identity_exact: backend === 'local'
    ? ctx.fs instanceof LocalFileSystem && !(ctx.fs instanceof SandboxedFileSystem)
    : ctx.fs instanceof SandboxedFileSystem && ctx.fs.sandboxMode === 'workspace-write',
  checksum_exact: workload === 'read' ? checksum === expectedReadChecksum : checksum === operations * payloadBytes,
  final_content_exact: finalContent === (workload === 'read' ? initialPayload : expectedFinal),
  workspace_outside_platform_tmp: !workspace.startsWith('/tmp/'),
}
if (!Object.values(checks).every(Boolean)) throw new Error(`C6 invariant failure: ${JSON.stringify({ checks, checksum })}`)

const wallNs = Number(ended - started)
const cpuTotalUs = cpu.user + cpu.system
console.log(JSON.stringify({
  benchmark: 'C6 DSH filesystem sandbox capability scaling', backend, workload, operations,
  payload_bytes: payloadBytes, checksum,
  timing: { wall_ns: wallNs, wall_ns_per_operation: wallNs / operations,
    cpu_user_us: cpu.user, cpu_system_us: cpu.system, cpu_total_us: cpuTotalUs,
    cpu_us_per_operation: cpuTotalUs / operations },
  resources: { max_rss_kb: afterResource.maxRSS,
    minor_page_faults_delta: afterResource.minorPageFault - beforeResource.minorPageFault,
    major_page_faults_delta: afterResource.majorPageFault - beforeResource.majorPageFault,
    voluntary_context_switches_delta: afterResource.voluntaryContextSwitches - beforeResource.voluntaryContextSwitches,
    involuntary_context_switches_delta: afterResource.involuntaryContextSwitches - beforeResource.involuntaryContextSwitches },
  checks,
}))

await ctx.fiber.dispose()
await rm(workspace, { recursive: true, force: true })
