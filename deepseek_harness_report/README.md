# DeepSeek Harness 新特性与运行时机制调研

本目录包含两份共享数据与证据边界的 Markdown-first 中文技术调研报告：
`report.template.md` 生成技术详细版，`report_showcase.template.md` 生成面向分享和跨团队
阅读的技术展示版。所有定量数字使用 placeholder；构建器从仓库现有 `results/*.json`
注入数据并生成发布 Markdown、数据 SVG 和附属离线 HTML。架构 SVG 是人工维护的静态资产，
不会在构建时被重写。不要直接维护生成的 Markdown 或 HTML
中的实验数字。

```bash
python3 deepseek_harness_report/scripts/build_report.py
```

构建器始终同时生成两版；也可使用便于发现的兼容入口：

```bash
python3 deepseek_harness_report/scripts/build_report.py --showcase
```

严格模式只重放现有 frozen evidence 并验证 CPU result，不重新运行 W/C benchmark：

```bash
python3 deepseek_harness_report/scripts/build_report.py --verify
```

独立检查生成物：

```bash
python3 deepseek_harness_report/scripts/validate_report.py
```

主要输出：

- `report.md`：正文 source of truth 的生成发布版；
- `report_showcase.md`：适合技术分享、内部评审和首次阅读的生成展示版；
- `generated/metrics.json`：从 W/C JSON 自动提取的定量数据；
- `generated/provenance.json`：输入指纹、pinned revisions 与实验环境；
- `figures/architecture/`：人工精修、纳入报告输入指纹的静态机制图；
- `figures/data/`：从 explicit C adapters 与结果 JSON 自动生成的数据图；
- `dist/report.html`：技术详细版离线 HTML；
- `dist/report_showcase.html`：技术展示版离线 HTML（两者均无 CDN，SVG 使用相对路径）。

本报告不修改 `results/`、`evidence/` 或任何 benchmark logic。
