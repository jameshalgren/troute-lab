# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pandas==2.3.3", "pyarrow==21.0.0", "xarray==2025.9.0", "netcdf4==1.7.2", "numpy==2.3.3",
#   "geopandas==1.1.1", "pyogrio==0.11.1", "shapely==2.1.2", "pyproj==3.7.2", "truststore==0.10.4",
# ]
# ///
"""Basin-explorer data build: locations of interest ("places") keyed to NWM feature_ids.

Builds explorer/data/places.json per explorer/DATA_CONTRACT.md:
  {meta, places:[{type, key, name, feature_id, lat, lon, net, river, order, flags, source, extra}]}
with type in {gage, forecast_point, reservoir, dam, bridge}.

  gage            RouteLink `gages` (USGS site numbers; 7-character Water Survey of Canada
                  station numbers are also present). Enriched from the USGS Water Data API
                  (monitoring-locations, time-series-metadata) and the ECCC hydrometric-stations
                  API. Drainage area of the model segment = NHDPlusV2 TotDASqKm of the COMID equal
                  to the feature_id (EPA WATERS NHDPlus map service, layer 2).
  forecast_point  NWPS gauges (api.water.noaa.gov/nwps/v1) that list a forecast PEDTS, CONUS
                  states only; reachId and usgsId from the per-gauge endpoint.
  reservoir       NWM waterbodies (RouteLink NHDWaterbodyComID groups), polygons from the NWM v3
                  hydrofabric, names = NHDPlusV2 waterbody GNIS_NAME (EPA WATERS layer 4), NWM
                  reservoir type from reservoir_index_*.nc (NCO parm/domain, nwm.v3.1.6).
  dam             National Inventory of Dams (USACE), "major" filter (see MAJOR_DAM below),
                  snapped to the nearest flowline of order >= 3 within 500 m.
  bridge          National Bridge Inventory (FHWA, 2025 delimited file), bridges with a waterway
                  under them (Item 42B in 5..8), snapped to the nearest flowline of any order
                  within 500 m and kept only if that flowline has order >= BRIDGE_MIN_ORDER.

Inputs:  data/RouteLink_CONUS.nc (NWM v3.1.6), data/explorer/segment_attrs.parquet
         (explorer/scripts/build_codes.py), and the NWM v3 hydrofabric geodatabase at
         $NWM_HYDROFABRIC_GDB (optional; without it, distances use RouteLink lat/lon points and
         dams/bridges snap to those points; meta.geometry says which was used).
Cache:   data/explorer/cache/ (gitignored). Every downloaded input is kept there and listed in
         data/explorer/cache/sources.json with URL, access date and SHA-256; that record is
         copied into places.json meta.sources. Re-runs reuse the cache (no network) unless
         --refresh is given. The web is only read (HTTP GET).
Outputs: explorer/data/places.json, data/explorer/T_places.csv,
         section "Places of interest" in explorer/README.md (between marker comments;
         other sections are left alone).
Optional cross-check: $NEXTGEN_HYDROFABRIC_GPKG = local conus_nextgen.gpkg (CONUS NextGen hydrofabric,
         community v2.2, from conus_nextgen.tar.gz on the communityhydrofabric S3 bucket; see NGEN_URL).
Usage:   NWM_HYDROFABRIC_GDB=/path/to/NWM_v3_hydrofabric.gdb [NEXTGEN_HYDROFABRIC_GPKG=/path/to/conus_nextgen.gpkg]
         uv run explorer/scripts/build_places.py
         [--refresh] [--skip-bridges]
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import truststore
import xarray as xr

truststore.inject_into_ssl()   # use the OS trust store (www.fhwa.dot.gov fails with certifi's bundle)

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "explorer" / "cache"
SOURCES = CACHE / "sources.json"
DOMAINS = ["CONUS", "AK", "HI", "PRVI"]
DOM_INDEX = {d: i for i, d in enumerate(DOMAINS)}
ROUTELINK = {d: ROOT / "data" / f"RouteLink_{d}.nc" for d in DOMAINS}
REACH_LAYER = {"CONUS": "nwm_reaches_conus", "AK": "nwm_reaches_alaska", "HI": "nwm_reaches_hawaii",
               "PRVI": "nwm_reaches_puertorico"}
WB_LAYER = {"CONUS": "nwm_waterbodies_conus", "AK": "nwm_waterbodies_alaska", "HI": "nwm_waterbodies_hawaii"}
# Projected CRS (meters) per domain for distances and snapping
DOM_CRS = {"CONUS": "EPSG:5070", "AK": "EPSG:3338", "HI": "ESRI:102007", "PRVI": "EPSG:32161"}
# lon/lat boxes (west, south, east, north) of each domain's channel network (RouteLink), padded
DOM_BOX = {"CONUS": (-126.0, 23.0, -61.0, 54.0), "AK": (-155.5, 58.3, -139.5, 64.0),
           "HI": (-160.6, 18.7, -154.6, 22.5), "PRVI": (-67.5, 17.5, -64.4, 18.7)}
# NWPS state abbreviations per domain, NBI state codes (FIPS) per domain
NWPS_STATES = {"AK": {"AK"}, "HI": {"HI"}, "PRVI": {"PR", "VI"}}
NBI_STATES = {"AK": {"02"}, "HI": {"15"}, "PRVI": {"72", "78"}}
HR_NHDP = "https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer"
ATTRS = ROOT / "data" / "explorer" / "segment_attrs.parquet"
OUT_JSON = ROOT / "explorer" / "data" / "places.json"
OUT_CSV = ROOT / "data" / "explorer" / "T_places.csv"
README = ROOT / "explorer" / "README.md"

UA = "troute-paper-basin-explorer/1.0 (research build script; read-only)"
TODAY = dt.date.today().isoformat()

USGS_API = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
ECCC_API = "https://api.weather.gc.ca/collections/hydrometric-stations/items"
EPA_NHDP = "https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer"
NWPS_API = "https://api.water.noaa.gov/nwps/v1/gauges"
NCO_DOMAIN = "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain"
NID_CSV = "https://nid.sec.usace.army.mil/api/nation/csv"
NBI_YEAR = 2025
NBI_ZIP = f"https://www.fhwa.dot.gov/bridge/nbi/{NBI_YEAR}hwybronefiledel.zip"
NBI_GUIDE = "https://www.fhwa.dot.gov/bridge/mtguide.pdf"
RES_TYPE_DOC = ("https://github.com/NCAR/wrf_hydro_nwm_public/blob/main/src/Routing/module_RT.F90 "
                "(reservoir_type dispatch: 1 level pool, 2 USGS persistence, 3 USACE persistence, "
                "4/5 RFC forecast); Persistence_Level_Pool_Hybrid_Module_README.md, "
                "RFC_Forecasts_Module_README.md in the same directory")

GAGE_DIST_KM = 2.0
DA_LO, DA_HI = 0.75, 1.33
INACTIVE_DAYS = 365
MAJOR_DAM = ("NID Height >= 50 ft OR Normal Storage >= 5,000 acre-ft OR Max Storage >= 25,000 "
             "acre-ft (the National Atlas 'major dams' definition, see "
             "http://lagic.lsu.edu/data/losco/dams00x020_usgs_2006_faq.html, accessed 2026-10-06); "
             "associated structures excluded")
DAM_MIN_ORDER, DAM_SNAP_M, DAM_FLAG_M, DAM_FLAG_ORDER = 3, 500.0, 250.0, 4
BRIDGE_MIN_ORDER, BRIDGE_SNAP_M, BRIDGE_FLAG_M = 6, 500.0, 250.0
NON_CONUS = {"AK", "HI", "PR", "VI", "GU", "AS", "MP"}
SQKM_PER_SQMI = 2.589988110336
EQ_CRS = "EPSG:5070"  # NAD83 / Conus Albers (meters); other domains: DOM_CRS


# ----------------------------------------------------------------------------- cache + http
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def load_sources() -> dict:
    return json.loads(SOURCES.read_text()) if SOURCES.exists() else {}


def record(rel: str, url: str, note: str = "") -> None:
    src = load_sources()
    p = CACHE / rel
    src[rel] = {"url": url, "accessed": TODAY, "sha256": sha256(p), "bytes": p.stat().st_size,
                **({"note": note} if note else {})}
    SOURCES.write_text(json.dumps(src, indent=1, sort_keys=True))


def http_get(url: str, params: dict | None = None, tries: int = 6, timeout: int = 180) -> bytes:
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    for k in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and k < tries - 1:
                wait = float(e.headers.get("Retry-After") or 0) or 2 ** (k + 1)
                time.sleep(min(wait, 120))
                continue
            if e.code == 404:
                return b""
            raise
        except (urllib.error.URLError, TimeoutError):
            if k < tries - 1:
                time.sleep(2 ** (k + 1))
                continue
            raise
    raise RuntimeError(url)


def cached_file(rel: str, url: str, refresh: bool) -> Path:
    p = CACHE / rel
    src = load_sources()
    if p.exists() and not refresh:
        if rel not in src:
            record(rel, url, note="file was already in the cache; access date = date first recorded")
        elif src[rel]["sha256"] != sha256(p):
            sys.exit(f"ERROR: {p} does not match the SHA-256 recorded in {SOURCES}")
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    print(f"fetch   {url}", flush=True)
    tmp = p.with_suffix(p.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=900) as r, open(tmp, "wb") as f:
        while b := r.read(1 << 20):
            f.write(b)
    tmp.rename(p)
    record(rel, url)
    return p


def cached_json(rel: str, url_desc: str, fetch, refresh: bool):
    """Aggregated API result: fetch() -> JSON-able object, cached as one file."""
    p = CACHE / rel
    src = load_sources()
    if p.exists() and not refresh and rel in src:
        if src[rel]["sha256"] != sha256(p):
            sys.exit(f"ERROR: {p} does not match the SHA-256 recorded in {SOURCES}")
        return json.loads(p.read_text())
    obj = fetch()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, separators=(",", ":"), sort_keys=True))
    record(rel, url_desc)
    return obj


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def ogc_pages(url: str, params: dict) -> list:
    """All features of an OGC API Features query, following rel=next links."""
    out, nxt, prm, seen = [], url, dict(params), set()
    limit = int(params.get("limit", 0))
    while nxt and nxt not in seen and len(seen) < 50:
        seen.add(nxt)
        d = json.loads(http_get(nxt, prm) or b"{}")
        feats = d.get("features", [])
        out.extend(feats)
        if not feats or (limit and len(feats) < limit):
            break                               # last page (some servers add a 'next' link anyway)
        nxt = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
        prm = None
        time.sleep(0.5)
    return out


def sq(ids) -> str:
    return ",".join(f"'{i}'" for i in ids)


# ----------------------------------------------------------------------------- network data
def load_network(dom):
    ds = xr.open_dataset(ROUTELINK[dom])
    rl = pd.DataFrame({
        "feature_id": ds["link"].values.astype(np.int64),
        "to": ds["to"].values.astype(np.int64),
        "wb": ds["NHDWaterbodyComID"].values.astype(np.int64),
        "gage": np.char.strip(ds["gages"].values.astype(str)),
    })
    attrs = pd.read_parquet(ATTRS)
    seg = attrs[attrs["dom"] == DOM_INDEX[dom]].set_index("feature_id")
    seg.attrs["dom"] = dom
    assert len(seg) == len(rl) and seg.index.equals(pd.Index(rl["feature_id"])), "segment_attrs out of date"
    return rl, seg


def load_geometry(dom, seg: pd.DataFrame):
    """GeoSeries of segment geometry in the domain's projected CRS, indexed by feature_id."""
    import geopandas as gpd
    gdb = os.environ.get("NWM_HYDROFABRIC_GDB") or str(ROOT / "data" / "NWM_v3_hydrofabric.gdb")
    crs = DOM_CRS[dom]
    if gdb and Path(gdb).exists():
        import pyogrio
        print(f"read    {REACH_LAYER[dom]} from $NWM_HYDROFABRIC_GDB", flush=True)
        g = pyogrio.read_dataframe(gdb, layer=REACH_LAYER[dom], columns=["ID"], use_arrow=True)
        g = g.set_index(g["ID"].astype(np.int64))["geometry"]
        g = g[~g.index.duplicated()].to_crs(crs)
        return g, f"NWM v3 hydrofabric nwm_reaches_* line geometry (projected per domain: {DOM_CRS})"
    pts = gpd.points_from_xy(seg["lon"], seg["lat"], crs="EPSG:4269")
    return (gpd.GeoSeries(pts, index=seg.index).to_crs(crs),
            "RouteLink lat/lon points (hydrofabric geodatabase not available)")


def to5070(lon, lat, crs=EQ_CRS):
    import geopandas as gpd
    return gpd.GeoSeries(gpd.points_from_xy(lon, lat, crs="EPSG:4326")).to_crs(crs)


def seg_fields(seg, fid):
    if fid is None or fid not in seg.index:
        return {"net": 0, "river": 0, "order": None}
    r = seg.loc[fid]
    out = {"net": int(r["net"]), "river": int(r["river"]), "order": int(r["order"])}
    if "p" in seg.columns:   # DFS preorder index and upstream-subtree size (build_codes.py):
        out["p"] = int(r["p"])   # everything upstream of this segment has p in [p, p + z)
        out["z"] = int(r["z"])
    return out


def place(type_, key, name, fid, lat, lon, seg, flags, source, extra):
    sf = seg_fields(seg, fid)
    return {"type": type_, "dom": seg.attrs.get("dom", "CONUS"), "key": key, "name": name,
            "feature_id": None if fid is None else int(fid),
            "lat": None if lat is None or pd.isna(lat) else round(float(lat), 5),
            "lon": None if lon is None or pd.isna(lon) else round(float(lon), 5),
            **sf, "flags": flags, "source": source,
            "extra": {k: (int(v) if isinstance(v, float) and v.is_integer() and k != "da_ratio" else v)
                      for k, v in extra.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}}


# ----------------------------------------------------------------------------- external lookups
def epa_query(layer: int, ids, fields: str, rel: str, refresh: bool) -> dict:
    def fetch():
        out = {}
        for ch in chunks(sorted(set(int(i) for i in ids)), 200):
            d = json.loads(http_get(f"{EPA_NHDP}/{layer}/query", {
                "where": f"comid IN ({','.join(map(str, ch))})", "outFields": fields,
                "returnGeometry": "false", "f": "json"}))
            if "error" in d:
                raise RuntimeError(d["error"])
            for f in d.get("features", []):
                a = f["attributes"]
                out[str(a["comid"])] = a
            time.sleep(0.3)
        return out
    return cached_json(rel, f"{EPA_NHDP}/{layer}/query?where=comid IN (...)&outFields={fields}", fetch, refresh)


HR_STATUS = {}


def hr_available() -> bool:
    """One quick probe of the NHDPlus HR service (it answered HTTP 502/504 or took > 100 s per
    query on 2026-10-07); if it fails, the AK lookups that need it are skipped and noted.
    The probe is a one-ID nhdplusid query (the kind hr_query makes): on 2026-10-08 those answered
    in 12-98 s, while a `where=1=0` count query got HTTP 504 after 180 s three times."""
    if "ok" not in HR_STATUS:
        try:
            req = urllib.request.Request(f"{HR_NHDP}/3/query?where=nhdplusid+IN+%2875000200002092%29"
                                         "&outFields=nhdplusid&returnGeometry=false&f=json",
                                         headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=240) as r:
                HR_STATUS["ok"] = "features" in json.loads(r.read())
        except Exception as ex:  # noqa: BLE001
            HR_STATUS["ok"] = False
            HR_STATUS["error"] = f"{type(ex).__name__}: {ex}"[:200]
        HR_STATUS["checked"] = TODAY
    return HR_STATUS["ok"]


def hr_query(ids, fields: str, rel: str, refresh: bool, layer: int = 3) -> dict:
    """NHDPlus HR (Alaska) attributes by nhdplusid, from the USGS NHDPlus HR map service."""
    p = CACHE / rel
    if not (p.exists() and rel in load_sources() and not refresh) and not hr_available():
        print(f"skip    {rel}: NHDPlus HR service unavailable ({HR_STATUS.get('error')})", flush=True)
        return {}

    def fetch():
        out = {}
        for ch in chunks(sorted(set(int(i) for i in ids)), 100):
            d = json.loads(http_get(f"{HR_NHDP}/{layer}/query", {
                "where": f"nhdplusid IN ({','.join(map(str, ch))})", "outFields": fields,
                "returnGeometry": "false", "f": "json"}))
            if "error" in d:
                raise RuntimeError(d["error"])
            for f in d.get("features", []):
                a = f["attributes"]
                out[str(int(a["nhdplusid"]))] = a
            time.sleep(0.3)
        return out
    return cached_json(rel, f"{HR_NHDP}/{layer}/query?where=nhdplusid IN (...)&outFields={fields}", fetch, refresh)


def usgs_sites(ids, refresh, sfx=""):
    props = ("monitoring_location_number,monitoring_location_name,agency_code,drainage_area,"
             "contributing_drainage_area,site_type_code,state_code")

    def fetch():
        feats = []
        for ch in chunks(sorted(ids), 100):
            feats += ogc_pages(f"{USGS_API}/monitoring-locations/items", {
                "f": "json", "limit": 10000, "filter-lang": "cql-text",
                "filter": f"monitoring_location_number IN ({sq(ch)})", "properties": props})
        return feats
    return cached_json(f"usgs/monitoring_locations{sfx}.json",
                       f"{USGS_API}/monitoring-locations/items?filter=monitoring_location_number IN (...)",
                       fetch, refresh)


def usgs_ts(ml_ids, refresh, sfx=""):
    def fetch():
        feats = []
        for ch in chunks(sorted(ml_ids), 100):
            feats += [f["properties"] for f in ogc_pages(f"{USGS_API}/time-series-metadata/items", {
                "f": "json", "limit": 10000, "filter-lang": "cql-text", "skipGeometry": "true",
                "filter": f"monitoring_location_id IN ({sq(ch)}) AND parameter_code IN ('00060','00065')",
                "properties": "monitoring_location_id,parameter_code,end_utc,computation_period_identifier"})]
        return feats
    return cached_json(f"usgs/time_series_metadata{sfx}.json",
                       f"{USGS_API}/time-series-metadata/items?filter=monitoring_location_id IN (...) "
                       "AND parameter_code IN ('00060','00065')", fetch, refresh)


def eccc_stations(refresh):
    def fetch():
        return [f for f in ogc_pages(ECCC_API, {"f": "json", "limit": 10000})]
    return cached_json("eccc/hydrometric_stations.json", f"{ECCC_API}?f=json&limit=10000", fetch, refresh)


def nwps_details(lids, refresh, sfx=""):
    rel = f"nwps/gauge_details{sfx}.json"
    p = CACHE / rel
    if p.exists() and not refresh and rel in load_sources():
        return json.loads(p.read_text())
    part = CACHE / "nwps" / f"gauge_details{sfx}.partial.jsonl"
    done = {}
    if part.exists() and not refresh:
        for line in part.read_text().splitlines():
            d = json.loads(line)
            done[d["lid"]] = d
    todo = [l for l in lids if l not in done]
    print(f"nwps    {len(done)} cached, {len(todo)} to fetch (4 parallel requests)", flush=True)
    keep = ("lid", "usgsId", "reachId", "name", "county", "latitude", "longitude")

    def one(lid):
        raw = http_get(f"{NWPS_API}/{lid}")
        time.sleep(0.1)
        if not raw:
            return {"lid": lid, "missing": True}
        d = json.loads(raw)
        return {k: d.get(k) for k in keep}

    with open(part, "a") as f, cf.ThreadPoolExecutor(4) as ex:
        for i, r in enumerate(ex.map(one, todo)):
            done[r["lid"]] = r
            f.write(json.dumps(r) + "\n")
            if i % 500 == 499:
                f.flush()
                print(f"        {i + 1}/{len(todo)}", flush=True)
    obj = {l: done[l] for l in lids}
    p.write_text(json.dumps(obj, separators=(",", ":"), sort_keys=True))
    record(rel, f"{NWPS_API}/{{lid}} (one GET per forecast gauge; fields {', '.join(keep)})")
    part.unlink()
    return obj


# ----------------------------------------------------------------------------- builders
def build_gages(rl, seg, geom, refresh, dom="CONUS"):
    sfx = "" if dom == "CONUS" else f"_{dom}"
    crs = DOM_CRS[dom]
    g = rl[rl["gage"] != ""][["feature_id", "gage"]]
    multi = g.groupby("gage")["feature_id"].nunique()
    multi = multi[multi > 1]
    usgs_like = g[g["gage"].str.fullmatch(r"\d+")]
    wsc_like = g[g["gage"].str.fullmatch(r"\d\d[A-Z]{2}\d{3}")]
    other = g[~g.index.isin(usgs_like.index) & ~g.index.isin(wsc_like.index)]
    # 7-digit numeric ids are not valid USGS site numbers (8-15 digits): also try zero-padded
    query_ids = set(usgs_like["gage"]) | {"0" + x for x in usgs_like["gage"] if len(x) == 7}
    sites = usgs_sites(query_ids, refresh, sfx)
    by_no = {}
    for f in sites:
        pr = f["properties"]
        no = pr["monitoring_location_number"]
        if no not in by_no or pr["agency_code"] == "USGS":
            by_no[no] = {**pr, "id": f["id"], "lon": f["geometry"]["coordinates"][0] if f.get("geometry") else None,
                         "lat": f["geometry"]["coordinates"][1] if f.get("geometry") else None}
    ts = usgs_ts([v["id"] for v in by_no.values()], refresh, sfx)
    last = {}
    for t in ts:
        if t.get("end_utc"):
            last[t["monitoring_location_id"]] = max(last.get(t["monitoring_location_id"], ""), t["end_utc"])
    eccc = {f["properties"]["STATION_NUMBER"]: f for f in eccc_stations(refresh)}
    if dom == "AK":   # NHDPlus HR NHDPlusIDs (Arc-Hydro Copper River IDs have no NHDPlus attributes)
        totda = hr_query([f for f in g["feature_id"] if f // 10**12 == 75], "nhdplusid,totdasqkm",
                         "nhdplushr/flowline_totdasqkm_AK.json", refresh)
    else:
        totda = epa_query(2, g["feature_id"], "comid,totdasqkm", f"epa/nhdplusv2_flowline_totdasqkm{sfx}.json", refresh)

    cutoff = (dt.date.fromisoformat(load_sources()[f"usgs/time_series_metadata{sfx}.json"]["accessed"])
              - dt.timedelta(days=INACTIVE_DAYS)).isoformat()
    wsc_set = set(wsc_like["gage"])
    rows = []
    for fid, gid in zip(g["feature_id"], g["gage"]):
        flags, extra = [], {"gage_id": gid}
        name = lat = lon = da_site = None
        is_wsc = gid in wsc_set
        if is_wsc:
            src, key = "rl_gages+eccc", f"wsc:{gid}"
            extra["agency"] = "WSC"
            f = eccc.get(gid)
            if f is None:
                flags.append("not_found")
            else:
                pr = f["properties"]
                name = pr["STATION_NAME"].title() if pr.get("STATION_NAME") else None
                lon, lat = f["geometry"]["coordinates"][:2]
                if pr.get("DRAINAGE_AREA_GROSS"):
                    da_site = pr["DRAINAGE_AREA_GROSS"] / SQKM_PER_SQMI
                extra["status"] = pr.get("STATUS_EN")
                if pr.get("STATUS_EN") != "Active":
                    flags.append("inactive")
        else:
            src, key = "rl_gages+usgs", f"usgs:{gid}"
            s = by_no.get(gid)
            if s is None and len(gid) == 7 and ("0" + gid) in by_no:
                s = by_no["0" + gid]
                flags.append("id_needs_leading_zero")
                extra["usgs_id"] = "0" + gid
            if s is None:
                flags.append("not_found")
            else:
                name, lat, lon = s["monitoring_location_name"], s["lat"], s["lon"]
                extra["agency"] = s["agency_code"]
                extra["site_type"] = s["site_type_code"]
                da_site = s.get("drainage_area")
                lt = last.get(s["id"])
                extra["last_q_or_stage"] = lt[:10] if lt else None
                if lt is None:
                    flags.append("no_q_or_stage_series")
                elif lt[:10] < cutoff:
                    flags.append("inactive")
        if gid in multi.index:
            flags.append("multi_segment")
        a = totda.get(str(fid))
        da_model = a["totdasqkm"] / SQKM_PER_SQMI if a and a.get("totdasqkm") else None
        if da_site:
            extra["da_sqmi_site"] = round(float(da_site), 2)
        if da_model:
            extra["da_sqmi_model"] = round(float(da_model), 2)
        if da_site and da_model:
            ratio = float(da_site) / da_model
            extra["da_ratio"] = round(ratio, 3)
            if not (DA_LO <= ratio <= DA_HI):
                flags.append("da_mismatch")
        rows.append(dict(type="gage", key=key, name=name, fid=int(fid), lat=lat, lon=lon,
                         flags=flags, source=src, extra=extra))
    # distance site -> segment
    df = pd.DataFrame(rows)
    has = df["lat"].notna()
    if has.any():
        pts = to5070(df.loc[has, "lon"].astype(float).values, df.loc[has, "lat"].astype(float).values, crs)
        lines = geom.reindex(df.loc[has, "fid"].values)
        d_km = pts.distance(lines.reset_index(drop=True), align=False).values / 1000.0
        for i, d in zip(df.index[has], d_km):
            if np.isfinite(d):
                df.at[i, "extra"]["dist_km"] = round(float(d), 3)
                if d > GAGE_DIST_KM:
                    df.at[i, "flags"].append("dist_gt_2km")
    out = []
    for r in df.itertuples():
        lat, lon = (r.lat, r.lon)
        if lat is None or pd.isna(lat):     # site not found: place it at the segment's RouteLink point
            lat, lon = seg.at[r.fid, "lat"], seg.at[r.fid, "lon"]
            r.extra["location"] = "routelink_segment"
        out.append(place(r.type, r.key, r.name, r.fid, lat, lon, seg, r.flags, r.source, r.extra))
    stats = {"routelink_gage_entries": int(len(g)), "unique_ids": int(g["gage"].nunique()),
             "ids_on_multiple_segments": int(len(multi)), "usgs_numeric_ids": int(len(usgs_like)),
             "wsc_ids": int(len(wsc_like)), "other_ids": int(len(other))}
    gage_seg = {r["extra"].get("usgs_id", r["extra"]["gage_id"]): r["feature_id"] for r in out}
    return out, stats, gage_seg


def build_forecast_points(seg, geom, gage_seg, refresh, dom="CONUS"):
    if dom != "CONUS":
        return build_forecast_points_ext(seg, geom, gage_seg, refresh, dom)

    def fetch_list():
        # the unfiltered list takes ~60 s and often hits the gateway timeout, so fetch CONUS in
        # 5-degree longitude bands (bbox in EPSG:4326) and de-duplicate by LID
        got = {}
        for x0 in range(-126, -65, 5):
            d = json.loads(http_get(NWPS_API, {"bbox.xmin": x0, "bbox.ymin": 23, "bbox.xmax": x0 + 5,
                                               "bbox.ymax": 51, "srid": "EPSG_4326"}))
            for gg in d["gauges"]:
                got[gg["lid"]] = gg
            time.sleep(1)
        return sorted(got.values(), key=lambda gg: gg["lid"])
    lst = cached_json("nwps/gauges.json", f"{NWPS_API}?bbox.xmin=..&bbox.ymin=23&bbox.xmax=..&bbox.ymax=51"
                      "&srid=EPSG_4326 (5-degree longitude bands from -126 to -61)", fetch_list, refresh)
    fc = [x for x in lst if (x.get("pedts") or {}).get("forecast")
          and (x.get("state") or {}).get("abbreviation") not in NON_CONUS]
    out = forecast_rows(fc, nwps_details([x["lid"] for x in fc], refresh), seg, geom, gage_seg, EQ_CRS)
    return out, {"nwps_gauges_listed": len(lst), "with_forecast_pedts_conus": len(fc)}


def build_forecast_points_ext(seg, geom, gage_seg, refresh, dom):
    """NWPS forecast points in AK / HI / PR+VI: gauges with a forecast PEDTS whose state is in
    the domain and whose location is inside the domain box (the NWM Alaska domain covers Cook
    Inlet and the Copper River only)."""
    w, s_, e, n = DOM_BOX[dom]

    def fetch_list():
        d = json.loads(http_get(NWPS_API, {"bbox.xmin": w, "bbox.ymin": s_, "bbox.xmax": e, "bbox.ymax": n,
                                           "srid": "EPSG_4326"}))
        return sorted(d["gauges"], key=lambda gg: gg["lid"])
    lst = cached_json(f"nwps/gauges_{dom}.json", f"{NWPS_API}?bbox.xmin={w}&bbox.ymin={s_}&bbox.xmax={e}"
                      f"&bbox.ymax={n}&srid=EPSG_4326", fetch_list, refresh)
    fc = [x for x in lst if (x.get("pedts") or {}).get("forecast")
          and (x.get("state") or {}).get("abbreviation") in NWPS_STATES[dom]]
    out = forecast_rows(fc, nwps_details([x["lid"] for x in fc], refresh, f"_{dom}"), seg, geom, gage_seg,
                        DOM_CRS[dom])
    return out, {"nwps_gauges_listed": len(lst), f"with_forecast_pedts_{dom}": len(fc)}


def forecast_rows(fc, det, seg, geom, gage_seg, crs):
    rows = []
    for x in fc:
        d = det.get(x["lid"], {})
        flags = []
        reach = str(d.get("reachId") or "").strip()
        fid = int(reach) if reach.isdigit() and int(reach) > 0 else None
        usgs = str(d.get("usgsId") or "").strip() or None
        if d.get("missing"):
            flags.append("detail_not_found")
        if fid is None:
            flags.append("no_reach_id")
        elif fid not in seg.index:
            flags.append("reach_not_in_routelink")
        extra = {"lid": x["lid"], "rfc": (x.get("rfc") or {}).get("abbreviation") or None,
                 "wfo": (x.get("wfo") or {}).get("abbreviation") or None,
                 "state": (x.get("state") or {}).get("abbreviation") or None, "usgs_id": usgs,
                 "reach_id": fid}
        if usgs and usgs in gage_seg:
            extra["gage_feature_id"] = gage_seg[usgs]
            if fid is not None and gage_seg[usgs] != fid:
                flags.append("reach_differs_from_gage_segment")
        elif usgs:
            extra["gage_in_routelink"] = False
        rows.append(dict(key=f"nws:{x['lid']}", name=x.get("name"), fid=fid if fid in seg.index else None,
                         lat=x.get("latitude"), lon=x.get("longitude"), flags=flags, extra=extra))
    df = pd.DataFrame(rows)
    if df.empty:
        return []
    has = df["fid"].notna() & df["lat"].notna()
    pts = to5070(df.loc[has, "lon"].astype(float).values, df.loc[has, "lat"].astype(float).values, crs)
    lines = geom.reindex(df.loc[has, "fid"].astype(np.int64).values)
    d_km = pts.distance(lines.reset_index(drop=True), align=False).values / 1000.0
    for i, d in zip(df.index[has], d_km):
        if np.isfinite(d):
            df.at[i, "extra"]["dist_km"] = round(float(d), 3)
            if d > GAGE_DIST_KM:
                df.at[i, "flags"].append("dist_gt_2km")
    return [place("forecast_point", r.key, r.name, None if pd.isna(r.fid) else int(r.fid), r.lat, r.lon, seg,
                  r.flags, "nwps", r.extra) for r in df.itertuples()]


def build_reservoirs(rl, seg, refresh, dom="CONUS"):
    import geopandas as gpd
    m = rl[rl["wb"] > 0]
    members = m.groupby("wb")["feature_id"].apply(set)
    outlets = {}
    for wb, grp in m.groupby("wb"):
        s = members[wb]
        o = grp[~grp["to"].isin(s)]
        outlets[wb] = list(o["feature_id"])
    # reservoir types
    rtype, rgage = {}, {}
    # CONUS: four configurations; AK: the glacier-dammed-lake file; HI and PRVI have none
    cfgs = {"CONUS": ["AnA", "Extended_AnA", "Short_Range", "Medium_Range"], "AK": ["GDL_AK"]}.get(dom, [])
    for c in cfgs:
        url = (f"{NCO_DOMAIN}/reservoir_index_{c}.nc" if dom == "CONUS"
               else f"{NCO_DOMAIN}_alaska/reservoir_index_{c}.nc")
        p = cached_file(f"nwm_parm/reservoir_index_{c}.nc", url, refresh)
        ds = xr.open_dataset(p)
        for lid, t in zip(ds["lake_id"].values.astype(np.int64), ds["reservoir_type"].values.astype(int)):
            rtype.setdefault(int(lid), {})[c] = int(t)
        if c == "GDL_AK":
            for gid, lid in zip(np.char.strip(ds["rfc_gage_id"].values.astype(str)), ds["rfc_lake_id"].values.astype(np.int64)):
                rgage[int(lid)] = f"rfc:{gid}"
        if c == "AnA":
            for ag, gv, lv in [("usgs", "usgs_gage_id", "usgs_lake_id"), ("usace", "usace_gage_id", "usace_lake_id"),
                               ("rfc", "rfc_gage_id", "rfc_lake_id")]:
                for gid, lid in zip(np.char.strip(ds[gv].values.astype(str)), ds[lv].values.astype(np.int64)):
                    rgage[int(lid)] = f"{ag}:{gid}"
    if dom == "AK":
        names = hr_query([w for w in members.index if w > 100], "nhdplusid,gnis_name,gnis_id,ftype",
                         "nhdplushr/waterbody_gnis_AK.json", refresh, layer=9)
    else:
        names = epa_query(4, members.index, "comid,gnis_name,gnis_id,ftype",
                          "epa/nhdplusv2_waterbody_gnis.json" if dom == "CONUS" else f"epa/nhdplusv2_waterbody_gnis_{dom}.json",
                          refresh)
    gdb = os.environ.get("NWM_HYDROFABRIC_GDB") or str(ROOT / "data" / "NWM_v3_hydrofabric.gdb")
    poly = None
    if gdb and Path(gdb).exists() and dom in WB_LAYER:
        import pyogrio
        poly = pyogrio.read_dataframe(gdb, layer=WB_LAYER[dom], columns=["ID"], use_arrow=True)
        poly = poly.set_index(poly["ID"].astype(np.int64))
        if dom != "CONUS":           # CONUS layer is already USA Contiguous Albers Equal Area (m)
            poly = poly.to_crs(DOM_CRS[dom])
        area = poly.geometry.area / 1e6
        cen = gpd.GeoSeries(poly.geometry.centroid, crs=poly.crs).to_crs("EPSG:4326")
    tname = {1: "level_pool", 2: "usgs_persistence", 3: "usace_persistence", 4: "rfc_forecast", 5: "rfc_forecast"}
    out = []
    for wb in members.index:
        flags = []
        outs = outlets[wb]
        if len(outs) != 1:
            flags.append("multiple_outlets" if outs else "no_outlet")
        fid = None
        if outs:
            fid = max(outs, key=lambda f: (seg.at[f, "order"], -seg.at[f, "d_seg"]))
        rt = rtype.get(int(wb), {})
        extra = {"wb_id": int(wb), "n_segments": len(members[wb]),
                 "res_type": tname.get(rt.get("AnA")) if rt else None,
                 "da_gage": rgage.get(int(wb))}
        if rt and len({tname.get(v) for v in rt.values()}) > 1:
            extra["res_type_by_config"] = {c: tname.get(v) for c, v in rt.items()}
        if not rt and cfgs:
            flags.append("not_in_reservoir_index")
        if len(outs) > 1:
            extra["outlets"] = [int(x) for x in outs]
        nm = names.get(str(int(wb)), {}).get("gnis_name") or None
        if poly is not None and wb in poly.index:
            extra["area_km2"] = round(float(area[wb]), 3)
            lat, lon = cen[wb].y, cen[wb].x
        else:
            if poly is not None:
                flags.append("no_polygon")
            elif dom == "PRVI":
                extra["location"] = "outlet_segment (no PRVI waterbody layer in the hydrofabric)"
            lat, lon = (seg.at[fid, "lat"], seg.at[fid, "lon"]) if fid else (None, None)
        out.append(place("reservoir", f"nwm_wb:{int(wb)}", nm, fid, lat, lon, seg, flags, "nwm_waterbody", extra))
    stats = {"waterbodies": len(members), "named": sum(1 for p in out if p["name"]), "reservoir_index": cfgs,
             "res_type_counts_AnA": pd.Series([p["extra"].get("res_type") for p in out]).value_counts().to_dict()}
    return out, stats


def snap(points, geom, cand_ids, max_m, crs=EQ_CRS):
    """Nearest candidate segment within max_m for each point (GeoSeries in the domain CRS)."""
    import geopandas as gpd
    lines = gpd.GeoDataFrame({"fid": cand_ids}, geometry=geom.reindex(cand_ids).values, crs=crs)
    lines = lines[lines.geometry.notna()]
    pts = gpd.GeoDataFrame({"i": np.arange(len(points))}, geometry=points.values, crs=crs)
    j = gpd.sjoin_nearest(pts, lines, how="left", max_distance=max_m, distance_col="snap_m")
    j = j.sort_values("snap_m").drop_duplicates("i").set_index("i").sort_index()
    return j["fid"], j["snap_m"]


def build_dams(seg, geom, refresh, dom="CONUS"):
    p = cached_file("nid/nation.csv", NID_CSV, refresh)
    with open(p) as f:
        data_date = f.readline().strip().split(",")[-1]      # "Data Last Updated:,YYYY-M-D"
    nid = pd.read_csv(p, skiprows=1, low_memory=False)
    num = lambda c: pd.to_numeric(nid[c], errors="coerce")
    major = (num("NID Height (Ft)") >= 50) | (num("Normal Storage (Acre-Ft)") >= 5000) | \
            (num("Max Storage (Acre-Ft)") >= 25000)
    major &= nid["Is Associated Structure?"].fillna("No").ne("Yes")
    w_, s_, e_, n_ = DOM_BOX[dom]
    inbox = num("Longitude").between(w_, e_) & num("Latitude").between(s_, n_)
    d = nid[major & num("Latitude").notna() & num("Longitude").notna() & inbox].reset_index(drop=True)
    cand = seg.index[seg["order"] >= DAM_MIN_ORDER].values
    d["Latitude"] = pd.to_numeric(d["Latitude"], errors="coerce")
    d["Longitude"] = pd.to_numeric(d["Longitude"], errors="coerce")
    if d.empty:
        return [], {"nid_records": int(len(nid)), "major_with_coords_in_domain": 0, "snapped_within_500m": 0}
    fid, dist = snap(to5070(d["Longitude"].values, d["Latitude"].values, DOM_CRS[dom]), geom, cand, DAM_SNAP_M,
                     DOM_CRS[dom])
    out = []
    for i, r in d.iterrows():
        f = fid.get(i)
        if f is None or pd.isna(f):
            continue
        f = int(f)
        flags = []
        if dist[i] > DAM_FLAG_M:
            flags.append("snap_gt_250m")
        if seg.at[f, "order"] < DAM_FLAG_ORDER:
            flags.append("low_order")
        val = lambda c: None if pd.isna(r[c]) or r[c] == "" else r[c]
        fnum = lambda c: None if pd.isna(pd.to_numeric(r[c], errors="coerce")) else float(pd.to_numeric(r[c], errors="coerce"))
        out.append(place("dam", f"nid:{r['NID ID']}", val("Dam Name"), f, r["Latitude"], r["Longitude"], seg, flags, "nid",
                         {"nid_id": r["NID ID"], "river_nid": val("River or Stream Name"), "state": val("State"),
                          "height_ft": fnum("NID Height (Ft)"), "normal_storage_af": fnum("Normal Storage (Acre-Ft)"),
                          "max_storage_af": fnum("Max Storage (Acre-Ft)"), "hazard": val("Hazard Potential Classification"),
                          "year": fnum("Year Completed"), "purposes": val("Purposes"), "snap_m": round(float(dist[i]), 1)}))
    stats = {"nid_records": int(len(nid)), "nid_data_date": data_date, "major_with_coords_in_domain": int(len(d)),
             "snapped_within_500m": len(out)}
    return out, stats


def dms(v, width):
    s = str(v).strip().split(".")[0].zfill(width)
    if not s.isdigit() or int(s) == 0:
        return np.nan
    deg = int(s[:width - 6])
    mm, ss = int(s[width - 6:width - 4]), int(s[width - 4:]) / 100.0
    if mm >= 60 or ss >= 60:
        return np.nan
    return deg + mm / 60 + ss / 3600


def build_bridges(seg, geom, refresh, dom="CONUS"):
    p = cached_file(f"nbi/{NBI_YEAR}hwybronefiledel.zip", NBI_ZIP, refresh)
    with zipfile.ZipFile(p) as z:
        name = z.namelist()[0]
        cols = ["STATE_CODE_001", "STRUCTURE_NUMBER_008", "FEATURES_DESC_006A", "FACILITY_CARRIED_007",
                "LOCATION_009", "LAT_016", "LONG_017", "YEAR_BUILT_027", "ADT_029", "SERVICE_UND_042B",
                "STRUCTURE_LEN_MT_049", "RECORD_TYPE_005A"]
        nbi = pd.read_csv(z.open(name), usecols=cols, dtype=str, quotechar="'", encoding="latin-1")
    nbi = nbi.apply(lambda c: c.str.strip().str.strip("'\"").str.strip())
    w = nbi[nbi["SERVICE_UND_042B"].isin(list("5678")) & (nbi["RECORD_TYPE_005A"] == "1")].copy()
    w["lat"] = [dms(v, 8) for v in w["LAT_016"]]
    w["lon"] = [-dms(v, 9) for v in w["LONG_017"]]
    if dom == "CONUS":
        ok = w["lat"].between(24, 50) & w["lon"].between(-125.5, -66)
    else:
        w_, s_, e_, n_ = DOM_BOX[dom]
        ok = w["STATE_CODE_001"].isin(NBI_STATES[dom]) & w["lat"].between(s_, n_) & w["lon"].between(w_, e_)
    w = w[ok].reset_index(drop=True)
    if w.empty:
        return [], {"nbi_records": int(len(nbi)), "waterway_under_with_coords": 0}
    fid, dist = snap(to5070(w["lon"].values, w["lat"].values, DOM_CRS[dom]), geom, seg.index.values, BRIDGE_SNAP_M,
                     DOM_CRS[dom])
    out = []
    for i, r in w.iterrows():
        f = fid.get(i)
        if f is None or pd.isna(f):
            continue
        f = int(f)
        if seg.at[f, "order"] < BRIDGE_MIN_ORDER:
            continue
        flags = ["snap_gt_250m"] if dist[i] > BRIDGE_FLAG_M else []
        num = lambda c: None if pd.isna(pd.to_numeric(r[c], errors="coerce")) else float(pd.to_numeric(r[c], errors="coerce"))
        out.append(place("bridge", f"nbi:{r['STATE_CODE_001']}:{r['STRUCTURE_NUMBER_008']}",
                         r["FACILITY_CARRIED_007"] or None, f, r["lat"], r["lon"], seg, flags, "nbi",
                         {"over": r["FEATURES_DESC_006A"] or None, "location": r["LOCATION_009"] or None,
                          "year_built": num("YEAR_BUILT_027"), "adt": num("ADT_029"),
                          "length_m": num("STRUCTURE_LEN_MT_049"), "service_under": r["SERVICE_UND_042B"],
                          "snap_m": round(float(dist[i]), 1)}))
    stats = {"nbi_records": int(len(nbi)), "waterway_under_with_coords": int(len(w)),
             f"snapped_order_ge_{BRIDGE_MIN_ORDER}": len(out)}
    return out, stats



# ----------------------------------------------------------------------------- NextGen cross-check
NGEN_URL = "https://communityhydrofabric.s3.us-east-1.amazonaws.com/hydrofabrics/community/conus_nextgen.tar.gz"
NGEN_NOTE = ("CONUS NextGen hydrofabric (community v2.2 build, conus_nextgen.gpkg inside conus_nextgen.tar.gz; "
             "the URL used by CIROH-UA/ngiab_data_preprocess, modules/data_sources/source_validation.py). "
             "Crosswalk: `network` layer rows (id = NextGen flowpath wb-*, hf_id = reference-fabric id = NWM "
             "feature_id/NHDPlus COMID). USGS gage -> flowpath from `flowpath-attributes`.gage; RFC LIDs "
             "(hl_reference 'rfc-gage', reservoir forecast points only) and NID ids from `hydrolocations`.")


def nextgen_crosscheck(places, rl):
    """Second opinion from the NextGen hydrofabric: is the place's feature_id one of the NWM segments
    aggregated into the NextGen flowpath that the hydrofabric assigns the same gage / LID / NID id to?"""
    import sqlite3
    gpkg = os.environ.get("NEXTGEN_HYDROFABRIC_GPKG")
    if not gpkg or not Path(gpkg).exists():
        return None
    print("read    NextGen hydrofabric crosswalk", flush=True)
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    net = pd.read_sql("SELECT id, hf_id FROM network WHERE hf_id IS NOT NULL AND id LIKE 'wb-%'", con)
    members = net.assign(hf=net["hf_id"].astype(np.int64)).groupby("id")["hf"].apply(set).to_dict()
    fa = pd.read_sql("SELECT id, gage FROM \"flowpath-attributes\" WHERE gage IS NOT NULL AND gage != ''", con)
    gage_fp = dict(zip(fa["gage"].str.strip(), fa["id"]))
    hl = pd.read_sql("SELECT id, hl_link, hl_reference FROM hydrolocations "
                     "WHERE hl_reference IN ('rfc-gage', 'nid')", con)
    rfc_fp = dict(zip(hl.loc[hl.hl_reference == "rfc-gage", "hl_link"], hl.loc[hl.hl_reference == "rfc-gage", "id"]))
    nid_fp = dict(zip(hl.loc[hl.hl_reference == "nid", "hl_link"], hl.loc[hl.hl_reference == "nid", "id"]))
    con.close()
    down = dict(zip(rl["feature_id"].astype(int), rl["to"].astype(int)))

    def verdict(fid, fp):
        mem = members.get(fp)
        if fid is None or not mem:
            return None
        if fid in mem:
            return "agree"
        if down.get(fid) in mem or any(down.get(m) == fid for m in mem):
            return "adjacent"
        return "differs"

    counts = {}
    for p in places:
        e, fp = p["extra"], None
        if p["type"] == "gage":
            fp = gage_fp.get(e.get("usgs_id", e["gage_id"])) or gage_fp.get(e["gage_id"])
        elif p["type"] == "forecast_point":
            fp = rfc_fp.get(e["lid"]) or (gage_fp.get(e["usgs_id"]) if e.get("usgs_id") else None)
        elif p["type"] == "dam":
            fp = nid_fp.get(e["nid_id"])
        if fp is None:
            continue
        v = verdict(p["feature_id"], fp)
        if v is None:
            continue
        e["ngen_fp"], e["ngen"] = fp, v
        if v == "differs":
            p["flags"].append("nextgen_differs")
        counts.setdefault(p["type"], {}).setdefault(v, 0)
        counts[p["type"]][v] += 1
    return counts


def nextgen_source(gpkg: str) -> dict:
    """Provenance of the local NextGen gpkg: S3 object metadata (HEAD) + SHA-256 of the file used."""
    info = {"url": NGEN_URL, "accessed": TODAY, "note": NGEN_NOTE}
    try:
        req = urllib.request.Request(NGEN_URL, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            info.update({"last_modified": r.headers.get("Last-Modified"), "etag": r.headers.get("ETag"),
                         "tar_bytes": int(r.headers.get("Content-Length") or 0)})
    except Exception as ex:  # provenance only; the check itself uses the local file
        info["head_error"] = str(ex)
    log = Path(gpkg).with_name("download_log.json")   # written by ngiab_data_preprocess at download
    if log.exists():
        hdr = json.loads(log.read_text())
        info["local_copy_downloaded"] = hdr.get("Date")
        info["local_copy_last_modified"] = hdr.get("Last-Modified")
    tar = Path(gpkg).with_name("conus_nextgen.tar.gz")
    if tar.exists():
        info["tar_sha256_local"] = sha256(tar)
    info["gpkg_sha256_local"] = sha256(Path(gpkg))
    info["gpkg_note"] = ("SHA-256 of the extracted gpkg as used; ngiab_data_preprocess adds indexes to it, so it "
                         "can differ from a fresh extraction. tar_sha256_local is the downloaded tarball.")
    return info



# places.json budget (~10 MB): drop extra fields that repeat the key or other fields, or are
# rarely needed in the map; the CSV copy keeps every field.
# Only pure duplicates are dropped (author, 2026-10-07: "add the CSV-only fields").
JSON_DROP = {"gage": {"gage_id", "ngen_fp"},
             "forecast_point": {"ngen_fp"},
             "bridge": set()}
JSON_TRIM_NOTE = ("extra in places.json omits only duplicates: gage_id (repeated in key) and ngen_fp (the NextGen "
                  "flowpath id; its verdict is in ngen); forecast_point reach_id / gage_feature_id when equal to "
                  "feature_id; snap_m rounded to whole meters, dist_km to 0.01 km. "
                  "data/explorer/T_places.csv (gitignored, regenerated) has the same fields unrounded.")


def slim_extra(pl):
    e = {k: v for k, v in pl["extra"].items() if k not in JSON_DROP.get(pl["type"], ())}
    if "snap_m" in e:
        e["snap_m"] = int(round(e["snap_m"]))
    if "dist_km" in e:
        e["dist_km"] = round(e["dist_km"], 2)
    if pl["type"] == "forecast_point":
        for k in ("reach_id", "gage_feature_id"):
            if pl["feature_id"] is not None and e.get(k) == pl["feature_id"]:
                e.pop(k)
    return e


# ----------------------------------------------------------------------------- outputs
def summary_md(places, stats, meta):
    df = pd.DataFrame(places)
    lines = ["<!-- places:start (generated by explorer/scripts/build_places.py; edits here are overwritten) -->",
             "## Places of interest", "",
             f"`data/places.json` (built {meta['built']}; {meta['file_mb']} MB) lists locations keyed to NWM "
             "v3.1.6 RouteLink feature_ids. A CSV copy is at `data/explorer/T_places.csv`. "
             "Flags mark places whose link to the network may be wrong; they are not corrections.", "",
             "| type | places | flagged | flags (count) |", "|---|---:|---:|---|"]
    for t in ["gage", "forecast_point", "reservoir", "dam", "bridge"]:
        s = df[df["type"] == t]
        if s.empty:
            lines.append(f"| {t} | 0 | | not built |")
            continue
        fc = pd.Series([f for fl in s["flags"] for f in fl]).value_counts()
        lines.append(f"| {t} | {len(s):,} | {int((s['flags'].str.len() > 0).sum()):,} | "
                     + ", ".join(f"`{k}` {v:,}" for k, v in fc.items()) + " |")
    lines += ["", "Places per domain:", "", "| domain | gage | forecast_point | reservoir | dam | bridge |",
              "|---|---:|---:|---:|---:|---:|"]
    for d in DOMAINS:
        c = df[df["dom"] == d]["type"].value_counts()
        lines.append(f"| {d} | " + " | ".join(f"{int(c.get(t, 0)):,}" for t in
                                               ["gage", "forecast_point", "reservoir", "dam", "bridge"]) + " |")
    lines += ["", "Sources, filters and flag definitions:", ""]
    for k, v in meta["method"].items():
        lines.append(f"- **{k}**: {v}")
    lines += ["", "Flags:", ""] + [f"- `{k}`: {v}" for k, v in meta["flags"].items()]
    lines += ["", "Inputs (access date; SHA-256 of the cached copy is in `meta.sources` of `places.json`):", ""]
    for k, v in meta["sources"].items():
        extra = f", S3 Last-Modified {v['last_modified']}" if v.get("last_modified") else ""
        if v.get("local_copy_downloaded"):
            extra += f"; local copy downloaded {v['local_copy_downloaded']}"
        lines.append(f"- `{k}`: {v['url']} (accessed {v['accessed']}{extra})")
    lines += ["", "Rebuild: `NWM_HYDROFABRIC_GDB=<path to NWM_v3_hydrofabric.gdb> "
              "NEXTGEN_HYDROFABRIC_GPKG=<path to conus_nextgen.gpkg> uv run explorer/scripts/build_places.py` "
              "(both variables optional; see the script docstring).", "<!-- places:end -->"]
    return "\n".join(lines) + "\n"


def write_readme(section: str):
    README.parent.mkdir(parents=True, exist_ok=True)
    txt = README.read_text() if README.exists() else "# Basin explorer\n"
    pat = re.compile(r"<!-- places:start.*?<!-- places:end -->\n?", re.S)
    if pat.search(txt):
        txt = pat.sub(lambda _: section, txt)
    else:
        txt = txt.rstrip("\n") + "\n\n" + section
    README.write_text(txt)


FLAG_DOC = {
    "not_found": "gage id not found in the USGS Water Data API (or ECCC station list for WSC ids)",
    "id_needs_leading_zero": "7-digit RouteLink id matched a USGS site only after adding a leading zero",
    "dist_gt_2km": f"site (or forecast point) is more than {GAGE_DIST_KM:g} km from its segment",
    "da_mismatch": f"site drainage area / NHDPlusV2 TotDASqKm of the segment's COMID outside {DA_LO}-{DA_HI}",
    "inactive": f"USGS: newest discharge (00060) or stage (00065) time series ends > {INACTIVE_DAYS} days "
                "before access; WSC: station status not 'Active'",
    "no_q_or_stage_series": "USGS site has no discharge or stage time series in the Water Data API",
    "multi_segment": "same gage id on more than one RouteLink segment",
    "detail_not_found": "NWPS per-gauge endpoint returned nothing",
    "no_reach_id": "NWPS gauge has no reachId",
    "reach_not_in_routelink": "NWPS reachId is not a feature_id of the domain's RouteLink",
    "reach_differs_from_gage_segment": "NWPS reachId differs from the RouteLink segment carrying the same USGS id",
    "multiple_outlets": "more than one member segment of the waterbody drains out of it (outlet = highest order)",
    "no_outlet": "no member segment drains out of the waterbody",
    "not_in_reservoir_index": "waterbody missing from reservoir_index_*.nc",
    "no_polygon": "waterbody id missing from the domain's nwm_waterbodies_* layer",
    "snap_gt_250m": "snapped more than 250 m",
    "low_order": f"dam snapped to a segment of order < {DAM_FLAG_ORDER}",
    "nextgen_differs": "the NextGen hydrofabric puts the same gage / LID / NID id on a flowpath that neither "
                       "contains nor touches this feature_id",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download every input")
    ap.add_argument("--skip-bridges", action="store_true")
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    stats, places = {}, []
    geom_note, rl_conus = None, None
    for dom in DOMAINS:
        rl, seg = load_network(dom)
        geom, geom_note = load_geometry(dom, seg)
        if dom == "CONUS":
            rl_conus = rl
        st = stats.setdefault(dom, {})
        # RouteLink segment of each gage id (7-digit ids also under their zero-padded form)
        gl = rl[rl["gage"] != ""]
        gage_seg = dict(zip(gl["gage"], gl["feature_id"].astype(int)))
        gage_seg.update({"0" + k: v for k, v in gage_seg.items() if len(k) == 7 and k.isdigit()})
        fps, st["forecast_point"] = build_forecast_points(seg, geom, gage_seg, a.refresh, dom)
        gages, st["gage"], _ = build_gages(rl, seg, geom, a.refresh, dom)
        res, st["reservoir"] = build_reservoirs(rl, seg, a.refresh, dom)
        dams, st["dam"] = build_dams(seg, geom, a.refresh, dom)
        places += gages + fps + res + dams
        if not a.skip_bridges:
            br, st["bridge"] = build_bridges(seg, geom, a.refresh, dom)
            places += br
        print(f"{dom:6} gages {len(gages):,}  forecast points {len(fps):,}  reservoirs {len(res):,}  "
              f"dams {len(dams):,}  bridges {0 if a.skip_bridges else len(br):,}", flush=True)
    rl = rl_conus

    ngen_counts = nextgen_crosscheck([p for p in places if p["dom"] == "CONUS"], rl)
    if ngen_counts is not None:
        stats["nextgen_crosscheck"] = ngen_counts
        print(f"ngen    {ngen_counts}", flush=True)
    method = {
        "domains": "All four NWM v3.1.6 domains (CONUS, AK, HI, PRVI); each place carries `dom`. Distances and "
                   f"snapping in a projected CRS per domain: {DOM_CRS}.",
        "gage": "RouteLink_{CONUS,AK,HI,PRVI}.nc `gages` (stripped). USGS ids: name, location, drainage_area from USGS Water "
                "Data API monitoring-locations; activity from time-series-metadata (00060, 00065). WSC ids: "
                "ECCC hydrometric-stations (DRAINAGE_AREA_GROSS). Model drainage area: NHDPlusV2 TotDASqKm "
                "of COMID = feature_id from the EPA WATERS NHDPlus service (CONUS, HI, PRVI; NHDPlus V2.1), or "
                "NHDPlus HR TotalDrainageAreaSqKm of NHDPlusID = feature_id from the USGS NHDPlus HR service (AK); "
                "missing where the feature_id has no NHDPlus record (e.g. AK Arc-Hydro segments), then no DA check.",
        "forecast_point": "NWPS /gauges entries inside lon -126..-61, lat 23..51 with a forecast PEDTS, excluding "
                          "AK, HI, PR, VI, GU, AS, MP (CONUS); AK, HI, PR+VI: NWPS gauges with a forecast PEDTS in "
                          f"the domain's state(s) {NWPS_STATES} and inside the domain box {DOM_BOX} (the NWM "
                          "Alaska domain covers Cook Inlet and the Copper River only); "
                          "reachId and usgsId from /gauges/{lid}.",
        "reservoir": "One place per RouteLink NHDWaterbodyComID; feature_id = outlet member (its `to` leaves "
                     "the waterbody); lat/lon = polygon centroid (nwm_waterbodies_{conus,alaska,hawaii}; "
                     "PRVI has no waterbody layer, so its places sit on the outlet segment), area from the polygon "
                     "in an equal-area/projected CRS; name = NHDPlusV2 waterbody GNIS_NAME (EPA WATERS layer 4; "
                     "CONUS, HI, PRVI) or NHDPlus HR NHDWaterbody GNIS_Name (layer 9; AK); "
                     "res_type from reservoir_index_AnA.nc (CONUS) or reservoir_index_GDL_AK.nc (AK; HI and PRVI "
                     "have no reservoir index) (codes per " + RES_TYPE_DOC + ").",
        "dam": f"NID national CSV; major = {MAJOR_DAM}; snapped to nearest segment of order >= {DAM_MIN_ORDER} "
               f"within {DAM_SNAP_M:g} m (domain CRS); dams outside the domain box or farther away are omitted.",
        "bridge": f"NBI {NBI_YEAR} delimited file, record type 1, Item 42B (service under) in 5-8 (waterway, "
                  f"highway-waterway, railroad-waterway, highway-waterway-railroad; 9 'relief' excluded); "
                  f"lat/lon decoded from Items 16/17 (DDMMSSss, DDDMMSSss, west longitude; coding guide "
                  f"{NBI_GUIDE}); AK, HI, PR+VI: state codes {NBI_STATES} inside the domain box; snapped to the nearest segment of any order within {BRIDGE_SNAP_M:g} m and kept "
                  f"if that segment has order >= {BRIDGE_MIN_ORDER}.",
        "segment_geometry": geom_note,
        "nhdplus_hr_service": (f"USGS NHDPlus HR map service ({HR_NHDP}) probe on {HR_STATUS.get('checked')}: "
                               + ("available" if HR_STATUS.get("ok") else f"unavailable ({HR_STATUS.get('error')}); AK gage "
                                  "drainage-area checks and AK waterbody names were not done") if HR_STATUS else "not needed (cached)"),
        "nextgen_crosscheck": (NGEN_NOTE + " Verdict per place in extra.ngen: agree (feature_id is in the "
                               "flowpath), adjacent (feature_id is directly up/downstream of it), differs."
                               if ngen_counts is not None else
                               "not run (set NEXTGEN_HYDROFABRIC_GPKG to a local conus_nextgen.gpkg from "
                               + NGEN_URL + ")"),
    }
    meta = {"built": TODAY, "routelink": "NWM v3.1.6 RouteLink_{CONUS,AK,HI,PRVI}.nc", "geometry": geom_note,
            "contract": "explorer/DATA_CONTRACT.md", "method": method, "flags": FLAG_DOC, "stats": stats,
            "sources": {**load_sources(),
                        **({"nextgen/conus_nextgen.gpkg (local, not cached)": nextgen_source(
                            os.environ["NEXTGEN_HYDROFABRIC_GPKG"])} if ngen_counts is not None else {})},
            "fields": "dom = NWM domain; net = listed network code or 0; river = innermost listed river code (rivers.json); "
                      "order = RouteLink Strahler order; lat/lon WGS84/NAD83 degrees, 5 decimals"}
    meta["json_extra_trim"] = JSON_TRIM_NOTE
    slim = [{**pl, "extra": slim_extra(pl)} for pl in places]
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({"meta": meta, "places": slim}, separators=(",", ":"), ensure_ascii=False))
    meta["file_mb"] = round(OUT_JSON.stat().st_size / 1e6, 2)
    OUT_JSON.write_text(json.dumps({"meta": meta, "places": slim}, separators=(",", ":"), ensure_ascii=False))

    df = pd.DataFrame(places)
    df["flags"] = df["flags"].map(";".join)
    df["extra"] = df["extra"].map(lambda e: json.dumps(e, separators=(",", ":"), ensure_ascii=False))
    df["feature_id"] = df["feature_id"].astype("Int64")
    df["order"] = df["order"].astype("Int64")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    write_readme(summary_md(places, stats, meta))
    print(json.dumps(stats, indent=1, default=str))
    print(f"wrote {OUT_JSON} ({meta['file_mb']} MB), {OUT_CSV}, {README}")


if __name__ == "__main__":
    main()
