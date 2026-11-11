"""Kernel-level tests of the patch series: compile, sweep, compare (results/sweep.json).

    uv run python sweep.py

Builds (build/harness/<name>/, gfortran; the kernel, the bind(c) wrapper and
harness/driver.F90):
  prod_<v>    T-Route's makefile flags (-g -O2 -fPIC), for v in L0..L7, L5x, L7x, ngwpc123,
              ngwpcdev (L5 = the corrected kernel, L7 = with the opt-in Secant patches)
  trace_<v>   the same flags, kernel instrumented with event counters (kernels.instrument)
  snan_<v>    -O0 -fcheck=all -finit-real=snan -finit-integer=-99999 -finit-logical=true,
              for L0, L5 and L7: a read of an uninitialized real raises IEEE invalid
  zero_L0     -O0 -finit-real=zero (unpatched; uninitialized reals start at 0),
  o0_L1       -O0 (patch 0001), the pair for the "only retries differ" test of 0001
  libmc_<v>   shared library of the prod objects for L0, L5 and L7 (ctypes test)
Compiler warnings with -Wall -Wextra -Wuninitialized -Wmaybe-uninitialized -O2 are
recorded for L0, L5 and L7.

Tests:
  1 determinism: each prod build run in file order and in reverse order, through the
    bind(c) wrapper as T-Route calls it (mode c) and directly from Fortran (mode f);
    and through ctypes from two fresh Python processes, one in file order, one in reverse
    order with Python work between calls (the determinism test).
  2 uninitialized reads: invalid-flag counts of the snan builds.
  3 each patch changes results only where its code path is taken: L(k-1) vs L(k), with
    the path read from trace_L(k-1).
  4 the full change L0 -> L5 and L0 -> L7, and L7 (contains NGWPC #123's kernel changes) vs
    NGWPC's own kernel.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import kernels  # noqa: E402

BUILD = HERE / "build" / "harness"
RES = HERE / "results"
CASES = BUILD / "cases.bin"
FC = os.environ.get("FC", "gfortran")
KDIR = HERE / "data" / "t-route" / "src" / "kernel" / "muskingum"
PROD = ["-g", "-O2", "-fPIC"]
SNAN = ["-g", "-O0", "-fcheck=all", "-finit-real=snan", "-finit-integer=-99999", "-finit-logical=true"]
WARN = ["-O2", "-Wall", "-Wextra", "-Wuninitialized", "-Wmaybe-uninitialized"]
OUTS = ["qdc", "velc", "depthc", "ck", "cn", "X"]
EVENTS = ["lastpass_converged", "negative_step", "degenerate_slope", "retry", "abandoned",
          "loop_skipped_after_retry", "no_flow", "iterations", "collapse_restart"]
VARIANTS = [f"L{k}" for k in range(kernels.LEVELS + 1)] + ["L5x", "L8x", "ngwpc123", "ngwpcdev"]
KEY = ("L0", "L5", "L8")   # unpatched, without the Secant package, corrected (default)


def run(cmd: list[str], cwd: Path) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"ERROR in {cwd}: {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p.stdout + p.stderr


def build(name: str, src: str, flags: list[str], trace: bool = False, shared: bool = False) -> Path:
    d = BUILD / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copy2(KDIR / "varPrecision.f90", d)
    shutil.copy2(KDIR / "pyMCsingleSegStime_NoLoop.f90", d)
    (d / "mc.f90").write_text(kernels.instrument(src) if trace else src)
    run([FC, *flags, "-c", "varPrecision.f90"], d)
    run([FC, *flags, "-c", "mc.f90"], d)
    run([FC, *flags, "-c", "pyMCsingleSegStime_NoLoop.f90"], d)
    objs = ["varPrecision.o", "mc.o", "pyMCsingleSegStime_NoLoop.o"]
    if shared:
        ext = ".dylib" if platform.system() == "Darwin" else ".so"
        run([FC, "-shared", "-o", "libmc" + ext, *objs], d)
        return d / ("libmc" + ext)
    run([FC, *flags, *(["-DTRACE"] if trace else []), "-c", str(HERE / "harness" / "driver.F90"),
         "-o", "driver.o"], d)
    run([FC, *flags, "-o", "driver", *objs, "driver.o"], d)
    return d / "driver"


def drive(exe: Path, tag: str, order="f", preset=0.0, scribble=0, mode="c", trace=False):
    out = exe.parent / f"out_{tag}.bin"
    run([str(exe), str(CASES), str(out), order, repr(preset), str(scribble), mode], exe.parent)
    raw = out.read_bytes()
    n = NCASES
    o = np.frombuffer(raw[: n * 24], dtype=np.float32).reshape(n, 6)
    fl = np.frombuffer(raw[n * 24: n * 28], dtype=np.int32)
    ev = np.frombuffer(raw[n * 28:], dtype=np.int32).reshape(n, 9) if trace else None
    return o, fl, ev


def ndiff(a: np.ndarray, b: np.ndarray, cols=slice(None)) -> np.ndarray:
    """Per case: True where any selected output differs bitwise (NaN == NaN)."""
    x, y = a[:, cols], b[:, cols]
    return (~((x == y) | (np.isnan(x) & np.isnan(y)))).reshape(len(a), -1).any(axis=1)


def rel(a: np.ndarray, b: np.ndarray, col: int) -> np.ndarray:
    return np.abs(a[:, col].astype(np.float64) - b[:, col]) / np.maximum(np.abs(b[:, col]), 1e-3)


def ctypes_run(lib: Path, order: str, out: Path) -> None:
    code = r"""
import ctypes, sys, numpy as np, random
lib = ctypes.CDLL(sys.argv[1]); order = sys.argv[2]; out = sys.argv[3]; cases = sys.argv[4]
n = int(np.fromfile(cases, dtype=np.int32, count=1)[0])
inp = np.fromfile(cases, dtype=np.float32, offset=4).reshape(n, 15)
F = ctypes.c_float; P = ctypes.POINTER(F)
lib.c_muskingcungenwm.argtypes = [P] * 21
res = np.zeros((n, 6), dtype=np.float32)
idx = range(n) if order == "f" else range(n - 1, -1, -1)
rnd = random.Random(7)
for i in idx:
    a = [F(float(v)) for v in inp[i]]
    o = [F(0.0) for _ in range(6)]
    if order == "r":
        sum(rnd.random() for _ in range(rnd.randrange(1, 20)))   # other work between calls
    lib.c_muskingcungenwm(*[ctypes.byref(v) for v in a], *[ctypes.byref(v) for v in o])
    res[i] = [v.value for v in o]
res.tofile(out)
"""
    subprocess.run([sys.executable, "-c", code, str(lib), order, str(out), str(CASES)], check=True)


NCASES = 0


def manning_mismatch(inp: np.ndarray, out: np.ndarray) -> np.ndarray:
    """|Q_manning(published depth) - published qdc| / max(qdc, 1e-3), float64, with the
    kernel's composite conveyance (secant2_h L327-329, hydraulic_geometry). At a root of
    the depth equation the two agree (up to the step-size tolerance and the guard)."""
    x = inp.astype(np.float64)
    bw, tw, twcc, n, ncc, cs, s0 = (x[:, i] for i in (6, 7, 8, 9, 10, 11, 12))
    z = np.where(cs == 0, 1.0, 1.0 / np.where(cs == 0, 1.0, cs))
    bfd = np.where(bw > tw, bw / 1e-5, np.where(bw == tw, bw / (2 * z), (tw - bw) / (2 * z)))
    h = out[:, 2].astype(np.float64)
    hg, hl = np.maximum(h - bfd, 0.0), np.minimum(bfd, h)
    m = (hg > 0) & (twcc <= 0)
    hg, hl = np.where(m, 0.0, hg), np.where(m, h, hl)
    A, WP = (bw + hl * z) * hl, bw + 2 * hl * np.sqrt(1 + z * z)
    AC, WPC = twcc * hg, np.where(hg > 0, twcc + 2 * hg, 0.0)
    R = (A + AC) / (WP + WPC)
    q = (WP + WPC) / (WP * n + WPC * ncc) * (A + AC) * R ** (2 / 3) * np.sqrt(s0)
    return np.abs(q - out[:, 0]) / np.maximum(np.abs(out[:, 0].astype(np.float64)), 1e-3)


def main() -> int:
    global NCASES
    BUILD.mkdir(parents=True, exist_ok=True)
    RES.mkdir(exist_ok=True)
    run([sys.executable, str(HERE / "harness" / "cases.py"), str(CASES)], HERE)
    NCASES = int(np.fromfile(CASES, dtype=np.int32, count=1)[0])
    inp = np.fromfile(CASES, dtype=np.float32, offset=4).reshape(NCASES, 15)
    meta = json.loads(CASES.with_suffix(".json").read_text())
    src = {v: kernels.kernel_source(v) for v in VARIANTS}
    for v in KEY:
        (BUILD / f"kernel_{v}.f90").write_text(src[v])
    R: dict = {"n_cases": NCASES, "n_structured": meta["n_structured"], "n_random": meta["n_random"],
               "compiler": run([FC, "--version"], HERE).splitlines()[0], "platform": platform.platform(),
               "flags": {"prod": " ".join(PROD), "snan": " ".join(SNAN), "warn": " ".join(WARN)}}

    # compiler warnings
    R["warnings"] = {}
    for v in KEY:
        d = BUILD / f"warn_{v}"
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(KDIR / "varPrecision.f90", d)
        (d / "mc.f90").write_text(src[v])
        run([FC, *WARN, "-c", "varPrecision.f90"], d)
        txt = run([FC, *WARN, "-c", "mc.f90"], d)
        kinds: dict[str, int] = {}
        for ln in txt.splitlines():
            if ln.startswith("Warning:"):
                k = ln.split("[")[-1].rstrip("]") if "[" in ln else ln
                kinds[k] = kinds.get(k, 0) + 1
        R["warnings"][v] = kinds

    prod, trace = {}, {}
    for v in VARIANTS:
        exe = build(f"prod_{v}", src[v], PROD)
        prod[v] = {k: drive(exe, k, **kw) for k, kw in {
            "c_f": {}, "c_r": {"order": "r"}, "c_scr": {"scribble": 7},
            "c_preset": {"preset": -999.0}, "c_preset1": {"preset": 1.0}, "f_f": {"mode": "f"}, "f_r": {"mode": "f", "order": "r"}}.items()}
        exe = build(f"trace_{v}", src[v], PROD, trace=True)
        trace[v] = drive(exe, "c_f", trace=True)
        print(f"ok      {v}", flush=True)

    # 1 determinism
    det = {}
    for v in VARIANTS:
        p = prod[v]
        det[v] = {
            "c_forward_vs_reverse": int(ndiff(p["c_f"][0], p["c_r"][0]).sum()),
            "c_forward_vs_scribbled_stack": int(ndiff(p["c_f"][0], p["c_scr"][0]).sum()),
            "f_forward_vs_reverse": int(ndiff(p["f_f"][0], p["f_r"][0]).sum()),
            "f_forward_vs_reverse_flow_depth": int(ndiff(p["f_f"][0], p["f_r"][0], slice(0, 3)).sum()),
            "c_preset_minus999_changes": {OUTS[i]: int(ndiff(p["c_f"][0], p["c_preset"][0], slice(i, i + 1)).sum())
                                          for i in range(6)},
            "c_qdc_on_entry_1_flow_vel_depth_changes": int(ndiff(p["c_f"][0], p["c_preset1"][0], slice(0, 3)).sum()),
            "c_qdc_on_entry_1_dry_cases_with_nonzero_depth": int(((p["c_preset1"][0][:, 2] > 0) &
                                                                  (trace[v][2][:, 6] > 0)).sum()),
            "trace_build_equals_prod": bool(not ndiff(p["c_f"][0], trace[v][0]).any()),
        }
    # ctypes, two fresh processes
    ct = {}
    for v in KEY:
        lib = build(f"libmc_{v}", src[v], PROD, shared=True)
        a, b = BUILD / f"ctypes_{v}_f.bin", BUILD / f"ctypes_{v}_r.bin"
        ctypes_run(lib, "f", a)
        ctypes_run(lib, "r", b)
        x = np.fromfile(a, dtype=np.float32).reshape(NCASES, 6)
        y = np.fromfile(b, dtype=np.float32).reshape(NCASES, 6)
        ct[v] = {"cases_differing": int(ndiff(x, y).sum()),
                 "cases_qdc_differing": int(ndiff(x, y, slice(0, 1)).sum()),
                 "max_qdc_rel_diff": float(f"{rel(x, y, 0).max():.4g}"),
                 "equals_driver_c_forward": bool(not ndiff(x, prod[v]["c_f"][0]).any())}
    R["determinism"] = {"harness": det, "ctypes_two_processes": ct}
    print("ok      determinism", flush=True)

    # 2 uninitialized reads
    un = {}
    for v in KEY:
        exe = build(f"snan_{v}", src[v], SNAN)
        o, fl, _ = drive(exe, "c_f")
        un[v] = {"cases_raising_invalid": int((fl & 1).astype(bool).sum()),
                 "cases_with_nan_output": int(np.isnan(o).any(axis=1).sum())}
    for v in KEY:
        un[v]["prod_cases_raising_invalid"] = int((prod[v]["c_f"][1] & 1).astype(bool).sum())
    R["uninitialized_reads"] = un
    print("ok      snan", flush=True)

    # 3 per-patch effect, and where each patch's path is taken
    ev_counts = {v: {EVENTS[j]: int((trace[v][2][:, j] > 0).sum()) for j in (0, 1, 2, 3, 4, 5, 6, 8)}
                 for v in VARIANTS}
    for v in VARIANTS:
        ev_counts[v]["iterations_total"] = int(trace[v][2][:, 7].sum())
    R["events_cases"] = ev_counts
    per = {}
    o0 = build("o0_L1", src["L1"], ["-g", "-O0"])
    z0 = build("zero_L0", src["L0"], ["-g", "-O0", "-finit-real=zero"])
    a, b = drive(z0, "c_f")[0], drive(o0, "c_f")[0]
    retried = trace["L0"][2][:, 3] > 0
    d = ndiff(a, b, slice(0, 3))
    per["0001_vs_zero_init"] = {"compared": "zero_L0 (-O0 -finit-real=zero) vs o0_L1 (-O0)",
                   "cases_flow_depth_differ": int(d.sum()),
                   "of_which_without_retry": int((d & ~retried).sum())}
    # path of each patch, read from the instrumented build one level down
    trig = {2: lambda e: e[:, 0] > 0, 3: lambda e: e[:, 5] > 0, 4: lambda e: np.zeros(len(e), bool),
            5: lambda e: np.zeros(len(e), bool), 6: lambda e: (e[:, 1] > 0) | (e[:, 2] > 0),
            7: lambda e: e[:, 4] > 0}
    own_path = {8: lambda e: e[:, 8] > 0}   # 0008's path: its restart fired (else L8 == L7)
    for k in range(1, kernels.LEVELS + 1):
        x, y = prod[f"L{k - 1}"]["c_f"][0], prod[f"L{k}"]["c_f"][0]
        dfd = ndiff(x, y, slice(0, 3))
        dall = ndiff(x, y)
        entry = {"cases_flow_vel_depth_differ": int(dfd.sum()), "cases_any_output_differ": int(dall.sum()),
                 "qdc_rel_gt_1e-3": int((rel(y, x, 0) > 1e-3).sum()),
                 "depth_rel_gt_1e-3": int((rel(y, x, 2) > 1e-3).sum())}
        if k in trig or k in own_path:
            t = trig[k](trace[f"L{k - 1}"][2]) if k in trig else own_path[k](trace[f"L{k}"][2])
            entry["cases_on_patch_path"] = int(t.sum())
            entry["flow_vel_depth_differ_off_path"] = int((dfd & ~t).sum())
        if k == 5:
            noflow = trace["L4"][2][:, 6] > 0
            dry = y[:, 2] == 0
            entry["ck_cn_X_differ_off_noflow_or_dry"] = int((dall & ~(noflow | dry)).sum())
        if k == 1:
            entry["note"] = "unpatched reads an undefined Qj_0; see the zero_L0 comparison above"
        per[f"{k:04d}"] = entry
    R["per_patch"] = per

    # stall bug signature in NGWPC's kernels (loop body skipped after a retry)
    for v in ("ngwpc123", "ngwpcdev", "L5", "L7", "L8"):
        e, o = trace[v][2], prod[v]["c_f"][0]
        sk = e[:, 5] > 0
        inflow = (inp[:, 1] + inp[:, 2] + inp[:, 3] + np.maximum(inp[:, 4], 0)) > 0
        R.setdefault("retry_loop_skipped", {})[v] = {
            "cases": int(sk.sum()), "of_which_qdc_zero_with_inflow": int((sk & inflow & (o[:, 0] == 0)).sum())}

    # 4 size of the full change, and the NGWPC comparison
    for tgt in ("L5", "L7", "L8"):
        x, y = prod["L0"]["c_f"][0], prod[tgt]["c_f"][0]
        full = {}
        for i, nm in ((0, "qdc"), (2, "depthc")):
            r = rel(y, x, i)
            full[nm] = {"bitwise_differ": int(ndiff(x, y, slice(i, i + 1)).sum()),
                        "rel_gt_1e-6": int((r > 1e-6).sum()), "rel_gt_1e-3": int((r > 1e-3).sum()),
                        "rel_gt_1e-1": int((r > 1e-1).sum())}
        R[{"L5": "L0_vs_L5", "L7": "L0_vs_L7", "L8": "L0_vs_corrected"}[tgt]] = full
    for a, b in (("L7", "ngwpc123"), ("L8", "ngwpcdev")):
        x, y = prod[a]["c_f"][0], prod[b]["c_f"][0]
        R[f"{a}_vs_{b}"] = {"flow_vel_depth_bitwise_differ": int(ndiff(x, y, slice(0, 3)).sum()),
                            "qdc_rel_gt_1e-3": int((rel(x, y, 0) > 1e-3).sum()),
                            "note": "L7 = NGWPC #123's kernel changes (0001, 0002, 0006, 0007) + 0003-0005; L8 adds "
                                    "#127's 4ecefec1. NGWPC's kernels also have a performance refactor (7c9153ff) "
                                    "that reorders floating-point work, and the NaN guard f318d0c5"}
    for b in ("L5", "L8"):
        x, y = prod[b]["c_f"][0], prod[b + "x"]["c_f"][0]
        R[f"optional_x_{b}_vs_{b}x"] = {"bitwise_differ": int(ndiff(x, y).sum()),
                                        "qdc_rel_gt_1e-3": int((rel(y, x, 0) > 1e-3).sum()),
                                        "X_changed": int(ndiff(x, y, slice(5, 6)).sum())}
    x, y = prod["L1"]["c_f"][0], prod["L0"]["c_f"][0]
    R["L0_vs_L1_prod"] = {"bitwise_differ": int(ndiff(x, y).sum()),
                          "qdc_rel_gt_1e-3": int((rel(x, y, 0) > 1e-3).sum())}
    # how well the published (depth, flow) pair satisfies the depth equation
    flowing = trace["L0"][2][:, 6] == 0
    negpath = (trace["L5"][2][:, 1] > 0) | (trace["L5"][2][:, 2] > 0)
    R["manning_consistency"] = {
        "definition": "|Manning Q(published depth) - published qdc| / max(qdc, 1e-3); flowing cases",
        **{v: {"median": float(f"{np.median(mm[flowing]):.3g}"),
               "p90": float(f"{np.percentile(mm[flowing], 90):.3g}"),
               "frac_lt_1pct_all": float(f"{np.mean(mm[flowing] < 0.01):.3g}"),
               "frac_lt_1pct_on_0006_path": float(f"{np.mean(mm[negpath] < 0.01):.3g}")}
           for v in ("L0", "L5", "L6", "L7", "L8", "ngwpcdev")
           for mm in [manning_mismatch(inp, prod[v]["c_f"][0])]}}
    (RES / "sweep.json").write_text(json.dumps(R, indent=1) + "\n")
    print(json.dumps({k: R[k] for k in ("determinism", "uninitialized_reads", "per_patch")}, indent=1))
    print("ok      results/sweep.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
