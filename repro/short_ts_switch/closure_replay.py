"""Replay every MC kernel call of a recorded T-Route run and reduce the closure diagnostics.

    uv run --with numba==0.61.2 python closure_replay.py <record_dir> <out.npz> [--qj0 0] [--corrected]

<record_dir> comes from closure_record.py. For every segment and step the inputs are the
ones T-Route used (mc_reach.pyx L506-515, L731-751; compute_reach_kernel L91-146):
  qup = sum of the upstream segments' flow at the previous step (T-Route's float32 sum,
        in T-Route's upstream order), quc = the same at the current step (False) or qup
        (True, assume_short_ts), qdp / depthp = the segment's own flow and depth at the
        previous step (the loop's q0/h0 at step 0), ql = qlat[:, step // qts_subdivisions].
Each call goes through closure_port.mc_kernel (float32 port). --corrected (2026-10-09):
the port follows the corrected kernel (../kernel_fixes/patches/0001-0008), as built by
default; without it, the d29f663 kernel with Qj_0 = --qj0 (default 0) on entry. Its outflow is compared with T-Route's; its internals are reduced
per segment (no per-step arrays are kept):

cnt (int64)  counts of segment-steps: CNT names below
fsum (f64)   sums: routed volume by class, the kernel's storage identity, the volume-loss
             decomposition by summation by parts, the inflow-weighted local shift
pk (f64)     closure values at the segment's peak step (first maximum of T-Route's flow)
mm (f64)     minima / maxima over active steps
hist         histograms (log10 Km, log10 dx/Ck, log10 C, log10 D, final X) by slope class
             and by stream order, split in-bank / overbank

Definitions (closure = the interval-2 secant2_h call of the last secant iteration, whose
C1..C4 produce qdc):
  Km = max(dt, dx/Ck)           clamp  <=> dx/Ck <= dt (or Ck = 0), i.e. C >= 1
  C  = Ck dt / dx               Courant number with the closure's celerity
  D  = qref / (W S0 Ck dx)      cell Reynolds number with the kernel's own reference
                                discharge qref (C-weighted flow from the interval-1
                                coefficients), X width W (TopWdthCC overbank, else the
                                water-surface width bw + 2 z h), Ck and dx. The kernel's
                                X2_raw = 1/2 (1 - D/2) (the extra factor 2 of NCAR/wrf_hydro_nwm_public#921), so the 0.25
                                floor binds at D > 1; Cunge's X = 1/2 (1 - D) would be
                                below 0.25 at D > 1/2 and negative at D > 1.
  floor <=> X2_raw < 0.25 (Ck > 0); cap <=> X2_raw > 0.5; overbank <=> h > bankfull
  depth (closure depth h of that call; bfd = (TopWdth - BtmWdth)/(2 z), z = 1/ChSlp).
Volume-loss decomposition: per step, dt/2 (qup + quc) + ql dt - dt/2 (qdp + qdc) =
a (quc - qup) + b (qdc - qdp), a = Km X, b = Km (1 - X) (the kernel's storage identity). Summation
by parts over the event gives in - out = boundary - sum_t [quc_t (a_t+1 - a_t) +
O_t (b_t+1 - b_t)]: only changes of Km X and Km (1 - X) between consecutive steps lose
or gain water. Each transition is assigned to "both" (clamp and floor at both steps;
contributes exactly 0), "floor" (floor at both, not clamp at both), "clamp" (clamp at
both, not floor at both) or "free" (everything else). With True the a-term is
identically zero (quc = qup). T-Route's own flows O are used, so the parts add up to
T-Route's per-segment loss within the replay error (reported). Where the negative-flow
guard replaced the raw value s by qdc, the identity carries an extra -D (qdc - s),
D = Km (1 - X) + dt/2 (`guard_term`). These sums start after the first hour (t_acc0):
T-Route's first step starts from the restart depth h0 = 0; `in_minus_out` covers all
steps, `in_minus_out_acc` the accounted ones. All counts, histograms, minima / maxima and
peak values also start at t_acc0; the fidelity counts cover every step.
Timing: per segment, the local first-moment shift of upstream water when enabling the
short-time-step assumption, Delta_t = dt/2 - Km X, is weighted by the
excess upstream inflow max(quc_t - quc_initial, 0) and split by step class.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit, prange

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import closure_port as CP  # noqa: E402

CNT = ["steps", "active", "clamp", "floor", "cap", "both", "c2neg", "c3neg", "over", "guard",
       "x1_floor0", "x1_cap", "ck0", "over_clamp", "over_floor", "over_c2neg", "D_gt_half",
       "err_q_rel_gt_1e-6", "err_q_rel_gt_1e-3", "q_bitwise_equal", "err_h_rel_gt_1e-3", "D_le_0",
       "over_both", "iterations", "retries", "guard_at_cap"]
FSUM = ["vol", "vol_clamp", "vol_floor", "vol_both", "vol_over", "in_minus_out", "id_a_dI", "id_b_dO",
        "bp_free", "bp_floor", "bp_clamp", "bp_both", "bp_boundary", "w_excess_inflow",
        "wdelta_free", "wdelta_floor", "wdelta_clamp", "wdelta_both",
        "max_abs_err_q", "max_rel_err_q", "max_abs_err_h", "guard_term", "in_minus_out_acc"]
PK = ["q", "step", "Ck", "dx_over_Ck", "Km", "X1_raw", "X2_raw", "X2", "C", "D", "C1", "C2", "C3", "C4",
      "over", "h_over_bfd", "qref", "width", "clamp", "floor"]
MM = ["min_X2_raw", "max_D", "min_Km", "max_Km", "min_dx_over_Ck", "max_dx_over_Ck", "min_C", "max_C",
      "min_X1_raw", "max_X1_raw", "max_h_over_bfd", "max_retries", "max_iterations"]
# histogram variables: (name, lo, hi, nbins) on the stated scale
HV = [("log10_Km_s", 0.0, 7.0, 140), ("log10_dx_over_Ck_s", 0.0, 7.0, 140), ("log10_C", -6.0, 4.0, 200),
      ("log10_D", -6.0, 7.0, 260), ("X2", 0.25, 0.5, 50)]
HOFF = np.cumsum([0] + [v[3] for v in HV])
NB = int(HOFF[-1])
SLOPE_CLASSES = ["floor_1e-5", "1e-5_to_2.5e-4", "2.5e-4_to_1e-3", "gt_1e-3"]


def slope_class(s0: np.ndarray) -> np.ndarray:
    return np.select([s0 <= 1.0001e-5, s0 < 2.5e-4, s0 <= 1e-3], [0, 1, 2], 3)


@njit(cache=True, inline="always")
def _bin(v, lo, hi, nb):
    b = int((v - lo) / (hi - lo) * nb)
    if b < 0:
        return 0
    if b >= nb:
        return nb - 1
    return b


@njit(cache=True, parallel=True)
def replay(Q, H, qlat, q0, h0, up_ptr, up_idx, P, dt, sts, qts, qj0, t_acc0, cnt, fs, pk, mm, hist,
           corrected=False):
    nseg, T = Q.shape
    dt64 = np.float64(dt)
    half = dt64 / 2.0
    for s in prange(nseg):
        dx, bw, tw, twcc, n, ncc, cs, s0 = P[s, 0], P[s, 1], P[s, 2], P[s, 3], P[s, 4], P[s, 5], P[s, 6], P[s, 7]
        k0, k1 = up_ptr[s], up_ptr[s + 1]
        qup_next = np.float32(0.0)
        for k in range(k0, k1):
            qup_next += q0[up_idx[k]]
        i_init = np.float64(qup_next)
        qdp = q0[s]
        hp = h0[s]
        best = -np.inf
        pa = 0.0
        pb = 0.0
        pquc = 0.0
        pO = 0.0
        pcl = False
        pfl = False
        a_first = 0.0
        b_first = 0.0
        qup_first = 0.0
        qdp_first = 0.0
        for j in range(len(MM_INIT)):
            mm[s, j] = MM_INIT[j]
        for t in range(T):
            qup = qup_next
            quc_now = np.float32(0.0)
            for k in range(k0, k1):
                quc_now += Q[up_idx[k], t]
            quc = qup if sts else quc_now
            ql = qlat[s, t // qts]
            qdc, hc, d = CP.mc_kernel(dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, hp, qj0, corrected)
            O = Q[s, t]
            Hs = H[s, t]
            active = d[0] > 0
            ck, dxck, km, x1r, x2r, x2, qref, width = d[1], d[2], d[3], d[4], d[6], d[7], d[8], d[9]
            over = d[10] > 0
            hcl, bfd = d[11], d[12]
            c1, c2, c3, c4 = d[13], d[14], d[15], d[16]
            # replay fidelity
            dq = abs(np.float64(qdc) - np.float64(O))
            rel = dq / max(abs(np.float64(O)), 1e-3)
            if rel > 1e-6:
                cnt[s, 17] += 1
            if rel > 1e-3:
                cnt[s, 18] += 1
            if qdc == O:
                cnt[s, 19] += 1
            dh = abs(np.float64(hc) - np.float64(Hs))
            if dh / max(np.float64(Hs), 1e-3) > 1e-3:
                cnt[s, 20] += 1
            if dq > fs[s, 18]:
                fs[s, 18] = dq
            if rel > fs[s, 19]:
                fs[s, 19] = rel
            if dh > fs[s, 20]:
                fs[s, 20] = dh
            # step volume balance with T-Route's flows (trapezoid), all steps and accounted steps
            qup64, quc64, qdp64, O64 = np.float64(qup), np.float64(quc), np.float64(qdp), np.float64(O)
            e = half * (qup64 + quc64) + np.float64(ql) * dt64 - half * (qdp64 + O64)
            fs[s, 5] += e
            if t < t_acc0:                       # spin-up: T-Route's first step starts from h0 = 0
                qup_next = quc_now
                qdp = O
                hp = Hs
                continue
            fs[s, 22] += e
            cnt[s, 0] += 1
            # closure classification
            cl = False
            fl = False
            a = 0.0
            b = 0.0
            vol = np.float64(O) * dt64
            fs[s, 0] += vol
            if active:
                cnt[s, 1] += 1
                cnt[s, 23] += np.int64(d[18])
                cnt[s, 24] += np.int64(d[19])
                cl = not (ck > 0) or dxck <= dt
                fl = ck > 0 and x2r < 0.25
                cap = ck > 0 and x2r > 0.5
                a = np.float64(km) * np.float64(x2)
                b = np.float64(km) * (1.0 - np.float64(x2))
                if cl:
                    cnt[s, 2] += 1
                    fs[s, 1] += vol
                if fl:
                    cnt[s, 3] += 1
                    fs[s, 2] += vol
                if cap:
                    cnt[s, 4] += 1
                if cl and fl:
                    cnt[s, 5] += 1
                    fs[s, 3] += vol
                if c2 < 0:
                    cnt[s, 6] += 1
                if c3 < 0:
                    cnt[s, 7] += 1
                if over:
                    cnt[s, 8] += 1
                    fs[s, 4] += vol
                    if cl:
                        cnt[s, 13] += 1
                    if fl:
                        cnt[s, 14] += 1
                    if c2 < 0:
                        cnt[s, 15] += 1
                    if cl and fl:
                        cnt[s, 22] += 1
                if d[17] > 0:
                    cnt[s, 9] += 1
                    if x2 == 0.5:
                        cnt[s, 25] += 1
                    # the guard replaced s = C1 qup + C2 quc + C3 qdp + C4 by qdc; the storage
                    # identity then carries -D (qdc - s), D = Km (1 - X) + dt/2
                    s_raw = (np.float64(c1) * qup64 + np.float64(c2) * quc64 + np.float64(c3) * qdp64
                             + np.float64(c4))
                    fs[s, 21] -= (b + half) * (np.float64(qdc) - s_raw)
                if x1r < 0:
                    cnt[s, 10] += 1
                if x1r > 0.5:
                    cnt[s, 11] += 1
                hob = np.float64(hcl) / np.float64(bfd)
                if hob > mm[s, 10]:
                    mm[s, 10] = hob
                if d[19] > mm[s, 11]:
                    mm[s, 11] = d[19]
                if d[18] > mm[s, 12]:
                    mm[s, 12] = d[18]
                if not (ck > 0):
                    cnt[s, 12] += 1
                else:
                    C = np.float64(ck) * dt64 / np.float64(dx)
                    D = np.float64(qref) / (np.float64(width) * np.float64(s0) * np.float64(ck) * np.float64(dx))
                    if D > 0.5:
                        cnt[s, 16] += 1
                    ov = 1 if over else 0
                    hist[s, ov, HOFF0 + _bin(np.log10(np.float64(km)), 0.0, 7.0, 140)] += 1
                    hist[s, ov, HOFF1 + _bin(np.log10(np.float64(dxck)), 0.0, 7.0, 140)] += 1
                    hist[s, ov, HOFF2 + _bin(np.log10(C) if C > 0 else -99.0, -6.0, 4.0, 200)] += 1
                    if D > 0:
                        hist[s, ov, HOFF3 + _bin(np.log10(D), -6.0, 7.0, 260)] += 1
                    else:
                        cnt[s, 21] += 1
                    hist[s, ov, HOFF4 + _bin(np.float64(x2), 0.25, 0.5, 50)] += 1
                    x2r64 = np.float64(x2r)
                    if x2r64 < mm[s, 0]:
                        mm[s, 0] = x2r64
                    if D > mm[s, 1]:
                        mm[s, 1] = D
                    km64 = np.float64(km)
                    if km64 < mm[s, 2]:
                        mm[s, 2] = km64
                    if km64 > mm[s, 3]:
                        mm[s, 3] = km64
                    dk = np.float64(dxck)
                    if dk < mm[s, 4]:
                        mm[s, 4] = dk
                    if dk > mm[s, 5]:
                        mm[s, 5] = dk
                    if C < mm[s, 6]:
                        mm[s, 6] = C
                    if C > mm[s, 7]:
                        mm[s, 7] = C
                    x1r64 = np.float64(x1r)
                    if x1r64 < mm[s, 8]:
                        mm[s, 8] = x1r64
                    if x1r64 > mm[s, 9]:
                        mm[s, 9] = x1r64
                    if np.float64(O) > best:
                        best = np.float64(O)
                        pk[s, 0] = best
                        pk[s, 1] = t
                        pk[s, 2] = ck
                        pk[s, 3] = dxck
                        pk[s, 4] = km
                        pk[s, 5] = x1r
                        pk[s, 6] = x2r
                        pk[s, 7] = x2
                        pk[s, 8] = C
                        pk[s, 9] = D
                        pk[s, 10] = c1
                        pk[s, 11] = c2
                        pk[s, 12] = c3
                        pk[s, 13] = c4
                        pk[s, 14] = 1.0 if over else 0.0
                        pk[s, 15] = hob
                        pk[s, 16] = qref
                        pk[s, 17] = width
                        pk[s, 18] = 1.0 if cl else 0.0
                        pk[s, 19] = 1.0 if fl else 0.0
            # storage identity with T-Route's flows
            fs[s, 6] += a * (quc64 - qup64)
            fs[s, 7] += b * (O64 - qdp64)
            # summation by parts: transition t-1 -> t
            if t == t_acc0:
                a_first, b_first, qup_first, qdp_first = a, b, qup64, qdp64
            else:
                both_fl = pfl and fl
                both_cl = pcl and cl
                cat = 8 + (1 if both_fl else 0) + (2 if both_cl else 0)
                term = -pO * (b - pb)
                if not sts:
                    term -= pquc * (a - pa)
                fs[s, cat] += term
            # local shift of upstream water, weighted by excess upstream inflow
            w = np.float64(quc_now) - i_init
            if w > 0 and active:
                fs[s, 13] += w
                scat = 14 + (1 if fl else 0) + (2 if cl else 0)
                fs[s, scat] += w * (half - a)
            pa, pb, pquc, pO, pcl, pfl = a, b, quc64, O64, cl, fl
            # advance to the next step with T-Route's state
            qup_next = quc_now
            qdp = O
            hp = Hs
        bnd = pb * pO - b_first * qdp_first
        if not sts:
            bnd += pa * pquc - a_first * qup_first
        fs[s, 12] = bnd


MM_INIT = np.array([np.inf, -np.inf, np.inf, -np.inf, np.inf, -np.inf, np.inf, -np.inf, np.inf, -np.inf,
                    -np.inf, -np.inf, -np.inf])
HOFF0, HOFF1, HOFF2, HOFF3, HOFF4 = (int(x) for x in HOFF[:5])


def run(record: Path, qj0: float = 0.0, corrected: bool = False) -> dict:
    meta = json.loads((record / "meta.json").read_text())
    Q = np.load(record / "q.npy", mmap_mode="r")
    H = np.load(record / "h.npy", mmap_mode="r")
    arrs = {k: np.load(record / f"{k}.npy") for k in ("qlat", "q0", "h0", "up_ptr", "up_idx", "params", "link")}
    nseg = Q.shape[0]
    cnt = np.zeros((nseg, len(CNT)), dtype=np.int64)
    fs = np.zeros((nseg, len(FSUM)))
    pk = np.full((nseg, len(PK)), np.nan)
    mm = np.zeros((nseg, len(MM)))
    hist = np.zeros((nseg, 2, NB), dtype=np.int32)
    t0 = time.perf_counter()
    replay(np.asarray(Q), np.asarray(H), arrs["qlat"], arrs["q0"], arrs["h0"], arrs["up_ptr"], arrs["up_idx"],
           np.ascontiguousarray(arrs["params"]), np.float32(meta["dt_s"]), bool(meta["assume_short_ts"]),
           int(meta["qts_subdivisions"]), np.float32(qj0), 3600 // int(meta["dt_s"]), cnt, fs, pk, mm, hist,
           corrected)
    wall = time.perf_counter() - t0
    return {"meta": meta, "cnt": cnt, "fs": fs, "pk": pk, "mm": mm, "hist": hist, "link": arrs["link"],
            "s0": arrs["params"][:, 7], "wall_s": wall,
            "q_hourly_last": np.asarray(Q[:, (3600 // meta["dt_s"]) - 1::3600 // meta["dt_s"]])}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--qj0", type=float, default=0.0)
    ap.add_argument("--corrected", action="store_true", help="port follows the corrected kernel")
    ap.add_argument("--compare-npz", type=Path, default=None,
                    help="run_troute.py output of the same configuration: q_hourly must match bitwise")
    args = ap.parse_args()
    r = run(args.record.resolve(), args.qj0, args.corrected)
    case = r["meta"]["case"]
    seg = pd.read_parquet(HERE / "build" / "inputs" / case / "segments.parquet")
    if not np.array_equal(seg["link"].to_numpy(), r["link"]):
        raise SystemExit("segment order differs from segments.parquet")
    same = None
    if args.compare_npz is not None and args.compare_npz.exists():
        ref = np.load(args.compare_npz)
        same = bool(np.array_equal(ref["q_hourly"], r["q_hourly_last"]) and np.array_equal(ref["link"], r["link"]))
    sc = slope_class(r["s0"].astype(np.float64))
    order = seg["order"].to_numpy().astype(int)
    orders = np.arange(1, order.max() + 1)
    hist_slope = np.stack([r["hist"][sc == c].sum(axis=0, dtype=np.int64) for c in range(4)])
    hist_order = np.stack([r["hist"][order == o].sum(axis=0, dtype=np.int64) for o in orders])
    import numba
    info = {**r["meta"], "qj0": args.qj0, "port_corrected": args.corrected, "replay_wall_s": round(r["wall_s"], 1),
            "numba": numba.__version__, "matches_published_run_hourly_bitwise": same}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, cnt=r["cnt"], fsum=r["fs"], pk=r["pk"], mm=r["mm"], hist_slope=hist_slope,
                        hist_order=hist_order, orders=orders, link=r["link"], cnt_names=np.array(CNT),
                        fsum_names=np.array(FSUM), pk_names=np.array(PK), mm_names=np.array(MM),
                        hist_vars=np.array([v[0] for v in HV]), hist_lo=np.array([v[1] for v in HV]),
                        hist_hi=np.array([v[2] for v in HV]), hist_nb=np.array([v[3] for v in HV]),
                        info=json.dumps(info))
    c = r["cnt"].sum(axis=0)
    print(f"ok      replayed {case} dt={info['dt_s']} sts={info['assume_short_ts']}: {c[0]} segment-steps in "
          f"{r['wall_s']:.1f} s; |port - T-Route| rel > 1e-6: {c[17]}, > 1e-3: {c[18]}; bitwise equal "
          f"{c[19] / c[0]:.4f}; max abs err {r['fs'][:, 18].max():.3g} m3/s; published-run match: {same}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
