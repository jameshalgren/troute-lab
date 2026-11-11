"""Check results/ against expected/expected.json and run self-consistency tests.
Exit 1 on any failure.

1. Self-consistency (always):
   - error-score classes 0-2 partition the MC segments; error-flagged km >= LS and BW km;
     effect-flagged km >= XF and KC km (the two budgets are separate);
     BW = BW_i | BW_ii | BW_iii (km between max and sum of the parts)
   - configuration nesting: A within B, F within B, C2 within C1, D1 within D2 (km and budget)
   - all percentages in [0, 100]; the Pareto curve is monotone and ends at 100%
   - literature formulas reproduce published values: Tang et al. (1999) Eq. 25 gives 0.45 /
     4.1 / 7.5 % at S = 1e-3 / 2.5e-4 / 1e-4; Eq. 29 at
     S = 1e-4 is within 0.5 points of Table 5 (9.23 %); Samuels's L at S0 = 1e-5, D = 5 m is
     350 km; the Potomac outlet's bankfull depth is 2.85 m (kernel formula)
   - Potomac check (if run): the rebuilt False event loss equals short_ts_switch's
     mechanism.json value (8.1192 % at dt = 300 s) to 0.01 points
2. Regression against expected/expected.json (values of the 2026-10-20 rerun; see README
   "Updating expected/"):
   integers exact and floats relative 1e-6, except keys listed under "_loose" (eHydro-derived,
   live service: absolute 2 percentage points).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import indicators as I

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
fails: list[str] = []
n = [0]


def ok(name: str, cond: bool, detail: str = "") -> None:
    n[0] += 1
    print(f"{'ok  ' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        fails.append(name)


def get(d, path):
    for k in path.split("/"):
        d = d[k] if isinstance(d, dict) else d[int(k)]
    return d


def main() -> int:
    res = json.loads((RES / "results.json").read_text())
    exp = json.loads((HERE / "expected" / "expected.json").read_text())
    pot = json.loads((RES / "potomac_check.json").read_text()) if (RES / "potomac_check.json").exists() else None

    # ---- 1. self-consistency
    for dom, s in res["domains"].items():
        ok(f"{dom}: error-score classes partition MC segments",
           sum(s["error_score"][k]["segments"] for k in "012") == s["mc_segments"])
        f = s["error_flagged"]["km"]
        ok(f"{dom}: error-flagged km >= LS and BW", all(f >= s[k]["km"] - 0.1 for k in ("LS_S0_lt_2.5e-4", "BW_any")))
        f = s["effect_flagged"]["km"]
        ok(f"{dom}: effect-flagged km >= XF and KC",
           all(f >= s[k]["km"] - 0.1 for k in ("XF_x_floor_binds_bankfull", "KC_k_clamp_dt300_bankfull")))
        ok(f"{dom}: effect-only + overlap = effect-flagged",
           abs(s["effect_only"]["km"] + s["error_and_effect"]["km"] - s["effect_flagged"]["km"]) < 0.2)
        parts = [s[k]["km"] for k in ("BW_i_confluence", "BW_ii_outlet", "BW_iii_lake_inlet")]
        ok(f"{dom}: BW between max and sum of parts", max(parts) - 0.1 <= s["BW_any"]["km"] <= sum(parts) + 0.1)
    c = res["configurations"]
    for small, big in (("A_mainstem", "B_mainstem_fringes"), ("F_candidate", "B_mainstem_fringes"),
                       ("C2_low_slope_1e-4", "C1_low_slope_2.5e-4"), ("D1_flat_miss_alluvial_plain", "D2_coastal_plain")):
        ok(f"nesting {small} within {big}", c[small]["km"] <= c[big]["km"] + 1e-6
           and c[small]["pct_known_error_budget"] <= c[big]["pct_known_error_budget"] + 1e-6
           and c[small]["pct_parameter_effect_budget"] <= c[big]["pct_parameter_effect_budget"] + 1e-6)
    seg = pd.read_parquet(RES / "segments_conus.parquet",
                          columns=["cfg_A_mainstem", "cfg_B_mainstem_fringes", "cfg_F_candidate", "cfg_C1_low_slope_2.5e-4",
                                   "cfg_C2_low_slope_1e-4", "cfg_D1_flat_miss_alluvial_plain", "cfg_D2_coastal_plain",
                                   "lake"])
    for small, big in (("A_mainstem", "B_mainstem_fringes"), ("F_candidate", "B_mainstem_fringes"),
                       ("C2_low_slope_1e-4", "C1_low_slope_2.5e-4"), ("D1_flat_miss_alluvial_plain", "D2_coastal_plain")):
        ok(f"segment-level subset {small} of {big}", not (seg[f"cfg_{small}"] & ~seg[f"cfg_{big}"]).any())
    ok("no configuration contains a lake segment", not seg.filter(like="cfg_").to_numpy()[seg["lake"].to_numpy()].any())
    pcts = [v for cc in c.values() for k, v in cc.items() if k.startswith("pct_") and isinstance(v, (int, float))]
    ok("configuration percentages in [0, 100]", all(-1e-9 <= v <= 100 + 1e-9 for v in pcts))
    par = pd.read_parquet(RES / "pareto.parquet")
    ok("Pareto curve monotone and complete",
       bool((np.diff(par["pct_budget"]) >= -1e-9).all() and (np.diff(par["pct_km"]) >= 0).all()
            and (np.diff(par["pct_effect_budget"]) >= -1e-9).all()
            and abs(par["pct_budget"].iloc[-1] - 100) < 1e-6 and abs(par["pct_km"].iloc[-1] - 100) < 1e-6
            and abs(par["pct_effect_budget"].iloc[-1] - 100) < 1e-6))
    t25 = I.tang_inbank_loss_pct(np.array([1e-3, 2.5e-4, 1e-4]))
    ok("Tang Eq. 25 reproduces 0.45 / 4.1 / 7.5 %", bool(np.allclose(t25, [0.45, 4.1, 7.5], atol=0.06)), str(t25.round(3)))
    t29 = float(I.tang_compound_loss_pct(np.array(1e-4)))
    ok("Tang Eq. 29 at 1e-4 within 0.5 of Table 5 (9.23 %)", abs(t29 - 9.23) < 0.5, f"{t29:.3f}")
    hb = {"Fr_bf": np.array([0.0]), "D": np.array([5.0])}
    L = float(I.backwater_length_km(hb, np.array([1e-5]))[0])
    ok("Samuels L(D = 5 m, S0 = 1e-5) = 350 km", abs(L - 350) < 1e-6, f"{L:.1f}")
    rl = I.load_routelink(HERE / "data" / "RouteLink_CONUS.nc")
    i = int(np.flatnonzero(rl["link"] == 4539621)[0])
    D = float(I.bankfull({k: v[i:i + 1] for k, v in rl.items()})["D"][0])
    ok("Potomac outlet bankfull depth 2.85 m (kernel formula)", abs(D - 2.8488) < 1e-3, f"{D:.4f}")
    if pot and not pot.get("skipped"):
        mj = HERE.parent / "short_ts_switch" / "results" / "mechanism.json"
        if mj.exists():
            want = json.loads(mj.read_text())["D_mass_balance"]["network"]["300"]["false"]["sum_segment_losses_pct_of_storm"]
            ok("Potomac False loss rebuilt = short_ts_switch mechanism.json", abs(pot["false_total_loss_pct_of_storm"] - want) < 0.01,
               f"{pot['false_total_loss_pct_of_storm']} vs {want}")

    # ---- 2. regression
    loose = set(exp.get("_loose", []))
    for key, want in exp["values"].items():
        src, path = key.split(":", 1)
        doc = res if src == "results" else pot
        if doc is None or (isinstance(doc, dict) and doc.get("skipped")):
            print(f"skip {key} (potomac_check not run)")
            continue
        try:
            have = get(doc, path)
        except (KeyError, IndexError, TypeError):
            ok(key, False, "missing")
            continue
        if key in loose:
            ok(key, isinstance(have, (int, float)) and abs(have - want) <= 2.0, f"got {have}, expected {want} (+/- 2)")
        elif isinstance(want, float):
            ok(key, isinstance(have, (int, float)) and math.isclose(have, want, rel_tol=1e-6, abs_tol=1e-9),
               f"got {have}, expected {want}")
        else:
            ok(key, have == want, f"got {have}, expected {want}")
    print(f"\n{n[0] - len(fails)}/{n[0]} checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
