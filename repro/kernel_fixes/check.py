"""Check the kernel corrections. Exit status 0 = every check passed.

    uv run python check.py [--write-expected]

Reads results/sweep.json (sweep.py) and results/troute_compare.json (troute_compare.sh).

1. Uninitialized reads: with -finit-real=snan the unpatched kernel raises IEEE invalid
   (reads of undefined reals); the corrected kernel raises it in no case, at -O0 or at
   T-Route's -O2.
2. Determinism and defined outputs (corrected kernel): file order = reverse order =
   scribbled stack, through the C interface and directly from Fortran; the values in the
   output arguments on entry change nothing (qdc = 1, X = -999).
3. Each patch changes results only where its code path is taken (instrumented builds):
   0001 equals the unpatched kernel with its uninitialized reals set to 0 on every case
   without a retry; 0002, 0003, 0006, 0007 and 0008 change no case off their path;
   0004 changes nothing; 0005 changes no flow, velocity or depth, and ck/cn/X only on dry
   or no-flow cases. "Corrected" = patches 0001-0008 (the default build); L5 = without
   the Secant package 0006-0008.
   Instrumented builds equal the plain builds bitwise (sweep and network).
4. Network (T-Route, Potomac and LowerColorado, dt = 300 s, both settings): the determinism
   cross-process test gives identical outflows with the corrected kernel; headwaters,
   which receive no upstream inflow, give identical results with True and False.
5. Regression against expected/expected.json (first run, macOS arm64, 2026-10-09):
   kernel-sweep counts exact; network numbers rel 1e-3 (outlet values) or abs 0.5 points
   (percentages). --write-expected rewrites the baseline from the current results.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
EXP = HERE / "expected" / "expected.json"
results: list[tuple[bool, str]] = []


def ok(cond, msg):
    results.append((bool(cond), msg))


def get(d, path):
    for k in path.split("|" if "|" in path else "/"):
        d = d[k]
    return d


REG_SWEEP = [
    "uninitialized_reads/L0/cases_raising_invalid",
    "per_patch/0001/cases_flow_vel_depth_differ",
    "per_patch/0006/cases_flow_vel_depth_differ",
    "per_patch/0007/cases_flow_vel_depth_differ",
    "per_patch/0008/cases_flow_vel_depth_differ",
    "retry_loop_skipped/ngwpc123/of_which_qdc_zero_with_inflow",
    "events_cases/L0/negative_step",
    "L0_vs_corrected/qdc/rel_gt_1e-3",
    "L0_vs_L5/qdc/rel_gt_1e-3",
    "optional_x_L8_vs_L8x/bitwise_differ",
]


def reg_network(tc: dict) -> list[str]:
    paths = []
    for key in tc["pairs"]:
        for p in ("unpatched -> corrected", "L5 -> corrected", "L5 -> L7", "corrected -> corrected+x"):
            if p in tc["pairs"][key]:
                for f in ("outlet_peak_change_pct", "outlet_peak_time_shift_h", "outlet_volume_change_pct",
                          "network_volume_change_pct", "segments_diff_gt_1pct_of_peak",
                          "max_diff_pct_of_own_peak"):
                    paths.append(f"pairs|{key}|{p}|{f}")
    for case, d in tc["switch"].items():
        for v in ("unpatched", "corrected"):
            if v in d:
                paths += [f"switch|{case}|{v}|peak_rel_diff_pct", f"switch|{case}|{v}|peak_time_shift_h"]
    return paths


def main() -> int:
    sw = json.loads((RES / "sweep.json").read_text())
    tcp = RES / "troute_compare.json"
    tc = json.loads(tcp.read_text()) if tcp.exists() else None

    # 1
    un = sw["uninitialized_reads"]
    ok(un["L0"]["cases_raising_invalid"] > 0,
       f"unpatched kernel reads undefined reals in {un['L0']['cases_raising_invalid']} of {sw['n_cases']} cases (snan build)")
    for v in ("L5", "L8"):
        ok(un[v]["cases_raising_invalid"] == 0 and un[v]["prod_cases_raising_invalid"] == 0,
           f"{v}: no IEEE invalid in any case (snan -O0 build and -O2 build)")
    # 2
    d = sw["determinism"]["harness"]["L8"]
    ok(d["c_forward_vs_reverse"] == 0 and d["c_forward_vs_scribbled_stack"] == 0
       and d["f_forward_vs_reverse"] == 0, "corrected kernel: same outputs in any call order / stack state")
    ok(d["c_qdc_on_entry_1_flow_vel_depth_changes"] == 0 and all(v == 0 for v in d["c_preset_minus999_changes"].values()),
       "corrected kernel: values in the output arguments on entry change nothing")
    ok(all(v["trace_build_equals_prod"] for v in sw["determinism"]["harness"].values()),
       "instrumented builds equal the plain builds bitwise (all variants)")
    # 3
    pp = sw["per_patch"]
    ok(pp["0001_vs_zero_init"]["of_which_without_retry"] == 0,
       f"0001 = unpatched kernel with zero-initialized reals on every case without a retry "
       f"({pp['0001_vs_zero_init']['cases_flow_depth_differ']} retried cases differ)")
    for k in ("0002", "0003", "0006", "0007", "0008"):
        ok(pp[k]["flow_vel_depth_differ_off_path"] == 0,
           f"{k} changes no case off its path ({pp[k]['cases_flow_vel_depth_differ']} changed, "
           f"{pp[k]['cases_on_patch_path']} on the path)")
    ok(pp["0004"]["cases_any_output_differ"] == 0, "0004 changes no output through T-Route's C interface")
    ok(pp["0005"]["cases_flow_vel_depth_differ"] == 0 and pp["0005"]["ck_cn_X_differ_off_noflow_or_dry"] == 0,
       "0005 changes no flow, velocity or depth; ck/cn/X only on no-flow or dry cases")
    ok(sw["retry_loop_skipped"]["L5"]["cases"] == 0 and sw["retry_loop_skipped"]["L8"]["cases"] == 0,
       "corrected kernel (and L5): no retry skips its Secant loop")
    # 4
    if tc is None:
        ok(False, "results/troute_compare.json missing (run troute_compare.sh)")
    else:
        x = tc.get("xproc", {})
        if "corrected" in x:
            ok(x["corrected"]["frac_calls_differing"] == 0,
               f"determinism test: corrected kernel identical in two processes ({x['corrected']['n_calls']} calls); "
               f"unpatched differs in {x.get('unpatched', {}).get('frac_calls_differing')}")
        else:
            ok(False, "cross-process test results missing")
        for case, dd in tc["switch"].items():
            c = dd.get("corrected")
            if c:
                ok(c["headwaters_true_vs_false_bitwise_differ"] == 0,
                   f"{case}: corrected kernel, all {c['headwaters']} headwaters identical with True and False")
        for v, e in tc["events"].items():
            for key, ee in e.items():
                if "equals_plain_build_bitwise" in ee:
                    ok(ee["equals_plain_build_bitwise"], f"network: {v} equals its plain build bitwise ({key})")
    # 5
    if "--write-expected" in sys.argv:
        vals = [{"path": "sweep|" + p, "value": get(sw, p), "kind": "exact"} for p in REG_SWEEP]
        if tc:
            vals += [{"path": "troute|" + p, "value": get(tc, p),
                      "kind": "pct" if p.endswith("pct") and "peak_change" not in p else "rel"}
                     for p in reg_network(tc)]
        EXP.parent.mkdir(exist_ok=True)
        EXP.write_text(json.dumps({"source": "first run of this experiment, macOS arm64, gfortran 15.2.0, "
                                             "2026-10-09 (Claude, for James Halgren); regression baseline",
                                   "values": vals}, indent=1) + "\n")
        print(f"wrote {EXP.relative_to(HERE)} ({len(vals)} values)")
    if EXP.exists():
        for e in json.loads(EXP.read_text())["values"]:
            src, p = e["path"].split("|", 1)
            if src == "troute" and tc is None:
                continue
            try:
                got = get(sw if src == "sweep" else tc, p)
            except KeyError:
                ok(False, f"regression {e['path']}: missing")
                continue
            want = e["value"]
            if e["kind"] == "exact":
                good = got == want
            elif e["kind"] == "pct":
                good = abs(got - want) <= 0.5
            else:
                good = abs(got - want) <= 1e-3 * max(abs(want), 1.0)
            ok(good, f"regression {e['path']}: {got} vs {want}")
    else:
        ok(False, "expected/expected.json missing")

    bad = sum(1 for g, _ in results if not g)
    for g, m in results:
        print(("ok    " if g else "FAIL  ") + m)
    print(f"{len(results) - bad}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
