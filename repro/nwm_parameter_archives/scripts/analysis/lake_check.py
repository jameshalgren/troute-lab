# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "netCDF4"]
# ///
"""Match LAKEPARM lake_id sets against RouteLink NHDWaterbodyComID sets and link IDs.
Supports §4 LAKEPARM counts, key finding "v3.0 LAKEPARM_CONUS (5,782 lakes) = the v3.0 and
v3.1.6/3.1.7 RouteLink waterbody set", and "in v2.1, four lake IDs are also link IDs".
Needs the full RouteLink/LAKEPARM files (not in this folder).
Usage: uv run scripts/analysis/lake_check.py RL_v30=RouteLink_CONUS.nc LP_v30=LAKEPARM_CONUS.nc [RL_x=... LP_y=...]
"""
import sys, numpy as np, netCDF4 as nc
rl = {k: v for k, v in (a.split("=") for a in sys.argv[1:] if a.startswith("RL_"))}
lp = {k: v for k, v in (a.split("=") for a in sys.argv[1:] if a.startswith("LP_"))}
lakes = {}
for k, p in lp.items():
    with nc.Dataset(p) as d: lakes[k] = set(d["lake_id"][:].astype(np.int64).tolist())
    print(k, "n lake_id", len(lakes[k]))
for k, p in rl.items():
    with nc.Dataset(p) as d:
        wb = d["NHDWaterbodyComID"][:].astype(np.int64); link = set(d["link"][:].astype(np.int64).tolist())
    s = set(wb[wb > 0].tolist())
    print(k, "segments", len(link), "segments with WB>0", int((wb > 0).sum()), "distinct WB ids", len(s))
    for lk, L in lakes.items():
        print(f"   vs {lk}: WB not in lakes {len(s - L)}, lakes not in WB {len(L - s)}, lake ids that are link ids {len(L & link)}")
