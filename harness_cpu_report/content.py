FEATURES = [
    ("Capability Seam", "W10 A/B/A′", "C6", "Provider 化能力让 policy / isolation 成为可观测的 Host CPU workload。"),
    ("Event Log Session", "W9 Resume/Fork/Replay", "C2 / C8", "append-only 事件日志经过 deriveMessages() 再构造 Model Context。"),
    ("Context Compaction", "W5", "C8", "Token pressure 触发 compaction，生成新的模型上下文。"),
    ("Code Mode / PTC", "W8", "C5", "多个工具调用折叠为一次 program execution，减少 loop 边界。"),
    ("Error as Runtime Policy", "W3 / W4 / W6", "C1", "错误在哪个边界被结构化，决定 Agent 能否继续修复。"),
    ("Policy / Sandbox", "W10", "C6", "path normalization、workspace fence、permission decision 都是执行工作。"),
]

MAPPING = [("Agent Loop", "W1–W3", "C1"), ("Error Recovery", "W4 / W6", "C1"), ("Compaction", "W5", "C8"), ("Event Log / Session", "W7 / W9", "C2 / C8"), ("Code Mode / PTC", "W8", "C5"), ("Capability Seam", "W10", "C6"), ("Tool Execution", "W1–W3", "C4"), ("Context Transport", "W5 / W7", "C3"), ("Multi-Agent", "—", "C7")]
