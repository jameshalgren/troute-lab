"""Check results/summary.json against expected/expected.json (AI-written, Claude, 2026-10-09)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
S = json.loads((HERE / "results" / "summary.json").read_text())
E = json.loads((HERE / "expected" / "expected.json").read_text())
B = json.loads((HERE / "build" / "build_info.json").read_text())
fails, n = [], 0


def ok(cond, msg):
    global n
    n += 1
    if not cond:
        fails.append(msg)


ok(B["changed_lines"] == E["build_changed_lines"], f"patch changes lines {B['changed_lines']}")
ok(abs(S["reference_check"]["rel_diff_peak_excess"]) < E["reference_check_max_rel_diff_peak"],
   "Hayami vs zero-inertia small-pulse peak disagree")
for c in S["small_pulse"]:
    tag = f"dx={c['dx_m']:.0f} dt={c['dt_s']:.0f}"
    for key, target in (("linear_mc_kernel", E["theory"]["linear_mc_kernel_D_eff_over_D_phys"]),
                        ("linear_mc_cunge", E["theory"]["linear_mc_cunge_D_eff_over_D_phys"])):
        if c[key] is not None:
            ok(abs(c[key]["D_eff_over_D_phys"] - target) < 0.01, f"{tag} {key} D_eff {c[key]['D_eff_over_D_phys']:.3f}")
    o, p = c["wrfhydro_orig"]["D_eff_over_D_phys"], c["wrfhydro_patched"]["D_eff_over_D_phys"]
    if c["D_cell"] < 0.5:
        lo, hi = E["harness_unclamped_cases"]["orig_D_eff_over_D_phys_range"]
        ok(lo <= o <= hi, f"{tag} orig D_eff {o:.3f}")
        lo, hi = E["harness_unclamped_cases"]["patched_D_eff_over_D_phys_range"]
        ok(lo <= p <= hi, f"{tag} patched D_eff {p:.3f}")
    if c["D_cell"] > 1.0:
        ok(abs(o - p) < E["harness_floor_cases"]["max_abs_diff_orig_vs_patched_D_eff"], f"{tag} floor case differs")
for c in S["large_pulse"]:
    ok(c["wrfhydro_patched"]["rmse_vs_ref_over_amp"] <= c["wrfhydro_orig"]["rmse_vs_ref_over_amp"],
       f"large pulse dx={c['dx_m']:.0f} dt={c['dt_s']:.0f}: patched RMSE not <= current")
# ---- part 1, lagged upstream inflow (short-time-step assumption; added 2026-11-02)
L1 = E["short_ts"]["part1_lagged"]
for c in S["small_pulse"]:
    tag = f"lagged dx={c['dx_m']:.0f} dt={c['dt_s']:.0f}"
    o, p = c["wrfhydro_orig_lagged"], c["wrfhydro_patched_lagged"]
    if c["courant"] <= L1["theory_max_courant"]:      # K clamp not binding: celerity 1/(1 - X + C/2)
        ok(abs(o["celerity_ratio"] - c["lagged_theory_celerity_ratio_X_kernel"]) < L1["celerity_theory_abs_tol"],
           f"{tag} current celerity {o['celerity_ratio']:.3f} vs theory")
        ok(abs(p["celerity_ratio"] - c["lagged_theory_celerity_ratio_X_cunge"]) < L1["celerity_theory_abs_tol"],
           f"{tag} patched celerity {p['celerity_ratio']:.3f} vs theory")
    if c["D_cell"] > 1.0:
        ok(abs(o["D_eff_over_D_phys"] - p["D_eff_over_D_phys"]) < E["harness_floor_cases"]["max_abs_diff_orig_vs_patched_D_eff"],
           f"{tag} floor case differs")
    if c["D_cell"] < 1.0:
        chg = 100 * (p["peak_excess_over_exact"] / o["peak_excess_over_exact"] - 1)
        sh = p["t_peak_minus_exact_h"] - o["t_peak_minus_exact_h"]
        lo, hi = L1["x_effect_peak_excess_change_pct_range"]
        ok(lo <= chg <= hi, f"{tag} X effect on the peak {chg:+.1f}%")
        lo, hi = L1["x_effect_t_peak_shift_h_range"]
        ok(lo <= sh <= hi, f"{tag} X effect on peak time {sh:+.2f} h")
    for v, d in (("current", o), ("patched", p)):
        ok(abs(d["volume_ratio"] - 1) < L1["small_volume_abs_dev"], f"{tag} {v} volume {d['volume_ratio']:.4f}")
for c in S["large_pulse"]:
    tag = f"lagged large dx={c['dx_m']:.0f} dt={c['dt_s']:.0f}"
    for v in ("orig", "patched"):
        d = c[f"wrfhydro_{v}_lagged"]
        ok(d["min_flow"] >= L1["large_min_flow_m3s"], f"{tag} {v}: leading-edge dip, min {d['min_flow']:.1f}")
        lo, hi = L1["large_volume_ratio_range"]
        ok(lo <= d["volume_ratio"] <= hi, f"{tag} {v}: volume {d['volume_ratio']:.3f}")
# ---- parts 2 and 3: Potomac network (skipped with QUICK=1, when no Potomac results exist)
PS = HERE / "results" / "potomac_summary.json"
if PS.exists():
    P, EP = json.loads(PS.read_text()), E["potomac"]
    tol, phy = EP["tolerances"], EP["physics"]
    ch = P["checks"]
    for v in ("current", "patched"):
        ok(ch["max_dev_steady_first_24h_m3s"][v] < phy["steady_max_dev_m3s"], f"{v}: not steady in the first 24 h")
        ok(ch["nonconvergence_messages"][v] == phy["nonconvergence"], f"{v}: secant failed to converge")
        lo, hi = phy["outlet_volume_over_lateral_range"]
        ok(lo <= ch["outlet_volume_over_lateral_volume"][v] <= hi, f"{v}: outlet volume vs lateral inflow")
    ok(abs(ch["outlet_volume_ratio_patched_over_current"] - 1) < phy["outlet_volume_ratio_abs_dev"],
       "patch changes the outlet volume")
    fl = P["floor"]
    ok(fl["patched"]["segment_steps_share"] >= fl["current"]["segment_steps_share"], "patched X on the floor less often")
    ok(fl["patched"]["flow_weighted_share"] >= fl["current"]["flow_weighted_share"], "patched X floor, flow-weighted")
    for v in ("current", "patched"):
        for k in ("segment_steps_share", "flow_weighted_share"):
            ok(abs(fl[v][k] - EP["network_floor_share"][v][k]) <= tol["floor_share_abs"], f"network floor {v} {k}")
    got = {(r["usgs"] or "outlet"): r for r in P["records"]}
    ok(set(got) == set(EP["records"]), f"record points {sorted(set(got) ^ set(EP['records']))}")
    for key, want in EP["records"].items():
        g = got.get(key)
        if g is None:
            continue
        tag = f"record {key}"
        ok(g["link"] == want["link"], f"{tag}: link {g['link']}")
        ok(g["peak_patched_m3s"] <= g["peak_current_m3s"] + 1e-6, f"{tag}: patch raised the peak")
        for k in ("peak_current_m3s", "peak_patched_m3s"):
            ok(abs(g[k] / want[k] - 1) <= tol["peak_rel"], f"{tag}: {k} {g[k]} vs {want[k]}")
        ok(abs(g["peak_excess_change_pct"] - want["peak_excess_change_pct"]) <= tol["change_pct_abs"], f"{tag}: change")
        ok(abs(g["t_peak_shift_h"] - want["t_peak_shift_h"]) <= tol["shift_h_abs"], f"{tag}: shift")
        for k in ("floor_share_current", "floor_share_patched"):
            ok(abs(g[k] - want[k]) <= tol["floor_share_abs"], f"{tag}: {k}")
        if g["usgs_area_km2"] and g["usgs_area_km2"] < phy["small_stream_area_km2"]:
            ok(abs(g["peak_change_pct"]) <= phy["small_stream_max_abs_change_pct"], f"{tag}: small stream changed")
    # ---- parts 2-3, sequential upstream inflow (not WRF-Hydro's driver; added 2026-11-02)
    SQ, ES = P.get("sequential"), E["short_ts"]
    ok(SQ is not None, "no sequential-mode results (network_driver ... sequential)")
    if SQ is not None:
        es = ES["potomac_sequential"]
        chs = SQ["checks"]
        for v in ("current", "patched"):
            ok(chs["max_dev_steady_first_24h_m3s"][v] < phy["steady_max_dev_m3s"], f"sequential {v}: not steady")
            # warning counts depend on compiler rounding with STS OFF (3/2 at -O2, 0/3 without FMA): a bound
            ok(chs["nonconvergence_messages"][v] <= es["max_nonconvergence"],
               f"sequential {v}: {chs['nonconvergence_messages'][v]} non-convergence messages")
            lo, hi = es["outlet_volume_over_lateral_range"]
            ok(lo <= chs["outlet_volume_over_lateral_volume"][v] <= hi, f"sequential {v}: outlet volume vs lateral")
        gs = {(r["usgs"] or "outlet"): r for r in SQ["records"]}
        tol_s = es["tolerances"]   # STS OFF values move between compiler builds; see expected.json
        for key, want in es["records"].items():
            g = gs.get(key)
            ok(g is not None, f"sequential record {key} missing")
            if g is None:
                continue
            tag = f"sequential record {key}"
            for k in ("peak_current_m3s", "peak_patched_m3s"):
                ok(abs(g[k] / want[k] - 1) <= tol_s["peak_rel"], f"{tag}: {k} {g[k]} vs {want[k]}")
            ok(abs(g["peak_excess_change_pct"] - want["peak_excess_change_pct"]) <= tol_s["change_pct_abs"], f"{tag}: change")
            ok(abs(g["t_peak_shift_h"] - want["t_peak_shift_h"]) <= tol_s["shift_h_abs"], f"{tag}: shift")
        MC, em = P["mode_comparison"], ES["mode_effect_outlet_short_ts_switch"]
        out = next(r for r in MC["records"] if not r["usgs"])
        ok(abs(out["mode_peak_change_pct"] - em["peak_change_pct"]) <= em["peak_change_tol_pct"],
           f"outlet lagged vs sequential {out['mode_peak_change_pct']}% vs ../short_ts_switch")
        ok(abs(out["mode_t_peak_shift_h"] - em["shift_h"]) <= em["shift_tol_h"],
           f"outlet lagged vs sequential {out['mode_t_peak_shift_h']} h vs ../short_ts_switch")
        TR0, T0 = SQ.get("troute_comparison"), ES["troute_sts0"]
        if TR0 is not None:
            ok(TR0["max_abs_diff_peak_change_pct_points"] <= T0["max_abs_diff_peak_change_pct_points"],
               f"T-Route False vs sequential: peak change differs by {TR0['max_abs_diff_peak_change_pct_points']} points")
            ok(TR0["max_abs_diff_shift_h"] <= T0["max_abs_diff_shift_h"], f"T-Route False vs sequential shift {TR0['max_abs_diff_shift_h']} h")
            ok(TR0["max_abs_diff_current_peak_pct"] <= T0["max_abs_diff_current_peak_pct"],
               f"T-Route False vs sequential current peaks {TR0['max_abs_diff_current_peak_pct']} %")
            o0 = next(r for r in TR0["records"] if not r["usgs"])
            ok(abs(o0["troute_peak_current_m3s"] / o0["wrfhydro_peak_current_m3s"] - 1) * 100 <= T0["outlet_current_peak_pct"],
               "T-Route False vs sequential: outlet peak")
            ok(abs(o0["troute_peak_change_pct"] - o0["wrfhydro_peak_change_pct"]) <= T0["outlet_change_pct_points"],
               "T-Route False vs sequential: outlet X effect")
    TR = P.get("troute_comparison")
    if TR is not None:
        T = EP["troute"]
        ok(TR["max_abs_diff_peak_change_pct_points"] <= T["max_abs_diff_peak_change_pct_points"],
           f"T-Route vs WRF-Hydro peak change differs by {TR['max_abs_diff_peak_change_pct_points']} points")
        ok(TR["max_abs_diff_shift_h"] <= T["max_abs_diff_shift_h"], f"T-Route vs WRF-Hydro shift {TR['max_abs_diff_shift_h']} h")
        ok(TR["max_abs_diff_current_peak_pct"] <= T["max_abs_diff_current_peak_pct"],
           f"T-Route vs WRF-Hydro current peaks {TR['max_abs_diff_current_peak_pct']} %")
        out = next(r for r in TR["records"] if not r["usgs"])
        ok(abs(out["troute_peak_change_pct"] - T["outlet_change_pct_kernel_fixes"]) <= T["outlet_change_tol"],
           f"T-Route outlet change {out['troute_peak_change_pct']} vs ../kernel_fixes")
        ok(abs(out["troute_shift_h"] - T["outlet_shift_h_kernel_fixes"]) <= T["outlet_shift_tol_h"],
           f"T-Route outlet shift {out['troute_shift_h']} vs ../kernel_fixes")
    else:
        print("skip    part 3 checks (no T-Route comparison in results/potomac_summary.json)")
else:
    print("skip    parts 2-3 checks (no results/potomac_summary.json; QUICK=1?)")

# ---- part 1 under NWM conditions (reaches.py, after part 2; added 2026-11-02)
RS = HERE / "results" / "reaches_summary.json"
if RS.exists():
    R, ER = json.loads(RS.read_text()), E["reaches"]
    tol, phy = ER["tolerances"], ER["physics"]
    got = {c["key"]: c for c in R["cases"]}
    ok(set(got) == set(ER["cases"]), f"reach cases {sorted(set(got) ^ set(ER['cases']))}")
    for key, want in ER["cases"].items():
        c = got.get(key)
        if c is None:
            continue
        on = c["sts_on"]
        for v in ("orig", "patched"):
            tag = f"reach {key} STS ON {v}"
            ok(on[v]["nonconvergence_warnings"] == 0, f"{tag}: secant failed to converge")
            ok(on[v]["min_flow_m3s"] >= c["inflow_base_m3s"] * phy["sts_on_min_flow_over_base"], f"{tag}: dip")
            lo, hi = phy["sts_on_volume_ratio_range"]
            ok(lo <= on[v]["volume_ratio"] <= hi, f"{tag}: volume {on[v]['volume_ratio']:.4f}")
        ok(on["patched"]["peak_m3s"] <= on["orig"]["peak_m3s"] * (1 + 1e-6), f"reach {key}: patch raised the peak")
        ok(abs(c["reference_peak_m3s"] / want["reference_peak_m3s"] - 1) <= tol["reference_peak_rel"],
           f"reach {key}: reference peak {c['reference_peak_m3s']:.2f}")
        ok(c["network_analogs"]["n_links"] == want["n_analog_links"], f"reach {key}: {c['network_analogs']['n_links']} analog links")
        for mk in ("sts_on", "sts_off"):
            m, w = c[mk], want[mk]
            t = tol if mk == "sts_on" else ER["sts_off_tolerances"]   # STS OFF is compiler-sensitive
            tag = f"reach {key} {mk}"
            ok(abs(m["orig"]["peak_m3s"] / w["peak_current_m3s"] - 1) <= t["peak_rel"], f"{tag}: current peak")
            ok(abs(m["peak_change_pct"] - w["peak_change_pct"]) <= t["change_pct_abs"], f"{tag}: peak change")
            ok(abs(m["t_peak_shift_h"] - w["t_peak_shift_h"]) <= t["shift_h_abs"], f"{tag}: shift")
    # the main stem at the slope floor: X on its floor in both versions, so the patch does nothing
    m = got["main_2p5km"]
    ok(m["x_cell_number"]["at_base"] >= 1.0 and abs(m["sts_on"]["peak_change_pct"]) < 1e-3, "main stem: X not floored")
    ok(m["network_analogs"]["part2_x_floor_share_current"] >= phy["main_floor_share_min"], "main-stem analogs: floor share")
else:
    print("skip    part 1 NWM-condition checks (no results/reaches_summary.json)")

print(f"{n - len(fails)}/{n} checks passed")
for f in fails:
    print("FAIL:", f)
sys.exit(1 if fails else 0)
