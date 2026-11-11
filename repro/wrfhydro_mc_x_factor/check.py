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
print(f"{n - len(fails)}/{n} checks passed")
for f in fails:
    print("FAIL:", f)
sys.exit(1 if fails else 0)
