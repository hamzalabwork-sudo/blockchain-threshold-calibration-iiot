"""Paper 2, experiment G1: why the thresholds need governance, and the dependence monitor.

On the held-out seeds (fresh split, as in fix_experiment.py), per dataset and seed:

1. manipulation: the guarded thresholds (h, h2) scaled by k; k < 1 is an insider who lowers them
   (the ledger's floor rule forbids going below the single-event floor), k > 1 one who raises them
   to let an attacker through (needs a colluding auditor on the ledger, and is exposed by re-deriving
   the thresholds from the committed recording). False isolation, detection and attack events granted
   per 10^4 events, on independent and AR(1) phi=0.9 traffic, rho 0.2 and 0.05.
2. contaminated recording: 5% of the recorded traces come from a device attacking at rate 0.2 from
   its first event; the resulting thresholds are evaluated on the same live streams.
3. re-derivation: the auditor recomputes the guarded thresholds from the committed recording (the
   calibration rows and seed) and must get identical values; the SHA-256 commitment changes if a
   single recorded row is altered.
4. dependence monitor: the gateway computes D, the median over devices of the lag-1 correlation of
   normal scores u = Phi^-1(F_cal(s)) over its events 400-499 (after every compromise), and requests
   recalibration if D > D_cal + DELTA, where D_cal is the same statistic on the recording. Flag rate
   for every (phi_cal, phi_live) pair at rho 0.2 and 1.

Outputs: results/governance/<dataset>_s<seed>.json
Usage: py -3.13 code/governance_sim.py [--seeds 44,...,51]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.stats import norm

from fix_experiment import BOOTS, N_CAL, PHIS, SCEN, Calib, cal_traces
from gwcore import COMPROMISED, T_EV, Evidence, authorize, metrics, mix_llr, streams

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "governance"
SCALES = (0.25, 0.5, 1.0, 2.0, 4.0)
DELTA, W0, W1 = 0.1, 400, 500
CONTAM = 0.05


def code_of(kw: dict) -> int:
    return int(100 * kw.get("phi", 0)) + 1000 * int(100 * kw.get("sigma", 0))


def dep_stat(S: np.ndarray, pool_sorted: np.ndarray, w0: int = W0, w1: int = W1) -> float:
    """Median over devices of the lag-1 correlation of normal scores in events [w0, w1)."""
    n = len(pool_sorted)
    x = S[:, w0:w1]
    F = (np.searchsorted(pool_sorted, x, "left") + np.searchsorted(pool_sorted, x, "right")) / (2 * n)
    u = norm.ppf(np.clip(F, 0.5 / n, 1 - 0.5 / n))
    a, b = u[:, :-1] - u[:, :-1].mean(1, keepdims=True), u[:, 1:] - u[:, 1:].mean(1, keepdims=True)
    den = np.sqrt((a ** 2).sum(1) * (b ** 2).sum(1))
    r = np.where(den > 0, (a * b).sum(1) / np.where(den > 0, den, 1), np.nan)
    return float(np.nanmedian(r))


def run(ds: str, seed: int) -> dict:
    t0 = time.perf_counter()
    z = np.load(ROOT / "data" / "scores" / f"{ds}_s{seed}.npz", allow_pickle=True)
    s_val, s_te, y_val, y_te, t_val, t_te = (z[k] for k in ("s_val", "s_te", "y_val", "y_te", "t_val", "t_te"))
    llr = Evidence(s_val, y_val, t_val)
    ben = np.flatnonzero(y_te == 0)
    cal_rows = np.random.default_rng([seed, 12]).permutation(ben)[: len(ben) // 2]
    eval_rows = np.setdiff1d(np.arange(len(y_te)), cal_rows)
    pool = s_te[cal_rows]
    pool_sorted = np.sort(pool)
    res = {"dataset": ds, "seed": seed, "manipulation": {}, "contaminated": {}, "rederive": {}, "monitor": {}}
    cals = {}
    for name in ("iid", "ar0.5", "ar0.9", "ar0.99"):
        kw = {k: v for k, v in SCEN[name].items() if k == "phi"}
        cals[name] = Calib(llr, pool, seed, code_of(kw), N_CAL, T_EV, kw, BOOTS)
    # 3. re-derivation from the committed recording
    commit = hashlib.sha256(np.ascontiguousarray(pool).tobytes() + seed.to_bytes(4, "big")).hexdigest()
    again = Calib(llr, pool.copy(), seed, code_of({"phi": 0.9}), N_CAL, T_EV, {"phi": 0.9}, BOOTS)
    tampered = pool.copy()
    tampered[np.argmax(tampered)] *= 0.999
    res["rederive"] = {"identical": bool(again.g_a == cals["ar0.9"].g_a and again.g_b == cals["ar0.9"].g_b),
                       "commit_changes_on_one_row": commit != hashlib.sha256(
                           np.ascontiguousarray(tampered).tobytes() + seed.to_bytes(4, "big")).hexdigest()}
    for name in ("iid", "ar0.9"):
        kw = {k: v for k, v in SCEN[name].items() if k == "phi"}
        cb = cals[name]
        # 2. contaminated recording: a share CONTAM of the recorded traces is an attacking device
        Sc = cal_traces(seed, code_of(kw), pool, N_CAL, T_EV, **kw).copy()
        rng = np.random.default_rng([seed, 14])
        att = np.flatnonzero(y_te == 1)
        for dev in rng.choice(N_CAL, int(CONTAM * N_CAL), replace=False):
            typ = rng.choice(np.unique(t_te[att]))
            hit = rng.random(T_EV) < 0.2
            Sc[dev, hit] = s_te[rng.choice(att[t_te[att] == typ], hit.sum())]
        from fix_experiment import joint_thresholds
        from gwcore import cusum_max
        Lc = llr(Sc)
        ca, cbb = joint_thresholds(cusum_max(Lc), cusum_max(mix_llr(Lc)))
        for rho in (0.2, 0.05):
            S, A, tau, tgt = streams(np.random.default_rng([seed, int(rho * 100), 5]), s_te, y_te, t_te, rho,
                                     rows=eval_rows, **kw)
            L = llr(S)
            Lm = mix_llr(L)
            for k in SCALES:
                m = metrics(S, A, tau, tgt, authorize(S, L, k * cb.g_a, Lm, k * cb.g_b, Lq=Lm))
                res["manipulation"][f"{name}/rho{rho:g}/x{k:g}"] = m
            m = metrics(S, A, tau, tgt, authorize(S, L, max(ca, cb.g_a), Lm, max(cbb, cb.g_b), Lq=Lm))
            res["contaminated"][f"{name}/rho{rho:g}"] = m | {"h": [ca, cbb], "h_clean": [cb.g_a, cb.g_b]}
    # 4. dependence monitor
    dcal = {}
    for name in ("iid", "ar0.5", "ar0.9", "ar0.99"):
        kw = {k: v for k, v in SCEN[name].items() if k == "phi"}
        dcal[name] = dep_stat(cal_traces(seed, code_of(kw), pool, N_CAL, T_EV, **kw), pool_sorted)
    names = {0.0: "iid", 0.5: "ar0.5", 0.9: "ar0.9", 0.99: "ar0.99"}
    for rho in (0.2, 1.0):
        for pl in PHIS:
            S, A, tau, tgt = streams(np.random.default_rng([seed, int(rho * 100), 15]), s_te, y_te, t_te, rho,
                                     rows=eval_rows, phi=pl)
            d = dep_stat(S, pool_sorted)
            for pc in PHIS:
                res["monitor"][f"rho{rho:g}/live{pl:g}/cal{pc:g}"] = {"D_live": d, "D_cal": dcal[names[pc]],
                                                                      "flag": bool(d > dcal[names[pc]] + DELTA)}
    res["config"] = {"scales": SCALES, "delta": DELTA, "window": [W0, W1], "contam": CONTAM, "compromised": COMPROMISED,
                     "wall_seconds": time.perf_counter() - t0}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="edgeiiot,forge,wustl")
    ap.add_argument("--seeds", default="44,45,46,47,48,49,50,51")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for seed in map(int, args.seeds.split(",")):
        for ds in args.datasets.split(","):
            out = OUT / f"{ds}_s{seed}.json"
            if out.exists():
                continue
            r = run(ds, seed)
            out.write_text(json.dumps(r, indent=1))
            mo = r["monitor"]
            print(f"[{ds}/s{seed}] rederive={r['rederive']} | D(live0.9)={mo['rho0.2/live0.9/cal0']['D_live']:.3f} "
                  f"Dcal(0)={mo['rho0.2/live0.9/cal0']['D_cal']:.3f} Dcal(0.9)={mo['rho0.2/live0.9/cal0.9']['D_cal']:.3f} | "
                  f"x0.25 iid FI={r['manipulation']['iid/rho0.2/x0.25']['false_isolation_rate']:.3f} "
                  f"x4 ar0.9 det={r['manipulation']['ar0.9/rho0.2/x4']['detection_rate']:.3f} "
                  f"contam ar0.9 det={r['contaminated']['ar0.9/rho0.2']['detection_rate']:.3f} "
                  f"({r['config']['wall_seconds']:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
