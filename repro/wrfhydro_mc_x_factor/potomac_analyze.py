"""Part 2 analysis: WRF-Hydro's own SUBMUSKINGCUNGE on the Potomac, current vs patched X.

AI-written (Claude, 2026-10-28). Reads build/potomac/ (potomac_inputs.py) and
build/potomac/out/ (fortran/network_driver.F90, one run per variant) and writes
results/potomac_summary.json and results/potomac_records.csv.

Part 3 (optional): if build/troute/{corrected,corrected+x}/ hold T-Route runs of the same
storm (troute_part3.sh), the same per-record changes are computed from T-Route and compared
with WRF-Hydro's (results/potomac_compare.csv). Run times are read from
build/potomac/timing.txt and build/troute/timing.txt when present.

Two upstream-inflow modes (added 2026-11-02). The top-level results are WRF-Hydro's own,
lagged mode (short-time-step assumption enabled; T-Route assume_short_ts True; outputs
out/{orig,patched}_*). If out/{orig,patched}_seq_* exist (network_driver ... sequential),
the same summary for the sequential mode (assumption disabled; T-Route False) goes under
"sequential", with T-Route's dt300_sts0 runs as its part-3 comparison, and
"mode_comparison" sets the X effect of the two modes side by side, with the effect of the
mode itself on the current kernel (results/potomac_modes.csv).

Per record point (USGS gauges from 17 to 29,940 km2, plus the outlet): peak flow and its
change, peak time and its shift (at the 300 s step), the 40-day volume, and the share of
time steps with X on its 0.25 floor (a diagnostic recomputed from the converged depth).
Network-wide: the distribution of per-link peak changes, overall and by size class.
Drainage-area notes for individual gauges (potomac_inputs.AREA_NOTES) are carried into the
table, e.g. the NHDPlusV2 TotDASqKM vs DivDASqKM difference at Antietam Creek.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
POT = HERE / "build" / "potomac"
OUT = POT / "out"
RESULTS = HERE / "results"
SIZE_CLASSES = [0, 25, 100, 300, 1000, 3000, 10000, 1e9]      # km2 (model area)


def load(variant: str, n: int, nrec: int, nhours: int) -> dict:
    hydro = np.fromfile(OUT / f"{variant}_hydro.bin", dtype=np.float32).reshape(nhours + 1, nrec).T
    with open(OUT / f"{variant}_peaks.bin", "rb") as f:
        qpeak = np.fromfile(f, dtype=np.float32, count=n)
        kpeak = np.fromfile(f, dtype=np.int32, count=n)
        vol = np.fromfile(f, dtype=np.float64, count=n)
    nfloor = np.fromfile(OUT / f"{variant}_floor.bin", dtype=np.int32)
    lines = (OUT / f"{variant}_diag.txt").read_text().split("\n")
    keys, vals = lines[0].split(), lines[1].split()
    diag = {k: float(v) for k, v in zip(keys, vals)}
    nconv = (OUT / f"{variant}_stdout.txt").read_text().count("Failure to converge")
    return {"hydro": hydro, "qpeak": qpeak.astype(float), "kpeak": kpeak, "vol": vol,
            "nfloor": nfloor, "diag": diag, "nonconvergence": nconv}


def runtimes() -> dict:
    """Wall-clock seconds from the timing logs written by run.sh and troute_part3.sh."""
    out = {}
    for name, path in (("wrfhydro_part2", POT / "timing.txt"), ("troute_part3", HERE / "build" / "troute" / "timing.txt")):
        if path.exists():
            d = {}
            for line in path.read_text().splitlines():
                if ":" in line and line.rstrip().endswith(" s") and not line.startswith("#"):
                    k, v = line.rsplit(":", 1)
                    d[k.strip()] = int(v.strip().split()[0])
                elif line.startswith("#"):
                    d["machine"] = line.lstrip("# ").strip()
            out[name] = d
    return out


def troute_compare(rows: list, sts: int = 1) -> dict | None:
    """Per-record T-Route current vs patched changes, next to WRF-Hydro's (part 3).

    sts = 1: assume_short_ts True, against WRF-Hydro's lagged mode (results/potomac_compare.csv);
    sts = 0: False, against the sequential mode (results/potomac_compare_sts0.csv).
    """
    base = HERE / "build" / "troute"
    fa = base / "corrected" / "results" / "runs" / "potomac_storm" / f"dt300_sts{sts}.npz"
    fb = base / "corrected+x" / "results" / "runs" / "potomac_storm" / f"dt300_sts{sts}.npz"
    if not (fa.exists() and fb.exists()):
        return None
    a, b = np.load(fa), np.load(fb)
    ia = {int(l): i for i, l in enumerate(a["link"])}
    ib = {int(l): i for i, l in enumerate(b["link"])}
    recs = []
    for row in rows:
        i, j = ia[row["link"]], ib[row["link"]]
        tr_chg = 100 * (b["peak_q"][j] - a["peak_q"][i]) / a["peak_q"][i]
        tr_shift = (b["peak_t_s"][j] - a["peak_t_s"][i]) / 3600
        recs.append({"name": row["name"], "usgs": row["usgs"], "link": row["link"],
                     "wrfhydro_peak_current_m3s": row["peak_current_m3s"], "troute_peak_current_m3s": r(a["peak_q"][i], 3),
                     "wrfhydro_peak_change_pct": row["peak_change_pct"], "troute_peak_change_pct": r(tr_chg, 3),
                     "wrfhydro_shift_h": row["t_peak_shift_h"], "troute_shift_h": r(tr_shift, 3)})
    with open(RESULTS / ("potomac_compare.csv" if sts else "potomac_compare_sts0.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0]))
        w.writeheader()
        w.writerows(recs)
    dchg = [abs(x["wrfhydro_peak_change_pct"] - x["troute_peak_change_pct"]) for x in recs]
    dsh = [abs(x["wrfhydro_shift_h"] - x["troute_shift_h"]) for x in recs]
    dpk = [abs(x["troute_peak_current_m3s"] / x["wrfhydro_peak_current_m3s"] - 1) * 100 for x in recs]
    return {"what": "T-Route (CIROH-UA d29f663 + ../kernel_fixes 0001-0008; patched adds the optional X patch), "
                    f"assume_short_ts {bool(sts)}, dt = 300 s, same Potomac storm",
            "records": recs,
            "max_abs_diff_peak_change_pct_points": r(max(dchg), 4),
            "max_abs_diff_shift_h": r(max(dsh), 4),
            "max_abs_diff_current_peak_pct": r(max(dpk), 4),
            "troute_wall_s": {"current": r(float(a["wall_s"]), 1), "patched": r(float(b["wall_s"]), 1)}}


def r(x, nd=4):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def mode_summary(o: dict, p: dict, meta: dict, lk, mode: str) -> tuple[list, dict]:
    """Per-record rows and the network summary for one upstream-inflow mode, current (o) vs patched (p)."""
    n, nhours, dt, nsub = meta["n_links"], meta["hours"], meta["dt_s"], meta["nsub"]
    recs = meta["records"]
    nsteps = nhours * nsub
    pos = {int(l): i for i, l in enumerate(lk["link"])}
    q0 = lk["q0"]
    area = lk["model_area_km2"]

    def excess_change(i):
        eo, ep = o["qpeak"][i] - q0[i], p["qpeak"][i] - q0[i]
        return 100 * (ep - eo) / eo if eo > 0 else np.nan

    rows = []
    for k, rm in enumerate(recs):
        i = pos[rm["link"]]
        rows.append({
            "name": rm["name"], "usgs": rm["usgs"] or "", "link": rm["link"], "area_note": rm.get("area_note") or "",
            "usgs_area_km2": rm["usgs_area_km2"], "lat": rm.get("lat"), "lon": rm.get("lon"),
            "model_area_km2": r(area[i], 1), "order": int(lk["order"][i]),
            "q0_m3s": r(q0[i], 3),
            "peak_current_m3s": r(o["qpeak"][i], 3), "peak_patched_m3s": r(p["qpeak"][i], 3),
            "peak_change_pct": r(100 * (p["qpeak"][i] - o["qpeak"][i]) / o["qpeak"][i], 2),
            "peak_excess_change_pct": r(excess_change(i), 2),
            "t_peak_current_h": r(o["kpeak"][i] * dt / 3600, 3), "t_peak_patched_h": r(p["kpeak"][i] * dt / 3600, 3),
            "t_peak_shift_h": r((p["kpeak"][i] - o["kpeak"][i]) * dt / 3600, 3),
            "volume_ratio_patched_over_current": r(p["vol"][i] / o["vol"][i], 6),
            "floor_share_current": r(o["nfloor"][i] / nsteps, 4), "floor_share_patched": r(p["nfloor"][i] / nsteps, 4),
        })

    # network-wide distribution (links whose peak rises above base flow)
    exc_o = o["qpeak"] - q0
    ok = exc_o > 1e-3 * np.maximum(q0, 1e-6)
    chg = np.where(ok, 100 * ((p["qpeak"] - q0) - exc_o) / np.where(ok, exc_o, 1), np.nan)
    shift = (p["kpeak"] - o["kpeak"]) * dt / 3600

    def dist(m):
        c, s = chg[m & ok], shift[m & ok]
        if c.size == 0:
            return {"links": 0}
        return {"links": int(c.size), "median_peak_excess_change_pct": r(np.median(c), 2),
                "p10_pct": r(np.percentile(c, 10), 2), "p90_pct": r(np.percentile(c, 90), 2),
                "share_lower_peak": r(np.mean(c < 0), 4), "median_shift_h": r(np.median(s), 3),
                "p90_shift_h": r(np.percentile(s, 90), 3)}

    by_size = {}
    for a, b in zip(SIZE_CLASSES[:-1], SIZE_CLASSES[1:]):
        by_size[f"{a:g}-{b:g}_km2" if b < 1e9 else f">{a:g}_km2"] = dist((area >= a) & (area < b))
    by_order = {str(k): dist(lk["order"] == k) for k in sorted(set(lk["order"].tolist()))}

    gauges = [row for row in rows if row["usgs"]]
    out_i = pos[recs[0]["link"]]
    what = {"lagged": "upstream inflow lagged (Qup = Quc = previous step), as in WRF-Hydro's DRIVE_CHANNEL",
            "sequential": "upstream inflow sequential (Quc = this step's upstream outflow; NOT WRF-Hydro's driver, "
                          "for comparison)"}[mode]
    summary = {
        "what": f"WRF-Hydro SUBMUSKINGCUNGE (55ed71c8), current vs patched X, Potomac synthetic storm; {what}",
        "upstream_inflow_mode": mode,
        "n_links": n, "hours": nhours, "dt_s": dt, "segment_steps": int(o["diag"]["segment_steps"]),
        "records": rows,
        "record_summary": {
            "gauges": len(gauges),
            "peak_excess_change_pct_range": [min(g["peak_excess_change_pct"] for g in gauges),
                                             max(g["peak_excess_change_pct"] for g in gauges)],
            "t_peak_shift_h_range": [min(g["t_peak_shift_h"] for g in gauges), max(g["t_peak_shift_h"] for g in gauges)],
        },
        "network_all_links": dist(np.ones(n, bool)), "network_by_model_area": by_size, "network_by_order": by_order,
        "floor": {v: {"segment_steps_share": r(d["diag"]["floor"] / d["diag"]["segment_steps"], 4),
                      "flow_weighted_share": r(d["diag"]["flow_weight_floor"] / d["diag"]["flow_weight_all"], 4),
                      "k_clamp_share": r(d["diag"]["kclamp"] / d["diag"]["segment_steps"], 4)}
                  for v, d in (("current", o), ("patched", p))},
        "checks": {
            "max_dev_steady_first_24h_m3s": {v: d["diag"]["maxdev_steady_m3s"] for v, d in (("current", o), ("patched", p))},
            "nonconvergence_messages": {"current": o["nonconvergence"], "patched": p["nonconvergence"]},
            "outlet_volume_over_lateral_volume": {
                v: r(d["vol"][out_i] / (meta["total_lateral_volume_m3"]), 5) for v, d in (("current", o), ("patched", p))},
            "outlet_volume_ratio_patched_over_current": r(p["vol"][out_i] / o["vol"][out_i], 6),
        },
    }
    return rows, summary


def mode_comparison(lag: dict, seq: dict) -> dict:
    """The X effect with lagged vs sequential upstream inflow, per record, and the mode effect itself."""
    recs = []
    for a, b in zip(lag["records"], seq["records"]):
        recs.append({
            "name": a["name"], "usgs": a["usgs"], "link": a["link"], "model_area_km2": a["model_area_km2"],
            "peak_current_lagged_m3s": a["peak_current_m3s"], "peak_current_sequential_m3s": b["peak_current_m3s"],
            "mode_peak_change_pct": r(100 * (a["peak_current_m3s"] / b["peak_current_m3s"] - 1), 2),
            "mode_t_peak_shift_h": r(a["t_peak_current_h"] - b["t_peak_current_h"], 3),
            "x_peak_excess_change_pct_lagged": a["peak_excess_change_pct"],
            "x_peak_excess_change_pct_sequential": b["peak_excess_change_pct"],
            "x_peak_change_pct_lagged": a["peak_change_pct"], "x_peak_change_pct_sequential": b["peak_change_pct"],
            "x_shift_h_lagged": a["t_peak_shift_h"], "x_shift_h_sequential": b["t_peak_shift_h"],
            "floor_share_current_lagged": a["floor_share_current"], "floor_share_current_sequential": b["floor_share_current"],
            "floor_share_patched_lagged": a["floor_share_patched"], "floor_share_patched_sequential": b["floor_share_patched"],
        })
    with open(RESULTS / "potomac_modes.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0]))
        w.writeheader()
        w.writerows(recs)
    g = [x for x in recs if x["usgs"]]
    d_chg = [abs(x["x_peak_excess_change_pct_lagged"] - x["x_peak_excess_change_pct_sequential"]) for x in g]
    d_sh = [abs(x["x_shift_h_lagged"] - x["x_shift_h_sequential"]) for x in g]
    return {"what": "mode_* = current kernel, lagged (WRF-Hydro) relative to sequential; x_* = patched vs current "
                    "within each mode",
            "records": recs,
            "gauges_max_abs_diff_x_peak_excess_change_pct_points": r(max(d_chg), 3),
            "gauges_max_abs_diff_x_shift_h": r(max(d_sh), 3),
            "outlet_volume_over_lateral_current": {"lagged": lag["checks"]["outlet_volume_over_lateral_volume"]["current"],
                                                   "sequential": seq["checks"]["outlet_volume_over_lateral_volume"]["current"]}}


def print_rows(rows: list) -> None:
    print(f"{'record point':44s} {'USGS km2':>9} {'model km2':>9} {'peak cur':>9} {'peak pat':>9} "
          f"{'dExcess%':>8} {'shift h':>7} {'floor c/p':>11}")
    for row in rows:
        ua = f"{row['usgs_area_km2']:,.0f}" if row["usgs_area_km2"] else "-"
        print(f"{row['name'][:44]:44s} {ua:>9} {row['model_area_km2']:>9,.0f} {row['peak_current_m3s']:>9.2f} "
              f"{row['peak_patched_m3s']:>9.2f} {row['peak_excess_change_pct']:>8.2f} {row['t_peak_shift_h']:>7.2f} "
              f"{row['floor_share_current']:>5.2f}/{row['floor_share_patched']:<5.2f}"
              + ("  *" if row["area_note"] else ""))


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    meta = json.loads((POT / "network.json").read_text())
    lk = np.load(POT / "links.npz")
    n, nhours = meta["n_links"], meta["hours"]
    nrec = len(meta["records"])
    o, p = load("orig", n, nrec, nhours), load("patched", n, nrec, nhours)
    rows, summary = mode_summary(o, p, meta, lk, "lagged")
    summary["notes"] = [
        "Peak changes are of the peak excess over the steady base flow; time shifts are at the 300 s step.",
        "model_area_km2 is the storm's nominal area (1.25 km2 per km of channel upstream); usgs_area_km2 "
        "is USGS's drainage area (NWIS, retrieved 2026-10-28).",
        "The outlet volume ratio is over 40 days and includes water still in storage at the end.",
        "Top level: lagged upstream inflow (WRF-Hydro's own driver, the NWM). 'sequential': the same with "
        "current-step upstream inflow (T-Route assume_short_ts False), for comparison."]
    summary["runtimes_s"] = runtimes()
    tr = troute_compare(rows)
    if tr is not None:
        summary["troute_comparison"] = tr
    seq_rows = None
    if (OUT / "orig_seq_peaks.bin").exists() and (OUT / "patched_seq_peaks.bin").exists():
        os_, ps = load("orig_seq", n, nrec, nhours), load("patched_seq", n, nrec, nhours)
        seq_rows, seq = mode_summary(os_, ps, meta, lk, "sequential")
        tr0 = troute_compare(seq_rows, 0)
        if tr0 is not None:
            seq["troute_comparison"] = tr0
        summary["sequential"] = seq
        summary["mode_comparison"] = mode_comparison(summary, seq)
        with open(RESULTS / "potomac_records_sequential.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(seq_rows[0]))
            w.writeheader()
            w.writerows(seq_rows)
    (RESULTS / "potomac_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with open(RESULTS / "potomac_records.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print("LAGGED upstream inflow (WRF-Hydro's DRIVE_CHANNEL, short-time-step assumption; the NWM)")
    print_rows(rows)
    print(json.dumps({k: summary[k] for k in ("network_all_links", "floor", "checks")}, indent=1))
    print(json.dumps(summary["network_by_model_area"], indent=1))
    if seq_rows is not None:
        seq = summary["sequential"]
        print("SEQUENTIAL upstream inflow (current step; assume_short_ts False; not WRF-Hydro's driver)")
        print_rows(seq_rows)
        print(json.dumps({k: seq[k] for k in ("network_all_links", "floor", "checks")}, indent=1))
        print("MODE COMPARISON: current-kernel peak, lagged vs sequential (% / h); X effect (peak excess change %, "
              "shift h) lagged | sequential")
        for x in summary["mode_comparison"]["records"]:
            print(f"{x['name'][:44]:44s} {x['mode_peak_change_pct']:+7.1f}% {x['mode_t_peak_shift_h']:+7.2f} h | "
                  f"{x['x_peak_excess_change_pct_lagged']:+6.2f}% {x['x_shift_h_lagged']:+5.2f} h | "
                  f"{x['x_peak_excess_change_pct_sequential']:+6.2f}% {x['x_shift_h_sequential']:+5.2f} h")
    for key, label in (("troute_comparison", "lagged / sts1"), ("sequential", "sequential / sts0")):
        t = summary.get(key) if key == "troute_comparison" else summary.get("sequential", {}).get("troute_comparison")
        if t:
            print(f"T-Route vs WRF-Hydro ({label}): max |d peak change| {t['max_abs_diff_peak_change_pct_points']} pts, "
                  f"max |d shift| {t['max_abs_diff_shift_h']} h, max |d current peak| {t['max_abs_diff_current_peak_pct']} %")


if __name__ == "__main__":
    main()
