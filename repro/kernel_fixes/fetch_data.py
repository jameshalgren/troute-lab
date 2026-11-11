"""Fetch the sources this experiment compiles, into data/, and verify them.

    uv run python fetch_data.py            # fetch + verify
    uv run python fetch_data.py --verify   # verify only

1. T-Route, CIROH-UA/t-route at TROUTE_SHA (the commit the patches apply to and the
   other repro/ experiments build). Cloned by commit SHA into data/t-route/. If
   ../short_ts_switch/data/t-route already holds that commit it is cloned from there
   (no download); either way HEAD must equal TROUTE_SHA and the kernel files must match
   the SHA-256 below.
2. Reference kernels, single files fetched by commit SHA (raw.githubusercontent.com) and
   checked by SHA-256:
   - NGWPC/t-route at the merge of PR #123 (34e6984d, 2026-08-21): Taher Chegini's
     kernel fixes on top of NGWPC's performance refactor and NaN guard.
   - NGWPC/t-route `development` at 9a3c303e (2026-09-17): adds 4ecefec1 (restart of a
     collapsed depth search), which is an algorithm change and not part of the patches.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TROUTE_REPO = "https://github.com/CIROH-UA/t-route"
TROUTE_SHA = "d29f663ac23f435b2e5c176f6e0d22ac4528c6a6"
TROUTE_DIR = DATA / "t-route"
SIBLING = HERE.parent / "short_ts_switch" / "data" / "t-route"
KDIR = "src/kernel/muskingum/"
# SHA-256 observed 2026-10-09
TROUTE_FILES = {
    KDIR + "MCsingleSegStime_f2py_NOLOOP.f90": "1c0e47b3528c3fdf20c960408e41138921cb903e5035bd19e6c4e68f8f4b46da",
}
REFERENCE = {
    "ngwpc_pr123.f90": (
        "https://raw.githubusercontent.com/NGWPC/t-route/34e6984dd646d7f7f29126bf910af4b0b87b72b9/"
        + KDIR + "MCsingleSegStime_f2py_NOLOOP.f90",
        "8ddcc4c16f55ebf1f40f7e43f7e6c08c3ce489329b9cdd698feb73c1b90aba28"),
    "ngwpc_development_9a3c303e.f90": (
        "https://raw.githubusercontent.com/NGWPC/t-route/9a3c303ee484ac04d69a44024478a446d8a9c2f4/"
        + KDIR + "MCsingleSegStime_f2py_NOLOOP.f90",
        "c99f5a6192d91039bbe34ef6783432fdd79ce8db1b1462b71a4881eba0e432eb"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str, cwd: Path | None = None) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        sys.exit(f"ERROR: git {' '.join(args)} failed:\n{p.stderr}")
    return p.stdout.strip()


def fetch_troute(verify_only: bool) -> list[str]:
    if not (TROUTE_DIR / ".git").exists():
        if verify_only:
            return [f"{TROUTE_DIR} missing"]
        DATA.mkdir(exist_ok=True)
        src = TROUTE_REPO
        if (SIBLING / ".git").exists() and git("rev-parse", "HEAD", cwd=SIBLING) == TROUTE_SHA:
            src = str(SIBLING)
        git("init", "-q", str(TROUTE_DIR))
        git("remote", "add", "origin", src, cwd=TROUTE_DIR)
        git("fetch", "-q", "--depth", "1", "origin", TROUTE_SHA, cwd=TROUTE_DIR)
        git("checkout", "-q", "FETCH_HEAD", cwd=TROUTE_DIR)
        git("remote", "set-url", "origin", TROUTE_REPO, cwd=TROUTE_DIR)
    bad = []
    head = git("rev-parse", "HEAD", cwd=TROUTE_DIR)
    if head != TROUTE_SHA:
        bad.append(f"data/t-route HEAD {head} != {TROUTE_SHA}")
    for rel, h in TROUTE_FILES.items():
        if sha256(TROUTE_DIR / rel) != h:
            bad.append(f"data/t-route/{rel}: SHA-256 differs")
    return bad


def fetch_reference(verify_only: bool) -> list[str]:
    bad = []
    d = DATA / "reference"
    d.mkdir(parents=True, exist_ok=True)
    for name, (url, h) in REFERENCE.items():
        f = d / name
        if not f.exists() and not verify_only:
            with urllib.request.urlopen(url, timeout=60) as r:
                f.write_bytes(r.read())
        if not f.exists():
            bad.append(f"{f} missing")
        elif sha256(f) != h:
            bad.append(f"{f}: SHA-256 differs (expected {h})")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    bad = fetch_troute(args.verify) + fetch_reference(args.verify)
    if bad:
        print("\n".join("ERROR: " + b for b in bad))
        return 1
    print(f"ok      data/t-route at {TROUTE_SHA[:10]}; {len(REFERENCE)} reference kernels verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
