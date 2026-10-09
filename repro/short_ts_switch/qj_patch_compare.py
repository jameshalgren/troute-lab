"""Compare the Qj-patched T-Route runs (qj_patch_check.sh) with the unpatched runs.

    uv run python qj_patch_compare.py build/qj_patch/results/runs/potomac_storm

Writes results/qj_patch_check.json. Besides the routed results it compares the
compiled MC kernel (ctypes, bind(c) wrapper) unpatched vs patched: the same 6,000 random
calls in separate processes (the unpatched kernel's outputs vary between processes; the
patched kernel's do not), and the patched kernel against the Python port mc_port.py.
"""
from __future__ import annotations

import ctypes
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze as A  # noqa: E402
import make_inputs as MI  # noqa: E402

CASE = "potomac_storm"
GEO = ("dx", "bw", "tw", "twcc", "n", "ncc", "cs", "s0")


def kernel_inputs(n=2000):
    """Deterministic random non-steady inputs around each sampled segment's peak state."""
    seg = pd.read_parquet(A.INPUTS / CASE / "segments.parquet")
    p = A.channel_params(CASE, seg["link"].to_numpy())
    ref = A.load(CASE, 300, False)
    rng = np.random.default_rng(1)
    rows = []
    for i in rng.choice(len(seg), n):
        g = p.iloc[i]
        q, h = float(ref["peak_q"][i]), float(ref["depth_at_peak"][i])
        for dt in (60.0, 300.0, 3600.0):
            rows.append([dt, q * rng.uniform(0.3, 1.5), q * rng.uniform(0.3, 1.5), q * rng.uniform(0.3, 1.5),
                         q * rng.uniform(0, 0.2), *[float(g[c]) for c in GEO], 0.0, h * rng.uniform(0.7, 1.3)])
    return np.array(rows, dtype=np.float32)


def kernel_batch(lib_path: str, out: str) -> None:
    """Call the compiled kernel on kernel_inputs(); save qdc (run in a fresh process)."""
    fn = ctypes.CDLL(lib_path).c_muskingcungenwm
    fn.restype = None
    res = []
    for args in kernel_inputs():
        cin = [ctypes.c_float(float(a)) for a in args]
        co = [ctypes.c_float(0.0) for _ in range(6)]
        fn(*[ctypes.byref(c) for c in cin + co])
        res.append(co[0].value)
    np.save(out, np.array(res, dtype=np.float64))


def kernel_comparison(patched_lib: Path) -> dict:
    import mc_port as M
    tmp = HERE / "build" / "qj_patch_kernel"
    tmp.mkdir(parents=True, exist_ok=True)
    outs = {}
    for name, lib in (("unpatched", A.LIBMC), ("patched", patched_lib)):
        for k in (1, 2):
            f = tmp / f"{name}_{k}.npy"
            subprocess.run([sys.executable, __file__, "--kernel-batch", str(lib), str(f)], check=True)
            outs[(name, k)] = np.load(f)
    rel = lambda a, b: np.abs(a - b) / np.maximum(np.abs(b), 1e-3)  # noqa: E731
    port = np.array([M.mc(*[float(x) for x in r[:13]], float(r[14]))[0] for r in kernel_inputs()])
    rp = rel(port, outs[("patched", 1)])
    d = {"n_calls": int(port.size)}
    for name in ("unpatched", "patched"):
        r = rel(outs[(name, 1)], outs[(name, 2)])
        d[f"{name}_kernel_two_processes"] = {"frac_calls_differing": A.r4(np.mean(r > 0)),
                                             "max_rel_diff": float(f"{r.max():.3g}")}
    d["port_vs_patched_kernel_rel_diff"] = {k: float(f"{v:.3g}") for k, v in
                                           zip(("p50", "p99", "max"), np.percentile(rp, [50, 99, 100]))}
    d["note"] = ("random non-steady inputs; the port is float64, the kernel float32; remaining port "
                 "differences are on slope-floor segments, where the depth secant is ill-conditioned")
    return d


def main() -> int:
    if sys.argv[1] == "--kernel-batch":
        kernel_batch(sys.argv[2], sys.argv[3])
        return 0
    pdir = Path(sys.argv[1]).resolve()
    seg = pd.read_parquet(A.INPUTS / CASE / "segments.parquet")
    tree = A.build_tree(seg)
    down = tree["down"]
    head = np.bincount(down[down >= 0], minlength=len(seg)) == 0
    o = int(np.flatnonzero(seg["is_outlet"].to_numpy())[0])
    q0 = seg["q0"].to_numpy()
    hours = 960
    T = hours * 3600.0
    ql = MI.storm_series(seg["length_km"].to_numpy(), hours).astype(np.float64)
    acc = ql.sum(axis=1) * 3600 - ql[:, 0] * T
    for i in tree["topo"]:
        if down[i] >= 0:
            acc[down[i]] += acc[i]
    info = json.loads((pdir.parents[2] / "build" / "build_info.json").read_text())
    out = {"patched_build": {"patches": info.get("patches"), "troute_commit": info.get("troute_commit")},
           "by_dt": {}}
    for dt in (300, 3600):
        pt, pf = np.load(pdir / f"dt{dt}_sts1.npz"), np.load(pdir / f"dt{dt}_sts0.npz")
        ot, of = A.load(CASE, dt, True), A.load(CASE, dt, False)
        d = {}
        for name, x, y in (("true", pt, ot), ("false", pf, of)):
            diff = np.abs(x["q_hourly"] - y["q_hourly"]).max(axis=1)
            rel = diff / np.maximum(y["peak_q"], 1e-6)
            d[name] = {
                "max_abs_diff_hourly_m3s": A.r4(diff.max()),
                "max_diff_pct_of_own_peak": A.r4(100 * rel.max()),
                "frac_segments_diff_gt_1pct_of_peak": A.r4(np.mean(rel > 0.01)),
                "outlet_peak_patched_m3s": A.r4(x["peak_q"][o]), "outlet_peak_unpatched_m3s": A.r4(y["peak_q"][o]),
                "outlet_event_balance_patched": A.r4((x["volume_m3"][o] - q0[o] * T) / acc[o]),
                "outlet_event_balance_unpatched": A.r4((y["volume_m3"][o] - q0[o] * T) / acc[o]),
            }
        dh_p = np.abs(pt["q_hourly"] - pf["q_hourly"]).max(axis=1)
        dh_o = np.abs(ot["q_hourly"] - of["q_hourly"]).max(axis=1)
        d["headwaters_differing_true_vs_false_gt_1e-4"] = {"patched": int((dh_p[head] > 1e-4).sum()),
                                                           "unpatched": int((dh_o[head] > 1e-4).sum())}
        d["outlet_true_vs_false"] = {
            "patched": {"peak_rel_diff_pct": A.r4(100 * (pt["peak_q"][o] / pf["peak_q"][o] - 1)),
                        "peak_time_shift_h": A.r4((pt["peak_t_s"][o] - pf["peak_t_s"][o]) / 3600)},
            "unpatched": {"peak_rel_diff_pct": A.r4(100 * (ot["peak_q"][o] / of["peak_q"][o] - 1)),
                          "peak_time_shift_h": A.r4((ot["peak_t_s"][o] - of["peak_t_s"][o]) / 3600)}}
        out["by_dt"][str(dt)] = d
    out["compiled_kernel"] = kernel_comparison(pdir.parents[2] / "build" / A.LIBMC.name)
    (HERE / "results" / "qj_patch_check.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
