"""Extension of courant_test.ipynb to routing timesteps up to 4 h (14400 s).

Stretches Wlostowski's test to 3600 s and up to 4 h, as was done for ../short_ts_switch,
and reports the X and K values the Cunge closure produces.

Same channel, kernel, driver and forcing shape as the notebook (run_experiment.py), with
  * dt = 30 ... 14400 s and a 120-h run, so the wave clears the outlet at every dt;
  * two forcing variants, kept separate:
      point   - the notebook's own formula (np.linspace time axis, Gaussian point
                samples rescaled so the largest sample is the 500 m3/s peak). At large dt
                this changes the injected volume and timing (aliasing).
      volume  - the same Gaussian averaged over each step, so every dt injects the same
                pulse volume (up to the part beyond the run);
  * three smaller variants (volume forcing): the short-time-step assumption enabled
    (quc = qup in the driver; T-Route assume_short_ts=True / WRF-Hydro), and the same
    channel at s0 = 1e-4 and 1e-5 with depth initialized at the kernel's normal depth.
The compiled Fortran produces every hydrograph. kernel_port.py runs beside it on the same
inputs and records what the kernel's Cunge closure (secant2_h) produced: Ck, dx/Ck, Km,
X from both secant estimates (clamped and unclamped), the reference discharge, the cell
Reynolds number D = Q/(B*S0*Ck*dx) and C1..C4. Its outflow agreement with the compiled
kernel is recorded per run.

Nothing in the original reproduction (run_experiment.py, expected/courant_test.json) is
changed. As a consistency check, this driver also reruns the notebook configuration
(15 h, dt 30..600 s) and confirms it reproduces run_experiment.reach_sim exactly.

Usage: run_extended.py [--jobs N] [--write-expected]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
CLOSURE_DIR = RESULTS / "extended_closure"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "build" / "courant"))

DT_LIST = [30, 60, 120, 300, 600, 900, 1200, 1800, 3600, 5400, 7200, 10800, 14400]
DURATION = 120 * 3600            # multiple of every dt above; see README for the choice
NOTEBOOK_DURATION = 15 * 3600
DX, RCHLEN = 2000, 20000
Q0, H0_NOTEBOOK = 2000, 2.78
T_PK, SCALE, PK_SCALE = 6 * 3600, 0.5 * 3600, 0.25
PULSE_VOLUME = PK_SCALE * Q0 * SCALE * math.sqrt(2 * math.pi)   # m3 above baseflow

VARIANTS = {
    # name: (forcing, s0 or None for the notebook's, short_ts, label)
    "core_point":  ("point",  None, False, "core, point-sampled forcing (notebook formula)"),
    "core_volume": ("volume", None, False, "core, volume-consistent forcing"),
    "short_ts":    ("volume", None, True,  "short-time-step assumption enabled (quc = qup)"),
    "slope_1e-4":  ("volume", 1e-4, False, "s0 = 1e-4, normal-depth start"),
    "slope_1e-5":  ("volume", 1e-5, False, "s0 = 1e-5, normal-depth start"),
}
FIELDS = ["Ck", "dx_over_Ck", "Km", "X1_raw", "X1", "X2_raw", "X2", "qref", "width",
          "D_cell", "C1", "C2", "C3", "C4", "courant_closure", "iterations", "guard", "h_closure"]


def channel(s0=None):
    from run_experiment import params
    p = dict(params)
    if s0 is not None:
        p["s0"] = s0
    return p


def manning_q(h, p):
    """Discharge at depth h from the kernel's own conveyance (secant2_h, L363-365), float64."""
    z = 1.0 / p["cs"]
    bw, tw, twcc, n, ncc, s0 = p["bw"], p["tw"], p["twcc"], p["n"], p["ncc"], p["s0"]
    bfd = (tw - bw) / (2 * z)
    if h > bfd:
        area, areac = (bw + bfd * z) * bfd, twcc * (h - bfd)
        wp, wpc = bw + 2 * bfd * math.sqrt(1 + z * z), twcc + 2 * (h - bfd)
    else:
        area, areac = (bw + h * z) * h, 0.0
        wp, wpc = bw + 2 * h * math.sqrt(1 + z * z), 0.0
    r = (area + areac) / (wp + wpc)
    return (1 / ((wp * n + wpc * ncc) / (wp + wpc))) * (area + areac) * r ** (2 / 3) * math.sqrt(s0)


def normal_depth(q, p):
    return brentq(lambda h: manning_q(h, p) - q, 1e-3, 100.0, xtol=1e-10)


def forcing(kind, dt, duration, pulse=True):
    nt = int(duration / dt)
    if not pulse:
        return np.full(nt, float(Q0))
    q_pk = PK_SCALE * Q0
    if kind == "point":     # notebook cell 5, verbatim formula
        x = np.linspace(0, duration, int(duration / dt))
        y = norm.pdf(x, T_PK, SCALE)
        return y * q_pk / max(y) + Q0
    if kind == "volume":    # mean of the same Gaussian over the step ending at t*dt
        t_end = np.arange(nt) * dt
        frac = norm.cdf(t_end, T_PK, SCALE) - norm.cdf(t_end - dt, T_PK, SCALE)
        ql = Q0 + q_pk * SCALE * math.sqrt(2 * math.pi) * frac / dt
        ql[0] = Q0 + q_pk * math.exp(-0.5 * ((0 - T_PK) / SCALE) ** 2)   # t = 0 is never routed
        return ql
    raise ValueError(kind)


def simulate(dt, duration, p, h0, ql0, short_ts=False, shadow=True):
    """The notebook's reach_sim loop with optional quc = qup, plus the shadow port."""
    from mc_sseg_stime_anw import muskingcunge_module as mc
    from kernel_port import Kernel
    ns, nt = int(RCHLEN / DX), int(duration / dt)
    flow = np.full((ns, nt), np.nan)
    depth = np.full((ns, nt), np.nan)
    courant = np.full((ns, nt), np.nan)
    xout = np.full((ns, nt), np.nan)
    ql = np.zeros((ns, nt))
    ql[0, :] = ql0
    flow[:, 0], depth[:, 0] = Q0, h0
    internals = {f: np.full((ns, nt), np.nan, dtype=np.float32) for f in FIELDS} if shadow else None
    port_q = np.full((ns, nt), np.nan) if shadow else None
    port_d = np.full((ns, nt), np.nan) if shadow else None
    port_x = np.full((ns, nt), np.nan) if shadow else None
    kern = Kernel("zero") if shadow else None
    args_c = (p["bw"], p["tw"], p["twcc"], p["n"], p["ncc"], p["cs"], p["s0"], 0)
    for t in range(1, nt):
        for x in range(ns):
            qup = 0 if x == 0 else flow[x - 1, t - 1]
            quc = 0 if x == 0 else (flow[x - 1, t - 1] if short_ts else flow[x - 1, t])
            qdp = flow[x, t - 1]
            q, v, d, ck, cn, X = mc.muskingcungenwm(dt, qup, quc, qdp, ql[x, t], DX, *args_c, depth[x, t - 1])
            flow[x, t], depth[x, t], courant[x, t], xout[x, t] = q, d, cn, X
            if shadow:
                pq, pv, pd, pck, pcn, pX, inn = kern(dt, qup, quc, qdp, ql[x, t], DX, *args_c, depth[x, t - 1])
                port_q[x, t], port_d[x, t], port_x[x, t] = pq, pd, pX
                for f in FIELDS:
                    internals[f][x, t] = inn[f]
    return {"flow": flow, "depth": depth, "courant": courant, "X": xout, "ql": ql,
            "internals": internals, "port_q": port_q, "port_d": port_d, "port_x": port_x}


def _stats(a):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    if a.size == 0:
        return None
    q = np.percentile(a, [0, 5, 50, 95, 100])
    return {"min": q[0], "p05": q[1], "median": q[2], "p95": q[3], "max": q[4], "n": int(a.size)}


def _frac(mask, total):
    return float(np.count_nonzero(mask)) / total if total else float("nan")


def run_job(job):
    name, dt = job
    kind, s0, short_ts, _ = VARIANTS[name]
    p = channel(s0)
    h0 = H0_NOTEBOOK if s0 is None else normal_depth(Q0, p)
    r = simulate(dt, DURATION, p, h0, forcing(kind, dt, DURATION), short_ts)
    base = simulate(dt, DURATION, p, h0, forcing(kind, dt, DURATION, pulse=False), short_ts, shadow=False)
    flow, inn, ql = r["flow"], r["internals"], r["ql"][0]
    nt = flow.shape[1]
    time_h = np.arange(nt) * dt / 3600
    q_out, q_base = flow[-1], base["flow"][-1]
    ex_out = q_out - q_base
    ex_in = ql - Q0
    v_in = float(np.sum(ex_in[1:]) * dt)
    v_out = float(np.sum(ex_out[1:]) * dt)
    k_pk = int(np.argmax(q_out))
    pk_ex_out = float(ex_out[k_pk])
    pk_ex_in = float(np.max(ex_in[1:]))
    cen_in = float(np.sum((np.arange(1, nt) * dt - dt / 2) * ex_in[1:]) / np.sum(ex_in[1:])) / 3600
    cen_out = float(np.sum(np.arange(1, nt) * dt * ex_out[1:]) / np.sum(ex_out[1:])) / 3600
    sel = (slice(None), slice(1, None))          # all segments, routed steps
    tot = flow[sel].size
    X2raw, X1raw = inn["X2_raw"][sel], inn["X1_raw"][sel]
    floor2, cap2 = X2raw < 0.25, X2raw > 0.5
    clamp = inn["dx_over_Ck"][sel] < dt
    pq = r["port_q"][sel]
    rel_q = np.abs(pq - flow[sel]) / np.abs(flow[sel])
    rel_d = np.abs(r["port_d"][sel] - r["depth"][sel]) / np.abs(r["depth"][sel])
    at_pk = {f: float(inn[f][-1, k_pk]) for f in FIELDS}
    at_pk["courant_kernel"] = float(r["courant"][-1, k_pk])
    # baseflow state (last step of the no-pulse run's outlet is representative; use the
    # pulse run's step 1 at the outlet, before the wave arrives)
    at_base = {f: float(inn[f][-1, 1]) for f in ("Ck", "dx_over_Ck", "Km", "X2_raw", "X2", "D_cell")}
    summary = {
        "variant": name, "dt_s": dt, "n_timesteps": nt, "h0_m": h0, "s0": p["s0"],
        "forcing": kind, "assume_short_ts": short_ts,
        "max_courant": float(np.nanmax(r["courant"])),
        "courant_at_outlet_peak": float(r["courant"][-1, k_pk]),
        "peak_time_h": float(time_h[k_pk]), "peak_flow_cms": float(q_out[k_pk]),
        "peak_excess_out_cms": pk_ex_out, "peak_excess_forcing_cms": pk_ex_in,
        "attenuation_vs_forcing": 1 - pk_ex_out / pk_ex_in,
        "injected_excess_volume_m3": v_in, "injected_over_pulse_volume": v_in / PULSE_VOLUME,
        "outlet_excess_volume_m3": v_out, "volume_ratio_out_over_in": v_out / v_in,
        "centroid_in_h": cen_in, "centroid_out_h": cen_out, "travel_time_centroid_h": cen_out - cen_in,
        "end_residual_over_peak_excess": float(abs(ex_out[-1]) / pk_ex_out),
        "baseline_drift_max_cms": float(np.max(np.abs(q_base[1:] - Q0))),
        "closure": {
            "frac_Km_clamped_to_dt": _frac(clamp, tot),
            "frac_X2_floor_0p25": _frac(floor2, tot), "frac_X2_cap_0p5": _frac(cap2, tot),
            "frac_X1_floor_0": _frac(X1raw < 0, tot), "frac_X1_cap_0p5": _frac(X1raw > 0.5, tot),
            "frac_C2_negative": _frac(inn["C2"][sel] < 0, tot),
            "frac_C3_negative": _frac(inn["C3"][sel] < 0, tot),
            "frac_negative_flow_guard": _frac(inn["guard"][sel] > 0, tot),
            "X2_raw_where_floored": _stats(X2raw[floor2]),
            "Km_s": _stats(inn["Km"][sel]), "dx_over_Ck_s": _stats(inn["dx_over_Ck"][sel]),
            "Ck_ms": _stats(inn["Ck"][sel]),
            "X1": _stats(inn["X1"][sel]), "X1_raw": _stats(X1raw),
            "X2": _stats(inn["X2"][sel]), "X2_raw": _stats(X2raw),
            "courant_kernel": _stats(r["courant"][sel]), "D_cell": _stats(inn["D_cell"][sel]),
            "C1": _stats(inn["C1"][sel]), "C2": _stats(inn["C2"][sel]),
            "C3": _stats(inn["C3"][sel]), "C4": _stats(inn["C4"][sel]),
            "iterations": _stats(inn["iterations"][sel]),
            "at_outlet_peak": at_pk, "at_outlet_baseflow_step1": at_base,
        },
        "port_agreement": {
            "max_rel_diff_flow": float(np.nanmax(rel_q)), "max_rel_diff_depth": float(np.nanmax(rel_d)),
            "frac_flow_bit_identical": _frac(pq == flow[sel], tot),
            "max_abs_diff_X": float(np.nanmax(np.abs(r["port_x"][sel] - r["X"][sel]))),
        },
    }
    CLOSURE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CLOSURE_DIR / f"{name}_dt{dt}.npz", flow=flow.astype(np.float32),
                        depth=r["depth"].astype(np.float32), courant=r["courant"].astype(np.float32),
                        ql0=ql.astype(np.float32), **inn)
    outlet = {"time_h": time_h, "ql0": ql, "q_out": q_out, "q_base": q_base,
              "depth_out": r["depth"][-1], "courant_out": r["courant"][-1],
              "Km_out": inn["Km"][-1], "X2_out": inn["X2"][-1]}
    return name, dt, summary, outlet


def notebook_consistency():
    """The extended driver at the notebook's 15 h / point forcing must equal reach_sim."""
    import run_experiment as R
    out = {}
    for dt in R.dt_array:
        ref = R.reach_sim(dt, R.dx, R.rchlen, R.duration, R.params, R.q0, R.h0, R.t_pk, R.scale, R.pk_scale)[0]
        got = simulate(dt, NOTEBOOK_DURATION, channel(), H0_NOTEBOOK,
                       forcing("point", dt, NOTEBOOK_DURATION), shadow=False)["flow"]
        out[str(dt)] = float(np.nanmax(np.abs(ref - got)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0, help="worker processes (default: CPU count)")
    ap.add_argument("--write-expected", action="store_true",
                    help="write expected/extended.json from this run (regression baseline)")
    a = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    jobs = [(v, dt) for v in VARIANTS for dt in DT_LIST]
    # largest jobs (small dt) first for load balance
    jobs.sort(key=lambda j: j[1])
    print(f"extended sweep: {len(VARIANTS)} variants x {len(DT_LIST)} dt, {DURATION / 3600:.0f} h")
    with ProcessPoolExecutor(max_workers=a.jobs or None) as ex:
        res = list(ex.map(run_job, jobs))
    runs = {v: {} for v in VARIANTS}
    outlets = {v: {} for v in VARIANTS}
    for name, dt, s, o in res:
        runs[name][dt] = s
        outlets[name][dt] = o
    # changes relative to dt = 30 s of the same variant
    for v in VARIANTS:
        ref = runs[v][DT_LIST[0]]
        for dt in DT_LIST:
            s = runs[v][dt]
            s["peak_time_shift_vs_dt30_h"] = s["peak_time_h"] - ref["peak_time_h"]
            s["peak_flow_change_vs_dt30_pct"] = 100 * (s["peak_flow_cms"] / ref["peak_flow_cms"] - 1)
            s["peak_excess_change_vs_dt30_pct"] = 100 * (s["peak_excess_out_cms"] / ref["peak_excess_out_cms"] - 1)
            s["travel_time_change_vs_dt30_h"] = s["travel_time_centroid_h"] - ref["travel_time_centroid_h"]
            print(f"{v:12s} dt={dt:6d}  maxC={s['max_courant']:7.3f}  peak {s['peak_time_h']:6.2f} h "
                  f"{s['peak_flow_cms']:8.2f}  Vout/Vin={s['volume_ratio_out_over_in']:.4f}  "
                  f"Vin/Vpulse={s['injected_over_pulse_volume']:.3f}  "
                  f"Kclamp={s['closure']['frac_Km_clamped_to_dt']:.2f}  "
                  f"Xfloor={s['closure']['frac_X2_floor_0p25']:.2f}  "
                  f"port={s['port_agreement']['max_rel_diff_flow']:.1e}")
    cons = notebook_consistency()
    print("notebook configuration through the extended driver, max |diff| vs reach_sim:", cons)
    normal = {v: (VARIANTS[v][1] or channel()["s0"], normal_depth(Q0, channel(VARIANTS[v][1])))
              for v in ("core_volume", "slope_1e-4", "slope_1e-5")}
    out = {
        "experiment": "courant_test_extended",
        "parameters": {"dt_list_s": DT_LIST, "duration_s": DURATION, "dx_m": DX, "rchlen_m": RCHLEN,
                       "q0_cms": Q0, "h0_notebook_m": H0_NOTEBOOK, "t_pk_s": T_PK, "scale_s": SCALE,
                       "pk_scale": PK_SCALE, "pulse_volume_m3": PULSE_VOLUME,
                       "variants": {k: {"forcing": f, "s0": s0 if s0 is not None else channel()["s0"],
                                        "assume_short_ts": st, "label": lab}
                                    for k, (f, s0, st, lab) in VARIANTS.items()},
                       "normal_depth_m_at_q0": {k: {"s0": s, "h_normal_m": h} for k, (s, h) in normal.items()},
                       "kernel_port_qj0_mode": "zero"},
        "notebook_consistency_max_abs_diff_cms": cons,
        "runs": {v: [runs[v][dt] for dt in DT_LIST] for v in VARIANTS},
    }
    (RESULTS / "extended_summary.json").write_text(json.dumps(out, indent=1, default=float) + "\n")
    with open(RESULTS / "extended_outlet.csv", "w") as f:
        f.write("variant,dt_s,time_h,ql_segment0_cms,q_outlet_cms,q_outlet_baseline_cms,"
                "depth_outlet_m,courant_outlet,Km_outlet_s,X_outlet\n")
        for v in VARIANTS:
            for dt in DT_LIST:
                o = outlets[v][dt]
                cols = [o[c] for c in ("time_h", "ql0", "q_out", "q_base", "depth_out", "courant_out",
                                       "Km_out", "X2_out")]
                for k in range(len(o["time_h"])):
                    f.write(f"{v},{dt}," + ",".join(repr(float(c[k])) for c in cols) + "\n")
    if a.write_expected:
        write_expected(out)
    print(f"wrote {RESULTS}/extended_summary.json, extended_outlet.csv, extended_closure/*.npz")
    return 0


def write_expected(out):
    import datetime
    base = {}
    for v, rs in out["runs"].items():
        base[v] = {str(s["dt_s"]): {
            "max_courant": round(s["max_courant"], 6), "peak_time_h": s["peak_time_h"],
            "peak_flow_cms": round(s["peak_flow_cms"], 4),
            "volume_ratio_out_over_in": round(s["volume_ratio_out_over_in"], 6),
            "injected_over_pulse_volume": round(s["injected_over_pulse_volume"], 6),
            "frac_Km_clamped_to_dt": round(s["closure"]["frac_Km_clamped_to_dt"], 6),
            "frac_X2_floor_0p25": round(s["closure"]["frac_X2_floor_0p25"], 6)} for s in rs}
    exp = {
        "_source": ("Regression baseline from this extension's own run (run_extended.py --write-expected), "
                    f"{datetime.date.today().isoformat()}, macOS arm64, gfortran 15.2.0. There is no 2020 "
                    "notebook output for dt > 600 s; these values guard against drift and are not an external "
                    "reference."),
        "_tolerances": {
            "peak_time_h": "+-1 output interval (dt/3600 h)",
            "peak_flow_cms": "rtol 1e-4", "max_courant": "rtol 1e-4",
            "volume_ratio_out_over_in": "abs 1e-4", "injected_over_pulse_volume": "abs 1e-6",
            "frac_Km_clamped_to_dt / frac_X2_floor_0p25": "abs 0.01",
        },
        "self_consistency": {
            "notebook_consistency_max_abs_diff_cms": 0.0,
            "port_max_rel_diff_flow": 1e-5, "port_max_rel_diff_depth": 1e-5,
            "end_residual_over_peak_excess_max": 1e-3,
            "volume_forcing_injected_over_pulse_volume_abs_tol": 1e-6,
            "baseline_drift_max_cms": 0.05,
        },
        "baseline": base,
    }
    (HERE / "expected" / "extended.json").write_text(json.dumps(exp, indent=1) + "\n")
    print("wrote expected/extended.json")


if __name__ == "__main__":
    sys.exit(main())
