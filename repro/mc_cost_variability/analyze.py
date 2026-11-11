"""Summaries of the per-call work counts and the cost vectors for ../jit_scheduling.

    uv run --locked python analyze.py

Reads results/runs/<scenario>/{counts,flows,verify}.npz|json (simulate.py) and, if present,
results/timing/<scenario>.npz (timing.py: measured port time per segment and 24-h window,
exported as port_us_<scenario>). Writes:
  tables/iterations_per_call.{csv,md}   distribution of secant iterations per call, calm vs
                                        each storm, and by flow state within the storm runs
  tables/segment_totals.{csv,md}        per-segment totals over the run: CV, worst/mean
  tables/windows.{csv,md}               per-unit cost over T-Route chunk windows (1 h, 3 h,
                                        24 h = default max_loop_size, whole run)
  tables/spatial.{csv,md}               where the expensive segments are: distance to outlet,
                                        tributary, slope class, stream order
  tables/hourly_network_cost.csv        network iterations per hour, every scenario
  tables/space_time_3h.csv              network cost over calm per 3-h window, by distance band
  tables/summary.json                   headline numbers (check.py regression values)
  results/cost/segment_cost.csv         cost vector per segment (NWM feature id)
  results/cost/segment_window_cost_<scenario>.npz   cost per segment per window
Conventions: per-call statistics leave out the first hour (T-Route's lite restart starts
every depth at 0, so the first steps' secant searches are artificial; as
../short_ts_switch/closure_replay.py). Aggregates over windows and the run include every
step, as T-Route would execute them.
"""
from __future__ import annotations

import json
import sys

import common as C
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ALL = list(C.SCENARIOS)
STORMS = [s for s in ALL if s != "calm"]
DIST_BANDS = [0, 50, 100, 200, 300, 400, 500, 700]
TOP = 0.10                     # "expensive" = top decile


def r(x, n=4):
    return None if x is None or not np.isfinite(x) else float(round(float(x), n))


def bincount_stats(bc: np.ndarray) -> dict:
    """Statistics of a distribution given as counts per iteration number."""
    n = bc.sum()
    k = np.arange(len(bc))
    mean = (k * bc).sum() / n
    var = ((k - mean) ** 2 * bc).sum() / n
    cdf = np.cumsum(bc) / n
    q = lambda p: int(np.searchsorted(cdf, p))  # noqa: E731
    nz = np.flatnonzero(bc)
    out = {"calls": int(n), "mean": r(mean), "cv": r(np.sqrt(var) / mean), "p50": q(0.5), "p90": q(0.9),
           "p99": q(0.99), "p99.9": q(0.999), "p99.99": q(0.9999), "max": int(nz.max()),
           "max_over_mean": r(nz.max() / mean, 2)}
    for v in range(1, 7):
        out[f"share_{v}"] = r(bc[v] / n, 5) if v < len(bc) else 0.0
    out["share_7plus"] = r(bc[7:].sum() / n, 6)
    out["share_0"] = r(bc[0] / n, 6)
    return out


def flow_state(q_hourly: np.ndarray, q0: np.ndarray) -> np.ndarray:
    """Per segment and hour: 0 base (q < 1.1 q0), 1 between, 2 flood rising (q >= 2 q0 and
    higher than the hour before), 3 flood falling (q >= 2 q0, not rising)."""
    ratio = q_hourly / q0[:, None]
    prev = np.concatenate([q_hourly[:, :1], q_hourly[:, :-1]], axis=1)
    st = np.ones(q_hourly.shape, np.uint8)
    st[ratio < 1.1] = 0
    flood = ratio >= 2.0
    st[flood & (q_hourly > prev)] = 2
    st[flood & ~(q_hourly > prev)] = 3
    return st


def windows_of(it: np.ndarray) -> dict:
    nseg, nts = it.shape
    return {k: it.reshape(nseg, nts // W, W).sum(axis=2, dtype=np.int64) for k, W in C.WINDOWS.items()}


def eta2(values: np.ndarray, groups: np.ndarray) -> float:
    """Share of the variance of values explained by group means (between-group / total)."""
    df = pd.DataFrame({"v": values, "g": groups})
    m = df.groupby("g", observed=True)["v"].transform("mean")
    tot = ((df["v"] - df["v"].mean()) ** 2).sum()
    return float(((m - df["v"].mean()) ** 2).sum() / tot) if tot > 0 else float("nan")


def adjacency_lift(top: np.ndarray, down: np.ndarray) -> float:
    """P(downstream neighbour is also 'top' | segment is 'top') / share of 'top' segments."""
    has = (down >= 0) & top
    if not has.any():
        return float("nan")
    return float(top[down[has]].mean() / top.mean())


def main() -> int:
    case = C.load_case()
    seg = case["seg"]
    nseg = len(seg)
    q0 = seg["q0"].to_numpy().astype(np.float64)
    down = seg["down_idx"].to_numpy()
    cost_dir = C.RESULTS / "cost"
    cost_dir.mkdir(parents=True, exist_ok=True)
    C.TABLES.mkdir(exist_ok=True)

    per_call_rows, totals_rows, hourly = [], [], {}
    win, verify, run_tot, tails = {}, {}, {}, {}
    calm_last_rs = calm_final_it = calm_constant = None
    for name in ALL:
        d = C.run_dir(name)
        if not (d / "counts.npz").exists():
            raise SystemExit(f"missing {d / 'counts.npz'}: run simulate.py {name}")
        verify[name] = json.loads((d / "verify.json").read_text())
        z = np.load(d / "counts.npz")
        it = z["n_iter"]
        if not np.array_equal(z["link"], case["link"]):
            raise SystemExit("segment order differs")
        acc = it[:, C.T_ACC0:]
        bc = np.bincount(acc.reshape(-1), minlength=8)
        rs, fa, gu = z["n_restart"][:, C.T_ACC0:], z["fail"][:, C.T_ACC0:], z["guard"][:, C.T_ACC0:]
        row = {"scenario": name, "storm_mm": C.SCENARIOS[name]["storm_mm"],
               "assume_short_ts": C.SCENARIOS[name]["sts"], "calls_in": "all", **bincount_stats(bc),
               "restarts_per_1e6_calls": r(rs.sum(dtype=np.int64) / acc.size * 1e6, 2),
               "calls_with_restart": int((rs > 0).sum()), "fails": int(fa.sum(dtype=np.int64)),
               "guard_calls": int((gu > 0).sum())}
        per_call_rows.append(row)
        if name != "calm":
            f = np.load(d / "flows.npz")
            st = np.repeat(flow_state(f["q_hourly"], q0), C.QTS, axis=1)[:, C.T_ACC0:]
            for code, label in [(0, "base_flow"), (2, "flood_rising"), (3, "flood_falling")]:
                m = st == code
                if m.any():
                    per_call_rows.append({"scenario": name, "storm_mm": C.SCENARIOS[name]["storm_mm"],
                                          "assume_short_ts": C.SCENARIOS[name]["sts"], "calls_in": label,
                                          **bincount_stats(np.bincount(acc[m], minlength=8)),
                                          "restarts_per_1e6_calls": r(rs[m].sum(dtype=np.int64) / m.sum() * 1e6, 2),
                                          "calls_with_restart": int((rs[m] > 0).sum()),
                                          "fails": int(fa[m].sum(dtype=np.int64)), "guard_calls": int((gu[m] > 0).sum())})
            m = st >= 2
            per_call_rows.append({"scenario": name, "storm_mm": C.SCENARIOS[name]["storm_mm"],
                                  "assume_short_ts": C.SCENARIOS[name]["sts"], "calls_in": "flood_all",
                                  **bincount_stats(np.bincount(acc[m], minlength=8)),
                                  "restarts_per_1e6_calls": r(rs[m].sum(dtype=np.int64) / m.sum() * 1e6, 2),
                                  "calls_with_restart": int((rs[m] > 0).sum()),
                                  "fails": int(fa[m].sum(dtype=np.int64)), "guard_calls": int((gu[m] > 0).sum())})
            del st, m
        # long searches, restarts, and what the run leaves behind (compared with calm)
        big = acc >= 10
        hrs = (np.nonzero(big)[1] + C.T_ACC0) // C.QTS
        seg_rs = (rs > 0).any(axis=1)
        last_rs = (z["n_restart"][:, -C.WINDOWS["24h"]:] > 0).sum(axis=1)
        rs_day = z["n_restart"].reshape(nseg, -1, C.WINDOWS["24h"]).sum(axis=(0, 2), dtype=np.int64)
        tails[name] = {"calls_ge_10_iterations": int(big.sum()), "segments_with_calls_ge_10": int(big.any(axis=1).sum()),
                       "hours_of_calls_ge_10": [int(hrs.min()), int(hrs.max())] if hrs.size else None,
                       "segments_with_restarts": int(seg_rs.sum()),
                       "segments_with_restarts_by_slope_class": np.bincount(seg["slope_class"].to_numpy()[seg_rs],
                                                                            minlength=4).tolist(),
                       "restarts_by_day": rs_day.tolist()}
        if name == "calm":
            calm_last_rs, calm_final_it = last_rs, it[:, -1].copy()
            calm_constant = float((acc.min(axis=1) == acc.max(axis=1)).mean())
        else:
            dif = np.flatnonzero(last_rs != calm_last_rs)
            tails[name].update({
                "segments_last_day_restarting_differently_from_calm": [
                    {"feature_id": int(case["link"][i]), "restart_steps_last_day": int(last_rs[i]),
                     "calm": int(calm_last_rs[i]), "s0": float(seg["s0"].iloc[i]), "order": int(seg["order"].iloc[i])}
                    for i in dif],
                "segments_final_step_iterations_differ_from_calm": int((it[:, -1] != calm_final_it).sum()),
                "segments_not_within_1pct_of_baseflow_at_end": int((np.abs(f["q_hourly"][:, -1] / q0 - 1) > 0.01).sum())})
        w = windows_of(it)
        win[name] = w
        run_tot[name] = w["run"][:, 0]
        hourly[name] = w["1h"].sum(axis=0)
        extra = {}
        tp = C.RESULTS / "timing" / f"{name}.npz"
        if tp.exists():
            tz = np.load(tp)
            if np.array_equal(tz["iters"], w["24h"]):
                extra["port_ns_24h"] = tz["ns"].astype(np.float32)   # measured port time per unit
        np.savez_compressed(cost_dir / f"segment_window_cost_{name}.npz", **extra,
                            feature_id=case["link"], to_feature_id=seg["to"].to_numpy(),
                            iters_1h=w["1h"].astype(np.int32), iters_3h=w["3h"].astype(np.int32),
                            iters_24h=w["24h"].astype(np.int32), iters_run=w["run"][:, 0].astype(np.int64),
                            steps_1h=C.WINDOWS["1h"], steps_3h=C.WINDOWS["3h"], steps_24h=C.WINDOWS["24h"],
                            steps_run=C.NTS, dt_s=C.DT, scenario=name,
                            storm_mm=C.SCENARIOS[name]["storm_mm"], assume_short_ts=C.SCENARIOS[name]["sts"])
        del it, acc, rs, fa, gu, z
        print(f"ok      {name}: per-call and window aggregates")

    # ------------------------------------------------------------- per-segment run totals
    calm_mean = run_tot["calm"].mean()
    for name in ALL:
        x = run_tot[name].astype(float)
        totals_rows.append({"scenario": name, "segments": nseg, "calls_per_segment": C.NTS,
                            "mean_iters_per_segment": r(x.mean(), 1), "cv_across_segments": r(x.std() / x.mean()),
                            "min_over_mean": r(x.min() / x.mean(), 3), "p1_over_mean": r(np.percentile(x, 1) / x.mean(), 3),
                            "p50_over_mean": r(np.median(x) / x.mean(), 3),
                            "p99_over_mean": r(np.percentile(x, 99) / x.mean(), 3),
                            "max_over_mean": r(x.max() / x.mean(), 3),
                            "network_total_over_calm": r(x.sum() / run_tot["calm"].sum(), 5),
                            "spearman_vs_calm": r(spearmanr(x, run_tot["calm"]).statistic),
                            "segments_costlier_than_calm": int((x > run_tot["calm"]).sum()),
                            "segments_cheaper_than_calm": int((x < run_tot["calm"]).sum())})

    # ------------------------------------------------------------- windows
    win_rows = []
    for name in ALL:
        for wk, W in C.WINDOWS.items():
            a = win[name][wk].astype(float)
            c = win["calm"][wk].astype(float)
            m_w = a.mean(axis=0)
            cv_w = a.std(axis=0) / m_w
            mm_w = a.max(axis=0) / m_w
            net_ratio = a.sum(axis=0) / c.sum(axis=0)
            # calm has no storm peak: use the last window (window 0 holds the restart transient)
            wpk = int(np.argmax(a.sum(axis=0) - c.sum(axis=0))) if name != "calm" else a.shape[1] - 1
            ratio_u = a / np.maximum(c, 1.0)
            win_rows.append({
                "scenario": name, "window": wk, "steps": W, "windows": a.shape[1], "units": a.size,
                "cv_pooled": r(a.std() / a.mean()), "worst_over_mean_pooled": r(a.max() / a.mean(), 3),
                "cv_across_segments_median_window": r(np.median(cv_w)), "cv_across_segments_min_window": r(cv_w.min()),
                "cv_across_segments_max_window": r(cv_w.max()),
                "worst_over_mean_median_window": r(np.median(mm_w), 3), "worst_over_mean_max_window": r(mm_w.max(), 3),
                "peak_window_index": wpk, "peak_window_start_h": r(wpk * W * C.DT / 3600, 2),
                "network_cost_peak_window_over_calm": r(net_ratio.max(), 4),
                "network_cost_windows_gt_1.05_calm": int((net_ratio > 1.05).sum()),
                "cv_across_segments_peak_window": r(cv_w[wpk]),
                "worst_over_mean_peak_window": r(mm_w[wpk], 3),
                "unit_ratio_to_calm_p50": r(np.median(ratio_u), 3), "unit_ratio_to_calm_p99": r(np.percentile(ratio_u, 99), 3),
                "unit_ratio_to_calm_p01": r(np.percentile(ratio_u, 1), 3),
                "unit_ratio_to_calm_max": r(ratio_u.max(), 3), "unit_ratio_to_calm_min": r(ratio_u.min(), 3),
                "spearman_vs_calm_peak_window": r(spearmanr(a[:, wpk], c[:, wpk]).statistic) if name != "calm" else 1.0,
            })
    # per-call reference row (window = 1 step), from the per-call distributions
    for row in per_call_rows:
        if row["calls_in"] == "all":
            win_rows.append({"scenario": row["scenario"], "window": "call", "steps": 1, "cv_pooled": row["cv"],
                             "worst_over_mean_pooled": row["max_over_mean"]})

    # ------------------------------------------------------------- spatial
    dist = seg["dist_to_outlet_km"].to_numpy()
    band = pd.cut(dist, DIST_BANDS, right=False, labels=[f"{a}-{b} km" for a, b in zip(DIST_BANDS[:-1], DIST_BANDS[1:])])
    slope_labels = ["floor 1e-5", "1e-5 to 2.5e-4", "2.5e-4 to 1e-3", "> 1e-3"]
    groupings = {"distance_to_outlet": band,
                 "subbasin": pd.Categorical(seg["subbasin"].to_numpy()),
                 "slope_class": pd.Categorical.from_codes(seg["slope_class"].to_numpy(), slope_labels),
                 "stream_order": pd.Categorical(seg["order"].to_numpy())}
    sp_rows, clus = [], {}
    calm_run = run_tot["calm"].astype(float)
    for name in ALL:
        a24 = win[name]["24h"].astype(float)
        c24 = win["calm"]["24h"].astype(float)
        wpk = int(np.argmax(a24.sum(axis=0) - c24.sum(axis=0))) if name != "calm" else a24.shape[1] - 1
        unit = a24[:, wpk]                     # cost of each segment in the peak 24-h window (calm: the last)
        excess = unit - c24[:, wpk]
        run_ex = run_tot[name].astype(float) - calm_run
        top = unit >= np.quantile(unit, 1 - TOP)
        topx = excess >= np.quantile(excess, 1 - TOP)
        clus[name] = {
            "peak_window_24h_index": wpk,
            "eta2_subbasin_unit_cost": r(eta2(unit, groupings["subbasin"])),
            "eta2_distance_band_unit_cost": r(eta2(unit, groupings["distance_to_outlet"])),
            "eta2_slope_class_unit_cost": r(eta2(unit, groupings["slope_class"])),
            "eta2_order_unit_cost": r(eta2(unit, groupings["stream_order"])),
            "spearman_unit_cost_vs_distance": r(spearmanr(unit, dist).statistic),
            "top_decile_adjacency_lift_unit_cost": r(adjacency_lift(top, down), 3),
            "share_of_window_cost_in_top_decile": r(unit[top].sum() / unit.sum()),
        }
        if name != "calm":
            clus[name].update({
                "eta2_subbasin_excess": r(eta2(excess, groupings["subbasin"])),
                "eta2_distance_band_excess": r(eta2(excess, groupings["distance_to_outlet"])),
                "eta2_slope_class_excess": r(eta2(excess, groupings["slope_class"])),
                "spearman_excess_vs_distance": r(spearmanr(excess, dist).statistic),
                "top_decile_adjacency_lift_excess": r(adjacency_lift(topx, down), 3),
                "share_of_positive_excess_in_top_decile": r(excess[topx].clip(0).sum() / excess.clip(0).sum()),
                "peak_window_excess_over_calm_window": r(excess.sum() / c24[:, wpk].sum()),
                "run_excess_over_calm_run": r(run_ex.sum() / calm_run.sum(), 5),
            })
        for gname, g in groupings.items():
            df = pd.DataFrame({"g": g, "unit": unit, "calm_unit": c24[:, wpk], "excess": excess, "run": run_tot[name],
                               "run_calm": calm_run, "top": top})
            agg = df.groupby("g", observed=True).agg(segments=("unit", "size"), unit_cost=("unit", "sum"), calm_cost=("calm_unit", "sum"),
                                      excess=("excess", "sum"), run=("run", "sum"), run_calm=("run_calm", "sum"),
                                      top=("top", "sum"))
            for gv, rr in agg.iterrows():
                sp_rows.append({"scenario": name, "grouping": gname, "group": gv, "segments": int(rr.segments),
                                "share_segments": r(rr.segments / nseg),
                                "mean_iters_per_call_peak_window": r(rr.unit_cost / rr.segments / C.WINDOWS["24h"], 3),
                                "share_peak_window_cost": r(rr.unit_cost / unit.sum()),
                                "peak_window_cost_over_calm": r(rr.unit_cost / rr.calm_cost, 4),
                                "share_peak_window_excess": r(rr.excess / excess.sum()) if name != "calm" else None,
                                "share_top_decile_segments": r(rr.top / top.sum()),
                                "run_cost_over_calm": r(rr.run / rr.run_calm, 5),
                                "mean_iters_per_call_run": r(rr.run / rr.segments / C.NTS, 3)})

    # ------------------------------------------------------------- space-time: excess by 3-h window and distance band
    st_rows = []
    codes = groupings["distance_to_outlet"].codes
    labels = list(groupings["distance_to_outlet"].categories)
    W3 = C.WINDOWS["3h"]
    for name in STORMS:
        ex = win[name]["3h"].astype(np.int64) - win["calm"]["3h"].astype(np.int64)
        cm = win["calm"]["3h"].astype(np.int64)
        for w in range(ex.shape[1]):
            row = {"scenario": name, "window_3h": w, "start_h": w * W3 * C.DT // 3600,
                   "network_cost_over_calm": r(1 + ex[:, w].sum() / cm[:, w].sum(), 4)}
            for k, lab in enumerate(labels):
                m = codes == k
                row[f"over_calm {lab}"] = r(1 + ex[m, w].sum() / cm[m, w].sum(), 4)
            st_rows.append(row)
    pd.DataFrame(st_rows).to_csv(C.TABLES / "space_time_3h.csv", index=False)

    # ------------------------------------------------------------- cost vector export
    out = pd.DataFrame({"feature_id": case["link"], "to_feature_id": seg["to"].to_numpy(),
                        "dist_to_outlet_km": seg["dist_to_outlet_km"].round(3), "n_down": seg["n_down"],
                        "up_path_segs": seg["up_path_segs"], "order": seg["order"], "slope_class": seg["slope_class"],
                        "subbasin": seg["subbasin"], "mainstem": seg["mainstem"], "calls": C.NTS})
    for name in ALL:
        out[f"iters_{name}"] = run_tot[name]
    for name in ALL:
        out[f"rel_{name}"] = (run_tot[name] / calm_mean).round(5)
    for name in ALL:                     # measured port time (timing.py), where it was run
        tp = C.RESULTS / "timing" / f"{name}.npz"
        if tp.exists():
            tz = np.load(tp)
            if np.array_equal(tz["link"], case["link"]) and np.array_equal(tz["iters"].sum(axis=1), run_tot[name]):
                out[f"port_us_{name}"] = (tz["ns"].astype(np.float64).sum(axis=1) / 1000).round(1)
    out.to_csv(cost_dir / "segment_cost.csv", index=False)

    # ------------------------------------------------------------- tables
    pc = pd.DataFrame(per_call_rows)
    pc.to_csv(C.TABLES / "iterations_per_call.csv", index=False)
    tot = pd.DataFrame(totals_rows)
    tot.to_csv(C.TABLES / "segment_totals.csv", index=False)
    wdf = pd.DataFrame(win_rows)
    wdf.to_csv(C.TABLES / "windows.csv", index=False)
    sp = pd.DataFrame(sp_rows)
    sp.to_csv(C.TABLES / "spatial.csv", index=False)
    pd.DataFrame({"hour": np.arange(1, C.HOURS + 1), **{n: hourly[n] for n in ALL}}).to_csv(
        C.TABLES / "hourly_network_cost.csv", index=False)
    md = ["# Tables (generated by analyze.py; do not edit)", ""]
    md += ["## Secant iterations per kernel call (first hour left out)", "",
           pc[["scenario", "calls_in", "calls", "mean", "cv", "p50", "p99", "p99.9", "max", "max_over_mean",
               "share_1", "share_2", "share_3", "share_4", "share_5", "share_6", "share_7plus",
               "restarts_per_1e6_calls", "fails", "guard_calls"]].to_markdown(index=False), ""]
    (C.TABLES / "iterations_per_call.md").write_text("\n".join(md) + "\n")
    (C.TABLES / "segment_totals.md").write_text("# Per-segment iterations over the run (analyze.py)\n\n"
                                                + tot.to_markdown(index=False) + "\n")
    cols = ["scenario", "window", "steps", "cv_pooled", "worst_over_mean_pooled", "cv_across_segments_median_window",
            "cv_across_segments_peak_window", "worst_over_mean_peak_window", "network_cost_peak_window_over_calm",
            "unit_ratio_to_calm_p99", "unit_ratio_to_calm_max", "unit_ratio_to_calm_min", "spearman_vs_calm_peak_window"]
    (C.TABLES / "windows.md").write_text("# Cost per unit over T-Route chunk windows (analyze.py)\n\n"
                                         + wdf[cols].to_markdown(index=False) + "\n")
    spm = ["# Where the cost is: peak 24-h window of each storm run; calm: its last 24-h window (analyze.py)", ""]
    for name in ["calm", "s25", "s250"]:
        for gname in groupings:
            spm += [f"## {name}, by {gname}", "",
                    sp[(sp.scenario == name) & (sp.grouping == gname)].drop(columns=["scenario", "grouping"])
                    .to_markdown(index=False), ""]
    (C.TABLES / "spatial.md").write_text("\n".join(spm) + "\n")

    summary = {
        "note": "generated by analyze.py; per-call statistics leave out the first hour",
        "verification": {n: verify[n]["replay_vs_closure_port"] for n in ALL},
        "per_call": {f"{rw['scenario']}/{rw['calls_in']}": {k: rw[k] for k in
                                                            ("calls", "mean", "cv", "p99", "p99.9", "max", "max_over_mean",
                                                             "share_2", "share_3", "share_7plus",
                                                             "restarts_per_1e6_calls", "fails")}
                     for rw in per_call_rows},
        "segment_totals": {rw["scenario"]: {k: v for k, v in rw.items() if k != "scenario"} for rw in totals_rows},
        "windows": {f"{rw['scenario']}/{rw['window']}": {k: v for k, v in rw.items() if k not in ("scenario", "window")}
                    for rw in win_rows},
        "clustering_peak_24h_window": clus,
        "outlet": {n: verify[n]["outlet"] for n in ALL},
        "closure_fractions": {n: verify[n]["closure_fractions_of_segment_steps"] for n in ALL},
        "negative_flow_guard_steps": {n: verify[n]["negative_flow_guard_steps"] for n in ALL},
        "long_searches_restarts_and_history": tails,
        "lowest_50km_slope_floor_share": r(float((seg.loc[seg["dist_to_outlet_km"] < 50, "slope_class"] == 0).mean())),
        "network_slope_floor_share": r(float((seg["slope_class"] == 0).mean())),
        "calm_segments_constant_iterations": r(calm_constant),
    }
    (C.TABLES / "summary.json").write_text(json.dumps(summary, indent=1, default=lambda o: o.item()
                                                      if hasattr(o, "item") else str(o)) + "\n")
    print("ok      tables/*.csv|md, tables/summary.json, results/cost/segment_cost.csv, "
          "results/cost/segment_window_cost_<scenario>.npz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
