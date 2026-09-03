#!/usr/bin/env python3
"""Build a portable, offline HTML research story from repository evidence."""
from pathlib import Path
import json
from data_loader import load_cpu_results, load_evidence_index
from derive import summary
from content import FEATURES, MAPPING
from validate import validate, validate_html

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

def card(feature):
    name, exp, cpu, text = feature
    return f'<article class="card"><span class="tag">FEATURE</span><strong>{name}</strong><p>{text}</p><p><b>OBSERVED</b> {exp}<br><b>CPU OBSERVED</b> {cpu}</p><span class="evidence">✓ evidence-linked · ✓ derived at build time</span></article>'

def chart(key, title, x, y):
    s = summary(load_cpu_results()).get(key, {})
    return f'<article class="chart"><h3>{title}</h3><div class="meta">X = {x} · Y = {y} · {s.get("benchmark", "result unavailable")}</div><div data-chart="{key}"></div><div class="meta">protocol: {s.get("protocol", "not recorded")[:16]}…</div></article>'

def main():
    validate(ROOT)
    cpu = load_cpu_results()
    report = {"summary": summary(cpu), "results": cpu, "generated_from": "results/c1-c8-*.json"}
    template = (HERE / "templates" / "index.html").read_text(encoding="utf-8")
    nav = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in [("overview","概览"),("harness","Harness 是什么"),("new","DeepSeek 新特性"),("mechanism","机制验证"),("cpu","CPU 工作负载"),("data","核心数据"),("insight","CPU 架构洞察"),("evidence","证据与限制")])
    mapping = "".join(f'<div>{a}</div><div>{b}</div><div>{c}</div>' for a,b,c in MAPPING)
    charts = "".join([chart("C1", "图 1 · Agent Step Scaling", "Tool Steps (log)", "Internal CPU / Wall"), chart("C2", "图 2 · Session State Cost", "Events", "μs / event"), chart("C3", "图 3 · Long Context Serialization", "Context bytes (log)", "CPU time"), chart("C4", "图 4 · Tool Process Lifecycle", "Operations (log)", "Wall / op"), chart("C5", "图 5 · Native vs PTC", "Operation count (log)", "Runtime"), chart("C7", "图 6 · Multi-Agent", "Agents", "Agents/s"), chart("C8", "图 7 · Context Pressure", "Surface nodes", "CPU / node")])
    evidence = load_evidence_index()
    html = template.replace("{{NAV}}", nav).replace("{{FEATURES}}", "".join(map(card, FEATURES))).replace("{{MAPPING}}", mapping).replace("{{CHARTS}}", charts).replace("{{EVIDENCE_FILE}}", evidence.get("file", "not found")).replace("{{CSS}}", (HERE / "static" / "style.css").read_text(encoding="utf-8")).replace("{{JS}}", (HERE / "static" / "charts.js").read_text(encoding="utf-8")).replace("{{DATA}}", json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    out = HERE / "dist" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    validate_html(out)
    print(f"built {out} ({len(html):,} bytes; {len(cpu)} CPU datasets)")

if __name__ == "__main__": main()
