"""Paper 2, experiment F1: restoring the gateway's false-isolation budget under serially correlated traffic.

The deployed CUSUM threshold h = log(T / budget) is a Ville / union bound, valid when the evidence l
satisfies E_0[e^l | past] <= 1, i.e. when benign events are conditionally independent. On AR(1)
benign traffic it breaks (E14). Two fixes, each alone and with the rho-mixture CUSUM:

- cal:    site-calibrated threshold. The operator records benign traces from the site (N_CAL benign
          streams with the site's dependence) and sets h to
          the (1 - budget) quantile of the per-stream CUSUM maximum. With the mixture CUSUM both
          thresholds sit at a common quantile level chosen so that the share of calibration streams
          where either fires is the budget.
- guard:  the site-calibrated mixture thresholds with two guards (chosen on seed 43, the design seed;
          seeds 44-51 are held out): (i) the 90th percentile of the calibrated thresholds over
          BOOTS bootstrap resamples of the calibration rows (row-pool uncertainty), and (ii) a floor
          at the largest single-event increment of each statistic, so that no single benign event
          can isolate a device.
- boot / floor: each guard alone (ablation).
- temper: tempered evidence l / c, where c >= 1 is the long-run variance inflation of l estimated by
          batch means on the same calibration traces; the bound threshold is kept. For c >= 1,
          E_0[e^(l/c)] <= E_0[e^l]^(1/c) <= 1 (Jensen), so the i.i.d. guarantee is preserved.

Also: a calibration-misspecification matrix (calibrate at phi_cal, run at phi_eval, rho 0.2) and the
long horizon (200 devices x 10,000 events).

Calibration source (--cal-source):
- fresh (default): the test split's benign rows are split in two disjoint halves per seed; the
  calibration traces come from one half ("recorded at the site after deployment"), every evaluation
  stream from the other half plus all attack rows. Nothing used for calibration is evaluated.
- val: calibration traces from the validation split, the same rows the evidence table is fitted on
  (in-sample). Evaluation streams then use the whole test split with the E14 seeds, so the "bound"
  policies reproduce E14 exactly (code/check_reproduces_e14.py).

Inputs: data/scores/<dataset>_s<seed>.npz (cached detector scores of the clean federated MLP).
Outputs: results/fix_<cal-source>/<dataset>_s<seed>.json
Usage: py -3.13 code/fix_experiment.py [--datasets edgeiiot,forge,wustl] [--seeds 43,...,51]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from gwcore import (BUDGET, LLR_CLIP, N_DEV, T_EV, Evidence, authorize, benign_rows, cusum_max, h_bound,
                    metrics, mix_llr, streams)

ROOT = Path(__file__).resolve().parents[1]
RHOS = (1.0, 0.5, 0.2, 0.1, 0.05)
SCEN = {"iid": {}, "ar0.5": {"phi": 0.5}, "ar0.9": {"phi": 0.9}, "ar0.99": {"phi": 0.99},
        "het0.5": {"sigma": 0.5}, "unseen": {"unseen": True}}
N_CAL, N_CAL_LONG = 2000, 1000
PHIS = (0.0, 0.5, 0.9, 0.99)
BOOTS, BOOTS_LONG, BOOT_Q = 20, 10, 90
FLOOR = (LLR_CLIP, float(mix_llr(np.array(LLR_CLIP))))


def cal_traces(seed, code, ben, n, t, phi=0.0, sigma=0.0, period=0):
    """n benign calibration streams of t events from the score pool ben, with the site's dependence."""
    rng = np.random.default_rng([seed, code, 11])
    return ben[benign_rows(rng, ben, n, t, phi, sigma, period)]


def inflation(L: np.ndarray, blocks: int = 5) -> float:
    """Long-run variance inflation of the evidence by batch means: Var(batch sum) / (b Var(l))."""
    n, t = L.shape
    b = t // blocks
    X = L[:, : b * blocks].reshape(n, blocks, b).sum(-1)
    return float(max(1.0, X.var() / (b * L.var())))


def joint_thresholds(m1: np.ndarray, m2: np.ndarray, budget: float = BUDGET) -> tuple[float, float]:
    """Common quantile level p with share(m1 > q1(p) or m2 > q2(p)) <= budget (bisection on p)."""
    lo, hi = 1 - budget, 1.0
    for _ in range(40):
        p = (lo + hi) / 2
        q1, q2 = np.quantile(m1, p), np.quantile(m2, p)
        if ((m1 > q1) | (m2 > q2)).mean() <= budget:
            hi = p
        else:
            lo = p
    return float(np.quantile(m1, hi)), float(np.quantile(m2, hi))


class Calib:
    """Thresholds and tempering factor from a site's benign calibration traces (n streams of t events
    drawn from the calibration pool with the site's dependence kw), plus the guarded thresholds."""

    def __init__(self, llr, pool: np.ndarray, seed: int, code: int, n: int, t: int, kw: dict, boots: int):
        Lc = llr(cal_traces(seed, code, pool, n, t, **kw))
        m1, m2 = cusum_max(Lc), cusum_max(mix_llr(Lc))
        self.h = float(np.quantile(m1, 1 - BUDGET))
        self.h_a, self.h_b = joint_thresholds(m1, m2)
        self.c = inflation(Lc)
        self.t = t
        bs = []
        for b in range(boots):
            pb = pool[np.random.default_rng([seed, 13, b]).integers(0, len(pool), len(pool))]
            Lb = llr(cal_traces(seed, code + 7 + b, pb, n, t, **kw))
            bs.append(joint_thresholds(cusum_max(Lb), cusum_max(mix_llr(Lb))))
        bs = np.array(bs)
        self.b_a, self.b_b = float(np.percentile(bs[:, 0], BOOT_Q)), float(np.percentile(bs[:, 1], BOOT_Q))
        self.f_a, self.f_b = max(self.h_a, FLOOR[0]), max(self.h_b, FLOOR[1])
        self.g_a = max(float(np.percentile(bs[:, 0], BOOT_Q)), FLOOR[0])
        self.g_b = max(float(np.percentile(bs[:, 1], BOOT_Q)), FLOOR[1])

    def as_dict(self) -> dict:
        return {"h_cal": self.h, "h_cal_mix": [self.h_a, self.h_b], "h_guard_mix": [self.g_a, self.g_b],
                "h_boot_mix": [self.b_a, self.b_b], "h_floor_mix": [self.f_a, self.f_b], "c": self.c,
                "h_bound": h_bound(self.t), "h_bound_mix": h_bound(self.t, 2)}


def policies(S, A, tau, tgt, L, cb: Calib, which=("bound", "bound_mix", "cal", "cal_mix", "boot", "floor", "guard", "temper", "temper_mix")) -> dict:
    t = S.shape[1]
    Lm = mix_llr(L)
    Lt = L / cb.c
    Ltm = mix_llr(Lt)
    hb, hb2 = h_bound(t), h_bound(t, 2)
    run = {"bound": lambda: authorize(S, L, hb, Lq=Lm),
           "bound_mix": lambda: authorize(S, L, hb2, Lm, hb2, Lq=Lm),
           "cal": lambda: authorize(S, L, cb.h, Lq=Lm),
           "cal_mix": lambda: authorize(S, L, cb.h_a, Lm, cb.h_b, Lq=Lm),
           "boot": lambda: authorize(S, L, cb.b_a, Lm, cb.b_b, Lq=Lm),
           "floor": lambda: authorize(S, L, cb.f_a, Lm, cb.f_b, Lq=Lm),
           "guard": lambda: authorize(S, L, cb.g_a, Lm, cb.g_b, Lq=Lm),
           "temper": lambda: authorize(S, Lt, hb, Lq=Ltm),
           "temper_mix": lambda: authorize(S, Lt, hb2, Ltm, hb2, Lq=Ltm)}
    return {k: metrics(S, A, tau, tgt, run[k]()) for k in which}


def run(ds: str, seed: int, cal_source: str) -> dict:
    t0 = time.perf_counter()
    z = np.load(ROOT / "data" / "scores" / f"{ds}_s{seed}.npz", allow_pickle=True)
    s_val, s_te, y_val, y_te, t_val, t_te, seen = (z[k] for k in ("s_val", "s_te", "y_val", "y_te", "t_val", "t_te", "seen"))
    llr = Evidence(s_val, y_val, t_val)
    if cal_source == "fresh":
        ben = np.flatnonzero(y_te == 0)
        cal_rows = np.random.default_rng([seed, 12]).permutation(ben)[: len(ben) // 2]
        eval_rows = np.setdiff1d(np.arange(len(y_te)), cal_rows)
        cal_pool = s_te[cal_rows]
    else:
        eval_rows, cal_pool = None, s_val[y_val == 0]
    unseen_rows = np.flatnonzero(~seen) if eval_rows is None else np.intersect1d(eval_rows, np.flatnonzero(~seen))
    res = {"dataset": ds, "seed": seed, "cal_source": cal_source, "cal_rows": int(len(cal_pool)),
           "calibration": {}, "scenarios": {}, "misspec": {}, "long": {}}
    cals = {}
    for name, kw in SCEN.items():
        ckw = {k: v for k, v in kw.items() if k in ("phi", "sigma")}
        code = int(100 * ckw.get("phi", 0)) + 1000 * int(100 * ckw.get("sigma", 0))
        cals[name] = Calib(llr, cal_pool, seed, code, N_CAL, T_EV, ckw, BOOTS)
        res["calibration"][name] = cals[name].as_dict()
    for rho in RHOS:
        for name, kw in SCEN.items():
            skw = {"rows": unseen_rows} if kw.get("unseen") else (kw | {"rows": eval_rows})
            S, A, tau, tgt = streams(np.random.default_rng([seed, int(rho * 100), 5]), s_te, y_te, t_te, rho, **skw)
            res["scenarios"][f"{name}/rho{rho:g}"] = policies(S, A, tau, tgt, llr(S), cals[name])
    # misspecification: calibrate at phi_cal, evaluate at phi_eval (rho 0.2)
    pc = {phi: (cals["iid"] if phi == 0 else cals[f"ar{phi:g}"]) for phi in PHIS}
    for pe in PHIS:
        S, A, tau, tgt = streams(np.random.default_rng([seed, 20, 5]), s_te, y_te, t_te, 0.2, phi=pe, rows=eval_rows)
        L = llr(S)
        for pcal in PHIS:
            res["misspec"][f"eval{pe:g}/cal{pcal:g}"] = policies(S, A, tau, tgt, L, pc[pcal], ("cal", "cal_mix", "guard"))
    # long horizon
    for name, phi in (("long_iid", 0.0), ("long_ar0.9", 0.9)):
        cb = Calib(llr, cal_pool, seed, 5000 + int(100 * phi), N_CAL_LONG, 10_000, {"phi": phi} if phi else {}, BOOTS_LONG)
        res["calibration"][name] = cb.as_dict()
        for rho in (0.2, 0.05):
            S, A, tau, tgt = streams(np.random.default_rng([seed, int(rho * 100), 6]), s_te, y_te, t_te, rho,
                                     n=200, t=10_000, phi=phi, rows=eval_rows)
            res["long"][f"{name}/rho{rho:g}"] = policies(S, A, tau, tgt, llr(S), cb)
    res["config"] = {"n_dev": N_DEV, "t_ev": T_EV, "budget": BUDGET, "n_cal": N_CAL, "n_cal_long": N_CAL_LONG,
                     "boots": BOOTS, "boots_long": BOOTS_LONG,
                     "boot_q": BOOT_Q, "floor": FLOOR, "wall_seconds": time.perf_counter() - t0}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="edgeiiot,forge,wustl")
    ap.add_argument("--seeds", default="43,44,45,46,47,48,49,50,51")
    ap.add_argument("--cal-source", choices=("fresh", "val"), default="fresh")
    args = ap.parse_args()
    out_dir = ROOT / "results" / f"fix_{args.cal_source}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for seed in map(int, args.seeds.split(",")):
        for ds in args.datasets.split(","):
            out = out_dir / f"{ds}_s{seed}.json"
            if out.exists():
                continue
            r = run(ds, seed, args.cal_source)
            out.write_text(json.dumps(r, indent=1))
            a = r["scenarios"]["ar0.9/rho0.2"]
            print(f"[{ds}/s{seed}] c(ar0.9)={r['calibration']['ar0.9']['c']:.2f} h_cal={r['calibration']['ar0.9']['h_cal']:.2f} | "
                  f"ar0.9 rho0.2 FI bound={a['bound']['false_isolation_rate']:.3f} cal={a['cal']['false_isolation_rate']:.3f} "
                  f"guard={a['guard']['false_isolation_rate']:.3f} | det bound={a['bound']['detection_rate']:.3f} "
                  f"cal={a['cal']['detection_rate']:.3f} guard={a['guard']['detection_rate']:.3f} "
                  f"({r['config']['wall_seconds']:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
