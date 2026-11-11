"""Kernel source variants for the harness, and the patch series as a library.

Variants (all from data/, see fetch_data.py):
  L0           T-Route's kernel at CIROH-UA d29f663, unmodified
  L1 .. L8     L0 with patches/0001 .. 000k applied in order
               L8 = the corrected kernel (DEFAULT_LEVEL): uninitialized reads, intent
                    errors, undefined outputs, Secant control-flow errors (0001-0005),
                    and Taher Chegini's Secant package 0006-0008 (false convergence,
                    hold depth, degenerate-root restart). L5 = without the package; L6
                    and L7 (0006 without 0008) are diagnostic only: they lose volume
  L<k>x        L<k> plus the OPTIONAL patch patches/optional/x-cunge-factor2.patch (Cunge's
               X without the extra factor 2; under review in NCAR/wrf_hydro_nwm_public#923, off by default)
  ngwpc123     NGWPC/t-route at the merge of PR #123 (34e6984d)
  ngwpcdev     NGWPC/t-route development at 9a3c303e

apply_series(root, upto) applies the first `upto` patches (all if None) to a T-Route
source tree with `git apply` (works on a plain directory). Other experiments
(short_ts_switch/build_troute.py, upstream_inflow_patch/build_patched.py) call it to
build the corrected kernel.

instrument(src) returns a copy of a kernel source with event counters (module
kernel_trace, array ev(8)) at the branches the patches touch; it adds integer stores only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH_DIR = HERE / "patches"
DATA = HERE / "data"
KREL = "src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90"
LEVELS = 8
DEFAULT_LEVEL = 8
OPTIONAL = {"x": PATCH_DIR / "optional" / "x-cunge-factor2.patch"}


def series() -> list[Path]:
    """The patch files in application order (patches/series)."""
    names = [ln.strip() for ln in (PATCH_DIR / "series").read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    return [PATCH_DIR / n for n in names]


def apply_series(root: Path, upto: int | None = None, check_only: bool = False,
                 optional: str = "") -> list[str]:
    """Apply patches 1..upto (DEFAULT_LEVEL if None) under T-Route source root, then the optional
    patches named by the letters in `optional` (x = Cunge X). Returns their names."""
    ps = series()[: (DEFAULT_LEVEL if upto is None else upto)] + [OPTIONAL[c] for c in optional]
    # A tree inside another git repository (e.g. build/ in this paper repo) makes
    # `git apply` treat paths as relative to that repository and skip them silently;
    # the ceiling stops git from looking above `root`.
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(Path(root).resolve().parent))
    for p in ps:
        cmd = ["git", "apply", "--whitespace=nowarn"] + (["--check"] if check_only else []) + [str(p)]
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env)
        if r.returncode:
            raise RuntimeError(f"git apply {p.name} failed in {root}:\n{r.stderr}")
        if not check_only:  # prove it applied: the reverse must now apply
            r = subprocess.run(["git", "apply", "--reverse", "--check", str(p)], cwd=root,
                               capture_output=True, text=True, env=env)
            if r.returncode:
                raise RuntimeError(f"{p.name} did not apply in {root}:\n{r.stderr}")
    return [p.name for p in ps]


def kernel_source(variant: str, troute: Path | None = None) -> str:
    troute = troute or DATA / "t-route"
    if variant.startswith("L"):
        digits = variant[1:].rstrip("".join(OPTIONAL))
        level, opt = int(digits), variant[1 + len(digits):]
        with tempfile.TemporaryDirectory() as td:
            dst = Path(td) / KREL
            dst.parent.mkdir(parents=True)
            shutil.copy2(troute / KREL, dst)
            apply_series(Path(td), level, optional=opt)
            return dst.read_text()
    ref = {"ngwpc123": "ngwpc_pr123.f90", "ngwpcdev": "ngwpc_development_9a3c303e.f90"}[variant]
    return (DATA / "reference" / ref).read_text()


TRACE_MODULE = """module kernel_trace
    use, intrinsic :: iso_fortran_env, only: int64
    implicit none
    integer(int64) :: ev(9) = 0
end module kernel_trace
"""


def _ins_after(t: str, pattern: str, line: str, count: int | None = 1) -> str:
    rx = re.compile(pattern, re.M)
    hits = list(rx.finditer(t))
    if count is not None and len(hits) != count:
        raise ValueError(f"instrument: {pattern!r} matched {len(hits)} times, expected {count}")
    for m in reversed(hits):
        t = t[: m.end()] + "\n" + line + t[m.end():]
    return t


def _ins_before(t: str, pattern: str, line: str, count: int | None = 1) -> str:
    rx = re.compile(pattern, re.M)
    hits = list(rx.finditer(t))
    if count is not None and len(hits) != count:
        raise ValueError(f"instrument: {pattern!r} matched {len(hits)} times, expected {count}")
    for m in reversed(hits):
        t = t[: m.start()] + line + "\n" + t[m.start():]
    return t


def instrument(src: str) -> str:
    """Event counters (see harness/driver.F90 for their meaning)."""
    t = TRACE_MODULE + "\n" + src
    t = _ins_after(t, r"^([ \t]*)use precis[ \t]*$", "    use kernel_trace, only: ev")
    t = _ins_after(t, r"^111[ \t]+continue[ \t]*$",
                   "        if (((rerror .le. 0.01_prec) .or. (aerror .lt. mindepth)) .and. "
                   "iter .ge. maxiter) ev(1) = ev(1) + 1\n"
                   "        if (iter .eq. 0) ev(6) = ev(6) + 1")
    t = _ins_after(t, r"^[ \t]+if\(h_1 \.lt\. 0\.0_prec\) then[ \t]*$", "                    ev(2) = ev(2) + 1")
    t = _ins_after(t, r"^[ \t]+else[ \t]*$(?=\n[ \t]+h_1 = h\b)", "                ev(3) = ev(3) + 1")
    t = _ins_before(t, r"^[ \t]+goto 110[ \t]*$", "                ev(4) = ev(4) + 1", count=None)
    t = _ins_before(t, r"^[ \t]+!\*yw added for test[ \t]*$", "        if (tries .gt. 4) ev(5) = ev(5) + 1")
    t = _ins_after(t, r"^[ \t]+else[ \t]+!\*no flow to route[ \t]*$", "        ev(7) = ev(7) + 1")
    t = _ins_after(t, r"^[ \t]+iter = iter \+ 1[ \t]*$", "            ev(8) = ev(8) + 1")
    t = _ins_after(t, r"^[ \t]+if \(collapsed \.and\. tries \.le\. 4\) then[ \t]*$",
                   "            ev(9) = ev(9) + 1", count=None)
    return t
