"""Summarize paper-2 experiment F1 (results/fix_<source>/) into results/summary.md and summary.json.

Held-out seeds 44-51 are aggregated as mean and worst seed (false isolation: highest; detection:
lowest); seed 43, on which the guard was chosen, is reported on its own. The E14 diagnostics come
from data/<dataset>_s<seed>.json.
Usage: py -3.13 code/summarize.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DS = {"edgeiiot": "Edge", "forge": "Forge", "wustl": "WUSTL"}
HELD, DESIGN = list(range(44, 52)), [43]
SCEN = ["iid", "unseen", "het0.5", "ar0.5", "ar0.9", "ar0.99"]
RHOS = ["1", "0.5", "0.2", "0.1", "0.05"]
POL = ["bound", "bound_mix", "cal", "cal_mix", "boot", "floor", "guard", "temper", "temper_mix"]
PHIS = ["0", "0.5", "0.9", "0.99"]


def load(src: str, seeds) -> dict[str, list[dict]]:
    return {d: [json.loads((ROOT / "results" / f"fix_{src}" / f"{d}_s{s}.json").read_text()) for s in seeds] for d in DS}


def agg(v, worst):
    v = [x for x in v if x is not None]
    return (float(np.mean(v)), float(worst(v))) if v else (None, None)


def block(runs, get, metric, worst, scale=100.0):
    return {d: agg([None if get(r) is None or get(r)[metric] is None else scale * get(r)[metric] for r in rs], worst)
            for d, rs in runs.items()}


def fmt(x):
    return "-" if x[0] is None else f"{x[0]:.1f}/{x[1]:.1f}"


def main() -> None:
    js, md = {}, ["# Paper 2, experiment F1: site-calibrated thresholds under correlated benign traffic", ""]
    for src, seeds, tag in (("fresh", HELD, "held-out seeds 44-51"), ("fresh", DESIGN, "design seed 43"),
                            ("val", HELD, "validation calibration (in-sample), seeds 44-51")):
        runs = load(src, seeds)
        key = f"{src}_{'held' if seeds == HELD else 'design'}"
        J = js.setdefault(key, {})
        md += [f"## {tag}", ""]
        for metric, worst, title, scale in (("false_isolation_rate", max, "False isolation of benign devices, %", 100),
                                            ("detection_rate", min, "Detection of compromised devices, %", 100),
                                            ("tti_median", max, "Median time to isolation, events", 1),
                                            ("benign_ever_blocked", max, "Benign devices ever blocked, %", 100)):
            md += [f"### {title} (mean/worst seed)", "", "| dataset | scenario | rho | " + " | ".join(POL) + " |",
                   "|---" * (3 + len(POL)) + "|"]
            for d in DS:
                for s in SCEN:
                    for rho in RHOS:
                        cells = []
                        for p in POL:
                            x = block({d: runs[d]}, lambda r: r["scenarios"][f"{s}/rho{rho}"].get(p), metric, worst, scale)[d]
                            J.setdefault(metric, {}).setdefault(d, {}).setdefault(f"{s}/rho{rho}", {})[p] = x
                            cells.append(fmt(x))
                        md.append(f"| {DS[d]} | {s} | {rho} | " + " | ".join(cells) + " |")
            md.append("")
        md += ["### Calibrated thresholds and tempering factor (mean over seeds)", "",
               "| dataset | scenario | h_bound | h_cal | h_cal_mix (cusum, mix) | h_guard (cusum, mix) | c |", "|---|---|---|---|---|---|---|"]
        for d, rs in runs.items():
            for s in SCEN + ["long_iid", "long_ar0.9"]:
                c = [r["calibration"][s] for r in rs]
                m = lambda k, i=None: float(np.mean([x[k] if i is None else x[k][i] for x in c]))
                J.setdefault("calibration", {}).setdefault(d, {})[s] = {"h_bound": m("h_bound"), "h_cal": m("h_cal"),
                    "h_cal_mix": [m("h_cal_mix", 0), m("h_cal_mix", 1)], "h_guard": [m("h_guard_mix", 0), m("h_guard_mix", 1)], "c": m("c")}
                md.append(f"| {DS[d]} | {s} | {m('h_bound'):.1f} | {m('h_cal'):.1f} | {m('h_cal_mix', 0):.1f}, {m('h_cal_mix', 1):.1f} | "
                          f"{m('h_guard_mix', 0):.1f}, {m('h_guard_mix', 1):.1f} | {m('c'):.1f} |")
        md += ["", "### Misspecified calibration (rho 0.2): false isolation / detection, % mean (worst FI seed)", "",
               "| dataset | eval phi | policy | " + " | ".join(f"cal phi {p}" for p in PHIS) + " |", "|---" * (3 + len(PHIS)) + "|"]
        for d, rs in runs.items():
            for pe in PHIS:
                for p in ("cal_mix", "guard"):
                    cells = []
                    for pc in PHIS:
                        fi = agg([100 * r["misspec"][f"eval{pe}/cal{pc}"][p]["false_isolation_rate"] for r in rs], max)
                        de = agg([100 * r["misspec"][f"eval{pe}/cal{pc}"][p]["detection_rate"] for r in rs], min)
                        J.setdefault("misspec", {}).setdefault(d, {})[f"eval{pe}/cal{pc}/{p}"] = {"fiso": fi, "detect": de}
                        cells.append(f"{fi[0]:.1f} ({fi[1]:.1f}) / {de[0]:.0f}")
                    md.append(f"| {DS[d]} | {pe} | {p} | " + " | ".join(cells) + " |")
        md += ["", "### Long horizon, 200 devices x 10,000 events: false isolation / detection, % (mean/worst)", "",
               "| dataset | scenario | " + " | ".join(POL) + " |", "|---" * (2 + len(POL)) + "|"]
        for d, rs in runs.items():
            for s in ("long_iid/rho0.2", "long_iid/rho0.05", "long_ar0.9/rho0.2", "long_ar0.9/rho0.05"):
                cells = []
                for p in POL:
                    if p not in rs[0]["long"][s]:
                        cells.append("-")
                        continue
                    fi = agg([100 * r["long"][s][p]["false_isolation_rate"] for r in rs], max)
                    de = agg([100 * r["long"][s][p]["detection_rate"] for r in rs], min)
                    J.setdefault("long", {}).setdefault(d, {}).setdefault(s, {})[p] = {"fiso": fi, "detect": de}
                    cells.append(f"{fmt(fi)} / {fmt(de)}")
                md.append(f"| {DS[d]} | {s} | " + " | ".join(cells) + " |")
        md.append("")
    diag = {}
    for d in DS:
        g = [json.loads((ROOT / "data" / f"{d}_s{s}.json").read_text())["diagnostics"] for s in range(43, 52)]
        diag[d] = {k: [float(np.mean([x[k] for x in g])), float(min(x[k] for x in g)), float(max(x[k] for x in g))]
                   for k in ("sum_f0_exp_l_val", "E0_exp_l_test", "E0_exp_l_test_unseen", "E0_l", "E1_l_all", "rho_star_all")}
    js["diagnostics_e14"] = diag
    md += ["## E14 diagnostics (seeds 43-51): mean [min, max]", ""] + [
        f"- {DS[d]}: " + ", ".join(f"{k}={v[0]:.2f} [{v[1]:.2f}, {v[2]:.2f}]" for k, v in x.items()) for d, x in diag.items()]
    (ROOT / "results" / "summary.md").write_text("\n".join(md), encoding="utf-8")
    (ROOT / "results" / "summary.json").write_text(json.dumps(js, indent=1), encoding="utf-8")
    print(f"wrote results/summary.md ({len(md)} lines)")


if __name__ == "__main__":
    main()
