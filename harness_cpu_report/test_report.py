"""Regression tests for report adapters and evidence-backed narrative values."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from content import build_features, build_key_findings, build_real_tasks  # noqa: E402
from build import report_input_fingerprint, report_input_paths  # noqa: E402
from data_loader import load_cpu_results, load_workload_results  # noqa: E402
from derive import build_charts  # noqa: E402


class ReportAdaptersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cpu = load_cpu_results()
        cls.workloads = load_workload_results()
        cls.charts = {chart["key"]: chart for chart in build_charts(cls.cpu)}

    def test_every_cpu_case_has_explicit_chart(self):
        self.assertEqual(set(self.charts), {f"C{number}" for number in range(1, 9)})

    def test_c1_separates_cpu_and_wall_in_ms(self):
        chart = self.charts["C1"]
        self.assertEqual(chart["y"]["unit"], "ms")
        self.assertEqual([item["name"] for item in chart["series"]], ["CPU", "Wall"])
        self.assertAlmostEqual(chart["series"][0]["points"][-1]["y"], 466.23, places=2)
        self.assertAlmostEqual(chart["series"][1]["points"][-1]["y"], 467.544, places=3)

    def test_c2_uses_five_per_event_cpu_slopes(self):
        chart = self.charts["C2"]
        self.assertEqual(chart["type"], "bar")
        self.assertEqual(chart["y"]["unit"], "μs/event")
        values = {point["x"]: point["y"] for point in chart["series"][0]["points"]}
        self.assertEqual(len(values), 5)
        self.assertAlmostEqual(values["Append"], 20.716, places=3)
        self.assertAlmostEqual(values["deriveMessages"], 0.108609, places=6)

    def test_c3_c4_c5_use_named_multi_series(self):
        self.assertEqual([item["name"] for item in self.charts["C3"]["series"]],
                         ["JSON encode", "JSON decode", "SSE + JSON decode"])
        self.assertEqual([item["name"] for item in self.charts["C4"]["series"]],
                         ["DSH managed", "Raw one-shot", "Persistent"])
        self.assertEqual([item["name"] for item in self.charts["C5"]["series"]],
                         ["Native", "PTC"])

    def test_c6_and_c7_metrics_are_not_generic_wall_fallbacks(self):
        self.assertEqual(self.charts["C6"]["y"]["unit"], "μs/op")
        c7 = self.charts["C7"]
        self.assertEqual(c7["series"][1]["axis"], "right")
        self.assertAlmostEqual(c7["series"][0]["points"][-1]["y"], 83.1719, places=4)
        self.assertAlmostEqual(c7["series"][1]["points"][-1]["y"], 72.7815, places=4)

    def test_c8_loads_cold_incremental_repeat_and_all_shape_inputs(self):
        self.assertEqual([item["name"] for item in self.charts["C8"]["series"]],
                         ["Cold replay", "Incremental（append + measure）", "Repeat measure"])
        incremental_x = [point["x"] for point in self.charts["C8"]["series"][1]["points"]]
        self.assertEqual(incremental_x, [110.5, 200.5, 1100.5, 5020.5, 10010.5])
        self.assertIn("测量窗口", self.charts["C8"]["y"]["label"])
        self.assertEqual(set(self.cpu["C8"]["data"]),
                         {"cold", "incremental", "repeat", "shape_schema", "shape_text",
                          "shape_tool_call", "shape_tool_result"})

    def test_feature_cards_are_backed_by_w_results(self):
        cards = build_features(self.workloads, self.cpu)
        text = " ".join(" ".join(card["observation"]) for card in cards)
        self.assertIn("FS_SANDBOX_DENIED", text)
        self.assertIn("Direct：8 tool calls / 9 requests", text)
        self.assertIn("PTC：1 program call / 2 requests", text)

    def test_real_tasks_and_key_findings_are_data_backed(self):
        tasks = build_real_tasks(self.workloads)
        self.assertEqual([(item["dsh"], item["openclaw"]) for item in tasks],
                         [("4 / 5", "5 / 5"), ("5 / 5", "2 / 5")])
        findings = build_key_findings(self.workloads, self.cpu)
        self.assertEqual(findings[0]["value"], "9 → 2")
        self.assertIn("83.17 Agents/s", [item["value"] for item in findings])
        self.assertIn("不是端到端 latency 倍率", findings[-1]["detail"])

    def test_report_input_fingerprint_is_stable_and_excludes_output(self):
        paths = report_input_paths()
        relative = [path.relative_to(HERE.parent).as_posix() for path in paths]
        self.assertEqual(relative, sorted(relative))
        self.assertIn("evidence/manifest.json", relative)
        self.assertIn("harness_cpu_report/build.py", relative)
        self.assertNotIn("harness_cpu_report/dist/index.html", relative)
        fingerprint = report_input_fingerprint()
        self.assertEqual(len(fingerprint), 64)
        self.assertEqual(fingerprint, report_input_fingerprint())


if __name__ == "__main__":
    unittest.main()
