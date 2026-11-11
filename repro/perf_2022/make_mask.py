"""Write a t-route domain mask: every RouteLink segment upstream of (and including) an outlet.

AI-written (Claude, 2026-11-04); not yet reviewed by the author.

The mask is a one-column CSV of feature_ids with no header. That is the format t-route's
`supernetwork_parameters: mask_file_path` reads at a6efbf4e (nhd_io.read_mask ->
pandas.read_csv(header=None); the first column becomes the index that filters the
RouteLink) and at CIROH-UA d29f663. fetch_inputs.py --mask uses the same file to cut
the lateral-inflow files down to these segments.

Presets (outlet feature_ids from other repro/ experiments, NWM v3.1.6 RouteLink; the
script checks that the outlet exists in the RouteLink it is given):
  potomac  4539621  mouth at Chesapeake Bay; 16,454 segments in v3.1.6
                    (../short_ts_switch/README.md, case potomac_storm)
  ohio     1844789  last Ohio River segment above the Mississippi; 230,729 segments in
                    v3.1.6 (../network_stats/expected/subrivers_expected.json)

Usage:
  uv run --locked python make_mask.py potomac [--routelink data/static/RouteLink_CONUS_v2.1.nc]
  uv run --locked python make_mask.py --outlet 1234567 --name mybasin
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import netCDF4
import numpy as np

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PERF2022_DATA", HERE / "data")).resolve()
PRESETS = {"potomac": 4539621, "ohio": 1844789}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preset", nargs="?", choices=sorted(PRESETS))
    ap.add_argument("--outlet", type=int)
    ap.add_argument("--name")
    ap.add_argument("--routelink", type=Path, default=DATA / "static" / "RouteLink_CONUS_v2.1.nc")
    ap.add_argument("--out-dir", type=Path, default=DATA / "masks")
    a = ap.parse_args()
    if a.preset:
        outlet, name = PRESETS[a.preset], a.name or a.preset
    elif a.outlet and a.name:
        outlet, name = a.outlet, a.name
    else:
        ap.error("give a preset, or --outlet and --name")

    with netCDF4.Dataset(a.routelink) as ds:
        link = np.ma.filled(ds["link"][:], -1).astype(np.int64)
        to = np.ma.filled(ds["to"][:], 0).astype(np.int64)
    if outlet not in set(link.tolist()):
        sys.exit(f"ERROR: outlet {outlet} is not a link in {a.routelink}")
    up = defaultdict(list)
    for l, t in zip(link.tolist(), to.tolist()):
        up[t].append(l)
    seen, stack = {outlet}, [outlet]
    while stack:
        for u in up.get(stack.pop(), ()):
            if u not in seen:
                seen.add(u)
                stack.append(u)
    ids = np.array(sorted(seen), dtype=np.int64)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    out = a.out_dir / f"{name}.csv"
    np.savetxt(out, ids, fmt="%d")
    info = {"name": name, "outlet": outlet, "n_segments": int(len(ids)),
            "routelink": str(a.routelink.name), "routelink_links": int(len(link))}
    (a.out_dir / f"{name}.json").write_text(json.dumps(info, indent=1) + "\n")
    print(f"ok      {out} : {len(ids)} segments upstream of {outlet} (inclusive), "
          f"{100 * len(ids) / len(link):.2f}% of {len(link)} links")
    return 0


if __name__ == "__main__":
    sys.exit(main())
