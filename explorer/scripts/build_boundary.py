# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy==2.3.3", "pandas==2.3.3", "pyarrow==21.0.0",
#   "pyogrio==0.11.1", "geopandas==1.1.1", "shapely==2.1.2", "pyproj==3.7.2",
# ]
# ///
"""Step 0 of the basin-explorer data build: which channel lies outside the United States.

For every NWM v3 hydrofabric reach (all four domains) this computes the share of its line
geometry that lies outside the U.S., using the U.S. Census Bureau TIGER/Line 2024 state
polygons (union of all states, DC and territories). TIGER/Line state polygons follow the
international boundary through the Great Lakes and the border rivers and extend over
coastal water, so channel in a lake or an estuary is not counted as "outside".

Per segment (data/explorer/segment_boundary.parquet, gitignored):
  feature_id, dom (0 CONUS, 1 AK, 2 HI, 3 PRVI)
  out_frac   share of the reach's line length outside the U.S. polygon (0..1), measured
             in the domain's equal-area projection (CONUS EPSG:5070, AK EPSG:3338,
             HI ESRI:102007, PRVI EPSG:32161)
  band_frac  share of the line within BAND_M of the U.S. international boundary (the part
             of the U.S. polygon outline that lies inside a FOREIGN_BOX)
  status     "on"  (band_frac >= 0.5: the channel follows the boundary, e.g. the Rio
                    Grande, St. Lawrence, Rainy, St. Croix, Niagara/Detroit/St. Clair),
             "out" (not "on", out_frac > 0.5 and the midpoint in a FOREIGN_BOX), or
             "in"  (everything else)
  country    "Canada" / "Mexico" for status "out"
Segments outside the polygon but not in a FOREIGN_BOX (offshore beyond the TIGER/Line
water limit) are reported in the log and counted as "in" (they are not in another country).
Crossings are counted later (build_codes.py) only between "in" and "out" segments,
skipping "on" segments (hysteresis), so a border river that wiggles across the line is
not a crossing.

BAND_M = 500 m. Justification: NHDPlus V2 flowlines come from 1:100,000 NHD (National Map
Accuracy Standard: 90% of well-defined points within 0.02 in. = ~51 m), the boundary in
a border river is the deepest channel / middle of a channel that is itself 50-1,500 m wide
(Rio Grande to St. Lawrence) and has migrated since it was mapped, and NHDPlus draws the
river as one center line. 500 m absorbs these offsets on all the border rivers listed
above without reaching typical tributaries; the log also reports 250 m for sensitivity.

Inputs:  NWM v3 hydrofabric geodatabase ($NWM_HYDROFABRIC_GDB or --gdb): nwm_reaches_{conus,
         alaska,hawaii,puertorico}; TIGER/Line 2024 state shapefile, downloaded once into
         data/explorer/cache/census/ (gitignored) and recorded with URL, access date and
         SHA-256 in data/explorer/cache/sources.json.
Usage:   NWM_HYDROFABRIC_GDB=/path/to/NWM_v3_hydrofabric.gdb uv run explorer/scripts/build_boundary.py
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "explorer" / "cache"
SOURCES = CACHE / "sources.json"
OUT = ROOT / "data" / "explorer" / "segment_boundary.parquet"
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip"
TIGER_REL = "census/tl_2024_us_state.zip"
UA = "troute-paper-basin-explorer/1.0 (research build script; read-only)"

# domain: (gdb layer, projected CRS for lengths, lon/lat box used to clip the U.S. polygon)
DOMAINS = {
    "CONUS": ("nwm_reaches_conus", "EPSG:5070", (-135.0, 22.0, -55.0, 56.0)),
    "AK": ("nwm_reaches_alaska", "EPSG:3338", (-170.0, 50.0, -125.0, 72.0)),
    "HI": ("nwm_reaches_hawaii", "ESRI:102007", (-162.0, 17.0, -153.0, 24.0)),
    "PRVI": ("nwm_reaches_puertorico", "EPSG:32161", (-68.5, 17.0, -63.5, 19.5)),
}
DOM_INDEX = {"CONUS": 0, "AK": 1, "HI": 2, "PRVI": 3}
# Where "outside the U.S. polygon" can only mean Canada or Mexico (lon/lat boxes on the
# reach midpoint). Outside these boxes, a reach outside the polygon is offshore water.
# Canada: north of the 41.6 N (Lake Erie) latitude in CONUS; any AK reach east of 141.2 W
# or south-east of the panhandle line. Mexico: south of 33 N and west of 96 W.
FOREIGN_BOX = {
    "CONUS": [(-141.0, 41.6, -52.0, 60.0, "Canada"), (-118.0, 14.0, -96.0, 33.0, "Mexico")],
    "AK": [(-141.2, 54.0, -120.0, 72.0, "Canada")],
    "HI": [], "PRVI": [],
}
MAX_VERTS = 4000  # quadtree leaf size for the U.S. polygon
BAND_M = 500.0    # half-width of the "on the boundary" band (see docstring)
BAND_ALT_M = 250.0


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:7.1f}s] {msg}", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def cached(rel: str, url: str) -> Path:
    p = CACHE / rel
    src = json.loads(SOURCES.read_text()) if SOURCES.exists() else {}
    if p.exists():
        if rel in src and src[rel]["sha256"] != sha256(p):
            sys.exit(f"ERROR: {p} does not match the SHA-256 recorded in {SOURCES}")
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        log(f"fetch {url}")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=600) as r, open(p.with_suffix(".part"), "wb") as f:
            while b := r.read(1 << 20):
                f.write(b)
        p.with_suffix(".part").rename(p)
    if rel not in src:
        src[rel] = {"url": url, "accessed": dt.date.today().isoformat(), "sha256": sha256(p),
                    "bytes": p.stat().st_size,
                    "note": "U.S. Census Bureau TIGER/Line Shapefiles 2024, State and Equivalent Entity "
                            "(https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html)"}
        SOURCES.write_text(json.dumps(src, indent=1, sort_keys=True))
    return p


def quadtree(geom, box, out_full, out_part, depth=0):
    """Split a (multi)polygon into leaves: boxes entirely inside (full) or pieces with at
    most MAX_VERTS vertices (part). Empty boxes are dropped."""
    import shapely
    if geom.is_empty:
        return
    x0, y0, x1, y1 = box
    cell = shapely.box(x0, y0, x1, y1)
    if shapely.get_num_coordinates(geom) <= MAX_VERTS or depth > 18:
        if abs(geom.area - cell.area) < 1e-9 * max(cell.area, 1.0):
            out_full.append(cell)
        else:
            out_part.append(geom)
        return
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    for b in ((x0, y0, xm, ym), (xm, y0, x1, ym), (x0, ym, xm, y1), (xm, ym, x1, y1)):
        quadtree(shapely.make_valid(shapely.clip_by_rect(geom, *b)), b, out_full, out_part, depth + 1)


def inside_length(lines, full, part):
    """Length of each line inside the union of `full` boxes and `part` pieces."""
    import shapely
    lines = np.asarray(lines)
    total = shapely.length(lines)
    inside = np.zeros(len(lines))
    tp = shapely.STRtree(part)
    li, pj = tp.query(lines, predicate="intersects")
    if len(li):
        inside += np.bincount(li, weights=shapely.length(shapely.intersection(lines[li], np.asarray(part)[pj])),
                              minlength=len(lines))
    if full:
        tf = shapely.STRtree(full)
        li, fj = tf.query(lines, predicate="intersects")
        if len(li):
            inside += np.bincount(li, weights=shapely.length(shapely.intersection(lines[li], np.asarray(full)[fj])),
                                  minlength=len(lines))
    return total, np.minimum(inside, total)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gdb", default=os.environ.get("NWM_HYDROFABRIC_GDB") or str(ROOT / "data" / "NWM_v3_hydrofabric.gdb"))
    args = ap.parse_args()
    if not args.gdb or not Path(args.gdb).exists():
        sys.exit("set NWM_HYDROFABRIC_GDB or pass --gdb (NWM v3 hydrofabric geodatabase)")
    import geopandas as gpd
    import pyogrio
    import shapely

    z = cached(TIGER_REL, TIGER_URL)
    st = gpd.read_file(f"zip://{z}")
    log(f"TIGER/Line states: {len(st)} features, CRS {st.crs.to_string()}")
    us = shapely.union_all(shapely.make_valid(st.to_crs(4269).geometry.values))
    frames, report = [], {}
    for dom, (layer, crs, bbox) in DOMAINS.items():
        g = pyogrio.read_dataframe(args.gdb, layer=layer, columns=["ID"], use_arrow=True)
        g = g[g.geometry.notna() & ~g.geometry.is_empty].to_crs(4269)
        log(f"{dom}: {len(g):,} reaches")
        usd = shapely.make_valid(shapely.clip_by_rect(us, *bbox))
        usd = gpd.GeoSeries([usd], crs=4269).to_crs(crs).iloc[0]
        lines = shapely.force_2d(g.to_crs(crs).geometry.values)
        b = shapely.bounds(usd)
        pad = 1000.0
        full, part = [], []
        quadtree(usd, (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad), full, part)
        log(f"{dom}: U.S. polygon split into {len(full):,} full cells and {len(part):,} pieces")
        tot, ins = inside_length(lines, full, part)
        out_frac = np.where(tot > 0, np.clip(1 - ins / np.where(tot > 0, tot, 1), 0, 1), 0.0)
        out_frac[out_frac < 1e-6] = 0.0
        mid = shapely.line_interpolate_point(g.geometry.values, 0.5, normalized=True)
        mx, my = shapely.get_x(mid), shapely.get_y(mid)
        inbox = np.zeros(len(g), bool)
        country = np.full(len(g), "", object)
        for (x0, y0, x1, y1, name) in FOREIGN_BOX[dom]:
            m = (mx >= x0) & (mx <= x1) & (my >= y0) & (my <= y1)
            inbox |= m
            country[m & (country == "")] = name
        # band along the international boundary: U.S. outline inside the foreign boxes
        band = {}
        if FOREIGN_BOX[dom]:
            outline = shapely.boundary(shapely.clip_by_rect(us, *bbox))
            boxes = shapely.union_all([shapely.box(x0, y0, x1, y1) for x0, y0, x1, y1, _ in FOREIGN_BOX[dom]])
            intl = gpd.GeoSeries([shapely.intersection(outline, boxes)], crs=4269).to_crs(crs).iloc[0]
            intl = shapely.simplify(intl, 10.0)
            log(f"{dom}: international outline {shapely.length(intl) / 1000:,.0f} km (incl. Great Lakes)")
            for w in (BAND_M, BAND_ALT_M):
                bp = shapely.buffer(intl, w)
                bb = shapely.bounds(bp)
                bf, bpart = [], []
                quadtree(bp, (bb[0] - 10, bb[1] - 10, bb[2] + 10, bb[3] + 10), bf, bpart)
                _, inb = inside_length(lines, bf, bpart)
                band[w] = np.where(tot > 0, inb / np.where(tot > 0, tot, 1), 0.0)
        band_frac = band.get(BAND_M, np.zeros(len(g)))
        on = band_frac >= 0.5
        outside = out_frac > 0.5
        foreign = outside & inbox & ~on
        offshore = outside & ~inbox
        status = np.where(on, "on", np.where(foreign, "out", "in"))
        report[dom] = {"segments": int(len(g)), "any_part_outside": int((out_frac > 0).sum()),
                       "majority_outside": int(outside.sum()), "on_boundary": int(on.sum()),
                       "on_boundary_at_250m": int((band.get(BAND_ALT_M, np.zeros(len(g))) >= 0.5).sum()),
                       "out": int(foreign.sum()),
                       "outside_not_foreign_offshore": int(offshore.sum()),
                       "out_by_country": {c: int((foreign & (country == c)).sum()) for c in sorted(set(country[foreign]))}}
        log(f"{dom}: {report[dom]}")
        if offshore.any():
            ex = g.loc[offshore, "ID"].head(5).tolist()
            log(f"{dom}: outside the polygon but not foreign (offshore), e.g. {ex} at "
                f"{[(round(float(a), 3), round(float(c), 3)) for a, c in zip(my[offshore][:5], mx[offshore][:5])]}")
        frames.append(pd.DataFrame({"feature_id": g["ID"].astype(np.int64).to_numpy(), "dom": DOM_INDEX[dom],
                                    "out_frac": out_frac.astype(np.float32), "band_frac": band_frac.astype(np.float32),
                                    "status": status, "country": np.where(foreign, country, "")}))
    df = pd.concat(frames, ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    meta = {"source": TIGER_URL, "sha256": sha256(z), "band_m": BAND_M,
            "rule": "on = band_frac >= 0.5; out = not on, out_frac > 0.5, midpoint in FOREIGN_BOX; else in",
            "report": report}
    (OUT.with_suffix(".json")).write_text(json.dumps(meta, indent=1))
    log(f"wrote {OUT} ({len(df):,} rows) and {OUT.with_suffix('.json').name}")


if __name__ == "__main__":
    main()
