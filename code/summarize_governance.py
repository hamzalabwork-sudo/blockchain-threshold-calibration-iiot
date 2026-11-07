"""Summarize G1 (results/governance/) and L1 (results/chain/) into results/governance_summary.md.

Usage: py -3.13 code/summarize_governance.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DS = {"edgeiiot": "Edge", "forge": "Forge", "wustl": "WUSTL"}
PHIS = ("0", "0.5", "0.9", "0.99")


def main() -> None:
    R = {d: [json.loads(p.read_text()) for p in sorted((ROOT / "results" / "governance").glob(f"{d}_s*.json"))] for d in DS}
    md = ["# Governance (G1) and ledger (L1) summary, held-out seeds 44-51", ""]
    ok = all(r["rederive"]["identical"] and r["rederive"]["commit_changes_on_one_row"] for rs in R.values() for r in rs)
    md += [f"Re-derivation identical and commitment sensitive to one row in all {sum(map(len, R.values()))} runs: {ok}", ""]
    md += ["## Threshold manipulation and contaminated recording (mean over seeds)", "",
           "| dataset | traffic | rho | k=0.25 FI/det | k=0.5 | k=1 | k=2 | k=4 | contaminated FI/det |", "|---" * 9 + "|"]
    for d, rs in R.items():
        for sc in ("iid", "ar0.9"):
            for rho in ("0.2", "0.05"):
                cells = []
                for k in ("0.25", "0.5", "1", "2", "4"):
                    m = [r["manipulation"][f"{sc}/rho{rho}/x{k}"] for r in rs]
                    cells.append(f"{100 * np.mean([x['false_isolation_rate'] for x in m]):.1f} / "
                                 f"{100 * np.mean([x['detection_rate'] for x in m]):.0f}")
                c = [r["contaminated"][f"{sc}/rho{rho}"] for r in rs]
                cells.append(f"{100 * np.mean([x['false_isolation_rate'] for x in c]):.1f} / "
                             f"{100 * np.mean([x['detection_rate'] for x in c]):.0f}")
                md.append(f"| {DS[d]} | {sc} | {rho} | " + " | ".join(cells) + " |")
    md += ["", "## Dependence monitor: share of runs that request recalibration (%), rows live phi, columns calibrated phi", ""]
    for d, rs in R.items():
        for rho in ("0.2", "1"):
            md += [f"**{DS[d]}, rho {rho}**", "", "| live \\ cal | " + " | ".join(PHIS) + " |", "|---" * 5 + "|"]
            for pl in PHIS:
                md.append(f"| {pl} | " + " | ".join(
                    f"{100 * np.mean([r['monitor'][f'rho{rho}/live{pl}/cal{pc}']['flag'] for r in rs]):.0f}" for pc in PHIS) + " |")
            md.append("")
    md += ["## Ledger (L1)", "", "| network | client | deploy gas | op | gas | latency median (s) | p95 (s) |", "|---" * 7 + "|"]
    for n in ("anvil", "clique"):
        p = ROOT / "results" / "chain" / f"{n}.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text())
        for op in ("publishModel", "propose", "approve", "requestRecalibration"):
            s = r["summary"][op]
            md.append(f"| {n} | {r['client']} | {r['deploy_gas']} | {op} | {s['gas']} | {s['lat_median_s']:.2f} | {s['lat_p95_s']:.2f} |")
        md.append(f"| {n} | | | view thresholds() | 0 | {r['summary']['view_ms_median'] / 1e3:.3f} | |")
        md.append(f"| {n} | | | violations rejected | {r['summary']['violations_rejected']} | | |")
        md.append(f"| {n} | | | tests | " + "; ".join(f"{k}: {v.get('reason', v)}" for k, v in r["tests"].items()) + " | | |")
    (ROOT / "results" / "governance_summary.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:12]))


if __name__ == "__main__":
    main()
