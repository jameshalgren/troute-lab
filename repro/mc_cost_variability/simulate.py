"""Route one scenario through the work-counting kernel port and record the work of every call.

    uv run --locked python simulate.py <scenario> [--keep-traj]

Scenarios: common.SCENARIOS (calm, s25, s100, s250, s25_f, s250_f).

Why not T-Route itself: T-Route (gfortran, netCDF-Fortran) is not built on the machine
used, and the compiled kernel returns no iteration count anyway. Instead the network is
routed by the float32 port, in the order and with the inputs T-Route uses
(compute_network_structured, mc_reach.pyx L502-512 and L731-751 @ d29f663; the same
semantics ../short_ts_switch/closure_replay.py uses to replay T-Route recordings):
  for every step t: for every segment s, upstream before downstream:
    qup = float32 sum of the upstream segments' flow at t-1 (ascending feature id),
    quc = the same sum at t (assume_short_ts = False) or qup (True),
    qdp, depthp = the segment's own flow and depth at t-1,
    ql  = hourly lateral inflow of hour t // qts_subdivisions;
  t = -1 is the initial state: steady baseflow, depth 0 (T-Route's lite restart, h0 = 0).
Each call goes through mc_count.mc_count (corrected kernel, Qj_0 = 0), which returns the
outflow, the depth and the work counters.

Verification in the same process (results in verify.json; check.py tests them):
1. every call is replayed from the stored trajectories through the unmodified
   ../short_ts_switch/closure_port.mc_kernel (corrected=True): outflow and depth must be
   bitwise identical, and its iteration and try counters equal to mc_count's;
2. closure fractions (clamp, floor, overbank, guard steps) from the same replay, for the
   comparison with T-Route's values in ../short_ts_switch/expected/closure.json;
3. outlet peak, peak time and event volume balance for the comparison with
   ../short_ts_switch/expected/expected.json (check.py).

Outputs in results/runs/<scenario>/:
  counts.npz   n_iter (uint16, nseg x nts: secant passes per call), n_restart (uint8:
               patch-0008 + non-convergence restarts), fail (uint8: fifth try reached,
               depth held), guard (uint8: negative-flow guard branch), link (feature ids);
               segment-major, step j is the call that produces the flow at t0 + (j+1) dt
  flows.npz    q_hourly (end of each hour), peak_q, peak_step, volume_m3, outlet_q (native)
  verify.json  replay comparison, closure fractions, outlet metrics, wall times
  traj_q.npy / traj_h.npy  (only with --keep-traj) native flow and depth, time-major
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import common as C  # first: sets NUMBA_CACHE_DIR and the read-only path to ../short_ts_switch
import numpy as np
from numba import njit, prange

import closure_port as CP  # ../short_ts_switch/closure_port.py, unmodified
import mc_count as MC


@njit(cache=True)
def forward(qlat, q0, h0, up_ptr, up_idx, P, topo, dt, sts, qts, nts, Qt, Ht, IT, RS, FA, GU):
    """Route nts steps. Qt, Ht (nts x nseg float32) receive flow and depth; IT, RS, FA, GU
    (nts x nseg) the work counters. Returns the number of inactive calls."""
    nseg = q0.shape[0]
    qprev = q0.copy()
    hprev = h0.copy()
    qcur = np.zeros(nseg, dtype=np.float32)
    hcur = np.zeros(nseg, dtype=np.float32)
    inactive = 0
    for t in range(nts):
        hr = t // qts
        for k in range(nseg):
            s = topo[k]
            qup = np.float32(0.0)
            quc_now = np.float32(0.0)
            for j in range(up_ptr[s], up_ptr[s + 1]):
                u = up_idx[j]
                qup += qprev[u]
                quc_now += qcur[u]
            quc = qup if sts else quc_now
            qdc, hc, it, nc, nn, fail, guard, active = MC.mc_count(
                dt, qup, quc, qprev[s], qlat[s, hr], P[s, 0], P[s, 1], P[s, 2], P[s, 3], P[s, 4],
                P[s, 5], P[s, 6], P[s, 7], hprev[s], np.float32(0.0), True)
            qcur[s] = qdc
            hcur[s] = hc
            IT[t, s] = it
            RS[t, s] = nc + nn
            FA[t, s] = fail
            GU[t, s] = guard
            if active == 0:
                inactive += 1
        Qt[t, :] = qcur
        Ht[t, :] = hcur
        qprev, qcur = qcur, qprev
        hprev, hcur = hcur, hprev
    return inactive


@njit(cache=True, parallel=True)
def replay_check(qlat, q0, h0, up_ptr, up_idx, P, dt, sts, qts, t_acc0, Qt, Ht, IT, RS, FA, out):
    """Replay every call through closure_port.mc_kernel (the unmodified port) from the stored
    trajectories. out (nseg x 10, int64) per segment: q differs, h differs, iters differ,
    tries differ, steps (t >= t_acc0), clamp, floor, over, guard, active (as closure_replay.py)."""
    nts, nseg = Qt.shape
    for t in range(nts):
        hr = t // qts
        for s in prange(nseg):
            qup = np.float32(0.0)
            quc_now = np.float32(0.0)
            for j in range(up_ptr[s], up_ptr[s + 1]):
                u = up_idx[j]
                qup += q0[u] if t == 0 else Qt[t - 1, u]
                quc_now += Qt[t, u]
            quc = qup if sts else quc_now
            qdp = q0[s] if t == 0 else Qt[t - 1, s]
            hp = h0[s] if t == 0 else Ht[t - 1, s]
            qdc, hc, d = CP.mc_kernel(dt, qup, quc, qdp, qlat[s, hr], P[s, 0], P[s, 1], P[s, 2], P[s, 3],
                                      P[s, 4], P[s, 5], P[s, 6], P[s, 7], hp, np.float32(0.0), True)
            if qdc != Qt[t, s]:
                out[s, 0] += 1
            if hc != Ht[t, s]:
                out[s, 1] += 1
            if np.int64(d[18]) != np.int64(IT[t, s]):
                out[s, 2] += 1
            if np.int64(d[19]) != np.int64(RS[t, s]) + np.int64(FA[t, s]):
                out[s, 3] += 1
            if t < t_acc0:
                continue
            out[s, 4] += 1
            if d[0] > 0:
                out[s, 9] += 1
                ck, dxck, x2r = d[1], d[2], d[6]
                if not (ck > 0) or dxck <= dt:
                    out[s, 5] += 1
                if ck > 0 and x2r < 0.25:
                    out[s, 6] += 1
                if d[10] > 0:
                    out[s, 7] += 1
                if d[17] > 0:
                    out[s, 8] += 1


def peak_time_s(q: np.ndarray, dt: int) -> tuple[float, float]:
    """Peak flow and parabola-refined peak time, as ../short_ts_switch/run_troute.py Reducer
    (step j valid at (j+1) dt; first maximum)."""
    j = int(np.argmax(q))
    t = (j + 1) * float(dt)
    if 0 < j < len(q) - 1:
        a, b, c = float(q[j - 1]), float(q[j]), float(q[j + 1])
        den = a - 2 * b + c
        if den < 0:
            t += float(np.clip(0.5 * (a - c) / den, -0.5, 0.5)) * dt
    return float(q[j]), t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario", choices=list(C.SCENARIOS))
    ap.add_argument("--keep-traj", action="store_true", help="keep native flow/depth (time-major .npy)")
    args = ap.parse_args()
    sc = C.SCENARIOS[args.scenario]
    case = C.load_case()
    nseg = len(case["link"])
    qlat = C.storm_qlat(case["length_km"], sc["storm_mm"])
    q0 = case["q0_base"].astype(np.float32)
    h0 = np.zeros(nseg, dtype=np.float32)
    P = np.ascontiguousarray(case["params"], dtype=np.float32)
    nts, dt, qts = C.NTS, np.float32(C.DT), C.QTS
    Qt = np.empty((nts, nseg), dtype=np.float32)
    Ht = np.empty((nts, nseg), dtype=np.float32)
    IT = np.empty((nts, nseg), dtype=np.uint16)
    RS = np.empty((nts, nseg), dtype=np.uint8)
    FA = np.empty((nts, nseg), dtype=np.uint8)
    GU = np.empty((nts, nseg), dtype=np.uint8)
    t0 = time.perf_counter()
    inactive = forward(qlat, q0, h0, case["up_ptr"], case["up_idx"], P, case["topo"], dt, sc["sts"], qts, nts,
                       Qt, Ht, IT, RS, FA, GU)
    wall_fwd = time.perf_counter() - t0
    out = np.zeros((nseg, 10), dtype=np.int64)
    t0 = time.perf_counter()
    replay_check(qlat, q0, h0, case["up_ptr"], case["up_idx"], P, dt, sc["sts"], qts, C.T_ACC0, Qt, Ht, IT, RS, FA,
                 out)
    wall_rep = time.perf_counter() - t0
    tot = out.sum(axis=0)
    d = C.run_dir(args.scenario)
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / "counts.npz", n_iter=np.ascontiguousarray(IT.T), n_restart=np.ascontiguousarray(RS.T),
                        fail=np.ascontiguousarray(FA.T), guard=np.ascontiguousarray(GU.T), link=case["link"])
    seg = case["seg"]
    o = int(np.flatnonzero(seg["is_outlet"].to_numpy())[0])
    outlet_q = Qt[:, o].copy()
    pk_q, pk_t = peak_time_s(outlet_q, C.DT)
    vol = Qt.astype(np.float64).sum(axis=0) * C.DT
    T = C.HOURS * 3600.0
    # storm lateral volume upstream of the outlet (all segments): ql - baseflow, hour-averaged
    base = qlat[:, :1].astype(np.float64)
    storm_vol_outlet = float(((qlat.astype(np.float64) - base).sum()) * 3600.0)
    evb = (vol[o] - float(q0[o]) * T) / storm_vol_outlet if storm_vol_outlet > 0 else None
    np.savez_compressed(d / "flows.npz", q_hourly=np.ascontiguousarray(Qt[qts - 1::qts].T),
                        peak_q=Qt.max(axis=0), peak_step=Qt.argmax(axis=0), volume_m3=vol, outlet_q=outlet_q,
                        link=case["link"])
    if args.keep_traj:
        np.save(d / "traj_q.npy", Qt)
        np.save(d / "traj_h.npy", Ht)
    calls = nseg * nts
    info = {"scenario": args.scenario, **sc, "dt_s": C.DT, "nts": nts, "nseg": nseg, "calls": calls,
            "inactive_calls": int(inactive),
            "replay_vs_closure_port": {"calls": calls, "q_not_bitwise_equal": int(tot[0]),
                                       "h_not_bitwise_equal": int(tot[1]), "iterations_differ": int(tot[2]),
                                       "tries_differ": int(tot[3])},
            "closure_fractions_of_segment_steps": {
                "steps": int(tot[4]), "active": int(tot[9]),
                "clamp": float(tot[5] / tot[4]), "floor": float(tot[6] / tot[4]), "over": float(tot[7] / tot[4])},
            "negative_flow_guard_steps": int(tot[8]),
            "outlet": {"feature_id": int(case["link"][o]), "peak_m3s": pk_q, "peak_time_h": pk_t / 3600.0,
                       "event_volume_balance": evb},
            "mean_iterations_per_call": float(IT.mean(dtype=np.float64)),
            "max_iterations_per_call": int(IT.max()),
            "wall_s": {"forward": round(wall_fwd, 1), "replay_check": round(wall_rep, 1)}}
    (d / "verify.json").write_text(json.dumps(info, indent=1) + "\n")
    r = info["replay_vs_closure_port"]
    print(f"ok      {args.scenario}: {calls} calls in {wall_fwd:.1f} s; mean iterations "
          f"{info['mean_iterations_per_call']:.3f}, max {info['max_iterations_per_call']}; replay vs closure_port: "
          f"q {r['q_not_bitwise_equal']}, h {r['h_not_bitwise_equal']}, iters {r['iterations_differ']}, "
          f"tries {r['tries_differ']} differ; outlet peak {pk_q:.2f} m3/s at {pk_t / 3600:.2f} h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
