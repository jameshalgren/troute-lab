"""Mechanism checks for the assume_short_ts results (README "Mechanism checks").

Writes results/mechanism.json, results/fig_mechanism_cascade.png and
results/fig_mass_balance.png. Needs the runs and build from run.sh.

A  Kernel port (mc_port.py) validated against T-Route's own outputs (mainstem segments
   replayed from their upstream neighbour's native-resolution outflow). A direct
   comparison with the compiled kernel through ctypes is not reproducible, because the
   unpatched kernel's output depends on uninitialized memory (E); qj_patch_compare.py
   does it against the patched kernel.
B  Linear Muskingum-Cunge (constant Km, X; T-Route's coefficient formulas) for one
   reach and cascades of 10 and 50 reaches, smooth and sharp inflow: measured mean
   delay, variance, peak, volume vs the exact moments of the discrete schemes.
C  T-Route's kernel (port) on uniform 40-segment cascades, a sloped and a slope-floor
   (So = 1e-5) channel with Potomac mainstem geometry: centroid shift vs predictions.
D  Mass balance: per-segment volume balance of the Potomac runs (in - out, from
   T-Route's volumes), and its decomposition on mainstem segments into the two terms of
   the kernel's discrete storage equation.
E  Headwater segments that differ between settings, and the kernel's uninitialized
   Qj_0 read.
F  Network centroid-shift predictors: as in analyze.py; lateral inflow excluded; and
   with an inflow-weighted effective Km*X.
G  Why the Potomac outlet responds slowly (mainstem travel time by channel class).
H  The steep front ("step") in the outlet hydrographs.

    uv run python mechanism.py            # JOBS=n parallel replays (default 4)
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.special import gammainc  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze as A  # noqa: E402
import make_inputs as MI  # noqa: E402
import mc_port as M  # noqa: E402

CASE = "potomac_storm"
OUT = HERE / "results"
GEO_COLS = ("dx", "bw", "tw", "twcc", "n", "ncc", "cs", "s0")
LITTLE_FALLS_KM = 192.578        # USGS 01646500 (RouteLink `gages`), distance above the outlet
STORM_CENTROID_H = MI.STORM_START_H + MI.STORM_SHAPE * MI.STORM_SCALE_H
BLUE, ORANGE, GRAY, INK, MUTED = A.BLUE, A.ORANGE, A.GRAY, A.INK, A.MUTED


def r4(x):
    return A.r4(x)


# ------------------------------------------------------------------ shared data
def network():
    seg = pd.read_parquet(A.INPUTS / CASE / "segments.parquet")
    p = A.channel_params(CASE, seg["link"].to_numpy())
    tree = A.build_tree(seg)
    down = tree["down"]
    nup = np.bincount(down[down >= 0], minlength=len(seg))
    ql = MI.storm_series(seg["length_km"].to_numpy(), int(json.loads(
        (A.INPUTS / CASE / "case.json").read_text())["hours"])).astype(np.float64)
    return seg, p, tree, down, nup, ql


def mainstem(run, seg):
    mi = run["main_idx"]
    o = np.argsort(-seg["dist_to_outlet_km"].to_numpy()[mi])
    return mi[o], run["main_q"][o].astype(np.float64), run["main_depth"][o]


# ------------------------------------------------------------------ inflows and moments
def inflow(dt, hours, base, vol, shape, scale_h, start_h=2.0):
    n = int(round(hours * 3600 / dt))
    edges = np.arange(n + 1) * dt / 3600.0 - start_h
    cdf = gammainc(shape, np.clip(edges, 0, None) / scale_h)
    return np.concatenate([[base], base + vol * np.diff(cdf) / dt])   # index 0 = initial state


def moments(q, base, dt):
    e = q - base
    t = np.arange(q.size) * dt
    v = e.sum()
    m = (e * t).sum() / v
    return v * dt, m, (e * (t - m) ** 2).sum() / v


def peak(q, dt):
    j = int(np.argmax(q))
    off = 0.0
    if 0 < j < q.size - 1:
        a, b, c = q[j - 1], q[j], q[j + 1]
        den = a - 2 * b + c
        if den < 0:
            off = float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    return float(q[j]), (j + off) * dt


# ------------------------------------------------------------------ A: port validation
def _replay(job):
    """Replay one mainstem segment from its upstream neighbour's native outflow.
    Returns arrays of the port's outflow and the storage-equation sums."""
    dt, sts, inflow_q, qd0, qu0, ql_hourly, geo, collect = job
    sph = 3600 // dt
    n = inflow_q.size
    out = np.empty(n)
    qdp, iprev, hp = qd0, qu0, 0.0
    s_di = s_do = vin = vout = 0.0
    nclip = 0
    for j in range(n):
        ql = float(ql_hourly[j // sph])
        qup = iprev
        quc = float(inflow_q[j]) if not sts else iprev
        qd, h, d = M.mc(float(dt), qup, quc, qdp, ql, *geo, hp)
        nclip += d["clip"] > 0
        if collect:
            s_di += d["Km"] * d["X"] * (quc - qup)
            s_do += d["Km"] * (1 - d["X"]) * (qd - qdp)
            vin += dt * ((qup + quc) / 2 + ql)
            vout += dt * (qdp + qd) / 2
        out[j] = qd
        qdp, hp, iprev = qd, h, float(inflow_q[j])
    return out, {"sum_KX_dI_m3": s_di, "sum_K1X_dO_m3": s_do, "port_in_minus_out_m3": vin - vout,
                 "n_negative_flow_guard": int(nclip)}


def replay_mainstem(seg, p, down, nup, ql, dt, jobs, pick=None):
    runs = {s: mainstem(A.load(CASE, dt, bool(s)), seg) for s in (0, 1)}
    mi = runs[0][0]
    cands = [k for k in range(1, len(mi)) if nup[mi[k]] == 1 and down[mi[k - 1]] == mi[k]]
    if pick is not None:
        cands = [cands[j] for j in np.linspace(0, len(cands) - 1, pick).astype(int)]
    q0 = seg["q0"].to_numpy()
    jobs_list, meta = [], []
    for k in cands:
        i = mi[k]
        geo = [float(p.iloc[i][c]) for c in GEO_COLS]
        for s in (0, 1):
            jobs_list.append((dt, s, runs[s][1][k - 1], float(q0[i]), float(q0[mi[k - 1]]), ql[i], geo, True))
            meta.append((k, i, s))
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        res = list(ex.map(_replay, jobs_list, chunksize=4))
    return runs, meta, res


# ------------------------------------------------------------------ B: linear MC
def coeffs(K, X, dt):
    km = max(dt, K)
    d = km * (1 - X) + dt / 2
    return (km * X + dt / 2) / d, (dt / 2 - km * X) / d, (km * (1 - X) - dt / 2) / d, km


def linear_cascade(I, N, K, X, dt, sts):
    c1, c2, c3, _ = coeffs(K, X, dt)
    up = I.astype(float)
    nclip = 0
    for _ in range(N):
        o = np.empty_like(up)
        o[0] = up[0]
        for n in range(1, up.size):
            quc = up[n - 1] if sts else up[n]
            s = c1 * up[n - 1] + c2 * quc + c3 * o[n - 1]
            if s < 0:                                    # T-Route's guard (C4 = 0)
                nclip += 1
                s = max(c1 * up[n - 1] + c2 * quc, c1 * up[n - 1] + c3 * o[n - 1])
            o[n] = s
        up = o
    return up, nclip


def analytic(K, X, dt, sts):
    """Exact per-reach mean delay (s) and variance (s^2) of the discrete scheme, from the
    generating function (C2 + C1 w)/(1 - C3 w) (False) or (C1 + C2) w/(1 - C3 w) (True)."""
    c1, c2, c3, _ = coeffs(K, X, dt)
    r = c3 / (1 - c3)
    if sts:
        mean, var = 1 + r, r * (1 + r)
    else:
        p_ = c1 / (c1 + c2)
        mean, var = p_ + r, p_ * (1 - p_) + r * (1 + r)
    return mean * dt, var * dt * dt


def linear_tests():
    base, vol = 100.0, 500 * 3600 * 6.0
    rows = []
    configs = [(3600, 0.4, 60), (3600, 0.4, 300), (3600, 0.4, 900), (3600, 0.25, 300),
               (3600, 0.5, 300), (900, 0.4, 3600)]
    for wave, (shape, scale) in {"smooth": (3, 4.0), "sharp": (3, 0.25)}.items():
        for K, X, dt in configs:
            for N in (1, 10, 50):
                hours = 48 + 3 * N * max(K, dt) / 3600 + 15 * scale
                I = inflow(dt, hours, base, vol, shape, scale)
                vin, mi_, vi = moments(I, base, dt)
                res = {}
                for sts in (False, True):
                    o, ncl = linear_cascade(I, N, K, X, dt, sts)
                    v, m, var = moments(o, base, dt)
                    pk, tp = peak(o, dt)
                    am, av = analytic(K, X, dt, sts)
                    res[sts] = dict(vol=v / vin, mean=(m - mi_) / N, mean_an=am, var=(var - vi) / N, var_an=av,
                                    pk=pk, tp=tp, clip=ncl)
                F, T = res[False], res[True]
                rows.append({
                    "wave": wave, "K_h": K / 3600, "X": X, "dt_s": dt, "N": N,
                    "Courant_dt_over_K": round(dt / K, 4),
                    "shift_per_reach_s": round(T["mean"] - F["mean"], 2),
                    "dt/2-Km*X_s": round(dt / 2 - max(dt, K) * X, 2),
                    "mean_per_reach_false_s": round(F["mean"], 2), "analytic_false_s": round(F["mean_an"], 2),
                    "mean_per_reach_true_s": round(T["mean"], 2), "analytic_true_s": round(T["mean_an"], 2),
                    "var_per_reach_false_h2": round(F["var"] / 3600 ** 2, 4), "analytic_var_false_h2": round(F["var_an"] / 3600 ** 2, 4),
                    "var_per_reach_true_h2": round(T["var"] / 3600 ** 2, 4), "analytic_var_true_h2": round(T["var_an"] / 3600 ** 2, 4),
                    "peak_excess_true_over_false_pct": round(100 * ((T["pk"] - base) / (F["pk"] - base) - 1), 2),
                    "peak_time_shift_h": round((T["tp"] - F["tp"]) / 3600, 3),
                    "volume_ratio_false": round(F["vol"], 6), "volume_ratio_true": round(T["vol"], 6),
                    "negative_flow_guard_steps_false": F["clip"], "negative_flow_guard_steps_true": T["clip"],
                })
    return rows


# ------------------------------------------------------------------ C: kernel cascades
CASCADE_GEO = {"dx": 2000.0, "bw": 38.84, "tw": 64.73, "twcc": 194.18, "n": 0.05, "ncc": 0.10, "cs": 0.1854}


def kernel_cascade(I, N, geo, dt, sts):
    T = I.size
    out = np.empty((N, T))
    kx = np.full((N, T), np.nan)
    km = np.full((N, T), np.nan)
    xx = np.full((N, T), np.nan)
    up = I.astype(float)
    nclip = 0
    for r in range(N):
        o = np.empty(T)
        o[0] = up[0]
        hp = 0.0
        for n in range(1, T):
            qd, h, d = M.mc(float(dt), up[n - 1], up[n - 1] if sts else up[n], o[n - 1], 0.0, *geo, hp)
            nclip += d["clip"] > 0
            kx[r, n], km[r, n], xx[r, n] = d["Km"] * d["X"], d["Km"], d["X"]
            o[n], hp = qd, h
        out[r] = o
        up = o
    return out, kx, km, xx, nclip


def _cascade_job(args):
    s0, dt = args
    N, base = 40, 150.0
    geo = [CASCADE_GEO[c] for c in GEO_COLS[:-1]] + [s0]
    hours = 60 + (40 if s0 > 1e-4 else 160)
    I = inflow(dt, hours, base, 1500 * 3600 * 8.0, 3, 4.0)
    vin = moments(I, base, dt)[0]
    of, kxf, kmf, xf, cf = kernel_cascade(I, N, geo, dt, False)
    ot, _, _, _, ct = kernel_cascade(I, N, geo, dt, True)
    t = (np.arange(I.size) - 0.5) * dt
    rows = []
    pred_pk = pred_eff = 0.0
    for k in range(N):
        ik = I if k == 0 else of[k - 1]
        j = int(np.argmax(of[k]))
        pred_pk += dt / 2 - kxf[k, j]
        # inflow-weighted effective Km*X: -sum_n t_n Km X (I_n - I_{n-1}) / V_in (exact for
        # constant coefficients, where it equals Km*X)
        dI = np.diff(ik)
        v = (ik - base).sum() * dt
        pred_eff += dt / 2 + (t[1:] * kxf[k, 1:] * dI).sum() / v
        if k + 1 in (1, 10, 20, 40):
            vf, mf, _ = moments(of[k], base, dt)
            vt, mt, _ = moments(ot[k], base, dt)
            pf, tf = peak(of[k], dt)
            pt, tt = peak(ot[k], dt)
            rows.append({"N": k + 1, "centroid_shift_h": round((mt - mf) / 3600, 3),
                         "pred_at_false_peak_h": round(pred_pk / 3600, 3),
                         "pred_inflow_weighted_h": round(pred_eff / 3600, 3),
                         "peak_excess_true_over_false_pct": round(100 * ((pt - base) / (pf - base) - 1), 2),
                         "peak_time_shift_h": round((tt - tf) / 3600, 3),
                         "volume_ratio_false": round(vf / vin, 4), "volume_ratio_true": round(vt / vin, 4)})
    return {"s0": s0, "dt_s": dt, "segments": N, "dx_m": CASCADE_GEO["dx"], "base_m3s": base,
            "inflow": "gamma(3, 4 h) storm, 8 h x 1500 m3/s excess volume",
            "Km_range_h": [round(float(np.nanmin(kmf)) / 3600, 2), round(float(np.nanmax(kmf)) / 3600, 2)],
            "X_range": [round(float(np.nanmin(xf)), 3), round(float(np.nanmax(xf)), 3)],
            "negative_flow_guard_steps": {"false": int(cf), "true": int(ct)}, "by_N": rows,
            "_series": {"t_h": (np.arange(I.size) * dt / 3600).tolist(), "in": I.tolist(),
                        "false": of[-1].tolist(), "true": ot[-1].tolist()}}


# ------------------------------------------------------------------ D: mass balance
def segment_balance(seg, p, tree, down, ql):
    T = ql.shape[1] * 3600.0
    vlat = ql.sum(axis=1) * 3600.0
    storm = vlat - ql[:, 0] * T
    acc = storm.copy()
    for i in tree["topo"]:
        if down[i] >= 0:
            acc[down[i]] += acc[i]
    o = int(np.flatnonzero(seg["is_outlet"].to_numpy())[0])
    q0 = seg["q0"].to_numpy()
    floor = p["s0"].to_numpy() <= 1.0001e-5
    main = seg["mainstem"].to_numpy()
    out, losses = {}, {}
    for dt in A.DTS:
        d = {}
        for s, name in ((0, "false"), (1, "true")):
            r = A.load(CASE, dt, bool(s))
            v = r["volume_m3"]
            vup = np.zeros(len(seg))
            np.add.at(vup, down[down >= 0], v[down >= 0])
            loss = vup + vlat - v                      # in - out per segment (m3)
            losses[(dt, s)] = loss
            tot = loss.sum()
            srt = np.sort(loss)[::-1]
            d[name] = {
                "sum_segment_losses_pct_of_storm": r4(100 * tot / acc[o]),
                "outlet_event_balance": r4((v[o] - q0[o] * T) / acc[o]),
                "share_in_slope_floor_segments_pct": r4(100 * loss[floor].sum() / tot),
                "share_in_mainstem_pct": r4(100 * loss[main].sum() / tot),
                "share_in_top_1pct_segments_pct": r4(100 * srt[: len(srt) // 100].sum() / tot),
                "sum_of_gaining_segments_pct_of_storm": r4(100 * loss[loss < 0].sum() / acc[o]),
            }
        out[str(dt)] = d
    ck, _, bfd, _ = A.courant_np(A.load(CASE, 300, False)["depth_at_peak"], p, 300)
    l0 = losses[(300, 0)]
    top = np.argsort(-l0)[:10]
    out["top10_false_dt300"] = [{
        "link": int(seg["link"].iloc[i]), "order": int(seg["order"].iloc[i]), "mainstem": bool(main[i]),
        "s0": float(p["s0"].iloc[i]), "dx_m": float(p["dx"].iloc[i]),
        "peak_depth_over_bankfull": r4(A.load(CASE, 300, False)["depth_at_peak"][i] / bfd[i]),
        "share_of_network_loss_pct": r4(100 * l0[i] / l0.sum()),
        "loss_pct_of_upstream_storm": r4(100 * l0[i] / acc[i]),
        "loss_true_pct_of_upstream_storm": r4(100 * losses[(300, 1)][i] / acc[i])} for i in top]
    out["slope_floor_segments"] = {"n": int(floor.sum()), "share_of_segments": r4(floor.mean()),
                                   "share_of_channel_length": r4(p["dx"].to_numpy()[floor].sum() / p["dx"].sum())}
    out["definition"] = ("per segment: (sum of upstream segments' routed volume + lateral volume) - own routed "
                         "volume, native resolution, 40 days; every segment is back at baseflow, so storage "
                         "change is ~0 and the per-segment losses add up to the outlet deficit")
    return out, losses, acc


def decomposition_summary(seg, meta, res, losses, dt=300):
    rows = []
    for (k, i, s), (_, d) in zip(meta, res):
        rows.append({"k": k, "i": i, "s": s, "troute_loss": losses[(dt, s)][i], **d})
    df = pd.DataFrame(rows)
    out = {}
    for s, name in ((0, "false"), (1, "true")):
        x = df[df.s == s]
        out[name] = {
            "n_segments": int(len(x)),
            "sum_troute_loss_m3": float(f"{x.troute_loss.sum():.4g}"),
            "sum_port_in_minus_out_m3": float(f"{x.port_in_minus_out_m3.sum():.4g}"),
            "sum_KX_dI_m3": float(f"{x.sum_KX_dI_m3.sum():.4g}"),
            "sum_K1X_dO_m3": float(f"{x.sum_K1X_dO_m3.sum():.4g}"),
            "identity_residual_rel": float(f"{abs(x.port_in_minus_out_m3.sum() - x.sum_KX_dI_m3.sum() - x.sum_K1X_dO_m3.sum()) / max(abs(x.port_in_minus_out_m3.sum()), 1):.3g}"),
            "port_vs_troute_loss_rel": float(f"{abs(x.port_in_minus_out_m3.sum() - x.troute_loss.sum()) / max(abs(x.troute_loss.sum()), 1):.3g}"),
            "spearman_KX_dI_vs_troute_loss": r4(spearmanr(x.sum_KX_dI_m3, x.troute_loss).statistic) if s == 0 else None,
            "segments_with_negative_flow_guard": int((x.n_negative_flow_guard > 0).sum()),
            "negative_flow_guard_steps": int(x.n_negative_flow_guard.sum()),
        }
    out["identity"] = ("per step, D*qdc = C-weighted inputs gives dt/2(qup+quc) + ql*dt - dt/2(qdp+qdc) = "
                       "Km*X*(quc-qup) + Km*(1-X)*(qdc-qdp); summed over the event, in - out = "
                       "sum Km*X*dI + sum Km*(1-X)*dO, which is zero only if Km and X are constant. "
                       "With assume_short_ts = True, quc = qup and the first sum is identically zero.")
    return out, df


# ------------------------------------------------------------------ E: headwaters / Qj_0
def headwater_check(seg, p, down, nup, ql):
    head = nup == 0
    out = {"n_headwater_segments": int(head.sum()), "by_dt": {}}
    for dt in A.DTS:
        a, b = A.load(CASE, dt, True), A.load(CASE, dt, False)
        d = np.abs(a["q_hourly"] - b["q_hourly"]).max(axis=1)
        out["by_dt"][str(dt)] = {"n_differing_gt_1e-4_m3s": int((d[head] > 1e-4).sum()),
                                 "max_abs_diff_m3s": r4(d[head].max()),
                                 "max_abs_diff_pct_of_own_peak": r4(100 * (d[head] / np.maximum(b["peak_q"][head], 1e-6)).max())}
    link = seg["link"].to_numpy()
    i = int(np.flatnonzero(link == 22339871)[0])            # largest headwater difference, dt = 3600 s
    geo = [float(p.iloc[i][c]) for c in GEO_COLS]
    hrs = slice(24, 30)
    series = {}
    for init in (0.0, 1.0, 1000.0):
        qdp, hp, o = float(seg["q0"].iloc[i]), 0.0, []
        for j in range(30):
            q, h, _ = M.mc(3600.0, 0.0, 0.0, qdp, float(np.float32(ql[i, j])), *geo, hp, qj0_init=init)
            o.append(q)
            qdp, hp = q, h
        series[f"port_Qj0_init_{init:g}"] = [round(v, 3) for v in o[hrs]]
    series["troute_false"] = [round(float(v), 3) for v in A.load(CASE, 3600, False)["q_hourly"][i][hrs]]
    series["troute_true"] = [round(float(v), 3) for v in A.load(CASE, 3600, True)["q_hourly"][i][hrs]]
    out["example"] = {"link": 22339871, "dt_s": 3600, "hours_index": [24, 30],
                      "note": "headwater: qup = quc = 0 in both settings, so the settings cannot differ "
                              "through the inputs; the port reproduces both T-Route series by changing only "
                              "the starting value of Qj_0", **series}
    return out


# ------------------------------------------------------------------ F: network predictors
def depth_from_flow(q, p):
    """Normal depth (T-Route's Manning in hydraulic_geometry/secant2_h) for flows q (nseg, T)."""
    P = {k: p[k].to_numpy().astype(np.float64)[:, None] for k in p.columns}
    z = np.where(P["cs"] == 0, 1.0, 1.0 / np.where(P["cs"] == 0, 1.0, P["cs"]))
    bfd = np.where(P["bw"] > P["tw"], P["bw"] / 1e-5,
                   np.where(P["bw"] == P["tw"], P["bw"] / (2 * z), (P["tw"] - P["bw"]) / (2 * z)))

    def qman(h):
        hgt = np.maximum(h - bfd, 0)
        hlt = np.minimum(bfd, h)
        nw = (hgt > 0) & (P["twcc"] <= 0)
        hgt, hlt = np.where(nw, 0, hgt), np.where(nw, h, hlt)
        area = (P["bw"] + hlt * z) * hlt
        wp = P["bw"] + 2 * hlt * np.sqrt(1 + z * z)
        areac = P["twcc"] * hgt
        wpc = np.where(hgt > 0, P["twcc"] + 2 * hgt, 0)
        r = (area + areac) / (wp + wpc)
        return (wp + wpc) / (wp * P["n"] + wpc * P["ncc"]) * (area + areac) * r ** (2 / 3) * np.sqrt(P["s0"])

    lo, hi = np.zeros_like(q), np.full_like(q, 200.0)
    for _ in range(50):
        mid = (lo + hi) / 2
        big = qman(mid) > q
        hi, lo = np.where(big, mid, hi), np.where(big, lo, mid)
    return (lo + hi) / 2


def tree_shift(tree, delta, lateral_excluded):
    down, topo, L = tree["down"], tree["topo"], tree["L"]
    acc = L.copy()
    s = np.zeros_like(L) if lateral_excluded else L * delta
    for i in topo:
        dn = down[i]
        if dn >= 0:
            acc[dn] += acc[i]
            s[dn] += s[i] + acc[i] * delta[dn]
    return s / acc / 3600.0


def network_predictors(seg, p, tree, down):
    q0 = seg["q0"].to_numpy()
    o = int(np.flatnonzero(seg["is_outlet"].to_numpy())[0])
    i0 = np.zeros(len(seg))
    np.add.at(i0, down[down >= 0], q0[down >= 0])
    out = {}
    for dt in A.DTS:
        a, b = A.load(CASE, dt, True), A.load(CASE, dt, False)
        Q = b["q_hourly"].astype(np.float64)
        T = Q.shape[1]
        I = np.zeros_like(Q)
        np.add.at(I, down[down >= 0], Q[down >= 0])
        H = depth_from_flow(Q, p)
        rep = pd.DataFrame({k: np.repeat(p[k].to_numpy(), T) for k in p.columns})
        _, _, x, km, _, _ = A.mc_coefficients(Q.ravel().astype(np.float32), H.ravel().astype(np.float32), rep, dt)
        KX = (km * x).reshape(Q.shape).astype(np.float64)
        t = np.arange(1, T + 1) * 3600.0 - 1800.0
        dI = np.diff(np.concatenate([i0[:, None], I], axis=1), axis=1)
        VI = ((I - i0[:, None]) * 3600).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            kx_eff = np.where(VI > 0, -(t[None, :] * KX * dI).sum(axis=1) / VI, np.nan)
        d_eff = np.where(np.isfinite(kx_eff), dt / 2 - kx_eff, 0.0)
        _, _, xp, kmp, _, _ = A.mc_coefficients(b["peak_q"], b["depth_at_peak"], p, dt)
        d_pk = dt / 2 - kmp * xp
        th = np.arange(1, T + 1, dtype=float)

        def cen(r):
            e = np.clip(r["q_hourly"] - q0[:, None], 0, None)
            return (e * th).sum(axis=1) / np.where(e.sum(axis=1) > 0, e.sum(axis=1), np.nan)

        meas = cen(a) - cen(b)
        back = lambda r: (r["q_hourly"][:, -1] - q0) < 0.01 * (r["peak_q"] - q0)  # noqa: E731
        comp = back(a) & back(b) & np.isfinite(meas)
        d = {"outlet_measured_h": r4(meas[o])}
        for name, delta, lx in (("at_false_peak_as_analyze", d_pk, False),
                                ("at_false_peak_lateral_excluded", d_pk, True),
                                ("inflow_weighted_effective_lateral_excluded", d_eff, True)):
            pr = tree_shift(tree, delta, lx)
            d[name] = {"outlet_predicted_h": r4(pr[o]),
                       "regression_slope_measured_on_predicted": r4(np.polyfit(pr[comp], meas[comp], 1)[0]),
                       "spearman": r4(spearmanr(pr[comp], meas[comp]).statistic),
                       "median_abs_error_h": r4(np.median(np.abs(meas - pr)[comp]))}
        out[str(dt)] = d
    out["note"] = ("lateral_excluded: lateral inflow enters through C4 = ql*dt/D, identical in both settings, "
                   "so a segment's own shift applies only to water arriving from upstream (headwaters: none). "
                   "inflow_weighted_effective: Km*X replaced by -sum_t t*Km*X*dI/V_in from hourly False flows "
                   "(depth by inverting T-Route's Manning relation), which equals Km*X for constant "
                   "coefficients and includes the hysteresis of Km(outflow) against the inflow.")
    return out


# ------------------------------------------------------------------ G, H: travel time, front
def travel_and_front(seg, p):
    out = {}
    for dt in (60, 300):
        b, a = A.load(CASE, dt, False), A.load(CASE, dt, True)
        mi, Qf, Hf = mainstem(b, seg)
        _, Qt, _ = mainstem(a, seg)
        pm = p.iloc[mi]
        dist = seg["dist_to_outlet_km"].to_numpy()[mi]
        dx, s0 = pm["dx"].to_numpy(), pm["s0"].to_numpy()
        ck, _, bfd, _ = A.courant_np(b["depth_at_peak"][mi], pm, dt)
        K = dx / ck / 3600
        h0 = depth_from_flow(seg["q0"].to_numpy()[mi][:, None].astype(np.float64), pm)[:, 0]
        ck0, _, _, _ = A.courant_np(h0.astype(np.float32), pm, dt)
        floor = s0 <= 1.0001e-5
        below = dist < LITTLE_FALLS_KM + 0.01
        lf = int(np.argmin(np.abs(dist - LITTLE_FALLS_KM)))
        o = len(mi) - 1
        rate = np.diff(Qf, axis=1) / (dt / 3600.0)
        d = {
            "mainstem_segments": int(len(mi)), "mainstem_km": r4(dx.sum() / 1e3),
            "sum_dx_over_ck_at_false_peak_h": r4(K.sum()),
            "slope_floor": {"segments": int(floor.sum()), "km": r4(dx[floor].sum() / 1e3), "sum_K_h": r4(K[floor].sum()),
                            "median_ck_at_peak_ms": r4(np.median(ck[floor])),
                            "median_ck_at_baseflow_ms": r4(np.median(ck0[floor])),
                            "median_peak_depth_over_bankfull": r4(np.median(b["depth_at_peak"][mi][floor] / bfd[floor]))},
            "other": {"segments": int((~floor).sum()), "km": r4(dx[~floor].sum() / 1e3), "sum_K_h": r4(K[~floor].sum()),
                      "median_ck_at_peak_ms": r4(np.median(ck[~floor])),
                      "median_ck_at_baseflow_ms": r4(np.median(ck0[~floor])),
                      "median_peak_depth_over_bankfull": r4(np.median(b["depth_at_peak"][mi][~floor] / bfd[~floor]))},
            "below_little_falls": {"segments": int(below.sum()), "km": r4(dx[below].sum() / 1e3),
                                   "share_slope_floor": r4(floor[below].mean()), "sum_K_h": r4(K[below].sum())},
            "outlet_baseflow_depth_m": r4(h0[o]), "outlet_bankfull_depth_m": r4(bfd[o]),
            "outlet_peak_depth_m": r4(b["depth_at_peak"][mi][o]),
            "peak_time_h_after_storm_centroid": {
                "little_falls_false": r4(b["peak_t_s"][mi][lf] / 3600 - STORM_CENTROID_H),
                "little_falls_true": r4(a["peak_t_s"][mi][lf] / 3600 - STORM_CENTROID_H),
                "outlet_false": r4(b["peak_t_s"][mi][o] / 3600 - STORM_CENTROID_H),
                "outlet_true": r4(a["peak_t_s"][mi][o] / 3600 - STORM_CENTROID_H)},
            "peak_m3s": {"little_falls_false": r4(b["peak_q"][mi][lf]), "little_falls_true": r4(a["peak_q"][mi][lf])},
        }
        if dt == 300:
            j = int(np.argmax(rate[o]))
            front = []
            for k in (o - 120, o - 60, o - 30, o):
                jj = int(np.argmax(rate[k]))
                front.append({"dist_km": r4(dist[k]), "max_rise_m3s_per_h": r4(rate[k, jj]),
                              "time_h": r4((jj + 1) * dt / 3600)})
            d["front"] = {
                "outlet_max_rise_m3s_per_h": r4(rate[o, j]), "outlet_time_of_max_rise_h": r4((j + 1) * dt / 3600),
                "outlet_flow_6h_before_and_after_m3s": [r4(Qf[o, max(j - 72, 0)]), r4(Qf[o, min(j + 72, Qf.shape[1] - 1)])],
                "first_hump_max_before_front_m3s": r4(Qf[o, : j - 72].max()),
                "flow_minimum_between_hump_and_front_m3s": r4(Qf[o, int(np.argmax(Qf[o, : j - 72])): j].min()),
                "along_mainstem": front,
                "same_front_at_dt60": None}
            b60 = A.load(CASE, 60, False)
            _, Q60, _ = mainstem(b60, seg)
            r60 = np.diff(Q60[o]) / (60 / 3600.0)
            d["front"]["same_front_at_dt60"] = {"outlet_max_rise_m3s_per_h": r4(r60.max()),
                                                "time_h": r4((int(np.argmax(r60)) + 1) * 60 / 3600)}
        out[str(dt)] = d
    return out


# ------------------------------------------------------------------ figures
def style(ax):
    A.style(ax)


def fig_cascade(lin, casc, path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))
    ax = axes[0]
    style(ax)
    sm = [r for r in lin if r["wave"] == "smooth"]
    x = np.array([r["dt/2-Km*X_s"] for r in sm]) / 3600
    y = np.array([r["shift_per_reach_s"] for r in sm]) / 3600
    lim = [min(x.min(), y.min()) * 1.1, max(x.max(), y.max()) * 1.1 + 0.02]
    ax.plot(lim, lim, color=GRAY, lw=1, ls=(0, (3, 2)))
    ax.plot(x, y, "o", ms=7, color=BLUE, mec="white", mew=1.5, label="smooth inflow (all N)")
    sh = [r for r in lin if r["wave"] == "sharp" and r["N"] == 50]
    ax.plot(np.array([r["dt/2-Km*X_s"] for r in sh]) / 3600, np.array([r["shift_per_reach_s"] for r in sh]) / 3600,
            "s", ms=7, color=ORANGE, mec="white", mew=1.5, label="sharp inflow, N = 50")
    ax.set_xlabel("dt/2 − Km·X (h)", fontsize=9, color=INK)
    ax.set_ylabel("measured mean-delay shift per reach,\nTrue − False (h)", fontsize=9, color=INK)
    ax.set_title("Linear MC: shift per reach = dt/2 − Km·X", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8)
    ax = axes[1]
    style(ax)
    for c, ls in zip(casc, ("-", "-")):
        if c["dt_s"] != 300:
            continue
        lab = "So = 1e-5 (slope floor)" if c["s0"] < 1e-4 else f"So = {c['s0']:g}"
        col = ORANGE if c["s0"] < 1e-4 else BLUE
        N = [r["N"] for r in c["by_N"]]
        ax.plot(N, [r["centroid_shift_h"] for r in c["by_N"]], color=col, lw=2, marker="o", ms=6, label=f"{lab}: measured")
        ax.plot(N, [r["pred_inflow_weighted_h"] for r in c["by_N"]], color=col, lw=1.2, ls=(0, (3, 2)))
        ax.plot(N, [r["pred_at_false_peak_h"] for r in c["by_N"]], color=col, lw=1.2, ls=(0, (1, 2)))
    ax.axhline(0, color="#b5b4ad", lw=0.8)
    ax.set_xlabel("segments in cascade", fontsize=9, color=INK)
    ax.set_ylabel("centroid shift True − False (h)", fontsize=9, color=INK)
    ax.set_title("T-Route kernel, dt = 300 s\nsolid: measured · dashed: inflow-weighted Km·X · dotted: Km·X at peak",
                 fontsize=9, color=INK)
    ax.legend(frameon=False, fontsize=8)
    ax = axes[2]
    style(ax)
    c = next(c for c in casc if c["s0"] < 1e-4 and c["dt_s"] == 300)
    s = c["_series"]
    ax.plot(s["t_h"], s["in"], color=GRAY, lw=1.2, ls=(0, (3, 2)), label="inflow")
    ax.plot(s["t_h"], s["false"], color=BLUE, lw=2, label="False, after 40 segments")
    ax.plot(s["t_h"], s["true"], color=ORANGE, lw=2, label="True, after 40 segments")
    ax.set_xlabel("hours", fontsize=9, color=INK)
    ax.set_ylabel("flow (m³/s)", fontsize=9, color=INK)
    v = c["by_N"][-1]
    ax.set_title(f"So = 1e-5 cascade, dt = 300 s: volume out/in False {v['volume_ratio_false']:.2f}, "
                 f"True {v['volume_ratio_true']:.2f}", fontsize=9, color=INK)
    ax.legend(frameon=False, fontsize=8)
    fig.suptitle("Mechanism checks: assume_short_ts = True (short-time-step assumption on) vs False",
                 fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_mass(bal, dec_df, path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    style(ax)
    for name, col, lab in (("false", BLUE, "False: current-step inflow (T-Route config default)"),
                           ("true", ORANGE, "True: short-time-step assumption on (WRF-Hydro/NWM)")):
        ax.plot(A.DTS, [bal[str(dt)][name]["outlet_event_balance"] for dt in A.DTS], color=col, lw=2, marker="o",
                ms=7, label=lab)
    ax.axhline(1, color="#b5b4ad", lw=0.8)
    ax.set_xscale("log")
    ax.set_xticks(A.DTS, [str(d) for d in A.DTS])
    ax.set_xlabel("routing timestep dt (s)", fontsize=9, color=INK)
    ax.set_ylabel("outlet event volume / storm volume", fontsize=9, color=INK)
    ax.set_title("Potomac outlet volume balance", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8)
    ax = axes[1]
    style(ax)
    x = dec_df[dec_df.s == 0]
    ax.plot(x.sum_KX_dI_m3 / 1e6, x.troute_loss / 1e6, "o", ms=6, color=BLUE, mec="white", mew=1, alpha=0.9,
            label="False")
    y = dec_df[dec_df.s == 1]
    ax.plot(y.sum_KX_dI_m3 / 1e6, y.troute_loss / 1e6, "o", ms=6, color=ORANGE, mec="white", mew=1, alpha=0.9,
            label="True (Σ Km·X·ΔI ≡ 0)")
    lim = [min(0, float(x.troute_loss.min()) / 1e6), float(x.sum_KX_dI_m3.max()) / 1e6 * 1.05]
    ax.plot(lim, lim, color=GRAY, lw=1, ls=(0, (3, 2)))
    ax.set_xlabel("Σ Km·X·ΔI over the event (10⁶ m³)", fontsize=9, color=INK)
    ax.set_ylabel("segment volume lost in T-Route, in − out (10⁶ m³)", fontsize=9, color=INK)
    ax.set_title("Mainstem segments, dt = 300 s: loss = inflow-storage term", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ------------------------------------------------------------------ main
def main() -> int:
    jobs = int(os.environ.get("JOBS", "4"))
    seg, p, tree, down, nup, ql = network()
    res = {"case": CASE}

    res["B_linear"] = linear_tests()
    print("ok      B linear MC tests")

    with ProcessPoolExecutor(max_workers=jobs) as ex:
        casc = list(ex.map(_cascade_job, [(2e-3, 300), (1e-5, 300), (2e-3, 60), (1e-5, 60)]))
    res["C_kernel_cascades"] = [{k: v for k, v in c.items() if k != "_series"} for c in casc]
    print("ok      C kernel cascades")

    bal, losses, _ = segment_balance(seg, p, tree, down, ql)
    runs, meta, rep = replay_mainstem(seg, p, down, nup, ql, 300, jobs)
    dec, dec_df = decomposition_summary(seg, meta, rep, losses)
    # port vs T-Route on the replayed mainstem segments
    errs = {0: [], 1: []}
    for (k, i, s), (q, _) in zip(meta, rep):
        tq = runs[s][1][k]
        errs[s].append(np.max(np.abs(q - tq)) / tq.max())
    res["A_port_vs_troute_mainstem_replay"] = {
        "dt_s": 300, "n_segments": len(errs[0]),
        "max_rel_diff_of_peak": {"false": float(f"{max(errs[0]):.3g}"), "true": float(f"{max(errs[1]):.3g}")},
        "median_rel_diff_of_peak": {"false": float(f"{np.median(errs[0]):.3g}"), "true": float(f"{np.median(errs[1]):.3g}")}}
    res["D_mass_balance"] = {"network": bal, "mainstem_decomposition_dt300": dec}
    print("ok      D mass balance", res["A_port_vs_troute_mainstem_replay"]["max_rel_diff_of_peak"])

    res["E_headwaters_and_Qj0"] = headwater_check(seg, p, down, nup, ql)
    print("ok      E headwaters")
    res["F_network_predictors"] = network_predictors(seg, p, tree, down)
    print("ok      F network predictors")
    res["G_H_travel_time_and_front"] = travel_and_front(seg, p)
    print("ok      G/H travel time and front")

    fig_cascade(res["B_linear"], casc, OUT / "fig_mechanism_cascade.png")
    fig_mass(bal, dec_df, OUT / "fig_mass_balance.png")
    (OUT / "mechanism.json").write_text(json.dumps(res, indent=2) + "\n")
    print("ok      results/mechanism.json, fig_mechanism_cascade.png, fig_mass_balance.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
