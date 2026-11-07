"""Exploration (seed 43): two guards for the site-calibrated mixture threshold, on the fresh split.

floor: each threshold is at least the largest single-event increment of its statistic (LLR_CLIP for
       the CUSUM, mix_llr(LLR_CLIP) for the mixture), so no single benign event can isolate a device.
boot:  the 90th percentile of the calibrated thresholds over 20 bootstrap resamples of the
       calibration rows (row-pool uncertainty).
Usage: py -3.13 code/explore_threshold_floor.py
"""
import numpy as np

from fix_experiment import N_CAL, SCEN, cal_traces, joint_thresholds
from gwcore import LLR_CLIP, T_EV, Evidence, authorize, cusum_max, metrics, mix_llr, streams
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FL1, FL2 = LLR_CLIP, float(mix_llr(np.array(LLR_CLIP)))
for ds in ("edgeiiot", "forge", "wustl"):
    seed = 43
    z = np.load(ROOT / "data" / "scores" / f"{ds}_s{seed}.npz", allow_pickle=True)
    s_val, s_te, y_val, y_te, t_val, t_te, seen = (z[k] for k in ("s_val", "s_te", "y_val", "y_te", "t_val", "t_te", "seen"))
    llr = Evidence(s_val, y_val, t_val)
    ben = np.flatnonzero(y_te == 0)
    cal_rows = np.random.default_rng([seed, 12]).permutation(ben)[: len(ben) // 2]
    eval_rows = np.setdiff1d(np.arange(len(y_te)), cal_rows)
    pool = s_te[cal_rows]
    for name in ("iid", "ar0.5", "ar0.9", "ar0.99", "het0.5"):
        kw = SCEN[name]
        code = int(100 * kw.get("phi", 0)) + 1000 * int(100 * kw.get("sigma", 0))
        Lc = llr(cal_traces(seed, code, pool, N_CAL, T_EV, **kw))
        ha, hb = joint_thresholds(cusum_max(Lc), cusum_max(mix_llr(Lc)))
        bs = []
        for b in range(20):
            pb = pool[np.random.default_rng([seed, 13, b]).integers(0, len(pool), len(pool))]
            Lb = llr(cal_traces(seed, code + 7 + b, pb, N_CAL, T_EV, **kw))
            bs.append(joint_thresholds(cusum_max(Lb), cusum_max(mix_llr(Lb))))
        bs = np.array(bs)
        ua, ub = np.percentile(bs[:, 0], 90), np.percentile(bs[:, 1], 90)
        row = []
        for rho in (1.0, 0.2, 0.05):
            S, A, tau, tgt = streams(np.random.default_rng([seed, int(rho * 100), 5]), s_te, y_te, t_te, rho, rows=eval_rows, **kw)
            L = llr(S)
            Lm = mix_llr(L)
            cells = []
            for tag, (a, b) in (("cal", (ha, hb)), ("floor", (max(ha, FL1), max(hb, FL2))), ("boot", (ua, ub)),
                                ("boot+floor", (max(ua, FL1), max(ub, FL2)))):
                m = metrics(S, A, tau, tgt, authorize(S, L, a, Lm, b, Lq=Lm))
                cells.append(f"{tag} {100 * m['false_isolation_rate']:.1f}/{100 * m['detection_rate']:.0f}")
            row.append(f"rho{rho:g}: " + ", ".join(cells))
        print(f"{ds} {name} h=({ha:.1f},{hb:.1f}) boot=({ua:.1f},{ub:.1f}) | " + " | ".join(row), flush=True)
