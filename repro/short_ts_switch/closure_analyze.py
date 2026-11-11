"""Summarize the closure diagnostics (closure_runs.py) -> results/closure/summary.json + figures.

    uv run --with numba==0.61.2 python closure_analyze.py

Reads results/closure/{patched,unpatched}/<case>/dt<dt>_sts<0|1>.npz (closure_replay.py)
and results/closure/jobs/*.json. Reports, per case, dt and setting:
- replay fidelity: the port against the patched T-Route, and the number of kernel calls
  whose outflow the unpatched T-Route computed differently; the two T-Route trajectories
  compared step by step. Since 2026-10-09 "patched" is the corrected kernel
  (../kernel_fixes/patches/0001-0007, the default build; replayed with the port's
  corrected mode) and "unpatched" the d29f663 kernel (build/unpatched_kernel; replayed
  with Qj_0 = 0 on entry, so it does not reproduce the kernel's uninitialized read of Qj_0). Before
  2026-10-09 "patched" meant the Qj-only diagnostic patch and the published runs were
  unpatched;
- the closure's values over all segment-steps (after the first hour) and at each
  segment's peak (Km, dx/Ck, X final and unclamped, C, D, C1..C4), by slope class, by
  stream order and in-bank vs overbank; fractions with Km = dt, X on the 0.25 floor, X at
  the 0.5 cap, C2 < 0, C3 < 0, negative-flow guard; how negative the unclamped X gets;
- Potomac: where the volume loss of the False runs arises (summation by parts of the
  kernel's storage identity, by closure regime, and the water the negative-flow guard
  adds), and how the first-moment shift of the short-time-step assumption splits
  by regime;
- cross-check against repro/diffusive_mainstem's per-segment screening flags (optional:
  skipped if that experiment has not been run).
Quantiles over segment-steps come from histograms (0.05-decade bins for Km, dx/Ck, C, D;
0.005 for X), interpolated within bins; minima / maxima and at-peak values are exact.
Diagnostics come from the patched replay (the published runs); the unpatched replay is
used only for the difference counts and for the loss decomposition of the unpatched runs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import xarray as xr  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze as A  # noqa: E402
import closure_replay as CR  # noqa: E402  (names and bins; importing it needs numba)
import make_inputs as MI  # noqa: E402
from run_experiment import CASES, DTS  # noqa: E402

OUT = HERE / "results" / "closure"
SKEL = HERE.parent / "diffusive_mainstem" / "results" / "segments_conus.parquet"
INK, MUTED = A.INK, A.MUTED
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
RAMP = A.RAMP
REC300 = HERE / "build" / "closure_runs" / "patched" / "potomac_storm"


def r(x, nd=4):
    if x is None:
        return None
    x = float(x)
    if not np.isfinite(x):
        return None
    return float(f"{x:.{nd}g}")


def load(build, case, dt, sts):
    z = np.load(OUT / build / case / f"dt{dt}_sts{sts}.npz")
    d = {k: z[k] for k in z.files}
    d["info"] = json.loads(str(z["info"]))
    for key, names in (("cnt", "cnt_names"), ("fsum", "fsum_names"), ("pk", "pk_names"), ("mm", "mm_names")):
        d[key + "_"] = {str(n): d[key][:, i] for i, n in enumerate(d[names])}
    return d


# ------------------------------------------------------------------ histogram helpers
def hslice(h, var):
    i = [v[0] for v in CR.HV].index(var)
    return h[..., CR.HOFF[i]:CR.HOFF[i + 1]], CR.HV[i]


def hquant(counts, spec, qs=(5, 50, 95)):
    _, lo, hi, nb = spec
    c = np.asarray(counts, dtype=float)
    tot = c.sum()
    if tot <= 0:
        return {f"p{q}": None for q in qs}
    cum = np.cumsum(c) / tot
    edges = np.linspace(lo, hi, nb + 1)
    out = {}
    for q in qs:
        k = int(np.searchsorted(cum, q / 100))
        prev = cum[k - 1] if k > 0 else 0.0
        f = (q / 100 - prev) / max(cum[k] - prev, 1e-300)
        v = edges[k] + f * (edges[k + 1] - edges[k])
        out[f"p{q}"] = v
    return out


def dist(counts_all, var, exact_min=None, exact_max=None, log=True):
    h, spec = hslice(counts_all, var)
    q = hquant(h, spec)
    f = (lambda v: 10 ** v) if log else (lambda v: v)
    d = {k: r(f(v)) if v is not None else None for k, v in q.items()}
    if exact_min is not None:
        d["min"] = r(exact_min)
    if exact_max is not None:
        d["max"] = r(exact_max)
    d["n"] = int(h.sum())
    return d


def frac(cnt, key, base="steps", mask=None):
    m = slice(None) if mask is None else mask
    den = cnt[base][m].sum()
    return r(cnt[key][m].sum() / den) if den else None


def pkq(a, qs=(5, 50, 95)):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    if not a.size:
        return {}
    return {**{f"p{q}": r(np.percentile(a, q)) for q in qs}, "min": r(a.min()), "max": r(a.max())}


# ------------------------------------------------------------------ closure block
REG = ["clamp", "floor", "both", "cap", "c2neg", "c3neg", "over", "guard", "x1_floor0", "x1_cap", "D_gt_half"]


def closure_block(z, sc, order, orders):
    c, f, pk, mm = z["cnt_"], z["fsum_"], z["pk_"], z["mm_"]
    hs, ho = z["hist_slope"], z["hist_order"]
    hall = hs.sum(axis=0)                      # (2, NB): in-bank, overbank
    tot = hall.sum(axis=0)
    out = {"segment_steps": int(c["steps"].sum()), "segments": int(len(sc)),
           "fractions_of_segment_steps": {k: frac(c, k) for k in REG},
           "fractions_of_routed_volume": {k: r(f[f"vol_{k}"].sum() / f["vol"].sum())
                                          for k in ("clamp", "floor", "both", "over")},
           "negative_flow_guard_steps": int(c["guard"].sum()),
           "negative_flow_guard_steps_with_X_at_cap": int(c["guard_at_cap"].sum()),
           "segments_with_guard": int((c["guard"] > 0).sum()),
           "secant_retries": int(c["retries"].sum()),
           "mean_secant_iterations": r(c["iterations"].sum() / c["active"].sum())}
    out["distributions_all_steps"] = {
        "Km_s": dist(tot, "log10_Km_s", np.nanmin(mm["min_Km"]), np.nanmax(mm["max_Km"])),
        "dx_over_Ck_s": dist(tot, "log10_dx_over_Ck_s", np.nanmin(mm["min_dx_over_Ck"]),
                             np.nanmax(mm["max_dx_over_Ck"])),
        "C": dist(tot, "log10_C", np.nanmin(mm["min_C"]), np.nanmax(mm["max_C"])),
        "D": dist(tot, "log10_D", None, np.nanmax(mm["max_D"])),
        "X_final": dist(tot, "X2", log=False),
        "X_unclamped_min": r(np.nanmin(mm["min_X2_raw"])),
        "X1_unclamped_min_max": [r(np.nanmin(mm["min_X1_raw"])), r(np.nanmax(mm["max_X1_raw"]))],
        "max_depth_over_bankfull": r(np.nanmax(mm["max_h_over_bfd"])),
    }
    # unclamped X where the floor binds: D > 1 (X2_raw = 1/2 - D/4)
    hD, spec = hslice(tot, "log10_D")
    k1 = int(round((0 - spec[1]) / (spec[2] - spec[1]) * spec[3]))
    qf = hquant(hD[k1:], ("", 0.0, spec[2], spec[3] - k1))
    out["X_unclamped_where_floored"] = {k: r(0.5 - 10 ** v / 4) for k, v in qf.items()}
    out["X_unclamped_where_floored"]["min"] = r(np.nanmin(mm["min_X2_raw"]))
    # in-bank vs overbank
    ib = {}
    for name, ov in (("inbank", 0), ("overbank", 1)):
        n = int(c["over"].sum() if ov else c["active"].sum() - c["over"].sum())
        ov_keys = {"clamp": "over_clamp", "floor": "over_floor", "c2neg": "over_c2neg", "both": "over_both"}
        fr = {}
        for k, kk in ov_keys.items():
            num = c[kk].sum() if ov else c[k].sum() - c[kk].sum()
            fr[k] = r(num / n) if n else None
        ib[name] = {"segment_steps": n, "fractions": fr,
                    "Km_s": dist(hall[ov], "log10_Km_s"), "D": dist(hall[ov], "log10_D"),
                    "X_final": dist(hall[ov], "X2", log=False), "C": dist(hall[ov], "log10_C")}
    out["inbank_vs_overbank"] = ib
    # by slope class / order
    def by(mask_list, hist, labels):
        res = {}
        for lab, m, h in zip(labels, mask_list, hist):
            if not m.any():
                continue
            t = h.sum(axis=0)
            res[lab] = {"segments": int(m.sum()), "fractions": {k: frac(c, k, mask=m) for k in
                                                                ("clamp", "floor", "both", "c2neg", "over")},
                        "Km_s": dist(t, "log10_Km_s"), "D": dist(t, "log10_D"), "C": dist(t, "log10_C"),
                        "X_final": dist(t, "X2", log=False),
                        "X_unclamped_min": r(np.nanmin(mm["min_X2_raw"][m])),
                        "at_peak": {"floor": r(np.nanmean(pk["floor"][m])), "clamp": r(np.nanmean(pk["clamp"][m])),
                                    "over": r(np.nanmean(pk["over"][m])),
                                    "X_unclamped_median": r(np.nanmedian(pk["X2_raw"][m])),
                                    "Km_s_median": r(np.nanmedian(pk["Km"][m]))}}
        return res
    out["by_slope_class"] = by([sc == i for i in range(4)], hs, CR.SLOPE_CLASSES)
    out["by_stream_order"] = by([order == o for o in orders], ho, [str(o) for o in orders])
    # at each segment's peak
    out["at_peak"] = {
        "fractions": {"clamp": r(np.nanmean(pk["clamp"])), "floor": r(np.nanmean(pk["floor"])),
                      "both": r(np.nanmean(pk["clamp"] * pk["floor"])), "over": r(np.nanmean(pk["over"])),
                      "cap": r(np.nanmean(pk["X2_raw"] > 0.5)), "c2neg": r(np.nanmean(pk["C2"] < 0)),
                      "c3neg": r(np.nanmean(pk["C3"] < 0)), "D_gt_half": r(np.nanmean(pk["D"] > 0.5))},
        **{k: pkq(pk[k]) for k in ("Km", "dx_over_Ck", "X2", "X2_raw", "X1_raw", "C", "D", "C1", "C2", "C3",
                                   "h_over_bfd")}}
    return out


# ------------------------------------------------------------------ volume loss and timing (Potomac)
def potomac_storm_volume(seg):
    hours = int(json.loads((A.INPUTS / "potomac_storm" / "case.json").read_text())["hours"])
    ql = MI.storm_series(seg["length_km"].to_numpy(), hours).astype(np.float64)
    return float((ql.sum(axis=1) * 3600 - ql[:, 0] * hours * 3600).sum())


def loss_block(z, storm, sc, pk_ref):
    f, c = z["fsum_"], z["cnt_"]
    loss = f["in_minus_out"]
    hyst = f["id_a_dI"] + f["id_b_dO"]
    resid = f["in_minus_out_acc"] - hyst - f["guard_term"]
    pct = lambda v: r(100 * np.sum(v) / storm)  # noqa: E731
    out = {"storm_volume_m3": r(storm, 6),
           "troute_loss_pct_of_storm": pct(loss),
           "first_hour_in_minus_out_pct": pct(loss - f["in_minus_out_acc"]),
           "hysteresis_terms_pct": pct(hyst),
           "hysteresis_by_regime_pct": {k: pct(f[f"bp_{k}"]) for k in ("free", "floor", "clamp", "both")},
           "hysteresis_boundary_pct": pct(f["bp_boundary"]),
           "negative_flow_guard_pct": pct(f["guard_term"]),
           "residual_pct": pct(resid),
           "by_parts_closure_rel": r(abs((sum(f[f"bp_{k}"].sum() for k in ("free", "floor", "clamp", "both"))
                                         + f["bp_boundary"].sum()) - hyst.sum()) / abs(hyst.sum()))}
    pos = np.clip(loss, 0, None)
    out["segment_shares_of_net_loss_pct"] = {
        **{f"slope_{lab}": r(100 * loss[sc == i].sum() / loss.sum()) for i, lab in enumerate(CR.SLOPE_CLASSES)},
        "floor_at_peak": r(100 * loss[pk_ref["floor"] == 1].sum() / loss.sum()),
        "floor_in_ge_half_of_steps": r(100 * loss[c["floor"] >= 0.5 * c["steps"]].sum() / loss.sum()),
        "clamp_at_peak": r(100 * loss[pk_ref["clamp"] == 1].sum() / loss.sum()),
        "segments_with_guard": r(100 * loss[c["guard"] > 0].sum() / loss.sum())}
    out["segment_shares_of_positive_loss_pct"] = {
        "floor_at_peak": r(100 * pos[pk_ref["floor"] == 1].sum() / pos.sum()),
        "floor_in_ge_half_of_steps": r(100 * pos[c["floor"] >= 0.5 * c["steps"]].sum() / pos.sum()),
        "clamp_at_peak": r(100 * pos[pk_ref["clamp"] == 1].sum() / pos.sum())}
    return out


def timing_block(z, seg, tree):
    """Outlet first-moment shift (True - False) predicted from the False closure values,
    lateral inflow excluded (as mechanism.py F), split by step regime."""
    f = z["fsum_"]
    W = f["w_excess_inflow"]
    down, topo, L = tree["down"], tree["topo"], tree["L"]
    res = {}
    o = int(np.flatnonzero(seg["is_outlet"].to_numpy())[0])
    for k in ("free", "floor", "clamp", "both"):
        delta = np.where(W > 0, f[f"wdelta_{k}"] / np.where(W > 0, W, 1), 0.0)
        Aacc = L.copy()
        S = np.zeros_like(L)
        for i in topo:
            dn = down[i]
            if dn >= 0:
                Aacc[dn] += Aacc[i]
                S[dn] += S[i] + Aacc[i] * delta[dn]
        res[k] = S[o] / Aacc[o] / 3600
    tot = sum(res.values())
    return {"outlet_predicted_shift_h": r(tot), "by_regime_h": {k: r(v) for k, v in res.items()},
            "share_by_regime_pct": {k: r(100 * v / tot) for k, v in res.items()},
            "note": "inflow-excess-weighted dt/2 - Km X per segment from the False (patched) replay at native "
                    "resolution, accumulated with storm volume entering from upstream (lateral excluded). "
                    "First-moment predictor of the timing shift (README \"Mechanism checks\"); compare results/mechanism.json F."}


# ------------------------------------------------------------------ screening cross-check
def screening(seg, z300):
    if not SKEL.exists():
        return {"skipped": "repro/diffusive_mainstem/results/segments_conus.parquet not found"}
    cs = pd.read_parquet(SKEL).set_index("link").reindex(seg["link"].to_numpy())
    if cs["km"].isna().any():
        return {"skipped": "Potomac segments missing from segments_conus.parquet"}
    c, pk = z300["cnt_"], z300["pk_"]
    floor_pk = pk["floor"] == 1
    floor_half = c["floor"] >= 0.5 * c["steps"]
    flags = {"XF": cs["XF"].to_numpy(bool), "LS": cs["LS"].to_numpy(bool), "BW": cs["BW"].to_numpy(bool),
             "KC": cs["KC"].to_numpy(bool), "error_flagged": cs["error"].to_numpy(bool),
             "effect_flagged": cs["effect"].to_numpy(bool), "F_candidate": cs["cfg_F_candidate"].to_numpy(bool),
             "A_mainstem": cs["cfg_A_mainstem"].to_numpy(bool),
             "B_mainstem_fringes": cs["cfg_B_mainstem_fringes"].to_numpy(bool)}
    km = cs["km"].to_numpy()
    out = {"definition": ("closure floor-bound = X on the 0.25 floor at the segment's peak (dt = 300 s, False, "
                          "patched replay); also >= half of the segment-steps on the floor. Screening flags at "
                          "bankfull from repro/diffusive_mainstem (XF = kernel X floor binds at bankfull; error = LS or BW; "
                          "effect = XF or KC)."),
           "floor_at_peak_segments": int(floor_pk.sum()), "floor_ge_half_steps_segments": int(floor_half.sum())}
    for name, m in flags.items():
        out[name] = {"segments": int(m.sum()),
                     "pct_of_floor_at_peak_segments_flagged": r(100 * (m & floor_pk).sum() / max(floor_pk.sum(), 1)),
                     "pct_of_flagged_floor_at_peak": r(100 * (m & floor_pk).sum() / max(m.sum(), 1)),
                     "pct_of_floor_ge_half_segments_flagged": r(100 * (m & floor_half).sum() / max(floor_half.sum(), 1)),
                     "pct_km_floor_at_peak_flagged": r(100 * km[m & floor_pk].sum() / max(km[floor_pk].sum(), 1e-9))}
    g = c["guard"] > 0
    out["guard_segments"] = {"n": int(g.sum()), "pct_XF": r(100 * (flags["XF"] & g).sum() / max(g.sum(), 1)),
                             "pct_LS": r(100 * (flags["LS"] & g).sum() / max(g.sum(), 1)),
                             "pct_floor_at_peak": r(100 * (floor_pk & g).sum() / max(g.sum(), 1))}
    xs = cs["x_kernel_raw_bf"].to_numpy()
    ok = np.isfinite(xs) & np.isfinite(pk["X2_raw"])
    out["spearman_screen_X_raw_at_bankfull_vs_closure_X_raw_at_peak"] = r(spearmanr(xs[ok], pk["X2_raw"][ok]).statistic)
    xf = flags["XF"]
    out["XF_vs_floor_at_peak_2x2"] = {"both": int((xf & floor_pk).sum()), "XF_only": int((xf & ~floor_pk).sum()),
                                      "floor_only": int((~xf & floor_pk).sum()), "neither": int((~xf & ~floor_pk).sum())}
    return out


# ------------------------------------------------------------------ float64 check of the guard
def guard_check(z300):
    """Two segments with the largest guard term: own-trajectory float64 replay (mc_port.py)
    with the kernel's guard vs clipping the raw MC value at zero."""
    import mc_port as M
    rec = REC300 / "dt300_sts0"
    if not (rec / "q.npy").exists():
        return {"skipped": "recording build/closure_runs/patched/potomac_storm/dt300_sts0 not kept"}
    Q = np.load(rec / "q.npy", mmap_mode="r")
    P = np.load(rec / "params.npy")
    ql = np.load(rec / "qlat.npy")
    q0 = np.load(rec / "q0.npy")
    ptr, idx = np.load(rec / "up_ptr.npy"), np.load(rec / "up_idx.npy")
    gt = z300["fsum_"]["guard_term"]
    rows = []
    for s in np.argsort(gt)[:2]:
        ups = idx[ptr[s]:ptr[s + 1]]
        I = np.concatenate([[q0[ups].sum(dtype=np.float32)], Q[ups].sum(axis=0, dtype=np.float32)]).astype(float)
        geo = [float(x) for x in P[s]]
        res = {}
        for mode in ("guard", "clip_at_zero"):
            qdp, hp, vin, vout, ng = float(q0[s]), 0.0, 0.0, 0.0, 0
            for t in range(Q.shape[1]):
                qup, quc, qlv = I[t], I[t + 1], float(ql[s, t // 12])
                qd, h, d = M.mc(300.0, qup, quc, qdp, qlv, *geo, hp)
                if d["clip"] > 0:
                    ng += 1
                    if mode == "clip_at_zero":
                        c1, c2, c3, c4 = d["C"]
                        qd = max(c1 * qup + c2 * quc + c3 * qdp + c4, 0.0)
                vin += 300 * ((qup + quc) / 2 + qlv)
                vout += 300 * (qdp + qd) / 2
                qdp, hp = qd, h
            res[mode] = {"guard_steps": ng, "in_minus_out_m3": r(vin - vout)}
        rows.append({"segment_index": int(s), "s0": r(P[s, 7]), "dx_m": r(P[s, 0]),
                     "replay_guard_term_m3": r(gt[s]), "float64_own_trajectory": res,
                     "water_added_by_guard_vs_clip_m3": r(res["clip_at_zero"]["in_minus_out_m3"]
                                                         - res["guard"]["in_minus_out_m3"])})
    return {"segments": rows, "note": "independent of the float32 port and of T-Route's trajectory downstream "
                                      "of the segment: the segment is re-routed from its recorded inflow"}


# ------------------------------------------------------------------ figures
def style(ax):
    A.style(ax)


def cdf_from_hist(h, spec, log=True):
    _, lo, hi, nb = spec
    edges = np.linspace(lo, hi, nb + 1)
    c = np.cumsum(h) / max(h.sum(), 1)
    x = edges[1:]
    return (10 ** x if log else x), c


def fig_k_x(Z, path):
    fig, axs = plt.subplots(2, 3, figsize=(17, 9))
    tots = {dt: Z[("potomac_storm", dt, 0)]["hist_slope"].sum(axis=(0, 1)) for dt in DTS}

    def cdf_panel(ax, var, log, title, xlabel, xlim=None, vlines=(), xscale=None):
        style(ax)
        for dt in DTS:
            h, spec = hslice(tots[dt], var)
            x, y = cdf_from_hist(h, spec, log=log)
            if var == "X2":
                x, y = np.r_[spec[1], x], np.r_[0, y]
            ax.plot(x, y, color=RAMP[dt], lw=2, label=f"dt = {dt} s")
        for v in vlines:
            ax.axvline(v, color="#b5b4ad", lw=0.9)
        if xscale:
            ax.set_xscale(xscale)
        if xlim:
            ax.set_xlim(*xlim)
        ax.set_xlabel(xlabel, fontsize=9, color=INK)
        ax.set_ylabel("fraction of segment-steps ≤ x", fontsize=9, color=INK)
        ax.set_title(title, fontsize=10, color=INK)
        ax.legend(frameon=False, fontsize=8, loc="upper left")

    ax = axs[0, 0]
    style(ax)
    for dt in DTS:
        for var, ls in (("log10_Km_s", "-"), ("log10_dx_over_Ck_s", (0, (3, 2)))):
            h, spec = hslice(tots[dt], var)
            x, y = cdf_from_hist(h, spec)
            ax.plot(x / 3600, y, color=RAMP[dt], lw=2, ls=ls, label=f"dt = {dt} s" if ls == "-" else None)
    ax.plot([], [], color=MUTED, lw=2, label="Km = max(dt, dx/Ck)")
    ax.plot([], [], color=MUTED, lw=2, ls=(0, (3, 2)), label="dx/Ck (unclamped; same for every dt)")
    ax.set_xscale("log")
    ax.set_xlim(1e-2, 1e2)
    ax.set_xlabel("hours", fontsize=9, color=INK)
    ax.set_ylabel("fraction of segment-steps ≤ x", fontsize=9, color=INK)
    ax.set_title("(a) Muskingum K: Km vs dx/Ck", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    cdf_panel(axs[0, 1], "X2", False, "(b) final X (floor 0.25, cap 0.5)", "Muskingum X used for C1..C4",
              xlim=(0.24, 0.51))
    ax = axs[0, 2]
    style(ax)
    for dt in DTS:
        h, spec = hslice(tots[dt], "log10_D")
        x, y = cdf_from_hist(h, spec)
        xr_ = 0.5 - x / 4                                   # unclamped X = 1/2 - D/4
        ax.plot(xr_[::-1], (1 - y)[::-1], color=RAMP[dt], lw=2, label=f"dt = {dt} s")
    ax.axvline(0.25, color=ORANGE, lw=1.2, ls=(0, (3, 2)), label="floor 0.25")
    ax.set_xscale("symlog", linthresh=1)
    ax.set_xlim(-1e5, 1)
    ax.set_xlabel("unclamped X = ½(1 − D/2) (symlog)", fontsize=9, color=INK)
    ax.set_ylabel("fraction of segment-steps ≤ x", fontsize=9, color=INK)
    ax.set_title("(c) X before the floor (curves overlap for all dt)", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax = axs[1, 0]
    style(ax)
    keys = [("clamp", BLUE, "Km = dt (K clamp, C ≥ 1)"), ("floor", ORANGE, "X on the 0.25 floor (D > 1)"),
            ("c2neg", AQUA, "C2 < 0 (C < 2X)"), ("over", YELLOW, "overbank")]
    for k, col, lab in keys:
        for sts, ls, mk in ((0, "-", "o"), (1, (0, (3, 2)), "s")):
            y = [100 * Z[("potomac_storm", dt, sts)]["cnt_"][k].sum() / Z[("potomac_storm", dt, sts)]["cnt_"]["steps"].sum()
                 for dt in DTS]
            ax.plot(DTS, y, color=col, lw=2, ls=ls, marker=mk, ms=7 if sts == 0 else 5, mec="white", mew=1.5,
                    label=lab if sts == 0 else None)
    ax.plot([], [], color=MUTED, lw=2, marker="o", label="False (assumption off)")
    ax.plot([], [], color=MUTED, lw=2, ls=(0, (3, 2)), marker="s", label="True (overlaps False)")
    ax.set_xscale("log")
    ax.set_xticks(DTS, [str(d) for d in DTS])
    ax.set_ylim(0, 100)
    ax.set_xlabel("routing timestep dt (s)", fontsize=9, color=INK)
    ax.set_ylabel("% of segment-steps", fontsize=9, color=INK)
    ax.set_title("(d) Where the limits bind", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=8, loc="center left")
    cdf_panel(axs[1, 1], "log10_C", True, "(e) Courant number C = Ck·dt/dx", "C (closure celerity)",
              xlim=(1e-3, 1e2), vlines=(1,), xscale="log")
    cdf_panel(axs[1, 2], "log10_D", True, "(f) cell Reynolds number D = Q/(W·S0·Ck·dx)",
              "D (lines: ½ Cunge's floor, 1 the kernel's floor)", xlim=(1e-5, 1e5), vlines=(0.5, 1), xscale="log")
    fig.suptitle("Potomac, what T-Route's MC closure produced at every segment-step after the first hour "
                 "(assume_short_ts = False unless noted; corrected kernel)", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_map(seg, z, path):
    with xr.open_dataset(A.INPUTS / "potomac_storm" / "RouteLink.nc") as ds:
        ll = pd.DataFrame({"lat": ds["lat"].values, "lon": ds["lon"].values},
                          index=ds["link"].values.astype(np.int64)).reindex(seg["link"].to_numpy())
    c = z["cnt_"]
    order = seg["order"].to_numpy()
    size = 0.6 + 1.6 * (order - 1)
    fig, axs = plt.subplots(1, 2, figsize=(13, 5.6))
    from matplotlib.colors import LinearSegmentedColormap
    seq = LinearSegmentedColormap.from_list("seqblue", ["#cde2fb"] + list(RAMP.values()))
    for ax, key, title in ((axs[0], "floor", "X on the 0.25 floor"), (axs[1], "clamp", "Km clamped to dt")):
        style(ax)
        fr = c[key] / np.maximum(c["steps"], 1)
        zero = fr == 0
        ax.scatter(ll["lon"][zero], ll["lat"][zero], s=size[zero], color="#d6d5cf", lw=0, label="never")
        o = np.argsort(fr)
        o = o[~zero[o]]
        sc_ = ax.scatter(ll["lon"].to_numpy()[o], ll["lat"].to_numpy()[o], s=size[o] + 1.5, c=100 * fr[o],
                         cmap=seq, vmin=0, vmax=100, lw=0)
        if key == "floor":
            g = c["guard"] > 0
            ax.scatter(ll["lon"][g], ll["lat"][g], s=18, facecolor="none", edgecolor=ORANGE, lw=1.2,
                       label="negative-flow guard fired")
        cb = fig.colorbar(sc_, ax=ax, shrink=0.75)
        cb.set_label(f"% of segment-steps with {title}", fontsize=8, color=INK)
        cb.ax.tick_params(labelsize=8, colors=MUTED)
        ax.set_aspect(1 / np.cos(np.deg2rad(39)))
        ax.set_xlabel("longitude", fontsize=9, color=INK)
        ax.set_ylabel("latitude", fontsize=9, color=INK)
        ax.set_title(f"{title}: {100 * c[key].sum() / c['steps'].sum():.1f}% of segment-steps", fontsize=10, color=INK)
        ax.legend(frameon=False, fontsize=8, loc="lower left", markerscale=2)
    fig.suptitle("Potomac network, dt = 300 s, assume_short_ts = False (dot size = stream order)",
                 fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_x_slope(z, s0, path):
    pk = z["pk_"]
    fig, axs = plt.subplots(1, 2, figsize=(12.5, 4.8))
    for ax, key, ttl in ((axs[0], "X2_raw", "unclamped X at each segment's peak"),
                         (axs[1], "min_X2_raw", "most negative unclamped X over the event")):
        style(ax)
        y = pk[key] if key in pk else z["mm_"][key]
        over = pk["over"] == 1
        for m, col, lab in ((~over, BLUE, "in-bank at peak"), (over, ORANGE, "overbank at peak")):
            ax.scatter(s0[m], y[m], s=7, color=col, alpha=0.55, lw=0, label=lab)
        for v, lab, va in ((0.25, "floor 0.25", "top"), (0.5, "cap 0.5", "bottom")):
            ax.axhline(v, color=MUTED, lw=0.9, ls=(0, (3, 2)))
            ax.text(1.2e-5, v, lab, fontsize=8, color=MUTED, va=va, ha="left")
        ax.set_ylim(-2e5, 1)
        ax.set_xscale("log")
        ax.set_yscale("symlog", linthresh=1)
        ax.set_xlabel("RouteLink slope S0 (floor 1e-5)", fontsize=9, color=INK)
        ax.set_ylabel("X = ½(1 − D/2) before clamping (symlog)", fontsize=9, color=INK)
        ax.set_title(ttl, fontsize=10, color=INK)
        ax.legend(frameon=False, fontsize=8, loc="lower right", markerscale=2)
    fig.suptitle("Potomac, dt = 300 s, assume_short_ts = False: the X the closure computes before the 0.25 floor",
                 fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ------------------------------------------------------------------ main
def main() -> int:
    res = {"definitions": {
        "segment_steps": "every segment at every routing step after the first hour (T-Route's first step starts "
                         "from the restart depth h0 = 0)",
        "closure": "the interval-2 secant2_h call of the last secant iteration (its C1..C4 give qdc)",
        "clamp": "Km = dt, i.e. dx/Ck <= dt (C >= 1)",
        "floor": "unclamped X2 < 0.25, i.e. D > 1",
        "cap": "unclamped X2 > 0.5, i.e. reference discharge qref <= 0",
        "D": "qref / (W S0 Ck dx), W = TopWdthCC overbank else bw + 2 z h; kernel X = 1/2 (1 - D/2); "
             "Cunge's X = 1/2 (1 - D) would be < 0.25 at D > 1/2 (D_gt_half) and < 0 at D > 1",
        "C": "Ck dt / dx with the closure's Ck",
        "overbank": "closure depth h > bankfull depth (TopWdth - BtmWdth) / (2 z), z = 1/ChSlp",
        "slope_classes": CR.SLOPE_CLASSES}, "fidelity": {}, "closure": {}, "potomac": {}}
    Z, U = {}, {}
    for case in CASES:
        seg = pd.read_parquet(A.INPUTS / case / "segments.parquet")
        p = A.channel_params(case, seg["link"].to_numpy())
        sc = CR.slope_class(p["s0"].to_numpy().astype(np.float64))
        order = seg["order"].to_numpy().astype(int)
        res["fidelity"][case], res["closure"][case] = {}, {}
        for dt in DTS:
            for sts in (0, 1):
                z = load("patched", case, dt, sts)
                u = load("unpatched", case, dt, sts)
                Z[(case, dt, sts)], U[(case, dt, sts)] = z, u
                job = json.loads((OUT / "jobs" / f"{case}_dt{dt}_sts{sts}.json").read_text())
                key = f"dt{dt}_sts{sts}"
                n_all = int(z["info"]["nseg"] * z["info"]["nts"])
                peak = z["pk_"]["q"]
                fid = {"kernel_calls": n_all}
                for name, x in (("patched_replay", z), ("unpatched_replay", u)):
                    cc, ff = x["cnt_"], x["fsum_"]
                    fid[name] = {"bitwise_equal_frac": r(cc["q_bitwise_equal"].sum() / n_all, 6),
                                 "n_rel_diff_gt_1e-6": int(cc["err_q_rel_gt_1e-6"].sum()),
                                 "n_rel_diff_gt_1e-3": int(cc["err_q_rel_gt_1e-3"].sum()),
                                 "frac_rel_diff_gt_1e-3": r(cc["err_q_rel_gt_1e-3"].sum() / n_all),
                                 "max_abs_diff_m3s": r(ff["max_abs_err_q"].max()),
                                 "max_abs_diff_over_segment_peak": r(np.nanmax(ff["max_abs_err_q"] / np.maximum(peak, 1e-6))),
                                 "median_segment_max_abs_diff_over_peak": r(np.nanmedian(ff["max_abs_err_q"] / np.maximum(peak, 1e-6))),
                                 "n_depth_rel_diff_gt_1e-3": int(cc["err_h_rel_gt_1e-3"].sum()),
                                 "recording_matches_published_run_hourly_bitwise":
                                     x["info"].get("matches_published_run_hourly_bitwise")}
                fid["troute_patched_vs_unpatched_trajectory"] = job["trajectory_patched_vs_unpatched"]
                fid["loops_start_from_previous_state"] = all(
                    l.get("starts_from_previous_last_step", True) for l in job["record_meta_patched"]["loops"])
                res["fidelity"][case][key] = fid
                res["closure"][case][key] = closure_block(z, sc, order, z["orders"])
                print(f"ok      {case} {key}", flush=True)
        if case == "potomac_storm":
            storm = potomac_storm_volume(seg)
            tree = A.build_tree(seg)
            for dt in DTS:
                for sts in (0, 1):
                    key = f"dt{dt}_sts{sts}"
                    z, u = Z[(case, dt, sts)], U[(case, dt, sts)]
                    res["potomac"][key] = {"loss_patched": loss_block(z, storm, sc, z["pk_"]),
                                           "loss_unpatched": loss_block(u, storm, sc, z["pk_"])}
                    if sts == 0:
                        res["potomac"][key]["timing_shift_prediction"] = timing_block(z, seg, tree)
            z300 = Z[(case, 300, 0)]
            res["screening_crosscheck_dt300_false"] = screening(seg, z300)
            res["guard_float64_check_dt300_false"] = guard_check(z300)
            fig_k_x(Z, OUT / "fig_closure_K_X_vs_dt.png")
            fig_map(seg, z300, OUT / "fig_closure_floor_map_dt300.png")
            fig_x_slope(z300, p["s0"].to_numpy(), OUT / "fig_closure_X_vs_slope_dt300.png")
            # per-segment table at dt = 300 s, False
            pk, c, mm = z300["pk_"], z300["cnt_"], z300["mm_"]
            pd.DataFrame({"link": seg["link"].to_numpy(), "order": seg["order"].to_numpy(), "s0": p["s0"].to_numpy(),
                          "slope_class": sc,
                          "frac_floor": c["floor"] / c["steps"], "frac_clamp": c["clamp"] / c["steps"],
                          "frac_c2neg": c["c2neg"] / c["steps"], "frac_over": c["over"] / c["steps"],
                          "guard_steps": c["guard"], "min_X_unclamped": mm["min_X2_raw"],
                          **{f"peak_{k}": pk[k] for k in CR.PK},
                          "loss_m3": z300["fsum_"]["in_minus_out"],
                          "guard_term_m3": z300["fsum_"]["guard_term"]}).to_csv(
                OUT / "segments_dt300_false.csv", index=False, float_format="%.6g")
    res["not_done"] = ("dt = 7200 and 14400 s: T-Route's hourly forcing needs dt to divide 3600 "
                       "(qts_subdivisions = 3600 // dt; run_troute.py refuses other values). Longer steps "
                       "would need re-aggregated forcing files and a check of T-Route's forcing handling; "
                       "not done.")
    (OUT / "summary.json").write_text(json.dumps(res, indent=1) + "\n")
    print("ok      results/closure/summary.json, fig_closure_K_X_vs_dt.png, fig_closure_floor_map_dt300.png, "
          "fig_closure_X_vs_slope_dt300.png, segments_dt300_false.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
