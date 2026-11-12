"""Spatial layers for the survey-feasibility screen.

Segment locations are RouteLink `lat`/`lon`, which are the along-line MIDPOINTS of the NWM
flowlines (checked against the NWM v3 channel hydrofabric: geometry_check.py). Matching
by midpoint avoids counting a tributary as "on" a waterway merely because its downstream
end touches the waterway at the confluence.

All distances are computed in CONUS Albers equal-area (EPSG:5070), metres.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

CRS = "EPSG:5070"
COASTAL_PLAIN_PROVINCE = "COASTAL PLAIN"
MISS_ALLUVIAL_SECTION = "MISSISSIPPI ALLUVIAL PLAIN"

PHYSIO_DIR = "physio"
NWN_FILE = "nwn/nwn_lines.geojson"
EHYDRO_FILE = "ehydro/ehydro_outlines.geojson"
EHYDRO_META = "ehydro/ehydro_meta.json"

# Recorded in results/provenance.json (details, licences and access dates: README.md "Sources").
SOURCES: dict = {
    "routelink": "NWM v3.1.7 RouteLink_{CONUS,AK,HI,PRVI}.nc, https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/parm/",
    "nhdplus_vaa": "nhdplusTools VAA parquet, HydroShare 6092c8a62fac45be97a09bfd0b0bf726 (2021-02-26)",
    "nhdplus_erom": "EPA NHDPlusV2.1 EROMExtension, https://dmap-data-commons-ow.s3.amazonaws.com/NHDPlusV21/Data/ (21 CONUS VPUs)",
    "physio": "Fenneman & Johnson (1946), USGS, doi:10.5066/P9B1S3K8, https://water.usgs.gov/GIS/dsdl/physio_shp.zip",
    "nwn": "BTS NTAD National Waterway Network Lines (USACE), doi:10.21949/1522176; FeatureServer "
           "services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/Waterway_Networks/FeatureServer/1 "
           "(data last edited 2025-09-30), retrieved 2026-10-08",
    "ehydro": "USACE eHydro SurveyJob outlines, services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/"
              "eHydro_Survey_Data/FeatureServer/0, live service, retrieved 2026-10-08",
}


def input_files(data: Path) -> dict:
    out = {}
    for p in sorted((data / PHYSIO_DIR).glob("physio.*")):
        out[f"physio/{p.name}"] = p
    for f in (NWN_FILE, EHYDRO_FILE):
        if (data / f).exists():
            out[f] = data / f
    return out


def load_all(data: Path) -> dict:
    shp = sorted((data / PHYSIO_DIR).glob("*.shp"))
    if len(shp) != 1:
        raise SystemExit("physiographic shapefile missing; run fetch_data.py")
    physio = gpd.read_file(shp[0])
    if physio.crs is None:
        raise SystemExit("physio shapefile has no CRS")
    physio = physio.to_crs(CRS)
    nwn = gpd.read_file(data / NWN_FILE).to_crs(CRS)
    nwn = nwn[nwn.geometry.notna() & ~nwn.geometry.is_empty]
    ehy = None
    meta_e = None
    if (data / EHYDRO_FILE).exists():
        ehy = gpd.read_file(data / EHYDRO_FILE).to_crs(CRS)
        ehy = ehy[ehy.geometry.notna() & ~ehy.geometry.is_empty].copy()
        ehy["geometry"] = ehy.geometry.make_valid()
        meta_e = json.loads((data / EHYDRO_META).read_text()) if (data / EHYDRO_META).exists() else {}
    meta = {"physio": {"file": shp[0].name, "features": int(len(physio))},
            "nwn": {"file": NWN_FILE, "features": int(len(nwn)),
                    "km": round(float(nwn.geometry.length.sum()) / 1000, 1)},
            "ehydro": None if ehy is None else {"file": EHYDRO_FILE, "features": int(len(ehy)), **(meta_e or {})}}
    return {"physio": physio, "nwn": nwn, "ehydro": ehy, "meta": meta}


def distance_to_lines(pts: gpd.GeoSeries, lines: gpd.GeoDataFrame, max_m: float = 5000.0) -> np.ndarray:
    """Distance (m) from each point to the nearest line, capped at max_m (inf beyond)."""
    left = gpd.GeoDataFrame(geometry=pts.reset_index(drop=True))
    j = gpd.sjoin_nearest(left, lines[["geometry"]], how="left", max_distance=max_m, distance_col="d")
    d = j.groupby(level=0)["d"].min().reindex(range(len(left))).to_numpy()
    return np.where(np.isnan(d), np.inf, d)


def points_in_polygons(pts: gpd.GeoSeries, polys: gpd.GeoDataFrame) -> np.ndarray:
    left = gpd.GeoDataFrame(geometry=pts.reset_index(drop=True))
    j = gpd.sjoin(left, polys[["geometry"]], how="inner", predicate="intersects")
    out = np.zeros(len(left), bool)
    out[np.unique(j.index.to_numpy())] = True
    return out


def physio_attributes(pts: gpd.GeoSeries, physio: gpd.GeoDataFrame) -> dict:
    left = gpd.GeoDataFrame(geometry=pts.reset_index(drop=True))
    cols = [c for c in ("DIVISION", "PROVINCE", "SECTION") if c in physio.columns]
    j = gpd.sjoin(left, physio[cols + ["geometry"]], how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")].reindex(range(len(left)))
    return {c.lower(): j[c].fillna("").astype(str).str.upper().to_numpy() for c in cols}
