"""Compare T-Route network runs across kernel variants (troute_compare.sh).

    uv run python troute_compare.py [--xproc-only]

Reads build/troute/<variant>/results/runs/<case>/dt300_sts<0|1>.npz and, for trace-*
variants, the .events.json beside them. Runs in ../short_ts_switch's environment (it
re-executes itself there: it needs pandas and that experiment's analyze.py).
Writes results/troute_compare.json:
  pairs      unpatched -> L1 (0001) -> L5 (0002-0005) -> corrected (0006-0008, the default);
             L5 -> L7 -> corrected (0006-0007 without 0008, then 0008), corrected ->
             corrected+x (optional Cunge-X patch):
             outlet peak, peak time, volume; network-wide differences of hourly flow
  switch     per variant, the True-vs-False outlet comparison (../short_ts_switch's headline) and the
             number of headwaters whose True and False results differ (the symptom of the uninitialized read;
             headwaters receive no upstream inflow, so the setting cannot matter there)
  events     per trace variant and run, how often each corrected code path was taken
  xproc      the same 6,000 calls through ctypes in two fresh processes (the determinism test)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STS = HERE.parent / "short_ts_switch"
try:
    import pandas as pd  # noqa: F401
except ImportError:  # re-run in ../short_ts_switch's locked environment
    os.execvp("uv", ["uv", "run", "--locked", "--directory", str(STS), "python", __file__, *sys.argv[1:]])

import numpy as np  # noqa: E402

sys.path.insert(0, str(STS))
import analyze as A  # noqa: E402

TR = HERE / "build" / "troute"
OUT = HERE / "results" / "troute_compare.json"
CASES = ("potomac_storm", "lc_nwm")
PAIRS = [("unpatched", "L1", "0001"), ("L1", "L5", "0002-0005"), ("L5", "corrected", "0006-0008"),
         ("L5", "L7", "0006-0007 without 0008 (diagnostic)"), ("L7", "corrected", "0008"),
         ("unpatched", "L5", "0001-0005"), ("unpatched", "corrected", "corrected kernel (0001-0008)"),
         ("unpatched", "L7", "0001-0007 (diagnostic)"), ("corrected", "corrected+x", "optional Cunge X")]


def r(x, d=4):
    return float(f"{float(x):.{d}g}")


def load(v, case, sts):
    f = TR / v / "results" / "runs" / case / f"dt300_sts{sts}.npz"
    return dict(np.load(f)) if f.exists() else None


def seg_info(case):
    seg = pd.read_parquet(A.INPUTS / case / "segments.parquet")
    tree = A.build_tree(seg)
    down = tree["down"]
    head = np.bincount(down[down >= 0], minlength=len(seg)) == 0
    return seg, head


def outlet(run, seg):
    o = int(np.flatnonzero(seg["is_outlet"].to_numpy())[0])
    return {"peak_m3s": r(run["peak_q"][o]), "peak_time_h": r(run["peak_t_s"][o] / 3600.0),
            "volume_m3": r(run["volume_m3"][o]), "end_flow_m3s": r(run["q_hourly"][o, -1])}


def pair(a, b, seg):
    qa, qb = a["q_hourly"].astype(np.float64), b["q_hourly"].astype(np.float64)
    d = np.abs(qb - qa)
    pk = np.maximum(a["peak_q"].astype(np.float64), 1e-6)
    worst = d.max(axis=1) / pk
    oa, ob = outlet(a, seg), outlet(b, seg)
    peak_rel = (b["peak_q"] - a["peak_q"]) / np.maximum(a["peak_q"], 1e-6)
    big = a["peak_q"] >= 1.0
    return {
        "outlet_from": oa, "outlet_to": ob,
        "outlet_peak_change_pct": r(100 * (ob["peak_m3s"] - oa["peak_m3s"]) / oa["peak_m3s"]),
        "outlet_peak_time_shift_h": r(ob["peak_time_h"] - oa["peak_time_h"]),
        "outlet_volume_change_pct": r(100 * (ob["volume_m3"] - oa["volume_m3"]) / oa["volume_m3"]),
        # sum of every segment's routed volume (the fork review's "sum Q")
        "network_volume_change_pct": r(100 * (b["volume_m3"].sum() - a["volume_m3"].sum()) / a["volume_m3"].sum()),
        "segment_hours_bitwise_differ_frac": r(np.mean(qa != qb)),
        "segments_any_difference": int((d.max(axis=1) > 0).sum()),
        "segments_diff_gt_1pct_of_peak": int((worst > 0.01).sum()),
        "segments_diff_gt_10pct_of_peak": int((worst > 0.10).sum()),
        "max_abs_diff_m3s": r(d.max()),
        "max_diff_pct_of_own_peak": r(100 * worst.max()),
        "peak_change_pct_p1_p50_p99_segments_ge_1m3s": [r(100 * np.percentile(peak_rel[big], p)) for p in (1, 50, 99)],
        "n_segments": int(len(pk)),
    }


def switch(v, case, seg, head):
    t, f = load(v, case, 1), load(v, case, 0)
    if t is None or f is None:
        return None
    ot, of = outlet(t, seg), outlet(f, seg)
    dh = np.abs(t["q_hourly"].astype(np.float64) - f["q_hourly"]).max(axis=1)
    return {"outlet_true": ot, "outlet_false": of,
            "peak_rel_diff_pct": r(100 * (ot["peak_m3s"] - of["peak_m3s"]) / of["peak_m3s"]),
            "peak_time_shift_h": r(ot["peak_time_h"] - of["peak_time_h"]),
            "headwaters": int(head.sum()),
            "headwaters_true_vs_false_differ_gt_1e-4": int((dh[head] > 1e-4).sum()),
            "headwaters_true_vs_false_bitwise_differ": int((dh[head] > 0).sum())}


def xproc() -> dict:
    res = {}
    for v in ("unpatched", "corrected"):
        f1, f2 = HERE / "results" / "xproc" / f"{v}_1.npy", HERE / "results" / "xproc" / f"{v}_2.npy"
        if f1.exists() and f2.exists():
            a, b = np.load(f1), np.load(f2)
            rel = np.abs(a - b) / np.maximum(np.abs(b), 1e-3)
            res[v] = {"n_calls": int(a.size), "frac_calls_differing": r(np.mean(a != b)),
                      "max_rel_diff": r(rel.max(), 3)}
    return res


def main() -> int:
    R = json.loads(OUT.read_text()) if OUT.exists() else {}
    if "--xproc-only" in sys.argv:
        R["xproc"] = xproc()
        OUT.write_text(json.dumps(R, indent=1) + "\n")
        print(json.dumps(R["xproc"], indent=1))
        return 0
    variants = sorted(p.name for p in TR.iterdir() if p.is_dir()) if TR.exists() else []
    R = {"dt_s": 300, "variants": variants, "pairs": {}, "switch": {}, "events": {}}
    for case in CASES:
        seg, head = seg_info(case)
        for sts in (1, 0):
            key = f"{case}/sts{sts}"
            R["pairs"][key] = {}
            for a, b, label in PAIRS:
                ra, rb = load(a, case, sts), load(b, case, sts)
                if ra is not None and rb is not None:
                    R["pairs"][key][f"{a} -> {b}"] = {"patches": label, **pair(ra, rb, seg)}
            for v in variants:
                if v.startswith("trace-"):
                    f = TR / v / "results" / "runs" / case / f"dt300_sts{sts}.events.json"
                    if f.exists():
                        e = json.loads(f.read_text())
                        n = e["kernel_calls"]
                        R["events"].setdefault(v, {})[key] = {
                            "kernel_calls": n, **{k: c for k, c in e["events"].items()},
                            "per_million_calls": {k: r(1e6 * c / n) for k, c in e["events"].items()}}
                        # trace builds must reproduce the plain build of the same level
                        plain = {"trace-L1": "L1", "trace-L5": "L5", "trace-L7": "L7", "trace-L8": "corrected"}.get(v)
                        rp, rt = load(plain, case, sts) if plain else None, load(v, case, sts)
                        if rp is not None and rt is not None:
                            R["events"][v][key]["equals_plain_build_bitwise"] = bool(
                                np.array_equal(rp["q_hourly"], rt["q_hourly"]))
        for v in variants:
            if not v.startswith("trace-"):
                s = switch(v, case, seg, head)
                if s:
                    R["switch"].setdefault(case, {})[v] = s
    R["xproc"] = xproc()
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(R, indent=1) + "\n")
    for key, d in R["pairs"].items():
        for p, x in d.items():
            print(f"{key:22s} {p:28s} outlet peak {x['outlet_peak_change_pct']:+.3g}% "
                  f"shift {x['outlet_peak_time_shift_h']:+.3g} h; segs >1% {x['segments_diff_gt_1pct_of_peak']}, "
                  f"max {x['max_diff_pct_of_own_peak']:.3g}% of peak")
    print("ok      results/troute_compare.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
