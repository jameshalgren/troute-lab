"""Fetch the NWM v3.1.6 RouteLink_CONUS.nc for the Potomac example, SHA-256 verified.

AI-written (Claude, 2026-10-16). Idempotent: skips a verified file. Reuses a verified
copy from a sibling experiment (repro/*/data/) instead of downloading 269 MB again.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# NWM v3.1.6 (hash observed 2026-09-30, server Last-Modified Thu, 09 Jul 2026; the same
# file and hash as repro/network_stats, repro/routelink_topwidth, repro/short_ts_switch).
ROUTELINK = ("https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain/RouteLink_CONUS.nc",
             "4957655896f4f27854f893d02fa084f9f79c1cf8e80ce77565a7356dadb6fc0e", 269369766)
ROUTELINK_DEST = DATA / "RouteLink_CONUS.nc"
SIBLINGS = sorted(HERE.parent.glob("*/data/RouteLink_CONUS.nc"))

MOVED_HELP = """\
NCEP keeps only operational NWM versions under /pmb/codes/nwprod/. If nwm.v3.1.6 has been
retired, obtain the exact RouteLink_CONUS.nc (matching the SHA-256 above) from an archive
of NWM v3.1.6 parameter files and place it in data/."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    url, want, size = ROUTELINK
    if ROUTELINK_DEST.exists() and sha256(ROUTELINK_DEST) == want:
        print("ok      RouteLink_CONUS.nc (sha256 verified)")
        return 0
    DATA.mkdir(exist_ok=True)
    for sib in SIBLINGS:
        if sib.resolve() != ROUTELINK_DEST.resolve() and sib.stat().st_size == size and sha256(sib) == want:
            shutil.copy2(sib, ROUTELINK_DEST)
            print(f"ok      RouteLink_CONUS.nc (copied from {sib.parent.parent.name}/, sha256 verified)")
            return 0
    print(f"fetch   {url} ({size / 1e6:.0f} MB)")
    part = ROUTELINK_DEST.with_suffix(".nc.part")
    try:
        with urllib.request.urlopen(url, timeout=600) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: download failed: {e}\n{MOVED_HELP}")
        return 1
    got = sha256(part)
    if got != want:
        print(f"ERROR: RouteLink_CONUS.nc sha256 {got} != {want}\n{MOVED_HELP}")
        return 1
    part.rename(ROUTELINK_DEST)
    print("ok      RouteLink_CONUS.nc (downloaded, sha256 verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
