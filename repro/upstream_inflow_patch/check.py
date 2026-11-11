"""Check this reproduction. Exit status 0 = every check passed.

Reads results/results_corrected.json and, if present, results/results_unpatched.json
(test_clip.py). Since 2026-10-09 the default build uses the corrected MC kernel
(../kernel_fixes); before, "qj" (the Qj-only fix) played its role here and "default" was
the unpatched kernel.

1. Exact replay (corrected build: the patch plus the corrected kernel): for both cases and both
   assume_short_ts settings, the clipped run fed the full run's boundary outflow at every
   routing step reproduces the full run bitwise on every clipped-domain segment at every
   step; the same with the by-network compute method, and with upstream_inflow_segments
   selecting one of the file's two boundaries (lc_nwm).
2. Structure (both builds): the clipped runs route exactly the clipped domain; the full
   runs route the whole network; segments that are not downstream of a boundary are
   unchanged in the corrected build.
3. No change without boundaries: the patched build's full runs equal the end-of-hour flows
   of ../short_ts_switch's build (no inflow patch, same kernel) bitwise. Skipped, with a
   note, if that experiment's results are not present or its kernel differs.
4. Unpatched-kernel build (opt-in, COMPARE_UNPATCHED=1 run.sh): the clipped run with
   step-resolution input reproduces the full-run outlet peak within 1e-4 (relative).
   Differences elsewhere come from the kernel's uninitialized secant variable (README);
   they are reported, not checked.
5. Regression against expected/expected.json (corrected kernel since 2026-10-09): boundary choice, clipped-domain size, and
   the errors caused by giving the boundary hydrograph only hourly (corrected build).

    uv run python check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
results: list[tuple[bool, str]] = []


def ok(cond: bool, msg: str) -> None:
    results.append((bool(cond), msg))


def get(d: dict, path: str):
    for k in path.split("/"):
        d = d[k]
    return d


def main() -> int:
    R = {}
    for v in ("corrected", "unpatched"):
        f = RES / f"results_{v}.json"
        if not f.exists():
            if v == "unpatched":
                print("note  results_unpatched.json absent (opt-in: COMPARE_UNPATCHED=1 run.sh); check 4 skipped")
                continue
            print(f"FAIL  {f.relative_to(HERE)} missing (run test_clip.py --variant {v})")
            return 1
        R[v] = json.loads(f.read_text())

    for c, cr in R["corrected"]["cases"].items():
        for tag, rr in cr["runs"].items():
            for kind in ("native", "native_bynetwork", "native_subset"):
                if kind in rr:
                    x = rr[kind]
                    ok(x["bitwise_identical"],
                       f"corrected {c} {tag} {kind}: clipped == full bitwise on {x['segments_compared']} "
                       f"segments x {x['steps_compared']} steps (max|err| {x['max_abs_err_m3s']:.3g})")
            for kind in ("native", "hourly"):
                ok(rr[kind]["max_abs_err_not_downstream_m3s"] == 0.0,
                   f"corrected {c} {tag} {kind}: segments not downstream of a boundary unchanged")

    for v, r in R.items():
        for c, cr in r["cases"].items():
            for tag, rr in cr["runs"].items():
                ok(rr["full_run"]["n_routed_segments"] == cr["n_segments"],
                   f"{v} {c} {tag}: full run routes all {cr['n_segments']} segments")
                for kind in [k for k in ("native", "hourly", "native_bynetwork", "native_subset")
                             if k in rr]:
                    want = rr[kind].get("n_clipped_domain", cr["n_clipped_domain"])
                    ok(rr[kind]["n_routed_segments"] == want,
                       f"{v} {c} {tag} {kind}: clipped run routes {rr[kind]['n_routed_segments']} "
                       f"= clipped domain {want}")

    n_reg = 0
    for v, r in R.items():
        for c, cr in r["cases"].items():
            for tag, rr in cr["runs"].items():
                reg = rr.get("no_boundary_regression_vs_unpatched")
                if reg is not None:
                    n_reg += 1
                    ok(reg["bitwise_identical"],
                       f"{v} {c} {tag}: patched build without boundaries == build without the patch "
                       f"(../short_ts_switch, kernel {reg.get('reference_kernel')}; end-of-hour flows, "
                       f"max|diff| {reg['max_abs_diff_m3s']:.3g})")
    if n_reg == 0:
        print("note  no reference without the patch (run ../short_ts_switch/run.sh to enable check 3)")
    for c, cr in R.get("unpatched", {"cases": {}})["cases"].items():
        for tag, rr in cr["runs"].items():
            o = rr["native"]["outlet"]
            ok(abs(o["peak_rel_err"]) < 1e-4,
               f"unpatched {c} {tag} native: outlet peak rel err {o['peak_rel_err']:.2e} < 1e-4")

    exp = json.loads((HERE / "expected" / "expected.json").read_text())
    for e in exp["values"]:
        got = get(R["corrected"]["cases"], e["path"])
        want = e["value"]
        if e["kind"] == "exact":
            good = got == want
        elif e["kind"] == "rel5pct":
            good = abs(got - want) <= 0.05 * abs(want)
        elif e["kind"] == "abs2e-5":
            good = abs(got - want) <= 2e-5
        else:
            good = False
        ok(good, f"expected {e['path']}: {got} vs {want} ({e['kind']})")

    n_fail = sum(1 for g, _ in results if not g)
    for g, m in results:
        print(("ok    " if g else "FAIL  ") + m)
    print(f"{len(results) - n_fail}/{len(results)} checks passed")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
