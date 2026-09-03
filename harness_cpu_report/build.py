#!/usr/bin/env python3
"""Build a portable, evidence-aware offline HTML report."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from pathlib import Path

from content import MAPPING, build_features
from data_loader import load_cpu_results, load_evidence_index, load_workload_results
from derive import build_charts
from validate import validate, validate_html


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def card(feature: dict) -> str:
    observations = "".join(f"<li>{esc(item)}</li>" for item in feature["observation"])
    sources = " · ".join(esc(item) for item in feature["sources"])
    return (
        '<article class="card feature-card">'
        f'<span class="tag">{esc(feature["kind"])}</span><strong>{esc(feature["name"])}</strong>'
        f'<p>{esc(feature["mechanism"])}</p><h4>本仓库实测</h4><ul>{observations}</ul>'
        f'<p><b>CPU 实测/关联：</b>{esc(feature["cpu"])}</p>'
        f'<p class="limit"><b>限制：</b>{esc(feature["limit"])}</p>'
        f'<div class="source">来源：{sources}</div></article>'
    )


def chart(chart_spec: dict, index: int) -> str:
    scale = {"linear": "线性", "log": "对数", "log1p": "log(1+x)", "category": "分类"}[chart_spec["x"]["scale"]]
    sources = " · ".join(chart_spec["sources"])
    return (
        f'<article class="chart"><h3>{esc(chart_spec["title"])}</h3>'
        f'<div class="meta">X：{esc(chart_spec["x"]["label"])}（{scale}） · '
        f'Y：{esc(chart_spec["y"]["label"])}（{esc(chart_spec["y"]["unit"])})</div>'
        f'<div class="chart-host" data-chart-index="{index}"></div>'
        f'<p class="chart-note">{esc(chart_spec["note"])}</p>'
        f'<div class="source">来源：{esc(sources)}</div></article>'
    )


def run_full_verification() -> None:
    subprocess.run([str(ROOT / "scripts" / "reproduce-evidence.sh")], cwd=ROOT, check=True)
    subprocess.run([str(ROOT / "scripts" / "cpu" / "verify-cpu-results.py")], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="执行 W evidence 重放与 C result 全量校验")
    args = parser.parse_args()

    cpu = load_cpu_results()
    workloads = load_workload_results()
    charts = build_charts(cpu)
    features = build_features(workloads, cpu)
    status = validate(ROOT, cpu, workloads, charts)
    if args.verify:
        run_full_verification()
        status["full_replay"] = "PASS"

    evidence = load_evidence_index()
    report = {"charts": charts, "validation": status, "generated_from": "explicit W2-W10 and C1-C8 adapters"}
    template = (HERE / "templates" / "index.html").read_text(encoding="utf-8")
    nav_items = [("overview", "概览"), ("harness", "Harness"), ("new", "关键机制"),
                 ("mechanism", "实验映射"), ("cpu", "CPU 工作负载"), ("data", "核心数据"),
                 ("insight", "CPU 启示"), ("evidence", "证据与限制")]
    nav = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in nav_items)
    mapping = "".join(f"<div>{esc(a)}</div><div>{esc(b)}</div><div>{esc(c)}</div>" for a, b, c in MAPPING)
    validation = (f"输入与 schema 校验：{status['input_validation']} · 完整证据重放：{status['full_replay']} · "
                  f"CPU samples：{status['cpu_samples']} · W summaries：{status['workload_summaries']}")
    html_text = (template.replace("{{NAV}}", nav)
                 .replace("{{FEATURES}}", "".join(card(item) for item in features))
                 .replace("{{MAPPING}}", mapping)
                 .replace("{{CHARTS}}", "".join(chart(item, index) for index, item in enumerate(charts)))
                 .replace("{{VALIDATION}}", esc(validation))
                 .replace("{{EVIDENCE_FILE}}", esc(evidence["file"]))
                 .replace("{{CSS}}", (HERE / "static" / "style.css").read_text(encoding="utf-8"))
                 .replace("{{JS}}", (HERE / "static" / "charts.js").read_text(encoding="utf-8"))
                 .replace("{{DATA}}", json.dumps(report, ensure_ascii=False, separators=(",", ":"))))
    output = HERE / "dist" / "index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    validate_html(output)
    print(f"已构建 {output}（{len(html_text):,} bytes；8 个显式 chart adapters；完整重放={status['full_replay']}）")


if __name__ == "__main__":
    main()
