"""Faithful port of courant_test.ipynb (awlostowski-noaa/t-route @ 27e06ee).

Cells 5 (reach_sim) and 7 (parameters, dt sweep, peak timing) of the notebook, with the
original Fortran kernel compiled by build_kernels.py. Differences from the notebook are
bookkeeping only:
  * results are held in numpy arrays instead of object-dtype DataFrames (the values
    are the same Python floats returned by the f2py wrapper);
  * results are written to results/ (CSV, JSON, PNG) instead of plt.show().
All parameters, the channel, the forcing, the time stepping, and the
upstream/downstream bookkeeping are exactly those of the notebook.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.stats import norm

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
sys.path.insert(0, str(HERE / "build" / "courant"))

try:
    from mc_sseg_stime_anw import muskingcunge_module as mc_anw  # noqa: E402
except ImportError as e:
    sys.exit(f"ERROR: compiled kernel not found ({e}); run build_kernels.py first")

# ---- notebook cell 7: channel geometry and roughness parameters (verbatim) ----
params = {}
params["bw"] = 50.0
params["tw"] = 100.0
params["twcc"] = 500.60
params["n"] = 0.02800000086426735
params["ncc"] = 0.03136000037193298
params["cs"] = 0.42
params["s0"] = 0.007999999690800905

# ---- notebook cell 7: simulation parameters (verbatim) ----
dt_array = [30, 60, 120, 300, 600]
duration = 15 * (60 * 60)
dx = 2000
rchlen = 20000
q0 = 2000
h0 = 2.78
t_pk = 6 * (60 * 60)
scale = 0.5 * (60 * 60)
pk_scale = 0.25


def reach_sim(dt, dx, rchlen, duration, params, q0, h0, t_pk, scale, pk_scale):
    """Port of notebook cell 5 `reach_sim` (same arguments, same returns)."""
    # build time/space domain
    segments = range(0, int(rchlen / dx))
    tsteps = range(0, int(duration / dt))
    ns, nt = len(segments), len(tsteps)

    # initialize matrices (notebook: DataFrames of NaN; ql of zeros)
    flow = np.full((ns, nt), np.nan)
    depth = np.full((ns, nt), np.nan)
    velocity = np.full((ns, nt), np.nan)
    celerity = np.full((ns, nt), np.nan)
    courant = np.full((ns, nt), np.nan)
    x_param = np.full((ns, nt), np.nan)
    ql = np.zeros((ns, nt))

    # initialize flow and depth
    flow[:, 0] = q0
    depth[:, 0] = h0
    velocity[:, 0] = 0

    # build lateral inflow data
    q_pk = pk_scale * q0
    x = np.linspace(0, duration, int(duration / dt))
    y = norm.pdf(x, t_pk, scale)
    y_scale = y * q_pk / max(y) + q0
    ql[0, :] = y_scale

    # execute simulation, stepping through time and space
    for t in tsteps[1:]:
        for x in segments:
            # qup - flow from the upstream segment in the previous timestep
            qup = 0 if x == 0 else flow[x - 1, t - 1]
            # quc - flow from the upstream segment, current timestep
            quc = 0 if x == 0 else flow[x - 1, t]
            # qdp - flow in this segment, previous timestep
            qdp = flow[x, t - 1]

            # MC compute kernel (original Fortran, via f2py)
            q, v, d, ck, cn, X = mc_anw.muskingcungenwm(
                dt, qup, quc, qdp, ql[x, t], dx,
                params["bw"], params["tw"], params["twcc"], params["n"],
                params["ncc"], params["cs"], params["s0"],
                0,  # velocity - an argument, but not used in the M-C module
                depth[x, t - 1],
            )
            flow[x, t] = q
            depth[x, t] = d
            velocity[x, t] = v
            celerity[x, t] = ck
            courant[x, t] = cn
            x_param[x, t] = X

    return flow, depth, velocity, celerity, courant, x_param, ql


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    import provenance

    RESULTS.mkdir(exist_ok=True)
    rows, summary = [], []
    fig, ax = plt.subplots(figsize=(9, 5.5))
    print("starting dt sensitivity simulations")
    for i, dt in enumerate(dt_array):
        flow, depth, velocity, celerity, courant, x_param, ql = reach_sim(
            dt, dx, rchlen, duration, params, q0, h0, t_pk, scale, pk_scale)
        time = (np.arange(flow.shape[1]) * dt) / (60 * 60)  # hours (notebook: columns * dt / 3600)
        q = flow[-1, :]                                        # downstream-most segment
        if i == 0:
            ax.plot(time, ql[0, :], "--", color="k", label="Forcing (lateral inflow, segment 0)")
        maxC = float(np.nanmax(courant))
        ax.plot(time, q, label=f"Sim{i}: dt = {dt} s, max C = {round(maxC, 2)}")
        m = max(q)
        peak_times = time[[k for k, j in enumerate(q) if j == m]]
        print(f"dt = {dt:4d} s: Peak time = {peak_times} hours, peak flow = {m:.3f} cms, max C = {maxC:.4f}")
        summary.append({
            "sim": i, "dt_s": dt, "n_segments": flow.shape[0], "n_timesteps": flow.shape[1],
            "max_courant": maxC, "max_courant_rounded_2": round(maxC, 2),
            "peak_time_h": [float(t) for t in peak_times], "peak_flow_cms": float(m),
            "max_depth_outlet_m": float(np.nanmax(depth[-1, :])),
            "output_interval_h": dt / 3600,
        })
        for k in range(flow.shape[1]):
            rows.append((dt, time[k], q[k], ql[0, k], depth[-1, k], courant[-1, k]))

    ax.set_xlim([0, 15])
    ax.set_ylabel("Flow (cms)")
    ax.set_xlabel("Time (hours)")
    ax.set_title("Outlet hydrographs, 20 km uniform channel, dx = 2000 m\n"
                 "(reproduction of courant_test.ipynb, awlostowski-noaa/t-route @ 27e06ee)", fontsize=10)
    ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(RESULTS / "courant_test_hydrographs.png", dpi=150)

    with open(RESULTS / "courant_test_outlet.csv", "w") as f:
        f.write("dt_s,time_h,q_outlet_cms,ql_segment0_cms,depth_outlet_m,courant_outlet\n")
        for r in rows:
            f.write(",".join(repr(float(v)) if isinstance(v, (float, np.floating)) else str(v) for v in r) + "\n")

    out = {"experiment": "courant_test", "parameters": {
        "params": params, "dt_array": dt_array, "duration_s": duration, "dx_m": dx,
        "rchlen_m": rchlen, "q0_cms": q0, "h0_m": h0, "t_pk_s": t_pk, "scale_s": scale,
        "pk_scale": pk_scale}, "runs": summary}
    (RESULTS / "courant_test.json").write_text(json.dumps(out, indent=2) + "\n")

    from fetch_data import COURANT_SHA, DISPERSION_SHA, DATA, FILES
    build_info = json.loads((HERE / "build" / "build_info.json").read_text())
    provenance.write(
        HERE, RESULTS,
        inputs={rel: DATA / rel for rel in FILES},
        sources={"repo": "https://github.com/awlostowski-noaa/t-route",
                 "courant_test_commit": COURANT_SHA,
                 "mc_numerical_dispersion_commit": DISPERSION_SHA},
        compilers=[["gfortran", "--version"], ["cc", "--version"]],
        extra={"build": build_info})
    print(f"wrote {RESULTS}/courant_test.json, courant_test_outlet.csv, courant_test_hydrographs.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
