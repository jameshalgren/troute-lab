"""Checks for the MC cost-variability experiment. Exit 1 if any check fails.

    uv run --locked python check.py                    # all checks
    uv run --locked python check.py --write-expected   # first reproduction only: freeze regression values

1. Instrumentation: for every scenario, every kernel call replayed through the unmodified
   ../short_ts_switch/closure_port.mc_kernel gives bitwise the same outflow and depth, and
   the same iteration and try counts, as mc_count (simulate.py, verify.json).
2. Port-driven routing vs T-Route: the 25 mm runs against T-Route's own values for the
   same case (../short_ts_switch/expected/expected.json and closure.json, corrected
   kernel, macOS arm64), with that experiment's tolerances (flows rel 2e-3, fractions
   abs 0.005, counts rel 10%, volume balance abs 0.005). One documented exception: the
   True - False peak-time shift is allowed 0.25 h (3 steps) instead of max(0.05 h, dt),
   because the False run's trajectory drifts (README "Verification").
3. Cost export: segment_cost.csv covers the 16,454 Potomac feature ids once each, the
   downstream ids close the tree at the outlet 4539621, and run totals equal the sums of
   the window files.
4. replay_record.py self-test (if run): counts identical to simulate.py's.
5. Timing (if run): time per call grows with iterations (b > 0).
6. Regression: headline numbers against expected/expected.json (first reproduction).
"""
from __future__ import annotations

import argparse
import json
import sys

import common as C
import numpy as np
import pandas as pd

FAILS: list[str] = []
N = [0]


def ok(cond: bool, msg: str) -> None:
    N[0] += 1
    print(f"{'ok' if cond else 'FAIL':8}{msg}")
    if not cond:
        FAILS.append(msg)


def ev(path: str, src: str) -> float:
    d = json.loads((C.STS_DIR / "expected" / src).read_text())
    for v in d["values"]:
        if v["path"] == path:
            return float(v["value"])
    raise KeyError(path)


REG_KEYS = {
    # path in tables/summary.json -> tolerance (abs for 'a', rel for 'r')
    "per_call/calm/all/mean": ("a", 1e-3), "per_call/s25/all/mean": ("a", 1e-3),
    "per_call/s250/all/mean": ("a", 1e-3), "per_call/s25/flood_all/mean": ("a", 1e-3),
    "per_call/s250/flood_all/mean": ("a", 1e-3), "per_call/s25/all/max": ("r", 0.1),
    "segment_totals/calm/cv_across_segments": ("a", 1e-3), "segment_totals/s25/cv_across_segments": ("a", 1e-3),
    "segment_totals/calm/max_over_mean": ("a", 1e-2), "segment_totals/s25/network_total_over_calm": ("a", 1e-4),
    "windows/s25/24h/network_cost_peak_window_over_calm": ("a", 1e-3),
    "windows/s25/24h/cv_across_segments_peak_window": ("a", 1e-3),
    "windows/s25/1h/network_cost_peak_window_over_calm": ("a", 1e-3),
    "windows/s250/24h/network_cost_peak_window_over_calm": ("a", 1e-3),
    "windows/s25/24h/spearman_vs_calm_peak_window": ("a", 0.02),
    "clustering_peak_24h_window/calm/eta2_slope_class_unit_cost": ("a", 0.01),
    "clustering_peak_24h_window/calm/top_decile_adjacency_lift_unit_cost": ("a", 0.05),
    "outlet/s25/peak_m3s": ("r", 1e-4), "outlet/s100/peak_m3s": ("r", 1e-4), "outlet/s250/peak_m3s": ("r", 1e-4),
}


def get(d: dict, path: str):
    parts = path.split("/")
    # keys of per_call and windows are "scenario/label"
    if parts[0] in ("per_call", "windows"):
        return d[parts[0]][f"{parts[1]}/{parts[2]}"][parts[3]]
    x = d
    for p in parts:
        x = x[p]
    return x


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write-expected", action="store_true")
    args = ap.parse_args()
    summ = json.loads((C.TABLES / "summary.json").read_text())

    # 1. instrumentation
    for name in C.SCENARIOS:
        v = json.loads((C.run_dir(name) / "verify.json").read_text())
        r = v["replay_vs_closure_port"]
        ok(r["calls"] == C.NTS * 16454 and r["q_not_bitwise_equal"] == 0 and r["h_not_bitwise_equal"] == 0
           and r["iterations_differ"] == 0 and r["tries_differ"] == 0,
           f"{name}: all {r['calls']} calls identical to closure_port.mc_kernel (outflow, depth, iterations, tries)")
        ok(v["inactive_calls"] == 0, f"{name}: every call routes water (no early returns)")

    # 2. vs T-Route
    vt = json.loads((C.run_dir("s25") / "verify.json").read_text())
    vf = json.loads((C.run_dir("s25_f") / "verify.json").read_text())
    for v, sts, tag in [(vt, 1, "true"), (vf, 0, "false")]:
        e = ev(f"potomac_storm/by_dt/300/outlet/peak_{tag}_m3s", "expected.json")
        got = v["outlet"]["peak_m3s"]
        ok(abs(got / e - 1) <= 2e-3, f"s25 sts={tag}: outlet peak {got:.2f} vs T-Route {e:.2f} m3/s (rel {got / e - 1:+.1e}, tol 2e-3)")
        e = ev(f"potomac_storm/by_dt/300/event_volume_balance/outlet_{tag}", "expected.json")
        got = v["outlet"]["event_volume_balance"]
        ok(abs(got - e) <= 0.005, f"s25 sts={tag}: outlet event volume balance {got:.4f} vs T-Route {e:.4f} (tol 0.005)")
        for k in ("clamp", "floor", "over"):
            e = ev(f"closure/potomac_storm/dt300_sts{sts}/fractions_of_segment_steps/{k}", "closure.json")
            got = v["closure_fractions_of_segment_steps"][k]
            ok(abs(got - e) <= 0.005, f"s25 sts={tag}: closure fraction {k} {got:.5f} vs T-Route {e:.5f} (tol 0.005)")
        e = ev(f"closure/potomac_storm/dt300_sts{sts}/negative_flow_guard_steps", "closure.json")
        got = v["negative_flow_guard_steps"]
        ok(abs(got - e) <= 0.1 * max(e, 1) if e > 0 else got == 0,
           f"s25 sts={tag}: negative-flow guard steps {got} vs T-Route {int(e)} (tol rel 10%)")
    e = ev("potomac_storm/by_dt/300/outlet/peak_time_shift_h", "expected.json")
    got = vt["outlet"]["peak_time_h"] - vf["outlet"]["peak_time_h"]
    ok(abs(got - e) <= 0.25, f"s25: peak-time shift True - False {got:.3f} h vs T-Route {e:.3f} h "
                              f"(tol 0.25 h; check.py of ../short_ts_switch uses 0.083 h, see README)")

    # 3. cost export
    case = C.load_case()
    sc = pd.read_csv(C.RESULTS / "cost" / "segment_cost.csv")
    ids = set(case["link"].tolist())
    ok(len(sc) == 16454 and sc["feature_id"].is_unique and set(sc["feature_id"]) == ids,
       "segment_cost.csv: 16,454 unique NWM feature ids = the Potomac network")
    out = sc[~sc["to_feature_id"].isin(ids)]
    ok(len(out) == 1 and int(out["feature_id"].iloc[0]) == 4539621 and int(out["to_feature_id"].iloc[0]) == 0,
       "segment_cost.csv: every to_feature_id is in the network except the outlet 4539621 (to = 0)")
    for name in C.SCENARIOS:
        z = np.load(C.RESULTS / "cost" / f"segment_window_cost_{name}.npz")
        same = all(np.array_equal(z[f"iters_{w}"].sum(axis=1, dtype=np.int64), sc[f"iters_{name}"].to_numpy())
                   for w in ("1h", "3h", "24h"))
        ok(same and np.array_equal(z["feature_id"], sc["feature_id"].to_numpy()) and (sc[f"iters_{name}"] > 0).all(),
           f"{name}: window costs (1 h, 3 h, 24 h) sum to the run totals in segment_cost.csv")

    # 4. self-test
    for p in sorted(C.RESULTS.glob("runs/selftest_*/selftest.json")):
        s = json.loads(p.read_text())
        ok(bool(s["ok"]), f"replay_record.py self-test on {s['scenario']}: counts identical to simulate.py")

    # 5. timing
    tp = C.RESULTS / "timing.json"
    if tp.exists():
        t = json.loads(tp.read_text())
        for name, u in t["units"].items():
            ok(u["ns_per_iteration_b"] > 0, f"timing {name}: time per call grows with iterations "
                                            f"({u['ns_per_call_fixed_a']:.1f} ns + {u['ns_per_iteration_b']:.1f} ns/iteration, "
                                            f"R2 {u['r2_time_vs_model']:.3f})")
    else:
        print("note    results/timing.json absent (timing.py not run); timing checks skipped")

    # 6. regression
    exp_path = C.HERE / "expected" / "expected.json"
    if args.write_expected:
        exp_path.parent.mkdir(exist_ok=True)
        vals = [{"path": k, "value": get(summ, k), "tol": list(t)} for k, t in REG_KEYS.items()]
        exp_path.write_text(json.dumps({"source": "first reproduction, macOS arm64, numba 0.61.2, 2026-10-30 "
                                                  "(Claude, AI, for James Halgren)", "values": vals}, indent=1) + "\n")
        print(f"note    wrote {exp_path.relative_to(C.HERE)} ({len(vals)} values)")
    if not exp_path.exists():
        ok(False, "expected/expected.json missing (first reproduction: check.py --write-expected)")
        print(f"\n{N[0] - len(FAILS)} of {N[0]} checks passed")
        return 1
    exp = json.loads(exp_path.read_text())
    for v in exp["values"]:
        got = get(summ, v["path"])
        kind, tol = v["tol"]
        good = abs(got - v["value"]) <= tol if kind == "a" else abs(got - v["value"]) <= tol * abs(v["value"])
        ok(good, f"regression {v['path']}: {got} vs {v['value']} ({'abs' if kind == 'a' else 'rel'} {tol})")

    print(f"\n{N[0] - len(FAILS)} of {N[0]} checks passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
