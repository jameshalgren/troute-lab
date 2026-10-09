# /// script
# requires-python = ">=3.10"
# ///
"""Download and verify the inputs of the basin-explorer build (read-only on the web).

  1. NWM v3.1.6 RouteLink files (CONUS, AK, HI, PRVI): fetched by repro/network_stats/fetch_data.py
     (URLs and SHA-256 pinned there) and linked into data/ (gitignored).
  2. NWM v3 channel hydrofabric (file geodatabase NWM_v3_hydrofabric.gdb), from the link on
     https://water.noaa.gov/about/nwm ("The file gdb is available here", accessed 2026-10-07):
     HYDROFABRIC_URL below, 3,250,751,657 bytes, server Last-Modified 2023-04-13, SHA-256 pinned.
     Downloaded to data/explorer/cache/hydrofabric/ and unpacked to data/NWM_v3_hydrofabric.gdb.

Usage:
  uv run explorer/scripts/fetch_inputs.py            # everything (~3.6 GB of downloads)
  uv run explorer/scripts/fetch_inputs.py --check    # no download: HEAD the URLs, verify what is present
  uv run explorer/scripts/fetch_inputs.py --routelink-only

The other inputs (TIGER/Line boundary, USGS/NWPS/NID/NBI/EPA lookups) are downloaded and
cached by the build scripts themselves.
"""
import argparse
import hashlib
import os
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
REPRO = ROOT / "repro" / "network_stats"
HYDROFABRIC_URL = "https://www.nohrsc.noaa.gov/owp_files/nwm/data_tools/NWM_channel_hydrofabric.tar.gz"
HYDROFABRIC_SHA = "77d8975b543ff864cdac0736cc4f455fe86d77049c4d8b1fb8e458ec755dbc94"
HYDROFABRIC_BYTES = 3_250_751_657
TAR = DATA / "explorer" / "cache" / "hydrofabric" / "NWM_channel_hydrofabric.tar.gz"
GDB = DATA / "NWM_v3_hydrofabric.gdb"
UA = "troute-paper-basin-explorer/1.0 (research build script; read-only)"
ROUTELINK = ["RouteLink_CONUS.nc", "RouteLink_AK.nc", "RouteLink_HI.nc", "RouteLink_PRVI.nc"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 22):
            h.update(b)
    return h.hexdigest()


def head(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers.get("Content-Length") or 0), r.headers.get("Last-Modified", "")


def routelink(check: bool) -> bool:
    sys.path.insert(0, str(REPRO))
    import fetch_data  # noqa: E402  (repro/network_stats/fetch_data.py: URLs + SHA-256)
    ok = True
    if check:
        for name in ROUTELINK:
            url, want, size = fetch_data.REQUIRED[name]
            n, lm = head(url)
            have = DATA / name
            state = ("present, sha256 OK" if have.exists() and sha256(have) == want else
                     "present, WRONG sha256" if have.exists() else "missing")
            print(f"{name}: server {n:,} bytes (pinned {size:,}; Last-Modified {lm}); data/{name}: {state}")
            ok &= n == size and state != "present, WRONG sha256"
        return ok
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}   # the repro has its own locked env
    subprocess.run(["uv", "run", "--locked", "python", "fetch_data.py", "--required-only"], cwd=REPRO, check=True, env=env)
    for name in ROUTELINK:
        src, dst = REPRO / "data" / name, DATA / name
        if not dst.exists():
            DATA.mkdir(exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                dst.write_bytes(src.read_bytes())
        _, want, _ = fetch_data.REQUIRED[name]
        good = sha256(dst) == want
        print(f"data/{name}: {'sha256 OK' if good else 'WRONG sha256'}")
        ok &= good
    return ok


def hydrofabric(check: bool) -> bool:
    n, lm = head(HYDROFABRIC_URL)
    print(f"hydrofabric: server {n:,} bytes (pinned {HYDROFABRIC_BYTES:,}; Last-Modified {lm})")
    if check:
        print(f"  {TAR.relative_to(ROOT)}: {'present' if TAR.exists() else 'missing'}; "
              f"{GDB.relative_to(ROOT)}: {'present' if GDB.exists() else 'missing'}")
        return n == HYDROFABRIC_BYTES
    if GDB.exists():
        print(f"  {GDB.relative_to(ROOT)} already present; not downloading")
        return True
    if not (TAR.exists() and TAR.stat().st_size == HYDROFABRIC_BYTES):
        TAR.parent.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {HYDROFABRIC_URL} (3.25 GB)")
        req = urllib.request.Request(HYDROFABRIC_URL, headers={"User-Agent": UA})
        part = TAR.with_suffix(".part")
        with urllib.request.urlopen(req, timeout=900) as r, open(part, "wb") as f:
            got = 0
            while b := r.read(1 << 22):
                f.write(b)
                got += len(b)
                print(f"\r  {got / 1e9:5.2f} / {HYDROFABRIC_BYTES / 1e9:.2f} GB", end="", flush=True)
        print()
        part.rename(TAR)
    if sha256(TAR) != HYDROFABRIC_SHA:
        sys.exit(f"ERROR: {TAR} SHA-256 differs from the pinned value; the file on the server may have changed")
    print("  sha256 OK; unpacking")
    with tarfile.open(TAR) as t:
        t.extractall(DATA, filter="data")
    print(f"  wrote {GDB.relative_to(ROOT)}")
    return GDB.exists()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="HEAD the URLs and verify local files; download nothing")
    ap.add_argument("--routelink-only", action="store_true")
    a = ap.parse_args()
    ok = routelink(a.check)
    if not a.routelink_only:
        ok &= hydrofabric(a.check)
    print("OK" if ok else "PROBLEMS (see above)")
    if GDB.exists():
        print(f"geodatabase: {GDB} (the build scripts use it by default; or set NWM_HYDROFABRIC_GDB)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
