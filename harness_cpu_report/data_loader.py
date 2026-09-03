"""Load benchmark JSON without requiring third-party dependencies."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def load_cpu_results():
    out = {}
    paths = sorted((ROOT / "results").glob("c[1-8]-*.json"))
    # Prefer the named primary runs when several pilot/shape files exist.
    preferred = {"C1": "c1-agent-loop-pilot.json", "C8": "c8-token-meter-cold-pilot.json"}
    chosen = {}
    for path in paths:
        key = path.name.split("-")[0].upper()
        if key not in chosen or path.name == preferred.get(key): chosen[key] = path
    for key, path in chosen.items():
        out[key] = {"file": str(path.relative_to(ROOT)), "data": load_json(path)}
    return out

def load_evidence_index():
    for name in ("manifest.json", "MANIFEST.sha256"):
        path = ROOT / "evidence" / name
        if path.exists():
            return {"file": str(path.relative_to(ROOT)), "text": path.read_text(encoding="utf-8", errors="replace")[:12000]}
    return {}
