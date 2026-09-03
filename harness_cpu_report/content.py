"""Build evidence-backed narrative cards from W and C result artifacts."""

SECTIONS = {
    "hero_body": (
        "简单 LLM 应用通常以一次 Prompt、一次模型调用和一次响应为中心。但 Agent 开始执行工具、"
        "保存状态、恢复失败、管理长 Context、运行代码并同时处理多个任务后，模型调用只剩整个执行链的"
        "一部分。越来越多控制、状态和执行工作开始落到 Harness 和 Host CPU。本研究首先验证 "
        "DeepSeek Harness 的关键 Runtime 机制，再通过 C1–C8 将这些机制产生的 CPU 工作负载拆开量化。"
    ),
    "why_harness": (
        "模型负责推理，但一个 Agent 任务并不是模型连续“思考”这么简单。在两次模型调用之间，系统还"
        "必须决定如何执行工具、如何记录结果、如何把历史重新组织成下一轮 Context，以及失败以后如何"
        "继续。这些工作共同构成 Harness / Agent Runtime。"
    ),
    "cpu_intro": (
        "当 Agent 从一次请求变成长生命周期进程，Host CPU 同时承接四类工作。Control Plane 推进 "
        "Agent Loop、恢复和编排；State Plane 追加 Event Log、派生 Context、序列化并执行压缩；"
        "Execution Plane 调度 Tool、Process、Code Runtime 与 Filesystem Policy；Scale Plane 则把"
        "这些成本复制到多个并发 Agent。C1–C8 不是处理器排名，而是把这些本地工作拆成可观察的机制成本。"
    ),
    "conclusion": (
        "当前实验显示，DeepSeek Harness 所代表的新一代 Agent Runtime 将越来越多工作放到 Host 侧："
        "Agent Loop、Session/Event Log、Context 管理、JSON/SSE 序列化、Tool 调度、Process 生命周期、"
        "Filesystem Policy 和 Programmatic Tool Execution 都形成了可测量的本地 CPU 工作负载。"
    ),
}


FEATURE_STORIES = {
    "capability": {
        "kicker": "Feature A · Composition",
        "title": "运行时能力不再全部写死在 Agent Loop 中",
        "concept": (
            "DeepSeek Harness 采用 everything-is-a-plugin 架构并由 Cordis 驱动。Runtime 子系统通过 "
            "composition 和 ctx.* service/capability 接口组织；不同 provider 可以在保持上层 consumer "
            "基本不变时改变底层行为。"
        ),
        "cpu": "Capability / policy boundary 也会执行 path canonicalization、containment check 与 policy decision。",
        "limit": "C6 测的是 DSH filesystem capability policy，不是 container、seccomp 或 Firecracker 的总成本。",
    },
    "session": {
        "kicker": "Feature B · State",
        "title": "Session 不只是聊天记录，而是可恢复的执行状态",
        "concept": (
            "普通聊天通常只保留 messages[]；DeepSeek Harness Session 保存 append-only typed event log，并从"
            "日志派生模型上下文。Resume、Fork 与 Replay 因而成为执行状态语义，而不只是聊天记录操作。"
        ),
        "cpu": "Event Log 建立了可恢复的 State Plane，但 append、持久化、扫描、派生与 fork 都会消耗 CPU。",
        "limit": "W9 是 DSH white-box 机制验证，不提供 DSH 与 OpenClaw 的 Session 性能排名。",
    },
    "context": {
        "kicker": "Feature C · Context",
        "title": "Context 不再只是不断增长的 messages 数组",
        "concept": (
            "长 Agent 不只面对 token 增长。Harness 还要维护 Context Projection、测量当前 surface、判断"
            "pressure，并在需要时生成更小的模型上下文。sdk-minimal 不会默认自动压缩；W5 显式加载 "
            "token-meter 与 compaction-basic 来验证这条机制链。"
        ),
        "cpu": "C8 拆分 cold replay、incremental append + measure 与 warm repeat，观察 context-pressure accounting。",
        "limit": "C8 测的是 pinned DSH TokenMeter 机制，不是模型 tokenizer，也不能直接外推生产模型 latency。",
    },
    "ptc": {
        "kicker": "Feature D · Execution",
        "title": "从 Tool Round Trip 到 Program Execution",
        "concept": (
            "Programmatic Tool Calling（PTC）改变的是模型可见的 orchestration 粒度：模型提交一个 program，"
            "再由本地 code runtime 连续 dispatch 多个底层工具。底层操作没有消失，外层 executor 被折叠。"
        ),
        "cpu": "C5 衡量本地 worker 的固定启动成本，以及操作数增长后重复 Agent Loop 边界被摊薄的趋势。",
        "limit": "零延迟 deterministic mock 中的 crossover 不是生产系统推荐阈值。",
    },
}


INSIGHTS = {
    "state": {
        "kicker": "洞察一 · State Plane",
        "title": "长生命周期 Agent 会持续扩大状态工作量",
        "intro": (
            "Session 变长以后，CPU 不只是多保存一些文本。Runtime 还要追加状态、从日志派生 Context、"
            "序列化请求、解析 SSE，并持续进行 context-pressure accounting。"
        ),
        "callout": "Agent 生命周期越长，Host CPU 越需要持续处理不断增长的 Runtime state surface。",
    },
    "execution": {
        "kicker": "洞察二 · Execution Plane",
        "title": "Tool 很短时，Runtime Boundary 可能成为主要成本",
        "intro": (
            "如果工具只做一次 tiny shell/no-op，但每次都要创建 process、连接 pipe、等待退出、包装 result，"
            "再进入下一 Agent step，那么昂贵的未必是工具计算，而可能是执行边界本身。"
        ),
        "callout": "Execution Plane 的关键不只在 Tool 做什么，还在 Runtime 以多细的粒度调用 Tool。",
    },
    "scale": {
        "kicker": "洞察三 · Scale Plane",
        "title": "Agent 并发逐渐变成 Runtime Density 问题",
        "intro": (
            "单 Agent 关注 latency；多 Agent 开始关注 throughput 与 density。每个 Agent 都是独立 Runtime "
            "process 时，增加 Agent 数既增加并行工作，也增加 runtime state、memory footprint 与调度压力。"
        ),
        "callout": "Scale Plane 同时关联 core、memory capacity 与 scheduler。",
    },
}


CHART_EXPLANATIONS = {
    "C1": {
        "measure": "固定 mock 下增加工具步数，记录 Agent Loop 的内部 CPU 与 wall time。",
        "read": "两条曲线随 step 增长；这是整个 cold fixture 的控制面组合成本。",
        "importance": "即使去掉真实模型网络延迟，持续推进 Loop 仍是可测量的 Host 工作。",
        "limit": "fixture 同时包含持续增长的 Session/context，不能解释成纯 dispatch 单函数成本。",
    },
    "C2": {
        "measure": "对 append、deriveMessages、fork prefix、JSONL write 与 warm load 拟合每事件 CPU slope。",
        "read": "在当前简单 event shape 下，append、fork 与 persistence 的边际成本高于 deriveMessages。",
        "importance": "Session 的持久化与恢复语义会形成独立于模型推理的 State Plane 工作。",
        "limit": "这些 slope 只属于固定事件形状和 pinned 实现，不能代表所有 Session。",
    },
    "C3": {
        "measure": "固定消息形状，只扩大逻辑 Context 字节，分别测 JSON encode、decode 与 SSE frame + decode。",
        "read": "字节规模增大后三条曲线均上升，SSE framing 与 JSON decode 的组合成本最明显。",
        "importance": "大 Context 会把 Host CPU 推向 string/JSON serialization workload，与模型 token compute 分层。",
        "limit": "不含网络、TLS、provider 排队或模型计算。",
    },
    "C4": {
        "measure": "对 tiny operation 比较 DSH managed one-shot、raw one-shot 与 persistent control。",
        "read": "Persistent control 把 process lifecycle 移出每次 operation，单位操作成本显著降低。",
        "importance": "对短工具，process/runtime boundary 可能比工具逻辑本身更贵。",
        "limit": "Persistent shell 是机制控制组，不代表 OpenClaw 或生产系统的实现方式。",
    },
    "C5": {
        "measure": "在零延迟 mock 下增加底层操作数，对比 Native Agent Loop 与 PTC program execution。",
        "read": "PTC 有明显 worker 固定成本；操作增多后，Native 重复边界增长更快，PTC 固定成本逐渐摊薄。",
        "importance": "PTC 将部分 orchestration 从模型往返转移到本地 code runtime。",
        "limit": "当前 crossover 不是生产建议；真实 provider latency、模型行为与工具负载均未包含。",
    },
    "C6": {
        "measure": "比较允许的 256 B 热文件写入经过 fs-local 与 fs-sandbox policy seam 的成本。",
        "read": "Sandbox provider 在 local write 之上增加稳定但有限的 policy 开销。",
        "importance": "Runtime policy 不是免费的，即使允许请求也需要 canonicalization 与 containment decision。",
        "limit": "只代表 filesystem capability policy，不等价于 OS、容器或 VM sandbox。",
    },
    "C7": {
        "measure": "固定每 Agent 工作量，将并发从 1 扩展到 32，记录吞吐与相对单 Agent 的并行效率。",
        "read": "吞吐继续增加，但高并发下效率下降；同时每个 child runtime 都保留独立内存 footprint。",
        "importance": "多 Agent 部署开始同时考验 core、scheduler、cache 与 memory capacity。",
        "limit": "只在单主机、固定 placement 与 pinned fixture 下成立，不用于处理器排名。",
    },
    "C8": {
        "measure": "测量 pinned DSH TokenMeter 在 cold replay、incremental append + measure 与 warm repeat 下的内部 CPU。",
        "read": "Cold 需要从 durable history replay meter state；Warm Repeat 即使无新 event，也随当前 surface 增长；Incremental 与 Repeat 接近。",
        "importance": "少量新增 event 不是主要 steady-state 成本，当前 surface 的重复处理更值得关注。",
        "limit": "Slope 是固定 fixture 的机制成本，不是模型 tokenizer 或生产端到端 latency。",
    },
}


LIMITATIONS = [
    "没有证明 ARM 优于 x86，也没有证明某个 CPU 厂商更适合 Agent。",
    "没有证明 DeepSeek Harness 全面优于 OpenClaw。",
    "没有证明 PTC 在所有 workload 下都更快。",
    "没有证明 C6 等价于完整 sandbox。",
    "没有证明 microbenchmark slope 可以直接转化为 production latency。",
]

MAPPING = [
    ("Agent Loop", "W1–W3", "C1"), ("错误恢复", "W4 / W6", "C1"),
    ("Compaction", "W5", "C8"), ("Event Log / Session", "W7 / W9", "C2 / C8"),
    ("Code Mode / PTC", "W8", "C5"), ("Capability Seam", "W10", "C6"),
    ("工具执行", "W1–W3", "C4"), ("上下文传输", "W5 / W7", "C3"),
    ("多 Agent", "—", "C7"),
]


def build_features(workloads: dict, cpu: dict) -> list[dict]:
    w = {key: item["data"] for key, item in workloads.items()}
    c = {key: item["data"] for key, item in cpu.items() if key != "C8"}
    w10 = w["W10"]
    c6 = c["C6"]["comparisons"]["write"]["1000"]
    w9 = w["W9"]
    w5d = w["W5"]["calibrated_main_pair"]["deepseek_harness"]
    w8d = w["W8"]["deepseek_harness"]
    w4 = w["W4"]
    c2fits = c["C2"]["linear_fits_over_event_count_medians"]
    return [
        {
            "kind": "架构机制", "name": "Everything is a Plugin / Capability Seam",
            "mechanism": "DeepSeek Harness 采用 everything-is-a-plugin 架构并由 Cordis 驱动。各运行时子系统通过 composition 和 ctx.* service/capability 接口组织；本仓库 W10 实际验证了 ctx.fs provider 的可替换边界。",
            "observation": [
                f"W10 fs-local：inside={w10['local_a']['inside']}，outside={w10['local_a']['outside']}",
                f"W10 fs-sandbox：inside={w10['sandbox_b']['inside']}，outside edit={w10['sandbox_b']['tool_results'][-1]['error_code']}",
                f"W10 swap back：A=A′ 为 {str(w10['checks']['a_equals_a_prime']).lower()}",
            ],
            "cpu": f"C6 @1000 writes：sandbox/local wall={c6['sandbox_over_local_wall_ns_per_operation']:.3f}×，CPU={c6['sandbox_over_local_cpu_us_per_operation']:.3f}×。",
            "limit": "C6 是 trusted filesystem policy seam，不是 seccomp、container 或 VM sandbox。",
            "sources": [workloads["W10"]["file"], cpu["C6"]["file"]],
        },
        {
            "kind": "架构机制", "name": "Append-only Event Log Session",
            "mechanism": "Session 保存 typed event log；模型 messages 由日志派生，因此 resume、fork 和 replay 是状态语义而不只是聊天记录。",
            "observation": [
                f"W9 crash prefix byte-identical：{str(w9['crash_resume']['checks']['committed_prefix_byte_identical']).lower()}",
                f"dangling call 自动重放：否；注入 {w9['crash_resume']['synthetic_error_code']}",
                f"Fork boundary messages 相等：{str(w9['fork']['checks']['derive_messages_equal_at_boundary']).lower()}",
                f"Replay 未访问 live provider：{str(w9['llm_replay']['checks']['provider_not_contacted_during_replay']).lower()}",
            ],
            "cpu": f"C2 边际 CPU：append {c2fits['append_cpu_us']['per_event_slope']:.2f}、deriveMessages {c2fits['derive_messages_cpu_us']['per_event_slope']:.3f}、fork {c2fits['fork_prefix_cpu_us']['per_event_slope']:.2f} μs/event。",
            "limit": "W9 是 DSH white-box 机制实验，不提供跨 runtime 排名。",
            "sources": [workloads["W9"]["file"], cpu["C2"]["file"]],
        },
        {
            "kind": "可选能力", "name": "Context Compaction",
            "mechanism": "当 composition 显式加载 token-meter 与 compaction service 后，runtime 可根据 context pressure 在执行中生成压缩上下文。",
            "observation": [
                f"W5 DSH：{w5d['tool_calls']} 次 tool calls，{w5d['compaction_requests']} 次 compaction，最终 completed={str(w5d['runtime_completed']).lower()}",
                "三个 boundary 后的下一次 agent request body 均下降",
            ],
            "cpu": "C8 分开测量 cold replay、incremental append+scan 与 repeat full-surface scan。",
            "limit": "sdk-minimal 默认不含 compaction；W5 是显式加载服务后的机制结果。",
            "sources": [workloads["W5"]["file"], *cpu["C8"]["files"].values()],
        },
        {
            "kind": "架构机制", "name": "Programmatic Tool Calling（PTC）",
            "mechanism": "模型生成一次 program call，在 code runtime 内部连续 dispatch 多个底层工具。",
            "observation": [
                f"W8 底层 shell 操作保持 {w8d['direct']['underlying_shell_calls']} 次",
                f"Direct：{w8d['direct']['model_visible_tool_calls']} tool calls / {w8d['direct']['provider_requests']} requests",
                f"PTC：{w8d['code']['model_visible_tool_calls']} program call / {w8d['code']['provider_requests']} requests",
                f"Request body 下降 {w8d['paired_change']['total_request_body_reduction_percent']:.1f}%",
            ],
            "cpu": "C5 显示 PTC 有固定 worker/runtime 成本，但高操作数时减少重复 Agent Loop 工作。",
            "limit": "零延迟 deterministic mock 不包含真实 provider latency。",
            "sources": [workloads["W8"]["file"], cpu["C5"]["file"]],
        },
        {
            "kind": "实验洞察", "name": "Error 是 Runtime Policy",
            "mechanism": "错误在哪个边界被结构化，决定模型是否能看到错误并继续执行；这不是官方命名的新 feature。",
            "observation": [
                f"W4 DSH malformed event：{w4['deepseek_harness']['provider_requests']} requests 后恢复",
                f"W4 OpenClaw pinned：{w4['openclaw']['runtime_error_kind']}，terminal",
                "W6 valid call 的参数错误在两侧均可返回模型并恢复",
            ],
            "cpu": "Recovery 会增加 Agent step、serialization 与 loop 边界；C1 只提供这些组合成本的基线。",
            "limit": "结论限于固定 malformed event、provider protocol 与 pinned revisions。",
            "sources": [workloads["W4"]["file"], workloads["W6"]["file"], cpu["C1"]["file"]],
        },
    ]


def build_real_tasks(workloads: dict) -> list[dict]:
    cards = []
    for key, title in (("W2", "小型 Python Bug Fix"), ("W3", "多模块 Feature Task")):
        data = workloads[key]["data"]
        dsh, openclaw = data["deepseek_harness"], data["openclaw"]
        observation = ("两侧均能完成该类基础 coding task；n=5 且 wall-time 分布重叠，不作速度排名。"
                       if key == "W2" else
                       "三个 incomplete_turn 现象促使 W4 使用 deterministic malformed event 隔离 recovery semantics。")
        cards.append({
            "key": key, "title": title,
            "dsh": f"{dsh['successes']} / {dsh['attempts']}",
            "openclaw": f"{openclaw['successes']} / {openclaw['attempts']}",
            "observation": observation, "source": workloads[key]["file"],
        })
    return cards


def build_key_findings(workloads: dict, cpu: dict) -> list[dict]:
    w8 = workloads["W8"]["data"]["deepseek_harness"]
    c4 = cpu["C4"]["data"]["aggregates"]
    c7 = cpu["C7"]["data"]
    c8 = cpu["C8"]["data"]
    cold_slope = c8["cold"]["linear_fits"]["internal_cpu_us_per_measure"]["per_surface_node_slope"]
    repeat_slope = c8["repeat"]["linear_fits"]["internal_cpu_us_per_measure"]["per_surface_node_slope"]
    return [
        {"label": "PTC / W8", "value": f"{w8['direct']['provider_requests']} → {w8['code']['provider_requests']}",
         "detail": "8 个底层操作不变，Code Mode / PTC 将 Provider Request 从 9 次降到 2 次。",
         "source": workloads["W8"]["file"]},
        {"label": "Process / C4", "value": f"{c4['dsh-managed']['1000']['wall_ns_per_operation']['median']/1e6:.2f} vs {c4['persistent']['1000']['wall_ns_per_operation']['median']/1e6:.3f} ms/op",
         "detail": "1000 tiny ops：Managed one-shot vs Persistent control；Runtime / Process 边界可能比工具逻辑更贵。",
         "source": cpu["C4"]["file"]},
        {"label": "Context Pressure / C8", "value": f"{cold_slope/repeat_slope:.1f}×",
         "detail": "Cold / Warm Repeat 边际 CPU slope 比值；Cold 包含 durable-history replay，不是端到端 latency 倍率。",
         "source": f"{cpu['C8']['files']['cold']} + {cpu['C8']['files']['repeat']}"},
        {"label": "Multi-Agent / C7", "value": f"{c7['aggregates']['32']['agents_per_second']['median']:.2f} Agents/s",
         "detail": f"32 Agents；并行效率 {c7['scaling']['32']['parallel_efficiency']*100:.1f}%，开始面对 core、scheduler 与 Runtime memory footprint 的组合压力。",
         "source": cpu["C7"]["file"]},
    ]


def build_story_evidence(workloads: dict, cpu: dict) -> dict:
    w = {key: item["data"] for key, item in workloads.items()}
    w10, w9 = w["W10"], w["W9"]
    w5 = w["W5"]["calibrated_main_pair"]["deepseek_harness"]
    w8 = w["W8"]["deepseek_harness"]
    c2 = cpu["C2"]["data"]["linear_fits_over_event_count_medians"]
    c6 = cpu["C6"]["data"]["comparisons"]["write"]["1000"]
    c7 = cpu["C7"]["data"]
    boundaries = w5["compaction_boundaries"]
    return {
        "capability": {
            "local_inside": w10["local_a"]["inside"],
            "local_outside": w10["local_a"]["outside"],
            "sandbox_inside": w10["sandbox_b"]["inside"],
            "sandbox_error": w10["sandbox_b"]["tool_results"][-1]["error_code"],
            "swap_restored": w10["checks"]["a_equals_a_prime"],
            "cpu_ratio": c6["sandbox_over_local_cpu_us_per_operation"],
        },
        "session": {
            "prefix_identical": w9["crash_resume"]["checks"]["committed_prefix_byte_identical"],
            "dangling_reexecuted": not w9["crash_resume"]["checks"]["dangling_call_not_dispatched"],
            "synthetic_error": w9["crash_resume"]["synthetic_error_code"],
            "fork_equal": w9["fork"]["checks"]["derive_messages_equal_at_boundary"],
            "provider_contacted": not w9["llm_replay"]["checks"]["provider_not_contacted_during_replay"],
            "append_slope": c2["append_cpu_us"]["per_event_slope"],
            "derive_slope": c2["derive_messages_cpu_us"]["per_event_slope"],
        },
        "context": {
            "tool_calls": w5["tool_calls"],
            "compactions": w5["compaction_requests"],
            "completed": w5["runtime_completed"],
            "boundaries": [
                {
                    "after": item["after_agent_request_ordinal"],
                    "before": item["agent_body_before_bytes"],
                    "after_bytes": item["agent_body_after_bytes"],
                }
                for item in boundaries
            ],
        },
        "ptc": {
            "operations": w8["direct"]["underlying_shell_calls"],
            "direct_calls": w8["direct"]["model_visible_tool_calls"],
            "direct_requests": w8["direct"]["provider_requests"],
            "code_calls": w8["code"]["model_visible_tool_calls"],
            "code_requests": w8["code"]["provider_requests"],
            "request_reduction": w8["paired_change"]["provider_request_reduction_percent"],
        },
        "scale": {
            "agents_per_second": c7["aggregates"]["32"]["agents_per_second"]["median"],
            "efficiency": c7["scaling"]["32"]["parallel_efficiency"] * 100,
            "sum_rss_gib": c7["aggregates"]["32"]["sum_child_max_rss_kb"]["median"] / 1024 / 1024,
            "max_child_rss_mib": c7["aggregates"]["32"]["max_child_max_rss_kb"]["median"] / 1024,
        },
    }


def build_provenance(cpu: dict, git_status: str, input_sha256: str,
                     full_replay: str) -> list[tuple[str, str]]:
    c1 = cpu["C1"]["data"]
    revisions = c1["protocol"]["source_revisions"]
    host = c1["host"]
    return [
        ("报告生成时 Git 状态", git_status),
        ("报告输入指纹 / SHA256", input_sha256),
        ("DeepSeek Harness", revisions["DSH_COMMIT"]),
        ("OpenClaw", revisions["OPENCLAW_COMMIT"]),
        ("Node.js", revisions["NODE_VERSION"]),
        ("Host", f"{host['machine']} / {host['logical_cpus']} logical CPUs"),
        ("Kernel", host["kernel_release"]),
        ("perf mode", c1["design"]["perf_mode"]),
        ("完整证据验证", f"W1–W10 / C1–C8 {full_replay}"),
    ]
