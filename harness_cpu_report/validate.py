"""Validate report inputs, chart specifications, and generated HTML."""

from __future__ import annotations

import math
import re
from pathlib import Path


def _false_checks(value, path="$"):
    failures = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key == "checks" and isinstance(item, dict):
                failures.extend(f"{child}.{name}" for name, passed in item.items() if passed is False)
            failures.extend(_false_checks(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            failures.extend(_false_checks(item, f"{path}[{index}]"))
    return failures


def validate(root: Path, cpu: dict, workloads: dict, charts: list[dict]) -> dict:
    required = [root / "results", root / "evidence", root / "harness_cpu_report" / "templates" / "index.html"]
    missing = [str(item) for item in required if not item.exists()]
    if missing:
        raise SystemExit("缺少报告输入：" + ", ".join(missing))
    if set(cpu) != {f"C{number}" for number in range(1, 9)}:
        raise ValueError("C1-C8 输入集合不完整")
    if set(workloads) != {f"W{number}" for number in range(2, 11)}:
        raise ValueError("W2-W10 输入集合不完整")

    datasets = [item["data"] for key, item in cpu.items() if key != "C8"]
    datasets.extend(cpu["C8"]["data"].values())
    sample_count = 0
    protocols = set()
    for data in datasets:
        protocol = data.get("protocol", {})
        if not protocol.get("protocol_sha256") or not protocol.get("files"):
            raise ValueError("CPU 结果缺少 protocol provenance")
        protocols.add(protocol["protocol_sha256"])
        samples = data.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ValueError("CPU 结果缺少 samples")
        sample_count += len(samples)
        failures = _false_checks(samples)
        if failures:
            raise ValueError(f"CPU fixture checks 失败：{failures[:3]}")

    if len(charts) != 8 or {chart["key"] for chart in charts} != set(cpu):
        raise ValueError("chart adapter 没有精确覆盖 C1-C8")
    for chart in charts:
        if chart["x"]["scale"] not in {"linear", "log", "log1p", "category"}:
            raise ValueError(f"{chart['key']} 坐标类型无效")
        if not chart["series"] or not chart["sources"]:
            raise ValueError(f"{chart['key']} 缺少 series/source")
        for item in chart["series"]:
            if not item["points"]:
                raise ValueError(f"{chart['key']}/{item['name']} 没有数据点")
            for point in item["points"]:
                if not isinstance(point["y"], (int, float)) or not math.isfinite(point["y"]):
                    raise ValueError(f"{chart['key']}/{item['name']} 包含非有限数")

    for key, item in workloads.items():
        if not item["data"].get("task"):
            raise ValueError(f"{key} summary 缺少 task")
        failures = _false_checks(item["data"])
        if failures:
            raise ValueError(f"{key} summary checks 失败：{failures[:3]}")

    return {"input_validation": "PASS", "full_replay": "未执行", "cpu_samples": sample_count,
            "cpu_protocols": len(protocols), "workload_summaries": len(workloads)}


def validate_html(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for marker in ("<html", "</html>", "<style>", "<script>", "DeepSeek Harness", "data-chart-key"):
        if marker not in text:
            raise SystemExit(f"生成 HTML 缺少 {marker}")
    if re.search(r"\{\{[A-Z_]+\}\}", text):
        raise SystemExit("生成 HTML 仍包含未替换模板变量")
