"""Check that the paper-2 gateway core reproduces E14: the "bound" and "bound_mix" policies of
results/fix_val/<ds>_s<seed>.json must equal E14's "deployed" and "mix_cusum" (data/<ds>_s<seed>.json).
Usage: py -3.13 code/check_reproduces_e14.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("false_isolation_rate", "benign_ever_blocked", "detection_rate", "tti_median", "wrongful_grant_rate")
bad = n = 0
for p in sorted((ROOT / "results" / "fix_val").glob("*.json")):
    f, e = json.loads(p.read_text()), json.loads((ROOT / "data" / p.name).read_text())
    for sc, v in f["scenarios"].items():
        for mine, theirs in (("bound", "deployed"), ("bound_mix", "mix_cusum")):
            for k in KEYS:
                n += 1
                a, b = v[mine][k], e["scenarios"][sc][theirs][k]
                if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12):
                    bad += 1
                    print("MISMATCH", p.name, sc, mine, k, a, b)
    for sc, v in f["long"].items():
        h = "h10000"
        for k in KEYS:
            n += 1
            a, b = v["bound"][k], e["scenarios"][sc][h][k]
            if (a is None) != (b is None) or (a is not None and abs(a - b) > 1e-12):
                bad += 1
                print("MISMATCH", p.name, sc, "long bound", k, a, b)
print(f"{n} values compared, {bad} mismatches")
