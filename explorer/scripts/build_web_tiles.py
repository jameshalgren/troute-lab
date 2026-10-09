# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "numpy==2.3.3", "pandas==2.3.3", "pyarrow==21.0.0",
#   "pmtiles==3.8.1", "mapbox-vector-tile==2.2.0",
# ]
# ///
"""Web tileset for the hosted basin explorer (GitHub Pages: at most 100 MB per file).

Same features as the full tiles (flowlines.pmtiles), split into files that each stay
under 95 MB:

  web_low.pmtiles        z3-8, all domains, the full tiles' order-by-zoom filter
                         (FULL_ORDER_BY_ZOOM in build_map_data.py) and waterbodies from z6
  web_<region>.pmtiles   z9-10, every segment and waterbody, one file per region; a region
                         is a band of z9 tile columns (REGIONS below), so every z9 and z10
                         tile is in exactly one file (no overlap, no duplicate features at
                         the seams). The map overzooms the z10 tiles past zoom 10.
  tiles.json             manifest read by index.html: per file its zoom range, bounds,
                         size and SHA-256; "hidefrom" = zoom from which the page hides the
                         file's layers (web_low hides at 9, where the regional files start)

Method: one tippecanoe run (z3-10, the same command as the full tiles but -z 10) into
data/explorer/web/_z3_10.pmtiles, then its tiles are copied unchanged into the files
above (by zoom, and for z9-10 by the z9 column x >> (z - 9)). Every attribute is kept
(id n r o d p z x h dm, integers), so upstream-of-point works on the hosted site.

Inputs:  data/explorer/flow.fgb, waterbodies.fgb (build_map_data.py)
Outputs: data/explorer/web/{tiles.json, web_*.pmtiles}   (gitignored; published as the
         explorer data bundle, scripts/export_public.py --bundle explorer)
Usage:   uv run explorer/scripts/build_web_tiles.py [--skip-tippecanoe]
         --skip-tippecanoe reuses data/explorer/web/_z3_10.pmtiles from an earlier run.
Needs:   tippecanoe >= 2.17 on PATH (built with 2.79.0)
"""
import argparse
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_map_data import (FULL_ORDER_BY_ZOOM, ROOT, SCRATCH, WATERBODY_MINZOOM,  # noqa: E402
                            log, tippecanoe, zoom_filter)
from pmtiles.reader import MmapSource, Reader, all_tiles  # noqa: E402
from pmtiles.tile import zxy_to_tileid  # noqa: E402
from pmtiles.writer import Writer  # noqa: E402

WEB = SCRATCH / "web"
SOURCE = WEB / "_z3_10.pmtiles"
ZOOMS = (3, 10)
LOW_MAX = 8            # web_low: z3-8; the regional files: z9-10
SPLIT_Z = 9            # regions are bands of z9 tile columns [x0, x1)
# Column bands chosen (2026-10-09) so the files have similar sizes; the east is denser per
# column. akhi = Alaska + Hawaii (all columns west of CONUS); east includes Puerto Rico and
# the U.S. Virgin Islands. Lon of a z9 column edge x: x / 512 * 360 - 180.
REGIONS = {"akhi": (0, 78),         # west of -125.16
           "west": (78, 100),       # -125.16 .. -109.69
           "plains": (100, 118),    # -109.69 .. -97.03
           "central": (118, 131),   # -97.03 .. -87.89  (Mississippi at St. Louis)
           "east": (131, 512)}      # east of -87.89
MAX_BYTES = 95_000_000


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def lon_of(x, z):
    return x / 2 ** z * 360 - 180


def lat_of(y, z):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** z))))


def group_of(z, x):
    if z <= LOW_MAX:
        return "low"
    c = x >> (z - SPLIT_Z)
    return next(k for k, (x0, x1) in REGIONS.items() if x0 <= c < x1)


def write(path, tiles, header, meta, bounds):
    """tiles: [(tileid, z, data)] sorted by tileid; bounds [w, s, e, n]."""
    h = dict(header)
    w, s, e, n = bounds
    h.update(min_lon_e7=round(w * 1e7), min_lat_e7=round(s * 1e7), max_lon_e7=round(e * 1e7),
             max_lat_e7=round(n * 1e7), center_lon_e7=round((w + e) / 2 * 1e7),
             center_lat_e7=round((s + n) / 2 * 1e7))
    zs = sorted({t[1] for t in tiles})
    h["center_zoom"] = zs[0]
    m = dict(meta)
    m["name"] = m["description"] = path.name
    m["antimeridian_adjusted_bounds"] = ",".join(f"{v:.6f}" for v in bounds)
    m["vector_layers"] = [dict(v, minzoom=max(v.get("minzoom", zs[0]), zs[0]), maxzoom=zs[-1])
                          for v in meta.get("vector_layers", [])]
    path.unlink(missing_ok=True)
    with open(path, "wb") as f:
        wr = Writer(f)
        for tid, _, data in tiles:
            wr.write_tile(tid, data)
        wr.finalize(h, m)


def split():
    with open(SOURCE, "rb") as f:
        r = Reader(MmapSource(f))
        header, meta = r.header(), r.metadata()
        groups = {"low": [], **{k: [] for k in REGIONS}}
        ext = {}   # group -> [xmin, ymin, xmax, ymax] in z9 tile units (regional groups)
        n = 0
        for (z, x, y), data in all_tiles(r.get_bytes):
            g = group_of(z, x)
            groups[g].append((zxy_to_tileid(z, x, y), z, data))
            n += 1
            if g != "low":
                s = z - SPLIT_Z
                e = ext.setdefault(g, [x >> s, y >> s, x >> s, y >> s])
                e[0], e[1] = min(e[0], x >> s), min(e[1], y >> s)
                e[2], e[3] = max(e[2], x >> s), max(e[3], y >> s)
    src_b = [header["min_lon_e7"] / 1e7, header["min_lat_e7"] / 1e7,
             header["max_lon_e7"] / 1e7, header["max_lat_e7"] / 1e7]
    entries = []
    for g, tiles in groups.items():
        tiles.sort()
        name = f"web_{g}.pmtiles"
        if g == "low":
            bounds = src_b
        else:   # the region's z9 tiles that hold data, cut to the data bounds
            x0, y0, x1, y1 = ext[g]
            bounds = [max(lon_of(x0, SPLIT_Z), src_b[0]), max(lat_of(y1 + 1, SPLIT_Z), src_b[1]),
                      min(lon_of(x1 + 1, SPLIT_Z), src_b[2]), min(lat_of(y0, SPLIT_Z), src_b[3])]
        bounds = [round(v, 6) for v in bounds]
        write(WEB / name, tiles, header, meta, bounds)
        zs = [t[1] for t in tiles]
        ent = {"file": name, "minzoom": min(zs), "maxzoom": max(zs), "bounds": bounds,
               "tiles": len(tiles), "bytes": (WEB / name).stat().st_size, "sha256": sha256(WEB / name)}
        if g == "low":
            ent["hidefrom"] = LOW_MAX + 1
        else:
            ent["z9_columns"] = list(REGIONS[g])
        entries.append(ent)
        log(f"{name}: z{ent['minzoom']}-{ent['maxzoom']}, {len(tiles):,} tiles, {ent['bytes'] / 1e6:.1f} MB, "
            f"bounds {bounds}")
    assert sum(e["tiles"] for e in entries) == n, "every tile must be in exactly one file"
    manifest = {
        "about": "Basin explorer web tiles (explorer/scripts/build_web_tiles.py): web_low z3-8 (all "
                 "domains, large rivers by zoom), regional files z9-10 (every segment) split on z9 tile "
                 "columns; layers of a file are shown from minzoom, and hidden from hidefrom if given.",
        "source": {"file": SOURCE.name, "tiles": n, "generator": meta.get("generator"),
                   "generator_options": meta.get("generator_options")},
        "tiles": entries,
    }
    (WEB / "tiles.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return entries


def read_tile(path, z, x, y):
    import mapbox_vector_tile
    with open(path, "rb") as f:
        data = Reader(MmapSource(f)).get(z, x, y)
    if data is None:
        return {}
    return mapbox_vector_tile.decode(gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data)


def validate(entries):
    ok = True
    for e in entries:
        good = e["bytes"] < MAX_BYTES
        print(f"  {e['file']}: {e['bytes'] / 1e6:.1f} MB < {MAX_BYTES / 1e6:.0f} MB: {good}")
        ok &= good
    total = sum(e["bytes"] for e in entries)
    print(f"  total {total / 1e6:.1f} MB")
    # a tile from each file is byte-identical to the source tile (St. Louis; the regions' seams)
    probes = [(8, -90.19, 38.63), (10, -90.19, 38.63), (10, -87.95, 37.0), (10, -87.85, 37.0),
              (10, -109.75, 44.0), (10, -109.6, 44.0), (10, -97.1, 40.0), (10, -96.95, 40.0),
              (10, -151.0, 61.2), (10, -157.9, 21.4), (10, -66.1, 18.3)]
    with open(SOURCE, "rb") as f:
        src = Reader(MmapSource(f))
        for z, lon, lat in probes:
            n2 = 2 ** z
            x = int((lon + 180) / 360 * n2)
            y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n2)
            want = src.get(z, x, y)
            name = f"web_{group_of(z, x)}.pmtiles"
            with open(WEB / name, "rb") as g:
                got = Reader(MmapSource(g)).get(z, x, y)
            others = []
            for e in entries:
                if e["file"] != name:
                    with open(WEB / e["file"], "rb") as g:
                        if Reader(MmapSource(g)).get(z, x, y) is not None:
                            others.append(e["file"])
            feats = read_tile(WEB / name, z, x, y).get("flow", {}).get("features", [])
            keys = set().union(*(ft["properties"] for ft in feats)) if feats else set()
            good = want is not None and got == want and not others and {"p", "z"} <= keys
            print(f"  z{z}/{x}/{y} ({lon}, {lat}) in {name}: identical to source {got == want}; "
                  f"{len(feats)} flow features, fields {sorted(keys)}; also in {others or 'no other file'}")
            ok &= good
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-tippecanoe", action="store_true", help=f"reuse {SOURCE.relative_to(ROOT)}")
    a = ap.parse_args()
    WEB.mkdir(parents=True, exist_ok=True)
    if not a.skip_tippecanoe:
        if shutil.which("tippecanoe") is None:
            sys.exit("tippecanoe not found on PATH (brew install tippecanoe)")
        v = subprocess.run(["tippecanoe", "--version"], capture_output=True, text=True)
        log(f"tippecanoe: {(v.stdout or v.stderr).strip()}")
        tippecanoe(SOURCE, [("flow", SCRATCH / "flow.fgb"), ("waterbodies", SCRATCH / "waterbodies.fgb")],
                   ZOOMS, {"flow": zoom_filter(FULL_ORDER_BY_ZOOM),
                           "waterbodies": [">=", "$zoom", WATERBODY_MINZOOM]})
    log(f"source {SOURCE.relative_to(ROOT)}: {SOURCE.stat().st_size / 1e6:.1f} MB, sha256 {sha256(SOURCE)}")
    for old in WEB.glob("web_*.pmtiles"):
        old.unlink()
    entries = split()
    log("validation:")
    ok = validate(entries)
    print(f"  tiles.json sha256 {sha256(WEB / 'tiles.json')}")
    log("done" if ok else "done WITH VALIDATION FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
