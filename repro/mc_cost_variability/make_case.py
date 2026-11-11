"""Build the Potomac case (network, channel parameters, topology, initial state) into data/inputs/potomac/.

    uv run --locked python make_case.py

Uses ../short_ts_switch/make_inputs.py read-only: `extract_potomac` (all segments upstream
of NWM feature 4539621 from NWM v3.1.6 RouteLink_CONUS.nc), `topology` (distance to
outlet, longest upstream path, mainstem) and `storm_series` / `steady_state` (synthetic
lateral inflow, exact steady state of the baseflow). What T-Route itself adds, replicated
here:
- channel parameters cast to float32 (nhd_network_utilities_v02.py L129 / NHDNetwork.py
  L232 @ d29f663), columns dx=Length, bw=BtmWdth, tw=TopWdth, twcc=TopWdthCC, n, ncc=nCC,
  cs=ChSlp, s0=So (../short_ts_switch/run_troute.py COLUMNS);
- upstream segments listed in ascending feature id (T-Route sorts the parameter frame by
  id before building connections, NHDNetwork.py L189 @ d29f663), which sets the float32
  order of junction sums (mc_reach.pyx L509-512).
Added for the cost analysis: slope class, tributary ("subbasin") of each segment, lat/lon.
"""
from __future__ import annotations

import json
import sys

import netCDF4
import numpy as np

from common import CASE_DIR, HOURS, routelink_path, storm_qlat

PCOLS = [("dx", "Length"), ("bw", "BtmWdth"), ("tw", "TopWdth"), ("twcc", "TopWdthCC"), ("n", "n"),
         ("ncc", "nCC"), ("cs", "ChSlp"), ("s0", "So")]
MIN_TRIB = 300            # tributaries with at least this many segments get their own subbasin label


def slope_class(s0: np.ndarray) -> np.ndarray:
    """As ../short_ts_switch/closure_replay.py: RouteLink floor 1e-5, <2.5e-4, <=1e-3, >1e-3."""
    return np.select([s0 <= 1.0001e-5, s0 < 2.5e-4, s0 <= 1e-3], [0, 1, 2], 3)


def main() -> int:
    import make_inputs as MI                        # ../short_ts_switch, read-only
    MI.ROUTELINK_DEST = routelink_path()
    CASE_DIR.mkdir(parents=True, exist_ok=True)
    rl = CASE_DIR / "RouteLink.nc"
    if rl.exists():
        rl.unlink()
    MI.extract_potomac(rl)
    with netCDF4.Dataset(rl) as ds:
        ds.set_auto_mask(False)
        link = ds["link"][:].astype(np.int64)
        to = ds["to"][:].astype(np.int64)
        length_m = ds["Length"][:].astype(float)
        order = ds["order"][:].astype(int)
        params = np.stack([ds[c][:].astype(np.float32) for _, c in PCOLS], axis=1)
        lat = ds["lat"][:].astype(float)
        lon = ds["lon"][:].astype(float)
    seg, topo, down = MI.topology(link, to, length_m, order)
    n = len(link)
    # upstream CSR, upstreams in ascending feature id
    src = np.nonzero(down >= 0)[0]
    o = np.lexsort((link[src], down[src]))
    up_idx = src[o].astype(np.int64)
    up_ptr = np.zeros(n + 1, np.int64)
    np.cumsum(np.bincount(down[src], minlength=n), out=up_ptr[1:])
    topo = np.asarray(topo, dtype=np.int64)
    # initial state: exact steady state of the baseflow (hour 0 has no storm in any scenario)
    ql0 = storm_qlat(seg["length_km"].to_numpy(), 0.0)[:, 0]
    q0 = MI.steady_state(ql0, list(topo), down).astype(np.float32)
    # tributary of each segment: walk down to the mainstem; the last off-mainstem segment
    # before it is the tributary's mouth
    main = seg["mainstem"].to_numpy()
    mouth = np.full(n, -1, dtype=np.int64)
    for i in topo[::-1]:                      # downstream before upstream
        if main[i]:
            continue
        d = down[i]
        mouth[i] = i if (d < 0 or main[d]) else mouth[d]
    size = np.bincount(mouth[mouth >= 0], minlength=n)
    big = np.flatnonzero(size >= MIN_TRIB)
    big = big[np.argsort(-size[big])]
    label = np.full(n, "minor_tributaries", dtype=object)
    label[main] = "mainstem"
    trib_rank = {int(m): k for k, m in enumerate(big)}
    for i in range(n):
        if mouth[i] >= 0 and int(mouth[i]) in trib_rank:
            m = int(mouth[i])
            label[i] = f"T{trib_rank[m] + 1:02d}_{link[m]}"
    seg["s0"] = params[:, 7].astype(float)
    seg["slope_class"] = slope_class(params[:, 7])
    seg["subbasin"] = label.astype(str)
    seg["trib_mouth_link"] = np.where(mouth >= 0, link[np.maximum(mouth, 0)], -1)
    seg["lat"], seg["lon"] = lat, lon
    seg["q0"] = q0
    seg["down_idx"] = down
    seg.to_parquet(CASE_DIR / "segments.parquet")
    for k, v in {"link": link, "params": params, "up_ptr": up_ptr, "up_idx": up_idx, "topo": topo,
                 "q0_base": q0, "length_km": seg["length_km"].to_numpy()}.items():
        np.save(CASE_DIR / f"{k}.npy", v)
    tribs = [{"label": f"T{k + 1:02d}_{link[m]}", "mouth_feature_id": int(link[m]), "segments": int(size[m]),
              "mouth_lat": round(float(lat[m]), 3), "mouth_lon": round(float(lon[m]), 3),
              "mouth_dist_to_outlet_km": round(float(seg["dist_to_outlet_km"].iloc[m]), 1)}
             for k, m in enumerate(big)]
    info = {"case": "potomac", "routelink": "NWM v3.1.6 RouteLink_CONUS.nc (sha256 pinned in common.py)",
            "outlet_feature_id": int(MI.POTOMAC_OUTLET), "n_segments": int(n), "hours": HOURS,
            "longest_path_segments": int(seg["up_path_segs"].max()),
            "longest_path_km": round(float(seg["up_path_km"].max()), 1),
            "mainstem_segments": int(main.sum()), "min_tributary_segments_for_label": MIN_TRIB,
            "tributaries": tribs,
            "minor_tributary_segments": int((label == "minor_tributaries").sum())}
    (CASE_DIR / "case.json").write_text(json.dumps(info, indent=1) + "\n")
    print(f"ok      potomac: {n} segments, longest path {info['longest_path_km']} km / "
          f"{info['longest_path_segments']} segments, mainstem {info['mainstem_segments']}, "
          f"{len(tribs)} tributaries >= {MIN_TRIB} segments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
