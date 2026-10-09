"""Download every input into data/ and verify its SHA-256.

Idempotent: a file already present with the expected hash is not downloaded again.
Fails (exit 1) with an explanation if a URL is gone or the content has changed.

    uv run python fetch_data.py                  # required + optional inputs
    uv run python fetch_data.py --required-only  # skip the optional NWM v2.1 RouteLink
    uv run python fetch_data.py --verify         # verify only, never download

Required: the four NWM v3.1.6 RouteLink files (same files, URLs, and hashes as
repro/routelink_topwidth/), and Natural Earth 1:10m land boundary lines (border
distance of each outlet) and 1:50m country polygons (segments in Canada or Mexico),
pinned by git commit.
Optional: the NWM v2.1 CONUS RouteLink (the file deployed in nwm.v2.2.0), from a public
HydroShare resource, for the cross-version comparison.
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
BASE = "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm"
NE_SHA = "117488dc884bad03366ff727eca013e434615127"  # natural-earth-vector, "v5.1.0 packaging", 2022-05-05

# relative path: (url, sha256, size in bytes)
REQUIRED = {
    # NWM v3.1.6; hashes observed 2026-09-30 (server Last-Modified Thu, 09 Jul 2026),
    # identical to repro/routelink_topwidth/fetch_data.py.
    "RouteLink_CONUS.nc": (f"{BASE}/domain/RouteLink_CONUS.nc",
                           "4957655896f4f27854f893d02fa084f9f79c1cf8e80ce77565a7356dadb6fc0e", 269369766),
    "RouteLink_AK.nc": (f"{BASE}/domain_alaska/RouteLink_AK.nc",
                        "d27384e77303e9a61ee1f059775a4904d1c54727d717f2d81249721533ecc793", 47399233),
    "RouteLink_HI.nc": (f"{BASE}/domain_hawaii/RouteLink_HI.nc",
                        "9e4ae9de3a6ec9dfabfa774c3acc4c185f675086aac366439f4c7dcb1df19a34", 1346576),
    "RouteLink_PRVI.nc": (f"{BASE}/domain_puertorico/RouteLink_PRVI.nc",
                          "f72ab05cc810cc9498ca7f26fd5097292c5bc4020a10fb83c27b273848a04447", 1380709),
    # Natural Earth (public domain), hash observed 2026-10-06.
    "ne/ne_10m_admin_0_boundary_lines_land.geojson": (
        f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_SHA}/geojson/"
        "ne_10m_admin_0_boundary_lines_land.geojson",
        "74d9c16229c095fde65943a9919e337682f044bcebccb120764f38edf3b70f4a", 2284669),
    # Natural Earth 1:50m country polygons (Canada, Mexico) to flag segments outside the
    # U.S.; hash observed 2026-10-06.
    "ne/ne_50m_admin_0_countries.geojson": (
        f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_SHA}/geojson/"
        "ne_50m_admin_0_countries.geojson",
        "8de557f75718487775c0ebdd5c8c41ba97ce79920a790ba32c40aaaf5ff81654", 3083538),
}
OPTIONAL = {
    # NWM v2.1 CONUS RouteLink. HydroShare resource 0a596929a3e5411bb0032a8de35e5089
    # (created 2022-09-23 by Austin Raney; abstract: pulled from
    # https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v2.2.0/parm/domain/ on 2022-09-23).
    # Global attributes: version = "NWM v2.1", produced Fri Apr 12 2019 by Kevin Sampson
    # (NCAR). The URL redirects to a signed Google Cloud Storage link (no login).
    # Hash observed 2026-10-06.
    "v2.1/RouteLink_CONUS_v2.1.nc": (
        "https://www.hydroshare.org/resource/0a596929a3e5411bb0032a8de35e5089/data/contents/RouteLink_CONUS.nc",
        "1b95f69aa8efcb48a1bd4a28136fabc6a59a5bda87de70f19bb0d453ace1d193", 269366417),
}

MOVED_HELP = """\
NCEP keeps only the operational NWM versions under /pmb/codes/nwprod/. If nwm.v3.1.6 has
been retired, the same files may be under a newer nwm.v3.x.y directory, but they must
then match the SHA-256 above to reproduce these results. Otherwise, obtain the exact
files from an archive of NWM v3.1.6 parameter files and place them in data/.
The optional v2.1 file can be skipped with --required-only."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "troute-paper-repro/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while chunk := r.read(1 << 20):
                f.write(chunk)
                got += len(chunk)
                if total:
                    print(f"\r  {dest.name}: {got / 1e6:7.1f} / {total / 1e6:.1f} MB", end="", flush=True)
            print()
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"ERROR: {url} returned HTTP {e.code}. The file may have moved.\n{MOVED_HELP}")
    except urllib.error.URLError as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"ERROR: could not reach {url}: {e.reason}")
    tmp.replace(dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="only verify existing files")
    ap.add_argument("--required-only", action="store_true", help="skip the optional v2.1 RouteLink")
    args = ap.parse_args()
    files = dict(REQUIRED) if args.required_only else {**REQUIRED, **OPTIONAL}
    bad = []
    for name, (url, want, size) in files.items():
        dest = DATA / name
        if dest.exists() and sha256(dest) == want:
            print(f"ok      {name} (sha256 verified)")
            continue
        if args.verify:
            bad.append(f"{name}: missing or wrong hash")
            continue
        print(f"fetch   {url}")
        download(url, dest)
        got = sha256(dest)
        if got != want:
            bad.append(f"{name}: sha256 {got} != expected {want} "
                       f"(size {dest.stat().st_size}, expected {size}). "
                       "The file at the URL has changed since it was recorded.")
        else:
            print(f"ok      {name} (sha256 verified)")
    if bad:
        print("\nERROR:\n  " + "\n  ".join(bad) + "\n" + MOVED_HELP, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
