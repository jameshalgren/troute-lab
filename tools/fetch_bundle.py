# /// script
# requires-python = ">=3.10"
# ///
"""Download a versioned data bundle (release assets) and verify every file's SHA-256.

Generated data is not kept in git. Each bundle in ../data_bundles.json lists its files
with size and SHA-256, a release tag, and where the files go in this repository.

    python tools/fetch_bundle.py explorer                # explorer web data -> explorer/data/
    python tools/fetch_bundle.py explorer --full         # + full-resolution tiles (983 MB)
    python tools/fetch_bundle.py network-stats           # domains_snapshot.json -> repro/network_stats/
    python tools/fetch_bundle.py explorer --verify       # check what is present, download nothing
    python tools/fetch_bundle.py explorer --source hydroshare
    python tools/fetch_bundle.py explorer --source https://example.org/mirror/   # or a local directory

Sources (--source): "github" (default) = release assets
https://github.com/<repo>/releases/download/<tag>/<file>; "hydroshare" = the bundle's
"hydroshare" base URL in data_bundles.json (the intended archival home; see the TODO
there); or any base URL / local directory that holds the same files. With the default,
a failed GitHub download falls back to HydroShare when that URL is set.

Standard library only; idempotent (verified files are not downloaded again).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "data_bundles.json"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def ok(p: Path, meta: dict) -> bool:
    return p.exists() and p.stat().st_size == meta["size"] and sha256(p) == meta["sha256"]


def bases(cfg: dict, b: dict, source: str) -> list[str]:
    gh = f"https://github.com/{cfg['repo']}/releases/download/{b['tag']}/"
    hs = b.get("hydroshare")
    if source == "github":
        return [gh] + ([hs] if hs else [])
    if source == "hydroshare":
        if not hs:
            sys.exit("no HydroShare URL for this bundle yet (set \"hydroshare\" in data_bundles.json)")
        return [hs]
    return [source]


def get(base: str, name: str, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".part")
    if base.startswith(("http://", "https://")):
        url = base.rstrip("/") + "/" + name
        req = urllib.request.Request(url, headers={"User-Agent": "troute-lab fetch_bundle.py"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    else:
        shutil.copyfile(Path(base.removeprefix("file://")).expanduser() / name, tmp)
    tmp.replace(dest)


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", choices=sorted(cfg["bundles"]))
    ap.add_argument("--full", action="store_true", help="also the optional (large) files")
    ap.add_argument("--verify", action="store_true", help="verify only, never download")
    ap.add_argument("--source", default="github", help="github (default), hydroshare, or a base URL / directory")
    ap.add_argument("--dest", type=Path, help="target directory (default: the bundle's dest in this repo)")
    a = ap.parse_args()
    b = cfg["bundles"][a.bundle]
    dest = (a.dest or REPO_ROOT / b["dest"]).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    want = {n: m for n, m in b["files"].items() if m.get("required", True) or a.full}
    print(f"{a.bundle} ({b['tag']}): {len(want)} files, {sum(m['size'] for m in want.values()) / 1e6:.1f} MB -> {dest}")
    bad = 0
    for name, meta in want.items():
        p = dest / name
        if ok(p, meta):
            print(f"  ok        {name}")
            continue
        if a.verify:
            print(f"  {'WRONG' if p.exists() else 'missing':9} {name}")
            bad += 1
            continue
        errors = []
        for base in bases(cfg, b, a.source):
            try:
                print(f"  fetching  {name} ({meta['size'] / 1e6:.1f} MB) from {base}")
                get(base, name, p)
            except Exception as e:  # noqa: BLE001  (report and try the next source)
                errors.append(f"{base}: {e}")
                continue
            if ok(p, meta):
                print(f"  ok        {name}")
                break
            errors.append(f"{base}: SHA-256 or size mismatch")
            p.unlink(missing_ok=True)
        else:
            bad += 1
            print(f"  FAILED    {name}: " + "; ".join(errors), file=sys.stderr)
    if bad:
        print(f"{bad} file(s) missing or wrong. The bundle may not be published yet, or the source "
              "changed; see README.md (Data) for the rebuild-from-scratch path.", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
