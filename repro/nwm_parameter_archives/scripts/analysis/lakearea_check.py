# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "netCDF4"]
# ///
"""LAKEPARM LkArea for seven large US lakes vs their published surface areas (km²).
Supports §8 question 7 (LkArea is in km²; v2.1 values are 75-95 % of full-pool areas).
Picks the largest lake among the 3 lake centroids nearest each reference point.
Needs LAKEPARM files (not in this folder).
Usage: uv run scripts/analysis/lakearea_check.py LAKEPARM_CONUS.nc [more LAKEPARM files]
"""
import sys, numpy as np, netCDF4
# name, lat, lon, published surface area km2 (full pool unless noted)
known = [("Lake Mead",36.15,-114.45,640),("Lake Powell",37.07,-111.25,653),
         ("Lake Tahoe",39.09,-120.04,496),("Lake Okeechobee",26.95,-80.83,1891),
         ("Fort Peck Lake",47.75,-106.6,1010),("Lake Sakakawea",47.6,-102.2,1550),
         ("Lake Oahe",45.0,-100.4,1500)]
for path in sys.argv[1:]:
    ds = netCDF4.Dataset(path)
    lat, lon, area = ds["lat"][:], ds["lon"][:], ds["LkArea"][:]
    ids = ds["lake_id"][:]
    print(path.split("/")[-2], "| LkArea attrs:", {k: ds["LkArea"].getncattr(k) for k in ds["LkArea"].ncattrs()})
    for n, la, lo, ref in known:
        d = np.hypot(lat - la, (lon - lo) * np.cos(np.radians(la)))
        i = np.argsort(d)[:3]
        best = i[np.argmax(area[i])]  # largest lake among 3 nearest centroids
        print(f"  {n:16s} ref {ref:5d} km2 | lake_id {int(ids[best]):>10d} at ({float(lat[best]):.2f},{float(lon[best]):.2f}) dist {float(d[best]):.2f} deg | LkArea {float(area[best]):.2f}")
