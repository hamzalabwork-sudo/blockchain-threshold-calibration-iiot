# Governance (G1) and ledger (L1) summary, held-out seeds 44-51

Re-derivation identical and commitment sensitive to one row in all 24 runs: True

## Threshold manipulation and contaminated recording (mean over seeds)

| dataset | traffic | rho | k=0.25 FI/det | k=0.5 | k=1 | k=2 | k=4 | contaminated FI/det |
|---|---|---|---|---|---|---|---|---|
| Edge | iid | 0.2 | 88.7 / 100 | 21.3 / 100 | 0.4 / 100 | 0.0 / 100 | 0.0 / 100 | 0.0 / 7 |
| Edge | iid | 0.05 | 88.7 / 100 | 21.8 / 100 | 0.4 / 98 | 0.0 / 87 | 0.0 / 68 | 0.0 / 0 |
| Edge | ar0.9 | 0.2 | 21.0 / 100 | 6.5 / 100 | 0.8 / 100 | 0.0 / 99 | 0.0 / 80 | 0.5 / 2 |
| Edge | ar0.9 | 0.05 | 21.6 / 95 | 6.8 / 82 | 1.0 / 56 | 0.1 / 16 | 0.0 / 0 | 0.8 / 0 |
| Forge | iid | 0.2 | 88.3 / 100 | 32.0 / 100 | 0.2 / 99 | 0.0 / 97 | 0.0 / 95 | 0.0 / 8 |
| Forge | iid | 0.05 | 88.2 / 100 | 32.1 / 97 | 0.1 / 87 | 0.0 / 77 | 0.0 / 62 | 0.0 / 0 |
| Forge | ar0.9 | 0.2 | 19.5 / 99 | 5.9 / 97 | 0.8 / 95 | 0.0 / 90 | 0.0 / 78 | 0.5 / 1 |
| Forge | ar0.9 | 0.05 | 19.9 / 88 | 6.2 / 75 | 0.8 / 51 | 0.1 / 15 | 0.0 / 0 | 0.6 / 0 |
| WUSTL | iid | 0.2 | 31.8 / 100 | 1.5 / 100 | 0.1 / 100 | 0.0 / 100 | 0.0 / 100 | 0.0 / 7 |
| WUSTL | iid | 0.05 | 31.9 / 100 | 1.0 / 100 | 0.0 / 100 | 0.0 / 97 | 0.0 / 83 | 0.0 / 0 |
| WUSTL | ar0.9 | 0.2 | 8.9 / 100 | 3.5 / 100 | 1.0 / 100 | 0.3 / 100 | 0.0 / 100 | 0.1 / 6 |
| WUSTL | ar0.9 | 0.05 | 8.9 / 100 | 3.9 / 100 | 1.4 / 99 | 0.3 / 94 | 0.0 / 72 | 0.1 / 0 |

## Dependence monitor: share of runs that request recalibration (%), rows live phi, columns calibrated phi

**Edge, rho 0.2**

| live \ cal | 0 | 0.5 | 0.9 | 0.99 |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 0.5 | 100 | 0 | 0 | 0 |
| 0.9 | 100 | 100 | 0 | 0 |
| 0.99 | 100 | 100 | 0 | 0 |

**Edge, rho 1**

| live \ cal | 0 | 0.5 | 0.9 | 0.99 |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 0.5 | 100 | 0 | 0 | 0 |
| 0.9 | 100 | 100 | 0 | 0 |
| 0.99 | 100 | 100 | 0 | 0 |

**Forge, rho 0.2**

| live \ cal | 0 | 0.5 | 0.9 | 0.99 |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 0.5 | 100 | 0 | 0 | 0 |
| 0.9 | 100 | 100 | 0 | 0 |
| 0.99 | 100 | 100 | 0 | 0 |

**Forge, rho 1**

| live \ cal | 0 | 0.5 | 0.9 | 0.99 |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 0.5 | 100 | 0 | 0 | 0 |
| 0.9 | 100 | 100 | 0 | 0 |
| 0.99 | 100 | 100 | 0 | 0 |

**WUSTL, rho 0.2**

| live \ cal | 0 | 0.5 | 0.9 | 0.99 |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 0.5 | 100 | 0 | 0 | 0 |
| 0.9 | 100 | 100 | 0 | 0 |
| 0.99 | 100 | 100 | 0 | 0 |

**WUSTL, rho 1**

| live \ cal | 0 | 0.5 | 0.9 | 0.99 |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |
| 0.5 | 100 | 0 | 0 | 0 |
| 0.9 | 100 | 100 | 0 | 0 |
| 0.99 | 100 | 100 | 0 | 0 |

## Ledger (L1)

| network | client | deploy gas | op | gas | latency median (s) | p95 (s) |
|---|---|---|---|---|---|---|
| anvil | anvil/v1.8.4 | 1262414 | publishModel | 33826 | 1.98 | 2.01 |
| anvil | anvil/v1.8.4 | 1262414 | propose | 169566 | 2.00 | 2.04 |
| anvil | anvil/v1.8.4 | 1262414 | approve | 67557 | 1.99 | 2.04 |
| anvil | anvil/v1.8.4 | 1262414 | requestRecalibration | 33248 | 1.98 | 2.01 |
| anvil | | | view thresholds() | 0 | 0.023 | |
| anvil | | | violations rejected | 11/11 | | |
| anvil | | | tests | outsider_proposes: operator; below_floor_h1: below floor; below_floor_h2: below floor; stale_model_proposal: stale model; insider_self_approval: two-person rule; outsider_approves: auditor; auditor_rederivation: {'honest_matches': True, 'inflated_x2_refused': True, 'rederive_seconds': 3.2622109000803903}; valid_after_honest_approval: {'valid': True}; outsider_requests_recal: gateway; recal_within_bound: within bound; valid_after_new_model: {'valid': False}; approve_pending_after_new_model: stale model; outsider_publishes_model: owner; outsider_grants_roles: owner | | |
| clique | Geth/v1.13.15-stable-c5ba367e/linux-amd64/go1.21.9 | 1262044 | publishModel | 33826 | 3.98 | 4.03 |
| clique | Geth/v1.13.15-stable-c5ba367e/linux-amd64/go1.21.9 | 1262044 | propose | 169566 | 4.00 | 4.02 |
| clique | Geth/v1.13.15-stable-c5ba367e/linux-amd64/go1.21.9 | 1262044 | approve | 67557 | 4.00 | 4.03 |
| clique | Geth/v1.13.15-stable-c5ba367e/linux-amd64/go1.21.9 | 1262044 | requestRecalibration | 33248 | 3.97 | 4.01 |
| clique | | | view thresholds() | 0 | 0.020 | |
| clique | | | violations rejected | 11/11 | | |
| clique | | | tests | outsider_proposes: operator; below_floor_h1: below floor; below_floor_h2: below floor; stale_model_proposal: stale model; insider_self_approval: two-person rule; outsider_approves: auditor; auditor_rederivation: {'honest_matches': True, 'inflated_x2_refused': True, 'rederive_seconds': 3.2637822999386117}; valid_after_honest_approval: {'valid': True}; outsider_requests_recal: gateway; recal_within_bound: within bound; valid_after_new_model: {'valid': False}; approve_pending_after_new_model: stale model; outsider_publishes_model: owner; outsider_grants_roles: owner | | |