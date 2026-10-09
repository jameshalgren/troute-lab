# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy==2.3.3", "pandas==2.3.3", "pyarrow==21.0.0",
#   "pyogrio==0.11.1", "geopandas==1.1.1", "shapely==2.1.2", "pyproj==3.8.0",
#   "xarray==2025.9.0", "netcdf4==1.7.2",
#   "pmtiles==3.8.1", "mapbox-vector-tile==2.2.0",
# ]
# ///
"""Step 2 of the basin-explorer data build: map tiles, width functions, boxes, outlets.

Needs step 1 (build_codes.py) to have written explorer/data/rivers.json and
data/explorer/segment_attrs.parquet. See explorer/DATA_CONTRACT.md for the schemas.

Inputs:  NWM v3 hydrofabric geodatabase (download from https://water.noaa.gov/about/nwm),
         passed as --gdb or env var NWM_HYDROFABRIC_GDB; layers nwm_reaches_{conus,alaska,
         hawaii,puertorico} (field ID = NWM feature_id = RouteLink link) and
         nwm_waterbodies_{conus,alaska,hawaii} (there is no Puerto Rico waterbody layer).
         data/RouteLink_{CONUS,AK,HI,PRVI}.nc (sizes of all networks for the histograms)
Outputs: explorer/data/widths.json, bboxes.json, outlets.geojson   (web data bundle)
         explorer/data/flowlines_overview.pmtiles (CONUS) and
         flowlines_overview_other.pmtiles (AK, HI, PRVI)                (web data bundle; each <= ~15 MB)
         explorer/data/flowlines.pmtiles                           (gitignored)
         data/explorer/flow.fgb, flow_overview.fgb, waterbodies.fgb     (gitignored scratch)
Needs:   tippecanoe >= 2.17 on PATH (PMTiles output), e.g. `brew install tippecanoe`
Usage:   NWM_HYDROFABRIC_GDB=/path/to/NWM_v3_hydrofabric.gdb uv run explorer/scripts/build_map_data.py
         [--skip-extract]  reuse data/explorer/*.fgb from an earlier run
         [--skip-tiles]    only write the JSON products
"""
import argparse
import gzip
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "explorer" / "data"
SCRATCH = ROOT / "data" / "explorer"
ATTRS = SCRATCH / "segment_attrs.parquet"
DOMAINS = ["CONUS", "AK", "HI", "PRVI"]
ROUTELINK = {d: ROOT / "data" / f"RouteLink_{d}.nc" for d in DOMAINS}
REACH_LAYER = {"CONUS": "nwm_reaches_conus", "AK": "nwm_reaches_alaska", "HI": "nwm_reaches_hawaii",
               "PRVI": "nwm_reaches_puertorico"}
WB_LAYERS = ["nwm_waterbodies_conus", "nwm_waterbodies_alaska", "nwm_waterbodies_hawaii"]
MAX_BINS = 300

# Minimum Strahler order shown from each zoom on (zoom >= key -> order >= value).
FULL_ZOOMS = (3, 12)
# CONUS and AK (dm 0, 1) use the large-river thresholds; the islands (HI, PRVI; dm 2, 3;
# max order 5 and 6) are small, so lower orders are kept from lower zooms.
FULL_ORDER_BY_ZOOM = {(0, 1): {3: 7, 5: 6, 6: 5, 7: 4, 8: 3, 9: 1}, (2, 3): {3: 4, 5: 3, 6: 2, 7: 1}}
OVERVIEW_ZOOMS = (3, 8)
OVERVIEW_ORDER_BY_ZOOM = {(0, 1): {3: 7, 5: 6, 7: 5}, (2, 3): {3: 4, 5: 3, 7: 1}}
OVERVIEW_MIN_ORDER = {dm: min(v.values()) for k, v in OVERVIEW_ORDER_BY_ZOOM.items() for dm in k}
WATERBODY_MINZOOM = 6


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:7.1f}s] {msg}", flush=True)


# ---------------------------------------------------------------- tree helpers
def load_nodes():
    return json.loads((OUT / "rivers.json").read_text())["nodes"]


def subtree_codes(nodes):
    """code -> set of codes in its subtree (sub-rivers only; networks use net == code)."""
    kids = {}
    for nd in nodes:
        if nd["kind"] == "sub" and nd["parent"] is not None:
            kids.setdefault(nd["parent"], []).append(nd["code"])
    out = {}
    for nd in nodes:
        if nd["kind"] != "sub":
            continue
        seen, stack = set(), [nd["code"]]
        while stack:
            c = stack.pop()
            if c not in seen:
                seen.add(c)
                stack.extend(kids.get(c, []))
        out[nd["code"]] = seen
    return out


def node_masks(nodes, attrs):
    """Yield (node, boolean mask over attrs rows) for every node in rivers.json."""
    net = attrs["net"].to_numpy()
    river = attrs["river"].to_numpy()
    subs = subtree_codes(nodes)
    for nd in nodes:
        if nd["kind"] == "network":
            yield nd, net == nd["code"]
        else:
            yield nd, np.isin(river, np.fromiter(subs[nd["code"]], dtype=river.dtype))


# ---------------------------------------------------------------- JSON products
def network_sizes(dom):
    """Segment counts of every independent network of a domain, largest first (from RouteLink)."""
    import xarray as xr
    ds = xr.open_dataset(ROUTELINK[dom])
    link = ds["link"].values.astype(np.int64)
    to = ds["to"].values.astype(np.int64)
    down = pd.Series(np.arange(len(link)), index=link).reindex(to).to_numpy()
    root = np.where(np.isnan(down), np.arange(len(link)), np.nan_to_num(down, nan=0)).astype(np.int64)
    while True:  # pointer jumping: root[i] -> outlet of i
        nxt = root[root]
        if np.array_equal(nxt, root):
            break
        root = nxt
    counts = np.bincount(root, minlength=len(link))
    sizes = np.sort(counts[np.isnan(down)])[::-1]
    return [int(s) for s in sizes]


def build_json(nodes, attrs, bounds):
    d_reach = attrs["d_reach"].to_numpy()
    d_of_fid = pd.Series(d_reach, index=attrs["feature_id"].to_numpy())
    widths, bboxes = {}, {}
    for nd, m in node_masks(nodes, attrs):
        c = str(nd["code"])
        d0 = int(d_of_fid[nd["feature_id"]]) if nd["kind"] == "sub" else 0
        rel = d_reach[m] - d0
        if len(rel) == 0:
            continue
        assert rel.min() >= 0, (c, rel.min())
        max_d = int(rel.max())
        b = max(1, math.ceil((max_d + 1) / MAX_BINS))
        counts = np.bincount(rel // b)
        widths[c] = {"bin": b, "d0": d0, "max_d": max_d, "counts": [int(x) for x in counts]}
        bb = bounds[m]
        bboxes[c] = [round(float(bb[:, 0].min()), 4), round(float(bb[:, 1].min()), 4),
                     round(float(bb[:, 2].max()), 4), round(float(bb[:, 3].max()), 4)]
    by_dom = {d: network_sizes(d) for d in DOMAINS}
    sizes = by_dom["CONUS"]
    widths["_networks"] = {"sizes": sizes, "by_domain": by_dom}
    (OUT / "widths.json").write_text(json.dumps(widths, separators=(",", ":")))
    (OUT / "bboxes.json").write_text(json.dumps(bboxes, separators=(",", ":")))

    feats = []
    for nd in nodes:
        lat = nd.get("outlet_lat") if nd["kind"] == "network" else nd.get("mouth_lat")
        lon = nd.get("outlet_lon") if nd["kind"] == "network" else nd.get("mouth_lon")
        if lat is None or lon is None:
            continue
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                      "properties": {"code": nd["code"], "name": nd["name"], "kind": nd["kind"], "dom": nd["dom"]}})
    (OUT / "outlets.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}, separators=(",", ":")))
    log(f"widths.json {len(widths) - 1} codes; _networks " + ", ".join(
        f"{d} {len(v):,} (sum {sum(v):,})" for d, v in by_dom.items()) + f"; bboxes {len(bboxes)}; outlets {len(feats)}")
    return widths


# ---------------------------------------------------------------- geometry
def extract(gdb, attrs):
    import geopandas as gpd
    import pyogrio
    import shapely

    parts = []
    for dom in DOMAINS:
        g = pyogrio.read_dataframe(gdb, layer=REACH_LAYER[dom], columns=["ID"], use_arrow=True)
        log(f"read {len(g):,} reaches from {REACH_LAYER[dom]}, CRS {g.crs.to_string()}")
        parts.append(g.to_crs(4326))
    g = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=4326)
    g = g.rename(columns={"ID": "id"})
    g["id"] = g["id"].astype(np.int64)
    a = attrs.set_index("feature_id")
    assert a.index.is_unique, "feature_ids must be unique across domains"
    missing = (~g["id"].isin(a.index)).sum()
    extra = len(a) - g["id"].isin(a.index).sum()
    log(f"join: {missing} reaches without attrs; {extra} attr rows without geometry")
    a = a.reindex(g["id"].to_numpy())
    g["n"] = a["net"].fillna(0).astype(np.int32).to_numpy()
    g["r"] = a["river"].fillna(0).astype(np.int32).to_numpy()
    g["o"] = a["order"].fillna(0).astype(np.int32).to_numpy()
    g["d"] = a["d_reach"].fillna(-1).astype(np.int32).to_numpy()
    dmv = a["dom"].fillna(0).astype(np.int32).to_numpy()
    g["dm"] = pd.array(dmv, dtype="Int32")           # absent for CONUS (keeps the tiles small)
    g.loc[dmv == 0, "dm"] = pd.NA
    # upstream interval: everything upstream of a segment has p in [p, p + z) (build_codes.py)
    g["p"] = a["p"].fillna(-1).astype(np.int32).to_numpy()
    g["z"] = a["z"].fillna(0).astype(np.int32).to_numpy()
    # x: 1 = outside the U.S., 2 = on the international boundary (absent = inside)
    tb = a["tb"].fillna(0).astype(np.int32).to_numpy()
    g["x"] = pd.array(np.where(tb > 0, tb, 0), dtype="Int32")
    g.loc[tb == 0, "x"] = pd.NA
    # h: 1 = hydrography source other than the domain's NHDPlus (absent = NHDPlus)
    xb = a["xb"].fillna(0).astype(np.int32).to_numpy()
    g["h"] = pd.array(xb, dtype="Int32")
    g.loc[xb == 0, "h"] = pd.NA
    g = g[["id", "n", "r", "o", "d", "dm", "p", "z", "x", "h", "geometry"]]
    g = g[~g.geometry.is_empty & g.geometry.notna()]
    # no reach may span the antimeridian (Alaska): a lon span > 180 degrees would mean it does
    b = shapely.bounds(g.geometry.values)
    span = int((b[:, 2] - b[:, 0] > 180).sum())
    log(f"reaches spanning more than 180 degrees of longitude (antimeridian): {span}")
    assert span == 0
    bnds = pd.DataFrame(b, index=g["id"].to_numpy().astype(np.int64))
    bnds = bnds.reindex(attrs["feature_id"].to_numpy())
    fill = np.column_stack([attrs["lon"], attrs["lat"], attrs["lon"], attrs["lat"]])
    bounds = np.where(np.isnan(bnds.to_numpy()), fill, bnds.to_numpy())
    np.save(SCRATCH / "seg_bounds.npy", bounds)

    for p in ["flow.fgb", "flow_overview.fgb", "flow_overview_other.fgb"]:
        (SCRATCH / p).unlink(missing_ok=True)
    pyogrio.write_dataframe(g, SCRATCH / "flow.fgb", driver="FlatGeobuf")
    # overviews stay small (web data bundle): no upstream-interval / hydrography-source fields; one file
    # for CONUS and one for AK + HI + PRVI, so each stays under ~15 MB
    dm = g["dm"].fillna(0).astype(int)
    keep = g["o"].to_numpy() >= dm.map(OVERVIEW_MIN_ORDER).to_numpy()
    cols = ["id", "n", "r", "o", "d", "dm", "x", "geometry"]
    pyogrio.write_dataframe(g.loc[keep & (dm == 0).to_numpy(), cols], SCRATCH / "flow_overview.fgb", driver="FlatGeobuf")
    pyogrio.write_dataframe(g.loc[keep & (dm > 0).to_numpy(), cols], SCRATCH / "flow_overview_other.fgb", driver="FlatGeobuf")
    log("wrote flow.fgb, flow_overview.fgb, flow_overview_other.fgb")

    ws = []
    for lay in WB_LAYERS:
        w = pyogrio.read_dataframe(gdb, layer=lay, columns=["ID"], use_arrow=True)
        w = w.to_crs(4326)
        w["geometry"] = shapely.force_2d(w.geometry.values)
        ws.append(gpd.GeoDataFrame({"id": w["ID"].astype(np.int64)}, geometry=w.geometry, crs=4326))
    w = gpd.GeoDataFrame(pd.concat(ws, ignore_index=True), crs=4326)
    (SCRATCH / "waterbodies.fgb").unlink(missing_ok=True)
    pyogrio.write_dataframe(w, SCRATCH / "waterbodies.fgb", driver="FlatGeobuf")
    log(f"wrote waterbodies.fgb ({len(w):,} polygons)")
    return bounds


# ---------------------------------------------------------------- tiles
def zoom_filter(by_domain):
    # dm is absent for CONUS features, so the CONUS/AK group is written as "not HI/PRVI"
    def dom_filter(doms):
        return ["in", "dm", *doms] if 0 not in doms else ["!in", "dm", *[d for d in (1, 2, 3) if d not in doms]]
    return ["any", *[["all", dom_filter(doms), [">=", "$zoom", z], [">=", "o", o]]
                     for doms, order_by_zoom in by_domain.items() for z, o in sorted(order_by_zoom.items())]]


def tippecanoe(out, layers, zooms, filters):
    # paths relative to the repo root (and cwd=ROOT): tippecanoe records its command line in
    # the file's metadata ("generator_options"), which must not carry local paths
    out.unlink(missing_ok=True)
    rel = lambda p: os.path.relpath(p, ROOT)
    cmd = ["tippecanoe", "-o", rel(out), "--force", "-Z", str(zooms[0]), "-z", str(zooms[1]),
           "--no-feature-limit", "--no-tile-size-limit", "--no-tile-stats",
           "-j", json.dumps(filters), "-T", "id:int", "-T", "n:int", "-T", "r:int", "-T", "o:int", "-T", "d:int",
           "-T", "p:int", "-T", "z:int", "-T", "x:int", "-T", "h:int", "-T", "dm:int",
           "--quiet"]
    for name, path in layers:
        cmd += ["-L", f"{name}:{rel(path)}"]
    log(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    log(f"{out.name}: {out.stat().st_size / 1e6:.1f} MB")


def build_tiles():
    if shutil.which("tippecanoe") is None:
        sys.exit("tippecanoe not found on PATH (brew install tippecanoe)")
    v = subprocess.run(["tippecanoe", "--version"], capture_output=True, text=True)
    log(f"tippecanoe: {(v.stdout or v.stderr).strip()}")
    tippecanoe(OUT / "flowlines.pmtiles",
               [("flow", SCRATCH / "flow.fgb"), ("waterbodies", SCRATCH / "waterbodies.fgb")],
               FULL_ZOOMS, {"flow": zoom_filter(FULL_ORDER_BY_ZOOM),
                            "waterbodies": [">=", "$zoom", WATERBODY_MINZOOM]})
    tippecanoe(OUT / "flowlines_overview.pmtiles", [("flow", SCRATCH / "flow_overview.fgb")],
               OVERVIEW_ZOOMS, {"flow": zoom_filter(OVERVIEW_ORDER_BY_ZOOM)})
    tippecanoe(OUT / "flowlines_overview_other.pmtiles", [("flow", SCRATCH / "flow_overview_other.fgb")],
               OVERVIEW_ZOOMS, {"flow": zoom_filter(OVERVIEW_ORDER_BY_ZOOM)})


# ---------------------------------------------------------------- validation
def tile_xy(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def read_tile(path, z, x, y):
    import mapbox_vector_tile
    from pmtiles.reader import MmapSource, Reader
    with open(path, "rb") as f:
        data = Reader(MmapSource(f)).get(z, x, y)
    if data is None:
        return {}
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return mapbox_vector_tile.decode(data)


def validate(nodes, attrs, widths, tiles):
    ok = True
    by = {nd["code"]: nd for nd in nodes}
    mo = next(nd for nd in nodes if nd["kind"] == "sub" and nd["name"] == "Missouri")
    tot = sum(widths[str(mo["code"])]["counts"])
    print(f"  Missouri ({mo['code']}): width total {tot:,} vs n_segments {mo['n_segments']:,}",
          "OK" if tot == mo["n_segments"] else "MISMATCH")
    ok &= tot == mo["n_segments"]
    ms = widths["1"]
    print(f"  Mississippi: max_d {ms['max_d']} (+1 inclusive = {ms['max_d'] + 1}; "
          f"longest_path_reaches {by[1]['longest_path_reaches']})")
    ok &= ms["max_d"] + 1 == by[1]["longest_path_reaches"]
    bad = [nd["code"] for nd in nodes if str(nd["code"]) in widths
           and sum(widths[str(nd["code"])]["counts"]) != nd["n_segments"]]
    missing = [nd["code"] for nd in nodes if str(nd["code"]) not in widths]
    print(f"  width totals == n_segments for {len(nodes) - len(bad) - len(missing)}/{len(nodes)} nodes; "
          f"mismatches: {bad[:20]}; without width function: {missing[:20]}")
    ok &= not bad and not missing
    for dom, sizes in widths["_networks"]["by_domain"].items():
        top = [nd["n_segments"] for nd in nodes if nd["kind"] == "network" and nd["dom"] == dom]
        same = sizes[:len(top)] == sorted(top, reverse=True)
        print(f"  _networks {dom}: {len(sizes):,} networks, sum {sum(sizes):,}; top {len(top)} match rivers.json: {same}")
        ok &= same
    pu = attrs["p"].is_unique
    print(f"  preorder p unique across {len(attrs):,} segments of all domains: {pu}")
    ok &= bool(pu)
    if not tiles:
        return ok
    a = attrs.set_index("feature_id")
    # one large river per domain: Missouri and Mississippi (CONUS), the largest network of AK, HI, PRVI
    probes = [mo["feature_id"], by[1]["feature_id"]] + [by[b + 1]["feature_id"] for b in (10000, 20000, 30000) if b + 1 in by]
    for path, z in [(OUT / "flowlines.pmtiles", 10), (OUT / "flowlines.pmtiles", 12),
                    (OUT / "flowlines_overview.pmtiles", 8), (OUT / "flowlines_overview_other.pmtiles", 8)]:
        if not path.exists():
            continue
        for fid in probes:
            row = a.loc[fid]
            if "overview" in path.name and (int(row["dom"]) == 0) != (path.name == "flowlines_overview.pmtiles"):
                continue
            x, y = tile_xy(float(row["lon"]), float(row["lat"]), z)
            t = read_tile(path, z, x, y)
            feats = t.get("flow", {}).get("features", [])
            hit = [f["properties"] for f in feats if f["properties"].get("id") == fid]
            tbv = int(row["tb"])
            want = {"id": fid, "n": int(row["net"]), "r": int(row["river"]), "o": int(row["order"]),
                    "d": int(row["d_reach"]), "dm": int(row["dom"]), "p": int(row["p"]), "z": int(row["z"])}
            good = bool(hit) and all({k: v for k, v in h.items() if k not in ("x", "h")} ==
                                     {k: v for k, v in want.items() if k in h and not (k == "dm" and v == 0)}
                                     and h.get("x", 0) == tbv and h.get("dm", 0) == want["dm"] for h in hit)
            print(f"  {path.name} z{z}/{x}/{y}: {len(feats)} features; segment {fid} -> {hit[:1]} "
                  f"{'OK' if good else 'MISMATCH, want ' + str(want)}")
            ok &= good
            props = pd.DataFrame([f["properties"] for f in feats])
            ref = a.reindex(props["id"])
            agree = ((props["n"].to_numpy() == ref["net"].to_numpy()) & (props["r"].to_numpy() == ref["river"].to_numpy())
                     & (props["o"].to_numpy() == ref["order"].to_numpy()) & (props["d"].to_numpy() == ref["d_reach"].to_numpy())
                     & (props.get("dm", pd.Series(0, index=props.index)).fillna(0).to_numpy() == ref["dom"].to_numpy())
                     & (props.get("x", pd.Series(0, index=props.index)).fillna(0).to_numpy() == ref["tb"].to_numpy()))
            print(f"    all {len(props)} features in tile agree with segment_attrs: {bool(agree.all())}; "
                  f"min order {int(props['o'].min())}")
            ok &= bool(agree.all())
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gdb", default=os.environ.get("NWM_HYDROFABRIC_GDB") or str(ROOT / "data" / "NWM_v3_hydrofabric.gdb"),
                    help="NWM v3 hydrofabric .gdb (default: $NWM_HYDROFABRIC_GDB)")
    ap.add_argument("--skip-extract", action="store_true")
    ap.add_argument("--skip-tiles", action="store_true")
    args = ap.parse_args()

    nodes = load_nodes()
    attrs = pd.read_parquet(ATTRS)
    log(f"{len(nodes)} nodes; {len(attrs):,} segments")
    if args.skip_extract:
        bounds = np.load(SCRATCH / "seg_bounds.npy")
    else:
        if not args.gdb or not Path(args.gdb).exists():
            sys.exit("set NWM_HYDROFABRIC_GDB or pass --gdb (NWM v3 hydrofabric geodatabase)")
        bounds = extract(args.gdb, attrs)
    widths = build_json(nodes, attrs, bounds)
    if not args.skip_tiles:
        build_tiles()
    log("validation:")
    ok = validate(nodes, attrs, widths, tiles=not args.skip_tiles)
    for p in ["widths.json", "bboxes.json", "outlets.geojson", "flowlines_overview.pmtiles",
              "flowlines_overview_other.pmtiles", "flowlines.pmtiles"]:
        if (OUT / p).exists():
            print(f"  {p}: {(OUT / p).stat().st_size / 1e6:.2f} MB")
    log("done" if ok else "done WITH VALIDATION FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
