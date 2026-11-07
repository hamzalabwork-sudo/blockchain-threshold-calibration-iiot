"""Paper 2, experiment L1: the ThresholdRegistry on two permissioned ledgers.

Networks (Docker; only containers named ztfl-p2-* are created and removed, nothing else is touched):
- anvil: a local EVM node with 2 s blocks (as the IoTJ testbed);
- clique: a four-signer geth 1.13.15 Clique network with a 1 s period, a replica of the live
  PureChain configuration. Node keys live in ~/.ztfl/p2_clique_net and are never committed.
All transaction keys are throwaway accounts created in memory; gas price is zero on both networks.

Per network:
1. costs: deployment and role set-up gas; then R governance cycles (publishModel, propose,
   approve, requestRecalibration), each transaction timed from submission to its receipt, and the
   gateway's view call thresholds() timed;
2. security tests: each attempted violation is sent on chain and must be rejected (receipt status
   0; the revert reason is read with eth_call), or must leave the gateway without valid thresholds;
3. auditor re-derivation: the operator proposes the guarded thresholds of a real calibration
   (Edge-IIoTset, seed 44, AR(1) phi=0.9, fresh split) with the hash of the recording; the auditor
   recomputes them from the recording before approving. An inflated proposal (x2) is refused.

Outputs: results/chain/<network>.json
Usage: py -3.13 code/chain_experiment.py [--networks anvil,clique] [--cycles 20]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
import requests
from eth_account import Account
from eth_keys import keys as eth_keys
from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.middleware import ExtraDataToPOAMiddleware

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "contracts" / "ThresholdRegistry.json"
OUT = ROOT / "results" / "chain"
SCALE = 10_000
FLOOR = (80_000, 57_000)                     # 8.0 and 5.70, x 1e4
FOUNDRY, GETH = "ghcr.io/foundry-rs/foundry:v1.8.4", "ethereum/client-go:v1.13.15"
ANVIL_PORT, ANVIL_CHAIN = 18660, 31337
CLIQUE_PORTS, CLIQUE_CHAIN = [18661, 18662, 18663, 18664], 900522
NET, SUBNET = "ztfl-p2-clique-net", "172.29.60"
WORK = Path.home() / ".ztfl" / "p2_clique_net"


def sh(*cmd, check=True) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(f"{cmd}: {r.stderr[-800:]}")
    return r.stdout


def rpc(port: int, method: str, params=None):
    r = requests.post(f"http://127.0.0.1:{port}", json={"jsonrpc": "2.0", "id": 1, "method": method,
                                                         "params": params or []}, timeout=30).json()
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["result"]


def wait_rpc(port: int, tries: int = 90) -> None:
    for _ in range(tries):
        try:
            rpc(port, "eth_blockNumber")
            return
        except Exception:
            time.sleep(1)
    raise TimeoutError(port)


def teardown() -> None:
    for name in ["ztfl-p2-anvil"] + [f"ztfl-p2-clique-{i}" for i in range(1, 5)]:
        sh("docker", "rm", "-f", name, check=False)
    sh("docker", "network", "rm", NET, check=False)


def start_anvil() -> int:
    sh("docker", "run", "-d", "--name", "ztfl-p2-anvil", "-p", f"127.0.0.1:{ANVIL_PORT}:8545", "--entrypoint", "anvil",
       FOUNDRY,
       "--host", "0.0.0.0", "--chain-id", str(ANVIL_CHAIN), "--block-time", "2", "--gas-price", "0",
       "--base-fee", "0", "--gas-limit", "30000000")
    wait_rpc(ANVIL_PORT)
    return ANVIL_PORT


def start_clique() -> int:
    """Four geth Clique signers, 1 s period, zero gas price (as stage4/clique_load.py of the IoTJ work)."""
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    signers, nodekeys = [Account.create() for _ in range(4)], [Account.create() for _ in range(4)]
    extra = "0x" + "00" * 32 + "".join(s.address[2:].lower() for s in signers) + "00" * 65
    genesis = {"config": {"chainId": CLIQUE_CHAIN, "homesteadBlock": 0, "eip150Block": 0, "eip155Block": 0,
                          "eip158Block": 0, "byzantiumBlock": 0, "constantinopleBlock": 0, "petersburgBlock": 0,
                          "istanbulBlock": 0, "berlinBlock": 0, "londonBlock": 0, "clique": {"period": 1, "epoch": 30000}},
               "difficulty": "0x1", "gasLimit": "0x1c9c380", "baseFeePerGas": "0x0", "extradata": extra, "alloc": {}}
    enodes = []
    for i, (s, nk) in enumerate(zip(signers, nodekeys), start=1):
        d = WORK / f"n{i}"
        (d / "keystore").mkdir(parents=True)
        ks = Account.encrypt(s.key, "pw")
        while len(ks["crypto"]["cipherparams"]["iv"]) != 32:    # eth-account can drop a leading zero byte of
            ks = Account.encrypt(s.key, "pw")                    # the IV; geth then panics on unlock
        (d / "keystore" / f"key{i}.json").write_text(json.dumps(ks))
        (d / "pw.txt").write_text("pw")
        (d / "nodekey").write_text(nk.key.hex().removeprefix("0x"))
        (d / "genesis.json").write_text(json.dumps(genesis))
        enodes.append(f"enode://{eth_keys.PrivateKey(nk.key).public_key.to_hex()[2:]}@{SUBNET}.{10 + i}:30303")
    sh("docker", "network", "create", "--subnet", f"{SUBNET}.0/24", NET)
    for i, s in enumerate(signers, start=1):
        mount = f"{WORK / f'n{i}'}:/data"
        sh("docker", "run", "--rm", "-v", mount, GETH, "init", "--datadir", "/data", "/data/genesis.json")
        sh("docker", "run", "-d", "--name", f"ztfl-p2-clique-{i}", "--network", NET, "--ip", f"{SUBNET}.{10 + i}",
           "-p", f"127.0.0.1:{CLIQUE_PORTS[i - 1]}:8545", "-v", mount, GETH,
           "--datadir", "/data", "--networkid", str(CLIQUE_CHAIN), "--nodekey", "/data/nodekey", "--nodiscover",
           "--http", "--http.addr", "0.0.0.0", "--http.vhosts", "*", "--http.api", "eth,net,web3,txpool,clique,admin",
           "--mine", "--miner.etherbase", s.address, "--unlock", s.address, "--password", "/data/pw.txt",
           "--allow-insecure-unlock", "--miner.gasprice", "0", "--txpool.pricelimit", "0", "--rpc.txfeecap", "0",
           "--syncmode", "full", "--verbosity", "2")
    for p in CLIQUE_PORTS:
        wait_rpc(p)
    for i, p in enumerate(CLIQUE_PORTS):
        for j, e in enumerate(enodes):
            if i != j:
                rpc(p, "admin_addPeer", [e])
    for _ in range(120):
        try:
            if int(rpc(CLIQUE_PORTS[0], "eth_blockNumber"), 16) > 3 and int(rpc(CLIQUE_PORTS[0], "net_peerCount"), 16) >= 3:
                return CLIQUE_PORTS[0]
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Clique network did not start: " + sh("docker", "ps", "-a", "--filter", "name=ztfl-p2-clique"))


class Chain:
    def __init__(self, port: int):
        self.w3 = Web3(Web3.HTTPProvider(f"http://127.0.0.1:{port}", request_kwargs={"timeout": 120}))
        self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        self.chain_id = self.w3.eth.chain_id
        self.nonce: dict[str, int] = {}

    def send(self, acct, fn=None, data=None, gas=3_000_000) -> tuple[dict, float]:
        a = acct.address
        if a not in self.nonce:
            self.nonce[a] = self.w3.eth.get_transaction_count(a, "pending")
        tx = (fn.build_transaction({"from": a, "gas": gas, "gasPrice": 0, "nonce": self.nonce[a], "chainId": self.chain_id})
              if fn is not None else {"data": data, "gas": gas, "gasPrice": 0, "nonce": self.nonce[a],
                                      "chainId": self.chain_id, "value": 0})
        self.nonce[a] += 1
        t0 = time.perf_counter()
        h = self.w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
        r = self.w3.eth.wait_for_transaction_receipt(h, timeout=300, poll_latency=0.05)
        return r, time.perf_counter() - t0

    def attempt(self, acct, fn) -> dict:
        """Send a transaction that should be rejected: the revert reason (eth_call) and the receipt status."""
        try:
            fn.call({"from": acct.address})
            reason = None
        except ContractLogicError as e:
            reason = (getattr(e, "message", None) or str(e)).split("execution reverted: ")[-1].split("'")[0].strip()
        r, _ = self.send(acct, fn)
        return {"reason": reason, "status": int(r.status), "gas": int(r.gasUsed)}


def proposal_id(C, r, gw, model, h1, h2, dep, bound, recording, params, sender) -> bytes:
    """The proposal id from the CalibrationProposed event, or recomputed as the contract does
    (keccak256(abi.encode(...)) with the proposer and block number) if the client returns no logs."""
    ev = C.events.CalibrationProposed().process_receipt(r)
    if ev:
        return ev[0]["args"]["id"]
    from eth_abi import encode
    print(f"  (no decoded log in receipt; {len(r.logs)} raw logs) recomputing the id", flush=True)
    return Web3.keccak(encode(["uint32", "bytes32", "uint32", "uint32", "uint32", "uint32", "bytes32", "bytes32", "address",
                               "uint256"], [gw, model, h1, h2, dep, bound, recording, params, sender, r.blockNumber]))


def real_calibration() -> dict:
    """Guarded thresholds of Edge-IIoTset seed 44 at AR(1) phi=0.9 (fresh split), and the recording hash."""
    import sys
    sys.path.insert(0, str(ROOT / "code"))
    from fix_experiment import BOOTS, N_CAL, Calib
    from governance_sim import code_of, dep_stat
    from gwcore import T_EV, Evidence
    from fix_experiment import cal_traces
    seed = 44
    z = np.load(ROOT / "data" / "scores" / f"edgeiiot_s{seed}.npz", allow_pickle=True)
    llr = Evidence(z["s_val"], z["y_val"], z["t_val"])
    ben = np.flatnonzero(z["y_te"] == 0)
    rows = np.random.default_rng([seed, 12]).permutation(ben)[: len(ben) // 2]
    pool = z["s_te"][rows]

    def derive(p):
        cb = Calib(llr, p, seed, code_of({"phi": 0.9}), N_CAL, T_EV, {"phi": 0.9}, BOOTS)
        d = dep_stat(cal_traces(seed, code_of({"phi": 0.9}), p, N_CAL, T_EV, phi=0.9), np.sort(p))
        return int(round(cb.g_a * SCALE)), int(round(cb.g_b * SCALE)), int(round(max(d, 0) * SCALE))

    t0 = time.perf_counter()
    h1, h2, dep = derive(pool)
    return {"h1": h1, "h2": h2, "dep": dep, "derive": derive, "pool": pool,
            "recording": hashlib.sha256(np.ascontiguousarray(pool).tobytes() + seed.to_bytes(4, "big")).digest(),
            "params": hashlib.sha256(b"T=500;beta=0.01;N=2000;B=20;q=90;rho0=0.1;floor=8.0,5.70").digest(),
            "derive_seconds": time.perf_counter() - t0}


def experiment(name: str, port: int, cycles: int, cal: dict) -> dict:
    ch = Chain(port)
    art = json.loads(ART.read_text())
    owner, operator, auditor, gateway, outsider, insider = (Account.create() for _ in range(6))
    factory = ch.w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
    r, lat = ch.send(owner, factory.constructor(*FLOOR))
    assert r.status == 1 and ch.w3.eth.get_code(r.contractAddress), "deployment failed"
    C = ch.w3.eth.contract(address=r.contractAddress, abi=art["abi"])
    res = {"network": name, "chain_id": ch.chain_id, "deploy_gas": int(r.gasUsed), "setup_gas": [], "ops": {},
           "views_ms": [], "tests": {}, "client": ch.w3.client_version}
    for fn in (C.functions.setRoles(operator.address, True, False), C.functions.setRoles(auditor.address, False, True),
               C.functions.setRoles(insider.address, True, True), C.functions.setGateway(7, gateway.address)):
        res["setup_gas"].append(int(ch.send(owner, fn)[0].gasUsed))
    ops = {k: {"gas": [], "latency_s": []} for k in ("publishModel", "propose", "approve", "requestRecalibration")}

    def rec(k, r, lat):
        assert r.status == 1, k
        ops[k]["gas"].append(int(r.gasUsed))
        ops[k]["latency_s"].append(lat)

    bound = cal["dep"] + 1000                       # D_cal + 0.1
    for c in range(cycles):
        model = hashlib.sha256(f"model-{c}".encode()).digest()
        rec("publishModel", *ch.send(owner, C.functions.publishModel(model)))
        r, lat = ch.send(operator, C.functions.propose(7, model, cal["h1"], cal["h2"], cal["dep"], bound,
                                                      cal["recording"], cal["params"]))
        rec("propose", r, lat)
        pid = proposal_id(C, r, 7, model, cal["h1"], cal["h2"], cal["dep"], bound, cal["recording"], cal["params"],
                          operator.address)
        rec("approve", *ch.send(auditor, C.functions.approve(pid)))
        t0 = time.perf_counter()
        ok = C.functions.thresholds(7).call()
        res["views_ms"].append(1e3 * (time.perf_counter() - t0))
        assert ok[0] and ok[1] == cal["h1"]
        rec("requestRecalibration", *ch.send(gateway, C.functions.requestRecalibration(7, bound + 500)))
        assert not C.functions.thresholds(7).call()[0]
    res["ops"] = ops
    # security tests on a fresh model
    T = res["tests"]
    model = hashlib.sha256(b"model-tests").digest()
    ch.send(owner, C.functions.publishModel(model))
    args = (7, model, cal["h1"], cal["h2"], cal["dep"], bound, cal["recording"], cal["params"])
    T["outsider_proposes"] = ch.attempt(outsider, C.functions.propose(*args))
    T["below_floor_h1"] = ch.attempt(operator, C.functions.propose(7, model, FLOOR[0] - 1, cal["h2"], cal["dep"], bound,
                                                                    cal["recording"], cal["params"]))
    T["below_floor_h2"] = ch.attempt(operator, C.functions.propose(7, model, cal["h1"], FLOOR[1] - 1, cal["dep"], bound,
                                                                    cal["recording"], cal["params"]))
    old = hashlib.sha256(b"model-0").digest()
    T["stale_model_proposal"] = ch.attempt(operator, C.functions.propose(7, old, *args[2:]))
    r, _ = ch.send(insider, C.functions.propose(*args))
    pid_self = proposal_id(C, r, *args, insider.address)
    T["insider_self_approval"] = ch.attempt(insider, C.functions.approve(pid_self))
    r, _ = ch.send(operator, C.functions.propose(*args))
    pid = proposal_id(C, r, *args, operator.address)
    T["outsider_approves"] = ch.attempt(outsider, C.functions.approve(pid))
    # auditor re-derivation before approval: honest proposal approved, inflated proposal refused
    t0 = time.perf_counter()
    h1, h2, dep = cal["derive"](cal["pool"])
    rederive_s = time.perf_counter() - t0
    honest = (h1, h2) == (cal["h1"], cal["h2"])
    r, _ = ch.send(operator, C.functions.propose(7, model, 2 * cal["h1"], 2 * cal["h2"], cal["dep"], bound,
                                                 cal["recording"], cal["params"]))
    pid_inf = proposal_id(C, r, 7, model, 2 * cal["h1"], 2 * cal["h2"], cal["dep"], bound, cal["recording"],
                          cal["params"], operator.address)
    p = C.functions.pending(pid_inf).call()
    inflated_detected = (p[1], p[2]) != (h1, h2)
    T["auditor_rederivation"] = {"honest_matches": honest, "inflated_x2_refused": inflated_detected,
                                 "rederive_seconds": rederive_s}
    if honest:
        ch.send(auditor, C.functions.approve(pid))
    T["valid_after_honest_approval"] = {"valid": bool(C.functions.thresholds(7).call()[0])}
    T["outsider_requests_recal"] = ch.attempt(outsider, C.functions.requestRecalibration(7, bound + 500))
    T["recal_within_bound"] = ch.attempt(gateway, C.functions.requestRecalibration(7, bound - 1))
    ch.send(owner, C.functions.publishModel(hashlib.sha256(b"model-next").digest()))
    T["valid_after_new_model"] = {"valid": bool(C.functions.thresholds(7).call()[0])}
    T["approve_pending_after_new_model"] = ch.attempt(auditor, C.functions.approve(pid_inf))
    T["outsider_publishes_model"] = ch.attempt(outsider, C.functions.publishModel(hashlib.sha256(b"evil").digest()))
    T["outsider_grants_roles"] = ch.attempt(outsider, C.functions.setRoles(outsider.address, True, True))
    res["blocks"] = ch.w3.eth.block_number
    return res


def summarize(res: dict) -> dict:
    s = {k: {"gas": int(np.median(v["gas"])), "lat_median_s": float(np.median(v["latency_s"])),
             "lat_p95_s": float(np.percentile(v["latency_s"], 95)), "n": len(v["gas"])} for k, v in res["ops"].items()}
    s["view_ms_median"] = float(np.median(res["views_ms"]))
    rej = {k: v for k, v in res["tests"].items() if "status" in v}
    s["violations_rejected"] = f"{sum(v['status'] == 0 for v in rej.values())}/{len(rej)}"
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--networks", default="anvil,clique")
    ap.add_argument("--cycles", type=int, default=20)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cal = real_calibration()
    print(f"calibration: h1={cal['h1'] / SCALE:.2f} h2={cal['h2'] / SCALE:.2f} dep={cal['dep'] / SCALE:.3f} "
          f"({cal['derive_seconds']:.1f}s)", flush=True)
    teardown()
    try:
        for name in args.networks.split(","):
            port = start_anvil() if name == "anvil" else start_clique()
            res = experiment(name, port, args.cycles, cal)
            res["summary"] = summarize(res)
            res["calibration"] = {k: cal[k] for k in ("h1", "h2", "dep")}
            (OUT / f"{name}.json").write_text(json.dumps(res, indent=1, default=str))
            print(name, json.dumps(res["summary"]), flush=True)
            print({k: v.get("reason", v) for k, v in res["tests"].items()}, flush=True)
            teardown()
    finally:
        teardown()


if __name__ == "__main__":
    main()
