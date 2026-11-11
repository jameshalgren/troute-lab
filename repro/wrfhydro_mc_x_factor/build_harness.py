"""Fetch WRF-Hydro's module_channel_routing.F90 at a pinned commit, apply the draft
patch, extract SUBMUSKINGCUNGE verbatim from both versions, and compile the harness.

AI-written (Claude, 2026-10-09). Stdlib only; needs gfortran and `patch`.
"""
import hashlib
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
WRF_REPO = "NCAR/wrf_hydro_nwm_public"
WRF_SHA = "55ed71c8fe4e82a385aad2d4c2aa576039c814ba"  # main, 2026-10-09
REL = "src/Routing/module_channel_routing.F90"
URL = f"https://raw.githubusercontent.com/{WRF_REPO}/{WRF_SHA}/{REL}"
PATCH = HERE / "wrf_hydro_mc_x_cunge.patch"
FC = shutil.which("gfortran") or "gfortran"
# WRF-Hydro's own gfortran flags (CMakeLists.txt, GNU branch), Release -O2
FFLAGS = ["-cpp", "-w", "-ffree-form", "-ffree-line-length-none", "-O2"]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def extract_sub(src: str) -> str:
    m = re.search(r"^subroutine SUBMUSKINGCUNGE\(.*?^END SUBROUTINE SUBMUSKINGCUNGE\s*$",
                  src, flags=re.S | re.M | re.I)
    if not m:
        raise SystemExit("SUBMUSKINGCUNGE not found")
    return m.group(0)


def wrap(modname: str, body: str) -> str:
    return (f"module {modname}\n  use iso_fortran_env, only: int64\n"
            "  use harness_stubs, only: hydro_stop, linkls_s, my_id\n  implicit none\n"
            "contains\n" + body + f"\nend module {modname}\n")


def main() -> None:
    orig_dir, pat_dir = BUILD / "orig", BUILD / "patched"
    for d in (orig_dir, pat_dir):
        (d / Path(REL).parent).mkdir(parents=True, exist_ok=True)
    o = orig_dir / REL
    if not o.exists():
        print("fetch", URL)
        with urllib.request.urlopen(URL, timeout=120) as r:
            o.write_bytes(r.read())
    p = pat_dir / REL
    shutil.copy(o, p)
    subprocess.run(["patch", "-s", "-p1", "-d", str(pat_dir), "-i", str(PATCH)], check=True)
    so, sp = o.read_text(), p.read_text()
    diff_lines = [i + 1 for i, (a, b) in enumerate(zip(so.splitlines(), sp.splitlines())) if a != b]
    (BUILD / "mc_orig.F90").write_text(wrap("mc_orig", extract_sub(so)))
    (BUILD / "mc_patched.F90").write_text(wrap("mc_patched", extract_sub(sp)))
    mods = [HERE / "fortran" / "stubs.F90", BUILD / "mc_orig.F90", BUILD / "mc_patched.F90"]
    for prog in ("driver", "network_driver"):      # prismatic channel; Potomac network
        srcs = [*mods, HERE / "fortran" / f"{prog}.F90"]
        subprocess.run([FC, *FFLAGS, "-J", str(BUILD), "-o", str(BUILD / prog), *map(str, srcs)],
                       check=True)
    ver = subprocess.run([FC, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    info = {"wrf_hydro_repo": WRF_REPO, "wrf_hydro_sha": WRF_SHA, "file": REL, "url": URL,
            "sha256_original": sha256(o), "sha256_patched": sha256(p),
            "sha256_patch": sha256(PATCH), "changed_lines": diff_lines,
            "compiler": ver, "fflags": FFLAGS}
    (BUILD / "build_info.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
