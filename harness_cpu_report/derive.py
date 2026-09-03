"""Small, deterministic transformations used by the report."""
import math

def _numbers(value):
    if isinstance(value, (int, float)) and math.isfinite(value):
        return [value]
    if isinstance(value, dict):
        found = []
        for v in value.values(): found.extend(_numbers(v))
        return found
    if isinstance(value, list):
        found = []
        for v in value: found.extend(_numbers(v))
        return found
    return []

def chart_points(data, preferred=("internal_cpu_us", "cpu_us", "wall_us", "mean_us", "median_us", "mean")):
    """Find aggregate-like records and return [{x,y}] for an illustrative chart."""
    agg = data.get("aggregates", {}) if isinstance(data, dict) else {}
    points = []
    if isinstance(agg, dict):
        for key, value in agg.items():
            if not isinstance(value, dict): continue
            nums = []
            for field in preferred:
                candidate = value.get(field)
                if isinstance(candidate, (int, float)): nums = [candidate]; break
                if isinstance(candidate, dict):
                    for stat in ("median", "mean", "avg"):
                        if isinstance(candidate.get(stat), (int, float)):
                            nums = [candidate[stat]]; break
                if nums: break
            # Most repository aggregates call the timing field internal_*.
            if not nums:
                for field, candidate in value.items():
                    if ("cpu" in field or "wall" in field or "time" in field or "runtime" in field) and isinstance(candidate, dict):
                        for stat in ("median", "mean", "avg"):
                            if isinstance(candidate.get(stat), (int, float)):
                                nums = [candidate[stat]]; break
                        if nums: break
            if nums:
                try: points.append({"x": float(key), "y": float(nums[0])})
                except ValueError: pass
    return sorted(points, key=lambda p: p["x"])

def summary(cpu):
    result = {}
    for key, item in cpu.items():
        d = item.get("data", {})
        result[key] = {
            "benchmark": d.get("benchmark", key),
            "created_at": d.get("created_at", ""),
            "machine": d.get("host", {}).get("machine", "unknown"),
            "points": chart_points(d),
            "protocol": d.get("protocol", {}).get("protocol_sha256", "not recorded"),
        }
    return result
