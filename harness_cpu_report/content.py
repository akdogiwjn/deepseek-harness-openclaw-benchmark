"""Build evidence-backed narrative cards from W and C result artifacts."""

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
    c3 = cpu["C3"]["data"]["aggregates"][str(16 * 1024 * 1024)]
    c7 = cpu["C7"]["data"]
    c8 = cpu["C8"]["data"]
    cold_slope = c8["cold"]["linear_fits"]["internal_cpu_us_per_measure"]["per_surface_node_slope"]
    repeat_slope = c8["repeat"]["linear_fits"]["internal_cpu_us_per_measure"]["per_surface_node_slope"]
    return [
        {"label": "PTC / W8", "value": f"{w8['direct']['provider_requests']} → {w8['code']['provider_requests']}",
         "detail": "Provider requests", "source": workloads["W8"]["file"]},
        {"label": "Process / C4", "value": f"{c4['dsh-managed']['1000']['wall_ns_per_operation']['median']/1e6:.2f} vs {c4['persistent']['1000']['wall_ns_per_operation']['median']/1e6:.3f} ms/op",
         "detail": "1000 tiny ops：DSH managed vs persistent control", "source": cpu["C4"]["file"]},
        {"label": "Long Context / C3", "value": f"{c3['sse_frame_and_json_decode_cpu_us']['median']/1000:.2f} ms",
         "detail": "16 MiB SSE + JSON 内部 CPU", "source": cpu["C3"]["file"]},
        {"label": "Multi-Agent / C7", "value": f"{c7['aggregates']['32']['agents_per_second']['median']:.2f} Agents/s",
         "detail": f"32 Agents；效率 {c7['scaling']['32']['parallel_efficiency']*100:.1f}%", "source": cpu["C7"]["file"]},
        {"label": "Context Pressure / C8", "value": f"{cold_slope/repeat_slope:.1f}×",
         "detail": "Cold / Warm Repeat 边际 CPU slope 比值；Cold 包含 durable-history replay，不是端到端 latency 倍率。",
         "source": f"{cpu['C8']['files']['cold']} + {cpu['C8']['files']['repeat']}"},
    ]


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
        ("perf mode", c1["design"]["perf_mode"]),
        ("完整证据验证", f"W1–W10 / C1–C8 {full_replay}"),
    ]
