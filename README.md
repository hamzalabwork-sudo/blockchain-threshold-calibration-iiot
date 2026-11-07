# Blockchain-Governed Threshold Calibration for Zero-Trust IIoT Gateways

Code, smart contract, cached detector scores and per-seed results for the paper
*Blockchain-Governed Threshold Calibration for Zero-Trust IIoT Gateways* (manuscript under review).

## The problem and the answer

A Zero-Trust IIoT gateway can authorize every device continuously by running a CUSUM test on the
evidence of a learned (federated) intrusion detector.

**Why the usual threshold breaks.** The usual threshold, the Ville bound `h = log(T / beta)`, needs no
attack data. It does assume that benign events are conditionally independent. When benign traffic is
autoregressive (phi = 0.9), it isolates 22-28% of benign devices within 500 events instead of 1%.

**The method.** It has three parts:

- **Guarded site calibration.** Three statistics are calibrated jointly, at the budget quantile of
  their maxima, on benign traces recorded at the site:
  - an evidence CUSUM;
  - a rho-mixture CUSUM (for low-rate attackers);
  - a residual CUSUM (for autoregressive dependence).

  Two guards protect the estimate: the 90th percentile over 20 row-bootstrap resamples, and a floor
  at the largest single-event increment.
- **Blockchain governance.** The `ThresholdRegistry` smart contract enforces five rules at write time:
  - it binds every calibration to the deployed model;
  - it enforces the floor;
  - it enforces a two-person rule (operator proposes, auditor approves);
  - it stores a commitment to the recording, which the auditor re-derives;
  - it records recalibration requests from a dependence monitor at the gateway.
- **Evaluation.** Three public IIoT datasets (Edge-IIoTset, IoTForge Pro, WUSTL-IIoT-2021), nine
  seeds, and five benign traffic models: i.i.d., AR(1) with phi 0.5/0.9/0.99, and periodic polling.
  - Seed 43 is the design seed; seeds 44-51 are held out.
  - Calibration and evaluation use disjoint halves of the benign test rows.

## Headline results (held-out seeds 44-51)

| Rule (calibrated on the same recording, 1% budget) | Largest mean false isolation (worst seed) | Mean detection over 15 settings |
|---|---|---|
| k-of-W count rule | 1.2% (5.9%) | 69% |
| EWMA trust score | 3.8% (27.9%) | 74% |
| Residual CUSUM | 1.5% (4.6%) | 79% |
| Ville bound (not calibrated) | 17.9% (34.9%) | 79% |
| Guarded evidence CUSUMs | 1.04% (4.2%) | 89% |
| **Guarded evidence + residual CUSUMs** | **1.03% (3.9%)** | **96%** |

**On-chain results.** These come from anvil (2 s blocks) and from a four-signer geth 1.13.15 Clique
network with a 1 s period:

| Operation | Gas |
|---|---|
| propose | 169,566 |
| approve | 67,557 |
| publishModel | 33,826 |
| requestRecalibration | 33,248 |

- Median confirmation is 2.0 s on anvil and 4.0 s on Clique.
- All 11 attempted violations reverted, on both networks.

The full logs are `results/summary.md`, `results/baselines_summary.md` and
`results/governance_summary.md`, and [EXPERIMENTS.md](EXPERIMENTS.md).

## Layout

| Path | Contents |
|---|---|
| `code/gwcore.py` | Gateway core: evidence (monotone, type-balanced LLR), per-device CUSUM and quarantine SPRT, stream generators (i.i.d., AR(1) rank copula, heterogeneity, periodic polling), metrics |
| `code/fix_experiment.py` | F1: bound vs calibrated vs guarded vs tempered thresholds; misspecification; long horizon |
| `code/baselines.py` | C1: k-of-W, EWMA trust, residual CUSUM, bound, ours, ours + residual |
| `code/governance_sim.py` | G1: threshold manipulation, contaminated recording, auditor re-derivation, dependence monitor |
| `code/chain_experiment.py` | L1: `ThresholdRegistry` on anvil and a four-signer Clique network; gas, latency, 11 violation tests |
| `code/check_reproduces_e14.py` | Checks that `gwcore` reproduces the companion work's gateway stress test exactly |
| `code/explore_threshold_floor.py` | The design-seed (43) exploration that chose the guards |
| `code/summarize*.py`, `code/make_figures.py` | Tables and the figure |
| `contracts/ThresholdRegistry.sol` | The smart contract (Solidity 0.8.24, compiled for the paris EVM); `ThresholdRegistry.json` holds the ABI and bytecode |
| `data/scores/` | Cached validation and test scores of the clean federated MLP detector (FedAvg, 10 clients, 30 rounds), seeds 43-51 |
| `data/*.json` | The companion work's gateway stress results, used by the reproduction check |
| `results/` | Per-seed JSON for every experiment, plus the summaries |

## Reproduce

Requires Python 3.13 and `pip install -r requirements.txt`. The chain experiment also needs Docker
(images `ghcr.io/foundry-rs/foundry:v1.8.4` and `ethereum/client-go:v1.13.15`).

```
python code/fix_experiment.py --cal-source fresh
python code/fix_experiment.py --cal-source val
python code/check_reproduces_e14.py
python code/baselines.py
python code/governance_sim.py
python code/chain_experiment.py
python code/summarize.py
python code/summarize_baselines.py
python code/summarize_governance.py
python code/make_figures.py
```

`chain_experiment.py` creates and removes only Docker containers named `ztfl-p2-*` and the network
`ztfl-p2-clique-net`. It uses throwaway accounts created in memory. Clique node keys are written to
`~/.ztfl/p2_clique_net`, outside the repository.

## Related repository

The federated detector, the data cleaning and the original gateway come from
[ztfl-zero-trust-fl-iiot](https://github.com/hamzalabwork-sudo/ztfl-zero-trust-fl-iiot).

## License

MIT. See [LICENSE](LICENSE).
