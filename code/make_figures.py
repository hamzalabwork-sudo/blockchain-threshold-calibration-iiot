"""Figures for paper 2 from results/summary.json (held-out seeds 44-51).

fig_budget.pdf (double column): top row, false isolation at rho 0.2 against benign dependence phi;
bottom row, detection against the attack rate rho on AR(1) phi = 0.9 traffic. One column per dataset.
Usage: py -3.13 code/make_figures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "paper" / "figures"
DS = {"edgeiiot": "Edge-IIoTset", "forge": "IoTForge Pro", "wustl": "WUSTL-IIoT"}
# Okabe-Ito (colour-blind safe); identity also carried by marker and line style
POL = {"bound": ("Bound threshold", "#7F7F7F", "o", "-"),
       "bound_mix": ("Bound + mixture", "#000000", "s", ":"),
       "cal": ("Calibrated", "#E69F00", "v", "--"),
       "guard": ("Calibrated + mixture, guarded", "#0072B2", "D", "-")}
FLOOR = 0.05


def main() -> None:
    J = json.loads((ROOT / "results" / "summary.json").read_text())["fresh_held"]
    FI, DE = J["false_isolation_rate"], J["detection_rate"]
    scen = [("iid", "0"), ("ar0.5", "0.5"), ("ar0.9", "0.9"), ("ar0.99", "0.99")]
    rhos = ["1", "0.5", "0.2", "0.1", "0.05"]
    with plt.rc_context({"font.size": 8, "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
                         "font.family": "serif", "font.serif": ["Times New Roman"],
                         "mathtext.fontset": "stix", "pdf.fonttype": 42}):
        fig, ax = plt.subplots(2, 3, figsize=(7.16, 2.8), sharey="row")
        for j, d in enumerate(DS):
            a = ax[0, j]
            for p, (lab, col, mk, ls) in POL.items():
                mean = [max(FLOOR, FI[d][f"{s}/rho0.2"][p][0]) for s, _ in scen]
                worst = [max(FLOOR, FI[d][f"{s}/rho0.2"][p][1]) for s, _ in scen]
                x = range(len(scen))
                a.plot(x, mean, color=col, marker=mk, ls=ls, lw=1.2, ms=4, label=lab)
                a.vlines(x, mean, worst, color=col, lw=0.8, alpha=0.7)
            a.axhline(1.0, color="#D55E00", lw=0.9, ls="--", label="1% budget")
            a.set_yscale("log")
            a.set_ylim(FLOOR * 0.8, 100)
            a.set_xticks(range(len(scen)), [lbl for _, lbl in scen])
            a.set_xlabel(r"benign dependence $\phi$")
            a.set_title(DS[d], fontsize=8.5)
            a.grid(axis="y", lw=0.3, color="#DDDDDD")
            if j == 0:
                a.set_ylabel("false isolation (%)")
            b = ax[1, j]
            for p, (lab, col, mk, ls) in POL.items():
                mean = [DE[d][f"ar0.9/rho{r}"][p][0] for r in rhos]
                worst = [DE[d][f"ar0.9/rho{r}"][p][1] for r in rhos]
                x = range(len(rhos))
                b.plot(x, mean, color=col, marker=mk, ls=ls, lw=1.2, ms=4)
                b.vlines(x, worst, mean, color=col, lw=0.8, alpha=0.7)
            b.set_xticks(range(len(rhos)), rhos)
            b.set_ylim(-3, 103)
            b.set_xlabel(r"attack rate $\rho$ ($\phi=0.9$)")
            b.grid(axis="y", lw=0.3, color="#DDDDDD")
            if j == 0:
                b.set_ylabel("detection (%)")
        h, l = ax[0, 0].get_legend_handles_labels()
        fig.legend(h, l, loc="upper center", ncol=5, frameon=False, bbox_to_anchor=(0.5, 1.01), fontsize=7, columnspacing=1.2, handlelength=2.2)
        fig.tight_layout(rect=(0, 0, 1, 0.94), h_pad=0.6, w_pad=0.6)
        FIG.mkdir(parents=True, exist_ok=True)
        fig.savefig(FIG / "fig_budget.pdf", bbox_inches="tight")
        fig.savefig(FIG / "fig_budget.png", dpi=200, bbox_inches="tight")
    print("wrote", FIG / "fig_budget.pdf")


if __name__ == "__main__":
    main()
