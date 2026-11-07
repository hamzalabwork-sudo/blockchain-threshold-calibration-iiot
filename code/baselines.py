"""Paper 2, experiment C1: comparison with established isolation rules, all calibrated on the same recording.

Every rule runs in the same gateway state machine as ours (per-event deny; an alarm opens the same
quarantine SPRT on the mixture evidence; re-admission resets the rule's statistic) and is calibrated on
the same benign recording (the calibration traces of fix_experiment.Calib, fresh split) to the same
1% false-isolation budget, as the quantile of the rule's per-trace extreme:

- k-of-W: isolate when at least c of the last W=20 events were flagged by the detector (s >= 0.5), the
  count rule common in IDS practice; c is the smallest integer reached by at most beta of the traces;
- EWMA trust: T_t = lam T_{t-1} + (1 - lam)(1 - s_t), lam = 0.9, isolate when T_t < theta, the
  weighted-trust score of Zero-Trust IoT designs (the detector term only, as in the IoTJ simulator);
- residual CUSUM (Alwan and Roberts; Lu and Reynolds): normal scores u = Phi^-1(F_rec(s)), an AR(1)
  fitted on the recording (phi_hat, pooled lag-1 correlation), standardized residuals
  r_t = (u_t - phi_hat u_{t-1}) / sqrt(1 - phi_hat^2), and the CUSUM max(0, S + r - k), k = 0.5;
- ours (guarded calibrated CUSUM + rho-mixture CUSUM) and the bound, recomputed on the same streams;
- ours + residual: the residual CUSUM run in parallel with our two CUSUMs, the three thresholds set at
  a common quantile level on the recording (union at most beta), with the same row bootstrap (90th
  percentile of B=20 resamples) and the single-event floor on the two evidence CUSUMs.
Traffic: i.i.d., AR(1) rank copula (phi 0.5/0.9/0.99), and periodic polling (each device repeats its own
cycle of 5-15 benign rows; 10% of events replaced by a random row), a dependence the AR(1) model of the
residual CUSUM does not describe.

Outputs: results/baselines/<dataset>_s<seed>.json
Usage: py -3.13 code/baselines.py [--seeds 43,...,51]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy.stats import norm

from fix_experiment import BOOT_Q, BOOTS, FLOOR, N_CAL, Calib, cal_traces
from gwcore import (BUDGET, Q_MAX, SPRT_A, SPRT_B, T_EV, Evidence, authorize, cusum_max, h_bound, metrics,
                    mix_llr, streams)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "baselines"
W, LAM, K_RES = 20, 0.9, 0.5
RHOS = (1.0, 0.2, 0.05)
SCEN = {"iid": {}, "ar0.5": {"phi": 0.5}, "ar0.9": {"phi": 0.9}, "ar0.99": {"phi": 0.99}, "periodic": {"period": 10}}


def code_of(kw: dict) -> int:
    """Calibration-trace seed code; identical to governance_sim.code_of for the AR scenarios."""
    return int(100 * kw.get("phi", 0)) + 50_000 * int(kw.get("period", 0))


class Rule:
    """A sequential isolation rule: init(n) -> state, step(state, x_t, active) -> (state, stat), alarm(stat)."""

    def __init__(self, kind: str, th: float, **kw):
        self.kind, self.th, self.kw = kind, th, kw

    def run(self, X: np.ndarray, Lq: np.ndarray, S: np.ndarray):
        """The gateway state machine of gwcore.authorize with this rule as the change detector."""
        n, t = X.shape
        flag = S >= 0.5
        granted, admitted = np.zeros((n, t), bool), np.zeros((n, t), bool)
        state = np.zeros(n, np.int8)
        st = self.init(n)
        lam, qlen = np.zeros(n), np.zeros(n, int)
        quarantined, blocked = np.zeros(n, bool), np.zeros(n, bool)
        readmits = []
        for i in range(t):
            act = state == 0
            admitted[:, i] = act
            granted[:, i] = act & ~flag[:, i]
            q = state == 1
            lam[q] += Lq[q, i]
            qlen[q] += 1
            ok = q & (lam <= SPRT_B)
            bad = q & ~ok & ((lam >= SPRT_A) | (qlen >= Q_MAX))
            state[bad] = 2
            blocked |= bad
            state[ok] = 0
            st = self.reset(st, ok)
            readmits += [(int(dv), i) for dv in np.flatnonzero(ok)]
            st, stat = self.step(st, X, i, act)
            alarm = act & self.alarm(stat)
            state[alarm], lam[alarm], qlen[alarm] = 1, 0.0, 0
            quarantined |= alarm
        return granted, admitted, readmits, quarantined, blocked

    def init(self, n):
        if self.kind == "kofw":
            return {"buf": np.zeros((n, W), bool), "pos": 0}
        if self.kind == "ewma":
            return {"T": np.ones(n)}
        return {"S": np.zeros(n), "prev": np.zeros(n)}

    def reset(self, st, ok):
        if self.kind == "kofw":
            st["buf"][ok] = False
        elif self.kind == "ewma":
            st["T"][ok] = 1.0
        else:
            st["S"][ok] = 0.0
        return st

    def step(self, st, X, i, act):
        if self.kind == "kofw":
            st["buf"][:, i % W] = np.where(act, X[:, i] >= 0.5, False)
            return st, st["buf"].sum(1)
        if self.kind == "ewma":
            st["T"][act] = LAM * st["T"][act] + (1 - LAM) * (1 - X[act, i])
            return st, st["T"]
        phi = self.kw["phi"]
        r = (X[:, i] - phi * st["prev"]) / np.sqrt(1 - phi ** 2)
        st["prev"] = X[:, i]
        st["S"][act] = np.maximum(0.0, st["S"][act] + r[act] - K_RES)
        return st, st["S"]

    def alarm(self, stat):
        return stat < self.th if self.kind == "ewma" else stat >= self.th if self.kind == "kofw" else stat > self.th


def extremes(kind: str, X: np.ndarray, phi: float = 0.0) -> np.ndarray:
    """Per-trace extreme of the rule's statistic with no isolation (for calibration)."""
    n, t = X.shape
    if kind == "kofw":
        f = (X >= 0.5).astype(int)
        c = np.cumsum(np.pad(f, ((0, 0), (1, 0))), axis=1)
        return (c[:, W:] - c[:, :-W]).max(1) if t >= W else f.sum(1)
    if kind == "ewma":
        T, low = np.ones(n), np.ones(n)
        for i in range(t):
            T = LAM * T + (1 - LAM) * (1 - X[:, i])
            np.minimum(low, T, out=low)
        return low
    S, high, prev = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(t):
        r = (X[:, i] - phi * prev) / np.sqrt(1 - phi ** 2)
        prev = X[:, i]
        S = np.maximum(0.0, S + r - K_RES)
        np.maximum(high, S, out=high)
    return high


def normal_scores(s: np.ndarray, pool_sorted: np.ndarray) -> np.ndarray:
    n = len(pool_sorted)
    F = (np.searchsorted(pool_sorted, s, "left") + np.searchsorted(pool_sorted, s, "right")) / (2 * n)
    return norm.ppf(np.clip(F, 0.5 / n, 1 - 0.5 / n))


def joint3(m: list[np.ndarray], budget: float = BUDGET) -> list[float]:
    """Common quantile level p with share(any m_j > Q_p(m_j)) <= budget (bisection)."""
    lo, hi = 1 - budget, 1.0
    for _ in range(40):
        p = (lo + hi) / 2
        q = [np.quantile(x, p) for x in m]
        if np.any([x > qq for x, qq in zip(m, q)], axis=0).mean() <= budget:
            hi = p
        else:
            lo = p
    return [float(np.quantile(x, hi)) for x in m]


def union_thresholds(llr, pool, seed, code, kw, phi_hat, ps) -> list[float]:
    """Guarded joint thresholds of (CUSUM on l, CUSUM on l_rho0, residual CUSUM): bootstrap + floor."""
    bs = []
    for b in range(BOOTS):                          # the same resamples and traces as Calib's bootstrap
        pb = pool[np.random.default_rng([seed, 13, b]).integers(0, len(pool), len(pool))]
        Sb = cal_traces(seed, code + 7 + b, pb, N_CAL, T_EV, **kw)
        Lb = llr(Sb)
        bs.append(joint3([cusum_max(Lb), cusum_max(mix_llr(Lb)), extremes("res", normal_scores(Sb, ps), phi_hat)]))
    bs = np.array(bs)
    q = np.percentile(bs, BOOT_Q, axis=0)
    return [max(q[0], FLOOR[0]), max(q[1], FLOOR[1]), float(q[2])]


def union_run(S, L, Lm, U, h, phi):
    """Gateway with three parallel change detectors (any alarm quarantines); same SPRT as authorize."""
    n, t = S.shape
    flag = S >= 0.5
    granted, admitted = np.zeros((n, t), bool), np.zeros((n, t), bool)
    state = np.zeros(n, np.int8)
    g1, g2, g3, prev = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    lam, qlen = np.zeros(n), np.zeros(n, int)
    quarantined, blocked = np.zeros(n, bool), np.zeros(n, bool)
    readmits = []
    for i in range(t):
        act = state == 0
        admitted[:, i] = act
        granted[:, i] = act & ~flag[:, i]
        q = state == 1
        lam[q] += Lm[q, i]
        qlen[q] += 1
        ok = q & (lam <= SPRT_B)
        bad = q & ~ok & ((lam >= SPRT_A) | (qlen >= Q_MAX))
        state[ok], g1[ok], g2[ok], g3[ok] = 0, 0.0, 0.0, 0.0
        state[bad] = 2
        blocked |= bad
        readmits += [(int(dv), i) for dv in np.flatnonzero(ok)]
        r = (U[:, i] - phi * prev) / np.sqrt(1 - phi ** 2)
        prev = U[:, i]
        g1[act] = np.maximum(0.0, g1[act] + L[act, i])
        g2[act] = np.maximum(0.0, g2[act] + Lm[act, i])
        g3[act] = np.maximum(0.0, g3[act] + r[act] - K_RES)
        alarm = act & ((g1 > h[0]) | (g2 > h[1]) | (g3 > h[2]))
        state[alarm], lam[alarm], qlen[alarm] = 1, 0.0, 0
        quarantined |= alarm
    return granted, admitted, readmits, quarantined, blocked


def run(ds: str, seed: int) -> dict:
    t0 = time.perf_counter()
    z = np.load(ROOT / "data" / "scores" / f"{ds}_s{seed}.npz", allow_pickle=True)
    s_val, s_te, y_val, y_te, t_val, t_te = (z[k] for k in ("s_val", "s_te", "y_val", "y_te", "t_val", "t_te"))
    llr = Evidence(s_val, y_val, t_val)
    ben = np.flatnonzero(y_te == 0)
    cal_rows = np.random.default_rng([seed, 12]).permutation(ben)[: len(ben) // 2]
    eval_rows = np.setdiff1d(np.arange(len(y_te)), cal_rows)
    pool = s_te[cal_rows]
    ps = np.sort(pool)
    res = {"dataset": ds, "seed": seed, "thresholds": {}, "scenarios": {}}
    for name, kw in SCEN.items():
        Sc = cal_traces(seed, code_of(kw), pool, N_CAL, T_EV, **kw)      # the recording Calib also uses
        cb = Calib(llr, pool, seed, code_of(kw), N_CAL, T_EV, kw, BOOTS)
        Uc = normal_scores(Sc, ps)
        a, b = Uc[:, :-1].ravel(), Uc[:, 1:].ravel()
        phi_hat = float(np.clip(np.corrcoef(a, b)[0, 1], 0.0, 0.995))
        c_k = int(np.ceil(np.quantile(extremes("kofw", Sc), 1 - BUDGET) + 1e-9))
        c_k = max(c_k, 1)
        while (extremes("kofw", Sc) >= c_k).mean() > BUDGET:
            c_k += 1
        th_e = float(np.quantile(extremes("ewma", Sc), BUDGET))
        th_r = float(np.quantile(extremes("res", Uc, phi_hat), 1 - BUDGET))
        hu = union_thresholds(llr, pool, seed, code_of(kw), kw, phi_hat, ps)
        res["thresholds"][name] = {"kofw_c": c_k, "ewma_theta": th_e, "res_h": th_r, "phi_hat": phi_hat,
                                   "guard": [cb.g_a, cb.g_b], "union": hu}
        for rho in RHOS:
            S, A, tau, tgt = streams(np.random.default_rng([seed, int(rho * 100), 5]), s_te, y_te, t_te, rho,
                                     rows=eval_rows, **kw)
            L = llr(S)
            Lm = mix_llr(L)
            out = {"kofw": metrics(S, A, tau, tgt, Rule("kofw", c_k).run(S, Lm, S)),
                   "ewma": metrics(S, A, tau, tgt, Rule("ewma", th_e).run(S, Lm, S)),
                   "residual_cusum": metrics(S, A, tau, tgt, Rule("res", th_r, phi=phi_hat).run(normal_scores(S, ps), Lm, S)),
                   "bound": metrics(S, A, tau, tgt, authorize(S, L, h_bound(T_EV), Lq=Lm)),
                   "ours": metrics(S, A, tau, tgt, authorize(S, L, cb.g_a, Lm, cb.g_b, Lq=Lm)),
                   "ours_residual": metrics(S, A, tau, tgt, union_run(S, L, Lm, normal_scores(S, ps), hu, phi_hat))}
            res["scenarios"][f"{name}/rho{rho:g}"] = out
    res["config"] = {"W": W, "lam": LAM, "k_res": K_RES, "wall_seconds": time.perf_counter() - t0}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", default="edgeiiot,forge,wustl")
    ap.add_argument("--seeds", default="43,44,45,46,47,48,49,50,51")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for seed in map(int, args.seeds.split(",")):
        for ds in args.datasets.split(","):
            out = OUT / f"{ds}_s{seed}.json"
            if out.exists():
                continue
            r = run(ds, seed)
            out.write_text(json.dumps(r, indent=1))
            v = r["scenarios"]["ar0.9/rho0.2"]
            print(f"[{ds}/s{seed}] ar0.9 rho0.2 FI/det: " + " ".join(
                f"{k}={100 * m['false_isolation_rate']:.1f}/{100 * m['detection_rate']:.0f}" for k, m in v.items())
                  + f" | th={r['thresholds']['ar0.9']} ({r['config']['wall_seconds']:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
