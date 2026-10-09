"""Check this reproduction. Exit status 0 = every check passed.

1. Self-consistency (bitwise): the runs in CHECK_RUNS were repeated by run.sh into
   results/rerun/; every array must be identical to the first run (same machine, same
   build). T-Route's MC kernel at this commit compiles without uninitialized-variable
   warnings (gfortran -Wall), so it should be deterministic.
2. Physical sanity: all outputs finite; in the storm cases the first 24 h are steady
   (exact steady initial state, constant baseflow), so True and False must agree there
   to < 1e-3 m3/s; the numpy Courant/X formulas used in analyze.py must match the
   compiled Fortran kernel (rel. diff < 1e-4 for ck and Cn; abs. diff < 0.01 for X,
   because the kernel's X uses the flow at its last secant iterate, not the final flow).
3. Theory: in the storm case the linear prediction of the outlet centroid shift
   (README "Why") must have the same sign as the measured shift at every dt.
4. Mechanism (results/mechanism.json, mechanism.py): the kernel port reproduces T-Route's
   own mainstem outputs (< 1e-3 of peak); linear MC with constant coefficients matches the
   exact discrete moments (shift per reach dt/2 - Km*X within 1 s, variance within 1%,
   volume conserved) for smooth inflow; the per-segment volume balances add up to the
   outlet deficit; on replayed mainstem segments in - out equals the two storage-equation
   sums (relative 1e-6), the inflow term is identically zero with True, and the port's
   in - out matches T-Route's within 5%.
5. Regression against expected/expected.json (values from the first reproduction,
   macOS arm64, 2026-10-07; see the README). Tolerances: flows rel. 2e-3; peak times
   +-max(0.05 h, dt); percentages abs. 0.5 percentage points; NSE/KGE abs. 0.005.
   These allow for float32 rounding differences across compilers/platforms but would
   catch any change in the model or the setup.

    uv run python check.py                # all checks
    uv run python check.py --no-rerun     # skip the bitwise rerun check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_experiment import CHECK_RUNS  # noqa: E402

RES = HERE / "results"
EXPECTED = HERE / "expected" / "expected.json"

results: list[tuple[bool, str]] = []


def ok(cond: bool, msg: str) -> None:
    results.append((bool(cond), msg))


def get(d: dict, path: str):
    for k in path.split("/"):
        d = d[k]
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rerun", action="store_true")
    args = ap.parse_args()
    res = json.loads((RES / "results.json").read_text())
    cases = res["cases"]

    # 1. bitwise self-consistency
    if not args.no_rerun:
        for case, dt, sts in CHECK_RUNS:
            name = f"{case}/dt{dt}_sts{int(sts == 'true')}.npz"
            a, b = np.load(RES / "runs" / name), np.load(RES / "rerun" / name)
            keys = [k for k in a.files if k != "wall_s"]
            same = all(np.array_equal(a[k], b[k]) for k in keys)
            ok(same, f"rerun bitwise identical: {name} ({len(keys)} arrays)")

    # 2. sanity
    for case, c in cases.items():
        for dt in res["dts_s"]:
            for sts in (0, 1):
                r = np.load(RES / "runs" / case / f"dt{dt}_sts{sts}.npz")
                ok(bool(r["finite"]), f"finite outputs: {case} dt={dt} sts={sts}")
        if case.endswith("storm"):
            for dt in res["dts_s"]:
                a = np.load(RES / "runs" / case / f"dt{dt}_sts1.npz")["q_hourly"][:, :24]
                b = np.load(RES / "runs" / case / f"dt{dt}_sts0.npz")["q_hourly"][:, :24]
                ok(np.abs(a - b).max() < 1e-3,
                   f"steady first 24 h identical (<1e-3 m3/s): {case} dt={dt} "
                   f"(max {np.abs(a - b).max():.2e})")
        kc = c["kernel_check"]
        ok(kc["max_rel_diff_ck"] < 1e-4 and kc["max_rel_diff_cn"] < 1e-4 and kc["max_abs_diff_X"] < 0.01,
           f"numpy ck/Cn/X match Fortran kernel: {case} ({kc['max_rel_diff_ck']:.1e}, "
           f"{kc['max_rel_diff_cn']:.1e}, {kc['max_abs_diff_X']:.1e})")

    # 3. linear theory: the predicted and measured outlet centroid shifts share their sign
    for case in (k for k in cases if k.endswith("storm")):
        for dt in res["dts_s"]:
            c = cases[case]["by_dt"][str(dt)]["centroid"]
            m, p = c["outlet_measured_shift_h"], c["outlet_predicted_shift_h"]
            ok(np.sign(m) == np.sign(p), f"theory sign: {case} dt={dt} outlet centroid shift "
               f"measured {m} h, predicted {p} h")

    # 4. mechanism checks (mechanism.py)
    mpath = RES / "mechanism.json"
    if not mpath.exists():
        ok(False, "results/mechanism.json missing (run mechanism.py)")
    else:
        mech = json.loads(mpath.read_text())
        rp = mech["A_port_vs_troute_mainstem_replay"]["max_rel_diff_of_peak"]
        ok(max(rp.values()) < 1e-3, f"mechanism: kernel port reproduces T-Route mainstem outputs ({rp})")
        lin = [r for r in mech["B_linear"] if r["wave"] == "smooth" and r["N"] <= 10]
        ok(all(abs(r["shift_per_reach_s"] - r["dt/2-Km*X_s"]) <= 1.0 for r in lin),
           f"mechanism: linear MC shift per reach = dt/2 - Km*X within 1 s ({len(lin)} cases)")
        ok(all(abs(r["var_per_reach_false_h2"] - r["analytic_var_false_h2"]) <= 0.01 * max(r["analytic_var_false_h2"], 0.2)
               and abs(r["var_per_reach_true_h2"] - r["analytic_var_true_h2"]) <= 0.01 * r["analytic_var_true_h2"]
               for r in lin), "mechanism: linear MC variances match the exact discrete values within 1%")
        ok(all(abs(r["volume_ratio_false"] - 1) < 1e-5 and abs(r["volume_ratio_true"] - 1) < 1e-5 for r in lin),
           "mechanism: linear MC (constant coefficients, smooth inflow) conserves volume in both settings")
        net = mech["D_mass_balance"]["network"]
        ok(all(abs(net[str(dt)][s]["sum_segment_losses_pct_of_storm"] - 100 * (1 - net[str(dt)][s]["outlet_event_balance"])) < 0.05
               for dt in res["dts_s"] for s in ("true", "false")),
           "mechanism: per-segment volume balances add up to the outlet deficit (all dt, both settings)")
        dec = mech["D_mass_balance"]["mainstem_decomposition_dt300"]
        ok(dec["false"]["identity_residual_rel"] < 1e-6 and dec["true"]["identity_residual_rel"] < 1e-6,
           "mechanism: in - out = sum Km*X*dI + sum Km*(1-X)*dO on replayed mainstem segments")
        ok(dec["true"]["sum_KX_dI_m3"] == 0.0, "mechanism: inflow storage term is identically zero with True")
        ok(dec["false"]["port_vs_troute_loss_rel"] < 0.05 and dec["true"]["port_vs_troute_loss_rel"] < 0.05,
           f"mechanism: replayed segment losses match T-Route's volumes (rel {dec['false']['port_vs_troute_loss_rel']}, "
           f"{dec['true']['port_vs_troute_loss_rel']})")

    # 5. regression
    if EXPECTED.exists():
        exp = json.loads(EXPECTED.read_text())
        for item in exp["values"]:
            got = get(cases, item["path"])
            want, kind = item["value"], item["kind"]
            if want is None or got is None:
                ok(want is None and got is None, f"{item['path']}: {got} vs expected {want}")
                continue
            if kind == "flow":
                tol = 2e-3 * max(abs(want), 1e-6)
            elif kind == "time":
                tol = max(0.05, item.get("dt_s", 0) / 3600)
            elif kind == "pct":
                tol = 0.5
            else:
                tol = 0.005
            ok(abs(got - want) <= tol, f"{item['path']}: {got} vs expected {want} (tol {tol:g})")
    else:
        ok(False, "expected/expected.json missing")

    n_bad = sum(not r for r, _ in results)
    for r, msg in results:
        if not r or "--verbose" in sys.argv:
            print(("PASS " if r else "FAIL ") + msg)
    print(f"{len(results) - n_bad}/{len(results)} checks passed")
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
