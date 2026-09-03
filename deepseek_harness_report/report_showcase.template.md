# DeepSeek Harness 技术展示版：从 Runtime 设计到可验证机制

> 面向第一次接触本项目的技术读者：先理解 Harness 负责什么，再看 DeepSeek Harness 如何组织状态与执行，最后用 W1–W10 和 C1–C8 说明这些机制如何被验证。

## 0. 一页看懂 DeepSeek Harness

### 0.1 这份调研想解决什么问题

DeepSeek Harness 是 DeepSeek 推出的开源 Agent Harness。本次调研不评价 DeepSeek 模型本身，而是研究 Harness 如何组织 Agent 的状态、工具、Context 和执行过程。我们选择 OpenClaw 作为参照，通过真实 Agent 任务与确定性机制实验，观察两套 pinned Runtime 的可见差异，再进一步拆解这些机制给 Host CPU 带来的本地工作。

这里的“核心设计”或“值得关注的新机制”，是指 DeepSeek Harness 当前版本重点采用、显式建模或提升为一等 Runtime 能力的设计，并不表示这些概念均由 DeepSeek 在整个 Agent 生态中首次发明。OpenClaw 已经具备 Session、Transcript、Context Compaction 和 Sandbox 等能力；本报告关注的是 DSH 如何重新组织这些能力、显式暴露哪些边界，以及这种组织如何改变状态与执行模型。

### 0.2 最值得关注的四个设计

| DeepSeek Harness 核心设计 | 一句话解释 | 最主要证据 |
|---|---|---|
| Everything is a Plugin | Runtime 能力通过 composition 和 capability/provider 组织，而不是全部固定在 Agent Loop 中 | W10 |
| Session Event Log | Session 被显式建模成执行事件流，Model Context 从这条状态流派生 | W9 |
| Context Management | Context 计量与 Compaction 被组织成可组合 Runtime capability | W5 |
| Code Mode / PTC | 多个模型可见 Tool Round Trip 可以折叠为一次 Program Execution | W8 |

**额外机制洞察。** W4/W6 表明，Harness 在什么边界结构化错误，会直接影响 Agent 是否获得下一次修复机会。Recovery 因此是本研究观察到的 Runtime semantics，不是第五个官方 Feature。

### 0.3 一句话结论

> DeepSeek Harness 值得关注的地方不是简单增加了更多 Agent 功能，而是把原本分散的状态、执行和能力边界进一步显式化，并通过统一 composition 组织起来。

---

## 1. Harness 到底负责什么

假设用户要求“修复一个 Python Bug，并运行测试验证”。模型负责理解任务、根据观察规划下一步；Harness 则把这些决定变成真实执行：调用模型、运行 `pytest`、保存 Tool Result、读取和修改文件、再次验证，并维护跨步骤的 Session 与 Context。

```text
用户任务
  ↓
Model：决定先运行测试
  ↓
Harness：执行 pytest，记录 Tool Result
  ↓
Model：根据报错决定读取源码并生成修改
  ↓
Harness：读取 / 写入文件，重新测试，保存 Session
```

| Model 主要负责 | Harness 主要负责 |
|---|---|
| 理解任务、推理和规划 | Model 调用与 Agent Loop |
| 决定下一步和调用什么 Tool | Tool Dispatch 与 Error Handling |
| 生成代码、文本或参数 | Session、Context 与持久化 |
| 根据观察调整计划 | Filesystem、Process、Code Runtime 与 Policy |

下面这张图主要看 Model 与 Harness 的职责边界：Model 位于决策路径，Harness 位于编排中心，并连接状态平面和执行平面。

<p align="center"><img src="figures/architecture/harness-model.svg" width="900" alt="Model 决策、Harness 编排并连接状态与执行平面"></p>
<p align="center"><sub>图 1-1　DeepSeek Harness 的重点变化发生在 Runtime 执行层，而不是模型推理能力本身。</sub></p>

后文出现的 Session、Context、Provider 和 PTC 都属于这条 Harness 路径。先建立这个边界，可以避免把 Runtime 的恢复、持久化或进程行为误认为“模型能力”。

---

## 2. 这次我们做了哪些实验

### 2.1 为什么分成三层

```text
真实 Agent 任务 W1–W3
        ↓ 发现行为与失败现象
确定性机制实验 W4–W8
        ↓ 隔离具体 Runtime 机制
DSH 白盒实验 W9–W10
        ↓ 验证显式 API / capability seam
CPU Microbenchmark C1–C8
        ↓ 拆解 Host CPU 工作
```

真实任务接近实际使用，但模型输出、网络与执行路径会引入大量变量，因此适合发现现象，不适合单独解释原因。W4–W8 使用 deterministic provider 或固定输入隔离单个机制；W9–W10 直接验证 DSH 的 Session 和 filesystem capability。确认机制后，C1–C8 再去掉真实模型网络延迟，测量 Host 侧工作。

### 2.2 Harness 行为实验 W1–W10

| 实验 | 测试内容 | 为什么做 | 主要回答的问题 | 主要结果 |
|---|---|---|---|---|
| W1 | Exact File Edit | 最基础 smoke test | 是否能完成明确、可验证的文件修改 | {{W1_SUMMARY}} |
| W2 | Python Bug Fix | 小型真实 Coding Task | 是否具备读代码、修改、测试和验证闭环 | DSH {{W2_DSH_SUCCESS}}/{{W2_DSH_TOTAL}}；OpenClaw {{W2_OPENCLAW_SUCCESS}}/{{W2_OPENCLAW_TOTAL}} |
| W3 | Multi-module Feature | 更长的真实执行链 | 是否出现值得进一步隔离的稳定性现象 | DSH {{W3_DSH_SUCCESS}}/{{W3_DSH_TOTAL}}；OpenClaw {{W3_OPENCLAW_SUCCESS}}/{{W3_OPENCLAW_TOTAL}}，观察到 `incomplete_turn` |
| W4 | Malformed Tool Call | 固定坏 provider event | 错误被结构化并继续，还是终止 Turn | {{W4_SUMMARY}} |
| W5 | Automatic Compaction | 固定长 Tool Result | Compaction 如何触发，之后能否继续 | {{W5_SUMMARY}} |
| W6 | Tool Failure | 固定 invalid args / exit {{W6_CHILD_EXIT_CODE}} | 普通 Tool Failure 与 malformed event 是否同一边界 | {{W6_SUMMARY}} |
| W7 | Long Tool Chain | 连续 {{W7_TOOL_CALLS}} 次 Tool Call | Context、request body 与 Tool state 如何累积 | {{W7_SUMMARY}} |
| W8 | Direct vs PTC | 相同 {{W8_OPERATIONS}} 个底层操作 | request 下降是否来自编排折叠，而非漏做工作 | DSH provider requests {{W8_DSH_DIRECT_REQUESTS}}→{{W8_DSH_CODE_REQUESTS}}，底层操作仍为 {{W8_OPERATIONS}} |
| W9 | Resume / Fork / Replay | DSH Session 白盒实验 | Event Log 如何支持恢复、分支和重放 | {{W9_SUMMARY}} |
| W10 | Filesystem Seam | `local → sandbox → local` | capability/provider 是否为可观察边界 | {{W10_SUMMARY}} |

W1–W3 是真实 Agent workload；W4–W8 是 deterministic mechanism tests；W9–W10 是 DSH white-box mechanism tests。W9/W10 没有完全对等的 OpenClaw fixture，不能用于两套 Runtime 排名。

### 2.3 为什么 W3 之后需要 W4

W1 只验证最基础的 exact edit。W2 是 `Retry-After` parser Bug：Agent 需要运行测试、阅读代码、修改实现并再次验证，DSH 完成 {{W2_DSH_SUCCESS}}/{{W2_DSH_TOTAL}}，OpenClaw 完成 {{W2_OPENCLAW_SUCCESS}}/{{W2_OPENCLAW_TOTAL}}。样本数只有 {{W2_DSH_TOTAL}}，wall-time 分布也不用于性能排名。

W3 要在多个 Python 模块中增加 weighted atomic quota consumption 并补充测试，执行链更长。DSH 完成 {{W3_DSH_SUCCESS}}/{{W3_DSH_TOTAL}}，OpenClaw 完成 {{W3_OPENCLAW_SUCCESS}}/{{W3_OPENCLAW_TOTAL}}；部分失败表现为 `incomplete_turn`。这只能说明真实任务里观察到了差异，不能说明差异一定来自某个 Harness Feature。因此 W4 固定 malformed provider event，只观察 Recovery Path。

### 2.4 CPU 实验 C1–C8

| 实验 | 测什么 | 对应 Runtime 工作 |
|---|---|---|
| C1 | Agent Loop 随 Tool Step 增长 | Control Plane |
| C2 | Event append、derive、fork、persist、load | State Plane |
| C3 | Context JSON encode/decode 与 SSE parsing | State / Serialization |
| C4 | Managed、one-shot 与 persistent process | Process / Tool Boundary |
| C5 | Native Tool Calling 与 PTC | Execution Granularity |
| C6 | Local FS 与 Sandbox FS Policy | Capability / Policy |
| C7 | 1→{{C7_AGENT_COUNT}} 个独立 Agent | Multi-Agent Scale |
| C8 | TokenMeter / Context Pressure | Context Management |

这一章只建立实验地图，具体数字集中在第 10 章，避免 CPU 抢占 Harness 机制主线。

---

## 3. Everything is a Plugin：把 Runtime 能力变成可组合边界

### 3.1 它解决什么问题

一个 Agent Runtime 同时包含模型调用、工具、文件系统、Session、Context、Sandbox 与 Code Runtime。如果这些能力全部直接固定在 Agent Loop 内部，更换文件系统策略或执行环境时会影响上层调用路径。DSH 希望把“使用能力的组件”和“真正实现能力的组件”分开。

**Provider** 是某项 Runtime capability 的具体实现。Consumer 只依赖稳定 Capability / Service，启动时的 composition 决定实际 Provider：

```text
Consumer → Capability / Service → Provider
tool-fs  → ctx.fs              → fs-local / fs-sandbox
```

### 3.2 Profile、Bundle、Patch 与 Cordis

第一次看这张图只需要沿垂直方向阅读：Profile 选择有序 Bundle，Patch 覆盖配置，最终形成 Plugin Tree，并注册 `ctx.*` services。

<p align="center"><img src="figures/architecture/composition-tree.svg" width="900" alt="Profile、Bundle、Patch 和 Cordis Plugin Tree 的组合关系"></p>
<p align="center"><sub>图 3-1　Everything is a Plugin 不只是源码拆模块；Runtime 在启动阶段由 composition 形成。</sub></p>

- **Profile**：一套命名的 Runtime composition；
- **Bundle**：按顺序加载的一组 Cordis 配置与插件代码；
- **Patch**：来自 profile、home 或 CLI 的覆盖层；
- **Cordis**：承载插件生命周期与 service 注册的 composition framework；
- **`ctx.*`**：插件获取稳定 service/capability 的接口，例如 `ctx.fs`、`ctx.sessions`。

插件化与依赖注入不是 DeepSeek 首创。这里值得关注的是，DSH 把 Model、Session、Tool、Agent Loop 等 Runtime 子系统统一放进同一 composition 模型。

### 3.3 `ctx.fs` 与 W10

这张图主要看中间的 `ctx.fs`：面向模型的 `tool-fs` 不变，下面的 Provider 可以换成 local 或 sandbox。

<p align="center"><img src="figures/architecture/capability-seam.svg" width="900" alt="tool-fs 通过 ctx.fs 使用 local 或 sandbox Provider"></p>
<p align="center"><sub>图 3-2　Consumer 与 Provider 分离后，替换实现可以改变 Policy，而不改上层 Tool 调用。</sub></p>

**测试目的。** 验证架构文档中的 `ctx.fs` 是否真的是可替换 Provider Boundary。

**测试方法。** 保持 Agent Loop、`tool-fs` 和 scripted calls 不变，只执行 `fs-local → fs-sandbox → fs-local`。

| Provider | workspace 内写入 | workspace 外写入 |
|---|---|---|
| fs-local | 成功 | `{{W10_LOCAL_OUTSIDE}}` |
| fs-sandbox | 成功 | `{{W10_SANDBOX_ERROR}}` |
| 再切回 fs-local | 成功 | 行为恢复：{{W10_SWAP_RESTORED}} |

**实际结论。** 当前 pinned revision 中，`ctx.fs` 的 Provider replacement 会改变真实 filesystem policy。W10 只直接证明这一条 seam，不泛化为所有 capability 均已验证。Policy 对 Host CPU 的成本统一在第 10 章讨论。

---

## 4. Session Event Log：把 Session 建模成执行状态

### 4.1 Model Messages 与 Runtime State

成熟 Agent Runtime 原本就会持久化 Session、Tool Result 或 Transcript。DSH 值得关注的地方，是把 **Session Event Log**——按顺序追加的 typed execution events——明确作为 Session 的核心状态模型，并要求模型输入能够从这条日志派生和重建。

| Model Messages 更关心 | Session Event Log 更关心 |
|---|---|
| 模型下一次需要看到什么 | Runtime 实际发生过什么 |
| user / assistant / tool history | turn、step、tool call/result 与 lifecycle event |
| Model Context | Durable Execution State |

`deriveMessages()` 把 Event Log 投影为 Model Context。当前准备发送给模型的 model-visible Context，后文简称 **surface**。

### 4.2 Turn、Step 与事件流

**Step** 是一次 Model Request 以及由它产生的 Tool Calls；**Turn** 是一次输入触发的整段执行，可以包含多个 Step。例如第一步运行测试并获得错误，第二步读取源码或提交修改，二者属于同一个 Turn 中的不同 Step。

下面这张图先看 Turn 内的 Step，再沿箭头进入 Event Log，最后看同一条日志如何支撑 Context、Resume、Fork 和 Replay。

<p align="center"><img src="figures/architecture/event-log.svg" width="940" alt="Turn、Step、typed events 与 Session Event Log 派生能力"></p>
<p align="center"><sub>图 4-1　Model Context 是 durable event stream 的 projection；恢复、分叉和重放依赖明确的日志边界。</sub></p>

### 4.3 W9：Resume、Fork、Replay

**测试目的。** 验证 Event Log 是否真的形成可持久化、可分支、可重放的执行状态，而不只是概念模型。

**测试方法。** W9-A 在 `tool/call` 已持久化、`tool/result` 尚未出现时终止进程；W9-B 从 closed-turn boundary 创建 child；W9-C 禁用 live LLM provider，使用记录的 model stream replay。

**实验事实。** Crash/Resume 中 committed prefix 保持不变：{{W9_PREFIX_IDENTICAL}}；dangling call 未自动 dispatch：{{W9_DANGLING_NOT_DISPATCHED}}；Runtime 注入 `{{W9_SYNTHETIC_ERROR}}`，关闭 interrupted turn，再从新 turn 继续。对有外部副作用的 Tool，这避免了在结果未知时盲目重复执行。

Fork 中 Parent 与 Child 在稳定边界的 derived messages 相等：{{W9_FORK_EQUAL}}，之后可以独立追加。Replay 未访问 live provider：{{W9_PROVIDER_NOT_CONTACTED}}，但只重建记录的 model stream/execution projection，不重放外部副作用。

**实际结论。** W9 验证的是当前 DSH API 的具体 semantics。OpenClaw 也存在 Session/Transcript persistence，但本仓库没有完全对等的 OpenClaw W9，不能做有/没有式判断。Event Log 的 Host 状态成本见第 10.1 节。

---

## 5. Context Management：把长 Context 治理放进 Runtime

### 5.1 为什么 Harness 要管理 Context

长期 Agent 会持续累积 user、assistant、Tool Call 和 Tool Result。Runtime 必须判断当前 surface 有多大、是否接近预算、哪些信息可以压缩，以及压缩后如何保持下一轮 Model Context 有效。OpenClaw 等 Harness 已经具有 Context Compaction；研究重点不是“DSH 第一次会压缩”，而是 DSH 如何把 TokenMeter 与 Compaction 组织成可组合 Runtime capability。

**TokenMeter** 评估当前 model-visible surface 的压力。**Compaction** 在达到策略边界后生成更小的 Context 表示。`sdk-minimal` 默认没有 automatic compaction；W5 显式加载 `token-meter + compaction-basic`。

下面这张图主要看 pressure check 的两条分支，以及 TokenMeter/Compaction 是可选 composition，而非 minimal profile 的隐含能力。

<p align="center"><img src="figures/architecture/context-management.svg" width="900" alt="Session projection、TokenMeter、Pressure Check 与 Compaction 路径"></p>
<p align="center"><sub>图 5-1　Context Management 把计量、策略判断和压缩结果放入 Runtime lifecycle。</sub></p>

### 5.2 W5：压缩能否触发并继续

**测试目的。** 验证 Context 增长后 Compaction 是否真实触发，以及压缩后 Agent 能否继续执行。

**测试方法。** 使用 deterministic tool chain、较大 Tool Result 与固定 summarizer，记录 Agent Request、Compaction Request 和 boundary 前后 body bytes。

W5 的 DSH fixture 包含 {{W5_DSH_TOOL_CALLS}} 次 Tool Call、{{W5_DSH_COMPACTIONS}} 次 Compaction，最终完成：{{W5_DSH_COMPLETED}}。

| Boundary | 压缩前 Agent body | 压缩后 Agent body | 下降 |
|---|---:|---:|---:|
{{W5_BOUNDARY_ROWS}}

**实际结论。** 三个 boundary 后 body 均缩小，任务继续完成。OpenClaw 在校准 fixture 中也记录到 {{W5_OPENCLAW_COMPACTIONS}} 次 Compaction，因此 W5 不是证明 DSH“有而 OpenClaw 没有”，而是观察两种 Runtime 的 Context shaping 路径。TokenMeter/pressure 的 CPU 数据见第 10.1 节。

---

## 6. Programmatic Tool Calling：改变 Tool 编排粒度

### 6.1 Direct 与 PTC

Direct Tool Calling 中，每个 Tool 都经过 Model Request、Tool Call、Runtime Dispatch、Tool Result、Context 重建和下一次 Model Request。**Programmatic Tool Calling（PTC）** 则让模型生成一个 Program，由本地 Runtime 在单个外层调用内连续调用多个 Tool，再把 Program Result 返回模型。

下面这张图左右采用相同起点与终点。需要关注的不是右侧 Tool 变少，而是多个 Tool 被包进一个 model-visible Program boundary。

<p align="center"><img src="figures/architecture/ptc.svg" width="900" alt="Direct Tool Calling 与 PTC 的对称执行边界"></p>
<p align="center"><sub>图 6-1　PTC 不减少底层 Tool 工作，减少的是模型层逐次暴露的 orchestration boundary。</sub></p>

让模型生成代码并在本地执行多个操作不是整个 Agent 行业首次出现。DSH 值得关注的是把 PTC 明确设计为 Runtime 的 Tool Presentation / Execution Mode，并通过正式 Code Runtime 与 Tool Pipeline 执行。

### 6.2 W8：确认没有漏做 Tool

**测试目的。** 排除“PTC request 更少只是因为少做了 Tool”的可能。

**测试方法。** 固定 {{W8_OPERATIONS}} 个底层 shell operations，要求顺序严格一致、每个恰好执行一次；Direct 让每个操作成为 model-visible call，PTC 让一个 Program dispatch 全部操作。

| DSH condition | 底层操作 | model-visible calls | provider requests |
|---|---:|---:|---:|
| Direct | {{W8_OPERATIONS}} | {{W8_DSH_DIRECT_CALLS}} | {{W8_DSH_DIRECT_REQUESTS}} |
| PTC | {{W8_OPERATIONS}} | {{W8_DSH_CODE_CALLS}} | {{W8_DSH_CODE_REQUESTS}} |

**实验事实。** DSH request body 总量下降 {{W8_DSH_BODY_REDUCTION_PCT}}%；OpenClaw 的构造对照也从 {{W8_OPENCLAW_DIRECT_REQUESTS}} 降到 {{W8_OPENCLAW_CODE_REQUESTS}} 个 provider requests，body 下降 {{W8_OPENCLAW_BODY_REDUCTION_PCT}}%。

**实际结论。** 变化来自 execution granularity，而不是漏做工作。这不是实际模型质量或端到端 task latency 提升证明；Native/PTC 的本地 CPU 成本见第 10.2 节。

---

## 7. 机制洞察：错误边界如何影响恢复

Error Recovery 本身不是 DeepSeek 首创功能。本章研究 W3/W4/W6 揭示的具体 Error Boundary Semantics：同一种失败在哪一层被结构化，会决定模型是否获得下一次修复机会。

```text
W3 真实任务观察 incomplete_turn
        ↓ 存在模型随机性等混杂变量
W4 固定 malformed provider event
        ↓ 只观察 Harness Recovery Path
W6 固定普通 Tool Failure
        ↓ 区分 provider event 与 tool execution boundary
```

下面这张图主要看固定 malformed event 穿过两套 pinned Runtime boundary 后的不同结果，而不是看一张普遍可靠性排名图。

<p align="center"><img src="figures/architecture/recovery-boundary.svg" width="900" alt="同一 malformed provider event 在两套 Runtime 中的不同 Recovery 结果"></p>
<p align="center"><sub>图 7-1　错误能否形成 model-visible observation，决定当前 Turn 是否有机会进入下一 Step。</sub></p>

### 7.1 W4 与 W6 为什么不重复

**W4 测试目的。** 固定 empty-name + truncated-arguments Tool Call，只观察 malformed provider event 的处理。

**W4 实验事实。** DSH 将其落为结构化 tool-dispatch error，并在 {{W4_DSH_REQUESTS}} 次 request 后完成：{{W4_DSH_COMPLETED}}；当前 pinned OpenClaw fixture 在 {{W4_OPENCLAW_REQUESTS}} 次 request 后以 `{{W4_OPENCLAW_ERROR}}` 终止。

**W6 测试目的。** 检查 normal Tool Error 是否也存在同样差异。测试分别固定 missing required argument 与 child exit {{W6_CHILD_EXIT_CODE}}；{{W6_SUMMARY}}。

**实际结论。** malformed provider event 与 valid Tool Failure 位于不同错误边界，不能合并成一个“Runtime 稳定性”指标。W4 只能证明两套 pinned Runtime 对固定输入的 semantics 不同，不能外推为 DSH 全面更可靠。

---

## 8. DeepSeek Harness 与 OpenClaw 的主要差异

OpenClaw 是参照 Runtime，不是被打分的“旧框架”。下表先回答两边是否都有相关能力，再说明 DSH 的组织方式与实验边界。

| 维度 | 两边都有相关能力吗 | DSH 值得关注的设计 | 当前实验实际验证 |
|---|---|---|---|
| Plugin / extensibility | 是，各有扩展路径 | everything-is-a-plugin + Cordis composition + `ctx.*` seam | W10 直接验证 `ctx.fs`，不代表所有 seam |
| Session persistence | 是 | typed append-only Event Log 作为核心 Session state | W9 验证 DSH Resume/Fork/Replay；无对等 OpenClaw W9 |
| Context Compaction | 是 | TokenMeter / Compaction 作为可组合 capability | W5 验证显式加载后的路径；预算与 estimator 不等价 |
| Tool execution | 是 | PTC 是明确的 execution model | W8 比较 direct/code condition，不作产品完整性排名 |
| Recovery | 是 | 关注 provider/tool boundary 的结构化 semantics | W4/W6 只覆盖固定 stimulus |
| Sandbox / Policy | 是 | capability/provider 可由 composition 替换 | W10 只验证 filesystem seam |

因此，本报告不支持“DSH 全面优于 OpenClaw”。它支持的是：当前 DSH 把 composition、Event Log、Context Management 与 PTC 明确提升为 Runtime 设计中心；两套 pinned Runtime 在若干固定边界上呈现可观察差异。

---

## 9. 从 Harness 设计到 Host CPU Workload

前面的 W 系列回答“Runtime 怎么工作”；下面的 C 系列回答“这些机制最终给 Host CPU 增加什么工作”。这张图是一张证据矩阵：前四行是 DSH 核心设计，后两行是补充机制或 scale workload。

<p align="center"><img src="figures/architecture/feature-to-cpu.svg" width="980" alt="Harness 机制、W 证据、Host Workload 与 C 证据矩阵"></p>
<p align="center"><sub>图 9-1　CPU 实验由已验证机制推导而来；Multi-Agent Scale 不被包装成新的 DSH Feature。</sub></p>

| Runtime Plane | 主要工作 | CPU 实验 |
|---|---|---|
| Control | Agent Loop、Recovery、Orchestration | C1 |
| State | Session、Context、Serialization、Pressure | C2 / C3 / C8 |
| Execution | Process、Code Runtime、Filesystem Policy | C4 / C5 / C6 |
| Scale | Multi-Agent Runtime Density | C7 |

CPU 分析用于说明软件机制会形成 Host workload，不是处理器排名。当前数据来自单一 {{META_HOST_MACHINE}} 主机、固定 topology 与 deterministic fixture。

---

## 10. CPU 数据得到的主要观察

**Control Plane。** C1 使用 deterministic in-process LLM 和 no-op Tool，观察 Agent Loop 随 Tool Step 增长的本地 CPU 成本。Cold fixture 从 {{C1_INITIAL_STEPS}} 增长到 {{C1_FINAL_STEPS}} steps 时，内部 CPU 时间从 {{C1_INITIAL_CPU_MS}} ms 增长到 {{C1_FINAL_CPU_MS}} ms。由于同一 append-only Session 的 Context 也随 step 增长，这表示 control-plane 与 growing-state 的组合成本，而不是纯 `while` loop overhead；因此不再增加一张独立 C1 图。

### 10.1 长生命周期 Agent 会形成扩大的状态工作集

C2 把 Session append、derive、fork、persist 和 load 的 slope 分开；C3 固定消息形状并扩大 Context Bytes；C8 区分 Cold Replay、Warm Repeat 与 Incremental pressure accounting。

<p align="center"><img src="figures/data/c2-session-cost.svg" width="940" alt="C2 Session 状态操作的每事件 CPU slope"></p>
<p align="center"><sub>图 10-1　固定 event shape 下，append slope={{C2_APPEND_CPU_US}} μs/event，deriveMessages slope={{C2_DERIVE_MESSAGES_CPU_US}} μs/event。</sub></p>

<p align="center"><img src="figures/data/c3-context-serialization.svg" width="980" alt="C3 Context 大小与 JSON、SSE 处理 CPU 时间"></p>
<p align="center"><sub>图 10-2　Context 扩大到 {{C3_MAX_CONTEXT_BYTES}} B 时，JSON encode={{C3_JSON_ENCODE_MS}} ms、decode={{C3_JSON_DECODE_MS}} ms、SSE+JSON={{C3_SSE_JSON_MS}} ms。</sub></p>

<p align="center"><img src="figures/data/c8-context-pressure.svg" width="980" alt="C8 TokenMeter Context Pressure 的 Cold 与 Warm 结果"></p>
<p align="center"><sub>图 10-3　Cold/Repeat 边际 slope 比为 {{C8_COLD_REPEAT_RATIO}}×；Incremental 使用 effective surface，不使用 initial surface。</sub></p>

**研究推断。** Long-lived Agent 更像 growing-state workload：即使没有新 event，Warm Repeat 仍随 surface 增长。但这些 slope 是当前 fixture 的 mechanism cost，不等于生产端到端 latency；C8 也不是 tokenizer benchmark。

### 10.2 Tiny Tool 下，Runtime Boundary 可能比 Tool 更显著

C4 比较 managed、raw one-shot 与 persistent process；C5 比较 Native Agent Loop 与 PTC program worker。两者共同说明，Tool 很短时，process lifecycle 与重复 orchestration boundary 可能占据显著比例。

<p align="center"><img src="figures/data/c4-process-lifecycle.svg" width="940" alt="C4 不同 Process lifecycle 的单次执行时间"></p>
<p align="center"><sub>图 10-4　{{C4_OPERATION_COUNT}} 次微操作下，managed={{C4_MANAGED}} ms/op、one-shot={{C4_RAW_ONESHOT}} ms/op、persistent control={{C4_PERSISTENT}} ms/op。</sub></p>

<p align="center"><img src="figures/data/c5-native-vs-ptc.svg" width="980" alt="C5 Native 与 PTC 随操作数增长的执行时间"></p>
<p align="center"><sub>图 10-5　PTC 有固定 worker cost；当前 crossover bracket 为 {{C5_CROSSOVER_LOW}}～{{C5_CROSSOVER_HIGH}} operations，不是生产 threshold。</sub></p>

在 {{C5_OPERATION_COUNT}} operations 点，Native={{C5_NATIVE_SELECTED_MS}} ms，PTC={{C5_PTC_SELECTED_MS}} ms。真实 provider latency、Program 生成质量与 Tool 计算都可能改变 crossover；当前结论只描述本地 execution granularity。

### 10.3 Policy 也是 Runtime 工作

W10 证明替换 `ctx.fs` provider 会改变 outside-path policy。C6 在 {{C6_OPERATION_COUNT}} 次允许写入下，记录 sandbox/local wall={{C6_WALL_RATIO_SELECTED}}×、CPU={{C6_CPU_RATIO_SELECTED}}×。C6 不是 container、seccomp、Firecracker 或远程 E2B benchmark，只说明 path normalization、containment check 和 policy decision 会形成可测 Host 工作。

### 10.4 多 Agent 变成 Runtime Density 问题

<p align="center"><img src="figures/data/c7-agent-scale.svg" width="980" alt="C7 Multi-Agent 吞吐与并行效率"></p>
<p align="center"><sub>图 10-6　{{C7_AGENT_COUNT}} Agents 达到 {{C7_SELECTED_AGENTS_PER_SECOND}} Agents/s，并行效率 {{C7_SELECTED_EFFICIENCY_PCT}}%；RSS 不增加第三个图轴。</sub></p>

该点 summed child max RSS={{C7_SELECTED_SUM_RSS_GIB}} GiB，最大单 child RSS={{C7_SELECTED_MAX_CHILD_RSS_MIB}} MiB。Scale Plane 同时关联 core、memory capacity 与 scheduler；固定单机结果不支持 ARM/x86、厂商或生产部署排名。

---

## 11. 实验证据、可信度与边界

### 11.1 三种证据等级

| 类型 | 可以复查什么 | 不能自动重建什么 |
|---|---|---|
| W1–W3 Real Workload | frozen workspace、diff、hidden verifier outcome | 完整 reasoning/provider transcript 与所有 runtime metadata |
| W4–W10 Mechanism | deterministic request、runtime artifact、机制 summary | 真实模型 workload 的总体分布 |
| C1–C8 CPU Pilot | raw samples、protocol binding、aggregate/fit 一致性 | 跨机器、跨 ISA 的普遍性能结论 |

本报告严格模式从 frozen evidence 重建 W1–W3 outcome、W4–W10 summary，并用 protocol-bound runner logic 从 C raw samples 重算 aggregate/fit。它验证 committed result 与当前 pinned logic 一致，不是对 aggregation formula 的第二套独立实现。

### 11.2 Provenance

| 项目 | 值 |
|---|---|
| 报告输入 SHA256 | `{{REPORT_INPUT_SHA256}}` |
| 生成时 Git 状态 | `{{GIT_STATUS_AT_GENERATION}}` |
| DeepSeek Harness | `{{DEEPSEEK_HARNESS_COMMIT}}` |
| OpenClaw | `{{OPENCLAW_COMMIT}}` |
| Node.js | `{{NODE_VERSION}}` |
| Host architecture | `{{META_HOST_MACHINE}}` |
| perf mode | `{{PERF_MODE}}` |
| Evidence verification | `{{EVIDENCE_VERIFICATION}}` |

### 11.3 本报告明确不声称什么

- 不声称 DeepSeek 首次发明 Plugin、Session persistence、Compaction 或 code execution；
- 不声称 DSH 全面优于 OpenClaw；
- 不把 W3 的 {{W3_DSH_SUCCESS}}/{{W3_DSH_TOTAL}} vs {{W3_OPENCLAW_SUCCESS}}/{{W3_OPENCLAW_TOTAL}} 外推为普遍可靠性排名；
- 不声称 PTC 永远更快或 {{C5_CROSSOVER_LOW}}～{{C5_CROSSOVER_HIGH}} 是生产阈值；
- 不把 Replay model stream 等同于重复外部副作用；
- 不把 C1–C8 用作 ARM/x86 或 CPU 厂商排名。

---

## 12. 总结

DeepSeek Harness 当前版本最值得研究的，不是某个孤立“新功能”，而是一套更显式的 Agent Runtime 组织方式：

1. Everything is a Plugin 把 Runtime 子系统放进统一 composition，并通过 capability/provider seam 分离 consumer 与实现；
2. Session Event Log 把 Session 建模成 durable execution state，Model Context 由日志派生；
3. Context Management 把 TokenMeter 与 Compaction 放入可组合 lifecycle；
4. PTC 把多次模型可见 Tool Round Trip 改为一次 Program Execution boundary；
5. W4/W6 进一步表明，Recovery 取决于错误在哪一层被结构化。

这些概念并非全部由 DeepSeek 在 Agent 行业首次提出。DSH 的特点在于把这些机制统一放进 composition、state 和 execution model，并让边界更显式、更容易替换、观察和验证。W1–W10 提供从真实任务到白盒机制的证据链；C1–C8 则说明这些抽象最终会落成 Control、State、Execution 与 Scale 四类 Host workload。

**因此，本次调研最重要的结论不是哪套 Harness 赢了，而是 DeepSeek Harness 把 composition、state 和 execution boundary 提升成了更显式的架构对象；这些边界既可以通过机制实验验证，也会进一步形成可测的 Host workload。**
