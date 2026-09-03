#!/usr/bin/env python3
"""Generate light technical-report SVGs from pinned report data and adapters."""

from __future__ import annotations

import html
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = ROOT / "deepseek_harness_report"
sys.path.insert(0, str(ROOT / "harness_cpu_report"))

from data_loader import load_cpu_results, load_workload_results  # noqa: E402
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


def architecture_harness_model() -> str:
    p = svg_open(980, 540)
    p += [svg_rect(390, 30, 200, 82, LIGHT_THEME["blue_fill"], LIGHT_THEME["blue"]),
          svg_text(490, 64, "Model", 22, weight=750), svg_text(490, 91, "推理 / 决策", 16, LIGHT_THEME["muted"]),
          svg_rect(315, 190, 350, 150, LIGHT_THEME["panel"], LIGHT_THEME["blue"]),
          svg_text(490, 226, "Harness", 22, weight=780), svg_text(490, 263, "Agent Loop · Context Assembly", 17),
          svg_text(490, 295, "Recovery · Policy", 17), svg_arrow(490, 188, 490, 118),
          svg_text(610, 150, "request / response", 15, LIGHT_THEME["muted"]),
          svg_rect(35, 222, 150, 72, LIGHT_THEME["panel2"], LIGHT_THEME["slate"]), svg_text(110, 265, "User", 21, weight=700),
          svg_arrow(190, 258, 308, 258),
          svg_rect(135, 420, 300, 95, LIGHT_THEME["teal_fill"], LIGHT_THEME["teal"]),
          svg_text(285, 454, "State", 21, weight=750), svg_text(285, 483, "Session · Event Log · Context", 16),
          svg_rect(545, 400, 330, 115, LIGHT_THEME["purple_fill"], LIGHT_THEME["purple"]),
          svg_text(710, 434, "Execution", 21, weight=750), svg_text(710, 463, "Tool · Process · Filesystem", 16),
          svg_text(710, 491, "Code Runtime", 16), svg_arrow(420, 345, 310, 414), svg_arrow(565, 345, 680, 394)]
    return finish(p)


def architecture_composition_tree() -> str:
    p = svg_open(980, 570)
    nodes = [(350, 25, 280, 62, "Profile", "named composition", LIGHT_THEME["blue_fill"], LIGHT_THEME["blue"]),
             (280, 125, 420, 78, "Ordered Bundles", "base · sdk · profile bundles", LIGHT_THEME["teal_fill"], LIGHT_THEME["teal"]),
             (260, 245, 460, 82, "Patch Layers", "profile → home → CLI --patch", LIGHT_THEME["amber_fill"], LIGHT_THEME["amber"]),
             (300, 370, 380, 72, "Cordis Plugin Tree", "mounted runtime composition", LIGHT_THEME["purple_fill"], LIGHT_THEME["purple"])]
    for x, y, w, h, title, sub, fill, stroke in nodes:
        p += [svg_rect(x, y, w, h, fill, stroke),
              svg_text(x+w/2, y+29, title, 21, weight=750), svg_text(x+w/2, y+54, sub, 15, LIGHT_THEME["muted"])]
    p += [svg_arrow(490, 90, 490, 120), svg_arrow(490, 207, 490, 240), svg_arrow(490, 332, 490, 365),
          svg_rect(90, 490, 800, 58, LIGHT_THEME["teal_fill"], LIGHT_THEME["teal"]),
          svg_text(490, 526, "ctx.llm · ctx.sessions · ctx.fs · ctx.tools · ctx.agentLoop · …", 18, mono=True),
          svg_arrow(490, 447, 490, 485)]
    return finish(p)


def architecture_capability_seam(w10: dict) -> str:
    allowed = w10["local_a"]["outside"] == "OUTSIDE_CHANGED"
    denied = w10["sandbox_b"]["tool_results"][-1]["error_code"] == "FS_SANDBOX_DENIED"
    restored = w10["checks"]["a_equals_a_prime"]
    p = svg_open(980, 560)
    layers = [(350, 25, 280, 70, "Consumer", "tool-fs", LIGHT_THEME["blue_fill"], LIGHT_THEME["blue"]),
              (350, 145, 280, 70, "Capability / Service", "ctx.fs", LIGHT_THEME["teal_fill"], LIGHT_THEME["teal"])]
    for x,y,w,h,title,sub,fill,stroke in layers:
        p += [svg_rect(x,y,w,h,fill,stroke), svg_text(490,y+29,title,17,LIGHT_THEME["muted"]), svg_text(490,y+55,sub,21,weight=750,mono=sub.startswith("ctx"))]
    p += [svg_arrow(490, 100, 490, 140), svg_arrow(490, 220, 285, 285), svg_arrow(490, 220, 695, 285),
          svg_rect(145, 290, 280, 72, LIGHT_THEME["blue_fill"], LIGHT_THEME["blue"]), svg_text(285,318,"Provider",16,LIGHT_THEME["muted"]), svg_text(285,345,"fs-local",20,weight=750,mono=True),
          svg_rect(555, 290, 280, 72, LIGHT_THEME["panel2"], LIGHT_THEME["slate"]), svg_text(695,318,"Provider",16,LIGHT_THEME["muted"]), svg_text(695,345,"fs-sandbox",20,weight=750,mono=True)]
    p += [svg_text(85, 415, "W10", 17, LIGHT_THEME["amber"], anchor="start", weight=750)]
    states = [(155,"local", "outside write ✓" if allowed else "N/A", LIGHT_THEME["success_fill"],LIGHT_THEME["success"]),
              (405,"sandbox", "outside write ✕" if denied else "N/A", LIGHT_THEME["error_fill"],LIGHT_THEME["error"]),
              (655,"local", "outside write ✓" if restored else "N/A", LIGHT_THEME["success_fill"],LIGHT_THEME["success"])]
    for i,(x,title,sub,fill,stroke) in enumerate(states):
        p += [svg_rect(x,435,170,80,fill,stroke),svg_text(x+85,466,title,18,weight=750,mono=True),svg_text(x+85,494,sub,15,stroke)]
        if i < 2: p.append(svg_arrow(x+175,475,x+240,475))
    return finish(p)


def architecture_event_log() -> str:
    p = svg_open(980, 650)
    p += [svg_rect(40,25,900,305,LIGHT_THEME["panel"],LIGHT_THEME["border"]),
          svg_text(75,58,"Turn",20,anchor="start",weight=780),
          svg_rect(75,82,830,105,LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"]),svg_text(100,112,"Step 1",18,anchor="start",weight=750)]
    labels = ["user/message","assistant/message","tool/call","tool/result","step/end"]
    xs = [100,260,445,600,755]
    widths = [135,160,135,135,120]
    for i,(x,label) in enumerate(zip(xs,labels)):
        width = widths[i]
        p += [svg_rect(x,130,width,38,LIGHT_THEME["bg"],LIGHT_THEME["border"],8,1.4),svg_text(x+width/2,155,label,15,mono=True)]
        if i < len(labels)-1: p.append(svg_arrow(x+width+4,149,xs[i+1]-6,149))
    p += [svg_rect(75,205,830,78,LIGHT_THEME["teal_fill"],LIGHT_THEME["teal"]),svg_text(100,235,"Step 2",18,anchor="start",weight=750),
          svg_text(490,260,"Model Request → assistant/message → step/end",16,mono=True),
          svg_text(490,315,"turn/end",17,LIGHT_THEME["muted"],mono=True),
          svg_arrow(490,335,490,385),svg_rect(330,390,320,65,LIGHT_THEME["teal_fill"],LIGHT_THEME["teal"]),svg_text(490,430,"Session Event Log",21,weight=780),
          svg_arrow(430,460,250,515),svg_arrow(470,460,430,515,True),svg_arrow(510,460,590,515,True),svg_arrow(550,460,750,515,True)]
    outputs=[(125,"deriveMessages()","Model Context",LIGHT_THEME["blue"]),(345,"Resume","repair / continue",LIGHT_THEME["teal"]),(565,"Fork","shared prefix",LIGHT_THEME["purple"]),(745,"Replay","recorded stream",LIGHT_THEME["amber"])]
    for x,title,sub,color in outputs:
        p += [svg_rect(x,520,180,82,LIGHT_THEME["bg"],LIGHT_THEME["border"],10,1.2),
              f'<circle cx="{x+22}" cy="547" r="6" fill="{color}"/>',
              svg_text(x+100,552,title,17,weight=750,mono="(" in title),svg_text(x+90,580,sub,15,LIGHT_THEME["muted"])]
    p.append(svg_text(930,630,"同一 durable stream 提供可追踪性",15,LIGHT_THEME["muted"],anchor="end"))
    return finish(p)


def architecture_context_management() -> str:
    p=svg_open(980,590)
    labels=[("Durable Session",40),("Context Projection",145),("Current Surface",250),("TokenMeter",355),("Pressure check",460)]
    for title,y in labels:
        p += [svg_rect(330,y,320,62,LIGHT_THEME["teal_fill"],LIGHT_THEME["teal"]),svg_text(490,y+39,title,19,weight=750,mono=title=="TokenMeter")]
        if y<460:p.append(svg_arrow(490,y+67,490,y+98))
    p += [svg_arrow(325,491,205,491),svg_arrow(655,491,775,491),
          svg_rect(30,455,170,72,LIGHT_THEME["success_fill"],LIGHT_THEME["success"]),svg_text(115,483,"below budget",17,weight=750),svg_text(115,508,"Continue",16,LIGHT_THEME["success"]),
          svg_rect(780,430,170,72,LIGHT_THEME["amber_fill"],LIGHT_THEME["amber"]),svg_text(865,458,"over budget",17,weight=750),svg_text(865,483,"Compaction",16,LIGHT_THEME["amber"]),
          svg_arrow(865,507,865,545),svg_rect(690,545,260,38,LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"],8),svg_text(820,570,"Smaller Model Context",16,weight=700),
          svg_badge(35,35,"optional composition",LIGHT_THEME["amber_fill"],LIGHT_THEME["amber"],190),svg_text(130,90,"token-meter + compaction-basic",15,LIGHT_THEME["muted"],mono=True)]
    return finish(p)


def architecture_ptc(w8: dict) -> str:
    d=w8["deepseek_harness"]
    p=svg_open(980,610)
    p += [svg_text(245,38,"Direct",21,weight=780),svg_text(735,38,"PTC / Code Mode",21,weight=780)]
    direct=[("Model Request 1",60),("Tool 1",145),("Model Request 2",230),("Tool 2",315),("Model Request N+1",465)]
    for title,y in direct:
        fill,stroke=(LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"]) if "Request" in title else (LIGHT_THEME["panel"],LIGHT_THEME["slate"])
        p += [svg_rect(110,y,270,58,fill,stroke),svg_text(245,y+37,title,18,weight=700)]
    for y1,y2 in [(123,140),(208,225),(293,310)]:p.append(svg_arrow(245,y1,245,y2))
    p += [svg_arrow(245,378,245,405),svg_text(245,430,"…",24,LIGHT_THEME["muted"]),svg_arrow(245,438,245,460),
          svg_rect(600,60,270,58,LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"]),svg_text(735,97,"Model Request 1",18,weight=700),svg_arrow(735,123,735,155),
          svg_rect(600,160,270,58,LIGHT_THEME["purple_fill"],LIGHT_THEME["purple"]),svg_text(735,197,"Program",19,weight=750),svg_arrow(735,223,735,255),
          svg_rect(580,260,310,125,LIGHT_THEME["panel"],LIGHT_THEME["purple"]),svg_multiline_text(735,305,["Tool · Tool · Tool","Tool · …"],18,weight=700),svg_arrow(735,390,735,460),
          svg_rect(600,465,270,58,LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"]),svg_text(735,502,"Model Request 2",18,weight=700),
          svg_badge(105,555,f'{d["direct"]["provider_requests"]} requests · {d["direct"]["model_visible_tool_calls"]} calls',LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"],280),
          svg_badge(595,555,f'{d["code"]["provider_requests"]} requests · {d["code"]["model_visible_tool_calls"]} call',LIGHT_THEME["purple_fill"],LIGHT_THEME["purple"],280)]
    return finish(p)


def architecture_recovery(w4: dict) -> str:
    p=svg_open(980,470)
    p += [svg_rect(320,25,340,65,LIGHT_THEME["amber_fill"],LIGHT_THEME["amber"]),svg_text(490,65,"Fixed malformed provider event",19,weight=750),
          svg_arrow(490,95,490,140),svg_rect(350,145,280,60,LIGHT_THEME["panel"],LIGHT_THEME["slate"]),svg_text(490,182,"Runtime boundary",20,weight=750),
          svg_arrow(430,210,255,265),svg_arrow(550,210,725,265),
          svg_text(255,255,"DeepSeek Harness",18,LIGHT_THEME["blue"],weight=750),svg_text(725,255,"Pinned OpenClaw",18,LIGHT_THEME["slate"],weight=750),
          svg_rect(105,275,300,58,LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"]),svg_text(255,311,"structured tool error",18,weight=700),
          svg_rect(575,275,300,58,LIGHT_THEME["panel2"],LIGHT_THEME["slate"]),svg_text(725,311,w4["openclaw"]["runtime_error_kind"],18,weight=700,mono=True),
          svg_arrow(255,338,255,375),svg_arrow(725,338,725,375),
          svg_rect(125,380,260,58,LIGHT_THEME["teal_fill"],LIGHT_THEME["teal"]),svg_text(255,416,"next model step",18,weight=750),
          svg_rect(595,380,260,58,LIGHT_THEME["error_fill"],LIGHT_THEME["error"]),svg_text(725,416,"terminate",18,weight=750)]
    return finish(p)


def architecture_feature_to_cpu() -> str:
    p=svg_open(1100,660)
    headers=[("机制 / Workload 来源",25,250),("W 证据",300,150),("Host 工作负载",485,330),("C 证据",855,180)]
    for title,x,w in headers:p += [svg_rect(x,20,w,55,LIGHT_THEME["panel2"],LIGHT_THEME["border"],8),svg_text(x+w/2,54,title,17,weight=750)]
    rows=[("Capability Seam","W10","path / policy execution","C6",False),("Session Event Log","W9","state append / copy / persistence","C2",False),("Context Management","W5","surface traversal / serialization","C3 / C8",False),("PTC / Code Mode","W8","code runtime / reduced orchestration","C5",False),("Recovery Semantics","W4 / W6","Agent control-flow work","C1 reference",True),("Multi-Agent Scale","—","Runtime density","C7",False)]
    p += [svg_text(25,104,"DeepSeek 核心设计",16,LIGHT_THEME["blue"],anchor="start",weight=750),
          f'<line x1="170" y1="99" x2="1035" y2="99" stroke="{LIGHT_THEME["grid"]}"/>',
          svg_text(25,442,"补充 Runtime 洞察",16,LIGHT_THEME["purple"],anchor="start",weight=750),
          f'<line x1="190" y1="437" x2="1035" y2="437" stroke="{LIGHT_THEME["grid"]}"/>']
    for i,(feature,w,work,c,dashed) in enumerate(rows):
        y=(115+i*75) if i<4 else (455+(i-4)*75); fill=LIGHT_THEME["bg"] if i%2==0 else LIGHT_THEME["panel"]
        for x,width in [(25,250),(300,150),(485,330),(855,180)]:p.append(svg_rect(x,y,width,62,fill,LIGHT_THEME["border"],7,1.2))
        p += [svg_text(150,y+38,feature,17,weight=700),svg_text(375,y+38,w,17,LIGHT_THEME["blue"],weight=750),svg_text(650,y+38,work,16),svg_text(945,y+38,c,17,LIGHT_THEME["teal"],weight=750)]
        p += [svg_arrow(277,y+31,294,y+31),svg_arrow(452,y+31,479,y+31),svg_arrow(817,y+31,849,y+31,dashed)]
    p += [svg_text(25,640,"实线：direct mapping　　虚线：indirect / supporting evidence",15,LIGHT_THEME["muted"],anchor="start")]
    return finish(p)


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
    for i,s in enumerate(spec["series"]):p += [f'<circle cx="{100+i*210}" cy="30" r="6" fill="{s["color"]}"/>',svg_text(115+i*210,35,s["name"],16,anchor="start")]
    return finish(p)


def data_c4(spec):
    rows=[(s["name"],s["points"][-1]["y"],s["color"]) for s in spec["series"]];p=svg_open(980,330,"C4",len(spec["series"]));left,right=230,130;minimum=.04;maximum=6;sx=lambda v:left+(math.log10(v)-math.log10(minimum))/(math.log10(maximum)-math.log10(minimum))*(980-left-right)
    for tick in [.05,.1,.3,1,3]:p += [f'<line x1="{sx(tick)}" y1="25" x2="{sx(tick)}" y2="270" stroke="{LIGHT_THEME["grid"]}"/>',svg_text(sx(tick),305,fmt(tick),15,LIGHT_THEME["muted"])]
    for i,(name,value,color) in enumerate(rows):y=70+i*75;p += [svg_text(left-18,y+5,name,17,anchor="end"),f'<line x1="{sx(minimum)}" y1="{y}" x2="{sx(value)}" y2="{y}" stroke="{color}" stroke-width="2"/>',f'<circle cx="{sx(value)}" cy="{y}" r="8" fill="{color}"/>',svg_text(sx(value)+14,y+5,f'{value:.3f}',16,color,anchor="start",weight=700)]
    count=int(spec["series"][0]["points"][-1]["x"]);p.append(svg_text(490,327,f"单次执行时间（ms/op，Wall Time）· 对数刻度 · {count} 次微操作",17,weight=700));return finish(p)


def data_c5(spec):
    p=svg_open(980,500,"C5",len(spec["series"]));series_maps=[{point["x"]:point["y"] for point in series["points"]} for series in spec["series"]]
    common=sorted(set(series_maps[0]) & set(series_maps[1])); bracket=None
    for low,high in zip(common,common[1:]):
        if (series_maps[0][low]-series_maps[1][low])*(series_maps[0][high]-series_maps[1][high]) <= 0:
            bracket=(low,high);break
    if bracket:
        tx=lambda value:math.log10(float(value)+1);xmin,xmax=tx(min(common)),tx(max(common));sx=lambda value:80+(tx(value)-xmin)/(xmax-xmin)*870
        x1,x2=sx(bracket[0]),sx(bracket[1]);p += [f'<rect x="{x1:.1f}" y="70" width="{x2-x1:.1f}" height="353" fill="{LIGHT_THEME["amber_fill"]}" opacity=".8"/>',f'<line x1="{x1:.1f}" y1="70" x2="{x1:.1f}" y2="423" stroke="{LIGHT_THEME["amber"]}" stroke-dasharray="5 5"/>',f'<line x1="{x2:.1f}" y1="70" x2="{x2:.1f}" y2="423" stroke="{LIGHT_THEME["amber"]}" stroke-dasharray="5 5"/>']
    p.append(line_panel(spec,spec["series"],0,35,980,450,False,False,y_label="执行时间（ms，Wall Time）",x_label="操作数 · log(1+x)"))
    p += [svg_text(105,92,"低操作数：PTC 固定启动成本更明显",15,LIGHT_THEME["muted"],anchor="start"),svg_text(925,118,"高操作数：重复 orchestration 逐渐摊薄",15,LIGHT_THEME["muted"],anchor="end")]
    if bracket:p.append(svg_text((x1+x2)/2,150,f"{fmt(bracket[0])}–{fmt(bracket[1])} 当前 fixture crossover 区间",15,LIGHT_THEME["amber"],weight=700))
    for i,s in enumerate(spec["series"]):p += [f'<circle cx="{120+i*160}" cy="25" r="6" fill="{s["color"]}"/>',svg_text(135+i*160,30,s["name"],16,anchor="start")]
    return finish(p)


def data_c6(spec):
    result=data_c4({"series":[{"name":s["name"],"color":s["color"],"points":s["points"]} for s in spec["series"]]})
    return result.replace('data-benchmark="C4"','data-benchmark="C6"',1)


def data_c7(spec, cpu):
    p=svg_open(980,650,"C7",len(spec["series"]));throughput=[spec["series"][0]];efficiency=[spec["series"][1]]
    p.append(line_panel(spec,throughput,0,30,980,285,False,False,y_label="吞吐（Agents/s）",x_label=""));p.append(line_panel(spec,efficiency,0,325,980,285,False,False,y_label="并行效率（%）",x_label="Agent 数"))
    d=cpu["C7"]["data"];last=max(d["aggregates"],key=int);p += [svg_badge(650,45,f'{last} Agents · {d["aggregates"][last]["agents_per_second"]["median"]:.2f} Agents/s',LIGHT_THEME["blue_fill"],LIGHT_THEME["blue"],280),svg_badge(690,355,f'{d["scaling"][last]["parallel_efficiency"]*100:.1f}% efficiency',LIGHT_THEME["amber_fill"],LIGHT_THEME["amber"],240)]
    return finish(p)


def data_c8(spec, cpu):
    p=svg_open(980,800,"C8",len(spec["series"]));p += [svg_text(25,28,"全部数量级 · Cold 与 Warm",17,anchor="start",weight=750),line_panel(spec,spec["series"],0,75,980,330,True,True,spec.get("xTicks"),"每测量窗口 CPU（μs）· 对数刻度","Surface 节点数 · 对数刻度"),svg_text(25,440,"Warm 细节 · Incremental 与 Repeat",17,anchor="start",weight=750),line_panel(spec,spec["series"][1:],0,450,980,330,True,False,spec.get("xTicks"),"每测量窗口 CPU（μs）","Surface 节点数 · 对数刻度")]
    d=cpu["C8"]["data"];slopes=[("Cold",d["cold"],"μs/surface-node"),("Incremental",d["incremental"],"μs/effective-node"),("Repeat",d["repeat"],"μs/surface-node")];x=50
    for name,data,unit in slopes:
        slope=data["linear_fits"]["internal_cpu_us_per_measure"]["per_surface_node_slope"];p.append(svg_badge(x,40,f'{name} {slope:.3f} {unit}',width=275));x+=292.5
    return finish(p)


def build_figure_sets(cpu: dict, workloads: dict) -> tuple[dict[str, str], dict[str, str]]:
    charts={c["key"]:c for c in build_charts(cpu)}
    architecture={"harness-model.svg":architecture_harness_model(),"composition-tree.svg":architecture_composition_tree(),"capability-seam.svg":architecture_capability_seam(workloads["W10"]["data"]),"event-log.svg":architecture_event_log(),"context-management.svg":architecture_context_management(),"ptc.svg":architecture_ptc(workloads["W8"]["data"]),"recovery-boundary.svg":architecture_recovery(workloads["W4"]["data"]),"feature-to-cpu.svg":architecture_feature_to_cpu()}
    data={"c2-session-cost.svg":data_c2(charts["C2"]),"c3-context-serialization.svg":data_c3(charts["C3"]),"c4-process-lifecycle.svg":data_c4(charts["C4"]),"c5-native-vs-ptc.svg":data_c5(charts["C5"]),"c6-fs-policy.svg":data_c6(charts["C6"]),"c7-agent-scale.svg":data_c7(charts["C7"],cpu),"c8-context-pressure.svg":data_c8(charts["C8"],cpu)}
    return architecture, data


def main() -> None:
    data_dir=REPORT_ROOT/"figures"/"data";arch_dir=REPORT_ROOT/"figures"/"architecture";data_dir.mkdir(parents=True,exist_ok=True);arch_dir.mkdir(parents=True,exist_ok=True)
    architecture,data=build_figure_sets(load_cpu_results(),load_workload_results())
    for name,content in architecture.items():(arch_dir/name).write_text(content,encoding="utf-8")
    for name,content in data.items():(data_dir/name).write_text(content,encoding="utf-8")
    print(f"generated {len(data)} data and {len(architecture)} architecture SVG figures")


if __name__=="__main__":main()
