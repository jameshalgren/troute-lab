"""EXPLORATORY: port of mc_numerical_dispersion.ipynb (awlostowski-noaa/t-route @ de52970,
branch segment-merge, 2020-09-07).

What is original and what is ported:
  * Numerical kernel: the original Fortran MCsingleSegStime_f2py_NOLOOP.f90 and its
    original bind(c) wrapper pyMCsingleSegStime_NoLoop.f90, compiled with the
    notebook's gfortran flags (build_kernels.py) and called through ctypes.
  * Network decomposition: the original nhd_network.py, imported unmodified from data/.
  * nhd_io.replace_downstreams: ported verbatim (the module imports geopandas).
  * mc_reach.compute_network / compute_reach_kernel (Cython): ported line by line to
    Python below, keeping float32 for every quantity the Cython code types as float.
  * Notebook cells 1-3 (sim, courant, the dt sweep): ported; pandas idioms adjusted only
    where pandas 3 forbids the 2020 form (float64 assignment into a float32 frame).
Run both settings of the short-timestep assumption (the saved notebook used False).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
from functools import partial
from itertools import chain
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
sys.path.insert(0, str(HERE / "data" / "dispersion"))
import nhd_network  # noqa: E402  (original, unmodified)

# Builds of the same, unmodified source (build_kernels.py). "notebook_flags" uses the
# notebook's flags (-O3 -fPIC); "init_zero" / "init_nan" add -finit-real=zero / =nan.
# The source reads the local variable AREAC before assigning it whenever depth <=
# bankfull (secant_h0, secant_h), so results depend on what is in that memory; the
# -finit-real builds make it deterministic. See README "Exploratory configuration".
VARIANTS = ("notebook_flags", "init_zero", "init_nan")
_kernel = None


def load_kernel(variant: str) -> None:
    global _kernel
    lib = ctypes.CDLL(str(HERE / "build" / f"dispersion_{variant}" / "libmc_segment_merge.so"))
    _kernel = lib.c_muskingcungenwm
    _kernel.argtypes = [ctypes.POINTER(ctypes.c_float)] * 18
    _kernel.restype = None

_IN = [ctypes.c_float() for _ in range(15)]
_OUT = [ctypes.c_float() for _ in range(3)]
_ARGS = [ctypes.byref(v) for v in _IN + _OUT]
f32 = np.float32


def muskingcunge(dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, velp, depthp):
    """mc_reach.muskingcunge: outputs zeroed, then c_muskingcungenwm. Returns (qdc, depthc, velc)."""
    for v, x in zip(_IN, (dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, velp, depthp)):
        v.value = x
    for v in _OUT:
        v.value = 0.0
    _kernel(*_ARGS)
    return _OUT[0].value, _OUT[2].value, _OUT[1].value  # qdc, depthc, velc


def compute_reach_kernel(qup, quc, nreach, input_buf, output_buf):
    """mc_reach.compute_reach_kernel (Cython), line by line.
    input_buf columns: qlat, dt, dx, bw, tw, twcc, n, ncc, cs, s0, qdp, velp, depthp"""
    for i in range(nreach):
        qlat, dt, dx, bw, tw, twcc, n, ncc, cs, s0, qdp, velp, depthp = input_buf[i, :13]
        qdc, depthc, velc = muskingcunge(dt, qup, quc, qdp, qlat, dx, bw, tw, twcc, n, ncc, cs, s0,
                                         velp, depthp)
        output_buf[i, 0] = qdc
        quc = f32(output_buf[i, 0])
        output_buf[i, 1] = velc
        output_buf[i, 2] = depthc
        qup = qdp


def compute_network(nsteps, reaches, connections, data_idx, data_cols, data_values, qlat_values,
                    assume_short_ts=False):
    """mc_reach.compute_network (Cython), ported. Same argument meaning and return value."""
    data_idx = np.asarray(data_idx)
    if qlat_values.shape[0] != data_idx.shape[0] or qlat_values.shape[1] != nsteps:
        raise ValueError("Qlat shape is incorrect")
    flowveldepth = np.zeros((data_idx.shape[0], nsteps * 3), dtype="float32")
    pos = {int(k): i for i, k in enumerate(data_idx)}           # binary_find equivalent
    colidx = {c: i for i, c in enumerate(data_cols)}
    scols = [colidx[c] for c in ["dt", "dx", "bw", "tw", "twcc", "n", "ncc", "cs", "s0"]]
    reach_rows = [[pos[s] for s in reach] for reach in reaches]
    us_rows = [[pos[s] for s in connections.get(reach[0], ())] for reach in reaches]
    maxlen = max(map(len, reaches))
    buf = np.empty((maxlen, 13), dtype="float32")
    out_buf = np.empty((maxlen, 3), dtype="float32")

    for timestep in range(nsteps):
        ts_offset = timestep * 3
        for srows, usrows in zip(reach_rows, us_rows):
            reachlen = len(srows)
            qup = f32(0.0)
            quc = f32(0.0)
            for u in usrows:
                quc = f32(quc + flowveldepth[u, ts_offset])
                if timestep > 0:
                    qup = f32(qup + flowveldepth[u, ts_offset - 3])
            bv = buf[:reachlen, :]
            bv[:, 0] = qlat_values[srows, timestep]
            for i, sc in enumerate(scols):
                bv[:, i + 1] = data_values[srows, sc]
            if timestep > 0:
                bv[:, 10] = flowveldepth[srows, ts_offset - 3]
                bv[:, 11] = flowveldepth[srows, ts_offset - 2]
                bv[:, 12] = flowveldepth[srows, ts_offset - 1]
            else:
                bv[:, 10:13] = 0.0
            if assume_short_ts:
                quc = qup
            ov = out_buf[:reachlen, :]
            compute_reach_kernel(qup, quc, reachlen, bv, ov)
            for i in range(3):
                flowveldepth[srows, ts_offset + i] = ov[:, i]
    return np.asarray(data_idx, dtype=np.intp), flowveldepth


def replace_downstreams(data, downstream_col, terminal_code):
    """nhd_io.replace_downstreams @ de52970, verbatim."""
    ds0_mask = data[downstream_col] == terminal_code
    new_data = data.copy()
    new_data.loc[ds0_mask, downstream_col] = ds0_mask.index[ds0_mask]
    new_data.loc[~data[downstream_col].isin(data.index), downstream_col] *= -1
    return new_data


def sim(dx, dt, q_baseflow, q_pk, short_tstep_assumption):
    """Notebook cell 1 `sim`, ported."""
    L = 20 * (1000)
    nsegs = round(L / dx)
    n_days = 6
    len_sim = n_days * (24 * 60 * 60)
    nts = round(len_sim / dt)

    link_start = 8815967
    headwaters = [8815960, 8815961]
    linkID = list(range(link_start, link_start + nsegs, 1))
    linkID = headwaters + linkID
    headwater_to = [link_start, link_start]
    toID = list(range(link_start + 1, link_start + nsegs, 1))
    toID.append(0)
    toID = headwater_to + toID

    d = {'link': linkID, 'to': toID, 'dx': [dx] * (nsegs + 2),
         'n': [0.028] * (nsegs + 2), 'ncc': [0.031] * (nsegs + 2), 's0': [0.0018] * (nsegs + 2),
         'bw': [112] * (nsegs + 2), 'tw': [448] * (nsegs + 2), 'twcc': [623] * (nsegs + 2),
         'MusK': [3600.0] * (nsegs + 2), 'MusX': [0.2] * (nsegs + 2), 'cs': [1.40] * (nsegs + 2)}
    df = pd.DataFrame(data=d).set_index('link').sort_index()
    df = replace_downstreams(df, 'to', 0)

    t_pk = 2 * 24 * (60 * 60)
    width = 2 * (60 * 60)
    x = np.linspace(0, len_sim, round(len_sim / dt))
    y = norm.pdf(x, t_pk, width)
    y_scale = y * q_pk / max(y) + q_baseflow
    # notebook: float32 DataFrame of zeros, row 0 (link 8815960) := y_scale
    ql_arr = np.zeros((len(linkID), round(len_sim / dt)), dtype=np.float32)
    ql_arr[0, :] = y_scale
    ql = pd.DataFrame(ql_arr, index=linkID, columns=range(round(len_sim / dt)))

    conn = nhd_network.extract_connections(df, 'to')
    rconn = nhd_network.reverse_network(conn)
    subnets = nhd_network.reachable_network(rconn, check_disjoint=False)
    subreaches = {}
    for tw, net in subnets.items():
        path_func = partial(nhd_network.split_at_junction, net)
        subreaches[tw] = nhd_network.dfs_decomposition(net, path_func)
    tail_water = max(linkID)
    reach = subreaches[tail_water]
    r = list(filter(None, chain.from_iterable(reach)))

    df["dt"] = dt
    df = df.astype("float32")
    data_sub = df.loc[r, ["dt", "dx", "bw", "tw", "twcc", "n", "ncc", "cs", "s0"]].sort_index()
    qlat_sub = ql.loc[r].sort_index()

    idx, fvd = compute_network(nts, reach, subnets[tail_water], data_sub.index.values.astype("int64"),
                               data_sub.columns.values, data_sub.values,
                               qlat_sub.values.astype("float32"), assume_short_ts=short_tstep_assumption)

    fdv_columns = pd.MultiIndex.from_product([range(nts), ["q", "v", "d"]])
    flowveldepth = pd.DataFrame(fvd, index=idx, columns=fdv_columns).sort_index()

    def extract(var):
        t = flowveldepth.loc[:, (slice(None), var)]
        t = t.T.reset_index(level=[0, 1])
        t = t.rename(columns={"level_0": "Timestep", "level_1": "Parameter"})
        t['Time (d)'] = ((t.Timestep + 1) * dt) / (24 * 60 * 60)
        return t.set_index('Time (d)').drop(["Timestep", "Parameter"], axis=1)

    flows = extract("q")
    forcing = flows.loc[:, flows.columns.min()]
    flows = flows.drop(headwaters, axis='columns')
    depth = extract("d").drop(headwaters, axis='columns')
    return flows, depth, df, forcing, reach


def courant(depth, df, dt, dx):
    """Notebook cell 2 `courant`, verbatim apart from formatting."""
    z = 1.0 / df.loc[depth.columns].cs
    bfd = (df.loc[depth.columns].tw - df.loc[depth.columns].bw) / (2 * z)
    Ck = pd.DataFrame(0, index=depth.index, columns=depth.columns, dtype=np.float32)
    for idx_s, s in enumerate(depth.columns, 0):
        d_numpy = depth.loc[:, s].to_numpy()
        t_gt_bf = np.nonzero(d_numpy > bfd[s])
        t_lt_bf = np.nonzero(d_numpy < bfd[s])
        idx_gt_bf = depth.iloc[t_gt_bf[0], idx_s].index
        idx_lt_bf = depth.iloc[t_lt_bf[0], idx_s].index
        h = depth.loc[idx_gt_bf, s]
        AREA = (df.loc[s].bw + bfd * z[s]) * bfd
        AREAC = (df.loc[s].twcc * (h - bfd))
        WP = (df.loc[s].bw + 2 * bfd * np.sqrt(1 + z[s] * z[s]))
        WPC = df.loc[s].twcc + (2 * (h - bfd))
        R = (AREA + AREAC) / (WP + WPC)
        ck = ((np.sqrt(df.loc[s].s0) / df.loc[s].n) * ((5 / 3) * R ** (2 / 3) -
              ((2 / 3) * R ** (5 / 3) * (2 * np.sqrt(1 + z[s] * z[s]) / (df.loc[s].bw + 2 * bfd * z[s])))) * AREA
              + ((np.sqrt(df.loc[s].s0) / (df.loc[s].ncc)) * (5 / 3) * (h - bfd) ** (2 / 3)) * AREAC) / (AREA + AREAC)
        if len(idx_gt_bf):
            Ck.loc[idx_gt_bf, s] = ck
        AREA = (df.loc[s].bw + depth.loc[idx_lt_bf, s] * z[s]) * depth.loc[idx_lt_bf, s]
        WP = (df.loc[s].bw + 2 * depth.loc[idx_lt_bf, s] * np.sqrt(1 + z[s] * z[s]))
        R = AREA / WP
        ck = (np.sqrt(df.loc[s].s0) / df.loc[s].n) * \
            ((5 / 3) * R ** (2 / 3) - ((2 / 3) * R ** (5 / 3) *
             (2 * np.sqrt(1 + z[s] * z[s]) / (df.loc[s].bw + 2 * depth.loc[idx_lt_bf, s] * z[s]))))
        Ck.loc[idx_lt_bf, s] = ck.astype(np.float32)
    C = Ck * (dt / dx)
    return C


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dt", type=int, nargs="*", default=[5, 10, 30, 60, 120, 400, 600])
    ap.add_argument("--dx", type=float, default=300)
    ap.add_argument("--short-ts", choices=["false", "true", "both"], default="both")
    ap.add_argument("--variant", choices=VARIANTS, default="init_zero")
    args = ap.parse_args()
    load_kernel(args.variant)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    RESULTS.mkdir(exist_ok=True)
    dx, q_baseflow, q_pk = args.dx, 100, 150
    settings = {"false": [False], "true": [True], "both": [False, True]}[args.short_ts]
    out = {"experiment": "mc_numerical_dispersion (exploratory)", "kernel_build_variant": args.variant,
           "dx_m": dx,
           "q_baseflow_cms": q_baseflow, "q_pk_cms": q_pk, "runs": []}
    fig, axes = plt.subplots(len(settings), 2, figsize=(13, 4.5 * len(settings)), squeeze=False)
    for row, sts in enumerate(settings):
        for i, dt in enumerate(args.dt):
            flow, depth, df, forcing, reach = sim(dx, dt, q_baseflow, q_pk, sts)
            C = courant(depth, df, dt, dx)
            outlet = flow.columns.max()
            courant_peak = C[C.index > 1.5].loc[:, C.columns.max()].max()
            qpk = flow.loc[:, outlet].max()
            dmx = depth.loc[:, outlet].max()
            tpk = flow.loc[:, outlet].idxmax()
            print(f"assume_short_ts={sts} Simulation {i} - Timestep: {dt} Spatial step: {dx:g}")
            print(f"  courant number at peakflow = {courant_peak!r}  maximum depth = {dmx!r}  "
                  f"peak flow = {qpk!r} at {tpk:.4f} d")
            out["runs"].append({"assume_short_ts": sts, "sim": i, "dt_s": dt,
                                "n_segments": int(len(flow.columns)), "n_timesteps": int(len(flow)),
                                "courant_at_peakflow": float(courant_peak),
                                "max_depth_outlet_m": float(dmx), "peak_flow_outlet_cms": float(qpk),
                                "peak_time_outlet_d": float(tpk),
                                "max_depth_any_segment_m": float(np.nanmax(depth.values))})
            ax_q, ax_d = axes[row]
            if i == 0:
                ax_q.plot(forcing.index, forcing.values, "--", color="k", label="Forcing")
            ax_q.plot(flow.index, flow[outlet].values, label=f"Sim{i}: dt = {dt} s")
            ax_d.plot(depth.index, depth[outlet].values, label=f"Sim{i}: dt = {dt} s")
        ax_q.set_xlim([1, 3]); ax_q.set_xlabel("Time (days)"); ax_q.set_ylabel("Outlet flow (cms)")
        ax_q.set_title(f"assume_short_ts = {sts}", fontsize=10); ax_q.legend(fontsize=7)
        ax_d.set_xlim([1, 3]); ax_d.set_yscale("log"); ax_d.set_xlabel("Time (days)")
        ax_d.set_ylabel("Outlet depth (m, log)"); ax_d.set_title(f"assume_short_ts = {sts}", fontsize=10)
    fig.suptitle(f"EXPLORATORY: mc_numerical_dispersion.ipynb port, dx = {dx:g} m, kernel build: {args.variant} "
                 "(awlostowski-noaa/t-route @ de52970)", fontsize=11)
    fig.tight_layout()
    fig.savefig(RESULTS / f"dispersion_{args.variant}.png", dpi=130)
    (RESULTS / f"dispersion_{args.variant}.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {RESULTS}/dispersion_{args.variant}.json and .png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
