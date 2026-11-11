"""How well do secant iterations predict the kernel's run time? Time the port per call and per unit.

    uv run --locked python timing.py [scenario ...]        (default: calm s25 s250)

Timing is of the float32 port (mc_count.mc_count, numba), single thread, on the machine
used; it is not the compiled T-Route kernel (see README "Caveats"). The clock is
mach_absolute_time (macOS), read inside the compiled loop through ctypes, so no Python
overhead enters a measurement; the script stops on other platforms.

1. Units: every (segment, 24-h window) of the run (the T-Route chunk window,
   common.WINDOWS["24h"] = 288 steps): the inputs of the unit's 288 calls are gathered
   from the routed trajectories into contiguous buffers (not timed), then the 288 calls
   are timed together, `--reps` times back to back (default 3); the minimum is kept.
   Window 0 (the restart spin-up) is left out of the fits. Fitted models, by least squares
   over all units: time = a * calls + b * iterations, and time = c * iterations (cost
   proportional to iterations, the proxy the scheduling model uses).
2. Calls by iteration count: up to 50,000 random calls per class (exactly k iterations,
   k = 1..8, then 9-20, 21-60, 61-1000) are timed as a batch (minimum of 5 repetitions)
   -> ns per call against the class's mean iteration count.

Outputs: results/timing/<scenario>.npz (unit times and iterations), results/timing.json,
tables/timing_per_call.csv, tables/timing_units.csv.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import sys
import time

import common as C  # first: sets NUMBA_CACHE_DIR and the read-only path to ../short_ts_switch
import numpy as np
import pandas as pd
from numba import njit

import mc_count as MC
import simulate as SIM

if sys.platform != "darwin":
    raise SystemExit("timing.py reads mach_absolute_time (macOS only)")
_libc = ctypes.CDLL(ctypes.util.find_library("c"))
_mat = _libc.mach_absolute_time
_mat.restype = ctypes.c_uint64
_mat.argtypes = []


class _TB(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


_tb = _TB()
_libc.mach_timebase_info(ctypes.byref(_tb))
NS_PER_TICK = _tb.numer / _tb.denom
# iteration-count classes for the per-call timing (inclusive bounds)
CLASSES = [(k, k) for k in range(1, 9)] + [(9, 20), (21, 60), (61, 1000)]


@njit(cache=False)
def time_units(qlat, q0, h0, up_ptr, up_idx, P, dt, sts, qts, Qs, Hs, W, reps, ticks, iters, sink):
    """Qs, Hs: segment-major (nseg x nts) flow and depth. For every unit: gather, then time
    the unit's W calls `reps` times back to back; keep the minimum."""
    nseg, nts = Qs.shape
    nw = nts // W
    bqup = np.empty(W, np.float32)
    bquc = np.empty(W, np.float32)
    bqdp = np.empty(W, np.float32)
    bql = np.empty(W, np.float32)
    bhp = np.empty(W, np.float32)
    for s in range(nseg):
        for w in range(nw):
            for i in range(W):                           # gather (not timed)
                t = w * W + i
                qup = np.float32(0.0)
                quc_now = np.float32(0.0)
                for j in range(up_ptr[s], up_ptr[s + 1]):
                    u = up_idx[j]
                    qup += q0[u] if t == 0 else Qs[u, t - 1]
                    quc_now += Qs[u, t]
                bqup[i] = qup
                bquc[i] = qup if sts else quc_now
                bqdp[i] = q0[s] if t == 0 else Qs[s, t - 1]
                bhp[i] = h0[s] if t == 0 else Hs[s, t - 1]
                bql[i] = qlat[s, t // qts]
            for rep in range(reps):
                acc = np.float32(0.0)
                itsum = 0
                t0 = _mat()
                for i in range(W):
                    qdc, hc, it, nc, nn, fail, guard, active = MC.mc_count(
                        dt, bqup[i], bquc[i], bqdp[i], bql[i], P[s, 0], P[s, 1], P[s, 2], P[s, 3], P[s, 4],
                        P[s, 5], P[s, 6], P[s, 7], bhp[i], np.float32(0.0), True)
                    acc += qdc + hc
                    itsum += it
                t1 = _mat()
                d = np.int64(t1 - t0)
                if rep == 0 or d < ticks[s, w]:
                    ticks[s, w] = d
                iters[s, w] = itsum
                sink[0] += acc


@njit(cache=False)
def gather_calls(qlat, q0, h0, up_ptr, up_idx, P, sts, qts, Qt, Ht, ss, tt, X):
    """Inputs of the calls (ss[k], tt[k]) -> X (k x 13): qup, quc, qdp, ql, dx..s0, depthp."""
    for k in range(len(ss)):
        s, t = ss[k], tt[k]
        qup = np.float32(0.0)
        quc_now = np.float32(0.0)
        for j in range(up_ptr[s], up_ptr[s + 1]):
            u = up_idx[j]
            qup += q0[u] if t == 0 else Qt[t - 1, u]
            quc_now += Qt[t, u]
        X[k, 0] = qup
        X[k, 1] = qup if sts else quc_now
        X[k, 2] = q0[s] if t == 0 else Qt[t - 1, s]
        X[k, 3] = qlat[s, t // qts]
        for c in range(8):
            X[k, 4 + c] = P[s, c]
        X[k, 12] = h0[s] if t == 0 else Ht[t - 1, s]


@njit(cache=False)
def time_calls(X, dt, reps, sink):
    best = np.int64(-1)
    for rep in range(reps):
        acc = np.float32(0.0)
        t0 = _mat()
        for k in range(X.shape[0]):
            qdc, hc, it, nc, nn, fail, guard, active = MC.mc_count(
                dt, X[k, 0], X[k, 1], X[k, 2], X[k, 3], X[k, 4], X[k, 5], X[k, 6], X[k, 7], X[k, 8], X[k, 9],
                X[k, 10], X[k, 11], X[k, 12], np.float32(0.0), True)
            acc += qdc
        t1 = _mat()
        d = np.int64(t1 - t0)
        if best < 0 or d < best:
            best = d
        sink[0] += acc
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="*", default=["calm", "s25", "s250"])
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()
    case = C.load_case()
    nseg = len(case["link"])
    P = np.ascontiguousarray(case["params"], dtype=np.float32)
    q0 = case["q0_base"].astype(np.float32)
    h0 = np.zeros(nseg, dtype=np.float32)
    W = C.WINDOWS[C.PRIMARY_WINDOW]
    dt = np.float32(C.DT)
    out_dir = C.RESULTS / "timing"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary, per_call_rows, unit_rows = {}, [], []
    rng = np.random.default_rng(20261030)
    for name in args.scenarios:
        sc = C.SCENARIOS[name]
        qlat = C.storm_qlat(case["length_km"], sc["storm_mm"])
        nts = C.NTS
        Qt = np.empty((nts, nseg), np.float32)
        Ht = np.empty((nts, nseg), np.float32)
        IT = np.empty((nts, nseg), np.uint16)
        RS = np.empty((nts, nseg), np.uint8)
        FA = np.empty((nts, nseg), np.uint8)
        GU = np.empty((nts, nseg), np.uint8)
        SIM.forward(qlat, q0, h0, case["up_ptr"], case["up_idx"], P, case["topo"], dt, sc["sts"], C.QTS, nts,
                    Qt, Ht, IT, RS, FA, GU)
        # 1. units
        nw = nts // W
        ticks = np.zeros((nseg, nw), np.int64)
        iters = np.zeros((nseg, nw), np.int64)
        sink = np.zeros(1, np.float64)
        Qs = np.ascontiguousarray(Qt.T)
        Hs = np.ascontiguousarray(Ht.T)
        t0 = time.perf_counter()
        time_units(qlat, q0, h0, case["up_ptr"], case["up_idx"], P, dt, sc["sts"], C.QTS, Qs, Hs, W, args.reps,
                   ticks, iters, sink)
        wall = time.perf_counter() - t0
        del Qs, Hs
        ns = ticks * NS_PER_TICK
        y = ns[:, 1:].ravel()                         # window 0 holds the restart spin-up (h0 = 0)
        x = iters[:, 1:].ravel().astype(float)
        A = np.stack([np.full_like(x, W), x], axis=1)
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        pred = A @ coef
        r2 = 1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        r_pearson = float(np.corrcoef(x, y)[0, 1])
        from scipy.stats import spearmanr
        rho = float(spearmanr(x, y).statistic)
        cv_t = float(y.std() / y.mean())
        cv_i = float(x.std() / x.mean())
        cv_model = float(pred.std() / pred.mean())
        c_prop = float((x * y).sum() / (x * x).sum())          # time = c * iterations (the cost proxy)
        r2_prop = 1 - ((y - c_prop * x) ** 2).sum() / ((y - y.mean()) ** 2).sum()
        np.savez_compressed(out_dir / f"{name}.npz", ns=ns.astype(np.float32), iters=iters, link=case["link"],
                            window_steps=W)
        summary[name] = {
            "units": int(y.size), "window_steps": W, "reps_min_of": args.reps, "wall_s": round(wall, 1),
            "ns_per_call_fixed_a": round(float(coef[0]), 2), "ns_per_iteration_b": round(float(coef[1]), 2),
            "r2_time_vs_model": round(float(r2), 4), "pearson_time_iters": round(r_pearson, 4),
            "spearman_time_iters": round(rho, 4), "mean_ns_per_call": round(float(y.mean() / W), 2),
            "cv_units_time": round(cv_t, 4), "cv_units_iterations": round(cv_i, 4),
            "cv_units_model_time": round(cv_model, 4),
            "ns_per_iteration_proportional": round(c_prop, 2), "r2_time_proportional_to_iterations": round(float(r2_prop), 4)}
        unit_rows.append({"scenario": name, **summary[name]})
        # 2. calls by iteration count: common classes from 20 M random calls, rare ones (>= 7) exhaustively
        flat = IT[C.T_ACC0:].reshape(-1)
        cand = rng.integers(0, flat.size, 20_000_000)
        cand = np.concatenate([cand[flat[cand] < 7], np.flatnonzero(flat >= 7)])
        kk = flat[cand].astype(np.int64)
        for lo, hi in CLASSES:
            sel = cand[(kk >= lo) & (kk <= hi)]
            if sel.size == 0:
                continue
            sel = rng.choice(sel, size=min(50_000, sel.size), replace=False)
            tt_k = (sel // nseg + C.T_ACC0).astype(np.int64)
            ss_k = (sel % nseg).astype(np.int64)
            X = np.empty((sel.size, 13), np.float32)
            gather_calls(qlat, q0, h0, case["up_ptr"], case["up_idx"], P, sc["sts"], C.QTS, Qt, Ht, ss_k, tt_k, X)
            best = time_calls(X, dt, 5, sink)
            per_call_rows.append({"scenario": name, "iterations_lo": lo, "iterations_hi": hi,
                                  "mean_iterations": round(float(flat[sel].mean()), 3), "calls_timed": int(sel.size),
                                  "ns_per_call": round(best * NS_PER_TICK / sel.size, 2)})
        print(f"ok      timing {name}: {y.size} units, {wall:.0f} s; time = {coef[0]:.1f} ns/call + "
              f"{coef[1]:.1f} ns/iteration, R2 {r2:.3f}; CV units time {cv_t:.3f} vs iterations {cv_i:.3f}")
        del Qt, Ht, IT, RS, FA, GU
    pc = pd.DataFrame(per_call_rows)
    fits = {}
    for name, g in pc.groupby("scenario"):
        b, a = np.polyfit(g["mean_iterations"], g["ns_per_call"], 1)
        fits[name] = {"ns_fixed": round(float(a), 2), "ns_per_iteration": round(float(b), 2),
                      "r2": round(float(np.corrcoef(g["mean_iterations"], g["ns_per_call"])[0, 1] ** 2), 4),
                      "classes": len(g)}
    import platform
    info = {"clock": "mach_absolute_time", "ns_per_tick": NS_PER_TICK, "machine": platform.machine(),
            "platform": platform.platform(), "units": summary, "per_call_linear_fit": fits,
            "note": "float32 port (numba), single thread; not the compiled T-Route kernel"}
    (C.RESULTS / "timing.json").write_text(json.dumps(info, indent=1) + "\n")
    C.TABLES.mkdir(exist_ok=True)
    pc.to_csv(C.TABLES / "timing_per_call.csv", index=False)
    pd.DataFrame(unit_rows).to_csv(C.TABLES / "timing_units.csv", index=False)
    print(f"ok      results/timing.json, tables/timing_per_call.csv, tables/timing_units.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
