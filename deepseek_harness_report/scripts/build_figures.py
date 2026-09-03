#!/usr/bin/env python3
"""Generate data SVGs from pinned results; architecture SVGs are curated assets."""

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

LIGHT_THEME = {
    "bg": "#FFFFFF", "panel": "#F8FAFC", "panel2": "#F3F6F9",
    "text": "#17212B", "muted": "#667085", "border": "#D7DEE7", "grid": "#E8EDF3",
    "blue": "#2563EB", "blue_fill": "#EFF6FF", "teal": "#0F766E", "teal_fill": "#ECFDF5",
    "purple": "#7C5CE7", "purple_fill": "#F5F3FF", "amber": "#B7791F", "amber_fill": "#FFFBEB",
    "success": "#2E7D32", "success_fill": "#F0FDF4", "error": "#C2413A", "error_fill": "#FEF2F2",
    "slate": "#64748B",
}
FONT = "'Noto Sans CJK SC','PingFang SC','Microsoft YaHei','Segoe UI',system-ui,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Consolas,monospace"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def svg_open(width: int, height: int, benchmark: str | None = None, series_count: int | None = None) -> list[str]:
    metadata = ((f' data-benchmark="{benchmark}" data-series-count="{series_count}"')
                if benchmark is not None else "")
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img"{metadata}>',
            f'<rect width="{width}" height="{height}" fill="{LIGHT_THEME["bg"]}"/>',
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#64748B"/></marker></defs>']


def svg_text(x, y, value, size=17, fill=None, anchor="middle", weight=400, mono=False) -> str:
    family = MONO if mono else FONT
    return (f'<text x="{x}" y="{y}" fill="{fill or LIGHT_THEME["text"]}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}" font-family="{family}">{esc(value)}</text>')


def svg_multiline_text(x, y, lines, size=18, fill=None, anchor="middle", weight=400, line_height=1.35, mono=False) -> str:
    family = MONO if mono else FONT
    spans = "".join(f'<tspan x="{x}" dy="{0 if i == 0 else size * line_height}">{esc(line)}</tspan>'
                    for i, line in enumerate(lines[:2]))
    return (f'<text x="{x}" y="{y}" fill="{fill or LIGHT_THEME["text"]}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}" font-family="{family}">{spans}</text>')


def svg_rect(x, y, width, height, fill=None, stroke=None, rx=10, stroke_width=1.8) -> str:
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" '
            f'fill="{fill or LIGHT_THEME["panel"]}" stroke="{stroke or LIGHT_THEME["border"]}" stroke-width="{stroke_width}"/>')


def svg_arrow(x1, y1, x2, y2, dashed=False, color=None) -> str:
    dash = ' stroke-dasharray="6 6"' if dashed else ""
    return (f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="{color or LIGHT_THEME["slate"]}" '
            f'stroke-width="2" marker-end="url(#arrow)"{dash}/>' )


def svg_badge(x, y, value, fill=None, color=None, width=145) -> str:
    return svg_rect(x, y, width, 32, fill or LIGHT_THEME["panel2"], color or LIGHT_THEME["border"], 16, 1.4) + svg_text(x + width / 2, y + 22, value, 15, color or LIGHT_THEME["muted"], weight=650)


def finish(parts: list[str]) -> str:
    return "".join(parts) + "</svg>\n"


def fmt(value: float) -> str:
    if abs(value)>=1_000_000:return f"{value/1_000_000:.1f}M"
    if abs(value)>=1_000:return f"{value/1_000:.1f}k"
    if abs(value)>=100:return f"{value:.0f}"
    if abs(value)>=10:return f"{value:.1f}"
    return f"{value:.3g}"


def line_panel(spec, series, x, y, width, height, log_x=False, log_y=False, x_ticks=None, y_label="", x_label=""):
    left,right,top,bottom=80,30,35,62; plot_w=width-left-right;plot_h=height-top-bottom
    points=[p for s in series for p in s["points"]]
    tx=(lambda v:math.log10(float(v)+1)) if spec["x"]["scale"]=="log1p" else ((lambda v:math.log10(float(v))) if log_x else lambda v:float(v))
    ty=(lambda v:math.log10(max(float(v),1e-9))) if log_y else lambda v:float(v)
    xmin,xmax=min(tx(p["x"]) for p in points),max(tx(p["x"]) for p in points); ymin=min(ty(p["y"]) for p in points); ymax=max(ty(p.get("high",p["y"])) for p in points)
    if not log_y:ymin=0
    sx=lambda v:x+left+(tx(v)-xmin)/(xmax-xmin or 1)*plot_w
    sy=lambda v:y+top+plot_h-(ty(v)-ymin)/(ymax-ymin or 1)*plot_h
    parts=[]
    for i in range(5):
        yy=y+top+i*plot_h/4; val=ymax-i*(ymax-ymin)/4
        parts += [f'<line x1="{x+left}" y1="{yy}" x2="{x+width-right}" y2="{yy}" stroke="{LIGHT_THEME["grid"]}"/>',svg_text(x+left-10,yy+5,fmt(10**val if log_y else val),15,LIGHT_THEME["muted"],"end")]
    ticks=x_ticks or sorted({p["x"] for p in points});stride=max(1,math.ceil(len(ticks)/7))
    for i,v in enumerate(ticks):
        if i%stride and i!=len(ticks)-1:continue
        parts.append(svg_text(sx(v),y+height-28,fmt(float(v)),15,LIGHT_THEME["muted"]))
    for s in series:
        coords=[(sx(p["x"]),sy(p["y"])) for p in s["points"]]; path=" ".join(("M" if i==0 else "L")+f"{xx:.1f},{yy:.1f}" for i,(xx,yy) in enumerate(coords))
        parts.append(f'<path d="{path}" fill="none" stroke="{s["color"]}" stroke-width="3" stroke-linecap="round"/>')
        for xx,yy in coords:parts.append(f'<circle cx="{xx}" cy="{yy}" r="5" fill="#FFFFFF" stroke="{s["color"]}" stroke-width="2.5"/>')
    parts += [svg_text(x+left+plot_w/2,y+height-5,x_label,17,weight=700),svg_text(x+8,y+18,y_label,17,anchor="start",weight=700)]
    return "".join(parts)


def data_c2(spec):
    pts=sorted(spec["series"][0]["points"],key=lambda p:p["y"],reverse=True);p=svg_open(980,450,"C2",len(spec["series"]));left,right,top,bottom=210,120,35,60;minimum=.08;maximum=30
    sx=lambda v:left+(math.log10(v)-math.log10(minimum))/(math.log10(maximum)-math.log10(minimum))*(980-left-right)
    for tick in [.1,.3,1,3,10,30]:p += [f'<line x1="{sx(tick)}" y1="{top}" x2="{sx(tick)}" y2="{390}" stroke="{LIGHT_THEME["grid"]}"/>',svg_text(sx(tick),420,fmt(tick),15,LIGHT_THEME["muted"])]
    for i,pt in enumerate(pts):
        y=65+i*62;p += [svg_text(left-18,y+5,pt["x"],16,anchor="end"),f'<line x1="{sx(minimum)}" y1="{y}" x2="{sx(pt["y"])}" y2="{y}" stroke="{LIGHT_THEME["teal"]}" stroke-width="2"/>',f'<circle cx="{sx(pt["y"])}" cy="{y}" r="7" fill="{LIGHT_THEME["teal"]}"/>',svg_text(sx(pt["y"])+13,y+5,fmt(pt["y"]),15,LIGHT_THEME["teal"],anchor="start",weight=700)]
    p.append(svg_text(490,447,"每事件 CPU slope（μs/event）· 对数刻度",17,weight=700));return finish(p)


def data_c3(spec):
    p=svg_open(980,500,"C3",len(spec["series"]));p.append(line_panel(spec,spec["series"],0,40,980,445,True,False,y_label="内部 CPU 时间（ms）",x_label="Context 大小（Bytes）· 对数刻度"))
    x=spec["series"][2]["points"][-1];mib=x["x"]/(1024*1024);p += [svg_badge(690,55,f'{mib:g} MiB · SSE+JSON {x["y"]:.1f} ms',LIGHT_THEME["amber_fill"],LIGHT_THEME["amber"],250)]
    labels={"JSON encode":"JSON 编码","JSON decode":"JSON 解码","SSE + JSON decode":"SSE 流解析 + JSON 解码"}
    for i,s in enumerate(spec["series"]):p += [f'<circle cx="{100+i*210}" cy="30" r="6" fill="{s["color"]}"/>',svg_text(115+i*210,35,labels.get(s["name"],s["name"]),16,anchor="start")]
    return finish(p)


def data_c4(spec):
    labels={"DSH managed":"DSH 管理路径","Raw one-shot":"直接单次进程","Persistent":"持久进程"}
    rows=[(labels.get(s["name"],s["name"]),s["points"][-1]["y"],s["color"]) for s in spec["series"]];p=svg_open(980,330,"C4",len(spec["series"]));left,right=230,130;minimum=.04;maximum=6;sx=lambda v:left+(math.log10(v)-math.log10(minimum))/(math.log10(maximum)-math.log10(minimum))*(980-left-right)
    for tick in [.05,.1,.3,1,3]:p += [f'<line x1="{sx(tick)}" y1="25" x2="{sx(tick)}" y2="270" stroke="{LIGHT_THEME["grid"]}"/>',svg_text(sx(tick),305,fmt(tick),15,LIGHT_THEME["muted"])]
    for i,(name,value,color) in enumerate(rows):y=70+i*75;p += [svg_text(left-18,y+5,name,17,anchor="end"),f'<line x1="{sx(minimum)}" y1="{y}" x2="{sx(value)}" y2="{y}" stroke="{color}" stroke-width="2"/>',f'<circle cx="{sx(value)}" cy="{y}" r="8" fill="{color}"/>',svg_text(sx(value)+14,y+5,f'{value:.3f}',16,color,anchor="start",weight=700)]
    count=int(spec["series"][0]["points"][-1]["x"]);p.append(svg_text(490,327,f"单次实际耗时（ms/op）· 对数刻度 · {count} 次微操作",17,weight=700));return finish(p)


def data_c5(spec):
    p=svg_open(980,500,"C5",len(spec["series"]));series_maps=[{point["x"]:point["y"] for point in series["points"]} for series in spec["series"]]
    common=sorted(set(series_maps[0]) & set(series_maps[1])); bracket=None
    for low,high in zip(common,common[1:]):
        if (series_maps[0][low]-series_maps[1][low])*(series_maps[0][high]-series_maps[1][high]) <= 0:
            bracket=(low,high);break
    if bracket:
        tx=lambda value:math.log10(float(value)+1);xmin,xmax=tx(min(common)),tx(max(common));sx=lambda value:80+(tx(value)-xmin)/(xmax-xmin)*870
        x1,x2=sx(bracket[0]),sx(bracket[1]);p += [f'<rect x="{x1:.1f}" y="70" width="{x2-x1:.1f}" height="353" fill="{LIGHT_THEME["amber_fill"]}" opacity=".8"/>',f'<line x1="{x1:.1f}" y1="70" x2="{x1:.1f}" y2="423" stroke="{LIGHT_THEME["amber"]}" stroke-dasharray="5 5"/>',f'<line x1="{x2:.1f}" y1="70" x2="{x2:.1f}" y2="423" stroke="{LIGHT_THEME["amber"]}" stroke-dasharray="5 5"/>']
    p.append(line_panel(spec,spec["series"],0,35,980,450,False,False,y_label="实际耗时（ms）",x_label="操作数（对数刻度）"))
    p += [svg_text(105,92,"低操作数：PTC 固定启动成本更明显",15,LIGHT_THEME["muted"],anchor="start"),svg_text(925,118,"高操作数：减少重复编排的收益更明显",15,LIGHT_THEME["muted"],anchor="end")]
    if bracket:p.append(svg_text((x1+x2)/2,150,f"{int(bracket[0])}–{int(bracket[1])} 性能反转区间",15,LIGHT_THEME["amber"],weight=700))
    labels={"Native":"常规 Tool 调用","PTC":"PTC / Code Mode"}
    for i,s in enumerate(spec["series"]):p += [f'<circle cx="{120+i*210}" cy="25" r="6" fill="{s["color"]}"/>',svg_text(135+i*210,30,labels.get(s["name"],s["name"]),16,anchor="start")]
    return finish(p)


def data_c6(spec):
    labels={"Local write":"Local 文件写入","Sandbox write":"Sandbox 文件写入"}
    rows=[(labels.get(s["name"],s["name"]),s["points"][-1]["y"],s["color"]) for s in spec["series"]]
    p=svg_open(980,280,"C6",len(spec["series"]));left,right=250,110
    maximum=max(value for _,value,_ in rows)*1.2
    sx=lambda value:left+float(value)/maximum*(980-left-right)
    for i in range(5):
        value=maximum*i/4
        p += [f'<line x1="{sx(value):.1f}" y1="25" x2="{sx(value):.1f}" y2="215" stroke="{LIGHT_THEME["grid"]}"/>',
              svg_text(sx(value),247,fmt(value),15,LIGHT_THEME["muted"])]
    for i,(name,value,color) in enumerate(rows):
        y=75+i*85
        p += [svg_text(left-18,y+5,name,17,anchor="end"),
              f'<line x1="{sx(0):.1f}" y1="{y}" x2="{sx(value):.1f}" y2="{y}" stroke="{color}" stroke-width="2"/>',
              f'<circle cx="{sx(value):.1f}" cy="{y}" r="8" fill="{color}"/>',
              svg_text(sx(value)+14,y+5,f'{value:.1f}',16,color,anchor="start",weight=700)]
    count=int(spec["series"][0]["points"][-1]["x"])
    p.append(svg_text(490,277,f"单次实际耗时（μs/op） · {count} 次允许写入",17,weight=700))
    return finish(p)


def data_c7(spec, cpu):
    p=svg_open(980,650,"C7",len(spec["series"]));throughput=[spec["series"][0]];efficiency=[spec["series"][1]]
    p.append(line_panel(spec,throughput,0,30,980,285,False,False,y_label="吞吐（Agents/s）",x_label=""));p.append(line_panel(spec,efficiency,0,325,980,285,False,False,y_label="并行效率（%）",x_label="Agent 数"))
    d=cpu["C7"]["data"];last=max(d["aggregates"],key=int);p += [svg_badge(650,45,f'{last} Agents · {d["aggregates"][last]["agents_per_second"]["median"]:.2f} Agents/s',LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"],280),svg_badge(690,355,f'{d["scaling"][last]["parallel_efficiency"]*100:.1f}% 并行效率',LIGHT_THEME["amber_fill"],LIGHT_THEME["amber"],240)]
    return finish(p)


def data_c8(spec, cpu):
    p=svg_open(980,800,"C8",len(spec["series"]))
    p.append(svg_text(25,25,"首次从完整历史建立状态的成本明显更高",17,anchor="start",weight=750))
    fills=(LIGHT_THEME["blue_fill"],LIGHT_THEME["teal_fill"],LIGHT_THEME["purple_fill"])
    labels=("Cold · 历史重建", "Incremental · 新增后计量", "Warm Repeat · 状态不变")
    for i,(item,label,fill) in enumerate(zip(spec["series"],labels,fills)):
        selected=item["points"][-1]["y"] / 1000
        p.append(svg_badge(25+i*318,38,f"{label} · {selected:.1f} ms",fill,item["color"],292))
    p.append(line_panel(spec,spec["series"],0,75,980,330,True,True,spec.get("xTicks"),
                        "单次计量 CPU 时间（μs）· 对数刻度","Context 规模 · 对数刻度"))
    p.append(svg_text(25,440,"已有计量状态后，Incremental 与 Warm Repeat 成本接近",17,
                      anchor="start",weight=750))
    p.append(line_panel(spec,spec["series"][1:],0,450,980,320,True,False,spec.get("xTicks"),
                        "单次计量 CPU 时间（μs）","Context 规模 · 对数刻度"))
    p.append(svg_text(25,795,"注：Incremental 横轴使用计量过程中经历的平均 Context 规模。",
                      14,LIGHT_THEME["muted"],anchor="start"))
    return finish(p)


def build_data_figures(cpu: dict) -> dict[str, str]:
    charts={c["key"]:c for c in build_charts(cpu)}
    return {"c2-session-cost.svg":data_c2(charts["C2"]),"c3-context-serialization.svg":data_c3(charts["C3"]),"c4-process-lifecycle.svg":data_c4(charts["C4"]),"c5-native-vs-ptc.svg":data_c5(charts["C5"]),"c6-fs-policy.svg":data_c6(charts["C6"]),"c7-agent-scale.svg":data_c7(charts["C7"],cpu),"c8-context-pressure.svg":data_c8(charts["C8"],cpu)}


def main() -> None:
    data_dir=REPORT_ROOT/"figures"/"data";data_dir.mkdir(parents=True,exist_ok=True)
    data=build_data_figures(load_cpu_results())
    for name,content in data.items():(data_dir/name).write_text(content,encoding="utf-8")
    print(f"generated {len(data)} data SVG figures; architecture SVGs are curated static assets")


if __name__=="__main__":main()
