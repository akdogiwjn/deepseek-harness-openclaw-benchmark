"""Validate the report inputs and generated artifact."""
from pathlib import Path
import json

def validate(root):
    required = [root / "results", root / "evidence", root / "harness_cpu_report" / "templates" / "index.html"]
    missing = [str(p) for p in required if not p.exists()]
    if missing: raise SystemExit("Missing report inputs: " + ", ".join(missing))

def validate_html(path):
    text = path.read_text(encoding="utf-8")
    for marker in ("<html", "</html>", "<style>", "<script>", "DeepSeek Harness"):
        if marker not in text: raise SystemExit(f"Generated HTML missing {marker}")
