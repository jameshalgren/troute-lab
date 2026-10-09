"""Download the original Fortran kernels, notebooks, and helper code, pinned by commit SHA.

Every file comes from raw.githubusercontent.com at an immutable commit and is checked
against the SHA-256 recorded below (observed 2026-10-05). Idempotent; exits 1 with an
explanation if a download fails or a hash differs.

    uv run python fetch_data.py            # download / verify
    uv run python fetch_data.py --verify   # verify only
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
REPO = "awlostowski-noaa/t-route"

# Commit of courant_test.ipynb (2020-10-06 notebook, last touched at this commit).
# The same work was merged upstream in NOAA-OWP/t-route PR #152 (2020-10-16).
COURANT_SHA = "27e06eefc43135a767f20cd0561190af7b8f4ed1"
# Commit of mc_numerical_dispersion.ipynb, branch segment-merge (2020-09-07).
DISPERSION_SHA = "de529705a11f0e305f9b4d46c32d65d08e289de7"

_FS = "src/fortran_routing/mc_pylink_v00/MC_singleSeg_singleTS"

# local path under data/: (commit, path in repo, sha256)
FILES = {
    # --- primary experiment (courant_test.ipynb) ---
    "courant/courant_test.ipynb":
        (COURANT_SHA, "notebooks/courant_test.ipynb",
         "f187169d0ba579295e2d1bd9a60aa6dbdc6485da69a08b4f7cad0d2414b149c0"),
    "courant/MCsingleSegStime_f2py_NOLOOP-anw.f90":
        (COURANT_SHA, f"{_FS}/courant_dev/MCsingleSegStime_f2py_NOLOOP-anw.f90",
         "251ffa5bbc47701df128178ffd42bc8ee626f014e7323fa52ee13add568441a3"),
    # The notebook copies the base directory's varPrecision.f90 into courant_dev/.
    "courant/varPrecision.f90":
        (COURANT_SHA, f"{_FS}/varPrecision.f90",
         "a18253a9d75fcc56a3677a3832ae1f3c9fde0225a61a1d07a26763f69c9dfaf1"),
    # --- exploratory experiment (mc_numerical_dispersion.ipynb) ---
    "dispersion/mc_numerical_dispersion.ipynb":
        (DISPERSION_SHA, "notebooks/mc_numerical_dispersion.ipynb",
         "b8268d4ed3e6f34cd7187fe6615a23e7ed62c15e71004d7dd9ca75ae77661a43"),
    "dispersion/varPrecision.f90":
        (DISPERSION_SHA, f"{_FS}/varPrecision.f90",
         "a18253a9d75fcc56a3677a3832ae1f3c9fde0225a61a1d07a26763f69c9dfaf1"),
    "dispersion/MCsingleSegStime_f2py_NOLOOP.f90":
        (DISPERSION_SHA, f"{_FS}/MCsingleSegStime_f2py_NOLOOP.f90",
         "c231224d7137b5a2076e5ccfcb40cdfb108c9268f0c9bb48b4025894307171f2"),
    "dispersion/pyMCsingleSegStime_NoLoop.f90":
        (DISPERSION_SHA, f"{_FS}/pyMCsingleSegStime_NoLoop.f90",
         "084e7967cdf01edc48c783c22ace19bf3067780c379d151755d45103ce6af93b"),
    # Cython reach loop that the dispersion notebook called; ported line by line in
    # run_dispersion.py (kept here as the reference for that port).
    "dispersion/mc_reach.pyx":
        (DISPERSION_SHA, "src/python_routing_v02/mc_reach.pyx",
         "c7bae2553a5186d21bcb77e8abee9e981419efe4a630a74ffce04213b94d4977"),
    # Network decomposition used by the notebook; imported unmodified.
    "dispersion/nhd_network.py":
        (DISPERSION_SHA, "src/python_framework_v02/nhd_network.py",
         "1c61d1dd08ecd79bf880ede80c7222fd1c00eb94cbd8a164166544052904b43f"),
    # Source of replace_downstreams() (ported; the module imports geopandas).
    "dispersion/nhd_io.py":
        (DISPERSION_SHA, "src/python_framework_v02/nhd_io.py",
         "8bb0dc86119ae0cf08b274131245b664901b24f99095d3762c5b5b49c407f156"),
}


def url_for(commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{commit}/{path}"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "troute-paper-repro/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"ERROR: {url} returned HTTP {e.code}. If the fork {REPO} was deleted, the "
                 "same commits are reachable from NOAA-OWP/t-route only for the parts merged "
                 "in PR #152; otherwise restore the files from an archive and place them in data/.")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: could not reach {url}: {e.reason}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="only verify existing files")
    args = ap.parse_args()
    bad = []
    for rel, (commit, path, want) in FILES.items():
        dest = DATA / rel
        if dest.exists() and sha256(dest) == want:
            print(f"ok      {rel}")
            continue
        if args.verify:
            bad.append(f"{rel}: missing or wrong hash")
            continue
        url = url_for(commit, path)
        print(f"fetch   {url}")
        download(url, dest)
        got = sha256(dest)
        if got != want:
            bad.append(f"{rel}: sha256 {got} != expected {want}")
        else:
            print(f"ok      {rel}")
    if bad:
        print("ERROR:\n  " + "\n  ".join(bad), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
