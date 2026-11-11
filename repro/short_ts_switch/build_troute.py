"""Build T-Route (pinned commit) into this experiment's locked uv environment.

Mirrors t-route's own build at that commit (compiler.sh + Dockerfile):
  1. Fortran kernels with t-route's makefiles: src/kernel/muskingum (`make`, `make
     install`), src/kernel/diffusive (four objects, `make install`), src/kernel/reservoir
     (`make install_lp`, `make install_rfc`; compiler.sh's bare `make` fails on a
     missing `bind_hybrid.a` target and compiler.sh ignores that, so it is skipped here).
  2. Cython/Python packages troute.network, troute.routing (--use-cython),
     troute.config and nwm_routing, installed with `uv pip install --no-deps
     --no-build-isolation` so they compile against the locked numpy/Cython (as the
     Dockerfile does for troute.routing).
  3. For diagnostics only: the same compiled MC objects linked into a shared library
     (build/libmc_kernel.*) so analyze.py can call T-Route's Fortran kernel through its
     bind(c) wrapper `c_muskingcungenwm` (Courant number, celerity, X, coefficients).

The source in data/t-route stays pristine; the build works on `git archive` of it in
build/t-route. Idempotent: skipped if build/build_info.json matches the commit, the
kernel variant and the packages import, unless --force.

Kernel (updated 2026-10-09; project rule: tests use a kernel without known coding
errors). --kernel, or the environment variable KERNEL, selects the MC kernel:
  corrected  (default) d29f663 plus patches 0001-0008 of ../kernel_fixes/patches/
             (uninitialized reads, intent errors, undefined outputs, Secant control
             flow, and Taher Chegini's Secant package from NGWPC #123/#127; see
             ../kernel_fixes/README.md)
  unpatched  d29f663 as published (reads uninitialized variables; the build behind the
             results published before 2026-10-09)
  L<k>       the first k patches of the series (L0 = unpatched, L5 = without the
             Secant package, L7 = 0006-0007 without 0008 (diagnostic only: loses volume),
             L8 = corrected)
  corrected+x, L<k>x
             plus the OPTIONAL Cunge-X patch (../kernel_fixes/patches/optional/; under
             review in NCAR/wrf_hydro_nwm_public#923, never the default)
  trace-L<k> L<k> with event counters (../kernel_fixes/kernels.py instrument()); used
             only by ../kernel_fixes/troute_compare.sh
--patch-qj (legacy; only qj_patch_check.sh, in a separate copy of this directory, with
--kernel unpatched): the 2026-10-08 diagnostic patch, `Qj_0 = 0` before the secant loop and
`Qj` intent(inout) in `secant2_h`. Superseded by patch 0001 of the series, which also
makes C1..C4 intent(inout).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fetch_data import TROUTE_DIR, TROUTE_SHA  # noqa: E402

BUILD = HERE / "build"
SRC = BUILD / "t-route"
INFO = BUILD / "build_info.json"
LIBEXT = ".dylib" if platform.system() == "Darwin" else ".so"
LIBMC = BUILD / f"libmc_kernel{LIBEXT}"
PY = sys.executable

log: list[dict] = []


def run(cmd: list[str] | str, cwd: Path, env: dict, check: bool = True) -> str:
    shell = isinstance(cmd, str)
    print(f"[{cwd.relative_to(HERE) if cwd.is_relative_to(HERE) else cwd}] "
          f"{cmd if shell else ' '.join(cmd)}", flush=True)
    p = subprocess.run(cmd, cwd=cwd, env=env, shell=shell, capture_output=True, text=True)
    log.append({"cwd": str(cwd.relative_to(HERE)), "cmd": cmd, "returncode": p.returncode})
    if check and p.returncode != 0:
        sys.stderr.write(p.stdout[-4000:] + "\n" + p.stderr[-4000:])
        sys.exit(f"ERROR: build step failed: {cmd}")
    return p.stdout


def tool(cmd: list[str]) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    p = subprocess.run(cmd, capture_output=True, text=True)
    return (p.stdout or p.stderr).strip()


def kernel_fixes_dir() -> Path:
    """../kernel_fixes, or $KERNEL_FIXES (set by working copies outside this directory)."""
    d = Path(os.environ.get("KERNEL_FIXES", HERE.parent / "kernel_fixes")).resolve()
    if not (d / "kernels.py").exists():
        sys.exit(f"ERROR: kernel patch series not found at {d} (set KERNEL_FIXES)")
    return d


def kernel_level(kernel: str) -> tuple[int | None, bool, str]:
    """(number of patches to apply, instrumented?, optional patch letters) for --kernel."""
    trace = kernel.startswith("trace-")
    k = kernel.removeprefix("trace-")
    opt = ""
    if k.endswith("+x"):          # optional Cunge-X patch (under review in NCAR/wrf_hydro_nwm_public#923)
        k, opt = k[:-2], "x"
    elif k.startswith("L") and k.endswith("x"):
        k, opt = k[:-1], "x"
    if k == "corrected":
        return None, trace, opt
    if k == "unpatched":
        return 0, trace, opt
    if k.startswith("L") and k[1:].isdigit():
        return int(k[1:]), trace, opt
    sys.exit(f"ERROR: unknown kernel '{kernel}' (corrected, corrected+x, unpatched, L<k>, L<k>x, "
             "trace-L<k>)")


def kernel_label(kernel: str, patch_qj: bool) -> str:
    return "unpatched+qj-legacy" if patch_qj else kernel


def expected_patches(kernel: str, patch_qj: bool) -> list:
    """The patch records build_info.json must hold for this --kernel (names + SHA-256)."""
    level, trace, opt = kernel_level(kernel)
    if patch_qj or (level == 0 and not opt):
        return []
    sys.path.insert(0, str(kernel_fixes_dir()))
    import kernels as KF
    names = [p.name for p in KF.series()[: (KF.DEFAULT_LEVEL if level is None else level)]]
    names += [KF.OPTIONAL[c].name for c in opt]
    return [{"patch": n, "sha256": hashlib.sha256(next(KF.PATCH_DIR.rglob(n)).read_bytes()).hexdigest()}
            for n in names]


def already_built(label: str, kernel: str, patch_qj: bool) -> bool:
    if not INFO.exists() or not LIBMC.exists():
        return False
    try:
        info = json.loads(INFO.read_text())
    except json.JSONDecodeError:
        return False
    if info.get("troute_commit") != TROUTE_SHA or info.get("kernel", "unpatched") != label:
        return False
    got = [p for p in info.get("patches", []) if isinstance(p, dict)]
    if got != expected_patches(kernel, patch_qj):   # the patch files changed since the build
        return False
    p = subprocess.run([PY, "-c", "import troute.routing.fast_reach.mc_reach, nwm_routing.__main__"],
                       capture_output=True)
    return p.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--kernel", default=os.environ.get("KERNEL", "corrected"),
                    help="corrected (default), unpatched, L<k>, trace-L<k>; or env KERNEL")
    ap.add_argument("--patch-qj", action="store_true",
                    help="legacy 2026-10-08 diagnostic patch (requires --kernel unpatched)")
    args = ap.parse_args()
    if args.patch_qj and args.kernel != "unpatched":
        sys.exit("ERROR: --patch-qj applies to the unpatched kernel only (--kernel unpatched)")
    label = kernel_label(args.kernel, args.patch_qj)
    if not args.force and already_built(label, args.kernel, args.patch_qj):
        print(f"ok      t-route {TROUTE_SHA[:10]} (kernel: {label}) already built into this environment")
        return 0

    fc = os.environ.get("F90", os.environ.get("FC", "gfortran"))
    for t in (fc, "make", "nf-config", "nc-config", "git"):
        if shutil.which(t) is None:
            sys.exit(f"ERROR: '{t}' not found. Needs a Fortran compiler, make, git and "
                     "netCDF-C/netCDF-Fortran (nc-config, nf-config).")

    if SRC.exists():
        shutil.rmtree(SRC)
    SRC.mkdir(parents=True)
    run(f"git -C '{TROUTE_DIR}' archive HEAD | tar -x -C '{SRC}'", HERE, os.environ.copy())

    libgf = Path(subprocess.run([fc, "-print-file-name=libgfortran" + LIBEXT],
                                capture_output=True, text=True).stdout.strip()).resolve().parent
    nf_lib = Path(tool(["nf-config", "--prefix"])) / "lib"
    nc_lib = Path(tool(["nc-config", "--prefix"])) / "lib"
    env = os.environ.copy()
    env.update({
        "F90": fc, "FC": fc, "CC": env.get("CC", "gcc"),
        "NETCDFINC": tool(["nf-config", "--includedir"]),
        "LIBRARY_PATH": os.pathsep.join(filter(None, [str(libgf), str(nf_lib), str(nc_lib),
                                                       env.get("LIBRARY_PATH", "")])),
    })

    k = SRC / "src" / "kernel"
    patches = []
    level, trace, opt = kernel_level(args.kernel)
    if level != 0 or opt:
        kf = kernel_fixes_dir()
        sys.path.insert(0, str(kf))
        import kernels as KF  # ../kernel_fixes/kernels.py
        names = KF.apply_series(SRC, level, optional=opt)
        patches += [{"patch": n, "sha256": hashlib.sha256(next(KF.PATCH_DIR.rglob(n)).read_bytes()).hexdigest()}
                    for n in names]
        print(f"ok      applied {len(names)} kernel patches from {kf.name}/patches", flush=True)
    if trace:
        kf = kernel_fixes_dir()
        sys.path.insert(0, str(kf))
        import kernels as KF
        f = k / "muskingum" / "MCsingleSegStime_f2py_NOLOOP.f90"
        f.write_text(KF.instrument(f.read_text()))
        patches.append("trace: event counters (kernel_fixes/kernels.py instrument())")
    if args.patch_qj:
        f = k / "muskingum" / "MCsingleSegStime_f2py_NOLOOP.f90"
        t = f.read_text()
        a, b = "    tries = 0\n", "    real(prec), intent(out) :: Qj, C1, C2, C3, C4, X\n"
        if t.count(a) != 1 or t.count(b) != 1:
            sys.exit("ERROR: --patch-qj: kernel source does not match the expected lines")
        t = t.replace(a, a + "    Qj_0 = 0.0_prec  ! PATCH (--patch-qj): set before the first secant2_h call\n")
        t = t.replace(b, "    real(prec), intent(inout) :: Qj  ! PATCH (--patch-qj): read on interval 1\n"
                         "    real(prec), intent(out) :: C1, C2, C3, C4, X\n")
        f.write_text(t)
        patches.append("qj: Qj_0 = 0 before the secant loop; secant2_h Qj intent(inout)")
    run(["make", "clean"], k / "muskingum", env)
    run(["make"], k / "muskingum", env)
    run(["make", "install"], k / "muskingum", env)
    run(["make", "clean"], k / "diffusive", env)
    run(["make", "diffusive.o", "pydiffusive.o", "chxsec_lookuptable.o", "pychxsec_lookuptable.o"],
        k / "diffusive", env)
    run(["make", "install"], k / "diffusive", env)
    run(["make", "clean"], k / "reservoir", env)
    run(["make", "install_lp"], k / "reservoir", env)
    run(["make", "install_rfc"], k / "reservoir", env)

    pip = ["uv", "pip", "install", "--python", PY, "--no-deps", "--no-build-isolation", "--reinstall"]
    cy = ["--config-setting=--build-option=--use-cython"]
    for pkg, extra in (("troute-network", cy), ("troute-routing", cy),
                       ("troute-config", []), ("troute-nwm", [])):
        run(pip + extra + [str(SRC / "src" / pkg)], SRC, env)

    # Diagnostics library: the same objects t-route's makefile compiled for mc_reach.
    mk = k / "muskingum"
    run([fc, "-shared", "-o", str(LIBMC), str(mk / "mc_single_seg.o"), str(mk / "pymc_single_seg.o")],
        mk, env)

    run([PY, "-c", "import troute.routing.fast_reach.mc_reach, nwm_routing.__main__; print('import ok')"],
        HERE, env)

    info = {
        "troute_repo": "https://github.com/CIROH-UA/t-route",
        "troute_commit": TROUTE_SHA,
        "platform": platform.platform(),
        "compilers": {fc: tool([fc, "--version"]).splitlines()[0],
                      "cc": (tool([env["CC"], "--version"]) or "").splitlines()[0]},
        "netcdf": {"nc-config --version": tool(["nc-config", "--version"]),
                   "nf-config --version": tool(["nf-config", "--version"])},
        "fortran_flags_from_makefiles": {
            "muskingum": "-g -c -O2 -fPIC -lgfortran -lgcc -static-libgfortran -static-libgcc -nodefaultlibs",
            "diffusive": "-g -c -O2 -fPIC -fbounds-check",
            "reservoir": "-g -w -c -ffree-form -ffree-line-length-none -fconvert=big-endian "
                         "-frecord-marker=4 ... -fPIC",
        },
        "libmc_kernel": LIBMC.name,
        "kernel": label,
        "patches": patches,
        "steps": log,
    }
    INFO.write_text(json.dumps(info, indent=2) + "\n")
    print(f"ok      built t-route {TROUTE_SHA[:10]} (kernel: {label}); details in build/build_info.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
