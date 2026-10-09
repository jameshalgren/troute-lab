"""Compare assume_short_ts True vs False; write results/results.json and figures.

Metrics per case and dt (True compared with False; False, T-Route's default, is the
reference unless noted):
  outlet      peak flow and time (native resolution, parabolic peak refinement),
              volume, NSE, KGE, max |difference|
  network     per-segment peak-time shift (True - False, h) and relative peak
              difference (%): percentiles, fractions above thresholds, binned by the
              longest upstream path (segments), distance to outlet, stream order;
              Spearman rank correlations
  centroid    (storm case) shift of the centroid of each segment's storm hydrograph
              (flow above the initial steady flow), for segments that passed >= 95% of
              their upstream storm volume in both runs, compared with the linear-theory
              prediction (README "Why"): per segment, enabling the short-time-step
              assumption (True) shifts the response centroid by Delta = dt/2 - Km*X
              (exact first moment of the two discrete schemes with fixed coefficients),
              and centroid shifts add along the cascade, weighted by where the storm
              water entered. Km and X are taken at each segment's False peak. This is
              the predictor as first defined (its outputs are regression-checked);
              mechanism.py tests it and an improved variant (README "Mechanism checks").
  mainstem    the same along the longest flow path (native resolution)
  Courant     Cn = ck * dt / dx at each segment's peak (ck from the depth at the peak,
              with T-Route's own `courant` formula; checked against the compiled
              Fortran kernel through ctypes)
  accuracy    for both settings, errors against the dt = 60 s False run
"""
from __future__ import annotations

import ctypes
import json
import platform
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
from run_experiment import CASES, DTS  # noqa: E402

INPUTS = HERE / "build" / "inputs"
RUNS = HERE / "results" / "runs"
OUT = HERE / "results"
LIBMC = HERE / "build" / ("libmc_kernel.dylib" if platform.system() == "Darwin" else "libmc_kernel.so")
REF_DT = 60
CMP_DTS = list(DTS)
STORM = [c for c in CASES if c.endswith("storm")]
STORM_M3_PER_KM = 25.0 / 1000 * 1.25e6    # make_inputs.py: 25 mm on 1.25 km2 per km

BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#8a8a85"     # False, True, reference
RAMP = {60: "#86b6ef", 300: "#5598e7", 900: "#1c5cab", 3600: "#0d366b"}
INK, MUTED = "#1f1f1e", "#6b6a64"


# ------------------------------------------------------------------ geometry / kernel
def channel_params(case: str, links: np.ndarray) -> pd.DataFrame:
    with xr.open_dataset(INPUTS / case / "RouteLink.nc") as ds:
        df = pd.DataFrame({k: ds[v].values for k, v in {
            "link": "link", "dx": "Length", "bw": "BtmWdth", "tw": "TopWdth", "twcc": "TopWdthCC",
            "n": "n", "ncc": "nCC", "cs": "ChSlp", "s0": "So"}.items()}).set_index("link")
    return df.loc[links].astype(np.float32)


def courant_np(h, p: pd.DataFrame, dt: float):
    """T-Route's `courant` + `hydraulic_geometry` (MCsingleSegStime_f2py_NOLOOP.f90), float32."""
    f = np.float32
    h = np.asarray(h, dtype=f)
    bw, tw, twcc = p.bw.to_numpy(), p.tw.to_numpy(), p.twcc.to_numpy()
    n, ncc, s0, cs, dx = p.n.to_numpy(), p.ncc.to_numpy(), p.s0.to_numpy(), p.cs.to_numpy(), p.dx.to_numpy()
    z = np.where(cs == 0, f(1), f(1) / np.where(cs == 0, f(1), cs))
    bfd = np.where(bw > tw, bw / f(0.00001), np.where(bw == tw, bw / (f(2) * z), (tw - bw) / (f(2) * z)))
    hgt = np.maximum(h - bfd, f(0))
    hlt = np.minimum(bfd, h)
    nwm3 = (hgt > 0) & (twcc <= 0)
    hgt = np.where(nwm3, f(0), hgt)
    hlt = np.where(nwm3, h, hlt)
    area = (bw + hlt * z) * hlt
    wp = bw + 2 * hlt * np.sqrt(1 + z * z)
    areac = twcc * hgt
    wpc = np.where(hgt > 0, twcc + 2 * hgt, f(0))
    r = (area + areac) / (wp + wpc)
    with np.errstate(divide="ignore", invalid="ignore"):
        ck = np.maximum(f(0), ((np.sqrt(s0) / n) * ((f(5) / 3) * r ** (f(2) / 3)
              - ((f(2) / 3) * r ** (f(5) / 3) * (2 * np.sqrt(1 + z * z) / (bw + 2 * hlt * z))))
              * area + ((np.sqrt(s0) / ncc) * (f(5) / 3) * hgt ** (f(2) / 3)) * areac) / (area + areac))
    ck = np.nan_to_num(ck)
    return ck, ck * (f(dt) / dx), bfd, z


def mc_coefficients(q, h, p: pd.DataFrame, dt: float):
    """C2 (weight on current upstream inflow) as in `secant2_h`, at flow q and depth h.

    X uses the kernel's second-call formula, X = 0.5 (1 - Q / (2 W s0 ck dx)) clipped to
    [0.25, 0.5], W = twl in-bank or twcc overbank; Km = max(dt, dx/ck).
    """
    ck, cn, bfd, z = courant_np(h, p, dt)
    s0, dx, twcc = p.s0.to_numpy(), p.dx.to_numpy(), p.twcc.to_numpy()
    twl = p.bw.to_numpy() + 2 * z * h
    over = (h > bfd) & (twcc > 0) & (p.ncc.to_numpy() > 0) & (ck > 0)
    w = np.where(over, twcc, twl)
    with np.errstate(divide="ignore", invalid="ignore"):
        x = np.clip(0.5 * (1 - q / (2 * w * s0 * ck * dx)), 0.25, 0.5)
        km = np.where(ck > 0, np.maximum(dt, dx / ck), dt)
    x = np.where(ck > 0, x, 0.5)
    d = km * (1 - x) + dt / 2
    c1 = (km * x + dt / 2) / d
    c2 = (dt / 2 - km * x) / d
    return c2, c1, x, km, ck, cn


def kernel_check(p: pd.DataFrame, h: np.ndarray, q: np.ndarray, dt: float, k: int = 400) -> dict:
    """Call T-Route's compiled Fortran MC kernel (bind(c) c_muskingcungenwm) on k segments in
    steady state (qup = quc = qdp = q, ql = 0, depthp = h) and compare its ck, cn, X with
    the numpy formulas evaluated at the kernel's returned depth and flow."""
    lib = ctypes.CDLL(str(LIBMC))
    fn = lib.c_muskingcungenwm
    fn.restype = None
    rng = np.random.default_rng(0)
    idx = rng.choice(np.flatnonzero((q > 0.1) & (h > 0)), size=min(k, int(((q > 0.1) & (h > 0)).sum())),
                     replace=False)
    sub = p.iloc[idx]
    outs = np.zeros((len(idx), 6), dtype=np.float32)
    for r, i in enumerate(idx):
        row = p.iloc[i]
        args = [dt, q[i], q[i], q[i], 0.0, row.dx, row.bw, row.tw, row.twcc, row.n, row.ncc,
                row.cs, row.s0, 0.0, h[i]]
        cin = [ctypes.c_float(a) for a in args]
        co = [ctypes.c_float(0.0) for _ in range(6)]
        fn(*[ctypes.byref(c) for c in cin + co])
        outs[r] = [c.value for c in co]
    qdc, depthc, ck_k, cn_k, x_k = outs[:, 0], outs[:, 2], outs[:, 3], outs[:, 4], outs[:, 5]
    ck_n, cn_n, _, _ = courant_np(depthc, sub, dt)
    _, _, x_n, _, _, _ = mc_coefficients(qdc, depthc, sub, dt)
    rel = lambda a, b: float(np.nanmax(np.abs(a - b) / np.maximum(np.abs(b), 1e-6)))  # noqa: E731
    return {"n_segments": int(len(idx)), "dt_s": dt,
            "max_rel_diff_ck": rel(ck_n, ck_k), "max_rel_diff_cn": rel(cn_n, cn_k),
            "max_abs_diff_X": float(np.nanmax(np.abs(x_n - x_k))),
            "note": "numpy formulas vs compiled Fortran kernel, steady inputs, depth/flow returned by the kernel"}


# ------------------------------------------------------------------ metrics
def nse(sim, ref):
    ref = np.asarray(ref, float)
    sim = np.asarray(sim, float)
    den = np.sum((ref - ref.mean()) ** 2)
    return float(1 - np.sum((sim - ref) ** 2) / den) if den > 0 else float("nan")


def kge(sim, ref):
    sim, ref = np.asarray(sim, float), np.asarray(ref, float)
    if ref.std() == 0 or sim.std() == 0:
        return float("nan")
    r = np.corrcoef(sim, ref)[0, 1]
    return float(1 - np.sqrt((r - 1) ** 2 + (sim.std() / ref.std() - 1) ** 2 + (sim.mean() / ref.mean() - 1) ** 2))


def nse_rows(sim, ref):
    ref = ref.astype(float)
    sim = sim.astype(float)
    den = ((ref - ref.mean(axis=1, keepdims=True)) ** 2).sum(axis=1)
    num = ((sim - ref) ** 2).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, 1 - num / den, np.nan)


def load(case, dt, sts):
    return dict(np.load(RUNS / case / f"dt{dt}_sts{int(sts)}.npz"))


def pct(a, qs=(1, 5, 25, 50, 75, 95, 99)):
    a = np.asarray(a, float)
    a = a[np.isfinite(a)]
    return {f"p{q}": round(float(np.percentile(a, q)), 4) for q in qs} if a.size else {}


def r4(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 4)


def outlet_series(run, seg):
    """Native-resolution outlet flow (outlet is on the mainstem) and its times (h)."""
    mi = run["main_idx"]
    o = int(np.flatnonzero(seg.is_outlet.to_numpy())[0])
    k = int(np.flatnonzero(mi == o)[0])
    q = run["main_q"][k]
    t = (np.arange(q.size) + 1) * int(run["dt"]) / 3600.0
    return t, q


def compare_outlet(a, b, seg, peak_interior_only=True):
    t, qa = outlet_series(a, seg)
    _, qb = outlet_series(b, seg)
    o = int(np.flatnonzero(seg.is_outlet.to_numpy())[0])
    out = {
        "peak_true_m3s": r4(a["peak_q"][o]), "peak_false_m3s": r4(b["peak_q"][o]),
        "peak_rel_diff_pct": r4(100 * (a["peak_q"][o] - b["peak_q"][o]) / b["peak_q"][o]),
        "peak_time_true_h": r4(a["peak_t_s"][o] / 3600), "peak_time_false_h": r4(b["peak_t_s"][o] / 3600),
        "peak_time_shift_h": r4((a["peak_t_s"][o] - b["peak_t_s"][o]) / 3600),
        "volume_rel_diff_pct": r4(100 * (a["volume_m3"][o] - b["volume_m3"][o]) / b["volume_m3"][o]),
        "nse_true_vs_false": r4(nse(qa, qb)), "kge_true_vs_false": r4(kge(qa, qb)),
        "max_abs_diff_m3s": r4(np.max(np.abs(qa - qb))),
        "max_abs_diff_pct_of_false_peak": r4(100 * np.max(np.abs(qa - qb)) / b["peak_q"][o]),
        "peak_at_run_end_true": bool(a["peak_step"][o] == qa.size - 1),
        "peak_at_run_end_false": bool(b["peak_step"][o] == qb.size - 1),
    }
    return out


def binned(x, y, edges):
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (x >= lo) & (x < hi) & np.isfinite(y)
        if m.sum() >= 5:
            rows.append({"bin": [r4(lo), r4(hi)], "n": int(m.sum()), "median": r4(np.median(y[m])),
                         "p10": r4(np.percentile(y[m], 10)), "p90": r4(np.percentile(y[m], 90))})
    return rows


def analyze_case(case: str) -> tuple[dict, dict]:
    seg = pd.read_parquet(INPUTS / case / "segments.parquet")
    info = json.loads((INPUTS / case / "case.json").read_text())
    p = channel_params(case, seg["link"].to_numpy())
    res = {"case": info, "by_dt": {}}
    figdata = {"seg": seg, "runs": {}}
    ref = load(case, REF_DT, False)
    storm = case in STORM
    tree = build_tree(seg)
    for dt in DTS:
        a, b = load(case, dt, True), load(case, dt, False)
        figdata["runs"][dt] = (a, b)
        for r in (a, b):
            if not bool(r["finite"]):
                raise RuntimeError(f"non-finite values in {case} dt={dt}")
        d = {"wall_s_true": r4(a["wall_s"]), "wall_s_false": r4(b["wall_s"])}
        d["outlet"] = compare_outlet(a, b, seg)
        # per segment
        dtp = (a["peak_t_s"] - b["peak_t_s"]) / 3600.0
        rel = 100 * (a["peak_q"] - b["peak_q"]) / np.where(b["peak_q"] > 0, b["peak_q"], np.nan)
        # segments where the peak is a real event peak (not at the run's first or last step)
        nst = b["q_hourly"].shape[1] * (3600 // dt)
        ev = (b["peak_step"] > 0) & (b["peak_step"] < nst - 1) & (a["peak_step"] < nst - 1)
        ev &= b["peak_q"] > (1.0 if not storm else 0.0)
        if storm:
            ev &= b["peak_q"] > seg["q0"].to_numpy() * 1.001
        ns = nse_rows(a["q_hourly"], b["q_hourly"])
        d["segments"] = {
            "n_segments": int(len(seg)), "n_event_segments": int(ev.sum()),
            "event_definition": ("False-run peak strictly inside the run and above the initial "
                                 "steady flow" if storm else
                                 "False-run peak strictly inside the run and >= 1 m3/s"),
            "peak_time_shift_h": pct(dtp[ev]), "peak_rel_diff_pct": pct(rel[ev]),
            "frac_abs_peak_rel_diff_gt_5pct": r4(np.mean(np.abs(rel[ev]) > 5)),
            "frac_abs_peak_rel_diff_gt_10pct": r4(np.mean(np.abs(rel[ev]) > 10)),
            "frac_abs_peak_time_shift_gt_1h": r4(np.mean(np.abs(dtp[ev]) > 1)),
            "nse_hourly_true_vs_false": pct(ns[ev], (5, 25, 50)),
            "max_abs_diff_hourly_m3s": r4(np.max(np.abs(a["q_hourly"] - b["q_hourly"]))),
        }
        x_up = seg["up_path_segs"].to_numpy()
        x_dist = seg["dist_to_outlet_km"].to_numpy()
        sp = lambda x, y: r4(spearmanr(x[ev], y[ev]).statistic) if ev.sum() > 10 else None  # noqa: E731
        d["dependence"] = {
            "spearman_peak_time_shift_vs_up_path_segs": sp(x_up, dtp),
            "spearman_peak_rel_diff_vs_up_path_segs": sp(x_up, rel),
            "spearman_peak_time_shift_vs_dist_to_outlet": sp(x_dist, dtp),
            "spearman_peak_rel_diff_vs_dist_to_outlet": sp(x_dist, rel),
            "peak_time_shift_h_by_up_path_segs": binned(x_up[ev], dtp[ev], [1, 10, 25, 50, 100, 200, 300, 400, 500, 700]),
            "peak_rel_diff_pct_by_up_path_segs": binned(x_up[ev], rel[ev], [1, 10, 25, 50, 100, 200, 300, 400, 500, 700]),
            "peak_time_shift_h_by_dist_to_outlet_km": binned(x_dist[ev], dtp[ev], [0, 50, 100, 200, 400, 800, 1700]),
            "peak_rel_diff_pct_by_order": [
                {"order": int(o), "n": int(((seg.order == o) & ev).sum()),
                 "median_peak_rel_diff_pct": r4(np.median(rel[ev & (seg.order == o).to_numpy()])),
                 "median_peak_time_shift_h": r4(np.median(dtp[ev & (seg.order == o).to_numpy()]))}
                for o in sorted(seg.order.unique()) if ((seg.order == o) & ev).sum() >= 5],
        }
        # Courant number, Muskingum X, Km and C2 at each segment's peak (False run)
        c2, c1, x, km, ck, cn = mc_coefficients(b["peak_q"], b["depth_at_peak"], p, dt)
        delta = dt / 2.0 - km * x            # s: centroid shift per segment, True - False
        d["courant_at_peak_false"] = {**pct(cn[ev], (5, 25, 50, 75, 95)),
                                      "frac_gt_1": r4(np.mean(cn[ev] > 1)),
                                      "frac_km_clamped_to_dt": r4(np.mean((km <= dt * 1.000001)[ev]))}
        d["muskingum_X_at_peak_false"] = pct(x[ev], (5, 25, 50, 75, 95))
        d["c2_at_peak_false"] = {**pct(c2[ev], (5, 25, 50, 75, 95)), "frac_negative": r4(np.mean(c2[ev] < 0))}
        d["delta_per_segment_s"] = {**pct(delta[ev], (5, 25, 50, 75, 95)),
                                    "frac_negative_(short_ts_earlier)": r4(np.mean(delta[ev] < 0))}
        # centroid shifts (storm case): measured vs predicted
        cen_meas = cen_pred = complete = None
        if storm:
            q0 = seg["q0"].to_numpy()
            t = np.arange(1, a["q_hourly"].shape[1] + 1, dtype=float)

            def centroid(r):
                e = np.clip(r["q_hourly"] - q0[:, None], 0, None)
                return (e * t).sum(axis=1) / np.where(e.sum(axis=1) > 0, e.sum(axis=1), np.nan), e.sum(axis=1) * 3600

            ca, va = centroid(a)
            cb, vb = centroid(b)
            storm_vol = tree["acc_km"] * STORM_M3_PER_KM
            back = lambda r: (r["q_hourly"][:, -1] - q0) < 0.01 * (r["peak_q"] - q0)  # noqa: E731
            complete = back(a) & back(b)
            # event-volume balance from the native-resolution volume: (V - q0*T) / storm volume
            T = float(a["hours"]) * 3600.0
            mb_a = (a["volume_m3"] - q0 * T) / storm_vol
            mb_b = (b["volume_m3"] - q0 * T) / storm_vol
            cen_meas = ca - cb
            cen_pred = tree_weighted_shift(tree, delta) / 3600.0
            o = int(np.flatnonzero(seg.is_outlet.to_numpy())[0])
            err = (cen_meas - cen_pred)[complete]
            d["centroid"] = {
                "n_complete_segments": int(complete.sum()),
                "complete_definition": "flow back within 1% of (peak - initial) of the initial "
                                       "steady flow at the end of the run, in both runs",
                "outlet_complete": bool(complete[o]),
                "outlet_measured_shift_h": r4(cen_meas[o]), "outlet_predicted_shift_h": r4(cen_pred[o]),
                "measured_shift_h": pct(cen_meas[complete], (1, 5, 50, 95, 99)),
                "predicted_shift_h": pct(cen_pred[complete], (1, 5, 50, 95, 99)),
                "median_abs_error_h": r4(np.median(np.abs(err))) if err.size else None,
                "spearman_measured_vs_predicted": r4(spearmanr(cen_meas[complete], cen_pred[complete]).statistic)
                if complete.sum() > 10 else None,
                "regression_slope_measured_on_predicted": r4(np.polyfit(cen_pred[complete], cen_meas[complete], 1)[0])
                if complete.sum() > 10 else None,
            }
            d["event_volume_balance"] = {
                "definition": "(run volume - initial flow * duration) / storm lateral volume upstream",
                "outlet_true": r4(mb_a[o]), "outlet_false": r4(mb_b[o]),
                "network_true": pct(mb_a, (1, 50, 99)), "network_false": pct(mb_b, (1, 50, 99)),
            }
        # mainstem (longest flow path), headwater -> outlet
        mi = a["main_idx"]
        mi = mi[np.argsort(-seg["dist_to_outlet_km"].to_numpy()[mi])]
        dist = seg["dist_to_outlet_km"].to_numpy()[mi]
        evm = ev[mi]
        d["mainstem"] = {
            "n": int(mi.size), "n_event": int(evm.sum()),
            "max_abs_peak_time_shift_h": r4(np.max(np.abs(dtp[mi][evm]))) if evm.any() else None,
            "max_abs_peak_rel_diff_pct": r4(np.max(np.abs(rel[mi][evm]))) if evm.any() else None,
        }
        figdata.setdefault("mainstem", {})[dt] = {
            "dist": dist, "peak_shift": dtp[mi], "rel": rel[mi], "ev": evm,
            "cen_meas": None if cen_meas is None else cen_meas[mi],
            "cen_pred": None if cen_pred is None else cen_pred[mi],
            "complete": None if complete is None else complete[mi]}
        # accuracy against the dt = REF_DT False run
        acc = {}
        o = int(np.flatnonzero(seg.is_outlet.to_numpy())[0])
        for name, r in (("true", a), ("false", b)):
            acc[name] = {
                "outlet_peak_err_pct": r4(100 * (r["peak_q"][o] - ref["peak_q"][o]) / ref["peak_q"][o]),
                "outlet_peak_time_err_h": r4((r["peak_t_s"][o] - ref["peak_t_s"][o]) / 3600),
                "outlet_nse_hourly_vs_ref": r4(nse(r["q_hourly"][o], ref["q_hourly"][o])),
                "network_median_abs_peak_err_pct": r4(np.median(np.abs(
                    100 * (r["peak_q"][ev] - ref["peak_q"][ev]) / ref["peak_q"][ev]))),
                "network_median_abs_peak_time_err_h": r4(np.median(np.abs(
                    (r["peak_t_s"][ev] - ref["peak_t_s"][ev]) / 3600))),
                "network_median_nse_hourly_vs_ref": r4(np.nanmedian(nse_rows(r["q_hourly"], ref["q_hourly"])[ev])),
            }
        d[f"accuracy_vs_dt{REF_DT}_false"] = acc
        res["by_dt"][str(dt)] = d
    # dt -> 0 limit of the per-segment shift: -K*X with K = dx/ck (state at the dt=REF_DT
    # False peak). True's limit is a linear reservoir with K(1-X); False's the Muskingum ODE.
    _, _, x, km, ck, _ = mc_coefficients(ref["peak_q"], ref["depth_at_peak"], p, 1e-6)
    k_true = np.where(ck > 0, p.dx.to_numpy() / np.where(ck > 0, ck, 1), np.nan)
    evr = (ref["peak_q"] > 0) & np.isfinite(k_true)
    limit = {"travel_time_ratio_true_over_false_per_segment_(1-X)": pct((1 - x)[evr], (5, 25, 50, 75, 95)),
             "note": "dt -> 0: False -> Muskingum ODE (mean delay K per segment); True -> linear "
                     "reservoir with K(1-X) (mean delay K(1-X)); state at the dt=REF_DT False peak"}
    if storm:
        pred0 = tree_weighted_shift(tree, -k_true * x) / 3600.0
        o = int(np.flatnonzero(seg.is_outlet.to_numpy())[0])
        limit["outlet_predicted_centroid_shift_h_dt_to_0"] = r4(pred0[o])
    res["dt_to_zero_limit"] = limit
    res["kernel_check"] = kernel_check(p, ref["depth_at_peak"], ref["peak_q"], 300.0)
    return res, figdata


def build_tree(seg: pd.DataFrame) -> dict:
    link = seg["link"].to_numpy()
    pos = {l: i for i, l in enumerate(link)}
    down = np.array([pos.get(t, -1) for t in seg["to"].to_numpy()])
    topo = np.argsort(seg["topo_rank"].to_numpy())            # upstream before downstream
    L = seg["length_km"].to_numpy().astype(float)
    acc = L.copy()
    for i in topo:
        if down[i] >= 0:
            acc[down[i]] += acc[i]
    return {"down": down, "topo": topo, "L": L, "acc_km": acc}


def tree_weighted_shift(tree: dict, delta: np.ndarray) -> np.ndarray:
    """Storm-volume-weighted sum of per-segment shifts from each entry point to segment i.

    Storm water enters each segment j in proportion to L_j; water from j passes through
    every segment on the path j -> i (j and i included), each adding delta_k. So the
    expected centroid shift at i is B_i / A_i with A_i = sum_{j up of i} L_j and
    B_i = sum_u B_u + A_i * delta_i (u = immediate upstream segments).
    """
    down, topo, L = tree["down"], tree["topo"], tree["L"]
    A = L.copy()
    S = L * delta
    for i in topo:
        dn = down[i]
        if dn >= 0:
            A[dn] += A[i]
            S[dn] += S[i] + A[i] * delta[dn]
    return S / A


# ------------------------------------------------------------------ figures
def style(ax):
    ax.grid(True, color="#e6e5e0", linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#b5b4ad")
    ax.tick_params(colors=MUTED, labelsize=8)


def fig_outlet(figs: dict, path: Path):
    fig, axes = plt.subplots(len(CASES), len(DTS), figsize=(13, 6.2))
    for i, case in enumerate(CASES):
        seg = figs[case]["seg"]
        tr, qr = outlet_series(load(case, REF_DT, False), seg)
        for j, dt in enumerate(DTS):
            ax = axes[i, j]
            style(ax)
            a, b = figs[case]["runs"][dt]
            t, qa = outlet_series(a, seg)
            _, qb = outlet_series(b, seg)
            if dt != REF_DT:
                ax.plot(tr, qr, color=GRAY, lw=1.2, ls=(0, (3, 2)), label=f"False, dt = {REF_DT} s")
            ax.plot(t, qb, color=BLUE, lw=2, label="False: current-step inflow (T-Route config default)")
            ax.plot(t, qa, color=ORANGE, lw=2, label="True: short-time-step assumption on (WRF-Hydro/NWM)")
            if i == 0:
                ax.set_title(f"dt = {dt} s", fontsize=10, color=INK)
            if j == 0:
                ax.set_ylabel(f"{case}\noutlet flow (m³/s)", fontsize=9, color=INK)
            if i == len(CASES) - 1:
                ax.set_xlabel("hours after t0", fontsize=9, color=INK)
        lo = min(ax.get_ylim()[0] for ax in axes[i])
        hi = max(ax.get_ylim()[1] for ax in axes[i])
        for ax in axes[i]:
            ax.set_ylim(lo, hi)
    h, l = axes[0, 1].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=3, frameon=False, fontsize=9, bbox_to_anchor=(0.5, 0.965))
    fig.suptitle("Outlet hydrographs, assume_short_ts = True (short-time-step assumption on) vs False (T-Route CIROH-UA d29f663)",
                 y=0.995, fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_distance(figs: dict, path: Path):
    case = STORM[0]
    ms = figs[case]["mainstem"]
    fig, axes = plt.subplots(3, 1, figsize=(9, 10), sharex=True)
    for dt in DTS:
        m = ms[dt]
        c = RAMP[dt]
        ev, cp = m["ev"], m["complete"]
        axes[0].plot(m["dist"][ev], m["peak_shift"][ev], color=c, lw=2, label=f"dt = {dt} s")
        axes[1].plot(m["dist"][cp], m["cen_meas"][cp], color=c, lw=2, label=f"dt = {dt} s, measured")
        axes[1].plot(m["dist"], m["cen_pred"], color=c, lw=1.2, ls=(0, (3, 2)))
        axes[2].plot(m["dist"][ev], m["rel"][ev], color=c, lw=2)
    for ax in axes:
        style(ax)
        ax.axhline(0, color="#b5b4ad", lw=0.8)
    axes[0].invert_xaxis()
    axes[0].set_ylabel("peak-time shift\nTrue − False (h)", fontsize=9, color=INK)
    axes[1].set_ylabel("centroid shift, True − False (h)\nsolid: measured · dashed: predicted", fontsize=9, color=INK)
    axes[2].set_ylabel("peak flow difference\n(True − False)/False (%)", fontsize=9, color=INK)
    axes[2].set_xlabel("distance upstream of the outlet along the mainstem (km)", fontsize=9, color=INK)
    axes[0].legend(frameon=False, fontsize=8, ncol=4)
    fig.suptitle(f"{case}: short-time-step assumption on (True) vs off (False) along the longest flow path\n"
                 "negative shift = True arrives earlier", fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fig_accuracy(res: dict, path: Path):
    case = STORM[0]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    key_acc = f"accuracy_vs_dt{REF_DT}_false"
    for ax, key, lab in ((axes[0], "outlet_peak_err_pct", "outlet peak-flow error (%)"),
                         (axes[1], "outlet_peak_time_err_h", "outlet peak-time error (h)")):
        style(ax)
        for name, c in (("false", BLUE), ("true", ORANGE)):
            y = [res[case]["by_dt"][str(dt)][key_acc][name][key] for dt in DTS]
            ax.plot(DTS, y, color=c, lw=2, marker="o", ms=6, label="True: short-time-step assumption on (WRF-Hydro/NWM)" if name == "true"
                    else "False: current-step inflow (T-Route config default)")
        ax.set_xscale("log")
        ax.set_xticks(DTS, [str(d) for d in DTS])
        ax.set_xlabel("routing timestep dt (s)", fontsize=9, color=INK)
        ax.set_ylabel(lab, fontsize=9, color=INK)
        ax.axhline(0, color="#b5b4ad", lw=0.8)
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle(f"{case}: outlet error against False at dt = {REF_DT} s",
                 fontsize=11, color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> int:
    OUT.mkdir(exist_ok=True)
    res, figs = {}, {}
    for case in CASES:
        res[case], figs[case] = analyze_case(case)
        print(f"ok      analyzed {case}")
    fig_outlet(figs, OUT / "fig_outlet_hydrographs.png")
    fig_distance(figs, OUT / "fig_shift_vs_distance.png")
    fig_accuracy(res, OUT / "fig_accuracy_vs_dt.png")
    summary = {"experiment": "repro/short_ts_switch", "reference_dt_s": REF_DT, "dts_s": DTS,
               "cases": res}
    (OUT / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    # compact table for the README
    rows = []
    for case in CASES:
        for dt in DTS:
            d = res[case]["by_dt"][str(dt)]
            o, s = d["outlet"], d["segments"]
            rows.append({"case": case, "dt": dt, "outlet_peak_F": o["peak_false_m3s"],
                         "outlet_peak_T": o["peak_true_m3s"], "peak_diff_%": o["peak_rel_diff_pct"],
                         "shift_h": o["peak_time_shift_h"], "NSE": o["nse_true_vs_false"],
                         "KGE": o["kge_true_vs_false"], "maxdiff_%pk": o["max_abs_diff_pct_of_false_peak"],
                         "seg_shift_p50": s["peak_time_shift_h"].get("p50"),
                         "seg_rel_p5": s["peak_rel_diff_pct"].get("p5"),
                         "seg_rel_p95": s["peak_rel_diff_pct"].get("p95"),
                         "Cn_p50": d["courant_at_peak_false"].get("p50"),
                         "C2<0": d["c2_at_peak_false"]["frac_negative"],
                         "cen_meas_out": d.get("centroid", {}).get("outlet_measured_shift_h"),
                         "cen_pred_out": d.get("centroid", {}).get("outlet_predicted_shift_h")})
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "summary_table.csv", index=False)
    print(tab.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
