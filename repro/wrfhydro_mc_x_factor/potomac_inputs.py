"""Build the Potomac network inputs for fortran/network_driver.F90.

AI-written (Claude, 2026-10-16). The network and storm are the same as the
`potomac_storm` case of repro/short_ts_switch (make_inputs.py there), so the two
experiments can be compared:
  - network: every NWM v3.1.7 RouteLink_CONUS.nc link upstream of feature 4539621
    (the Potomac's outlet), 16,454 links;
  - lateral inflow to link i is proportional to its length L_i (RouteLink has no
    catchment area), with a nominal 1.25 km^2 of contributing area per km of channel:
      ql_i(t) = L_i[km] * 1.25 * (0.01 m^3/s/km^2 baseflow
                                  + 25 mm runoff as a gamma(k=3, theta=4 h) pulse from 24 h)
    as hour averages, for 40 days;
  - initial state: the exact steady state of the baseflow (each link's flow is the sum
    of the baseflow laterals upstream of and including it), so the first 24 h must stay
    steady under either formula.
NWM channel timestep: dt = 300 s, 12 steps per hourly lateral inflow.

Writes build/potomac/inputs.bin (layout in network_driver.F90) and network.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import netCDF4
import numpy as np
from scipy.special import gammainc

from fetch_data import ROUTELINK, ROUTELINK_DEST

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "potomac"

POTOMAC_OUTLET = 4539621          # NWM v3.1.7 feature_id of the Potomac's network outlet
AREA_PER_KM = 1.25                # km^2 of contributing area per km of channel (nominal)
BASEFLOW = 0.01                   # m^3/s per km^2
STORM_MM = 25.0                   # storm runoff depth (mm)
STORM_SHAPE, STORM_SCALE_H, STORM_START_H = 3.0, 4.0, 24.0
HOURS = 40 * 24
DT = 300.0
NSUB = 12

# Record points: USGS streamgages carried in RouteLink `gages` on the Potomac network,
# two or so per size class (19 to 30,000 km2). Station names, locations and drainage
# areas are USGS's, from the NWIS site service (siteOutput=expanded), retrieved
# 2026-10-28; drain_area_va (mi2) converted at 2.589988 km2/mi2. Pages:
# https://waterdata.usgs.gov/monitoring-location/USGS-<id>
# (usgs id, station name, lat, lon, USGS drainage area km2)
GAGES = [
    ("01650800", "Sligo Creek near Takoma Park, MD", 38.9862222, -77.0048611, 17.4),
    ("01617800", "Marsh Run at Grimes, MD", 39.51455556, -77.77722222, 49.0),
    ("01636464", "Bullskin Run below Kabletown, WV", 39.2115833, -77.8348611, 56.2),
    ("01615000", "Opequon Creek near Berryville, VA", 39.1747222, -78.0783333, 150.6),
    ("01648010", "Rock Creek at Joyce Rd, Washington, DC", 38.960167, -77.042056, 165.3),
    ("01639000", "Monocacy River at Bridgeport, MD", 39.67905556, -77.23452778, 448.1),
    ("01619500", "Antietam Creek near Sharpsburg, MD", 39.44977778, -77.7301944, 727.8),
    ("01614500", "Conococheague Creek at Fairview, MD", 39.716389, -77.824778, 1279.4),
    ("01611500", "Cacapon River near Great Cacapon, WV", 39.5823158, -78.3097312, 1748.2),
    ("01629500", "S F Shenandoah River near Luray, VA", 38.6462305, -78.5347329, 3553.5),
    ("01636500", "Shenandoah River at Millville, WV", 39.28204576, -77.7891606, 7875.8),
    ("01610000", "Potomac River at Paw Paw, WV", 39.5388611, -78.4556111, 8104.1),
    ("01613000", "Potomac River at Hancock, MD", 39.69755556, -78.17788889, 10526.2),
    ("01618000", "Potomac River at Shepherdstown, WV", 39.434722, -77.801389, 15423.4),
    ("01638500", "Potomac River at Point of Rocks, MD", 39.2735833, -77.5431111, 24996.3),
    ("01646500", "Potomac River near Washington, DC (Little Falls)", 38.94977778, -77.12763889, 29940.3),
]
# Drainage-area note (checked 2026-10-28). Three nearby gauges answer different questions:
# Antietam Creek near Sharpsburg (01619500, 728 km2), Potomac at Shepherdstown (01618000,
# 15,423 km2) and Marsh Run at Grimes (01617800, 49 km2). RouteLink tags 01619500 to link
# 5894726, the last reach of Antietam Creek, correctly for routing (about 656 km2 routed
# here). But NHDPlusV2's TotDASqKM for that COMID is 16,124 km2: a small side channel
# leaves the Potomac upstream as the minor path of a divergence (COMID 5894756,
# ArtificialPath, divergence = 2; then 5894226, 5894248, 5894724) and enters Antietam's last
# reach, and TotDASqKM counts the whole upper Potomac through it. The divergence-routed
# DivDASqKM is 730 km2, matching USGS. USGS's NLDI basin for the COMID (16,124 km2) follows
# the same total-upstream topology. NWM RouteLink cuts the side channel off from the
# Potomac. Lesson: near divergences use DivDASqKM, not TotDASqKM.
AREA_NOTES = {"01619500": "NHDPlusV2 TotDASqKM 16,124 km2 (through a minor divergence) vs "
                          "DivDASqKM 730 km2 vs USGS 728 km2; NWM routing is consistent with USGS"}


def storm_series(length_km: np.ndarray, hours: int) -> np.ndarray:
    """Hour-averaged lateral inflow [m^3/s], shape (nseg, hours); as in short_ts_switch."""
    area_m2 = length_km * AREA_PER_KM * 1e6
    edges = np.arange(hours + 1, dtype=float) - STORM_START_H
    cdf = gammainc(STORM_SHAPE, np.clip(edges, 0, None) / STORM_SCALE_H)
    frac = np.diff(cdf)
    storm = np.outer(area_m2 * STORM_MM / 1000.0, frac / 3600.0)
    base = (length_km * AREA_PER_KM * BASEFLOW)[:, None]
    return (base + storm).astype(np.float32)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(ROUTELINK_DEST) as ds:
        link_all = ds["link"][:].filled().astype(np.int64)
        to_all = ds["to"][:].filled().astype(np.int64)
        pos = {int(l): i for i, l in enumerate(link_all)}
        ups: dict[int, list[int]] = {}
        for i, t in enumerate(to_all):
            if t > 0:
                ups.setdefault(int(t), []).append(i)
        keep, stack = [], [pos[POTOMAC_OUTLET]]
        while stack:
            i = stack.pop()
            keep.append(i)
            stack.extend(ups.get(int(link_all[i]), []))
        keep = np.sort(np.array(keep))
        v = {k: ds[k][:][keep].filled().astype(np.float32)
             for k in ("So", "Length", "n", "ChSlp", "BtmWdth", "TopWdth", "TopWdthCC", "nCC", "Kchan")}
        order = ds["order"][:][keep].filled().astype(np.int32)
        lat = ds["lat"][:][keep].filled().astype(np.float64)
        lon = ds["lon"][:][keep].filled().astype(np.float64)
        gages = ds["gages"][:][keep]
        gage_str = ["".join(c.decode() for c in row.filled(b" ")).strip() for row in gages]
    link = link_all[keep]
    to = to_all[keep]
    n = len(link)
    if to[link == POTOMAC_OUTLET][0] != 0:
        raise SystemExit("Potomac outlet is not a network outlet")
    if np.any(v["Kchan"] != 0):
        raise SystemExit("Kchan is nonzero somewhere: channel loss would apply in WRF-Hydro")
    idx = {int(l): i for i, l in enumerate(link)}
    down = np.array([idx.get(int(t), -1) + 1 for t in to], dtype=np.int32)   # 1-based, 0 = outlet

    # topological order (headwaters first) for the steady state
    nup = np.zeros(n, int)
    for d in down:
        if d > 0:
            nup[d - 1] += 1
    stack = [i for i in range(n) if nup[i] == 0]
    topo = []
    while stack:
        i = stack.pop()
        topo.append(i)
        d = down[i] - 1
        if d >= 0:
            nup[d] -= 1
            if nup[d] == 0:
                stack.append(d)
    assert len(topo) == n

    length_km = v["Length"].astype(float) / 1000.0
    ql = storm_series(length_km, HOURS)
    q0 = ql[:, 0].astype(np.float64)
    for i in topo:
        if down[i] > 0:
            q0[down[i] - 1] += q0[i]

    outlet = int(np.flatnonzero(link == POTOMAC_OUTLET)[0])
    rec = [outlet]
    rec_meta = [{"name": "Potomac outlet (NWM feature 4539621)", "link": POTOMAC_OUTLET, "usgs": None,
                 "usgs_area_km2": None, "lat": None, "lon": None, "flag": None}]
    for gid, name, glat, glon, garea in GAGES:
        hits = [i for i, g in enumerate(gage_str) if g == gid]
        if len(hits) != 1:
            raise SystemExit(f"gage {gid}: {len(hits)} links")
        rec.append(hits[0])
        rec_meta.append({"name": name, "link": int(link[hits[0]]), "usgs": gid, "usgs_area_km2": garea,
                         "lat": glat, "lon": glon, "flag": None, "area_note": AREA_NOTES.get(gid)})
    rec_arr = np.array(rec, dtype=np.int32) + 1

    with open(OUT / "inputs.bin", "wb") as f:
        np.array([n, HOURS, NSUB, len(rec)], dtype=np.int32).tofile(f)
        np.array([DT], dtype=np.float32).tofile(f)
        down.tofile(f)
        link.astype(np.int64).tofile(f)
        for k in ("So", "Length", "n", "ChSlp", "BtmWdth", "TopWdth", "TopWdthCC", "nCC"):
            v[k].tofile(f)
        q0.astype(np.float32).tofile(f)
        rec_arr.tofile(f)
        np.ascontiguousarray(ql.T).tofile(f)     # Fortran ql(n, hours): hour by hour

    upstream_km = np.zeros(n)
    for i in topo:
        upstream_km[i] += length_km[i]
        if down[i] > 0:
            upstream_km[down[i] - 1] += upstream_km[i]
    meta = {
        "routelink": {"url": ROUTELINK[0], "sha256": ROUTELINK[1]},
        "outlet_feature": POTOMAC_OUTLET, "n_links": n, "hours": HOURS, "dt_s": DT, "nsub": NSUB,
        "storm": {"area_per_km_km2": AREA_PER_KM, "baseflow_m3s_per_km2": BASEFLOW,
                  "runoff_mm": STORM_MM, "gamma_shape": STORM_SHAPE, "gamma_scale_h": STORM_SCALE_H,
                  "start_h": STORM_START_H},
        "total_lateral_volume_m3": float(ql.astype(np.float64).sum() * 3600.0),
        "q0_outlet_m3s": float(q0[outlet]),
        "slope_floor_links": int(np.sum(v["So"] <= 1.0001e-5)),
        "records": rec_meta,
    }
    (OUT / "network.json").write_text(json.dumps(meta, indent=2))
    np.savez_compressed(OUT / "links.npz", link=link, to=to, order=order, length_km=length_km,
                        so=v["So"], q0=q0, upstream_km=upstream_km, lat=lat, lon=lon,
                        model_area_km2=upstream_km * AREA_PER_KM)
    print(f"Potomac: {n} links, {HOURS} h, outlet q0 = {q0[outlet]:.1f} m3/s, "
          f"lateral volume {meta['total_lateral_volume_m3']:.4g} m3")


if __name__ == "__main__":
    main()
