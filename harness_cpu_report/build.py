#!/usr/bin/env python3
"""Build a portable, evidence-aware offline HTML report."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import subprocess
from pathlib import Path

from content import (CHART_EXPLANATIONS, FEATURE_STORIES, INSIGHTS, LIMITATIONS,
                     SECTIONS, build_features, build_key_findings, build_provenance,
                     build_real_tasks, build_story_evidence)
from data_loader import (CPU_FILES, C8_FILES, WORKLOAD_FILES, load_cpu_results,
                         load_evidence_index, load_workload_results)
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


def chart(chart_spec: dict, size: str = "hero") -> str:
    scale = {"linear": "线性", "log": "对数", "log1p": "log(1+x)", "category": "分类"}[chart_spec["x"]["scale"]]
    sources = " · ".join(chart_spec["sources"])
    explanation = CHART_EXPLANATIONS[chart_spec["key"]]
    return (
        f'<article class="chart-panel chart-{esc(size)}"><div class="chart-heading">'
        f'<span class="evidence-id">{esc(chart_spec["key"])}</span><h3>{esc(chart_spec["title"])}</h3>'
        f'<div class="meta">X：{esc(chart_spec["x"]["label"])}（{scale}） · '
        f'Y：{esc(chart_spec["y"]["label"])}（{esc(chart_spec["y"]["unit"])})</div></div>'
        f'<div class="chart-host" data-chart-key="{esc(chart_spec["key"])}"></div>'
        '<div class="chart-explanation">'
        f'<div><b>图中测了什么</b><p>{esc(explanation["measure"])}</p></div>'
        f'<div><b>怎么看这张图</b><p>{esc(explanation["read"])}</p></div>'
        f'<div><b>为什么重要</b><p>{esc(explanation["importance"])}</p></div>'
        f'<div class="chart-limit"><b>这张图不能证明什么</b><p>{esc(explanation["limit"])}</p></div>'
        '</div>'
        f'<div class="source">来源：{esc(sources)}</div></article>'
    )


def finding_card(item: dict) -> str:
    return (f'<article class="metric"><span class="tag">{esc(item["label"])}</span>'
            f'<strong>{esc(item["value"])}</strong><p>{esc(item["detail"])}</p>'
            f'<div class="source">{esc(item["source"])}</div></article>')


def task_card(item: dict) -> str:
    return (f'<article class="task-result"><span class="evidence-id">{esc(item["key"])}</span>'
            f'<strong>{esc(item["title"])}</strong><div class="flow score-row">'
            f'<span>DSH <b>{esc(item["dsh"])}</b></span><span>OpenClaw <b>{esc(item["openclaw"])}</b></span></div>'
            f'<p>{esc(item["observation"])}</p><div class="source">来源：{esc(item["source"])}</div></article>')


def provenance_table(items: list[tuple[str, str]]) -> str:
    return "".join(f'<div><dt>{esc(label)}</dt><dd><code>{esc(value)}</code></dd></div>'
                   for label, value in items)


def _bool(value: bool) -> str:
    return "是" if value else "否"


def feature_stories(evidence: dict, charts: dict) -> str:
    cap, session, context, ptc = (evidence[key] for key in ("capability", "session", "context", "ptc"))
    boundary_rows = "".join(
        f'<li>第 {item["after"]} 次 Agent Request 后：'
        f'{item["before"]:,} B → {item["after_bytes"]:,} B</li>'
        for item in context["boundaries"]
    )
    story_data = [
        ("capability", '''<div class="mechanism-diagram capability-map">
          <span>Agent Loop</span><i>↓</i><span>tool-fs</span><i>↓</i><span><code>ctx.fs</code></span>
          <div class="branch"><span>fs-local<br><small>outside write ✓</small></span><span>fs-sandbox<br><small>outside write ✕</small></span></div></div>''',
         f'''<p>W10 保持 Agent Loop、tool-fs consumer 与 scripted calls 不变，只替换 <code>ctx.fs</code> provider。</p>
         <div class="behavior-compare"><div><b>fs-local</b><span>workspace：{esc(cap["local_inside"])}</span><span>outside：{esc(cap["local_outside"])}</span></div>
         <div><b>fs-sandbox</b><span>workspace：{esc(cap["sandbox_inside"])}</span><span>outside：{esc(cap["sandbox_error"])}</span></div></div>
         <p>切回 local 后行为恢复：<b>{_bool(cap["swap_restored"])}</b>。C6 @1000 writes 的 sandbox/local CPU 比为 <b>{cap["cpu_ratio"]:.3f}×</b>。</p>''',
         chart(charts["C6"], "support")),
        ("session", '''<div class="mechanism-diagram event-map"><div class="event-stream"><span>turn/start</span><span>user/message</span><span>tool/call</span><span>tool/result</span><span>step/end</span><span>turn/end</span></div>
          <div class="event-branches"><span>deriveMessages() → Model Context</span><span>Resume</span><span>Fork</span><span>Replay</span></div></div>''',
         f'''<div class="evidence-triad"><div><b>Crash / Resume</b><p>已提交 prefix byte-identical：{_bool(session["prefix_identical"])}；dangling call 重新执行：{_bool(session["dangling_reexecuted"])}，注入 <code>{esc(session["synthetic_error"])}</code> 后继续。</p></div>
         <div><b>Fork</b><p>closed-turn boundary 的 parent/child 派生消息相等：{_bool(session["fork_equal"])}；随后可独立追加。</p></div>
         <div><b>Replay</b><p>使用记录的 model stream 重放；访问 live provider：{_bool(session["provider_contacted"])}。</p></div></div>
         <p>C2 当前 fixture 的 append slope 为 <b>{session["append_slope"]:.2f} μs/event</b>，deriveMessages slope 为 <b>{session["derive_slope"]:.3f} μs/event</b>。</p>''', ""),
        ("context", '''<div class="mechanism-diagram pipeline"><span>Session grows</span><i>→</i><span>Context Projection</span><i>→</i><span>TokenMeter</span><i>→</i><span>Pressure</span><i>→</i><span>Compaction</span></div>''',
         f'''<p>W5 中 <b>{context["tool_calls"]} 次 tool calls</b> 触发 <b>{context["compactions"]} 次 compaction</b>，并在压缩后继续完成任务：{_bool(context["completed"])}。</p>
         <ul class="boundary-list">{boundary_rows}</ul>''', chart(charts["C8"])),
        ("ptc", '''<div class="mechanism-diagram executor-map"><div><b>Direct</b><span>LLM → Tool → LLM → Tool → LLM</span></div><div><b>Program Execution</b><span>LLM → Program { Tool · Tool · Tool } → LLM</span></div><strong>Executor Collapse</strong></div>''',
         f'''<p>W8 固定 <b>{ptc["operations"]} 个底层 shell 操作</b>：Direct 是 <b>{ptc["direct_calls"]} 个 model-visible calls / {ptc["direct_requests"]} requests</b>；Code Mode 是 <b>{ptc["code_calls"]} 个 program call / {ptc["code_requests"]} requests</b>。</p>
         <p>Provider Request 减少 <b>{ptc["request_reduction"]:.1f}%</b>；变化的是外层编排粒度，而不是底层操作数量。</p>''', chart(charts["C5"])),
    ]
    result = []
    for key, diagram, measured, embedded_chart in story_data:
        story = FEATURE_STORIES[key]
        result.append(
            f'<article class="feature-story" id="feature-{key}"><div class="story-copy">'
            f'<span class="chapter-kicker">{esc(story["kicker"])}</span><h3>{esc(story["title"])}</h3>'
            f'<p class="article-lead">{esc(story["concept"])}</p>{diagram}<h4>本仓库怎么验证</h4>{measured}'
            f'<div class="cpu-link"><b>CPU 对应</b><p>{esc(story["cpu"])}</p></div>'
            f'<p class="limit-line"><b>当前没有证明：</b>{esc(story["limit"])}</p></div>{embedded_chart}</article>'
        )
    return "".join(result)


def insight_block(name: str, chart_keys: list[str], charts: dict, scale: dict | None = None) -> str:
    item = INSIGHTS[name]
    scale_note = ""
    if scale:
        scale_note = (f'<div class="density-strip"><span><b>{scale["agents_per_second"]:.2f}</b> Agents/s</span>'
                      f'<span><b>{scale["efficiency"]:.1f}%</b> parallel efficiency</span>'
                      f'<span><b>{scale["sum_rss_gib"]:.2f} GiB</b> summed child max RSS</span>'
                      f'<span><b>{scale["max_child_rss_mib"]:.1f} MiB</b> max child RSS</span></div>')
    return (f'<section class="insight"><div class="article-copy"><span class="chapter-kicker">{esc(item["kicker"])}</span>'
            f'<h3>{esc(item["title"])}</h3><p class="article-lead">{esc(item["intro"])}</p>{scale_note}</div>'
            + "".join(chart(charts[key]) for key in chart_keys)
            + f'<blockquote class="insight-callout">{esc(item["callout"])}</blockquote></section>')


def evidence_details(cpu: dict, workloads: dict, provenance: list[tuple[str, str]]) -> str:
    protocols = []
    for key in (f"C{number}" for number in range(1, 8)):
        protocols.append((key, cpu[key]["data"]["protocol"]["protocol_sha256"]))
    protocols.extend((f"C8/{name}", data["protocol"]["protocol_sha256"])
                     for name, data in cpu["C8"]["data"].items())
    protocol_html = "".join(f'<li><span>{esc(key)}</span><code>{esc(value)}</code></li>' for key, value in protocols)
    workload_html = "".join(f'<li><span>{esc(key)}</span><code>{esc(item["file"])}</code></li>'
                            for key, item in workloads.items())
    detail_labels = {"报告生成时 Git 状态", "Node.js", "Host", "Kernel", "perf mode"}
    environment = provenance_table([item for item in provenance if item[0] in detail_labels])
    return (f'<dl class="details-provenance">{environment}</dl>'
            '<p>W1 final-workspace evidence 由 <code>evidence/manifest.json</code> 绑定；下列是报告直接读取的 W2–W10 summaries。</p>'
            f'<div class="detail-columns"><div><h4>W evidence sources</h4><ul>{workload_html}</ul></div>'
            f'<div><h4>C protocol hashes</h4><ul>{protocol_html}</ul></div></div>')


def git_status_at_generation() -> str:
    revision = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT,
                              text=True, capture_output=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                text=True, capture_output=True, check=True).stdout.strip())
    return revision + (" + working-tree changes" if dirty else "")


def report_input_paths() -> list[Path]:
    """Return every source/data input that determines the generated report."""
    result_names = set(CPU_FILES.values()) | set(C8_FILES.values()) | set(WORKLOAD_FILES.values())
    paths = [ROOT / "results" / name for name in result_names]
    paths.append(ROOT / "evidence" / "manifest.json")
    paths.extend(HERE.glob("*.py"))
    paths.extend((HERE / "templates").glob("*.html"))
    paths.extend((HERE / "static").glob("*.css"))
    paths.extend((HERE / "static").glob("*.js"))
    return sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix())


def report_input_fingerprint() -> str:
    """Hash sorted relative-path + per-file-SHA256 records, excluding generated output."""
    digest = hashlib.sha256()
    for path in report_input_paths():
        relative = path.relative_to(ROOT).as_posix()
        file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def run_full_verification() -> None:
    subprocess.run([str(ROOT / "scripts" / "reproduce-evidence.sh")], cwd=ROOT, check=True)
    subprocess.run([str(ROOT / "scripts" / "cpu" / "verify-cpu-results.py")], cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="执行 W evidence 重放与 C result 全量校验")
    parser.add_argument("--print-input-fingerprint", action="store_true",
                        help="输出报告输入 SHA256 后退出")
    args = parser.parse_args()
    if args.print_input_fingerprint:
        print(report_input_fingerprint())
        return

    cpu = load_cpu_results()
    workloads = load_workload_results()
    charts = build_charts(cpu)
    charts_by_key = {item["key"]: item for item in charts}
    findings = build_key_findings(workloads, cpu)
    real_tasks = build_real_tasks(workloads)
    story_evidence = build_story_evidence(workloads, cpu)
    status = validate(ROOT, cpu, workloads, charts)
    if args.verify:
        run_full_verification()
        status["full_replay"] = "PASS"
    provenance = build_provenance(
        cpu, git_status_at_generation(), report_input_fingerprint(), status["full_replay"])
    summary_labels = {"报告输入指纹 / SHA256", "DeepSeek Harness", "OpenClaw", "完整证据验证"}
    provenance_summary = [item for item in provenance if item[0] in summary_labels]

    evidence = load_evidence_index()
    report = {"charts": charts, "validation": status, "generated_from": "explicit W2-W10 and C1-C8 adapters"}
    template = (HERE / "templates" / "index.html").read_text(encoding="utf-8")
    nav_items = [("conclusion", "研究结论"), ("why", "为什么需要 Harness"),
                 ("deepseek", "DeepSeek Harness"), ("experiments", "实验验证"),
                 ("cpu", "CPU 工作负载"), ("insights", "数据洞察"),
                 ("evidence", "证据与边界")]
    nav = "".join(f'<a href="#{anchor}">{label}</a>' for anchor, label in nav_items)
    validation = (f"输入与 schema 校验：{status['input_validation']} · 完整证据重放：{status['full_replay']} · "
                  f"CPU samples：{status['cpu_samples']} · W summaries：{status['workload_summaries']}")
    limitations = "".join(f"<li>{esc(item)}</li>" for item in LIMITATIONS)
    scale = story_evidence["scale"]
    html_text = (template.replace("{{NAV}}", nav)
                 .replace("{{HERO_BODY}}", esc(SECTIONS["hero_body"]))
                 .replace("{{FINDINGS}}", "".join(finding_card(item) for item in findings))
                 .replace("{{WHY_HARNESS}}", esc(SECTIONS["why_harness"]))
                 .replace("{{FEATURE_STORIES}}", feature_stories(story_evidence, charts_by_key))
                 .replace("{{REAL_TASKS}}", "".join(task_card(item) for item in real_tasks))
                 .replace("{{CPU_INTRO}}", esc(SECTIONS["cpu_intro"]))
                 .replace("{{STATE_INSIGHT}}", insight_block("state", ["C2", "C3", "C8"], charts_by_key))
                 .replace("{{EXECUTION_INSIGHT}}", insight_block("execution", ["C4", "C5"], charts_by_key))
                 .replace("{{SCALE_INSIGHT}}", insight_block("scale", ["C7"], charts_by_key, scale))
                 .replace("{{SUPPORTING_CHARTS}}", chart(charts_by_key["C1"], "support")
                          + chart(charts_by_key["C6"], "support"))
                 .replace("{{CONCLUSION_BODY}}", esc(SECTIONS["conclusion"]))
                 .replace("{{LIMITATIONS}}", limitations)
                 .replace("{{VALIDATION}}", esc(validation))
                 .replace("{{PROVENANCE}}", provenance_table(provenance_summary))
                 .replace("{{EVIDENCE_DETAILS}}", evidence_details(cpu, workloads, provenance))
                 .replace("{{EVIDENCE_FILE}}", esc(evidence["file"]))
                 .replace("{{CSS}}", (HERE / "static" / "style.css").read_text(encoding="utf-8"))
                 .replace("{{JS}}", (HERE / "static" / "charts.js").read_text(encoding="utf-8"))
                 .replace("{{DATA}}", json.dumps(report, ensure_ascii=False, separators=(",", ":"))))
    output = HERE / "dist" / "index.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_text, encoding="utf-8")
    validate_html(output)
    print(f"已构建 {output}（{len(html_text):,} bytes；8 个显式 chart adapters；"
          f"完整重放={status['full_replay']}；输入 SHA256={report_input_fingerprint()}）")


if __name__ == "__main__":
    main()
