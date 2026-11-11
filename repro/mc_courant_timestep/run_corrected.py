"""The courant experiment with the corrected 2020 kernel, beside the faithful one.

    uv run python run_corrected.py [--jobs N]

Added 2026-10-09 (project rule: tests use a kernel without known coding errors). The
2020 kernel (MCsingleSegStime_f2py_NOLOOP-anw.f90) has the coding errors corrected in
T-Route's kernel by ../kernel_fixes/patches/0001-0007 (README there). build_kernels.py
compiles a patched copy (../kernel_fixes/patches/anw2020/) as mc_sseg_stime_anw_corrected.
This script reruns, with both kernels and the same drivers:
  - the primary experiment (run_experiment.reach_sim, dt = 30 ... 600 s);
  - the extension's volume-forcing variants (run_extended.simulate, dt = 30 s ... 4 h).
The faithful results (run_experiment.py, run_extended.py) are untouched; this writes
results/corrected_kernel.json with both sets of numbers and their differences.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "build" / "courant"))
sys.path.insert(0, str(HERE / "build" / "courant_corrected"))
KERNELS = {"faithful": "mc_sseg_stime_anw", "corrected": "mc_sseg_stime_anw_corrected"}
EXT_VARIANTS = ("core_volume", "short_ts", "slope_1e-4", "slope_1e-5")


def use(kernel: str) -> None:
    """Make `from mc_sseg_stime_anw import muskingcunge_module` resolve to `kernel`."""
    sys.modules["mc_sseg_stime_anw"] = importlib.import_module(KERNELS[kernel])
    import run_experiment as R
    R.mc_anw = sys.modules["mc_sseg_stime_anw"].muskingcunge_module


def primary(kernel: str) -> list[dict]:
    use(kernel)
    import run_experiment as R
    out = []
    for dt in R.dt_array:
        flow, depth, _v, _c, courant, _x, _ql = R.reach_sim(dt, R.dx, R.rchlen, R.duration, R.params,
                                                           R.q0, R.h0, R.t_pk, R.scale, R.pk_scale)
        q = flow[-1, :]
        t = np.arange(flow.shape[1]) * dt / 3600
        out.append({"dt_s": dt, "peak_time_h": float(t[int(np.argmax(q))]), "peak_flow_cms": float(q.max()),
                    "max_courant": float(np.nanmax(courant)), "outlet_flow": q})
    return out


def ext_job(job):
    kernel, name, dt = job
    use(kernel)
    import run_extended as E
    kind, s0, short_ts, _ = E.VARIANTS[name]
    p = E.channel(s0)
    h0 = E.H0_NOTEBOOK if s0 is None else E.normal_depth(E.Q0, p)
    r = E.simulate(dt, E.DURATION, p, h0, E.forcing(kind, dt, E.DURATION), short_ts, shadow=False)
    b = E.simulate(dt, E.DURATION, p, h0, E.forcing(kind, dt, E.DURATION, pulse=False), short_ts, shadow=False)
    q, qb, ql = r["flow"][-1], b["flow"][-1], r["ql"][0]
    nt = len(q)
    ex_out, ex_in = q - qb, ql - E.Q0
    v_in, v_out = float(np.sum(ex_in[1:]) * dt), float(np.sum(ex_out[1:]) * dt)
    cen_in = float(np.sum((np.arange(1, nt) * dt - dt / 2) * ex_in[1:]) / np.sum(ex_in[1:])) / 3600
    cen_out = float(np.sum(np.arange(1, nt) * dt * ex_out[1:]) / np.sum(ex_out[1:])) / 3600
    k = int(np.argmax(q))
    return kernel, name, dt, {"peak_time_h": k * dt / 3600, "peak_flow_cms": float(q[k]),
                              "peak_excess_out_cms": float(ex_out[k]),
                              "travel_time_centroid_h": cen_out - cen_in,
                              "volume_ratio_out_over_in": v_out / v_in,
                              "max_courant": float(np.nanmax(r["courant"])),
                              "all_flows_finite": bool(np.isfinite(r["flow"][:, 1:]).all())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0)
    a = ap.parse_args()
    res: dict = {"kernels": KERNELS, "primary": {}, "extended": {}}
    prim = {k: primary(k) for k in KERNELS}
    for f, c in zip(prim["faithful"], prim["corrected"]):
        d = np.abs(f["outlet_flow"] - c["outlet_flow"])
        res["primary"][str(f["dt_s"])] = {
            "faithful": {k: v for k, v in f.items() if k != "outlet_flow"},
            "corrected": {k: v for k, v in c.items() if k != "outlet_flow"},
            "outlet_max_abs_diff_cms": float(np.nanmax(d)),
            "outlet_bitwise_identical": bool(np.array_equal(f["outlet_flow"], c["outlet_flow"], equal_nan=True)),
        }
        print(f"primary dt={f['dt_s']:4d}: peak {f['peak_time_h']:.4f} h {f['peak_flow_cms']:.3f} -> "
              f"{c['peak_time_h']:.4f} h {c['peak_flow_cms']:.3f}; max |dQ| {np.nanmax(d):.3g}")
    import run_extended as E
    jobs = [(k, v, dt) for k in KERNELS for v in EXT_VARIANTS for dt in E.DT_LIST]
    jobs.sort(key=lambda j: j[2])
    with ProcessPoolExecutor(max_workers=a.jobs or None) as ex:
        out = list(ex.map(ext_job, jobs))
    got = {(k, v, dt): s for k, v, dt, s in out}
    for v in EXT_VARIANTS:
        res["extended"][v] = {}
        for dt in E.DT_LIST:
            f, c = got[("faithful", v, dt)], got[("corrected", v, dt)]
            res["extended"][v][str(dt)] = {
                "faithful": f, "corrected": c,
                "peak_flow_change_pct": 100 * (c["peak_flow_cms"] / f["peak_flow_cms"] - 1),
                "travel_time_change_h": c["travel_time_centroid_h"] - f["travel_time_centroid_h"],
                "volume_ratio_change": c["volume_ratio_out_over_in"] - f["volume_ratio_out_over_in"]}
            print(f"{v:12s} dt={dt:6d}: peak {f['peak_flow_cms']:9.3f} -> {c['peak_flow_cms']:9.3f}  "
                  f"travel {f['travel_time_centroid_h']:7.3f} -> {c['travel_time_centroid_h']:7.3f} h  "
                  f"V {f['volume_ratio_out_over_in']:.4f} -> {c['volume_ratio_out_over_in']:.4f}")
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "corrected_kernel.json").write_text(json.dumps(res, indent=1) + "\n")
    print("wrote results/corrected_kernel.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
