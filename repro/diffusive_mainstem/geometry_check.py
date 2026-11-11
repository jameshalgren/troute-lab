"""Optional: confirm that RouteLink lat/lon are the along-line midpoints of NWM flowlines.

The screening matches segments to the National Waterway Network, eHydro footprints and
physiographic polygons by RouteLink `lat`/`lon`. This script checks what that point is,
using the NWM v3 channel hydrofabric (public: NWM_v3_channel_hydrofabric.gdb.tar.gz,
https://www.nohrsc.noaa.gov/pub/staff/keicher/NWM_live/web/data_tools/, 3.25 GB; not
downloaded by fetch_data.py). Point the environment variable NWM_HYDROFABRIC_GDB at an
extracted copy of the .gdb; the script is skipped if it is not set.

Reads the first N features of layer nwm_reaches_conus and reports the distance from the
RouteLink point to the line's start, end, along-line midpoint, and to the line itself.
Writes results/geometry_check.json.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pyogrio
import shapely

import indicators as I

HERE = Path(__file__).resolve().parent
N = 5000


def main() -> int:
    gdb = os.environ.get("NWM_HYDROFABRIC_GDB")
    out = HERE / "results" / "geometry_check.json"
    if not gdb or not Path(gdb).exists():
        print("SKIP geometry_check: NWM_HYDROFABRIC_GDB not set")
        return 0
    df = pyogrio.read_dataframe(gdb, layer="nwm_reaches_conus", max_features=N).to_crs(5070)
    rl = I.load_routelink(HERE / "data" / "RouteLink_CONUS.nc")
    pos = {int(l): i for i, l in enumerate(rl["link"])}
    keep = [pos.get(int(x), -1) for x in df["ID"]]
    df = df[[k >= 0 for k in keep]]
    idx = np.array([k for k in keep if k >= 0])
    import geopandas as gpd
    pts = gpd.GeoSeries(shapely.points(rl["lon"][idx], rl["lat"][idx]), crs=4269).to_crs(5070).to_numpy()
    lines = shapely.line_merge(df.geometry.to_numpy())
    single = shapely.get_type_id(lines) == 1
    start = shapely.get_point(lines, 0)
    end = shapely.get_point(lines, -1)
    mid = shapely.line_interpolate_point(lines, 0.5, normalized=True)
    d = {"start": shapely.distance(pts, start), "end": shapely.distance(pts, end),
         "midpoint": shapely.distance(pts, mid), "line": shapely.distance(pts, lines)}
    res = {"features_compared": int(single.sum()),
           **{f"median_m_to_{k}": round(float(np.nanmedian(v[single])), 3) for k, v in d.items()},
           **{f"p99_m_to_{k}": round(float(np.nanpercentile(v[single], 99)), 3) for k, v in d.items()}}
    out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
