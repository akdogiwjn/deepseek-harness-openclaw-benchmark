# DeepSeek Harness 新型 Agent Harness 机制调研

本目录是一份 Markdown-first 中文技术调研报告。`report.template.md` 是人工维护的正文
模板，所有定量数字使用 placeholder；构建器从仓库现有 `results/*.json` 注入数据并生成
唯一发布正文 `report.md`、静态 SVG 和附属离线 HTML。不要直接维护 `report.md` 或 HTML
中的实验数字。

```bash
python3 deepseek_harness_report/scripts/build_report.py
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
- `generated/metrics.json`：从 W/C JSON 自动提取的定量数据；
- `generated/provenance.json`：输入指纹、pinned revisions 与实验环境；
- `figures/`：从 explicit C adapters 和固定架构描述生成的 SVG；
- `dist/report.html`：由 `report.md` 转换的单文件、无 CDN 正文页面（SVG 使用相对路径）。

本报告不修改 `results/`、`evidence/` 或任何 benchmark logic。
