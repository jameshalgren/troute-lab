"""Build T-Route (CIROH-UA d29f663) with the upstream-inflow patch into this .venv.

Mirrors repro/short_ts_switch/build_troute.py (which follows t-route's own compiler.sh
and Dockerfile at that commit), with one extra step: `git apply` of
troute-upstream-inflow.patch to the source copy before compiling.

1. Source: CIROH-UA/t-route at TROUTE_SHA. Reuses ../short_ts_switch/data/t-route
   (read-only, via `git archive`) if it holds that commit; otherwise fetches the commit
   by SHA into data/t-route.
2. build/t-route = `git archive` of that commit + the patch.
3. Fortran kernels with t-route's makefiles (muskingum, diffusive, reservoir lp/rfc),
   then troute.network, troute.routing (--use-cython), troute.config and nwm_routing
   with `uv pip install --no-deps --no-build-isolation` against the locked numpy/Cython.
4. build/build_info.json: commit, patch SHA-256, compilers, every command.

    uv run python build_patched.py [--variant corrected|unpatched] [--force] [--no-patch]

Kernel (2026-10-09; project rule: tests use a kernel without known coding errors):
  corrected  (default) the MC kernel with the patch series ../kernel_fixes/patches/
             (Taher Chegini's NGWPC #123 kernel fixes and three further corrections)
  unpatched  the kernel as published at d29f663 (opt-in comparison; reads uninitialized
             variables, so clipped and full runs differ for that reason alone)
Before 2026-10-09 the variants were "default" (= unpatched kernel) and "qj" (the Qj-only
diagnostic fix from repro/short_ts_switch); "corrected" replaces "qj".

Each variant needs its own environment (run.sh: .venv for corrected,
build/venv_unpatched for unpatched, selected with UV_PROJECT_ENVIRONMENT) and builds in
build/<variant>/.

--no-patch builds the unpatched commit (used only to confirm the patch changes nothing
when no boundaries are configured; run.sh does not need it).
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
TROUTE_REPO = "https://github.com/CIROH-UA/t-route"
TROUTE_SHA = "d29f663ac23f435b2e5c176f6e0d22ac4528c6a6"
SIBLING_SRC = HERE.parent / "short_ts_switch" / "data" / "t-route"
OWN_SRC = HERE / "data" / "t-route"
PATCH = HERE / "troute-upstream-inflow.patch"
VARIANTS = ("corrected", "unpatched")
KERNEL_FIXES = HERE.parent / "kernel_fixes"
BUILD = SRC = INFO = None  # set in main() from --variant: build/<variant>/
PY = sys.executable
log: list[dict] = []


def run(cmd, cwd: Path, env: dict, check: bool = True) -> str:
    shell = isinstance(cmd, str)
    print(f"[{cwd}] {cmd if shell else ' '.join(cmd)}", flush=True)
    p = subprocess.run(cmd, cwd=cwd, env=env, shell=shell, capture_output=True, text=True)
    log.append({"cwd": str(cwd.relative_to(HERE)) if cwd.is_relative_to(HERE) else str(cwd),
                "cmd": cmd, "returncode": p.returncode})
    if check and p.returncode != 0:
        sys.stderr.write(p.stdout[-4000:] + "\n" + p.stderr[-4000:])
        sys.exit(f"ERROR: build step failed: {cmd}")
    return p.stdout


def tool(cmd: list[str]) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    p = subprocess.run(cmd, capture_output=True, text=True)
    return (p.stdout or p.stderr).strip()


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def has_commit(repo: Path) -> bool:
    if not (repo / ".git").exists():
        return False
    p = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{TROUTE_SHA}^{{commit}}"],
                       capture_output=True)
    return p.returncode == 0


def source_repo(env: dict) -> Path:
    if has_commit(SIBLING_SRC):
        return SIBLING_SRC
    if not has_commit(OWN_SRC):
        OWN_SRC.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "-q"], OWN_SRC, env)
        run(["git", "fetch", "--depth", "1", TROUTE_REPO, TROUTE_SHA], OWN_SRC, env)
    return OWN_SRC


def already_built(patched: bool, kernel: str) -> bool:
    if not INFO.exists():
        return False
    try:
        info = json.loads(INFO.read_text())
    except json.JSONDecodeError:
        return False
    want = sha256(PATCH) if patched else None
    if (info.get("troute_commit") != TROUTE_SHA or info.get("patch_sha256") != want
            or info.get("kernel") != kernel):
        return False
    if kernel == "corrected":  # rebuild when the kernel patch files change
        sys.path.insert(0, str(KERNEL_FIXES))
        import kernels as KF
        want = [{"patch": p.name, "sha256": sha256(p)} for p in KF.series()[:KF.DEFAULT_LEVEL]]
        if info.get("kernel_patches") != want:
            return False
    p = subprocess.run([PY, "-c", "import troute.routing.fast_reach.mc_reach, nwm_routing.__main__"],
                       capture_output=True)
    return p.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-patch", action="store_true")
    ap.add_argument("--variant", choices=VARIANTS, default="corrected",
                    help="corrected (default): the MC kernel with ../kernel_fixes/patches; "
                         "unpatched: the kernel as published (comparison)")
    args = ap.parse_args()
    global BUILD, SRC, INFO
    BUILD = HERE / "build" / args.variant
    SRC, INFO = BUILD / "t-route", BUILD / "build_info.json"
    patched = not args.no_patch
    if not args.force and already_built(patched, args.variant):
        print(f"ok      t-route {TROUTE_SHA[:10]} ({'patched' if patched else 'unpatched'}) already built")
        return 0

    fc = os.environ.get("F90", os.environ.get("FC", "gfortran"))
    for t in (fc, "make", "nf-config", "nc-config", "git"):
        if shutil.which(t) is None:
            sys.exit(f"ERROR: '{t}' not found. Needs a Fortran compiler, make, git and "
                     "netCDF-C/netCDF-Fortran (nc-config, nf-config).")
    env = os.environ.copy()
    repo = source_repo(env)
    if SRC.exists():
        shutil.rmtree(SRC)
    SRC.mkdir(parents=True)
    run(f"git -C '{repo}' archive {TROUTE_SHA} | tar -x -C '{SRC}'", HERE, env)
    if patched:
        # build/ lies inside the paper repository: stop git from finding that repository,
        # or `git apply` would silently skip every path (they are outside the subdirectory).
        genv = dict(env, GIT_CEILING_DIRECTORIES=str(BUILD))
        run(["git", "apply", "--check", str(PATCH)], SRC, genv)
        run(["git", "apply", str(PATCH)], SRC, genv)
        run(["git", "apply", "--reverse", "--check", str(PATCH)], SRC, genv)  # proves it applied

    kernel_patches = []
    if args.variant == "corrected":
        sys.path.insert(0, str(KERNEL_FIXES))
        import kernels as KF  # ../kernel_fixes/kernels.py (applies with a git ceiling, verifies)
        kernel_patches = [{"patch": n, "sha256": sha256(KF.PATCH_DIR / n)} for n in KF.apply_series(SRC)]
        print(f"ok      applied {len(kernel_patches)} kernel patches", flush=True)

    libext = ".dylib" if platform.system() == "Darwin" else ".so"
    libgf = Path(subprocess.run([fc, "-print-file-name=libgfortran" + libext],
                                capture_output=True, text=True).stdout.strip()).resolve().parent
    nf_lib = Path(tool(["nf-config", "--prefix"])) / "lib"
    nc_lib = Path(tool(["nc-config", "--prefix"])) / "lib"
    env.update({
        "F90": fc, "FC": fc, "CC": env.get("CC", "gcc"),
        "NETCDFINC": tool(["nf-config", "--includedir"]),
        "LIBRARY_PATH": os.pathsep.join(filter(None, [str(libgf), str(nf_lib), str(nc_lib),
                                                       env.get("LIBRARY_PATH", "")])),
    })
    k = SRC / "src" / "kernel"
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
    run([PY, "-c", "import troute.routing.fast_reach.mc_reach, nwm_routing.__main__; print('import ok')"],
        HERE, env)
    INFO.write_text(json.dumps({
        "troute_repo": TROUTE_REPO,
        "troute_commit": TROUTE_SHA,
        "patch": PATCH.name if patched else None,
        "patch_sha256": sha256(PATCH) if patched else None,
        "variant": args.variant,
        "kernel": args.variant,
        "kernel_patches": kernel_patches,
        "venv": sys.prefix,
        "platform": platform.platform(),
        "compilers": {fc: (tool([fc, "--version"]) or "").splitlines()[0],
                      "cc": (tool([env["CC"], "--version"]) or "").splitlines()[0]},
        "netcdf": {"nc-config --version": tool(["nc-config", "--version"]),
                   "nf-config --version": tool(["nf-config", "--version"])},
        "steps": log,
    }, indent=2) + "\n")
    print(f"ok      built t-route {TROUTE_SHA[:10]} ({'patched' if patched else 'unpatched'}, "
          f"kernel {args.variant})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
