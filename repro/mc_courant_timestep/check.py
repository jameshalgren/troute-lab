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


def finish() -> int:
    print()
    if fails:
        print(f"FAILED ({len(fails)}):\n  " + "\n  ".join(fails))
        return 1
    print("PASS: all checked quantities reproduced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
