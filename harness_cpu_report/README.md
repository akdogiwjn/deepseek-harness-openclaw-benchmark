# Harness CPU Report

离线研究报告构建器。所有输入来自仓库根目录的 `results/` 与 `evidence/`；构建阶段将 CSS、JavaScript 和派生数据全部 inline 到一个 HTML 文件。

```bash
python3 harness_cpu_report/build.py
```

严格模式会在构建前执行 W1–W10 frozen evidence 重放和 C1–C8 result
verification；只有全部通过，HTML 才显示“完整证据重放：PASS”：

```bash
python3 harness_cpu_report/build.py --verify
```

输出：`harness_cpu_report/dist/index.html`。可直接双击打开，不需要 Web Server、npm、CDN、网络或本地 JSON fetch。

页面中的“报告生成时 Git 状态”只描述生成动作发生时的 checkout 与工作树，不作为
生成 HTML 的内容标识。稳定标识使用“报告输入指纹 / SHA256”：构建器收集显式使用的
W2–W10、C1–C8 JSON、`evidence/manifest.json`，以及报告的 Python、template、CSS 和
JavaScript 源文件；排除 `dist/index.html`。它逐个计算文件 SHA256，再按相对路径排序，
对 `relative_path + NUL + file_sha256 + newline` 记录重新计算总 SHA256。可直接复算：

```bash
python3 harness_cpu_report/build.py --print-input-fingerprint
```

`data_loader.py` 使用显式文件清单读取 W2–W10 与 C1–C8；`derive.py` 为每个
CPU benchmark 提供独立、schema-aware chart adapter，明确字段、单位、series
和坐标变换。通用 JavaScript 只渲染 chart spec，不猜测数据含义。C8 同时加载
cold、incremental、repeat 和四种 shape 结果。

默认构建会检查必需 JSON、protocol metadata、sample fixture checks、有限数值与
chart spec 完整性，但不会把这些检查描述成完整 evidence replay。

报告层回归测试会锁定 C1–C8 的明确 series、单位和关键取数路径：

```bash
python3 -m unittest harness_cpu_report/test_report.py
```
