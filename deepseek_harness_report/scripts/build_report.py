#!/usr/bin/env python3
"""Build the Markdown-first DeepSeek Harness research report and derived HTML."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "deepseek_harness_report"
RESULTS = ROOT / "results"

RESULT_FILES = {
    "w2": "w2-aggregate-n5.json", "w3": "w3-aggregate-n5.json",
    "w4": "w4-recovery-summary.json", "w5": "w5-compaction-summary.json",
    "w6": "w6-tool-failure-summary.json", "w7": "w7-long-chain-summary.json",
    "w8": "w8-code-mode-summary.json", "w9": "w9-session-summary.json",
    "w10": "w10-fs-seam-summary.json", "c1": "c1-agent-loop-pilot.json",
    "c2": "c2-session-count-pilot.json", "c3": "c3-context-json-pilot.json",
    "c4": "c4-shell-lifecycle-pilot.json", "c5": "c5-code-mode-cpu-pilot.json",
    "c6": "c6-fs-sandbox-cpu-pilot.json", "c7": "c7-agent-scaleout-pilot.json",
    "c8_cold": "c8-token-meter-cold-pilot.json",
    "c8_incremental": "c8-token-meter-incremental-pilot.json",
    "c8_repeat": "c8-token-meter-repeat-pilot.json",
    "c8_shape_schema": "c8-token-meter-shape-schema-pilot.json",
}


def load_inputs() -> dict:
    return {key: json.loads((RESULTS / name).read_text(encoding="utf-8"))
            for key, name in RESULT_FILES.items()}


def build_metrics(data: dict) -> dict:
    w2, w3, w4, w5, w6, w7, w8, w9, w10 = (data[key] for key in
        ("w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9", "w10"))
    c2, c3, c4, c5, c6, c7 = (data[key] for key in ("c2", "c3", "c4", "c5", "c6", "c7"))
    cold, repeat = data["c8_cold"], data["c8_repeat"]
    w5d, w5o = w5["calibrated_main_pair"]["deepseek_harness"], w5["calibrated_main_pair"]["openclaw"]
    w8d, w8o = w8["deepseek_harness"], w8["openclaw"]
    cold_slope = cold["linear_fits"]["internal_cpu_us_per_measure"]["per_surface_node_slope"]
    repeat_slope = repeat["linear_fits"]["internal_cpu_us_per_measure"]["per_surface_node_slope"]
    max_context = str(16 * 1024 * 1024)
    c4_count = max(c4["aggregates"]["dsh-managed"], key=int)
    c5_count = max(c5["aggregates"]["native"], key=int)
    c5_counts = sorted(set(c5["aggregates"]["native"]) & set(c5["aggregates"]["ptc"]), key=int)
    c5_crossover = None
    for low, high in zip(c5_counts, c5_counts[1:]):
        low_delta = (c5["aggregates"]["native"][low]["internal_wall_ns"]["median"] -
                     c5["aggregates"]["ptc"][low]["internal_wall_ns"]["median"])
        high_delta = (c5["aggregates"]["native"][high]["internal_wall_ns"]["median"] -
                      c5["aggregates"]["ptc"][high]["internal_wall_ns"]["median"])
        if low_delta * high_delta <= 0:
            c5_crossover = (int(low), int(high))
            break
    if c5_crossover is None:
        raise ValueError("C5 Native/PTC series have no measured crossover bracket")
    c6_count = max(c6["aggregates"]["local-write"], key=int)
    c7_agents = max(c7["aggregates"], key=int)
    child_exit = int(re.search(r"exits (\d+)", w6["scenarios"]["nonzero_child_exit"]["stimulus"]).group(1))
    return {
        "meta": {"host_machine": data["c1"]["host"]["machine"],
                 "cpu_samples_per_point": next(iter(data["c1"]["aggregates"].values()))["samples"]},
        "w2": {"dsh_success": w2["deepseek_harness"]["successes"], "dsh_total": w2["deepseek_harness"]["attempts"],
               "openclaw_success": w2["openclaw"]["successes"], "openclaw_total": w2["openclaw"]["attempts"]},
        "w3": {"dsh_success": w3["deepseek_harness"]["successes"], "dsh_total": w3["deepseek_harness"]["attempts"],
               "openclaw_success": w3["openclaw"]["successes"], "openclaw_total": w3["openclaw"]["attempts"]},
        "w4": {"dsh_requests": w4["deepseek_harness"]["provider_requests"],
               "dsh_completed": w4["deepseek_harness"]["runtime_completed"],
               "openclaw_requests": w4["openclaw"]["provider_requests"],
               "openclaw_error": w4["openclaw"]["runtime_error_kind"]},
        "w5": {"dsh_tool_calls": w5d["tool_calls"], "dsh_compactions": w5d["compaction_requests"],
               "dsh_completed": w5d["runtime_completed"], "openclaw_compactions": w5o["compaction_requests"],
               "boundaries": w5d["compaction_boundaries"]},
        "w6": {"dsh_invalid_completed": w6["scenarios"]["missing_required_argument"]["deepseek_harness"]["runtime_completed"],
               "openclaw_invalid_completed": w6["scenarios"]["missing_required_argument"]["openclaw"]["runtime_completed"],
               "dsh_nonzero_completed": w6["scenarios"]["nonzero_child_exit"]["deepseek_harness"]["runtime_completed"],
               "openclaw_nonzero_completed": w6["scenarios"]["nonzero_child_exit"]["openclaw"]["runtime_completed"],
               "child_exit_code": child_exit},
        "w7": {"tool_calls": w7["deepseek_harness"]["tool_calls"],
               "dsh_final_markers": w7["deepseek_harness"]["final_request_tool_result_count"],
               "openclaw_final_markers": w7["openclaw"]["final_request_tool_result_count"],
               "dsh_request_growth_bytes": w7["deepseek_harness"]["context"]["request_body_growth_bytes"],
               "openclaw_request_growth_bytes": w7["openclaw"]["context"]["request_body_growth_bytes"]},
        "w8": {"operations": w8d["direct"]["underlying_shell_calls"],
               "dsh_direct_calls": w8d["direct"]["model_visible_tool_calls"],
               "dsh_direct_requests": w8d["direct"]["provider_requests"],
               "dsh_code_calls": w8d["code"]["model_visible_tool_calls"],
               "dsh_code_requests": w8d["code"]["provider_requests"],
               "dsh_body_reduction_pct": w8d["paired_change"]["total_request_body_reduction_percent"],
               "openclaw_direct_requests": w8o["direct"]["provider_requests"],
               "openclaw_code_requests": w8o["code"]["provider_requests"],
               "openclaw_body_reduction_pct": w8o["paired_change"]["total_request_body_reduction_percent"]},
        "w9": {"prefix_identical": w9["crash_resume"]["checks"]["committed_prefix_byte_identical"],
               "dangling_not_dispatched": w9["crash_resume"]["checks"]["dangling_call_not_dispatched"],
               "synthetic_error": w9["crash_resume"]["synthetic_error_code"],
               "fork_equal": w9["fork"]["checks"]["derive_messages_equal_at_boundary"],
               "provider_not_contacted": w9["llm_replay"]["checks"]["provider_not_contacted_during_replay"]},
        "w10": {"local_outside": w10["local_a"]["outside"],
                "sandbox_error": w10["sandbox_b"]["tool_results"][-1]["error_code"],
                "swap_restored": w10["checks"]["a_equals_a_prime"]},
        "c2": {name: c2["linear_fits_over_event_count_medians"][name]["per_event_slope"] for name in
               ("append_cpu_us", "derive_messages_cpu_us", "fork_prefix_cpu_us",
                "jsonl_write_cpu_us", "jsonl_warm_load_cpu_us")},
        "c3": {"max_context_bytes": int(max_context),
               "json_encode_ms": c3["aggregates"][max_context]["json_encode_request_cpu_us"]["median"] / 1000,
               "json_decode_ms": c3["aggregates"][max_context]["json_decode_request_cpu_us"]["median"] / 1000,
               "sse_json_ms": c3["aggregates"][max_context]["sse_frame_and_json_decode_cpu_us"]["median"] / 1000},
        "c4": {"operation_count": int(c4_count),
               "managed": c4["aggregates"]["dsh-managed"][c4_count]["wall_ns_per_operation"]["median"] / 1_000_000,
               "raw_oneshot": c4["aggregates"]["raw-oneshot"][c4_count]["wall_ns_per_operation"]["median"] / 1_000_000,
               "persistent": c4["aggregates"]["persistent"][c4_count]["wall_ns_per_operation"]["median"] / 1_000_000},
        "c5": {"operation_count": int(c5_count),
               "native_selected_ms": c5["aggregates"]["native"][c5_count]["internal_wall_ns"]["median"] / 1_000_000,
               "ptc_selected_ms": c5["aggregates"]["ptc"][c5_count]["internal_wall_ns"]["median"] / 1_000_000,
               "crossover_low": c5_crossover[0], "crossover_high": c5_crossover[1],
               "series_ms": {mode: {count: row["internal_wall_ns"]["median"] / 1_000_000
                                     for count, row in values.items()}
                             for mode, values in c5["aggregates"].items()}},
        "c6": {"operation_count": int(c6_count),
               "wall_ratio_selected": c6["comparisons"]["write"][c6_count]["sandbox_over_local_wall_ns_per_operation"],
               "cpu_ratio_selected": c6["comparisons"]["write"][c6_count]["sandbox_over_local_cpu_us_per_operation"]},
        "c7": {"agent_count": int(c7_agents),
               "selected_agents_per_second": c7["aggregates"][c7_agents]["agents_per_second"]["median"],
               "selected_efficiency_pct": c7["scaling"][c7_agents]["parallel_efficiency"] * 100,
               "selected_sum_rss_gib": c7["aggregates"][c7_agents]["sum_child_max_rss_kb"]["median"] / 1024 / 1024,
               "selected_max_child_rss_mib": c7["aggregates"][c7_agents]["max_child_max_rss_kb"]["median"] / 1024},
        "c8": {"cold_slope": cold_slope, "repeat_slope": repeat_slope,
               "cold_repeat_ratio": cold_slope / repeat_slope},
    }


def source_revision(data: dict, key: str) -> str:
    values = set()
    for name, item in data.items():
        if not name.startswith("c"):
            continue
        value = item.get("protocol", {}).get("source_revisions", {}).get(key)
        if value:
            values.add(value)
    if len(values) != 1:
        raise ValueError(f"inconsistent or missing {key}: {sorted(values)}")
    return values.pop()


def report_input_paths() -> list[Path]:
    paths = [RESULTS / name for name in RESULT_FILES.values()]
    paths.append(ROOT / "evidence" / "manifest.json")
    paths.append(REPORT_ROOT / "report.template.md")
    paths.extend((REPORT_ROOT / "scripts").glob("*.py"))
    return sorted(paths, key=lambda path: path.relative_to(ROOT).as_posix())


def input_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in report_input_paths():
        relative = path.relative_to(ROOT).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(f"{relative}\0{file_hash}\n".encode())
    return digest.hexdigest()


def build_provenance(data: dict, strict: bool) -> dict:
    host = data["c1"]["host"]
    revision = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT,
                              text=True, capture_output=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                text=True, capture_output=True, check=True).stdout.strip())
    return {"report_input_sha256": input_fingerprint(),
            "git_status_at_generation": revision + (" + working-tree changes" if dirty else ""),
            "deepseek_harness_commit": source_revision(data, "DSH_COMMIT"),
            "openclaw_commit": source_revision(data, "OPENCLAW_COMMIT"),
            "node_version": source_revision(data, "NODE_VERSION"),
            "host": host, "perf_mode": data["c1"]["design"]["perf_mode"],
            "evidence_verification": "PASS" if strict else "NOT_RUN",
            "result_files": RESULT_FILES}


def flatten(value, prefix="") -> dict[str, str]:
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            result.update(flatten(child, f"{prefix}_{key}" if prefix else key))
    elif isinstance(value, bool):
        result[prefix.upper()] = "是" if value else "否"
    elif isinstance(value, float):
        result[prefix.upper()] = f"{value:.3f}".rstrip("0").rstrip(".")
    elif isinstance(value, list):
        pass
    else:
        result[prefix.upper()] = str(value)
    return result


def inject(template: str, metrics: dict, provenance: dict) -> str:
    values = flatten(metrics) | flatten(provenance)
    w5_rows = "\n".join(
        f'| 第 {item["after_agent_request_ordinal"]} 次 Agent request 后 | '
        f'{item["agent_body_before_bytes"]:,} B | {item["agent_body_after_bytes"]:,} B | '
        f'{item["agent_body_reduction_bytes"]:,} B |'
        for item in metrics["w5"]["boundaries"])
    values["W5_BOUNDARY_ROWS"] = w5_rows
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", template)))
    if unresolved:
        raise ValueError(f"unresolved report placeholders: {unresolved}")
    return template


def inline(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"!\[([^]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1">', escaped)
    escaped = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_to_html(markdown: str) -> tuple[str, str]:
    lines, output, toc = markdown.splitlines(), [], []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1; continue
        if line.lstrip().startswith("<"):
            output.append(line)
            index += 1; continue
        if line.startswith("```"):
            language = line[3:].strip(); block = []; index += 1
            while index < len(lines) and not lines[index].startswith("```"):
                block.append(lines[index]); index += 1
            output.append(f'<pre><code class="language-{html.escape(language)}">{html.escape(chr(10).join(block))}</code></pre>')
            index += 1; continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2)
            slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", title.lower()).strip("-")
            output.append(f'<h{level} id="{slug}">{inline(title)}</h{level}>')
            if level == 2: toc.append((slug, re.sub(r"`", "", title)))
            index += 1; continue
        if line.startswith("> "):
            block = []
            while index < len(lines) and lines[index].startswith("> "):
                block.append(lines[index][2:]); index += 1
            output.append(f'<blockquote>{"<br>".join(inline(item) for item in block)}</blockquote>'); continue
        if "|" in line and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[index + 1]):
            headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
            index += 2; rows = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")]); index += 1
            output.append("<div class=\"table-wrap\"><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in headers) +
                          "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>" for row in rows) + "</tbody></table></div>")
            continue
        if re.match(r"^[-*]\s+", line):
            items = []
            while index < len(lines) and re.match(r"^[-*]\s+", lines[index]):
                items.append(re.sub(r"^[-*]\s+", "", lines[index])); index += 1
            output.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ul>"); continue
        if re.match(r"^\d+\.\s+", line):
            items = []
            while index < len(lines) and re.match(r"^\d+\.\s+", lines[index]):
                items.append(re.sub(r"^\d+\.\s+", "", lines[index])); index += 1
            output.append("<ol>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ol>"); continue
        if line.strip() == "---":
            output.append("<hr>"); index += 1; continue
        paragraph = [line]; index += 1
        while index < len(lines) and lines[index].strip() and not re.match(r"^(#|```|> |[-*]\s+|\d+\.\s+)", lines[index]):
            if "|" in lines[index] and index + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[index + 1]): break
            paragraph.append(lines[index]); index += 1
        output.append(f'<p>{inline(" ".join(item.strip() for item in paragraph))}</p>')
    toc_html = "".join(f'<a href="#{slug}">{html.escape(title)}</a>' for slug, title in toc)
    return "\n".join(output).replace('src="figures/', 'src="../figures/'), toc_html


def html_document(body: str, toc: str) -> str:
    css = """*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:64px}body{margin:0;background:#fff;color:#17212b;font:18px/1.78 'Noto Sans CJK SC','PingFang SC','Microsoft YaHei','Segoe UI',system-ui,sans-serif}nav{position:sticky;top:0;z-index:4;padding:14px max(24px,calc((100% - 1380px)/2));display:flex;gap:18px;overflow:auto;background:#fffffff2;border-bottom:1px solid #d7dee7;backdrop-filter:blur(12px)}nav a{color:#667085;text-decoration:none;white-space:nowrap;font-size:13px}nav a:hover{color:#2563eb}main{max-width:1000px;margin:auto;padding:70px 30px}h1{font-size:58px;line-height:1.08;letter-spacing:-.025em}h2{font-size:39px;margin-top:90px;padding-top:20px;border-top:1px solid #d7dee7}h3{font-size:28px;margin-top:52px}h4{font-size:22px}p,li{color:#475467}strong,h1,h2,h3,h4{color:#17212b}code{color:#0f766e;background:#f3f6f9;padding:.12em .32em;border-radius:4px}pre{padding:22px;overflow:auto;background:#f8fafc;border:1px solid #d7dee7;border-radius:12px}pre code{background:none;color:#344054}blockquote{margin:28px 0;padding:18px 24px;border-left:4px solid #2563eb;background:#eff6ff;color:#1e3a5f;font-size:21px}img{display:block;width:min(100%,980px);margin:32px auto}.table-wrap{overflow:auto;margin:28px 0}table{width:100%;border-collapse:collapse;background:#fff}th,td{padding:13px 15px;text-align:left;border:1px solid #d7dee7;vertical-align:top}th{color:#0f766e;background:#f8fafc}hr{border:0;border-top:1px solid #d7dee7;margin:65px 0}a{color:#2563eb}sub{color:#667085}.table-wrap+ p{margin-top:20px}@media(max-width:700px){body{font-size:16px}main{padding:45px 18px}h1{font-size:42px}h2{font-size:32px}nav{padding-left:18px}}"""
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DeepSeek Harness 新特性与运行时机制调研</title><style>{css}</style></head><body><nav>{toc}</nav><main>{body}</main></body></html>\n'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="重放 W evidence 并验证 C results，不运行 benchmark")
    args = parser.parse_args()
    if args.verify:
        subprocess.run([str(ROOT / "scripts" / "reproduce-evidence.sh")], cwd=ROOT, check=True)
        subprocess.run([str(ROOT / "scripts" / "cpu" / "verify-cpu-results.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(REPORT_ROOT / "scripts" / "build_figures.py")], cwd=ROOT, check=True)
    data = load_inputs(); metrics = build_metrics(data); provenance = build_provenance(data, args.verify)
    generated = REPORT_ROOT / "generated"; generated.mkdir(parents=True, exist_ok=True)
    (generated / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (generated / "provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = inject((REPORT_ROOT / "report.template.md").read_text(encoding="utf-8"), metrics, provenance)
    (REPORT_ROOT / "report.md").write_text(report, encoding="utf-8")
    body, toc = markdown_to_html(report)
    dist = REPORT_ROOT / "dist"; dist.mkdir(parents=True, exist_ok=True)
    (dist / "report.html").write_text(html_document(body, toc), encoding="utf-8")
    subprocess.run([sys.executable, str(REPORT_ROOT / "scripts" / "validate_report.py")], cwd=ROOT, check=True)
    print(f"built report.md and dist/report.html; evidence={provenance['evidence_verification']}")


if __name__ == "__main__":
    main()
