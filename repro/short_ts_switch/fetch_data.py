"""Fetch every input into data/ and verify it.

Idempotent: verified inputs are not fetched again. Fails (exit 1) with an explanation if
a source is gone or its content differs from what was recorded.

    uv run python fetch_data.py            # fetch + verify
    uv run python fetch_data.py --verify   # verify only, never download

Inputs
1. T-Route source, CIROH-UA/t-route at commit TROUTE_SHA (head of branch `ngiab`,
   2026-09-18, "Merge pull request #49 from alk05/update_for_feather_da"). Fetched with
   git by commit SHA (immutable) into data/t-route/. Its test domain
   test/LowerColorado_TX/ (RouteLink subset + 28 hourly NWM CHRTOUT files) is one of
   the two domains; those files are additionally checked against the SHA-256 below.
2. NWM v3.1.6 RouteLink_CONUS.nc from NCEP (same URL and hash as repro/network_stats/
   and repro/routelink_topwidth/), from which the Potomac network is extracted. If a
   sibling experiment already holds a verified copy, it is hard-linked (or copied)
   instead of downloaded again.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

TROUTE_REPO = "https://github.com/CIROH-UA/t-route"
TROUTE_SHA = "d29f663ac23f435b2e5c176f6e0d22ac4528c6a6"
TROUTE_DIR = DATA / "t-route"

# SHA-256 of the LowerColorado_TX files used, observed 2026-10-07 at TROUTE_SHA.
LC = "test/LowerColorado_TX/"
LC_FILES = {
    "domain/RouteLink.nc": "e7ab06e5a93c664a91b10650063e0994279ef5ecc355024a780594d44e1aab47",
    "channel_forcing/202108231300.CHRTOUT_DOMAIN1": "c9161e8789ffafcef10089f1ea422e1fc9dfce7e4af632e42239dec4c47e35d0",
    "channel_forcing/202108231400.CHRTOUT_DOMAIN1": "c73f24043c952f0f15b098cf0855fd660556c83777a30ad022bbf4ab8e47d907",
    "channel_forcing/202108231500.CHRTOUT_DOMAIN1": "3c3c8aab92171aecaf6c77695f228737681c0564a2daaaada35fcca03c34b4b1",
    "channel_forcing/202108231600.CHRTOUT_DOMAIN1": "8ef0c61545d2dd9eb579d331daccdb2e036a6a45ba9c2f53dc4be00e1e496fb2",
    "channel_forcing/202108231700.CHRTOUT_DOMAIN1": "e2d27080ec4d963ef103dff1bc1b4b569c3ce005357cec937911d0d8213d1d3d",
    "channel_forcing/202108231800.CHRTOUT_DOMAIN1": "4283d1379ef66804919ba7a31e5d69cf696478c3e15a6f1b768e25de844a5aaa",
    "channel_forcing/202108231900.CHRTOUT_DOMAIN1": "63feedbae1bc1e25bfb4f07002c0d101380b04361196f1b5bd9add48060be13b",
    "channel_forcing/202108232000.CHRTOUT_DOMAIN1": "11ef4f617353e372561656a9c052efe57946a09b68e052e549758941eeca06de",
    "channel_forcing/202108232100.CHRTOUT_DOMAIN1": "49960896b7a1d86529f7933f542b73497f35d6def24af31b61907628cc969e98",
    "channel_forcing/202108232200.CHRTOUT_DOMAIN1": "52544309d00b86b658bea8641416645c5583979a04a1f990b16deb5d7acbe1f3",
    "channel_forcing/202108232300.CHRTOUT_DOMAIN1": "368b98aa98c3c4a2dc4d6d5ba49c76956f7a49d18d67f0bc4e1e9350af009ea2",
    "channel_forcing/202108240000.CHRTOUT_DOMAIN1": "a20f09d27f4d2f15ffa3d21b524380bc120397dbb5f79d3b367366a25cbb1b97",
    "channel_forcing/202108240100.CHRTOUT_DOMAIN1": "aef15cdebb97704b6b9cf05191da23d17aaaf17a757ca1d023bfa76983e89653",
    "channel_forcing/202108240200.CHRTOUT_DOMAIN1": "73d53c78bb0d9094bb2fa23caf9463a72317fd3157de7879d73dc1fac14687c2",
    "channel_forcing/202108240300.CHRTOUT_DOMAIN1": "bb4feee3883a6809a874cab2bb70aa8685f1e6afb040c3d60d0d26e617f56308",
    "channel_forcing/202108240400.CHRTOUT_DOMAIN1": "4a8b47f1983123cdb16be1694c1227105b7356a8826c9e1e0d3c1139319a5a98",
    "channel_forcing/202108240500.CHRTOUT_DOMAIN1": "9ea2118f14c7cddf9b104c090adedfa51809a86083d73b07158cfaad79ef7a5e",
    "channel_forcing/202108240600.CHRTOUT_DOMAIN1": "f29b41123761412d48246e70ac6b07c5985d5f47438918cd433f36931eff3bdc",
    "channel_forcing/202108240700.CHRTOUT_DOMAIN1": "9f4ed90f3c1d0552b9dfae0a04e3a81c9c29945014737eeaf9bb625e82398203",
    "channel_forcing/202108240800.CHRTOUT_DOMAIN1": "47197e89178bad9ca58dfaf6f2e843a9ea0e6ab1248a024d5480fb5f7e2ed38f",
    "channel_forcing/202108240900.CHRTOUT_DOMAIN1": "2b5a34d9aedc56d2ddf7265b359f7ffb2811d139c84e8cecea07f603e1f65904",
    "channel_forcing/202108241000.CHRTOUT_DOMAIN1": "8840e77ffdf42721db57365ff77af77d13ea5111e7a1ae2548b0ec13e6209862",
    "channel_forcing/202108241100.CHRTOUT_DOMAIN1": "7f8ed4d44cb77a562b52dad3691e3293948ba6fee2e232bde11492477add04fd",
    "channel_forcing/202108241200.CHRTOUT_DOMAIN1": "f7cd3785b3e134badaeb76e235c65206a7e2223481367eee6ba81f810319fdbc",
    "channel_forcing/202108241300.CHRTOUT_DOMAIN1": "0ca881eac6c1ada9665125ab05ed2af4fbed56d877af1838b78dc110b7edce00",
    "channel_forcing/202108241400.CHRTOUT_DOMAIN1": "82246ae2791d4c9d1ea4132deee9381baabd78b87f83b7dbd569d9f9e5d1a884",
    "channel_forcing/202108241500.CHRTOUT_DOMAIN1": "b2921a94d59653a2bdb398b217fbb44a464a73f4545d5cc5e58c9984b691fa91",
    "channel_forcing/202108241600.CHRTOUT_DOMAIN1": "3f2b6df2cdac60933a1bcdb2a0477fbdab6f0c66181fd6fe248cbd380e8838df",
}

# NWM v3.1.6 (hash observed 2026-09-30, server Last-Modified Thu, 09 Jul 2026; identical
# to repro/network_stats/fetch_data.py and repro/routelink_topwidth/fetch_data.py).
ROUTELINK = ("https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain/RouteLink_CONUS.nc",
             "4957655896f4f27854f893d02fa084f9f79c1cf8e80ce77565a7356dadb6fc0e", 269369766)
ROUTELINK_DEST = DATA / "RouteLink_CONUS.nc"
SIBLINGS = [HERE.parent / "network_stats" / "data" / "RouteLink_CONUS.nc",
            HERE.parent / "routelink_topwidth" / "data" / "RouteLink_CONUS.nc"]

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


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"ERROR: git {' '.join(args)} failed:\n{out.stderr}")
    return out.stdout.strip()


def fetch_troute(verify_only: bool) -> list[str]:
    bad = []
    if not (TROUTE_DIR / ".git").exists():
        if verify_only:
            return ["data/t-route missing"]
        print(f"fetch   {TROUTE_REPO} @ {TROUTE_SHA} (shallow, by commit SHA)")
        TROUTE_DIR.mkdir(parents=True, exist_ok=True)
        git("init", "-q", cwd=TROUTE_DIR)
        git("fetch", "-q", "--depth", "1", TROUTE_REPO, TROUTE_SHA, cwd=TROUTE_DIR)
        git("checkout", "-q", "FETCH_HEAD", cwd=TROUTE_DIR)
    head = git("rev-parse", "HEAD", cwd=TROUTE_DIR)
    if head != TROUTE_SHA:
        bad.append(f"data/t-route HEAD is {head}, expected {TROUTE_SHA}")
    if git("status", "--porcelain", cwd=TROUTE_DIR):
        bad.append("data/t-route has local modifications (it must stay pristine; the build "
                   "works on a copy in build/)")
    if not bad:
        print(f"ok      t-route source @ {head} (clean)")
    for rel, want in LC_FILES.items():
        p = TROUTE_DIR / LC / rel
        if not p.exists():
            bad.append(f"{LC}{rel} missing")
        elif sha256(p) != want:
            bad.append(f"{LC}{rel}: sha256 mismatch")
    if not any(LC in b for b in bad):
        print(f"ok      {LC}: {len(LC_FILES)} files (sha256 verified)")
    return bad


def fetch_routelink(verify_only: bool) -> list[str]:
    url, want, size = ROUTELINK
    if ROUTELINK_DEST.exists() and sha256(ROUTELINK_DEST) == want:
        print("ok      RouteLink_CONUS.nc (sha256 verified)")
        return []
    if verify_only:
        return ["RouteLink_CONUS.nc missing or wrong hash"]
    ROUTELINK_DEST.parent.mkdir(parents=True, exist_ok=True)
    for sib in SIBLINGS:
        if sib.exists() and sha256(sib) == want:
            try:
                os.link(sib, ROUTELINK_DEST)
            except OSError:
                shutil.copy2(sib, ROUTELINK_DEST)
            print(f"ok      RouteLink_CONUS.nc (from sibling experiment, sha256 verified)")
            return []
    print(f"fetch   {url}")
    tmp = ROUTELINK_DEST.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "troute-paper-repro/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"ERROR: could not download {url}: {e}\n{MOVED_HELP}")
    tmp.replace(ROUTELINK_DEST)
    got = sha256(ROUTELINK_DEST)
    if got != want:
        return [f"RouteLink_CONUS.nc: sha256 {got} != expected {want} (size "
                f"{ROUTELINK_DEST.stat().st_size}, expected {size}). The file at the URL has changed."]
    print("ok      RouteLink_CONUS.nc (sha256 verified)")
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="only verify existing inputs")
    args = ap.parse_args()
    bad = fetch_troute(args.verify) + fetch_routelink(args.verify)
    if bad:
        print("\nERROR:\n  " + "\n  ".join(bad) + "\n" + MOVED_HELP, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
