"""Summarize C1 (results/baselines/) into results/baselines_summary.md and .json.

Held-out seeds 44-51 (seed 43 separately). Per method and (traffic, rho): false isolation as the mean
over datasets and seeds and the worst (dataset, seed); detection and median time to isolation as the
mean over datasets and seeds; plus the per-dataset means.
Usage: py -3.13 code/summarize_baselines.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DS = {"edgeiiot": "Edge", "forge": "Forge", "wustl": "WUSTL"}
METHODS = ["kofw", "ewma", "residual_cusum", "bound", "ours", "ours_residual"]
SCEN = ["iid", "ar0.5", "ar0.9", "ar0.99", "periodic"]
RHOS = ["1", "0.2", "0.05"]


def main() -> None:
    js, md = {}, ["# C1: comparison with established isolation rules (same recording, same 1% budget)", ""]
    for tag, seeds in (("held", range(44, 52)), ("design", [43])):
        R = {d: [json.loads((ROOT / "results" / "baselines" / f"{d}_s{s}.json").read_text()) for s in seeds] for d in DS}
        J = js.setdefault(tag, {})
        md += [f"## {tag} seeds {list(seeds)}", "",
               "| traffic | rho | method | FI mean | FI worst | det mean | TTI mean | per-dataset FI / det |",
               "|---" * 8 + "|"]
        for sc in SCEN:
            for rho in RHOS:
                for m in METHODS:
                    fi = [100 * r["scenarios"][f"{sc}/rho{rho}"][m]["false_isolation_rate"] for rs in R.values() for r in rs]
                    de = [100 * r["scenarios"][f"{sc}/rho{rho}"][m]["detection_rate"] for rs in R.values() for r in rs]
                    tt = [r["scenarios"][f"{sc}/rho{rho}"][m]["tti_median"] for rs in R.values() for r in rs]
                    tt = [x for x in tt if x is not None]
                    per = {DS[d]: [float(np.mean([100 * r["scenarios"][f"{sc}/rho{rho}"][m]["false_isolation_rate"] for r in rs])),
                                   float(np.mean([100 * r["scenarios"][f"{sc}/rho{rho}"][m]["detection_rate"] for r in rs]))]
                           for d, rs in R.items()}
                    J[f"{sc}/rho{rho}/{m}"] = {"fi_mean": float(np.mean(fi)), "fi_worst": float(max(fi)),
                                               "det_mean": float(np.mean(de)), "tti_mean": float(np.mean(tt)) if tt else None,
                                               "per_dataset": per}
                    md.append(f"| {sc} | {rho} | {m} | {np.mean(fi):.1f} | {max(fi):.1f} | {np.mean(de):.0f} | "
                              f"{(np.mean(tt) if tt else float('nan')):.0f} | "
                              + "; ".join(f"{k} {v[0]:.1f}/{v[1]:.0f}" for k, v in per.items()) + " |")
        md.append("")
    (ROOT / "results" / "baselines_summary.md").write_text("\n".join(md), encoding="utf-8")
    (ROOT / "results" / "baselines_summary.json").write_text(json.dumps(js, indent=1), encoding="utf-8")
    print(f"wrote results/baselines_summary.md ({len(md)} lines)")


if __name__ == "__main__":
    main()
