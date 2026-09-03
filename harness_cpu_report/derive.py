"""Explicit, schema-aware adapters from C1-C8 results to chart specifications."""

from __future__ import annotations

import math


COLORS = ["#5aa7ff", "#46c8b3", "#a98bff", "#f0b75a", "#ed7474"]


def median(record: dict, field: str) -> float:
    value = record[field]
    value = value["median"] if isinstance(value, dict) else value
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"non-finite or missing metric: {field}")
    return float(value)


def points(rows: dict, field: str, factor: float = 1.0) -> list[dict]:
    result = []
    for key, value in sorted(rows.items(), key=lambda item: float(item[0])):
        point = {"x": float(key), "y": median(value, field) * factor}
        metric = value[field]
        if isinstance(metric, dict) and all(name in metric for name in ("min", "max")):
            point.update({"low": float(metric["min"]) * factor, "high": float(metric["max"]) * factor})
        result.append(point)
    return result


def series(name: str, data: list[dict], color: str, axis: str = "left") -> dict:
    return {"name": name, "points": data, "color": color, "axis": axis}


def spec(key: str, title: str, chart_type: str, x_label: str, x_scale: str,
         y_label: str, unit: str, sources: list[str], series_data: list[dict],
         note: str = "", right_axis: dict | None = None) -> dict:
    result = {
        "key": key, "title": title, "type": chart_type,
        "x": {"label": x_label, "scale": x_scale},
        "y": {"label": y_label, "unit": unit},
        "series": series_data, "sources": sources, "note": note,
    }
    if right_axis:
        result["rightAxis"] = right_axis
    return result


def build_c1(item: dict) -> dict:
    rows = item["data"]["aggregates"]
    return spec("C1", "图 1 · Agent Loop 随工具步数增长", "line", "工具步数", "log1p",
                "内部耗时", "ms", [item["file"]], [
                    series("CPU", points(rows, "internal_cpu_total_us", 1 / 1000), COLORS[0]),
                    series("Wall", points(rows, "internal_wall_ns", 1 / 1_000_000), COLORS[1]),
                ], "Cold path，并包含持续增长的 Session/context。")


def build_c2(item: dict) -> dict:
    fits = item["data"]["linear_fits_over_event_count_medians"]
    fields = [("Append", "append_cpu_us"), ("deriveMessages", "derive_messages_cpu_us"),
              ("Fork prefix", "fork_prefix_cpu_us"), ("JSONL write", "jsonl_write_cpu_us"),
              ("Warm load", "jsonl_warm_load_cpu_us")]
    bars = [{"x": label, "y": float(fits[field]["per_event_slope"])} for label, field in fields]
    return spec("C2", "图 2 · Session/Event Log 边际成本", "horizontal-bar", "Session 操作", "category",
                "拟合 CPU 成本", "μs/event", [item["file"]],
                [series("每事件 CPU", bars, COLORS[0])],
                "来自 event-count medians 的线性拟合斜率，不是单点总耗时。")


def build_c3(item: dict) -> dict:
    rows = item["data"]["aggregates"]
    return spec("C3", "图 3 · 长上下文 JSON/SSE 处理", "line", "逻辑上下文字节", "log",
                "内部 CPU", "ms", [item["file"]], [
                    series("JSON encode", points(rows, "json_encode_request_cpu_us", 1 / 1000), COLORS[0]),
                    series("JSON decode", points(rows, "json_decode_request_cpu_us", 1 / 1000), COLORS[1]),
                    series("SSE + JSON decode", points(rows, "sse_frame_and_json_decode_cpu_us", 1 / 1000), COLORS[2]),
                ], "固定消息形状，只扩大文本字节数。")


def nested_lines(item: dict, key: str, title: str, labels: list[tuple[str, str]], field: str,
                 factor: float, unit: str, note: str, x_scale: str = "log") -> dict:
    rows = item["data"]["aggregates"]
    return spec(key, title, "line", "操作数", x_scale, "耗时", unit, [item["file"]], [
        series(label, points(rows[name], field, factor), COLORS[index])
        for index, (name, label) in enumerate(labels)
    ], note)


def build_c4(item: dict) -> dict:
    return nested_lines(item, "C4", "图 4 · Shell 生命周期成本",
                        [("dsh-managed", "DSH managed"), ("raw-oneshot", "Raw one-shot"),
                         ("persistent", "Persistent")], "wall_ns_per_operation", 1 / 1_000_000,
                        "ms/op", "后两条是机制控制组，不是 OpenClaw 实现。")


def build_c5(item: dict) -> dict:
    return nested_lines(item, "C5", "图 5 · Native 与 PTC 本地执行时间",
                        [("native", "Native"), ("ptc", "PTC")], "internal_wall_ns", 1 / 1_000_000,
                        "ms", "零延迟 mock；交叉点不是生产推荐阈值。", "log1p")


def build_c6(item: dict) -> dict:
    return nested_lines(item, "C6", "图 6 · Filesystem policy seam",
                        [("local-write", "Local write"), ("sandbox-write", "Sandbox write")],
                        "wall_ns_per_operation", 1 / 1000, "μs/op",
                        "允许的 256 B 热文件写入；这是 capability policy，不是 OS sandbox。")


def build_c7(item: dict) -> dict:
    data = item["data"]
    efficiency = [{"x": float(key), "y": float(value["parallel_efficiency"]) * 100}
                  for key, value in sorted(data["scaling"].items(), key=lambda item: float(item[0]))]
    return spec("C7", "图 7 · 多 Agent 扩展", "line", "并发 Agent", "linear",
                "吞吐", "Agents/s", [item["file"]], [
                    series("Agents/s", points(data["aggregates"], "agents_per_second"), COLORS[0]),
                    series("并行效率", efficiency, COLORS[1], "right"),
                ], "右轴为相对单 Agent 的并行效率。",
                {"label": "并行效率", "unit": "%", "min": 0, "max": 110})


def build_incremental_points(data: dict) -> list[dict]:
    """Use the time-weighted effective surface axis recorded by C8-B samples."""
    effective_by_initial: dict[int, set[float]] = {}
    for sample in data["samples"]:
        fixture = sample["fixture"]
        initial = int(fixture["surface_events"])
        effective_by_initial.setdefault(initial, set()).add(float(fixture["effective_surface_nodes"]))
    result = []
    for key, aggregate in sorted(data["aggregates"].items(), key=lambda item: float(item[0])):
        initial = int(key)
        effective = effective_by_initial.get(initial, set())
        if len(effective) != 1:
            raise ValueError(f"C8 incremental initial={initial} has ambiguous effective surface: {effective}")
        metric = aggregate["internal_cpu_us_per_measure"]
        result.append({"x": effective.pop(), "y": float(metric["median"]),
                       "low": float(metric["min"]), "high": float(metric["max"])})
    return result


def build_c8(item: dict) -> dict:
    names = ("cold", "incremental", "repeat")
    result = spec("C8", "图 8 · TokenMeter/context pressure", "line",
                "Surface 规模（Incremental 使用平均 effective surface）", "log",
                "每次测量窗口内部 CPU", "μs", [item["files"][name] for name in names], [
                    series("Cold replay", points(item["data"]["cold"]["aggregates"],
                                                  "internal_cpu_us_per_measure"), COLORS[0]),
                    series("Incremental（append + measure）", build_incremental_points(item["data"]["incremental"]), COLORS[1]),
                    series("Repeat measure", points(item["data"]["repeat"]["aggregates"],
                                                     "internal_cpu_us_per_measure"), COLORS[2]),
                ], "Cold：首次 measure 含 durable-history replay；Incremental：append one turn + measure；"
                   "Repeat：surface 不变的重复 measure。三者用于机制分解，不是可互换延迟。")
    result["xTicks"] = [10, 100, 1000, 10000]
    return result


CHART_BUILDERS = {"C1": build_c1, "C2": build_c2, "C3": build_c3, "C4": build_c4,
                  "C5": build_c5, "C6": build_c6, "C7": build_c7, "C8": build_c8}


def build_charts(cpu: dict) -> list[dict]:
    return [CHART_BUILDERS[key](cpu[key]) for key in CHART_BUILDERS]
