"""Count the kernel's work on a T-Route recording (for machines where T-Route is built).

    uv run --locked python replay_record.py <record_dir> <name>      # writes results/runs/<name>/
    uv run --locked python replay_record.py --self-test s25           # checks this script

<record_dir> is the output of ../short_ts_switch/closure_record.py (T-Route's own run with
every segment-step's flow and depth plus the inputs T-Route passed to the MC computation;
format in that file's docstring). Every call is replayed from T-Route's inputs through
mc_count.mc_count (corrected kernel, Qj_0 = 0, as ../short_ts_switch/closure_replay.py
--corrected), so the counts are those of the port on T-Route's own trajectories, and the
port's outflow is compared with T-Route's (the fidelity measured in
../short_ts_switch/README.md "Closure diagnostics": 90-98% bitwise). The record must come
from a T-Route build with the corrected kernel (the default of ../short_ts_switch/build_troute.py).
Writes counts.npz in simulate.py's format plus fidelity.json.

--self-test <scenario>: writes simulate.py's trajectory of <scenario> in the
closure_record.py format into build/selftest_record/, replays it, and requires counts
identical to simulate.py's (then deletes the temporary record).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys

import common as C  # first: sets NUMBA_CACHE_DIR
import numpy as np
from numba import njit, prange

import mc_count as MC


@njit(cache=True, parallel=True)
def replay(Q, H, qlat, q0, h0, up_ptr, up_idx, P, dt, sts, qts, IT, RS, FA, GU, fid):
    """Q, H: segment-major (nseg x nts) T-Route flow and depth. fid (nseg x 3): calls with
    port outflow != T-Route (bitwise), relative difference > 1e-6, > 1e-3."""
    nseg, nts = Q.shape
    for s in prange(nseg):
        for t in range(nts):
            qup = np.float32(0.0)
            quc_now = np.float32(0.0)
            for j in range(up_ptr[s], up_ptr[s + 1]):
                u = up_idx[j]
                qup += q0[u] if t == 0 else Q[u, t - 1]
                quc_now += Q[u, t]
            quc = qup if sts else quc_now
            qdp = q0[s] if t == 0 else Q[s, t - 1]
            hp = h0[s] if t == 0 else H[s, t - 1]
            qdc, hc, it, nc, nn, fail, guard, active = MC.mc_count(
                dt, qup, quc, qdp, qlat[s, t // qts], P[s, 0], P[s, 1], P[s, 2], P[s, 3], P[s, 4], P[s, 5],
                P[s, 6], P[s, 7], hp, np.float32(0.0), True)
            IT[s, t] = it
            RS[s, t] = nc + nn
            FA[s, t] = fail
            GU[s, t] = guard
            O = Q[s, t]
            if qdc != O:
                fid[s, 0] += 1
            rel = abs(np.float64(qdc) - np.float64(O)) / max(abs(np.float64(O)), 1e-3)
            if rel > 1e-6:
                fid[s, 1] += 1
            if rel > 1e-3:
                fid[s, 2] += 1


def run_record(rec, out_name: str) -> dict:
    meta = json.loads((rec / "meta.json").read_text())
    Q = np.load(rec / "q.npy", mmap_mode="r")
    H = np.load(rec / "h.npy", mmap_mode="r")
    a = {k: np.load(rec / f"{k}.npy") for k in ("qlat", "q0", "h0", "up_ptr", "up_idx", "params", "link")}
    nseg, nts = Q.shape
    IT = np.empty((nseg, nts), np.uint16)
    RS = np.empty((nseg, nts), np.uint8)
    FA = np.empty((nseg, nts), np.uint8)
    GU = np.empty((nseg, nts), np.uint8)
    fid = np.zeros((nseg, 3), np.int64)
    replay(np.ascontiguousarray(Q), np.ascontiguousarray(H), a["qlat"], a["q0"], a["h0"], a["up_ptr"], a["up_idx"],
           np.ascontiguousarray(a["params"], dtype=np.float32), np.float32(meta["dt_s"]),
           bool(meta["assume_short_ts"]), int(meta["qts_subdivisions"]), IT, RS, FA, GU, fid)
    d = C.run_dir(out_name)
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / "counts.npz", n_iter=IT, n_restart=RS, fail=FA, guard=GU, link=a["link"])
    f = fid.sum(axis=0)
    info = {"record": str(rec.name), "meta": {k: meta[k] for k in ("case", "dt_s", "assume_short_ts", "nts", "nseg")
                                              if k in meta},
            "calls": int(nseg * nts), "port_q_not_bitwise_equal": int(f[0]), "rel_gt_1e-6": int(f[1]),
            "rel_gt_1e-3": int(f[2]), "mean_iterations_per_call": float(IT.mean(dtype=np.float64))}
    (d / "fidelity.json").write_text(json.dumps(info, indent=1) + "\n")
    return info


def self_test(name: str) -> int:
    import simulate as SIM
    sc = C.SCENARIOS[name]
    case = C.load_case()
    nseg = len(case["link"])
    qlat = C.storm_qlat(case["length_km"], sc["storm_mm"])
    q0 = case["q0_base"].astype(np.float32)
    h0 = np.zeros(nseg, np.float32)
    P = np.ascontiguousarray(case["params"], dtype=np.float32)
    Qt = np.empty((C.NTS, nseg), np.float32)
    Ht = np.empty((C.NTS, nseg), np.float32)
    IT = np.empty((C.NTS, nseg), np.uint16)
    RS = np.empty((C.NTS, nseg), np.uint8)
    FA = np.empty((C.NTS, nseg), np.uint8)
    GU = np.empty((C.NTS, nseg), np.uint8)
    SIM.forward(qlat, q0, h0, case["up_ptr"], case["up_idx"], P, case["topo"], np.float32(C.DT), sc["sts"], C.QTS,
                C.NTS, Qt, Ht, IT, RS, FA, GU)
    rec = C.BUILD / "selftest_record"
    rec.mkdir(parents=True, exist_ok=True)
    np.save(rec / "q.npy", np.ascontiguousarray(Qt.T))
    np.save(rec / "h.npy", np.ascontiguousarray(Ht.T))
    del Qt, Ht
    for k, v in {"qlat": qlat, "q0": q0, "h0": h0, "up_ptr": case["up_ptr"], "up_idx": case["up_idx"],
                 "params": P, "link": case["link"]}.items():
        np.save(rec / f"{k}.npy", v)
    (rec / "meta.json").write_text(json.dumps({"case": "potomac", "dt_s": C.DT, "assume_short_ts": sc["sts"],
                                               "nts": C.NTS, "nseg": nseg, "qts_subdivisions": C.QTS}))
    info = run_record(rec, f"selftest_{name}")
    z = np.load(C.run_dir(f"selftest_{name}") / "counts.npz")
    same = (np.array_equal(z["n_iter"], IT.T) and np.array_equal(z["n_restart"], RS.T)
            and np.array_equal(z["fail"], FA.T) and np.array_equal(z["guard"], GU.T))
    ok = same and info["port_q_not_bitwise_equal"] == 0
    shutil.rmtree(rec)
    (C.run_dir(f"selftest_{name}") / "counts.npz").unlink()
    out = {"scenario": name, "counts_identical_to_simulate": bool(same),
           "replayed_q_bitwise_equal_to_recording": info["port_q_not_bitwise_equal"] == 0, "ok": bool(ok)}
    (C.run_dir(f"selftest_{name}") / "selftest.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"{'ok' if ok else 'FAIL':8}replay_record self-test on {name}: counts identical {same}, "
          f"outflow differs in {info['port_q_not_bitwise_equal']} calls")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record", nargs="?")
    ap.add_argument("name", nargs="?")
    ap.add_argument("--self-test", metavar="SCENARIO")
    args = ap.parse_args()
    if args.self_test:
        return self_test(args.self_test)
    if not (args.record and args.name):
        ap.error("record and name are required (or --self-test)")
    from pathlib import Path
    info = run_record(Path(args.record).resolve(), args.name)
    print(f"ok      replayed {info['calls']} calls: outflow not bitwise equal to T-Route in "
          f"{info['port_q_not_bitwise_equal']}, rel > 1e-3 in {info['rel_gt_1e-3']}; mean iterations "
          f"{info['mean_iterations_per_call']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
