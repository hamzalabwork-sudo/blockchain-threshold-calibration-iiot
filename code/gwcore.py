"""Self-contained gateway core for paper 2 (copied from ztfl/src/closed_loop.py and gateway_stress.py).

Per-device authorization of a learned detector's scores: per-event deny (s >= 0.5), a CUSUM on the
binned log-likelihood ratio (LLR) of the score, and a quarantine SPRT against a low-rate attacker.
The functions below are the deployed ones; `authorize` is generalized so the CUSUM evidence, the
threshold and the optional rho-mixture CUSUM can be set separately (for the fixes in fix_experiment.py).
"""
from __future__ import annotations

import numpy as np
from scipy.stats import norm
from sklearn.isotonic import IsotonicRegression

N_DEV, T_EV, COMPROMISED, TAU_RANGE = 1000, 500, 0.2, (100, 300)
BUDGET = 0.01                           # benign false-isolation budget
SPRT_ALPHA = SPRT_BETA = 0.01
SPRT_A, SPRT_B = np.log((1 - SPRT_BETA) / SPRT_ALPHA), np.log(SPRT_BETA / (1 - SPRT_ALPHA))
Q_MAX = 100
RHO_MIN = 0.1
BINS = np.linspace(-16, 16, 65)
LLR_CLIP = 8.0


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p.astype(np.float64), 1e-7, 1 - 1e-7)
    return np.log(p) - np.log1p(-p)


class Evidence:
    """Monotone, type-balanced binned LLR of the detector score, fitted on the validation split."""

    def __init__(self, s_val: np.ndarray, y_val: np.ndarray, types_val: np.ndarray):
        z = np.clip(logit(s_val), BINS[0], BINS[-1])
        n0, n1 = np.histogram(z[y_val == 0], BINS)[0], np.histogram(z[y_val == 1], BINS)[0]
        f0 = n0 + 0.5
        at = np.unique(types_val[y_val == 1])
        f1 = np.mean([np.histogram(z[types_val == t], BINS)[0] / (types_val == t).sum() for t in at], axis=0)
        f1 = f1 + 0.5 / n1.sum()
        table = np.log(f1 / f1.sum()) - np.log(f0 / f0.sum())
        table = IsotonicRegression().fit_transform(np.arange(len(table)), table, sample_weight=n0 + n1 + 1e-3)
        self.table = np.clip(table, -LLR_CLIP, LLR_CLIP)

    def __call__(self, s: np.ndarray) -> np.ndarray:
        return self.table[np.clip(np.digitize(logit(s), BINS) - 1, 0, len(self.table) - 1)]


def h_bound(t: int, k: int = 1) -> float:
    """Horizon threshold from Ville's inequality and a union bound over t events (and k statistics)."""
    return float(np.log(k * t / BUDGET))


def benign_rows(rng, s_ben: np.ndarray, n: int, t: int, phi: float = 0.0, sigma: float = 0.0,
                period: int = 0, eps: float = 0.1) -> np.ndarray:
    """Benign row indices for n devices x t events: i.i.d., or a Gaussian-copula AR(1) on the score
    rank (phi), or a per-device rank offset (sigma), or periodic polling (period > 0): each device
    repeats its own cycle of rows, of a length drawn uniformly from [period/2, 3 period/2], and each
    event is replaced by a random row with probability eps. The marginal of every event stays f0."""
    if period:
        lens = rng.integers(period // 2, 3 * period // 2 + 1, n)
        cyc = rng.integers(0, len(s_ben), (n, int(lens.max())))
        idx = cyc[np.arange(n)[:, None], np.arange(t)[None, :] % lens[:, None]]
        jit = rng.random((n, t)) < eps
        idx[jit] = rng.integers(0, len(s_ben), int(jit.sum()))
        return idx
    if phi == 0 and sigma == 0:
        return rng.integers(0, len(s_ben), (n, t))
    order = np.argsort(s_ben, kind="stable")
    r = np.empty((n, t))
    r[:, 0] = rng.standard_normal(n)
    e = rng.standard_normal((n, t))
    for i in range(1, t):
        r[:, i] = phi * r[:, i - 1] + np.sqrt(1 - phi ** 2) * e[:, i]
    if sigma:
        r = (r + rng.normal(0, sigma, (n, 1))) / np.sqrt(1 + sigma ** 2)
    u = np.clip(norm.cdf(r), 0, 1 - 1e-12)
    return order[(u * len(s_ben)).astype(int)]


def streams(rng, s, y, types, rho, n=N_DEV, t=T_EV, phi=0.0, sigma=0.0, rows=None, period=0):
    """Device streams from a score pool: 20% compromised at tau, then a share rho of attack events."""
    rows = np.arange(len(y)) if rows is None else rows
    ben = rows[y[rows] == 0]
    S = s[ben][benign_rows(rng, s[ben], n, t, phi, sigma, period)]
    A = np.zeros((n, t), dtype=bool)
    tau = np.full(n, t)
    att_types = np.unique(types[rows][y[rows] == 1])
    for dev in rng.permutation(n)[: int(round(COMPROMISED * n))]:
        tau[dev] = rng.integers(*TAU_RANGE) if t == T_EV else rng.integers(t // 5, 3 * t // 5)
        pool = rows[types[rows] == rng.choice(att_types)]
        hit = (np.arange(t) >= tau[dev]) & (rng.random(t) < rho)
        A[dev, hit] = True
        S[dev, hit] = s[rng.choice(pool, hit.sum())]
    target = (np.arange(n)[:, None] + rng.integers(1, n, (n, t))) % n
    return S, A, tau, target


def mix_llr(L: np.ndarray, rho: float = RHO_MIN) -> np.ndarray:
    return np.log(rho * np.exp(L) + 1 - rho)


def cusum_max(L: np.ndarray) -> np.ndarray:
    """Per-stream maximum of the CUSUM with no isolation (threshold calibration)."""
    c, high = np.zeros(len(L)), np.zeros(len(L))
    for i in range(L.shape[1]):
        c = np.maximum(0.0, c + L[:, i])
        np.maximum(high, c, out=high)
    return high


def authorize(S, L, h, L2=None, h2=None, Lq=None):
    """The deployed gateway. L: CUSUM evidence, h: its threshold; L2/h2: an optional second CUSUM in
    parallel (the rho-mixture); Lq: quarantine SPRT evidence (default: the mixture of the raw LLR,
    which the caller passes). Returns granted, admitted, re-admissions and benign counters."""
    n, t = S.shape
    flag = S >= 0.5
    granted, admitted = np.zeros((n, t), bool), np.zeros((n, t), bool)
    state = np.zeros(n, np.int8)
    g, g2, lam, qlen = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n, int)
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
        state[ok], g[ok], g2[ok] = 0, 0.0, 0.0
        state[bad] = 2
        blocked |= bad
        readmits += [(int(dv), i) for dv in np.flatnonzero(ok)]
        g[act] = np.maximum(0.0, g[act] + L[act, i])
        alarm = act & (g > h)
        if L2 is not None:
            g2[act] = np.maximum(0.0, g2[act] + L2[act, i])
            alarm |= act & (g2 > h2)
        state[alarm], lam[alarm], qlen[alarm] = 1, 0.0, 0
        quarantined |= alarm
    return granted, admitted, readmits, quarantined, blocked


def metrics(S, A, tau, target, out) -> dict:
    granted, admitted, readmits, quarantined, blocked = out
    n, t = A.shape
    comp = tau < t
    idx = np.arange(t)
    out_after = ~admitted & (idx[None, :] >= tau[:, None])
    detected = out_after.any(axis=1) & comp
    tti = np.where(detected, out_after.argmax(axis=1) - tau, -1)
    false_reauth = {dv for dv, i in readmits if comp[dv] and i >= tau[dv]}
    return {
        "false_isolation_rate": float((~admitted[~comp]).any(axis=1).mean()),
        "benign_ever_blocked": float(blocked[~comp].mean()),
        "benign_denial_rate": float(1 - granted[~comp].mean()),
        "detection_rate": float(detected[comp].mean()),
        "tti_median": float(np.median(tti[detected])) if detected.any() else None,
        "tti_p90": float(np.percentile(tti[detected], 90)) if detected.any() else None,
        "wrongful_grant_rate": float(granted[A].mean()) if A.any() else 0.0,
        "false_reauth_rate": len(false_reauth) / int(detected.sum()) if detected.any() else None,
        "attack_events_granted_per_10k": float(1e4 * (granted & A).sum() / max(1, comp.sum() * t)),
    }
