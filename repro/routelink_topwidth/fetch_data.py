"""Download the NWM v3.1.6 RouteLink files into data/ and verify their SHA-256.

Idempotent: a file already present with the expected hash is not downloaded again.
Fails (exit 1) with an explanation if a URL is gone or the content has changed.

    uv run python fetch_data.py            # download / verify all four domains
    uv run python fetch_data.py --verify   # verify only, never download
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

# name: (url, sha256, size in bytes). Hashes observed on copies downloaded 2026-09-30;
# re-confirmed against the server's Content-Length and Last-Modified
# (Thu, 09 Jul 2026) on 2026-10-05.
FILES = {
    "RouteLink_CONUS.nc": (f"{BASE}/domain/RouteLink_CONUS.nc",
                           "4957655896f4f27854f893d02fa084f9f79c1cf8e80ce77565a7356dadb6fc0e", 269369766),
    "RouteLink_AK.nc": (f"{BASE}/domain_alaska/RouteLink_AK.nc",
                        "d27384e77303e9a61ee1f059775a4904d1c54727d717f2d81249721533ecc793", 47399233),
    "RouteLink_HI.nc": (f"{BASE}/domain_hawaii/RouteLink_HI.nc",
                        "9e4ae9de3a6ec9dfabfa774c3acc4c185f675086aac366439f4c7dcb1df19a34", 1346576),
    "RouteLink_PRVI.nc": (f"{BASE}/domain_puertorico/RouteLink_PRVI.nc",
                          "f72ab05cc810cc9498ca7f26fd5097292c5bc4020a10fb83c27b273848a04447", 1380709),
}

MOVED_HELP = """\
NCEP keeps only the operational NWM versions under /pmb/codes/nwprod/. If nwm.v3.1.6 has
been retired, the same files may be under a newer nwm.v3.x.y directory, but they must
then match the SHA-256 above to reproduce these results. Otherwise, obtain the exact
files from an archive of NWM v3.1.6 parameter files and place them in data/."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
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
    args = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    bad = []
    for name, (url, want, size) in FILES.items():
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
                       "The file at the URL has changed since 2026-09-30.")
        else:
            print(f"ok      {name} (sha256 verified)")
    if bad:
        print("\nERROR:\n  " + "\n  ".join(bad) + "\n" + MOVED_HELP, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
