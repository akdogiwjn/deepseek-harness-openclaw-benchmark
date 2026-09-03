#!/usr/bin/env python3
"""Generate static SVG figures from the existing explicit C-series adapters."""

from __future__ import annotations

import html
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "deepseek_harness_report"
sys.path.insert(0, str(ROOT / "harness_cpu_report"))

from data_loader import load_cpu_results  # noqa: E402
from derive import build_charts  # noqa: E402

DATA_NAMES = {
    "C2": "c2-session-cost.svg", "C3": "c3-context-serialization.svg",
    "C4": "c4-process-lifecycle.svg", "C5": "c5-native-vs-ptc.svg",
    "C6": "c6-fs-policy.svg", "C7": "c7-agent-scale.svg",
    "C8": "c8-context-pressure.svg",
}

BG, PANEL, TEXT, MUTED, GRID = "#0b151c", "#101c23", "#f2f7f5", "#a2b2b9", "#29404a"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}k"
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def svg_text(x, y, text, size=14, fill=MUTED, anchor="start", weight=400) -> str:
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}" '
            f'font-family="system-ui, sans-serif">{esc(text)}</text>')


def render_horizontal(spec: dict) -> str:
    width, height = 960, 480
    left, right, top, bottom = 190, 45, 90, 70
    points = spec["series"][0]["points"]
    maximum = max(point["y"] for point in points) * 1.1
    plot_w, slot = width - left - right, (height - top - bottom) / len(points)
    items = []
    for tick in range(6):
        value = maximum * tick / 5
        x = left + plot_w * tick / 5
        items.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{height-bottom}" stroke="{GRID}"/>')
        items.append(svg_text(x, height - 35, fmt(value), anchor="middle"))
    color = spec["series"][0]["color"]
    for index, point in enumerate(points):
        y = top + index * slot + slot * .2
        bar_w = point["y"] / maximum * plot_w
        items.append(svg_text(left - 15, y + slot * .32, point["x"], anchor="end", size=15))
        items.append(f'<rect x="{left}" y="{y}" width="{bar_w}" height="{slot*.55}" rx="6" fill="{color}"/>')
        items.append(svg_text(left + bar_w + 9, y + slot * .32, fmt(point["y"]), fill=TEXT, size=14))
    items.append(svg_text((left + width - right) / 2, height - 8,
                          f'{spec["y"]["label"]} ({spec["y"]["unit"]})', anchor="middle", weight=700))
    return svg_frame(spec, "".join(items), width, height)


def render_line(spec: dict) -> str:
    width, height = 960, 480
    left, right, top, bottom = 90, 90 if spec.get("rightAxis") else 40, 100, 72
    all_points = [point for series in spec["series"] for point in series["points"]]
    transform = (lambda value: math.log10(float(value))) if spec["x"]["scale"] == "log" else (
        (lambda value: math.log10(float(value) + 1)) if spec["x"]["scale"] == "log1p" else lambda value: float(value))
    x_values = [transform(point["x"]) for point in all_points]
    x_min, x_max = min(x_values), max(x_values)
    left_points = [point for series in spec["series"] if series.get("axis") != "right" for point in series["points"]]
    right_points = [point for series in spec["series"] if series.get("axis") == "right" for point in series["points"]]
    y_max = max([point.get("high", point["y"]) for point in left_points] + [0]) or 1
    r_max = spec.get("rightAxis", {}).get("max") or (max([p["y"] for p in right_points] + [1]))
    plot_w, plot_h = width - left - right, height - top - bottom
    sx = lambda value: left + (transform(value) - x_min) / (x_max - x_min or 1) * plot_w
    sy = lambda value, axis="left": top + plot_h - float(value) / (r_max if axis == "right" else y_max) * plot_h
    items = []
    for tick in range(6):
        y = top + plot_h * tick / 5
        items.append(f'<line x1="{left}" y1="{y}" x2="{width-right}" y2="{y}" stroke="{GRID}"/>')
        items.append(svg_text(left - 12, y + 5, fmt(y_max * (1 - tick / 5)), anchor="end"))
        if right_points:
            items.append(svg_text(width - right + 12, y + 5, fmt(r_max * (1 - tick / 5))))
    ticks = spec.get("xTicks") or sorted({point["x"] for point in all_points})
    stride = max(1, math.ceil(len(ticks) / 7))
    for index, value in enumerate(ticks):
        if index % stride and index != len(ticks) - 1:
            continue
        items.append(svg_text(sx(value), height - 35, fmt(float(value)), anchor="middle"))
    for series in spec["series"]:
        axis = series.get("axis", "left")
        coords = [(sx(point["x"]), sy(point["y"], axis)) for point in series["points"]]
        path = " ".join(("M" if index == 0 else "L") + f"{x:.1f},{y:.1f}" for index, (x, y) in enumerate(coords))
        items.append(f'<path d="{path}" fill="none" stroke="{series["color"]}" stroke-width="4" stroke-linecap="round"/>')
        for point, (x, y) in zip(series["points"], coords):
            if "low" in point and "high" in point:
                items.append(f'<line x1="{x}" y1="{sy(point["low"], axis)}" x2="{x}" y2="{sy(point["high"], axis)}" stroke="{series["color"]}" opacity=".5" stroke-width="2"/>')
            items.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{series["color"]}" stroke="{BG}" stroke-width="2"/>')
    legend_x = left
    for series in spec["series"]:
        items.append(f'<circle cx="{legend_x}" cy="72" r="6" fill="{series["color"]}"/>')
        items.append(svg_text(legend_x + 12, 77, series["name"], size=15, fill=TEXT))
        legend_x += 35 + len(series["name"]) * 10
    items.append(svg_text((left + width - right) / 2, height - 7, spec["x"]["label"], anchor="middle", weight=700))
    items.append(svg_text(18, 25, f'{spec["y"]["label"]} ({spec["y"]["unit"]})', weight=700))
    if right_points:
        items.append(svg_text(width - 12, 25, f'{spec["rightAxis"]["label"]} ({spec["rightAxis"]["unit"]})', anchor="end", weight=700))
    return svg_frame(spec, "".join(items), width, height)


def svg_frame(spec: dict, body: str, width: int, height: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(spec["title"])}">'
            f'<rect width="100%" height="100%" rx="20" fill="{PANEL}"/>'
            f'{svg_text(28, 42, spec["title"], size=24, fill=TEXT, weight=800)}{body}</svg>\n')


def architecture_figures() -> dict[str, str]:
    common = 'font-family="system-ui,sans-serif" text-anchor="middle"'
    return {
        "harness-model.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 360"><rect width="960" height="360" rx="22" fill="{PANEL}"/><g {common} fill="{TEXT}"><text x="480" y="44" font-size="25" font-weight="800">Model 决策，Harness 执行并维持状态</text><rect x="65" y="120" width="150" height="72" rx="12" fill="#14242c" stroke="#5aa7ff"/><text x="140" y="163" font-size="20">User</text><path d="M220 156H310" stroke="#46c8b3" stroke-width="4"/><rect x="315" y="88" width="220" height="138" rx="16" fill="#14242c" stroke="#46c8b3"/><text x="425" y="145" font-size="23" font-weight="700">Harness</text><text x="425" y="180" font-size="16" fill="{MUTED}">Loop · Context · Policy</text><path d="M540 130H640" stroke="#46c8b3" stroke-width="4"/><path d="M540 185H640" stroke="#46c8b3" stroke-width="4"/><rect x="645" y="80" width="210" height="70" rx="12" fill="#14242c" stroke="#5aa7ff"/><text x="750" y="123" font-size="20">Model</text><rect x="645" y="170" width="210" height="105" rx="12" fill="#14242c" stroke="#a98bff"/><text x="750" y="210" font-size="20">Tool · Process</text><text x="750" y="243" font-size="16" fill="{MUTED}">Session · Filesystem</text></g></svg>''',
        "capability-seam.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 390"><rect width="960" height="390" rx="22" fill="{PANEL}"/><g {common} fill="{TEXT}"><text x="480" y="45" font-size="25" font-weight="800">Consumer 与 Provider 分离</text><rect x="355" y="80" width="250" height="58" rx="12" fill="#14242c" stroke="#46c8b3"/><text x="480" y="117" font-size="20">Agent Loop → tool-fs</text><path d="M480 140V195" stroke="#46c8b3" stroke-width="4"/><rect x="380" y="195" width="200" height="58" rx="12" fill="#14242c" stroke="#46c8b3"/><text x="480" y="232" font-size="21">ctx.fs</text><path d="M480 255V285M480 285H250M480 285H710M250 285V310M710 285V310" stroke="#46c8b3" stroke-width="4" fill="none"/><rect x="120" y="310" width="260" height="58" rx="12" fill="#14242c" stroke="#5aa7ff"/><text x="250" y="346" font-size="19">fs-local · outside ✓</text><rect x="580" y="310" width="260" height="58" rx="12" fill="#14242c" stroke="#ed7474"/><text x="710" y="346" font-size="19">fs-sandbox · outside ✕</text></g></svg>''',
        "event-log.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 420"><rect width="960" height="420" rx="22" fill="{PANEL}"/><g {common} fill="{TEXT}"><text x="480" y="42" font-size="25" font-weight="800">Session Event Log → Model Projection 与恢复语义</text><g font-size="16">{''.join(f'<rect x="{55+i*143}" y="95" width="125" height="55" rx="9" fill="#14242c" stroke="#46c8b3"/><text x="{117+i*143}" y="129">{name}</text>' for i,name in enumerate(["turn/start","user/message","tool/call","tool/result","step/end","turn/end"]))}</g><path d="M480 160V225" stroke="#46c8b3" stroke-width="4"/><rect x="330" y="225" width="300" height="62" rx="12" fill="#14242c" stroke="#5aa7ff"/><text x="480" y="264" font-size="21">deriveMessages() → Context</text><g font-size="19">{''.join(f'<rect x="{100+i*210}" y="330" width="160" height="55" rx="10" fill="#14242c" stroke="#a98bff"/><text x="{180+i*210}" y="365">{name}</text>' for i,name in enumerate(["Resume","Fork","Replay","Traceability"]))}</g></g></svg>''',
        "ptc.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 390"><rect width="960" height="390" rx="22" fill="{PANEL}"/><g {common} fill="{TEXT}"><text x="480" y="45" font-size="25" font-weight="800">Executor Collapse：改变模型可见的编排粒度</text><text x="245" y="95" font-size="21" fill="#5aa7ff">Direct Tool Calling</text><text x="715" y="95" font-size="21" fill="#a98bff">Programmatic Tool Calling</text><g font-size="18">{''.join(f'<rect x="{70+i*95}" y="140" width="75" height="52" rx="9" fill="#14242c" stroke="#5aa7ff"/><text x="{107+i*95}" y="173">{name}</text>' for i,name in enumerate(["LLM","Tool","LLM","Tool"]))}<rect x="610" y="132" width="210" height="62" rx="11" fill="#14242c" stroke="#a98bff"/><text x="715" y="170" font-size="20">LLM → Program</text><rect x="575" y="235" width="280" height="86" rx="13" fill="#14242c" stroke="#46c8b3"/><text x="715" y="270" font-size="19">Tool · Tool · Tool · Tool</text><text x="715" y="300" font-size="15" fill="{MUTED}">local code runtime dispatch</text></g><text x="480" y="365" font-size="22" font-weight="800" fill="#46c8b3">底层操作不消失，外层 round trip 被折叠</text></g></svg>''',
        "feature-to-cpu.svg": f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 410"><rect width="960" height="410" rx="22" fill="{PANEL}"/><g {common} fill="{TEXT}"><text x="480" y="42" font-size="25" font-weight="800">Feature → Runtime Mechanism → Host CPU Workload</text>{''.join(f'<rect x="{45+i*230}" y="90" width="190" height="80" rx="12" fill="#14242c" stroke="{color}"/><text x="{140+i*230}" y="125" font-size="19" font-weight="700">{name}</text><text x="{140+i*230}" y="151" font-size="14" fill="{MUTED}">{sub}</text><path d="M{140+i*230} 175V235" stroke="{color}" stroke-width="4"/>' for i,(name,sub,color) in enumerate([("Control","Loop · Recovery","#5aa7ff"),("State","Event · Context","#46c8b3"),("Execution","Tool · Process","#a98bff"),("Scale","Multi-Agent","#f0b75a")]))}{''.join(f'<rect x="{45+i*230}" y="235" width="190" height="105" rx="12" fill="#14242c" stroke="{color}"/><text x="{140+i*230}" y="275" font-size="17">{line1}</text><text x="{140+i*230}" y="306" font-size="15" fill="{MUTED}">{line2}</text>' for i,(line1,line2,color) in enumerate([("C1","Agent steps","#5aa7ff"),("C2 · C3 · C8","state surface","#46c8b3"),("C4 · C5 · C6","boundaries","#a98bff"),("C7","density","#f0b75a")]))}</g></svg>''',
    }


def main() -> None:
    data_dir = REPORT_ROOT / "figures" / "data"
    arch_dir = REPORT_ROOT / "figures" / "architecture"
    data_dir.mkdir(parents=True, exist_ok=True)
    arch_dir.mkdir(parents=True, exist_ok=True)
    charts = {chart["key"]: chart for chart in build_charts(load_cpu_results())}
    for key, filename in DATA_NAMES.items():
        renderer = render_horizontal if charts[key]["type"] == "horizontal-bar" else render_line
        (data_dir / filename).write_text(renderer(charts[key]), encoding="utf-8")
    for filename, content in architecture_figures().items():
        (arch_dir / filename).write_text(content + "\n", encoding="utf-8")
    print(f"generated {len(DATA_NAMES)} data and 5 architecture SVG figures")


if __name__ == "__main__":
    main()
