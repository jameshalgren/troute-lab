"""Full NWM domain (CONUS, AK, HI, PRVI): network names, lake-outlet names, more sub-rivers.

Runs after analyze.py (reads results/networks_<DOMAIN>.csv) and subrivers.py.

    uv run --locked python domains.py            # offline: uses domains_snapshot.json (release asset)
    uv run --locked python domains.py --refresh  # live queries + GNIS download; rewrites the snapshot

1. NAMES of the top networks of AK (200), HI (100) and PRVI (100).
   * HI and PRVI: feature_ids are NHDPlus V2.1 COMIDs (VPUs 20, 21). The rule of
     river_names.py: on the NHDPlus level path (mainstem) through the outlet, `name` is the
     first non-blank GNIS name going upstream and `mainstem_name` the most frequent one
     (EPA WATERS NHDPlus V2.1 MapServer).
   * AK: feature_ids are NHDPlus HR NHDPlusIDs (Cook Inlet) or Arc-Hydro segments (Copper
     River, IDs 190201xxxxxxxx; RouteLink_AK.nc processing_notes). The USGS NHDPlus HR map
     service was unusable when this was built (HTTP 502/504, > 100 s per query, 2026-10-07),
     so AK names come from the USGS GNIS Domestic Names file (national text file, "Stream"
     features with mouth = primary point and source = source point): a GNIS stream names a
     network if its mouth lies within MOUTH_KM of the outlet segment's RouteLink point and its
     source lies within SOURCE_KM of a segment of the network; of several, the one with the
     longest mouth-source distance. No match: UNVERIFIED.
2. LAKE-OUTLET NAMES (all four domains; CONUS top 500). The author noted that the network
   named "Tchefuncte River" drains Lake Pontchartrain and all its tributaries. (Cause: in
   NHDPlus V2 the artificial paths through Lake Pontchartrain carry the GNIS name "Tchefuncte
   River", and the lake polygon has no GNIS name.) Rule:
     a. Walk upstream from the outlet along the RouteLink mainstem (at each junction the
        upstream segment with the most segments above it) for at most LAKE_WALK segments.
     b. Each RouteLink waterbody met (NHDWaterbodyComID != -9999; the author: "isn't
        particularly well curated") is a candidate lake L, in walk order. Its drainage D =
        the segments upstream of (and including) the first lake segment on the walk.
     c. L captures the network if D >= LAKE_MIN_DRAIN of the network, L has >= 2 inflows
        (segments outside L flowing into L) with >= LAKE_MIN_SHARE of D each, and its largest
        inflow has < LAKE_MAX_SHARE of D.
     d. ... and the network's level-path name is the name of one of L's inflows (the name
        was taken from a river upstream of the lake, the Tchefuncte case) or is UNVERIFIED.
        A network named for the lake's outflow (e.g. Jordan River below Utah Lake) keeps it.
     e. New name: "<lake name> (<inflow 1>, <inflow 2>, ...)", inflows with
        >= LABEL_MIN_SHARE of D, largest first (at most LABEL_MAX). An inflow is labeled by
        the most frequent GNIS name on its NHDPlus level path upstream of the inflow point
        (AK: the GNIS stream rule of 1). Lake name: NHDPlus V2.1 waterbody GNIS name (EPA
        layer 4); if blank (Lake Pontchartrain) or AK, the nearest GNIS Lake / Reservoir / Bay /
        Swamp point to the centroid of the lake's RouteLink segment points within
        max(LAKE_GNIS_KM, the spread of those points); flagged `lake_name_from_gnis_point`.
     f. Other flags (uncertain cases): lake_unnamed (keeps its name), tributary_below_lake (a
        tributary with >= BELOW_FLAG_SHARE of the network joins between outlet and lake),
        inflow_unnamed.
   `display_name` is the name to show; `river_name` is unchanged, so older checks still hold.
3. SUB-RIVERS for AK, HI and PRVI (EXT_CANDIDATES). HI and PRVI: subrivers.py's rules
   (resolve(), components(), follow()). AK: GNIS points: candidate mouth segments lie within
   SUB_MOUTH_KM of the GNIS mouth point (inside the parent's subtree); a candidate is valid
   if a segment within SOURCE_KM of the GNIS source point lies upstream of it; the valid
   candidate with the smallest subtree is the river's lowest segment, extended downstream
   through segments with a single upstream segment (no other inflow). Status "gnis_points".

Outputs: results/T_basins.csv (adds display_name, name_rule, name_note, name_source),
         results/T_basins_{AK,HI,PRVI}.csv, results/lake_renames.csv,
         results/T_subrivers_ext.csv, results/domains.json (checked by check.py).
Snapshot: domains_snapshot.json (release asset; ../../tools/fetch_bundle.py network-stats): every EPA query answer used, keyed by query,
         and every GNIS feature any lookup returned (with the national file's URL, access
         date and SHA-256); its own SHA-256 is recorded in expected/domains_expected.json.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

import subrivers as sr
from analyze import BIG_ID, DATA, RESULTS, WB_MISSING, classify, load

HERE = Path(__file__).resolve().parent
SNAP = HERE / "domains_snapshot.json"
EPA = "https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer"
GNIS_URL = "https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/DomesticNames/DomesticNames_National_Text.zip"
GNIS_ZIP = DATA / "gnis" / "DomesticNames_National_Text.zip"
GNIS_CLASSES = {"Stream", "Lake", "Reservoir", "Bay", "Swamp"}
LAKE_CLASSES = {"Lake", "Reservoir", "Bay", "Swamp"}
N_TOP = {"CONUS": 500, "AK": 200, "HI": 100, "PRVI": 100}
LAKE_WALK = 50
LAKE_MIN_DRAIN = 0.5
LAKE_MAX_SHARE = 0.75
LAKE_MIN_SHARE = 0.05
LABEL_MIN_SHARE = 0.05
LABEL_MAX = 5
BELOW_FLAG_SHARE = 0.20
LAKE_GNIS_KM = 3.0
CONF_WALK = 10        # outlet-confluence rule: junctions within this many mainstem segments of the outlet
CONF_MIN_SHARE = 0.15  # ... where at least two branches each hold this share of the network
CONF_WATER_WALK = 10  # a water body this close to the outlet names a renamed confluence
# Water bodies the author asked about: (label, GNIS name, GNIS class, state, radius km around the GNIS point)
BAYS = [("Galveston Bay", "Galveston Bay", "Bay", "Texas", 35), ("Sabine Lake", "Sabine Lake", "Lake", "Texas", 25),
        ("Lake Pontchartrain", "Lake Pontchartrain", "Lake", "Louisiana", 40), ("Mobile Bay", "Mobile Bay", "Bay", "Alabama", 45),
        ("Chesapeake Bay", "Chesapeake Bay", "Bay", "Maryland", 150), ("Delaware Bay", "Delaware Bay", "Bay", "Delaware", 60),
        ("San Francisco Bay", "San Francisco Bay", "Bay", "California", 60), ("Puget Sound", "Puget Sound", "Bay", "Washington", 100),
        ("Pamlico Sound", "Pamlico Sound", "Bay", "North Carolina", 80), ("Albemarle Sound", "Albemarle Sound", "Bay", "North Carolina", 60),
        ("Lake Okeechobee", "Lake Okeechobee", "Lake", "Florida", 40), ("Great Salt Lake", "Great Salt Lake", "Lake", "Utah", 70),
        ("Lake Tahoe", "Lake Tahoe", "Lake", "California", 20)]
WATER_FTYPES = {390: "LakePond", 436: "Reservoir", 493: "Estuary"}   # NHDPlus WBArea_FType counted as water bodies
BAD_NAME = __import__("re").compile(r"^[A-Za-z]{2,6}\d{3,}$")      # NHDPlus V2.1 HI placeholders, e.g. 'Ke360959'


def valid_name(n) -> bool:
    return isinstance(n, str) and bool(n.strip()) and not BAD_NAME.match(n.strip())
MOUTH_KM = 10.0       # AK: GNIS mouth point to the network's nearest segment
SUB_MOUTH_KM = 5.0    # AK sub-rivers / lake inflows: GNIS mouth point to candidate mouth segments
SOURCE_KM = 25.0      # AK: GNIS source point to the nearest RouteLink segment (sources are often on glaciers)
NAME_MIN_SHARE = 0.5  # AK: a GNIS stream names a network if it drains at least this share of it
EPA_F = dict(fl=2, wb=4, id="comid", lp="levelpathid", hs="hydroseq", term="terminalflag", dn="dnhydroseq",
             da="totdasqkm", vpu="vpuid")
DOM_VPU = {"CONUS": None, "HI": "20", "PRVI": "21"}
DOM_STATE = {"AK": {"Alaska"}, "HI": {"Hawaii"}, "PRVI": {"Puerto Rico", "U.S. Virgin Islands", "Virgin Islands"}}

C = sr.C
# Sub-rivers and primary rivers outside CONUS. Names are exact GNIS names (EPA NHDPlus V2.1
# for HI and PRVI; GNIS Domestic Names for AK); boxes (lat_min, lat_max, lon_min, lon_max)
# separate same-named rivers.
EXT_CANDIDATES = {
    "AK": [
        C("ak_susitna", "Susitna", ["Susitna River"], None, "AI", ["19"], "Alaska", kind="primary"),
        C("ak_copper", "Copper", ["Copper River"], None, "AI", ["19"], "Alaska", kind="primary"),
        C("ak_matanuska", "Matanuska", ["Matanuska River"], None, "AI", ["19"], "Alaska", kind="primary"),
        C("ak_knik", "Knik", ["Knik River"], None, "AI", ["19"], "Alaska", kind="primary"),
        C("ak_kenai", "Kenai", ["Kenai River"], None, "AI", ["19"], "Alaska", kind="primary"),
        C("ak_little_susitna", "Little Susitna", ["Little Susitna River"], None, "AI", ["19"], "Alaska",
          kind="primary"),
        C("ak_kasilof", "Kasilof", ["Kasilof River"], None, "AI", ["19"], "Alaska", kind="primary"),
        C("ak_yentna", "Yentna", ["Yentna River"], "ak_susitna", "AI", ["19"], "Alaska"),
        C("ak_skwentna", "Skwentna", ["Skwentna River"], "ak_yentna", "AI", ["19"], "Alaska"),
        C("ak_chulitna", "Chulitna", ["Chulitna River"], "ak_susitna", "AI", ["19"], "Alaska"),
        C("ak_talkeetna", "Talkeetna", ["Talkeetna River"], "ak_susitna", "AI", ["19"], "Alaska"),
        C("ak_deshka", "Deshka", ["Deshka River"], "ak_susitna", "AI", ["19"], "Alaska"),
        C("ak_chitina", "Chitina", ["Chitina River"], "ak_copper", "AI", ["19"], "Alaska"),
        C("ak_gulkana", "Gulkana", ["Gulkana River"], "ak_copper", "AI", ["19"], "Alaska"),
        C("ak_tazlina", "Tazlina", ["Tazlina River"], "ak_copper", "AI", ["19"], "Alaska"),
        C("ak_klutina", "Klutina", ["Klutina River"], "ak_copper", "AI", ["19"], "Alaska"),
        C("ak_tonsina", "Tonsina", ["Tonsina River"], "ak_copper", "AI", ["19"], "Alaska"),
    ],
    "HI": [
        C("hi_waimea", "Waimea (Kauaʻi)", ["Waimea River"], None, "AI", ["20"], "Hawaii", kind="primary",
          box=(21.8, 22.3, -159.85, -159.25)),
        C("hi_makaweli", "Makaweli", ["Makaweli River"], "hi_waimea", "AI", ["20"], "Hawaii"),
        C("hi_wailua", "Wailua (Kauaʻi)", ["Wailua River"], None, "AI", ["20"], "Hawaii", kind="primary",
          box=(21.8, 22.3, -159.85, -159.25)),
        C("hi_hanalei", "Hanalei", ["Hanalei River"], None, "AI", ["20"], "Hawaii", kind="primary"),
        C("hi_hanapepe", "Hanapepe", ["Hanapepe River"], None, "AI", ["20"], "Hawaii", kind="primary"),
        C("hi_wainiha", "Wainiha", ["Wainiha River"], None, "AI", ["20"], "Hawaii", kind="primary"),
        C("hi_wailuku", "Wailuku (Hilo)", ["Wailuku River"], None, "AI", ["20"], "Hawaii", kind="primary",
          box=(19.5, 20.0, -155.6, -155.0)),
        C("hi_kaukonahua", "Kaukonahua (Oʻahu)", ["Kaukonahua Stream"], None, "AI", ["20"], "Hawaii",
          kind="primary"),
    ],
    "PRVI": [
        C("pr_loiza", "Río Grande de Loíza", ["Río Grande De Loiza"], None, "AI", ["21"], "Puerto Rico",
          kind="primary"),
        C("pr_gurabo", "Río Gurabo", ["Río Gurabo"], "pr_loiza", "AI", ["21"], "Puerto Rico"),
        C("pr_plata", "Río de la Plata", ["Río de la Plata"], None, "AI", ["21"], "Puerto Rico", kind="primary"),
        C("pr_arecibo", "Río Grande de Arecibo", ["Río Grande de Arecibo"], None, "AI", ["21"], "Puerto Rico",
          kind="primary"),
        C("pr_caonillas", "Río Caonillas", ["Río Caonillas"], "pr_arecibo", "AI", ["21"], "Puerto Rico"),
        C("pr_anasco", "Río Grande de Añasco", ["Río Grande de Añasco"], None, "AI", ["21"], "Puerto Rico",
          kind="primary"),
        C("pr_manati", "Río Grande de Manatí", ["Río Grande de Manati"], None, "AI", ["21"], "Puerto Rico",
          kind="primary"),
        C("pr_culebrinas", "Río Culebrinas", ["Río Culebrinas"], None, "AI", ["21"], "Puerto Rico", kind="primary"),
        C("pr_guanajibo", "Río Guanajibo", ["Río Guanajibo"], None, "AI", ["21"], "Puerto Rico", kind="primary"),
        C("pr_cibuco", "Río Cibuco", ["Río Cibuco"], None, "AI", ["21"], "Puerto Rico", kind="primary"),
    ],
}


# every candidate name counts as "known" to subrivers.follow() (rule b), whatever the domain
# order, so the resolution (and the snapshot queries it makes) is deterministic
for _cands in EXT_CANDIDATES.values():
    for _c in _cands:
        sr.CAND[_c["key"]] = _c
        sr.KNOWN.update(_c["names"])


# ----------------------------------------------------------------------------- snapshot
def _get(url: str, tries: int = 6, timeout: int = 300) -> dict:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "troute-paper-repro/1.0 (read-only)"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry ({str(e)[:120]})", file=sys.stderr, flush=True)
            time.sleep(min(60, 5 * (i + 1)))
    raise RuntimeError(url)


def km(lat0, lon0, lat, lon):
    """Local equirectangular distance in km (fine for the few-km radii used here)."""
    return np.hypot((np.asarray(lon) - lon0) * np.cos(np.radians(lat0)) * 111.32, (np.asarray(lat) - lat0) * 110.57)


class Snap:
    """EPA query answers and GNIS features: live (refresh, recorded) or from domains_snapshot.json."""

    def __init__(self, refresh: bool, resume: bool = False):
        self.refresh = refresh
        if refresh and resume and SNAP.exists():
            self.s = json.loads(SNAP.read_text())
            self.s["generated"] = dt.date.today().isoformat()
        elif refresh:
            self.s = {"generated": dt.date.today().isoformat(), "services": {"epa": EPA}, "queries": {},
                      "gnis": {"url": GNIS_URL, "features": {}}}
        else:
            if not SNAP.exists():
                raise SystemExit(f"{SNAP.name} missing; run `python ../../tools/fetch_bundle.py network-stats` (or `domains.py --refresh`)")
            self.s = json.loads(SNAP.read_text())
        self.s.setdefault("gnis", {"url": GNIS_URL, "features": {}})
        self._gnis = None
        self.used: set[str] = set()

    # ---- EPA WATERS (ArcGIS REST)
    def query(self, layer: int, where: str, fields: str) -> list[dict]:
        key = f"epa/{layer}?where={where}&outFields={fields}"
        q = self.s["queries"]
        self.used.add(key)
        if key not in q:
            if not self.refresh:
                raise SystemExit(f"query not in {SNAP.name}: {key[:160]}; run `domains.py --refresh`")
            base = f"{EPA}/{layer}/query?"
            n = _get(base + urllib.parse.urlencode({"where": where, "returnCountOnly": "true", "f": "json"}))["count"]
            rows, off = [], 0
            while off < n:
                d = _get(base + urllib.parse.urlencode({
                    "where": where, "outFields": fields, "returnGeometry": "false", "orderByFields": "OBJECTID",
                    "resultOffset": off, "resultRecordCount": 1000, "f": "json"}))
                got = [[f["attributes"].get(k) for k in fields.split(",")] for f in d["features"]]
                if not got:
                    break
                rows += got
                off += len(got)
            if len(rows) != n:
                raise SystemExit(f"{key}: got {len(rows)} of {n} rows (truncated)")
            q[key] = {"count": n, "rows": rows}
        cols = fields.split(",")
        return [dict(zip(cols, r)) for r in q[key]["rows"]]

    # ---- GNIS Domestic Names (national text file)
    def _gnis_table(self) -> pd.DataFrame:
        if self._gnis is not None:
            return self._gnis
        if self.refresh:
            if not GNIS_ZIP.exists():
                GNIS_ZIP.parent.mkdir(parents=True, exist_ok=True)
                print(f"fetch {GNIS_URL}", flush=True)
                req = urllib.request.Request(GNIS_URL, headers={"User-Agent": "troute-paper-repro/1.0 (read-only)"})
                with urllib.request.urlopen(req, timeout=900) as r:
                    GNIS_ZIP.write_bytes(r.read())
            z = zipfile.ZipFile(GNIS_ZIP)
            name = next(n for n in z.namelist() if n.endswith(".txt"))
            t = pd.read_csv(io.TextIOWrapper(z.open(name), encoding="utf-8-sig"), sep="|", dtype=str,
                            usecols=["feature_id", "feature_name", "feature_class", "state_name", "prim_lat_dec",
                                     "prim_long_dec", "source_lat_dec", "source_long_dec"])
            t = t[t["feature_class"].isin(GNIS_CLASSES)].copy()
            for c in ("prim_lat_dec", "prim_long_dec", "source_lat_dec", "source_long_dec"):
                t[c] = pd.to_numeric(t[c], errors="coerce")
            t = t[t["prim_lat_dec"].notna() & (t["prim_lat_dec"] != 0)]
            g = self.s["gnis"]
            g.update(url=GNIS_URL, accessed=dt.date.today().isoformat(),
                     sha256=hashlib.sha256(GNIS_ZIP.read_bytes()).hexdigest(), file=name,
                     classes=sorted(GNIS_CLASSES))
        else:
            rows = [[k, *v] for k, v in self.s["gnis"]["features"].items()]
            t = pd.DataFrame(rows, columns=["feature_id", "feature_name", "feature_class", "state_name", "prim_lat_dec",
                                            "prim_long_dec", "source_lat_dec", "source_long_dec"])
        t = t.reset_index(drop=True)
        self._gnis = t
        return t

    def _keep(self, t: pd.DataFrame) -> pd.DataFrame:
        if self.refresh:
            f = self.s["gnis"]["features"]
            for r in t.itertuples(index=False):
                f[str(r.feature_id)] = [r.feature_name, r.feature_class, r.state_name,
                                        *[None if pd.isna(v) else round(float(v), 7) for v in
                                          (r.prim_lat_dec, r.prim_long_dec, r.source_lat_dec, r.source_long_dec)]]
        return t

    def gnis_near(self, lat: float, lon: float, radius_km: float, classes: set[str]) -> pd.DataFrame:
        t = self._gnis_table()
        dlat = radius_km / 110.0
        dlon = radius_km / (111.0 * max(0.2, np.cos(np.radians(lat))))
        m = (t["prim_lat_dec"].between(lat - dlat, lat + dlat) & t["prim_long_dec"].between(lon - dlon, lon + dlon)
             & t["feature_class"].isin(classes))
        c = t[m].copy()
        c["dist_km"] = km(lat, lon, c["prim_lat_dec"].to_numpy(), c["prim_long_dec"].to_numpy())
        c = c[c["dist_km"] <= radius_km]
        return self._keep(c.drop(columns="dist_km")).assign(dist_km=c["dist_km"])

    def gnis_box(self, bbox, classes: set[str], states: set[str]) -> pd.DataFrame:
        t = self._gnis_table()
        w, s_, e, n = bbox
        m = (t["prim_long_dec"].between(w, e) & t["prim_lat_dec"].between(s_, n) & t["feature_class"].isin(classes)
             & t["state_name"].isin(states))
        return self._keep(t[m])

    def gnis_named(self, name: str, states: set[str], classes: set[str]) -> pd.DataFrame:
        t = self._gnis_table()
        return self._keep(t[(t["feature_name"] == name) & t["state_name"].isin(states) & t["feature_class"].isin(classes)])

    def save(self) -> None:
        self.s["_about"] = (
            "Snapshot used by domains.py. queries: EPA WATERS NHDPlus V2.1 MapServer answers, key = epa/layer?where&"
            "outFields -> count (returnCountOnly) and rows (values in outFields order). gnis: every feature of the "
            "USGS GNIS Domestic Names national text file (classes Stream, Lake, Reservoir, Bay, Swamp) that a lookup "
            "returned: id -> [name, class, state, prim_lat, prim_lon, source_lat, source_lon]; url, access date and "
            "SHA-256 of the zip used.")
        g = self.s["gnis"]
        g["features"] = dict(sorted(g["features"].items(), key=lambda kv: int(kv[0])))
        lines = ["{"]
        for k in ("_about", "generated", "services"):
            lines.append(f"{json.dumps(k)}: {json.dumps(self.s[k], ensure_ascii=False)},")
        meta = {k: v for k, v in g.items() if k != "features"}
        feats = ",\n".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                            for k, v in g["features"].items())
        lines.append(f'"gnis": {{"meta": {json.dumps(meta, ensure_ascii=False)}, "features": {{\n{feats}\n}}}},')
        items = [f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                 for k, v in sorted(self.s["queries"].items()) if k in self.used]   # unused answers are dropped
        lines.append('"queries": {\n' + ",\n".join(items) + "\n}")
        lines.append("}")
        SNAP.write_text("\n".join(lines) + "\n")


def _norm_snapshot(s: dict) -> dict:
    """The saved file nests gnis as {meta, features}; accept both layouts."""
    g = s.get("gnis", {})
    if "meta" in g:
        s["gnis"] = {**g["meta"], "features": g["features"]}
    return s


# ----------------------------------------------------------------------------- hydrography lookups
class Hydro:
    """Per-domain lookups. CONUS/HI/PRVI: NHDPlus V2.1 attributes (EPA). AK: GNIS points."""

    def __init__(self, snap: Snap, dom: str, d: dict, g: sr.Net):
        self.snap, self.dom, self.d, self.g = snap, dom, d, g
        self._attrs: dict[int, dict | None] = {}
        self.lat, self.lon = d["lat"].astype(float), d["lon"].astype(float)
        if dom == "AK":   # grid of segment points for radius queries
            self.cell = 0.05
            key = collections.defaultdict(list)
            for i, (a, b) in enumerate(zip(np.floor(self.lat / self.cell).astype(int), np.floor(self.lon / self.cell).astype(int))):
                key[(a, b)].append(i)
            self.grid = {k: np.asarray(v) for k, v in key.items()}

    def in_service(self, fid: int) -> bool:
        if self.dom == "CONUS":
            return fid < BIG_ID
        return self.dom in ("HI", "PRVI")

    def seg_near(self, lat: float, lon: float, radius_km: float) -> np.ndarray:
        n = int(np.ceil(radius_km / (self.cell * 55))) + 1
        a0, b0 = int(np.floor(lat / self.cell)), int(np.floor(lon / self.cell))
        c = [self.grid.get((a0 + i, b0 + j)) for i in range(-n, n + 1) for j in range(-2 * n, 2 * n + 1)]
        c = np.concatenate([x for x in c if x is not None]) if any(x is not None for x in c) else np.zeros(0, int)
        return c[km(lat, lon, self.lat[c], self.lon[c]) <= radius_km]

    def attrs(self, fids) -> dict[int, dict | None]:
        f = EPA_F
        need = sorted({int(x) for x in fids if int(x) not in self._attrs and self.in_service(int(x))})
        flds = ",".join([f["id"], "gnis_name", f["lp"], f["hs"], f["term"], f["dn"], f["da"], f["vpu"],
                         "wbareacomid", "wbarea_ftype"])
        for k in range(0, len(need), 100):
            chunk = need[k:k + 100]
            got = {int(r[f["id"]]): r for r in self.snap.query(f["fl"], f"{f['id']} IN ({','.join(map(str, chunk))})", flds)}
            for c in chunk:
                r = got.get(c)
                self._attrs[c] = None if r is None else {
                    "name": (r["gnis_name"] or "").strip(), "lp": int(r[f["lp"]] or 0) or None,
                    "hs": float(r[f["hs"]] or 0), "term": r[f["term"]], "dn": float(r[f["dn"]] or 0),
                    "da": r[f["da"]], "vpu": r[f["vpu"]], "wbarea": int(r["wbareacomid"] or 0),
                    "wbarea_ftype": r["wbarea_ftype"]}
        return {int(x): self._attrs.get(int(x)) for x in fids}

    def levelpath_rows(self, lps) -> dict[int, list[dict]]:
        f = EPA_F
        out = collections.defaultdict(list)
        lps = sorted({int(x) for x in lps if x})
        for k in range(0, len(lps), 20):
            chunk = lps[k:k + 20]
            for r in self.snap.query(f["fl"], f"{f['lp']} IN ({','.join(map(str, chunk))})", f"gnis_name,{f['hs']},{f['lp']}"):
                out[int(r[f["lp"]])].append({"name": (r["gnis_name"] or "").strip(), "hs": float(r[f["hs"]] or 0)})
        return out

    def water_of(self, idxs) -> dict[int, int]:
        """Water body of each segment index: RouteLink NHDWaterbodyComID, else (CONUS/HI/PRVI) the
        NHDPlus flowline's WBAreaComID when that area is a LakePond, Reservoir or Estuary."""
        wb = self.d["wb"]
        out = {int(i): int(wb[i]) for i in idxs if wb[i] != WB_MISSING}
        rest = [int(i) for i in idxs if int(i) not in out]
        if rest and self.dom != "AK":
            a = self.attrs([int(self.g.link[i]) for i in rest])
            for i in rest:
                x = a[int(self.g.link[i])]
                if x and x["wbarea"] and x["wbarea_ftype"] in WATER_FTYPES:
                    out[i] = x["wbarea"]
        return out

    def members(self, start: int, W: int) -> np.ndarray:
        """Segments of water body W connected to segment `start`, found walking upstream."""
        g = self.g
        mem, front = {int(start)}, [int(start)]
        while front:
            ups = [int(u) for x in front for u in g.up_order[g.up_ptr[x]:g.up_ptr[x + 1]]]
            w = self.water_of(ups)
            front = [u for u in ups if w.get(u) == W and u not in mem]
            mem.update(front)
        return np.array(sorted(mem))

    def ftype_of_hydroseq(self, hss) -> dict[float, object]:
        f = EPA_F
        hss = sorted({int(h) for h in hss if h})
        out = {}
        for k in range(0, len(hss), 100):
            chunk = hss[k:k + 100]
            for r in self.snap.query(f["fl"], f"{f['hs']} IN ({','.join(map(str, chunk))})", f"{f['hs']},ftype"):
                out[float(r[f["hs"]])] = r["ftype"]
        return out

    def waterbody_name(self, wb: int, members: np.ndarray) -> tuple[str, str]:
        """(name, source) of a RouteLink waterbody: NHDPlus V2.1 GNIS name, else nearest GNIS point."""
        if self.dom != "AK" and wb > 100:
            rows = self.snap.query(EPA_F["wb"], f"comid IN ({int(wb)})", "comid,gnis_name,ftype")
            nm = (rows[0]["gnis_name"] or "").strip() if rows else ""
            if valid_name(nm):
                return nm, "nhdplus_waterbody"
        la, lo = self.lat[members].astype(float), self.lon[members].astype(float)
        L = self.d["length_m"][members].astype(float)
        c_lat, c_lon = float(np.average(la, weights=L)), float(np.average(lo, weights=L))
        spread = float(km(c_lat, c_lon, la, lo).max()) if len(la) else 0.0
        c = self.snap.gnis_near(c_lat, c_lon, max(LAKE_GNIS_KM, spread), LAKE_CLASSES)
        c = c[[valid_name(n) for n in c["feature_name"]]]
        if c.empty:
            return "", ""
        # vote: each member segment's length goes to the nearest GNIS point; most length wins
        c = c.sort_values("feature_id").reset_index(drop=True)
        d = np.stack([km(la, lo, la * 0 + r.prim_lat_dec, lo * 0 + r.prim_long_dec) for r in c.itertuples()])
        votes = np.bincount(d.argmin(axis=0), weights=L, minlength=len(c))
        b = c.iloc[int(np.argmax(votes))]
        share = votes.max() / votes.sum()
        return str(b["feature_name"]), (f"gnis_point:{b['feature_id']} ({b['feature_class']}; nearest GNIS point to "
                                        f"{100 * share:.0f}% of the water body's channel length)")

    def name_comids(self, name: str) -> dict[str, list[int]]:   # subrivers.Gnis interface (HI, PRVI)
        f = EPA_F
        safe = name.replace("'", "''")
        by = collections.defaultdict(list)
        for r in self.snap.query(f["fl"], f"gnis_name='{safe}' AND {f['vpu']}='{DOM_VPU[self.dom]}'", f"{f['id']},{f['vpu']}"):
            by[str(r[f["vpu"]])].append(int(r[f["id"]]))
        return {k: sorted(v) for k, v in by.items()}

    def comid_attrs(self, comids):
        a = self.attrs(comids)
        return {c: (None if a[int(c)] is None else (a[int(c)]["name"], a[int(c)]["lp"], a[int(c)]["da"])) for c in comids}

    def levelpath_names(self, lp):
        rows = self.levelpath_rows([lp]).get(int(lp), [])
        return dict(collections.Counter(r["name"] for r in rows).most_common())

    # ---- AK: GNIS stream points
    def nearest_seg(self, lat: float, lon: float, radius_km: float, among: np.ndarray | None = None) -> int | None:
        c = self.seg_near(lat, lon, radius_km)
        if among is not None and len(c):
            c = c[among[c]]
        if not len(c):
            return None
        return int(c[np.argmin(km(lat, lon, self.lat[c], self.lon[c]))])

    def ak_streams(self) -> pd.DataFrame:
        """GNIS streams of the AK domain with the segment nearest their source (SOURCE_KM)."""
        if getattr(self, "_streams", None) is None:
            b = (float(self.lon.min()) - 0.3, float(self.lat.min()) - 0.3, float(self.lon.max()) + 0.3, float(self.lat.max()) + 0.3)
            t = self.snap.gnis_box(b, {"Stream"}, DOM_STATE["AK"]).copy().sort_values("feature_id").reset_index(drop=True)
            t = t[t["source_lat_dec"].notna() & (t["source_lat_dec"] != 0)]
            t["s_seg"] = [self.nearest_seg(float(a), float(o), SOURCE_KM) for a, o in zip(t["source_lat_dec"], t["source_long_dec"])]
            self._streams = t[t["s_seg"].notna()].astype({"s_seg": int}).reset_index(drop=True)
        return self._streams

    def gnis_mouth_seg(self, r, root: int | None = None, radius: float = SUB_MOUTH_KM) -> int | None:
        """Lowest segment of GNIS stream r: among segments within `radius` of its mouth point that
        have its source segment upstream (and lie inside `root`'s subtree if given), the one with
        the smallest subtree, extended downstream through single-inflow segments."""
        g = self.g
        sseg = int(r.s_seg)
        c = self.seg_near(float(r.prim_lat_dec), float(r.prim_long_dec), radius)
        if not len(c):
            return None
        c = c[(g.tin[sseg] >= g.tin[c]) & (g.tin[sseg] < g.tin[c] + g.size[c])]
        if root is not None and len(c):
            c = c[g.in_subtree(c, root)]
        if not len(c):
            return None
        m = int(c[np.lexsort((g.link[c], g.size[c]))[0]])
        while g.ds[m] >= 0 and g.indeg[g.ds[m]] == 1 and (root is None or g.in_subtree(np.array([g.ds[m]]), root)[0]):
            m = int(g.ds[m])
        return m

    def gnis_name_for(self, root: int, min_share: float) -> tuple[str | None, str]:
        """GNIS stream whose source drains to `root` and whose lowest segment (mouth within
        MOUTH_KM, inside the subtree) drains the largest share of root's subtree (>= min_share)."""
        g = self.g
        t = self.ak_streams()
        lo, hi = g.tin[root], g.tin[root] + g.size[root]
        inside = t[(g.tin[t["s_seg"].to_numpy()] >= lo) & (g.tin[t["s_seg"].to_numpy()] < hi)]
        best, bshare = None, 0.0
        for r in inside.itertuples():
            m = self.gnis_mouth_seg(r, root, MOUTH_KM)
            if m is None:
                continue
            sh = g.size[m] / g.size[root]
            if sh > bshare + 1e-12:
                best, bshare = (r, m), sh
        if best is None or bshare < min_share:
            return None, ""
        r, m = best
        return str(r.feature_name), (f"GNIS {r.feature_id} ({r.feature_class}); its lowest segment drains "
                                     f"{100 * bshare:.0f}% of the network")


# ----------------------------------------------------------------------------- rules
def mainstem_walk(g: sr.Net, i: int, steps: int) -> list[int]:
    path = [i]
    for _ in range(steps):
        ups = g.up_order[g.up_ptr[i]:g.up_ptr[i + 1]]
        if ups.size == 0:
            break
        i = int(ups[np.argmax(g.size[ups])])
        path.append(i)
    return path


def network_name(hy: Hydro, g: sr.Net, o: int) -> dict:
    link = g.link
    rec = {"outlet_feature_id": int(link[o])}
    if hy.dom == "AK":
        nm, src = hy.gnis_name_for(o, NAME_MIN_SHARE)
        rec.update(name=nm or "UNVERIFIED", mainstem_name=None, outlet_in_nhdplus_v2=False, mainstem_steps_up=None,
                   name_rule="gnis_mouth_source" if nm else "unverified",
                   source=(f"GNIS Domestic Names stream whose source (nearest segment within {SOURCE_KM:g} km) drains to "
                           f"the outlet and whose mouth (within {MOUTH_KM:g} km) is lowest; {src}") if nm
                   else "no GNIS stream drains >= half of the network")
        return rec
    walk = mainstem_walk(g, o, 50)
    a = hy.attrs([int(link[w]) for w in walk])
    hit = next(((a[int(link[w])], s) for s, w in enumerate(walk) if a[int(link[w])]), None)
    if hit is None:
        rec.update(name="UNVERIFIED", outlet_in_nhdplus_v2=False, name_rule="unverified",
                   source="no COMID within 50 RouteLink mainstem segments found in NHDPlus V2.1")
        return rec
    h, steps = hit
    rows = sorted(hy.levelpath_rows([h["lp"]]).get(h["lp"], []), key=lambda r: r["hs"])
    cnt = collections.Counter(r["name"] for r in rows if valid_name(r["name"]))
    first = next((r["name"] for r in rows if valid_name(r["name"])), None)
    rec.update(name=first or "UNVERIFIED", mainstem_name=cnt.most_common(1)[0][0] if cnt else None,
               outlet_in_nhdplus_v2=steps == 0, mainstem_steps_up=steps,
               nhdplus_terminalfl=h["term"], nhdplus_dnhydroseq=h["dn"], nhdplus_totdasqkm=h["da"],
               nhdplus_levelpathi=h["lp"], name_rule="levelpath_gnis" if first else "unverified",
               source=f"NHDPlus V2.1 GNIS_NAME on level path {h['lp']} (EPA WATERS)")
    return rec


def inflow_label(hy: Hydro, g: sr.Net, u: int, first: bool = False) -> str | None:
    """Most frequent GNIS name on u's level path upstream of u (lake inflows: a connecting channel
    is labeled by the river that dominates its level path); first=True: the first name going
    upstream from u (confluence branches)."""
    if hy.dom == "AK":
        return hy.gnis_name_for(u, NAME_MIN_SHARE)[0]
    walk = mainstem_walk(g, u, 50)
    a = hy.attrs([int(g.link[w]) for w in walk])
    hit = next((a[int(g.link[w])] for w in walk if a[int(g.link[w])]), None)
    if hit is None:
        return None
    rows = sorted((r for r in hy.levelpath_rows([hit["lp"]]).get(hit["lp"], []) if r["hs"] >= hit["hs"]),
                  key=lambda r: r["hs"])
    if first:
        return next((r["name"] for r in rows if valid_name(r["name"])), None)
    cnt = collections.Counter(r["name"] for r in rows if valid_name(r["name"]))
    return cnt.most_common(1)[0][0] if cnt else None


def lake_rule(hy: Hydro, g: sr.Net, o: int, base_name: str) -> dict | None:
    """First water body on the outlet's mainstem walk that captures the network (see doc)."""
    walk = mainstem_walk(g, o, LAKE_WALK)
    netsz = int(g.size[o])
    water = hy.water_of(walk)
    seen, cands = set(), []
    for k, w in enumerate(walk):
        W = water.get(int(w))
        if W is not None and W not in seen:
            seen.add(W)
            cands.append((k, W))
    for k, W in cands:
        drain = int(g.size[walk[k]])
        if drain < LAKE_MIN_DRAIN * netsz:
            continue
        members = hy.members(walk[k], W)
        mset = set(int(x) for x in members)
        inflow = [int(u) for m in members for u in g.up_order[g.up_ptr[m]:g.up_ptr[m + 1]] if int(u) not in mset]
        shares = sorted(((g.size[u] / drain, u) for u in inflow), key=lambda t: (-t[0], int(g.link[t[1]])))
        big = [s for s, _ in shares if s >= LAKE_MIN_SHARE]
        if not shares or shares[0][0] >= LAKE_MAX_SHARE or len(big) < 2:
            continue
        labels, flags = [], []
        for s_, u in shares:
            if s_ < LABEL_MIN_SHARE or len(labels) >= LABEL_MAX + 3:
                break
            lab = inflow_label(hy, g, u)
            if not valid_name(lab):
                flags.append("inflow_unnamed")
                lab = f"unnamed inflow at {g.d['lat'][u]:.3f}, {g.d['lon'][u]:.3f}"
            labels.append((lab, round(float(s_), 4), int(g.link[u])))
        # (d) the name must come from upstream of the water body: an inflow carries it, and the
        # outflow channel (mainstem between outlet and water body) does not
        out_names = set()
        if k and hy.dom != "AK":
            a = hy.attrs([int(g.link[w]) for w in walk[:k]])
            out_names = {x["name"] for x in a.values() if x and x["name"]}
        unverified = base_name.startswith("UNVERIFIED")
        from_inflow = unverified or (base_name in {lab for lab, _, _ in labels} and base_name not in out_names
                                     and hy.dom != "AK")
        res = {"lake_id": W, "walk_step": k, "lake_segments": int(len(members)), "n_inflows": len(inflow),
               "drain_share": round(drain / netsz, 4), "largest_inflow_share": round(float(shares[0][0]), 4),
               "n_inflows_ge_min": len(big), "inflows": labels, "outflow_names": sorted(out_names),
               "_members": members}
        if not from_inflow:
            res.update(renamed=False, flags=["named_for_outflow"], display_name=base_name, previous_name=base_name,
                       lake_name="", lake_name_source="", below_lake=[])
            return res
        below = []
        wset = set(int(w) for w in walk)
        for w in walk[:k]:
            for u in g.up_order[g.up_ptr[w]:g.up_ptr[w + 1]]:
                if int(u) not in wset and g.size[u] / netsz >= BELOW_FLAG_SHARE:
                    lab = inflow_label(hy, g, int(u))
                    below.append((round(float(g.size[u] / netsz), 4), int(g.link[u]),
                                  lab if valid_name(lab) else None))
        if below:
            flags.append("tributary_below_lake")
        res.update(below_lake=below, flags=sorted(set(flags)))
        return res
    return None


def confluence_rule(hy: Hydro, g: sr.Net, o: int, base_name: str) -> dict | None:
    """Outlet-confluence rule: two or more large branches meet within CONF_WALK segments of the
    outlet and the network is named for a branch that is not the largest (e.g. "Buffalo Bayou"
    for the San Jacinto + Buffalo Bayou network). Rename to "<largest> and <other>", or to the
    water body there ("Sabine Lake (Sabine River, Neches River)")."""
    walk = mainstem_walk(g, o, CONF_WALK)
    netsz = int(g.size[o])
    for k, w in enumerate(walk):
        ups = g.up_order[g.up_ptr[w]:g.up_ptr[w + 1]]
        br = sorted(((g.size[u] / netsz, int(u)) for u in ups), key=lambda t: (-t[0], int(g.link[t[1]])))
        big = [(sh, u) for sh, u in br if sh >= CONF_MIN_SHARE]
        if len(big) < 2:
            continue
        labels = [(inflow_label(hy, g, u, first=True), round(float(sh), 4), int(g.link[u])) for sh, u in big]
        names = [lab for lab, _, _ in labels]
        if not all(valid_name(n) for n in names) or len(set(names)) < len(names):
            return None
        if base_name not in names[1:] or hy.dom == "AK":
            return None
        res = {"junction_step": k, "junction_feature_id": int(g.link[w]), "inflows": labels, "below_lake": [],
               "flags": [], "drain_share": 1.0, "largest_inflow_share": labels[0][1], "rule": "outlet_confluence"}
        # the water body at the junction if there is one, else the first one near the outlet
        ww = mainstem_walk(g, o, max(CONF_WATER_WALK, k))
        wat = hy.water_of(ww)
        W = wat.get(int(w)) or next((wat[int(x)] for x in ww[:CONF_WATER_WALK + 1] if int(x) in wat), None)
        if W is not None:
            start = int(w) if wat.get(int(w)) == W else next(int(x) for x in ww if wat.get(int(x)) == W)
            lname, lsrc = hy.waterbody_name(W, hy.members(start, W))
            if lname:
                res.update(lake_id=W, lake_name=lname, lake_name_source=lsrc,
                           display_name=f"{lname} ({', '.join(names)})")
                if lsrc.startswith("gnis_point"):
                    res["flags"].append("lake_name_from_gnis_point")
                return res
        res.update(lake_id=None, lake_name="", lake_name_source="", display_name=" and ".join(names))
        return res
    return None


def bay_report(g: sr.Net, hy: Hydro, top: pd.DataFrame) -> list[dict]:
    """For the water bodies in BAYS: listed networks whose outlet lies within the radius of the
    GNIS point (separate networks), and the network that contains the segment nearest the point."""
    out = []
    lat, lon = hy.lat, hy.lon
    olat, olon = top["outlet_lat"].to_numpy(float), top["outlet_lon"].to_numpy(float)
    for label, name, cls, state, rad in BAYS:
        f = hy.snap.gnis_named(name, {state}, {cls})
        if f.empty:
            out.append({"water_body": label, "gnis_id": None, "networks_ending_nearby": "", "contained_in": ""})
            continue
        r = f.sort_values("feature_id").iloc[0]
        d = km(r.prim_lat_dec, r.prim_long_dec, olat, olon)
        near = top[d <= rad].assign(dist_km=d[d <= rad]).sort_values("n_segments", ascending=False)
        box = (np.abs(lat - r.prim_lat_dec) < 0.2) & (np.abs(lon - r.prim_long_dec) < 0.25)
        cand = np.flatnonzero(box)
        cont = ""
        if len(cand):
            j = cand[np.argmin(km(r.prim_lat_dec, r.prim_long_dec, lat[cand], lon[cand]))]
            dj = float(km(r.prim_lat_dec, r.prim_long_dec, lat[j], lon[j]))
            o = int(g.link[g.outlet_of[j]])
            row = top[top["outlet_feature_id"] == o]
            cont = (f"#{int(row['rank'].iloc[0])} {row['display_name'].iloc[0]}" if len(row) else f"network outlet {o} (not listed)") \
                + f" (nearest segment {dj:.1f} km from the GNIS point)"
        out.append({"water_body": label, "gnis_id": int(r.feature_id), "gnis_lat": r.prim_lat_dec, "gnis_lon": r.prim_long_dec,
                    "radius_km": rad, "n_networks_ending_nearby": len(near),
                    "networks_ending_nearby": "; ".join(f"#{int(x['rank'])} {x['display_name']} ({int(x['n_segments']):,} seg)"
                                                        for _, x in near.iterrows()),
                    "contained_in": cont})
    return out


# ----------------------------------------------------------------------------- per domain
BASIN_COLS = ["rank", "river_name", "mainstem_name", "outlet_feature_id", "outlet_lat", "outlet_lon",
              "outlet_class", "class_confidence", "border_km", "n_segments", "pct_domain_segments", "n_reaches",
              "length_km", "max_order", "longest_path_segments", "longest_path_reaches", "longest_path_km",
              "n_headwaters", "n_junctions", "n_gages", "n_waterbodies", "n_waterbody_segments",
              "n_ids_ge_1e9", "n_segments_in_canada_mexico", "nhdplus_totdasqkm", "name_steps_up", "class_method"]


def do_domain(dom: str, snap: Snap) -> tuple[pd.DataFrame, list[dict], sr.Net, Hydro]:
    d = load(DATA / f"RouteLink_{dom}.nc")
    g = sr.Net(d)
    hy = Hydro(snap, dom, d, g)
    nets = pd.read_csv(RESULTS / f"networks_{dom}.csv")
    top = nets.head(N_TOP[dom]).copy()
    idx = pd.Series(np.arange(g.link.size), index=g.link)
    outl = [int(idx[f]) for f in top["outlet_feature_id"]]
    if dom != "CONUS":
        recs = [network_name(hy, g, o) for o in outl]
        dn = [r.get("nhdplus_dnhydroseq") for r in recs if r.get("outlet_in_nhdplus_v2") and r.get("nhdplus_dnhydroseq")]
        ft = hy.ftype_of_hydroseq(dn) if dom != "AK" else {}
        for r in recs:
            f = ft.get(float(r["nhdplus_dnhydroseq"])) if r.get("outlet_in_nhdplus_v2") and r.get("nhdplus_dnhydroseq") else None
            r["nhdplus_downstream_ftype"] = "Coastline" if f in ("Coastline", 566) else f
            if not r.get("nhdplus_dnhydroseq"):
                r["nhdplus_dnhydroseq"] = None
        top["river_name"] = [r["name"] for r in recs]
        top["mainstem_name"] = [r.get("mainstem_name") or "" for r in recs]
        top["name_steps_up"] = [r.get("mainstem_steps_up") for r in recs]
        top["nhdplus_totdasqkm"] = [r.get("nhdplus_totdasqkm") for r in recs]
        cls = [classify(r if dom != "AK" else None, b) for r, b in zip(recs, top["border_km"])]
        top["outlet_class"] = [c[0] for c in cls]
        top["class_confidence"] = [c[1] for c in cls]
        top["class_method"] = [c[2].replace("NHDPlus V2", "NHDPlus V2.1") for c in cls]
        top["name_rule"] = [r["name_rule"] for r in recs]
        top["name_source"] = [r["source"] for r in recs]
    else:
        top["name_rule"] = np.where(top["river_name"].fillna("UNVERIFIED").str.startswith("UNVERIFIED"),
                                    "unverified", "levelpath_gnis")
        top["name_source"] = "river_names.json (NHDPlus V2 GNIS on the outlet's level path)"
    lakes, disp, note = [], [], []
    for o, (_, row) in zip(outl, top.iterrows()):
        base = row["river_name"] if isinstance(row["river_name"], str) and row["river_name"] else "UNVERIFIED"
        if base.startswith("UNVERIFIED"):
            base = f"UNVERIFIED ({row['outlet_lat']:.3f}, {row['outlet_lon']:.3f})"
        x = lake_rule(hy, g, o, base)
        if x is None or x.get("renamed") is False:
            c = confluence_rule(hy, g, o, base)
            if c is not None:
                c = {"domain": dom, "rank": int(row["rank"]), "outlet_feature_id": int(g.link[o]), "renamed": True,
                     "previous_name": base, "walk_step": c["junction_step"], **c}
                lakes.append(c)
                disp.append(c["display_name"])
                note.append(f"outlet-confluence rule: branches {', '.join(f'{a} ({100 * b:.0f}%)' for a, b, _ in c['inflows'])} "
                            f"meet {c['junction_step']} segments above the outlet; level-path name was '{base}'")
                continue
        if x is None:
            disp.append(base)
            note.append("")
            continue
        x = {"domain": dom, "rank": int(row["rank"]), "outlet_feature_id": int(g.link[o]), "rule": "lake_outlet", **x}
        lakes.append(x)
        if x.get("renamed") is False:      # named for the lake's outflow: keep
            disp.append(base)
            note.append("")
            continue
        lname, lsrc = hy.waterbody_name(x["lake_id"], x["_members"])
        x["lake_name"], x["lake_name_source"], x["previous_name"] = lname, lsrc, base
        if lsrc.startswith("gnis_point"):
            x["flags"] = sorted(set(x["flags"]) | {"lake_name_from_gnis_point"})
        if not lname:
            x["flags"] = sorted(set(x["flags"]) | {"lake_unnamed"})
            x["renamed"], x["display_name"] = False, base
            disp.append(base)
            note.append(f"outlet path runs through unnamed waterbody {x['lake_id']} (kept the level-path name)")
            continue
        labs = []
        for lab, s, _ in x["inflows"]:
            if lab not in labs and not lab.startswith("unnamed"):
                labs.append(lab)
        shown = labs[:LABEL_MAX]
        name = f"{lname} ({', '.join(shown)}{', …' if len(labs) > LABEL_MAX else ''})" if shown else lname
        x["renamed"], x["display_name"] = True, name
        disp.append(name)
        note.append(f"lake-outlet rule: drains {lname} (waterbody {x['lake_id']}; name {lsrc}); level-path name was "
                    f"'{base}'" + (f"; flags: {', '.join(x['flags'])}" if x["flags"] else ""))
    top["display_name"] = disp
    top["name_note"] = note
    top.loc[[n.startswith("lake-outlet") for n in note], "name_rule"] = "lake_outlet"
    top.loc[[n.startswith("outlet-confluence") for n in note], "name_rule"] = "outlet_confluence"
    return top, lakes, g, hy


def ak_resolve(g: sr.Net, hy: Hydro, c: dict, res: dict) -> dict:
    """AK sub-river / primary river from GNIS mouth and source points (see doc, item 3)."""
    out = {"key": c["key"], "status": "UNVERIFIED", "issues": []}
    feats = hy.snap.gnis_named(c["names"][0], DOM_STATE["AK"], {"Stream"})
    scope = None
    if c["parent"]:
        par = res[c["parent"]]
        if "_mouth" not in par:
            out["issues"].append("parent unresolved")
            return out
        scope = int(g.outlet_of[par["_mouth"]]) if sr.CAND[c["parent"]]["kind"] == "primary" else par["_mouth"]
    best = None
    for r in feats.sort_values("feature_id").itertuples():
        if pd.isna(r.source_lat_dec) or r.source_lat_dec == 0:
            continue
        sseg = hy.nearest_seg(float(r.source_lat_dec), float(r.source_long_dec), SOURCE_KM)
        if sseg is None:
            continue
        rr = r._replace(s_seg=sseg) if hasattr(r, "s_seg") else type("R", (), {**r._asdict(), "s_seg": sseg})()
        m = hy.gnis_mouth_seg(rr, scope, SUB_MOUTH_KM if scope is not None else MOUTH_KM)
        if m is not None and (best is None or g.size[m] > g.size[best[0]]):
            best = (m, r)
    if best is None:
        out["issues"].append(f"no GNIS '{c['names'][0]}' (Alaska, Stream) whose mouth and source match the network")
        return out
    m, r = best
    if c["kind"] == "primary":
        o = int(g.outlet_of[m])
        if hy.netname.get(int(g.link[o])) == c["names"][0]:
            m = o            # the network carries the river's name: the river is its mainstem -> outlet
        elif g.ds[m] >= 0:
            out["issues"].append(f"drains into another river ({int(g.depth[m])} segments above its network outlet)")
    out.update(_mouth=int(m), status="gnis_points",
               method=f"GNIS {r.feature_id}: mouth {r.prim_lat_dec:.4f}, {r.prim_long_dec:.4f}; source "
                      f"{r.source_lat_dec:.4f}, {r.source_long_dec:.4f}")
    return out


def sub_rows(dom: str, g: sr.Net, hy: Hydro, top: pd.DataFrame) -> list[dict]:
    cands = EXT_CANDIDATES[dom]
    res, rows = {}, []
    allnets = pd.read_csv(RESULTS / f"networks_{dom}.csv")
    rank_all = dict(zip(allnets["outlet_feature_id"], allnets["rank"]))
    netname = dict(zip(top["outlet_feature_id"], top["display_name"]))
    total = int(g.ds.size)
    for c in cands:
        hy.netname = dict(zip(top["outlet_feature_id"].astype(int), top["river_name"]))
        r = ak_resolve(g, hy, c, res) if dom == "AK" else sr.resolve(g, hy, c, res)
        r.update(kind=c["kind"])
        res[c["key"]] = r
        row = {"domain": dom, "key": c["key"], "label": c["label"], "kind": c["kind"], "group": c["group"],
               "source": c["source"], "status": r["status"], "gnis_names": "; ".join(c["names"]),
               "parent_label": sr.CAND[c["parent"]]["label"] if c["parent"] else None, "method": r.get("method")}
        if "_mouth" in r:
            m = r["_mouth"]
            st = g.stats(m)
            o = int(g.outlet_of[m])
            row.update(mouth_feature_id=int(g.link[m]), mouth_lat=round(float(g.d["lat"][m]), 4),
                       mouth_lon=round(float(g.d["lon"][m]), 4), joins=r.get("joins"), **st,
                       network_outlet_feature_id=int(g.link[o]), network_rank=int(rank_all[int(g.link[o])]),
                       network_name=netname.get(int(g.link[o]), ""), network_segments=int(g.size[o]),
                       pct_network=100 * st["n_segments"] / g.size[o], pct_domain=100 * st["n_segments"] / total,
                       mouth_steps_to_outlet=int(g.depth[m]))
            if c["parent"] and "_mouth" in res[c["parent"]]:
                pk = c["parent"]
                pm = res[pk]["_mouth"]
                p_root = int(g.outlet_of[pm]) if sr.CAND[pk]["kind"] == "primary" else pm
                row.update(parent_mouth_feature_id=int(g.link[p_root]), parent_segments=int(g.size[p_root]),
                           pct_parent=100 * st["n_segments"] / g.size[p_root])
                if not bool(g.in_subtree(np.array([m]), p_root)[0]) and row["status"] != "not_in_parent":
                    row["status"] = "UNVERIFIED"
                    r["issues"].append("mouth is NOT inside the parent's network/subtree")
        row["issues"] = " | ".join(r["issues"])
        row["notes"] = "; ".join(x for x in [row["issues"], f"joins {r.get('joins')}" if r.get("joins") else ""] if x)
        rows.append(row)
    return rows


def lake_inflow_rows(dom: str, g: sr.Net, hy: Hydro, top: pd.DataFrame, lakes: list[dict], taken: set[int]) -> list[dict]:
    """Named inflows of every renamed network's water body (and named tributaries joining below
    it) become listed sub-rivers with their mouths at the water body."""
    rows = []
    idx = pd.Series(np.arange(g.link.size), index=g.link)
    total = int(g.ds.size)
    for x in lakes:
        if not x.get("renamed"):
            continue
        o = int(idx[x["outlet_feature_id"]])
        best = {}
        for lab, sh, fid in x["inflows"]:
            if valid_name(lab) and not lab.startswith("unnamed") and lab not in best:
                best[lab] = (fid, "inflow")
        for sh, fid, lab in x.get("below_lake", []):
            if lab and lab not in best:
                best[lab] = (fid, "joins below the water body")
        for lab, (fid, where) in best.items():
            if fid in taken:
                continue
            taken.add(fid)
            m = int(idx[fid])
            st = g.stats(m)
            rows.append({"domain": dom, "key": f"lake_{dom}_{x['rank']}_{fid}", "label": lab, "kind": "sub",
                         "group": "Lake and bay inflows", "source": "lake rule", "status": "lake_inflow",
                         "gnis_names": lab, "parent_label": x["display_name"], "method": where,
                         "mouth_feature_id": int(fid), "mouth_lat": round(float(g.d["lat"][m]), 4),
                         "mouth_lon": round(float(g.d["lon"][m]), 4), "joins": x["lake_name"] or x["display_name"], **st,
                         "network_outlet_feature_id": int(x["outlet_feature_id"]), "network_rank": int(x["rank"]),
                         "network_name": x["display_name"], "network_segments": int(g.size[o]),
                         "parent_mouth_feature_id": int(x["outlet_feature_id"]), "parent_segments": int(g.size[o]),
                         "pct_parent": 100 * st["n_segments"] / g.size[o], "pct_network": 100 * st["n_segments"] / g.size[o],
                         "pct_domain": 100 * st["n_segments"] / total, "mouth_steps_to_outlet": int(g.depth[m]),
                         "issues": "", "notes": (f"{where} {x['lake_name']} (lake-outlet rule)" if x.get("rule") == "lake_outlet"
                                                 else f"branch meeting {x['walk_step']} segments above the outlet (outlet-confluence rule)")})
    return rows


def waterbody_report(dom: str, g: sr.Net, hy: Hydro, top: pd.DataFrame, lakes: list[dict]) -> list[dict]:
    """Which listed networks end in (or within 10 mainstem segments of) the same water body:
    separate networks vs. merged into one."""
    idx = pd.Series(np.arange(g.link.size), index=g.link)
    by = collections.defaultdict(list)
    first = {}
    for _, r in top.iterrows():
        o = int(idx[r["outlet_feature_id"]])
        walk = mainstem_walk(g, o, 10)
        w = hy.water_of(walk)
        hit = next(((int(x), w[int(x)]) for x in walk if int(x) in w), None)
        if hit:
            by[hit[1]].append((int(r["rank"]), r["display_name"], int(r["n_segments"])))
            first.setdefault(hit[1], hit[0])
    rename = {x["lake_id"]: x for x in lakes if x.get("renamed")}
    out = []
    for W, nets in by.items():
        if len(nets) < 2 and W not in rename:
            continue
        name, src = hy.waterbody_name(W, hy.members(first[W], W))
        x = rename.get(W)
        out.append({"domain": dom, "water_body_id": W, "water_body_name": name, "name_source": src,
                    "n_networks": len(nets),
                    "networks": "; ".join(f"#{k} {n} ({s:,} seg)" for k, n, s in sorted(nets)),
                    "merged_inflows_of_renamed_network": "; ".join(f"{a} ({100 * b:.0f}%)" for a, b, _ in x["inflows"]) if x else ""})
    return sorted(out, key=lambda r: (-r["n_networks"], r["water_body_id"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="query live (EPA, GNIS) and rewrite domains_snapshot.json")
    ap.add_argument("--resume", action="store_true", help="with --refresh: keep answers already in the snapshot")
    args = ap.parse_args()
    snap = Snap(args.refresh, args.resume)
    snap.s = _norm_snapshot(snap.s)
    tables, lakes, subs, summary, inflow_rows, wbrep = {}, [], [], {}, [], []
    _ts = pd.read_csv(RESULTS / "T_subrivers.csv")
    taken = set(int(x) for x in _ts.loc[_ts["kind"] == "sub", "mouth_feature_id"].dropna())
    for dom in ("CONUS", "AK", "HI", "PRVI"):
        top, lk, g, hy = do_domain(dom, snap)
        tables[dom] = top
        lakes += lk
        if dom != "CONUS":
            subs += sub_rows(dom, g, hy, top)
        taken |= {int(r["mouth_feature_id"]) for r in subs if r.get("mouth_feature_id") and r["kind"] == "sub"}
        inflow_rows += lake_inflow_rows(dom, g, hy, top, lk, taken)
        wbrep += waterbody_report(dom, g, hy, top, lk)
        if dom == "CONUS":
            bays = bay_report(g, hy, top)
        summary[dom] = {"n_top": len(top),
                        "top": [{"rank": int(r["rank"]), "outlet_feature_id": int(r["outlet_feature_id"]),
                                 "n_segments": int(r["n_segments"]), "river_name": r["river_name"],
                                 "display_name": r["display_name"], "outlet_class": r["outlet_class"]}
                                for _, r in top.head(5).iterrows()],
                        "name_rule_counts": {k: int(v) for k, v in top["name_rule"].value_counts().sort_index().items()},
                        "n_lake_renamed": int(sum(1 for x in lk if x.get("renamed")))}
        print(f"{dom}: top {len(top)}; names {summary[dom]['name_rule_counts']}; lake renames "
              f"{summary[dom]['n_lake_renamed']}", flush=True)
    if args.refresh:
        snap.save()
    cols = BASIN_COLS + ["display_name", "name_rule", "name_note", "name_source"]
    for dom, t in tables.items():
        out = RESULTS / ("T_basins.csv" if dom == "CONUS" else f"T_basins_{dom}.csv")
        t = t.copy()
        for c, nd in (("pct_domain_segments", 4), ("length_km", 1), ("longest_path_km", 1), ("border_km", 1),
                      ("nhdplus_totdasqkm", 1)):
            t[c] = pd.to_numeric(t[c], errors="coerce").astype(float).round(nd)
        t["name_steps_up"] = pd.to_numeric(t["name_steps_up"], errors="coerce").astype("Int64")
        t[cols].to_csv(out, index=False)
    lk = pd.DataFrame([{**{k: v for k, v in x.items() if k not in ("inflows", "below_lake", "flags")},
                        "flags": ";".join(x["flags"]),
                        "inflows": "; ".join(f"{a} ({100 * s:.1f}%, {u})" for a, s, u in x["inflows"]),
                        "below_lake": "; ".join(f"{lab or 'unnamed'} ({100 * s:.1f}%, {u})" for s, u, lab in x["below_lake"])}
                       for x in [{k: v for k, v in y.items() if k != "_members"} for y in lakes]])
    lk.to_csv(RESULTS / "lake_renames.csv", index=False)
    sdf = pd.DataFrame(subs + inflow_rows)
    sdf.to_csv(RESULTS / "T_subrivers_ext.csv", index=False, float_format="%.4f")
    pd.DataFrame(wbrep).to_csv(RESULTS / "waterbody_networks.csv", index=False)
    pd.DataFrame(bays).to_csv(RESULTS / "bay_networks.csv", index=False)
    out = {
        "snapshot_sha256": hashlib.sha256(SNAP.read_bytes()).hexdigest(),
        "domains": summary,
        "lake_renames": {f"{x['domain']}:{x['rank']}": {"outlet_feature_id": x["outlet_feature_id"],
                                                         "lake_id": x["lake_id"], "display_name": x["display_name"],
                                                         "renamed": x["renamed"], "flags": x["flags"]}
                         for x in lakes},
        "subrivers_ext": {r["key"]: {k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()
                                     if k in ("status", "mouth_feature_id", "n_segments", "n_reaches",
                                              "longest_path_reaches", "network_rank")}
                          for r in subs},
        "lake_inflow_subrivers": {f"{r['domain']}:{r['network_rank']}:{r['label']}": {
            "mouth_feature_id": r["mouth_feature_id"], "n_segments": r["n_segments"]} for r in inflow_rows},
        "bays": {r["water_body"]: {"n_networks_ending_nearby": r.get("n_networks_ending_nearby"),
                                   "contained_in": r["contained_in"]} for r in bays},
        "water_bodies": {f"{r['domain']}:{r['water_body_id']}": {"name": r["water_body_name"],
                                                                  "n_networks": r["n_networks"]} for r in wbrep},
    }
    (RESULTS / "domains.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n")
    print(f"lake rule: {sum(1 for x in lakes if x['renamed'])} renamed of {len(lakes)} capturing lakes")
    for x in lakes:
        print(f"  {x['domain']:5} #{x['rank']:<4} {x['previous_name'][:36]:36} -> {x['display_name'][:100]} "
              f"{x['flags'] or ''} drain {x['drain_share']} largest {x['largest_inflow_share']}")
    for r in inflow_rows:
        print(f"  inflow sub-river: {r['domain']} #{r['network_rank']} {r['label']:28} {r['mouth_feature_id']:>12} "
              f"{r['n_segments']:>6} seg -> {r['joins']}")
    for r in bays:
        print(f"  bay {r['water_body']:18} ending nearby: {r.get('networks_ending_nearby', '')[:160]} | contains: {r['contained_in']}")
    for r in wbrep:
        print(f"  water body {r['domain']} {r['water_body_id']} {r['water_body_name'][:30]:30} {r['n_networks']} nets: "
              f"{r['networks'][:150]}")
    for r in subs:
        print(f"  {r['domain']:5} {r['status'][:11]:11} {r['label']:24} {r.get('mouth_feature_id', '')!s:>15} "
              f"{r.get('n_segments', '')!s:>7} rank {r.get('network_rank', '')!s:4} {r['issues'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
