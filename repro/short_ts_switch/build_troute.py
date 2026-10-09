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
build/t-route. Idempotent: skipped if build/build_info.json matches the commit and the
packages import, unless --force.

--patch-qj (used only by qj_patch_check.sh, in a separate copy of this directory):
initializes the secant variable that the kernel reads before setting it. `secant2_h`
(interval 1) uses its intent(out) argument `Qj` in the X formula; the caller passes
`Qj_0`, which is unset on the first iteration. A plain `Qj_0 = 0` is removed by the
compiler (dead store before an intent(out) argument), so the patch also declares `Qj`
intent(inout). The default build applies no patch.
"""
from __future__ import annotations

import argparse
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


def already_built() -> bool:
    if not INFO.exists() or not LIBMC.exists():
        return False
    try:
        info = json.loads(INFO.read_text())
    except json.JSONDecodeError:
        return False
    if info.get("troute_commit") != TROUTE_SHA:
        return False
    p = subprocess.run([PY, "-c", "import troute.routing.fast_reach.mc_reach, nwm_routing.__main__"],
                       capture_output=True)
    return p.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--patch-qj", action="store_true", help="initialize Qj_0 (diagnostic build only)")
    args = ap.parse_args()
    if not args.force and already_built():
        print(f"ok      t-route {TROUTE_SHA[:10]} already built into this environment")
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
        "patches": patches,
        "steps": log,
    }
    INFO.write_text(json.dumps(info, indent=2) + "\n")
    print(f"ok      built t-route {TROUTE_SHA[:10]}; details in build/build_info.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
