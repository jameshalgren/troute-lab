"""Prepare the T-Route inputs for each case into build/inputs/<case>/.

Cases (see README "Design"):
  lc_nwm         LowerColorado_TX test domain shipped with t-route (11,248 NWM segments),
                 recorded NWM v2.1 AnA lateral inflows for 28 h from 2021-08-23 13:00 UTC
                 (the shipped CHRTOUT files), warm-started from the NWM's own routed
                 `streamflow` in the first CHRTOUT file.
  potomac_storm  Potomac River network (all segments upstream of NWM feature 4539621)
                 extracted from NWM v3.1.6 RouteLink_CONUS.nc, synthetic storm, 40 days.

Synthetic storm: lateral inflow to segment i is
proportional to its channel length L_i (RouteLink `Length`; RouteLink carries no
catchment area), using a nominal 1.25 km^2 of contributing area per km of channel:
  ql_i(t) = L_i[km] * 1.25 * ( 0.01 m^3/s/km^2 baseflow
                               + 25 mm runoff distributed in time as a gamma(k=3,
                                 theta=4 h) pulse starting 24 h after t0 )
Hourly values are hour-averages (exact volume). The initial state is the exact steady
state of the baseflow (each segment's flow = sum of baseflow laterals upstream of and
including it), so the first 24 h are steady and True/False must agree there.

Each case directory gets: RouteLink.nc (the network), forcing/*.CHRTOUT_DOMAIN1
(feature_id + q_lateral; the lc_nwm case points at the shipped files instead),
restart.pkl (a T-Route "lite restart": qu0, qd0, h0, time), and segments.parquet
(topology metrics used by analyze.py), plus case.json.
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import netCDF4
import numpy as np
import pandas as pd
import xarray as xr
from scipy.special import gammainc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fetch_data import ROUTELINK_DEST, TROUTE_DIR  # noqa: E402

INPUTS = HERE / "build" / "inputs"
LC_DIR = TROUTE_DIR / "test" / "LowerColorado_TX"

POTOMAC_OUTLET = 4539621          # NWM v3.1.6 feature_id of the Potomac's network outlet
AREA_PER_KM = 1.25                # km^2 of contributing area per km of channel (nominal)
BASEFLOW = 0.01                   # m^3/s per km^2
STORM_MM = 25.0                   # storm runoff depth (mm)
STORM_SHAPE, STORM_SCALE_H, STORM_START_H = 3.0, 4.0, 24.0

CASES = {
    "lc_nwm": {"label": "LowerColorado_TX, recorded NWM forcing", "hours": 28,
               "t0": "2021-08-23 13:00"},
    "potomac_storm": {"label": "Potomac (NWM v3.1.6), synthetic storm", "hours": 40 * 24,
                      "t0": "2000-01-01 00:00"},
}


# ----------------------------------------------------------------------------- topology
def topology(link: np.ndarray, to: np.ndarray, length_m: np.ndarray, order: np.ndarray) -> pd.DataFrame:
    """Per-segment distance to outlet, longest upstream path, mainstem flag."""
    n = len(link)
    pos = {l: i for i, l in enumerate(link)}
    down = np.array([pos.get(t, -1) for t in to])
    ups: list[list[int]] = [[] for _ in range(n)]
    for i, d in enumerate(down):
        if d >= 0:
            ups[d].append(i)
    # topological order: headwaters first (Kahn on upstream counts)
    nup = np.array([len(u) for u in ups])
    stack = [i for i in range(n) if nup[i] == 0]
    topo = []
    while stack:
        i = stack.pop()
        topo.append(i)
        d = down[i]
        if d >= 0:
            nup[d] -= 1
            if nup[d] == 0:
                stack.append(d)
    if len(topo) != n:
        raise RuntimeError("network has a cycle")
    L = length_m / 1000.0
    up_km = np.zeros(n)
    up_seg = np.zeros(n, dtype=int)
    for i in topo:                      # upstream before downstream
        if ups[i]:
            up_km[i] = L[i] + max(up_km[u] for u in ups[i])
            up_seg[i] = 1 + max(up_seg[u] for u in ups[i])
        else:
            up_km[i] = L[i]
            up_seg[i] = 1
    dist_km = np.zeros(n)               # from the segment's downstream end to the outlet's
    n_down = np.zeros(n, dtype=int)
    for i in reversed(topo):            # downstream before upstream
        d = down[i]
        if d >= 0:
            dist_km[i] = dist_km[d] + L[d]
            n_down[i] = n_down[d] + 1
    outlets = [i for i in range(n) if down[i] < 0]
    outlet = max(outlets, key=lambda i: up_km[i])
    main = np.zeros(n, dtype=bool)      # longest flow path (by km) from the main outlet
    i = outlet
    while True:
        main[i] = True
        if not ups[i]:
            break
        i = max(ups[i], key=lambda u: up_km[u])
    return pd.DataFrame({
        "link": link, "to": to, "length_km": L, "order": order,
        "dist_to_outlet_km": dist_km, "n_down": n_down,
        "up_path_km": up_km, "up_path_segs": up_seg, "mainstem": main,
        "is_outlet": np.isin(np.arange(n), [outlet]),
        "topo_rank": np.argsort(np.array(topo)).astype(int),
    }), topo, down


def steady_state(ql: np.ndarray, topo: list[int], down: np.ndarray) -> np.ndarray:
    q = ql.astype(np.float64).copy()
    for i in topo:
        d = down[i]
        if d >= 0:
            q[d] += q[i]
    return q


# ----------------------------------------------------------------------------- forcing
def storm_series(length_km: np.ndarray, hours: int) -> np.ndarray:
    """Hour-averaged lateral inflow [m^3/s], shape (nseg, hours)."""
    area_m2 = length_km * AREA_PER_KM * 1e6
    edges = np.arange(hours + 1, dtype=float) - STORM_START_H
    cdf = gammainc(STORM_SHAPE, np.clip(edges, 0, None) / STORM_SCALE_H)
    frac = np.diff(cdf)                                  # fraction of storm volume per hour
    storm = np.outer(area_m2 * STORM_MM / 1000.0, frac / 3600.0)
    base = (length_km * AREA_PER_KM * BASEFLOW)[:, None]
    return (base + storm).astype(np.float32)


def write_chrtout(folder: Path, t0: datetime, feature_id: np.ndarray, ql: np.ndarray) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for h in range(ql.shape[1]):
        t = t0 + timedelta(hours=h)
        with netCDF4.Dataset(folder / f"{t:%Y%m%d%H%M}.CHRTOUT_DOMAIN1", "w") as ds:
            ds.createDimension("feature_id", len(feature_id))
            v = ds.createVariable("feature_id", "i8", ("feature_id",))
            v[:] = feature_id
            q = ds.createVariable("q_lateral", "f4", ("feature_id",))
            q.units = "m3 s-1"
            q[:] = ql[:, h]
            ds.description = "Synthetic lateral inflow (repro/short_ts_switch/make_inputs.py)"
            ds.model_output_valid_time = f"{t:%Y-%m-%d_%H:%M:%S}"  # as in NWM CHRTOUT files


def write_restart(path: Path, link: np.ndarray, q: np.ndarray, t0: datetime) -> None:
    q = np.asarray(q, dtype=np.float32)
    df = pd.DataFrame({"qu0": q, "qd0": q, "h0": np.zeros_like(q)}, index=pd.Index(link, name="link"))
    df["time"] = pd.Timestamp(t0)
    df.to_pickle(path)


# ----------------------------------------------------------------------------- cases
def extract_potomac(dest: Path) -> None:
    with netCDF4.Dataset(ROUTELINK_DEST) as ds:
        link = ds["link"][:].filled().astype(np.int64)
        to = ds["to"][:].filled().astype(np.int64)
    pos = pd.Series(np.arange(len(link)), index=link)
    ups: dict[int, list[int]] = {}
    for i, t in enumerate(to):
        if t > 0:
            ups.setdefault(int(t), []).append(i)
    keep, stack = [], [int(pos[POTOMAC_OUTLET])]
    while stack:
        i = stack.pop()
        keep.append(i)
        stack.extend(ups.get(int(link[i]), []))
    keep = np.sort(np.array(keep))
    # Default CF decoding matters: it turns the (feature_id, IDLength) char array `gages`
    # into 1-D strings. Written back raw, T-Route's reader would expand every segment
    # into IDLength = 15 rows (duplicated connections).
    with xr.open_dataset(ROUTELINK_DEST, decode_times=False) as ds:
        sub = ds.isel(feature_id=keep).load()
    if int(sub["to"].values[sub["link"].values == POTOMAC_OUTLET][0]) != 0:
        raise RuntimeError("Potomac outlet is not a network outlet")
    sub.attrs["subset_note"] = (f"All {len(keep)} segments upstream of feature {POTOMAC_OUTLET} "
                                "(Potomac River outlet), from NWM v3.1.6 RouteLink_CONUS.nc; "
                                "repro/short_ts_switch/make_inputs.py")
    sub.to_netcdf(dest)


def prepare(case: str) -> dict:
    cfg = CASES[case]
    d = INPUTS / case
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    t0 = datetime.strptime(cfg["t0"], "%Y-%m-%d %H:%M")
    rl = d / "RouteLink.nc"
    if case.startswith("lc"):
        shutil.copy2(LC_DIR / "domain" / "RouteLink.nc", rl)
    else:
        extract_potomac(rl)
    with xr.open_dataset(rl) as ds:
        link = ds["link"].values.astype(np.int64)
        to = ds["to"].values.astype(np.int64)
        length_m = ds["Length"].values.astype(float)
        order = ds["order"].values.astype(int)
    seg, topo, down = topology(link, to, length_m, order)

    if case == "lc_nwm":
        forcing = LC_DIR / "channel_forcing"
        # Warm start: the NWM's routed streamflow valid at t0 (first CHRTOUT file),
        # by feature_id. Missing values (lake/fill) -> 0.
        with xr.open_dataset(forcing / f"{t0:%Y%m%d%H%M}.CHRTOUT_DOMAIN1") as c:
            s = pd.Series(c["streamflow"].values, index=c["feature_id"].values.astype(np.int64))
        q0 = s.reindex(link).astype(float).fillna(0.0).clip(lower=0.0).to_numpy()
        n_missing = int(s.reindex(link).isna().sum())
        meta = {"forcing_dir": str(forcing.relative_to(HERE)), "forcing": "recorded NWM CHRTOUT "
                "(T-Route reads qBucket + qSfcLatRunoff when both are present)",
                "initial_state": "NWM streamflow at t0 by feature_id",
                "initial_state_missing_set_to_zero": n_missing}
    else:
        ql = storm_series(seg["length_km"].to_numpy(), cfg["hours"])
        forcing = d / "forcing"
        write_chrtout(forcing, t0, link, ql)
        q0 = steady_state(ql[:, 0], topo, down)
        meta = {"forcing_dir": str(forcing.relative_to(HERE)), "forcing": "synthetic storm",
                "initial_state": "exact steady state of the baseflow laterals",
                "storm": {"area_per_km_km2": AREA_PER_KM, "baseflow_m3s_per_km2": BASEFLOW,
                          "runoff_mm": STORM_MM, "gamma_shape": STORM_SHAPE,
                          "gamma_scale_h": STORM_SCALE_H, "start_h": STORM_START_H},
                "total_lateral_volume_m3": float(ql.sum() * 3600.0)}
    write_restart(d / "restart.pkl", link, q0, t0)
    seg["q0"] = q0
    seg.to_parquet(d / "segments.parquet")
    info = {"case": case, **cfg, "n_segments": int(len(link)),
            "outlet": int(seg.loc[seg.is_outlet, "link"].iloc[0]),
            "n_network_outlets": int((down < 0).sum()),
            "longest_path_km": float(seg.up_path_km.max()),
            "longest_path_segments": int(seg.up_path_segs.max()),
            "mainstem_segments": int(seg.mainstem.sum()),
            "total_channel_km": float(seg.length_km.sum()),
            "median_length_km": float(seg.length_km.median()), **meta}
    (d / "case.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"ok      {case}: {info['n_segments']} segments, longest path "
          f"{info['longest_path_km']:.0f} km / {info['longest_path_segments']} segments")
    return info


def main() -> int:
    for case in (sys.argv[1:] or list(CASES)):
        prepare(case)
    return 0


if __name__ == "__main__":
    sys.exit(main())
