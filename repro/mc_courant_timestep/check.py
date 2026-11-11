"""Compare results/ with expected/. Exit 1 on any mismatch in a checked quantity.

Primary (courant_test.ipynb), gating:
  * peak time within +-1 output interval (dt/3600 h) of the notebook's printed value
  * max Courant number within +-0.01 of the notebook's legend value
  * regression baseline: outlet peak flow within rtol 1e-4 of this reproduction's
    2026-10-05 values (guards against toolchain drift; not a notebook value)
  * the expected peak times equal the numbers printed in the saved notebook (parsed
    from data/courant/courant_test.ipynb, so expected/ cannot drift from the source)
Exploratory (mc_numerical_dispersion.ipynb), gating only for runs the notebook's
numbers can be reproduced for (init_zero build, assume_short_ts=False, rtol 1e-5);
everything else is reported.
Extension (run_extended.py, dt up to 14400 s), gating: self-consistency (the extended
driver reproduces the notebook configuration exactly; the instrumented port matches the
compiled kernel; the wave clears; forcing volumes) and a regression baseline from the
extension's own run (expected/extended.json). Runs unless --primary-only is given without
--with-extended.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
EXP = HERE / "expected"
fails: list[str] = []


def report(ok: bool, msg: str, gate: bool = True) -> None:
    tag = ("ok  " if ok else "FAIL") if gate else ("info" if ok else "DIFF")
    print(f"  {tag} {msg}")
    if gate and not ok:
        fails.append(msg)


def load(p: Path):
    if not p.exists():
        print(f"FAIL: {p.relative_to(HERE)} not found; run run.sh")
        sys.exit(1)
    return json.loads(p.read_text())


def notebook_peak_times() -> list[float]:
    nb = json.loads((HERE / "data" / "courant" / "courant_test.ipynb").read_text())
    text = "".join("".join(o.get("text", "")) for c in nb["cells"] if c["cell_type"] == "code"
                   for o in c.get("outputs", []))
    return [float(x) for x in re.findall(r"Peak time =\s+\[\s*([0-9.]+)\s*\]", text)]


def main() -> int:
    print("Primary: courant_test.ipynb (dx = 2000 m, 20 km, dt = 30..600 s)")
    exp = load(EXP / "courant_test.json")
    got = {r["dt_s"]: r for r in load(RES / "courant_test.json")["runs"]}
    nb_pk = notebook_peak_times()
    report(nb_pk == [e["peak_time_h"] for e in exp["runs"]],
           f"expected peak times match saved notebook output {nb_pk}")
    for e in exp["runs"]:
        dt = e["dt_s"]
        g = got.get(dt)
        if g is None:
            report(False, f"dt={dt}: missing")
            continue
        tol = dt / 3600
        pk = g["peak_time_h"]
        report(len(pk) == 1 and abs(pk[0] - e["peak_time_h"]) <= tol + 1e-9,
               f"dt={dt:4d} s peak time {pk} h vs notebook {e['peak_time_h']} h (tol +-{tol:.4f} h)")
        report(abs(g["max_courant"] - e["max_courant"]) <= 0.01 + 1e-12,
               f"dt={dt:4d} s max C {g['max_courant']:.4f} vs notebook {e['max_courant']} (tol +-0.01)")
    base = exp["regression_baseline"]
    for dt, want in base["peak_flow_cms"].items():
        have = got[int(dt)]["peak_flow_cms"]
        report(math.isclose(have, want, rel_tol=base["rtol"]),
               f"dt={int(dt):4d} s peak flow {have:.3f} vs baseline {want} (rtol {base['rtol']:g})")

    if "--primary-only" not in sys.argv or "--with-extended" in sys.argv:
        check_extended()
    check_corrected()
    if "--primary-only" in sys.argv:
        print("\nExploratory checks skipped (--primary-only)")
        return finish()
    print("\nExploratory: mc_numerical_dispersion.ipynb (dx = 300 m, dt = 5..600 s)")
    exp = load(EXP / "dispersion_notebook.json")
    rtol = exp["rtol"]
    for variant in ("init_zero", "notebook_flags"):
        p = RES / f"dispersion_{variant}.json"
        if not p.exists():
            report(variant != "init_zero", f"{p.name} missing")
            continue
        runs = {r["dt_s"]: r for r in load(p)["runs"] if r["assume_short_ts"] is False}
        print(f" build {variant}, assume_short_ts=False vs notebook:")
        for e in exp["runs"]:
            g = runs.get(e["dt_s"])
            if g is None:
                continue
            ok = (math.isclose(g["courant_at_peakflow"], e["courant_at_peakflow"], rel_tol=rtol)
                  and math.isclose(g["max_depth_outlet_m"], e["max_depth_outlet_m"], rel_tol=rtol))
            gate = variant == "init_zero" and e["reproducible"]
            report(ok, f"dt={e['dt_s']:4d} s C@peak {g['courant_at_peakflow']:.8g} vs {e['courant_at_peakflow']}, "
                       f"max depth {g['max_depth_outlet_m']:.8g} vs {e['max_depth_outlet_m']} m"
                       + ("" if gate else "  [not checked]"), gate=gate)
    return finish()


def check_extended() -> None:
    """Extension to dt = 14400 s (run_extended.py). No 2020 values exist beyond 600 s, so
    these are self-consistency checks plus a regression baseline from this extension's
    own run (expected/extended.json)."""
    print("\nExtension: dt = 30..14400 s, 120 h (run_extended.py; self-consistency + regression)")
    exp = load(EXP / "extended.json")
    got = load(RES / "extended_summary.json")
    sc = exp["self_consistency"]
    cons = got["notebook_consistency_max_abs_diff_cms"]
    report(all(v == sc["notebook_consistency_max_abs_diff_cms"] for v in cons.values()),
           f"extended driver at the notebook's 15 h / point forcing reproduces reach_sim exactly {cons}")
    runs = got["runs"]
    allr = [r for rs in runs.values() for r in rs]
    pq = max(r["port_agreement"]["max_rel_diff_flow"] for r in allr)
    pdp = max(r["port_agreement"]["max_rel_diff_depth"] for r in allr)
    report(pq <= sc["port_max_rel_diff_flow"] and pdp <= sc["port_max_rel_diff_depth"],
           f"instrumented port vs compiled kernel, same inputs: max rel diff flow {pq:.2e}, depth {pdp:.2e} "
           f"(tol {sc['port_max_rel_diff_flow']:g})")
    res = max(r["end_residual_over_peak_excess"] for r in allr)
    report(res <= sc["end_residual_over_peak_excess_max"],
           f"wave has cleared the outlet at 120 h in every run: max end residual {res:.1e} of peak excess")
    drift = max(r["baseline_drift_max_cms"] for r in allr)
    report(drift <= sc["baseline_drift_max_cms"], f"no-pulse baseline stays at 2000 m3/s: max drift {drift:.4f} m3/s")
    vin = max(abs(r["injected_over_pulse_volume"] - 1) for v in runs if v != "core_point" for r in runs[v])
    report(vin <= sc["volume_forcing_injected_over_pulse_volume_abs_tol"],
           f"volume-consistent forcing injects the pulse volume at every dt: max |ratio - 1| {vin:.1e}")
    # both limits bind (Km = dt, X = 0.25) -> C1..C3 = 0.6, 0.2, 0.2 whatever the channel,
    # so the two low-slope channels must give the same outlet hydrograph there
    for (a, b) in [("slope_1e-4", "slope_1e-5")]:
        for ra, rb in zip(runs[a], runs[b]):
            ca, cb = ra["closure"], rb["closure"]
            if ca["frac_Km_clamped_to_dt"] == 1 and cb["frac_Km_clamped_to_dt"] == 1 \
                    and ca["frac_X2_floor_0p25"] == 1 and cb["frac_X2_floor_0p25"] == 1:
                report(math.isclose(ra["peak_flow_cms"], rb["peak_flow_cms"], rel_tol=1e-6)
                       and ra["peak_time_h"] == rb["peak_time_h"],
                       f"dt={ra['dt_s']:5d} s: both limits bind in both slopes -> identical peaks "
                       f"({ra['peak_flow_cms']:.3f} vs {rb['peak_flow_cms']:.3f} m3/s)")
    base = exp["baseline"]
    n_ok = n = 0
    for v, rs in runs.items():
        for r in rs:
            e = base.get(v, {}).get(str(r["dt_s"]))
            n += 1
            if e is None:
                report(False, f"{v} dt={r['dt_s']}: no baseline")
                continue
            c = r["closure"]
            checks = [
                abs(r["peak_time_h"] - e["peak_time_h"]) <= r["dt_s"] / 3600 + 1e-9,
                math.isclose(r["peak_flow_cms"], e["peak_flow_cms"], rel_tol=1e-4),
                math.isclose(r["max_courant"], e["max_courant"], rel_tol=1e-4),
                abs(r["volume_ratio_out_over_in"] - e["volume_ratio_out_over_in"]) <= 1e-4,
                abs(r["injected_over_pulse_volume"] - e["injected_over_pulse_volume"]) <= 1e-6,
                abs(c["frac_Km_clamped_to_dt"] - e["frac_Km_clamped_to_dt"]) <= 0.01,
                abs(c["frac_X2_floor_0p25"] - e["frac_X2_floor_0p25"]) <= 0.01,
            ]
            if all(checks):
                n_ok += 1
            else:
                report(False, f"{v} dt={r['dt_s']}: regression mismatch {checks} "
                              f"(peak {r['peak_time_h']} h {r['peak_flow_cms']:.4f}, V {r['volume_ratio_out_over_in']:.6f})")
    report(n_ok == n, f"regression baseline: {n_ok}/{n} runs within tolerance "
                      "(peak time, peak flow, max C, volumes, clamp/floor fractions)")


def check_corrected() -> None:
    """Corrected 2020 kernel (run_corrected.py, added 2026-10-09). On this channel only the
    degenerate-root restart (FIX 0008) is ever taken, in a few early steps: results must
    match the faithful kernel to within 1e-6 of peak (primary), and 0.001% peak flow,
    0.01 h travel time and 1e-4 volume ratio (extension)."""
    p = RES / "corrected_kernel.json"
    print("\nCorrected kernel (run_corrected.py; ../kernel_fixes/patches/anw2020/)")
    if not p.exists():
        report(False, f"{p.name} missing (run run_corrected.py)")
        return
    d = load(p)
    prim = d["primary"]
    worst = max(x["outlet_max_abs_diff_cms"] / x["faithful"]["peak_flow_cms"] for x in prim.values())
    report(worst < 1e-6, f"primary experiment: outlet hydrographs within {worst:.2g} of peak at all {len(prim)} dt")
    n = sum(len(v) for v in d["extended"].values())
    good = sum(1 for v in d["extended"].values() for x in v.values()
               if abs(x["peak_flow_change_pct"]) < 1e-3 and abs(x["travel_time_change_h"]) < 0.01
               and abs(x["volume_ratio_change"]) < 1e-4)
    report(good == n, f"extension (volume-forcing variants): {good}/{n} runs within tolerance")


def finish() -> int:
    print()
    if fails:
        print(f"FAILED ({len(fails)}):\n  " + "\n  ".join(fails))
        return 1
    print("PASS: all checked quantities reproduced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
