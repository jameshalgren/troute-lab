"""Compile the original (unmodified) Fortran Muskingum-Cunge kernels into build/.

1. Primary (courant_test.ipynb): f2py, exactly as notebook cell 3 does
       f2py -c varPrecision.f90 MCsingleSegStime_f2py_NOLOOP-anw.f90 -m mc_sseg_stime_anw
   using numpy's f2py (meson + ninja backend on Python >= 3.12; buildtype=release).
2. Exploratory (mc_numerical_dispersion.ipynb): gfortran objects with the notebook's
   flags (-O3 -fPIC), linked into a shared library and called through the original
   bind(c) wrapper pyMCsingleSegStime_NoLoop.f90 via ctypes (the notebook called the
   same wrapper from Cython). Also built with -finit-real=zero and -finit-real=nan,
   because the source reads an uninitialized local variable (see README).

Sources are copied from data/ (hash-verified by fetch_data.py) and re-verified here.
Writes build/build_info.json (compiler versions, commands, flags).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
sys.path.insert(0, str(HERE))
from fetch_data import DATA, FILES, sha256  # noqa: E402

FC = os.environ.get("FC", "gfortran")


def run(cmd, cwd):
    print("  $", " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-4000:], r.stderr[-4000:], sep="\n")
        sys.exit(f"ERROR: build step failed: {' '.join(cmd)}")
    return r


def staged(sub: str, names: list[str]) -> Path:
    d = BUILD / sub
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    for n in names:
        rel = f"{sub}/{n}"
        src = DATA / rel
        want = FILES[rel][2]
        if not src.exists() or sha256(src) != want:
            sys.exit(f"ERROR: {src} missing or modified; run fetch_data.py")
        shutil.copy2(src, d / n)
    return d


def main() -> int:
    if shutil.which(FC) is None:
        sys.exit(f"ERROR: Fortran compiler '{FC}' not found (set FC=...)")
    info = {"FC": FC, "fc_version": subprocess.run([FC, "--version"], capture_output=True,
                                                    text=True).stdout.splitlines()[0]}

    # --- 1. f2py build of the courant kernel ---
    d = staged("courant", ["varPrecision.f90", "MCsingleSegStime_f2py_NOLOOP-anw.f90"])
    cmd = [sys.executable, "-m", "numpy.f2py", "-c", "varPrecision.f90",
           "MCsingleSegStime_f2py_NOLOOP-anw.f90", "-m", "mc_sseg_stime_anw",
           "--build-dir", "f2py_build"]
    env_fc = {**os.environ, "FC": FC}
    print("  $", " ".join(cmd))
    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True, env=env_fc)
    if r.returncode:
        print(r.stdout[-4000:], r.stderr[-4000:], sep="\n")
        sys.exit("ERROR: f2py build failed")
    so = sorted(d.glob("mc_sseg_stime_anw*.so")) + sorted(d.glob("mc_sseg_stime_anw*.pyd"))
    if not so:
        sys.exit("ERROR: f2py produced no extension module")
    cc_json = d / "f2py_build" / "bbdir" / "compile_commands.json"
    info["courant"] = {
        "f2py_command": " ".join(cmd[1:]),
        "extension": so[0].name,
        "compile_commands": json.loads(cc_json.read_text()) if cc_json.exists() else None,
    }

    # --- 2. gfortran + ctypes build of the segment-merge kernel ---
    # Three builds of the same unmodified source. "notebook_flags" = the notebook's
    # commands. The source reads an uninitialized local (AREAC) when depth <= bankfull,
    # so two diagnostic builds pin that memory: -finit-real=zero and -finit-real=nan.
    info["dispersion"] = {}
    for variant, extra in [("notebook_flags", []), ("init_zero", ["-finit-real=zero"]),
                           ("init_nan", ["-finit-real=nan"])]:
        sub = f"dispersion_{variant}"
        d = BUILD / sub
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        for n in ["varPrecision.f90", "MCsingleSegStime_f2py_NOLOOP.f90", "pyMCsingleSegStime_NoLoop.f90"]:
            src = DATA / "dispersion" / n
            if sha256(src) != FILES[f"dispersion/{n}"][2]:
                sys.exit(f"ERROR: {src} modified; run fetch_data.py")
            shutil.copy2(src, d / n)
        flags = ["-O3", "-fPIC", *extra]
        steps = [
            [FC, "varPrecision.f90", "-c", "-o", "var_precision.o", *flags],
            [FC, "MCsingleSegStime_f2py_NOLOOP.f90", "-c", "-o", "mc_single_seg.o", *flags],
            [FC, "pyMCsingleSegStime_NoLoop.f90", "-c", "-o", "pymc_single_seg.o", *flags],
            [FC, "-shared", "var_precision.o", "mc_single_seg.o", "pymc_single_seg.o",
             "-o", "libmc_segment_merge.so"],
        ]
        for s_ in steps:
            run(s_, d)
        info["dispersion"][variant] = {"commands": [" ".join(x) for x in steps],
                                       "library": f"{sub}/libmc_segment_merge.so"}

    (BUILD / "build_info.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"built kernels with {info['fc_version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
