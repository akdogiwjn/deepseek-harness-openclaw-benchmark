# Harness CPU Report

离线研究报告构建器。所有输入来自仓库根目录的 `results/` 与 `evidence/`；构建阶段将 CSS、JavaScript 和派生数据全部 inline 到一个 HTML 文件。

```bash
python3 harness_cpu_report/build.py
```

输出：`harness_cpu_report/dist/index.html`。可直接双击打开，不需要 Web Server、npm、CDN、网络或本地 JSON fetch。

`data_loader.py` 负责读取结果，`derive.py` 负责从 aggregate 数据派生图表点，`validate.py` 做输入和输出校验。若新增 `results/cN-*.json`，重新运行构建即可刷新报告。
