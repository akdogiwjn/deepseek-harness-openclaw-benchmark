#!/usr/bin/env python3
"""Validate generated report inputs, figures, metrics, provenance, and references."""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "deepseek_harness_report"
ARCHITECTURE_FIGURES = {
    "harness-model.svg", "composition-tree.svg", "capability-seam.svg", "event-log.svg",
    "context-management.svg", "ptc.svg", "recovery-boundary.svg", "feature-to-cpu.svg",
}
sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_report import RESULT_FILES, input_fingerprint, load_inputs, source_revision  # noqa: E402


def finite_numbers(value, path="$" ) -> None:
    if isinstance(value, dict):
        for key, child in value.items(): finite_numbers(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value): finite_numbers(child, f"{path}[{index}]")
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite metric at {path}")


def validate_document(report_name: str, html_name: str, chapter_count: int) -> tuple[str, int]:
    report = (REPORT_ROOT / report_name).read_text(encoding="utf-8")
    html = (REPORT_ROOT / "dist" / html_name).read_text(encoding="utf-8")
    if re.search(r"\{\{[A-Z0-9_]+\}\}", report):
        raise ValueError(f"{report_name} contains unresolved placeholders")
    markdown_figures = re.findall(r"!\[([^]]*)\]\((figures/[^)]+)\)", report)
    html_figures = re.findall(r'<img\s+src="(figures/[^"]+)"[^>]*alt="([^"]+)"', report)
    figure_pairs = [(path, alt) for alt, path in markdown_figures] + html_figures
    figures = [path for path, _ in figure_pairs]
    if not figures or any(not (REPORT_ROOT / path).is_file() for path in figures):
        raise ValueError("referenced report figure missing")
    if len(figures) != len(set(figures)):
        raise ValueError("report repeats a figure instead of referencing its canonical discussion")
    if any(not alt.strip() for _, alt in figure_pairs):
        raise ValueError("report figure missing alt text")
    if len(set(figures)) > 16:
        raise ValueError("report uses too many figures")
    captioned = re.findall(r'<p align="center"><sub>图\s*[0-9]', report)
    if len(captioned) < len(figure_pairs):
        raise ValueError("each major figure must have a Chinese caption")
    for number in range(chapter_count):
        if f"## {number}." not in report:
            raise ValueError(f"{report_name} missing chapter {number}")
    if not all(marker in html for marker in ("<!doctype html>", "<nav>", "<table>", "../figures/")):
        raise ValueError(f"derived HTML is incomplete: {html_name}")
    return report, len(set(figures))


def main() -> None:
    readme = (REPORT_ROOT / "README.md").read_text(encoding="utf-8")
    if any(name not in readme for name in ("report.md", "report_showcase.md")):
        raise ValueError("README does not identify both report editions")
    reports = {}
    figure_counts = {}
    for report_name, html_name, chapter_count in (
        ("report.md", "report.html", 12),
        ("report_showcase.md", "report_showcase.html", 12),
    ):
        reports[report_name], figure_counts[report_name] = validate_document(
            report_name, html_name, chapter_count)
    detailed = reports["report.md"]
    showcase = reports["report_showcase.md"]
    if len(showcase) > len(detailed):
        raise ValueError("showcase report is longer than the detailed edition")
    showcase_requirements = (
        "## 2. 这次我们做了哪些实验", "Harness 行为实验 W1–W10", "CPU 实验 C1–C8",
        "Everything is a Plugin", "Session Event Log", "Context Management",
        "Programmatic Tool Calling", "OpenClaw 已经具备", "不是第五个官方 Feature",
    )
    for phrase in showcase_requirements:
        if phrase not in showcase:
            raise ValueError(f"showcase report missing required framing: {phrase}")
    if "新特性五" in showcase:
        raise ValueError("showcase incorrectly presents Recovery as a fifth feature")
    for assertion_dump in ("=是", "：是", "=否", "：否"):
        if assertion_dump in showcase:
            raise ValueError(
                "showcase exposes boolean assertions instead of human-readable summaries: "
                f"{assertion_dump}"
            )
    editorial_asides = (
        "面向第一次接触本项目的技术读者", "这一章只建立实验地图", "第一次看这张图",
        "这张图主要看", "下面这张图主要看", "下面这张图左右采用相同起点与终点",
        "因此不再增加一张独立 C1 图", "RSS 不增加第三个图轴", "不被包装成新的",
        "deterministic mechanism tests", "white-box mechanism tests", "calibrated fixture",
        "pinned Runtime", "先建立这个边界",
        "## 11. 实验证据、可信度与边界", "### 11.2 Provenance",
        "Context 墛长", "summed child max RSS", "containment 判断", "Cold/Repeat 边际 slope",
        "closed-turn boundary", "committed prefix", "dangling call", "live provider",
        "SSE parsing", "实际参与计量的 Context 节点", "Runtime Density",
        "不被包装成", "malformed provider event", "Native Tool Calling",
        "Cold 路径增长最快", "边际增长斜率约为 Warm Repeat", "μs/有效节点",
        "Host CPU 实验看到了什么", "Agent 运行越久，状态处理成本越高",
        "个 Context 节点时", "% efficiency", "状态平面和执行平面",
        "lifecycle event", "automatic compaction", "Runtime lifecycle",
        "更容易替换、观察和验证",
    )
    for phrase in editorial_asides:
        if phrase in showcase:
            raise ValueError(f"showcase contains an editorial aside: {phrase}")
    metrics = json.loads((REPORT_ROOT / "generated" / "metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((REPORT_ROOT / "generated" / "provenance.json").read_text(encoding="utf-8"))
    data = load_inputs()
    for name in RESULT_FILES.values():
        if not (ROOT / "results" / name).is_file(): raise ValueError(f"missing result {name}")
    for key in ("DSH_COMMIT", "OPENCLAW_COMMIT", "NODE_VERSION"):
        source_revision(data, key)
    for directory, expected in (("deepseek-harness", provenance["deepseek_harness_commit"]),
                                ("openclaw", provenance["openclaw_commit"])):
        checkout = ROOT / "sources" / directory
        if checkout.exists():
            actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=checkout, text=True,
                                    capture_output=True, check=True).stdout.strip()
            if actual != expected: raise ValueError(f"{directory} checkout is {actual}, expected {expected}")
    protocols = [item.get("protocol") for key, item in data.items() if key.startswith("c")]
    if any(not item or not item.get("protocol_sha256") for item in protocols):
        raise ValueError("C1-C8 protocol provenance incomplete")
    for report_name, report in reports.items():
        for number in range(1, 11):
            if f"W{number}" not in report: raise ValueError(f"{report_name}: W{number} reference absent")
        for number in range(1, 9):
            if f"C{number}" not in report: raise ValueError(f"{report_name}: C{number} reference absent")
    finite_numbers(metrics)
    if provenance["report_input_sha256"] != input_fingerprint():
        raise ValueError("report input fingerprint mismatch")
    pinned = {provenance["deepseek_harness_commit"], provenance["openclaw_commit"]}
    if any(len(value) != 40 for value in pinned): raise ValueError("pinned revision is not a full SHA")
    if not (ROOT / "evidence" / "manifest.json").is_file(): raise ValueError("evidence manifest missing")
    forbidden = {"#0b151c", "#101c23"}
    expected_series = {"C2": 1, "C3": 3, "C4": 3, "C5": 2, "C6": 2, "C7": 2, "C8": 3}
    architecture_paths = REPORT_ROOT / "figures" / "architecture"
    if {path.name for path in architecture_paths.glob("*.svg")} != ARCHITECTURE_FIGURES:
        raise ValueError("curated architecture SVG set differs from the required report assets")
    for path in (REPORT_ROOT / "figures").rglob("*.svg"):
        text = path.read_text(encoding="utf-8")
        root = ElementTree.fromstring(text)
        if "viewBox" not in root.attrib: raise ValueError(f"SVG missing viewBox: {path}")
        if any(color in text.lower() for color in forbidden): raise ValueError(f"legacy dark color in {path}")
        for node in root.iter("{http://www.w3.org/2000/svg}text"):
            size = node.attrib.get("font-size")
            if size and float(size) < 14: raise ValueError(f"SVG text below 14px in {path}: {size}")
        benchmark = root.attrib.get("data-benchmark")
        if benchmark and int(root.attrib.get("data-series-count", -1)) != expected_series[benchmark]:
            raise ValueError(f"{benchmark} SVG series count mismatch")
        if benchmark == "C8":
            c8_legend = ("Cold · 历史重建", "Incremental · 新增后计量",
                         "Warm Repeat · 状态不变")
            if any(label not in text for label in c8_legend):
                raise ValueError("C8 SVG is missing its color-keyed path legend")
        if benchmark == "C7" and "% 并行效率" not in text:
            raise ValueError("C7 SVG is missing the Chinese parallel-efficiency label")
    sys.path.insert(0, str(ROOT / "harness_cpu_report"))
    from data_loader import load_cpu_results  # noqa: E402
    from derive import build_charts  # noqa: E402
    cpu_results = load_cpu_results()
    c8 = next(item for item in build_charts(cpu_results) if item["key"] == "C8")
    effective_x = [point["x"] for point in c8["series"][1]["points"]]
    initial_x = [float(key) for key in sorted(data["c8_incremental"]["aggregates"], key=float)]
    if effective_x == initial_x or effective_x != [110.5, 200.5, 1100.5, 5020.5, 10010.5]:
        raise ValueError("C8 Incremental no longer uses effective_surface_nodes")
    from build_figures import build_data_figures  # noqa: E402
    for name, content in build_data_figures(cpu_results).items():
        if (REPORT_ROOT / "figures" / "data" / name).read_text(encoding="utf-8") != content:
            raise ValueError(f"generated data SVG differs from JSON/source-derived output: {name}")
    counts = ", ".join(f"{name}={count} figures" for name, count in figure_counts.items())
    print(f"report validation PASS: {counts}, {len(RESULT_FILES)} result inputs")


if __name__ == "__main__":
    main()
