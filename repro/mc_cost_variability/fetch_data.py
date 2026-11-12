"""Find (or download) NWM v3.1.7 RouteLink_CONUS.nc and verify its SHA-256.

    uv run --locked python fetch_data.py

The file is shared with ../network_stats and ../short_ts_switch (same URL and SHA-256 as
their fetch_data.py). A verified copy in one of those folders is used in place; otherwise
it is downloaded into data/ (gitignored).
"""
from __future__ import annotations

import sys
import urllib.request

from common import DATA, ROUTELINK_CANDIDATES, ROUTELINK_SHA256, ROUTELINK_URL, sha256


def main() -> int:
    for p in ROUTELINK_CANDIDATES:
        if p.exists():
            if sha256(p) == ROUTELINK_SHA256:
                print(f"ok      RouteLink_CONUS.nc (sha256 verified) at {p.relative_to(DATA.parent.parent)}")
                return 0
            print(f"warn    {p}: sha256 mismatch, ignored")
    dest = DATA / "RouteLink_CONUS.nc"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    print(f"fetch   {ROUTELINK_URL}")
    req = urllib.request.Request(ROUTELINK_URL, headers={"User-Agent": "troute-paper-repro/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    if sha256(tmp) != ROUTELINK_SHA256:
        tmp.unlink()
        print("ERROR: downloaded RouteLink_CONUS.nc has a different SHA-256 (see "
              "../short_ts_switch/fetch_data.py MOVED_HELP)", file=sys.stderr)
        return 1
    tmp.replace(dest)
    print("ok      RouteLink_CONUS.nc (downloaded, sha256 verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
