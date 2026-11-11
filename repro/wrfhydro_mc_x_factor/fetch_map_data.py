"""Fetch the inputs of the Potomac map figure (figure only; no result depends on them).

AI-written (Claude, 2026-10-31). Writes into data/map/ (untrusted downloads; nothing in it is
executed) and records each file's request and SHA-256 in data/map/sources.json.
- State outlines: Natural Earth 1:110m admin-1 (states/provinces, lakes cut out), pinned to the
  same natural-earth-vector commit as ../network_stats. A changed hash is an ERROR.
- Basin outline: USGS NLDI basin for NWM/NHDPlusV2 COMID 4539621 (the Potomac outlet). Live
  service: a changed hash is a WARNING only.
- Elevation: USGS 3D Elevation Program (3DEP) Bare Earth DEM, ImageServer exportImage, raw
  float32 elevation in UTM 18N (EPSG:32618) at 150 m over the basin. Live mosaic: a changed
  hash is a WARNING only (values drift as USGS adds lidar).
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAP = HERE / "data" / "map"
UA = {"User-Agent": "byu-troute-paper"}
NE_SHA = "117488dc884bad03366ff727eca013e434615127"  # natural-earth-vector, as ../network_stats
STATES = (f"https://raw.githubusercontent.com/nvkelso/natural-earth-vector/{NE_SHA}/geojson/"
          "ne_110m_admin_1_states_provinces_lakes.geojson")
BASIN = "https://api.water.usgs.gov/nldi/linked-data/comid/4539621/basin"
DEM_SERVICE = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
# DEM grid in EPSG:32618: the NLDI basin's extent (89,945-386,959 E; 4,194,243-4,457,474 N,
# checked 2026-10-31) plus 6 km, snapped outward to 150 m: 2,061 x 1,836 pixels
DEM_RES = 150.0
DEM_BBOX = (83850.0, 4188150.0, 393000.0, 4463550.0)   # xmin, ymin, xmax, ymax


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def get(url: str, timeout: int = 300) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if attempt == 3:
                raise
            print(f"retry   {url[:70]}… ({e})")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def main() -> int:
    MAP.mkdir(parents=True, exist_ok=True)
    srcf = MAP / "sources.json"
    known = json.loads(srcf.read_text()) if srcf.exists() else {}
    xmin, ymin, xmax, ymax = DEM_BBOX
    nx, ny = int(round((xmax - xmin) / DEM_RES)), int(round((ymax - ymin) / DEM_RES))
    dem_q = {"bbox": f"{xmin},{ymin},{xmax},{ymax}", "bboxSR": "32618", "imageSR": "32618",
             "size": f"{nx},{ny}", "format": "tiff", "pixelType": "F32", "noData": "-999999",
             "interpolation": "RSP_BilinearInterpolation", "renderingRule": '{"rasterFunction":"None"}',
             "adjustAspectRatio": "false", "f": "image"}
    items = [("states.geojson", STATES, True),
             ("basin.geojson", BASIN, False),
             ("dem_3dep_utm18n_150m.tif", DEM_SERVICE + "?" + urllib.parse.urlencode(dem_q), False)]
    status = 0
    for name, url, pinned in items:
        f = MAP / name
        if f.exists() and name in known and sha256(f.read_bytes()) == known[name]["sha256"]:
            print(f"ok      {name} (sha256 verified)")
            continue
        data = get(url)
        if name.endswith(".tif") and not data[:4] in (b"II*\x00", b"MM\x00*"):
            print(f"ERROR   {name}: the service did not return a TIFF: {data[:200]!r}")
            return 1
        h = sha256(data)
        if name in known and known[name]["sha256"] != h:
            msg = f"{name}: sha256 changed ({known[name]['sha256'][:12]} -> {h[:12]})"
            if pinned:
                print("ERROR   " + msg)
                return 1
            print("WARNING " + msg + "; live service, figure only")
        f.write_bytes(data)
        known[name] = {"url": url, "sha256": h, "bytes": len(data), "retrieved": time.strftime("%Y-%m-%d"),
                       "pinned": pinned}
        if name.endswith(".tif"):
            known[name].update({"crs": "EPSG:32618", "bbox": list(DEM_BBOX), "res_m": DEM_RES, "shape": [ny, nx]})
        print(f"ok      {name} ({len(data) / 1e6:.1f} MB)")
    srcf.write_text(json.dumps(known, indent=2) + "\n")
    return status


if __name__ == "__main__":
    sys.exit(main())
