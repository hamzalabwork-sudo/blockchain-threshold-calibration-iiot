# Experiment log

## F1: site-calibrated thresholds under correlated benign traffic (2026-11-07)

**Question.** The deployed gateway threshold h = log(T/beta) is a Ville / union bound. It needs
conditionally independent benign events. Can a threshold calibrated on the site's own benign traces
restore the 1% false-isolation budget without attack data, and at what detection cost?

**Setup.**
- Detector scores: clean FedAvg MLP from the IoTJ work (E14 cache), 3 datasets, seeds 43-51.
- Streams: 1,000 devices x 500 events, 20% compromised; attack rate rho in {1, 0.5, 0.2, 0.1, 0.05}.
- Benign traffic models: i.i.d., AR(1) rank copula (phi 0.5/0.9/0.99), heterogeneity sigma 0.5,
  and rows unseen in training.
- Long horizon: 200 devices x 10^4 events.
- Calibration (fresh): the test benign rows are split into disjoint halves. The calibration half
  gives 2,000 traces; the evaluation half plus attack rows gives the streams.
- Seed 43 is the design seed; seeds 44-51 are held out.

**Policies.**
- bound and bound+mixture: the deployed thresholds, which reproduce E14 exactly (8,640 values,
  0 mismatches).
- cal: calibrated CUSUM only.
- cal_mix: calibrated CUSUM and mixture CUSUM at a joint quantile.
- boot / floor: each guard alone.
- guard: bootstrap 90th percentile over 20 row resamples, plus the single-event floor (8 for the
  CUSUM, 5.70 for the mixture).
- temper and temper_mix: evidence divided by the batch-means variance inflation, with the bound kept.

**Findings (held-out seeds 44-51).**
- The bound fails at phi=0.9. False isolation is 22-28% on Edge and Forge at T=500, and 94-99% at
  T=10^4. On i.i.d. traffic it is at most 0.1%.
- Calibrating the CUSUM alone restores the budget under dependence. Detection collapses (3-4% at
  rho=0.2, phi=0.9), because its threshold of about 40 sits above a CUSUM with negative drift. The
  mixture CUSUM restores 96-100%.
- Plain calibration is fragile on i.i.d. traffic: 1.3-3.5% mean, 21% worst seed.
  - The bootstrap fixes Edge and Forge: the tail rows decide the threshold.
  - The floor fixes WUSTL: calibrated h is about 2, below the largest single-event increment of 8.
- The guarded threshold keeps mean false isolation within 1% in 86 of 90 settings. The largest mean
  is 1.4%; the worst seed is 4.2% (WUSTL, phi=0.9). The bound meets 1% in 50 of 90 settings, with a
  largest mean of 27.8% and a worst seed of 34.9%.
- Cost of the guard:
  - Time to isolation at phi=0.9, rho=0.2 roughly doubles (24 to 46 events).
  - At phi=0.9, rho=0.05, detection is 51-56% on Edge and Forge.
  - At phi=0.99, rho=0.05, detection is near 0 on Edge and Forge (84% on WUSTL).
- Gain of the guard on i.i.d. traffic: detection at rho=0.05 rises from 38-44% to 87-100%.
- Misspecification:
  - Calibrating for i.i.d. traffic and running at phi=0.9 gives 27-36% false isolation.
  - Calibrating for phi=0.99 and running on i.i.d. traffic costs about 24% of detections at rho=0.2.
- Long horizon, guarded threshold:
  - Edge and Forge at phi=0.9: 0.8-0.9% mean.
  - WUSTL at phi=0.9: 4.2% mean (26% worst seed).
  - i.i.d. traffic: worst seed 8.8-10%.
- Tempering keeps the budget but detects 0% at rho=0.2 on phi=0.9 traffic.
- Calibrating on the validation rows that fitted the evidence (in-sample) gives up to 6.2% mean on
  WUSTL (26% worst seed); the guarded threshold gives at most 1.8%.
- Calibration takes about 3 s per site on a laptop CPU.

**Files.**
- Code: `code/fix_experiment.py` and `code/summarize.py`.
- Results: `results/fix_fresh/` and `results/fix_val/`, summarized in `results/summary.md`.
- `results/fix_fresh_v1/` is the first run without the boot and floor ablations. It is identical on
  all shared policies.

## G1 / L1: ledger governance of the thresholds (2026-11-07)

**Why.** A calibrated threshold is a site-specific security parameter that an insider could move;
the ledger governs it.

**The contract.** `contracts/ThresholdRegistry.sol` enforces five rules:
- R1 model binding: a new model invalidates every calibration at once.
- R2 on-chain floor: h >= 8 and h2 >= 5.70.
- R3 two-person rule: operator proposes, a different auditor approves.
- R4 committed recording: SHA-256 of the rows and seed, re-derived by the auditor before approval.
- R5 recalibration requests: only above the committed dependence bound.

**G1 (simulation, held-out seeds 44-51, fresh split; `results/governance_summary.md`).**
- Re-derivation is identical in 24 of 24 runs. Changing one recorded row changes the commitment.
- Manipulation, with thresholds scaled by k:
  - On independent traffic at rho=0.2, false isolation is 88.7/88.3/31.8% at k=0.25 and
    21.3/32.0/1.5% at k=0.5 (Edge/Forge/WUSTL).
  - Detection at phi=0.9, rho=0.05 falls from 56/51/99% at k=1 to 16/15/94% at k=2 and 0/0/72% at
    k=4.
- The floor (R2) blocks these reductions on independent traffic, where the guarded thresholds sit
  just above the floor. On correlated Edge and Forge traffic (thresholds near 50) even k=0.25 clears
  the floor, so only re-derivation (R4) exposes it.
- Contaminated recording (5% of traces attacking at rho=0.2): detection is 1-8% at rho=0.2 and 0% at
  rho=0.05. The ledger only makes this forensically reviewable.
- Dependence monitor (D = median lag-1 correlation of normal scores over 100 events,
  delta = 0.1 fixed in advance):
  - It flags 100% of runs in 5 of the 6 under-calibrated cells and 0% in the matched or
    over-calibrated cells, on all three datasets at rho 0.2 and 1.
  - It misses phi_cal 0.9 to live 0.99: D rises only 0.05-0.07, and false isolation reaches 5-6%.

**L1 (on-chain, `results/chain/`).**
- Networks: anvil 1.8.4 with 2 s blocks, and geth 1.13.15 Clique with 4 signers and a 1 s period.
- 20 cycles per network. Gas, identical on both networks:
  - deploy 1,262,414
  - publishModel 33,826
  - propose 169,566
  - approve 67,557
  - requestRecalibration 33,248
- Median latency: about 2.0 s on anvil and 4.0 s on Clique. The thresholds() view takes 20-23 ms.
- 11/11 violations reverted with the intended reason on both networks.
- A new model invalidated the thresholds. The auditor re-derivation (3.3 s) matched the honest
  proposal and refused a doubled one.
- A calibration costs about 237k gas in two transactions.

**Pitfalls hit.**
1. solc 0.8.24 defaults to the cancun EVM, and its PUSH0 opcode makes deployment fail silently on
   geth Clique. The fix is `evm_version=paris`, as for PureChain.
2. eth-account can write a 15-byte keystore IV, and geth then panics on unlock. The fix is to
   re-encrypt until the IV is 16 bytes.

## C1: comparison with established isolation rules (2026-11-07)

**Setup.**
- Calibration and budget: every rule is calibrated on the same recording (fresh split) to the same
  1% budget.
- Gateway: every rule runs in the same gateway with the same quarantine SPRT.
- Traffic: i.i.d., AR(1) with phi 0.5/0.9/0.99, and periodic polling (new). In periodic polling each
  device repeats its own cycle of 5-15 benign rows, and 10% of events are random.
- Attack rates rho: 1, 0.2, 0.05.
- Seed 43 is the design seed; seeds 44-51 are held out.
- Script: `code/baselines.py`; summary in `results/baselines_summary.md`.

**Rules compared.**
- k-of-W: c flagged events in the last 20.
- EWMA trust: lam 0.9, isolates below theta.
- Residual CUSUM (Alwan & Roberts; Lu & Reynolds): normal scores, AR(1) fitted on the recording,
  k = 0.5.
- The bound.
- Ours: guarded evidence CUSUM + mixture CUSUM.
- Ours + residual: three CUSUMs at a joint quantile, with the bootstrap on all three and the floor on
  the two evidence CUSUMs. Designed on seed 43, after the residual CUSUM won at strong AR(1) there.

**Results (held-out seeds; mean over 3 datasets x 8 seeds; 15 settings).**

| Rule | Largest mean FI (worst seed) | Mean detection over the 15 settings |
|---|---|---|
| k-of-W | 1.2% (5.9%) | 69% |
| EWMA trust | 3.8% (27.9%, WUSTL seed 48, i.i.d.) | 74% |
| Residual CUSUM | 1.5% (4.6%) | 79% |
| Bound | 17.9% (34.9%) | 79% |
| Ours | 1.04% (4.2%) | 89% |
| Ours + residual | 1.03% (3.9%) | 96% |

- k-of-W and EWMA trust miss slow attackers under dependence: 13-39% detection at phi=0.9.
- The residual CUSUM wins under exact AR(1) (97-100% at rho=0.05) but fails on periodic polling
  (27% at rho=0.2, 2% at rho=0.05) and on i.i.d. traffic at rho=0.05 (57%).
- Ours + residual is at least 93% in every setting except periodic polling at rho=0.05, where it gets
  64% and EWMA gets 86%.
- Time to isolation at phi=0.9, rho=0.2: 33 events for ours, 18 for ours + residual.

**Caveat.** The AR(1) traffic is generated from exactly the model the residual CUSUM assumes, which
favours it. The periodic-polling scenario was added for that reason.
