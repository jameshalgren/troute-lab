"""Characterize the NWM channel network as independent drainage networks.

For each RouteLink domain (CONUS, AK, HI, PRVI) this script:
  * builds the downstream graph (`link` -> `to`); an OUTLET is a segment whose `to` is 0
    or is not a `link` in the same file; a NETWORK is the set of segments draining to
    one outlet (a tree, because each segment has exactly one `to`);
  * computes per-network statistics (results/networks_<DOMAIN>.csv);
  * computes domain summaries, a size histogram, and two scheduling calculations
    (results/results.json):
      - bin packing: the fewest equal processors such that no processor carries more
        work than the largest network (first-fit decreasing, FFD), and
      - makespan vs. number of processors P = 1..16 for by-network LPT scheduling
        (longest-processing-time-first list scheduling);
  * draws figures (results/fig_network_sizes.{png,pdf}, results/fig_makespan.{png,pdf});
  * joins river names from river_names.json (a committed snapshot of USGS queries made
    by river_names.py) and writes results/T_basins.csv, the machine-readable basin table.

Definitions (stated once, used everywhere):
  segment      one RouteLink row (an NHDPlus flowline / NWM feature_id).
  headwater    segment with no upstream segment.
  junction     segment with >= 2 upstream segments.
  reach        maximal run of consecutive segments with no tributary inflow between them.
               A segment STARTS a new reach unless it has exactly one upstream segment,
               so #reaches = #headwaters + #junctions (in-degree != 1).
  depth        number of downstream steps from a segment to its network's outlet
               (outlet depth = 0).
  longest path (segments) = max depth + 1 (both end segments counted).
  longest path (reaches)  = max over headwaters of the number of reaches traversed to
               the outlet, counting both the headwater's reach and the outlet's reach.
  longest path (km)       = max over segments of the summed `Length` from that segment's
               upstream end to the outlet's downstream end. This can be a different
               path from the one with the most segments.
  gages        segments whose `gages` string is non-blank.
  waterbody segments  segments with NHDWaterbodyComID != -9999 (the only non-positive
               value present); also the number of distinct waterbody ComIDs.
"""
from __future__ import annotations

import heapq
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

import provenance

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"
DOMAINS = {d: DATA / f"RouteLink_{d}.nc" for d in ("CONUS", "AK", "HI", "PRVI")}
# Optional older full-CONUS RouteLink (NWM v2.1, as deployed in nwm.v2.2.0); see fetch_data.py.
OPTIONAL = {"CONUS_v2.1": DATA / "v2.1" / "RouteLink_CONUS_v2.1.nc"}
WB_MISSING = -9999
# CONUS feature_ids >= 1e9 are not NHDPlus V2 COMIDs (largest COMID in the file is
# 948,100,740). Their prefixes (101, 102, 109, 110, 113, 115, 117, 118) match the
# regions the v2.1 processing_notes list as "Arc-Hydro derived segments" (01a, 02b, 09a,
# 10h/10i, 13a/b/d, 15a/b, 17b, 18a); the prefix-to-region mapping is our inference.
# Not meaningful for AK (all AK IDs are large).
BIG_ID = 1_000_000_000
TOPK = (1, 2, 3, 5, 10, 20, 100)
P_RANGE = range(1, 17)
N_TABLE = 500  # rows in results/T_basins.csv (author's request: top 500 primary rivers)


def load(path: Path) -> dict:
    ds = xr.open_dataset(path, decode_times=False)
    out = {
        "link": ds["link"].values.astype(np.int64),
        "to": ds["to"].values.astype(np.int64),
        "length_m": ds["Length"].values.astype(np.float64),
        "order": ds["order"].values.astype(np.int64),
        "lat": ds["lat"].values.astype(np.float64),
        "lon": ds["lon"].values.astype(np.float64),
        "gage": np.char.strip(ds["gages"].values.astype("U15")) != "",
        "wb": ds["NHDWaterbodyComID"].values.astype(np.int64),
    }
    ds.close()
    return out


def graph(link: np.ndarray, to: np.ndarray):
    """Downstream index (-1 for outlets) and CSR upstream adjacency."""
    n = link.size
    if np.unique(link).size != n:
        raise SystemExit("duplicate link IDs; the network is not a function of link")
    srt = np.argsort(link)
    pos = np.searchsorted(link[srt], to)
    pos[pos >= n] = 0
    found = (link[srt][pos] == to) & (to != 0)
    ds = np.where(found, srt[pos], -1)
    if np.any(ds == np.arange(n)):
        raise SystemExit("self-loop found")
    indeg = np.bincount(ds[ds >= 0], minlength=n)
    up_order = np.argsort(ds, kind="stable")
    up_order = up_order[ds[up_order] >= 0]
    up_ptr = np.concatenate([[0], np.cumsum(indeg)])
    return ds, indeg, up_order, up_ptr, found


def traverse(ds, indeg, up_order, up_ptr, length_m):
    """Breadth-first from every outlet upstream. Returns net id, depth, km-to-outlet,
    reaches-to-outlet for every segment; segments never reached lie on cycles."""
    n = ds.size
    net = np.full(n, -1, np.int64)
    depth = np.full(n, -1, np.int64)
    dist = np.zeros(n)
    rcount = np.zeros(n, np.int64)
    head = indeg != 1  # starts a reach
    front = np.flatnonzero(ds < 0)
    net[front] = np.arange(front.size)
    depth[front] = 0
    dist[front] = length_m[front]
    rcount[front] = 1
    while front.size:
        counts = indeg[front]
        starts = up_ptr[front]
        if counts.sum() == 0:
            break
        rep = np.repeat(np.arange(front.size), counts)
        offs = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
        ups = up_order[np.repeat(starts, counts) + offs]
        par = front[rep]
        net[ups] = net[par]
        depth[ups] = depth[par] + 1
        dist[ups] = dist[par] + length_m[ups]
        # moving up from `par` to `ups` enters a new reach iff `par` is a reach start
        rcount[ups] = rcount[par] + head[par].astype(np.int64)
        front = ups
    return net, depth, dist, rcount


def ffd_bins(sizes: np.ndarray, cap: float) -> int:
    """First-fit decreasing: number of bins of capacity `cap` needed."""
    loads: list[float] = []
    for s in np.sort(sizes)[::-1]:
        for i, l in enumerate(loads):
            if l + s <= cap + 1e-9:
                loads[i] = l + s
                break
        else:
            loads.append(float(s))
    return len(loads)


def lpt(sizes: np.ndarray, p: int) -> float:
    """Makespan of LPT list scheduling of indivisible jobs on p identical processors."""
    h = [0.0] * p
    for s in np.sort(sizes)[::-1]:
        heapq.heapreplace(h, h[0] + float(s))
    return max(h)


def scheduling(work: np.ndarray, label: str) -> dict:
    total = float(work.sum())
    big = float(work.max())
    mk = []
    for p in P_RANGE:
        m = lpt(work, p)
        mk.append({"P": p, "makespan": m, "makespan_pct_of_total": 100 * m / total,
                   "speedup": total / m, "lower_bound": max(total / p, big),
                   "makespan_equals_largest_network": bool(abs(m - big) < 1e-6 * total)})
    p_min = next((r["P"] for r in mk if r["makespan_equals_largest_network"]), None)
    return {
        "work": label,
        "total": total,
        "largest_network": big,
        "largest_share_pct": 100 * big / total,
        "max_speedup_by_network": total / big,
        "lower_bound_processors_ceil_total_over_largest": int(np.ceil(total / big - 1e-12)),
        "ffd_processors_with_capacity_largest": ffd_bins(work, big),
        "lpt_smallest_P_with_makespan_equal_largest": p_min,
        "lpt_makespan_vs_P": mk,
    }


def analyze_domain(path: Path) -> tuple[pd.DataFrame, dict, dict]:
    d = load(path)
    ds, indeg, up_order, up_ptr, found = graph(d["link"], d["to"])
    net, depth, dist, rcount = traverse(ds, indeg, up_order, up_ptr, d["length_m"])
    n = ds.size
    foreign = foreign_mask(d["lat"], d["lon"])
    on_cycle = int((net < 0).sum())
    outlets = np.flatnonzero(ds < 0)
    nn = outlets.size
    ok = net >= 0
    g = net[ok]

    def bsum(x):
        return np.bincount(g, weights=x[ok], minlength=nn)

    def bmax(x):
        out = np.full(nn, np.iinfo(np.int64).min if x.dtype.kind == "i" else -np.inf, x.dtype)
        np.maximum.at(out, g, x[ok])
        return out

    is_head = indeg != 1
    hw = indeg == 0
    wb_ok = d["wb"] != WB_MISSING
    wb_pairs = pd.DataFrame({"net": net[ok & wb_ok], "wb": d["wb"][ok & wb_ok]}).drop_duplicates()
    wb_unique = np.bincount(wb_pairs["net"].to_numpy(), minlength=nn)
    rpath = np.full(nn, 0, np.int64)
    np.maximum.at(rpath, net[ok & hw], rcount[ok & hw])

    df = pd.DataFrame({
        "outlet_feature_id": d["link"][outlets],
        "outlet_to": d["to"][outlets],
        "outlet_lat": np.round(d["lat"][outlets], 4),
        "outlet_lon": np.round(d["lon"][outlets], 4),
        "n_segments": np.bincount(g, minlength=nn),
        "n_reaches": bsum(is_head.astype(float)).astype(np.int64),
        "length_km": bsum(d["length_m"]) / 1000.0,
        "max_order": bmax(d["order"]),
        "outlet_order": d["order"][outlets],
        "longest_path_segments": bmax(depth) + 1,
        "max_depth": bmax(depth),
        "longest_path_reaches": rpath,
        "longest_path_km": bmax(dist) / 1000.0,
        "n_headwaters": bsum(hw.astype(float)).astype(np.int64),
        "n_junctions": bsum((indeg >= 2).astype(float)).astype(np.int64),
        "n_gages": bsum(d["gage"].astype(float)).astype(np.int64),
        "n_waterbody_segments": bsum(wb_ok.astype(float)).astype(np.int64),
        "n_waterbodies": wb_unique,
        "n_ids_ge_1e9": bsum((d["link"] >= BIG_ID).astype(float)).astype(np.int64),
        "n_segments_in_canada_mexico": bsum(foreign.astype(float)).astype(np.int64),
    })
    df["pct_domain_segments"] = 100 * df["n_segments"] / n
    df["pct_domain_length"] = 100 * df["length_km"] / df["length_km"].sum()
    df = df.sort_values(["n_segments", "outlet_feature_id"], ascending=[False, True]).reset_index(drop=True)
    df.insert(0, "rank", np.arange(1, nn + 1))

    sizes = df["n_segments"].to_numpy()
    q = [0.5, 0.9, 0.99, 0.999]
    edges = 2 ** np.arange(0, int(np.ceil(np.log2(sizes.max()))) + 2)
    hist, _ = np.histogram(sizes, bins=edges)
    s = {
        "n_segments": int(n),
        "n_networks": int(nn),
        "n_outlets_to_zero": int((d["to"][outlets] == 0).sum()),
        "n_outlets_to_missing_id": int((d["to"][outlets] != 0).sum()),
        "n_segments_on_cycles": on_cycle,
        "n_reaches": int(is_head.sum()),
        "n_headwaters": int(hw.sum()),
        "n_junctions": int((indeg >= 2).sum()),
        "max_indegree": int(indeg.max()),
        "total_length_km": float(d["length_m"].sum() / 1000),
        "n_gage_segments": int(d["gage"].sum()),
        "n_waterbody_segments": int(wb_ok.sum()),
        "n_waterbodies": int(np.unique(d["wb"][wb_ok]).size),
        "n_segments_in_canada_mexico": int(foreign.sum()),
        "n_networks_with_segments_in_canada_mexico": int((np.bincount(g, weights=foreign[ok].astype(float),
                                                                      minlength=nn) > 0).sum()),
        "n_ids_ge_1e9_in_canada_mexico": int((foreign & (d["link"] >= BIG_ID)).sum()),
        "ids_ge_1e9": {
            "n_segments": int((d["link"] >= BIG_ID).sum()),
            "by_id_prefix_link_div_1e7": {str(k): int(v) for k, v in zip(*np.unique(
                d["link"][d["link"] >= BIG_ID] // 10_000_000, return_counts=True))},
            "n_north_of_49.05N": int(((d["link"] >= BIG_ID) & (d["lat"] > 49.05)).sum()),
            "n_south_of_31.3N": int(((d["link"] >= BIG_ID) & (d["lat"] < 31.3)).sum()),
            "n_networks_containing": int((np.bincount(g, weights=(d["link"] >= BIG_ID)[ok].astype(float),
                                                      minlength=nn) > 0).sum()),
        },
        "network_size_quantiles": {str(k): float(np.quantile(sizes, k)) for k in q},
        "network_size_median": float(np.median(sizes)),
        "network_size_mean": float(sizes.mean()),
        "n_single_segment_networks": int((sizes == 1).sum()),
        "n_networks_ge": {str(t): int((sizes >= t).sum()) for t in (10, 100, 1000, 10000, 100000)},
        "share_of_segments_in_largest_k_pct": {str(k): float(100 * sizes[:k].sum() / n) for k in TOPK},
        "size_histogram_log2_bins": {"edges": edges.tolist(), "counts": hist.tolist()},
        "largest": {c: df[c].iloc[0].item() for c in ["outlet_feature_id", "n_segments", "n_reaches",
                    "longest_path_segments", "longest_path_reaches", "longest_path_km", "max_order"]},
        "scheduling_segments": scheduling(sizes.astype(float), "segments"),
        "scheduling_length_km": scheduling(df["length_km"].to_numpy(), "channel length (km)"),
    }
    s["without_segments_in_canada_mexico"] = split_without(d, ~foreign, net, d["link"][outlets])
    s["without_ids_ge_1e9"] = split_without(d, d["link"] < BIG_ID, net, d["link"][outlets])
    return df, s, {"link": d["link"], "to": d["to"], "lat": d["lat"], "lon": d["lon"], "net": net, "outlet_ids": d["link"][outlets]}


WATCH = (22811611, 23832907, 21412883, 626220)


def split_without(d: dict, keep: np.ndarray, net0: np.ndarray, outlet_ids0: np.ndarray) -> dict:
    """Recompute networks after deleting segments (keep == False). A kept segment whose
    `to` was deleted becomes an outlet. Reports the domain network count and, for the
    networks in WATCH, the pieces they fall into."""
    if keep.all():
        return {"n_removed": 0}
    link, to = d["link"][keep], d["to"][keep]
    ds, indeg, up_order, up_ptr, _ = graph(link, to)
    net, depth, dist, _ = traverse(ds, indeg, up_order, up_ptr, d["length_m"][keep])
    outl = np.flatnonzero(ds < 0)
    size = np.bincount(net, minlength=outl.size)
    lp = np.zeros(outl.size, np.int64)
    np.maximum.at(lp, net, depth + 1)
    km = np.zeros(outl.size)
    np.maximum.at(km, net, dist / 1000)
    orig = outlet_ids0[net0[keep]]  # original network (by outlet) of each kept segment
    lat, lon = d["lat"][keep], d["lon"][keep]
    res = {"n_removed": int((~keep).sum()), "n_networks": int(outl.size), "pieces": {}}
    for w in WATCH:
        m = orig == w
        if not m.any():
            continue
        ids, cnt = np.unique(net[m], return_counts=True)
        o = np.argsort(-cnt)
        res["pieces"][str(w)] = {
            "n_kept_segments": int(m.sum()), "n_pieces": int(ids.size),
            "largest_pieces": [{"outlet_feature_id": int(link[outl[ids[k]]]),
                                "outlet_lat": round(float(lat[outl[ids[k]]]), 4),
                                "outlet_lon": round(float(lon[outl[ids[k]]]), 4),
                                "n_segments": int(size[ids[k]]), "longest_path_segments": int(lp[ids[k]]),
                                "longest_path_km": round(float(km[ids[k]]), 1)} for k in o[:5]],
        }
    return res


def continuity(g: dict, df: pd.DataFrame) -> dict:
    """Which networks hold the NHDPlus upstream-mainstem flowlines (NLDI snapshot in
    river_names.json) of selected rivers? One network = mainstem continuous."""
    snap_path = HERE / "river_names.json"
    if not snap_path.exists():
        return {}
    snap = json.loads(snap_path.read_text())["mainstem_continuity"]
    srt = np.argsort(g["link"])
    rank = pd.Series(df["rank"].to_numpy(), index=df["outlet_feature_id"].to_numpy())
    size = pd.Series(df["n_segments"].to_numpy(), index=df["outlet_feature_id"].to_numpy())
    out = {}
    for fid, rec in snap.items():
        ms = np.array(rec["mainstem"], dtype=float)
        c = ms[:, 0].astype(np.int64)
        pos = np.clip(np.searchsorted(g["link"][srt], c), 0, srt.size - 1)
        hit = g["link"][srt][pos] == c
        nets = g["net"][srt[pos[hit]]]
        nets = nets[nets >= 0]
        oid, cnt = np.unique(g["outlet_ids"][nets], return_counts=True)
        o = np.argsort(-cnt)
        out[fid] = {
            "nldi_mainstem_flowlines": int(c.size),
            "present_in_routelink": int(hit.sum()),
            "mainstem_lat_range": [float(ms[:, 1].min()), float(ms[:, 1].max())],
            "absent_lat_range": [float(ms[~hit, 1].min()), float(ms[~hit, 1].max())] if (~hit).any() else None,
            "absent_lon_range": [float(ms[~hit, 2].min()), float(ms[~hit, 2].max())] if (~hit).any() else None,
            "n_networks_holding_mainstem": int(oid.size),
            "networks": [{"outlet_feature_id": int(oid[k]), "rank": int(rank[oid[k]]),
                          "n_segments": int(size[oid[k]]), "mainstem_flowlines": int(cnt[k])}
                         for k in o[:10]],
        }
    return out


def fig_sizes(dfs: dict[str, pd.DataFrame]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2 = "#0b0b0b", "#52514e"
    colors = {"CONUS": "#2a78d6", "AK": "#eb6834", "HI": "#1baf7a", "PRVI": "#4a3aa7"}
    fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.8))
    for dom, df in dfs.items():
        sz = df["n_segments"].to_numpy()
        a.loglog(np.arange(1, sz.size + 1), sz, lw=2, color=colors[dom], label=f"{dom} ({sz.size:,} networks)")
    a.set_xlabel("Network rank (by segments)", color=ink2)
    a.set_ylabel("Segments in network", color=ink2)
    a.set_title("Rank-size of independent networks", color=ink, loc="left", fontsize=10)
    a.legend(frameon=False, fontsize=8)
    sz = dfs["CONUS"]["n_segments"].to_numpy()
    edges = 2.0 ** np.arange(0, int(np.ceil(np.log2(sz.max()))) + 2)
    a2 = b
    a2.hist(sz, bins=edges, color=colors["CONUS"], edgecolor="white", linewidth=1)
    a2.set_xscale("log")
    a2.set_yscale("log")
    a2.set_xlabel("Segments in network (log2 bins)", color=ink2)
    a2.set_ylabel("Number of networks", color=ink2)
    a2.set_title("CONUS network-size histogram", color=ink, loc="left", fontsize=10)
    for ax in (a, b):
        ax.grid(alpha=0.25, lw=0.5)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(colors=ink2, labelsize=8)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(RESULTS / f"fig_network_sizes.{ext}", dpi=200)
    plt.close(fig)


def fig_makespan(s: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2 = "#0b0b0b", "#52514e"
    fig, ax = plt.subplots(figsize=(5.5, 3.8))
    for key, color, lab, dy, va in (("scheduling_segments", "#2a78d6", "work = segments", 3, "bottom"),
                                    ("scheduling_length_km", "#eb6834", "work = channel length", -3, "top")):
        sc = s[key]
        P = [r["P"] for r in sc["lpt_makespan_vs_P"]]
        m = [r["makespan_pct_of_total"] for r in sc["lpt_makespan_vs_P"]]
        ax.plot(P, m, "-o", lw=2, ms=4, color=color, label=f"LPT by network, {lab}")
        ax.axhline(sc["largest_share_pct"], color=color, lw=1, ls="--")
        ax.annotate(f"largest network, {lab.split('= ')[1]}: {sc['largest_share_pct']:.1f}%", (16, sc["largest_share_pct"]),
                    xytext=(0, dy), textcoords="offset points", ha="right", va=va, fontsize=8, color=ink2)
    P = np.arange(1, 17)
    ax.plot(P, 100 / P, ":", color=ink2, lw=1.2, label="ideal (100%/P)")
    ax.set_xlabel("Processors P", color=ink2)
    ax.set_ylabel("Makespan (% of total CONUS work)", color=ink2)
    ax.set_title("By-network parallelism is capped by the largest network", color=ink, loc="left", fontsize=10)
    ax.set_xticks(P)
    ax.set_ylim(0, 105)
    ax.grid(alpha=0.25, lw=0.5)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors=ink2, labelsize=8)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(RESULTS / f"fig_makespan.{ext}", dpi=200)
    plt.close(fig)


BORDER_KM = 10.0
NE_FILE = DATA / "ne" / "ne_10m_admin_0_boundary_lines_land.geojson"
NE_COUNTRIES = DATA / "ne" / "ne_50m_admin_0_countries.geojson"


def foreign_mask(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """True where a point lies inside the Canada or Mexico polygons of Natural Earth
    1:50m admin-0 countries. Approximate within a few km of the border (1:50m)."""
    from matplotlib.path import Path as MPath
    feats = json.loads(NE_COUNTRIES.read_text())["features"]
    pts = np.column_stack([lon, lat])
    out = np.zeros(lat.size, bool)
    for f in feats:
        if f["properties"]["ADMIN"] not in ("Canada", "Mexico"):
            continue
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            ring = np.asarray(poly[0])
            x0, y0 = ring.min(axis=0)
            x1, y1 = ring.max(axis=0)
            cand = np.flatnonzero((pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1))
            if cand.size == 0:
                continue
            inside = MPath(ring).contains_points(pts[cand])
            for hole in poly[1:]:
                inside &= ~MPath(np.asarray(hole)).contains_points(pts[cand])
            out[cand[inside]] = True
    return out


def border_distance_km(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Distance (km) from each point to the nearest U.S. international land boundary
    (Natural Earth 1:10m; local equirectangular approximation, fine at < ~50 km)."""
    feats = json.loads(NE_FILE.read_text())["features"]
    segs = []
    for f in feats:
        pr = f["properties"]
        if "United States of America" not in (pr["ADM0_LEFT"], pr["ADM0_RIGHT"]):
            continue
        g = f["geometry"]
        for line in (g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]):
            a = np.asarray(line)
            segs.append(np.hstack([a[:-1], a[1:]]))
    S = np.vstack(segs)  # lon1, lat1, lon2, lat2
    out = np.empty(lat.size)
    for k in range(0, lat.size, 512):
        la, lo = lat[k:k + 512, None], lon[k:k + 512, None]
        c = np.cos(np.radians(la))
        ax, ay = (S[:, 0] - lo) * c * 111.32, (S[:, 1] - la) * 110.57
        bx, by = (S[:, 2] - lo) * c * 111.32, (S[:, 3] - la) * 110.57
        dx, dy = bx - ax, by - ay
        t = np.clip(-(ax * dx + ay * dy) / np.maximum(dx * dx + dy * dy, 1e-12), 0, 1)
        out[k:k + 512] = np.sqrt((ax + t * dx) ** 2 + (ay + t * dy) ** 2).min(axis=1)
    return out


def classify(rec: dict | None, border_km: float) -> tuple[str, str, str]:
    """(class, confidence, method) for one outlet. See README "Outlet classes"."""
    if rec is None:
        if border_km <= BORDER_KM:
            return ("international_boundary_cut", "medium", f"outlet within {BORDER_KM:g} km of the "
                    "U.S. international boundary (Natural Earth); no NHDPlus V2 attributes queried")
        return ("not_classified", "", "outside the NHDPlus snapshot (river_names.py --top)")
    in_nhd = rec.get("outlet_in_nhdplus_v2")
    if in_nhd and rec.get("nhdplus_downstream_ftype") == "Coastline":
        return ("coastal", "high", "NHDPlus V2 dnhydroseq of the outlet COMID is a Coastline feature")
    if border_km <= BORDER_KM:
        conf = "high" if in_nhd else "medium"
        why = ("NHDPlus V2 continues downstream (terminalfl = 0)" if in_nhd and rec.get("nhdplus_terminalfl") == 0
               else "NHDPlus V2 also ends here (terminalfl = 1, dnhydroseq = 0)" if in_nhd
               else "outlet COMID not in NHDPlus V2")
        return ("international_boundary_cut", conf,
                f"outlet within {BORDER_KM:g} km of the U.S. international boundary (Natural Earth); {why}")
    if in_nhd and rec.get("nhdplus_terminalfl") == 1 and not rec.get("nhdplus_dnhydroseq"):
        return ("inland_terminal", "medium", "NHDPlus V2 terminal flowline with no downstream feature "
                f"(dnhydroseq = 0), > {BORDER_KM:g} km from the international boundary: a closed (endorheic) "
                "basin or a stream that NHDPlus leaves disconnected (e.g., a losing/dry channel)")
    if in_nhd and rec.get("nhdplus_terminalfl") == 0:
        return ("routelink_truncated", "medium", "NHDPlus V2 continues downstream of the RouteLink outlet")
    return ("undetermined", "", "outlet COMID not in NHDPlus V2 (or attributes inconclusive)")


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    """Add border distance (all networks) and names/outlet class (snapshot networks)."""
    names_path = HERE / "river_names.json"
    names = json.loads(names_path.read_text())["names"] if names_path.exists() else {}
    df = df.copy()
    df["border_km"] = border_distance_km(df["outlet_lat"].to_numpy(), df["outlet_lon"].to_numpy())
    recs = [names.get(str(f)) for f in df["outlet_feature_id"]]
    df["river_name"] = [r["name"] if r else "" for r in recs]
    df["mainstem_name"] = [(r.get("mainstem_name") or "") if r else "" for r in recs]
    df["name_steps_up"] = [r.get("mainstem_steps_up") if r else None for r in recs]
    df["nhdplus_totdasqkm"] = [r.get("nhdplus_totdasqkm") if r else None for r in recs]
    cls = [classify(r, b) for r, b in zip(recs, df["border_km"])]
    df["outlet_class"] = [c[0] for c in cls]
    df["class_confidence"] = [c[1] for c in cls]
    df["class_method"] = [c[2] for c in cls]
    return df


def basin_table(df: pd.DataFrame, all_s: dict, n_top: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top-n primary networks (every CONUS outlet has to == 0) plus a summary block."""
    cols = ["rank", "river_name", "mainstem_name", "outlet_feature_id", "outlet_lat", "outlet_lon",
            "outlet_class", "class_confidence", "border_km", "n_segments", "pct_domain_segments", "n_reaches",
            "length_km", "max_order", "longest_path_segments", "longest_path_reaches", "longest_path_km",
            "n_headwaters", "n_junctions", "n_gages", "n_waterbodies", "n_waterbody_segments",
            "n_ids_ge_1e9", "n_segments_in_canada_mexico", "nhdplus_totdasqkm", "name_steps_up", "class_method"]
    top = df.head(n_top)[cols].copy()
    for c, nd in (("pct_domain_segments", 4), ("length_km", 1), ("longest_path_km", 1), ("border_km", 1),
                  ("nhdplus_totdasqkm", 1)):
        top[c] = top[c].astype(float).round(nd)
    top["name_steps_up"] = top["name_steps_up"].astype("Int64")
    rows = []
    for lo, hi in ((1, 15), (16, 100), (101, 500), (501, len(df))):
        part = df.iloc[lo - 1:hi]
        rows.append({"group": f"CONUS ranks {lo}-{min(hi, len(df))}", "n_networks": len(part),
                     "n_segments": int(part["n_segments"].sum()),
                     "pct_domain_segments": float(part["pct_domain_segments"].sum()),
                     "n_reaches": int(part["n_reaches"].sum()), "length_km": float(part["length_km"].sum()),
                     "n_gages": int(part["n_gages"].sum()), "n_waterbodies": int(part["n_waterbodies"].sum())})
    for dom in ("CONUS", "AK", "HI", "PRVI"):
        a = all_s[dom]
        rows.append({"group": f"{dom} domain total", "n_networks": a["n_networks"], "n_segments": a["n_segments"],
                     "pct_domain_segments": 100.0, "n_reaches": a["n_reaches"], "length_km": a["total_length_km"],
                     "n_gages": a["n_gage_segments"], "n_waterbodies": a["n_waterbodies"],
                     "largest_network_segments": a["largest"]["n_segments"],
                     "largest_network_feature_id": a["largest"]["outlet_feature_id"],
                     "median_network_segments": a["network_size_median"],
                     "single_segment_networks": a["n_single_segment_networks"],
                     "max_order": a["max_order"]})
    summ = pd.DataFrame(rows)
    for c in ("largest_network_segments", "largest_network_feature_id", "single_segment_networks", "max_order"):
        summ[c] = summ[c].astype("Int64")
    return top, summ


def tributaries(g: dict, df: pd.DataFrame, to: np.ndarray) -> dict:
    """Are named NHDPlus tributaries (snapshot) inside the expected network, and where
    does the downstream-most named flowline flow (the confluence segment)?"""
    snap_path = HERE / "river_names.json"
    if not snap_path.exists():
        return {}
    full = json.loads(snap_path.read_text())
    snap = full.get("tributaries", {})
    mainstem = {k: {int(r[0]) for r in v["mainstem"]} for k, v in full.get("mainstem_continuity", {}).items()}
    id2i = pd.Series(np.arange(g["link"].size), index=g["link"])
    out = {}
    for key, rec in snap.items():
        c = pd.Index(rec["comids_downstream_first"])
        present = c[c.isin(id2i.index)]
        nets = g["net"][id2i[present].to_numpy()]
        oid, cnt = np.unique(g["outlet_ids"][nets], return_counts=True)
        conf = None
        if len(present):
            dm = int(present[0])  # downstream-most named flowline present in RouteLink
            i = int(id2i[dm])
            j = int(id2i[to[i]]) if to[i] in id2i.index else None
            ms = mainstem.get(str(rec["outlet_feature_id"]), set())
            conf = {"downstream_most_named_comid_in_routelink": dm,
                    "nhdplus_downstream_most_named_comid": rec["downstream_most_comid"],
                    "flows_to": int(to[i]),
                    "flows_to_lat_lon": [round(float(g["lat"][j]), 4), round(float(g["lon"][j]), 4)] if j is not None else None,
                    "flows_to_is_on_nhdplus_mainstem": bool(int(to[i]) in ms),
                    "network_outlet": int(g["outlet_ids"][g["net"][i]])}
        out[key] = {"named_flowlines": len(c), "present_in_routelink": len(present),
                    "networks": {str(int(o)): int(n) for o, n in zip(oid, cnt)}, "confluence": conf}
    return out


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    summaries, dfs = {}, {}
    for dom, p in {**DOMAINS, **OPTIONAL}.items():
        if not p.exists():
            if dom in OPTIONAL:
                print(f"skip  {dom}: optional input {p.relative_to(HERE)} not present")
                continue
            print(f"ERROR: {p} missing; run fetch_data.py first", file=sys.stderr)
            return 1
        df, s, g = analyze_domain(p)
        s["max_order"] = int(df["max_order"].max())
        df = annotate(df)
        if dom.startswith("CONUS"):
            s["mainstem_continuity"] = continuity(g, df)
            s["tributaries"] = tributaries(g, df, g["to"])
        s["outlet_class_counts"] = df["outlet_class"].value_counts().to_dict()
        s["n_outlets_within_border_km"] = int((df["border_km"] <= BORDER_KM).sum())
        df.to_csv(RESULTS / f"networks_{dom}.csv", index=False, float_format="%.4f")
        dfs[dom], summaries[dom] = df, s
        sc = s["scheduling_segments"]
        print(f"{dom:10s} {s['n_segments']:>9,} segments  {s['n_networks']:>6,} networks  "
              f"{s['n_reaches']:>9,} reaches  largest {s['largest']['n_segments']:,} "
              f"({sc['largest_share_pct']:.1f}%)  FFD processors {sc['ffd_processors_with_capacity_largest']}")
        for fid, r in s.get("mainstem_continuity", {}).items():
            print(f"           mainstem of {fid}: {r['present_in_routelink']}/{r['nldi_mainstem_flowlines']} "
                  f"NHDPlus flowlines in RouteLink, in {r['n_networks_holding_mainstem']} network(s)")
        for k, r in s.get("tributaries", {}).items():
            print(f"           {k}: {r['present_in_routelink']}/{r['named_flowlines']} in RouteLink, "
                  f"networks {r['networks']}, confluence {r['confluence']}")
    fig_sizes({k: v for k, v in dfs.items() if k in DOMAINS})
    fig_makespan(summaries["CONUS"])
    top, summ = basin_table(dfs["CONUS"], summaries, N_TABLE)
    top.to_csv(RESULTS / "T_basins.csv", index=False)
    summ.round(4).to_csv(RESULTS / "T_basins_summary.csv", index=False)
    if "CONUS_v2.1" in dfs:
        summaries["version_comparison"] = compare_versions(dfs["CONUS"], dfs["CONUS_v2.1"])
    top20 = {dom: dfs[dom].head(20 if dom.startswith("CONUS") else 3).drop(columns=["class_method"])
             .to_dict(orient="records") for dom in dfs}
    out = {"_definitions": __doc__, "domains": summaries, "top_networks": top20}
    (RESULTS / "results.json").write_text(json.dumps(out, indent=2, default=_jsonable) + "\n")
    provenance.write(HERE, RESULTS, inputs={d: p for d, p in {**DOMAINS, **OPTIONAL}.items() if p.exists()}
                     | {"natural_earth_boundaries": NE_FILE, "river_names.json": HERE / "river_names.json"},
                     sources={"river_names.json": "snapshot of USGS NHDPlus V2 / NLDI queries; see river_names.py"})
    print(f"wrote {RESULTS}/")
    return 0


def _jsonable(o):
    if isinstance(o, (np.integer, np.floating, np.bool_)):
        return o.item()
    if o is None or (isinstance(o, float) and np.isnan(o)):
        return None
    raise TypeError(type(o))


def compare_versions(new: pd.DataFrame, old: pd.DataFrame) -> dict:
    """Networks present in one version but not the other (by outlet feature_id), and
    size changes of networks with the same outlet."""
    m = new.merge(old, on="outlet_feature_id", how="outer", suffixes=("_v316", "_v21"), indicator=True)
    both = m[m["_merge"] == "both"]
    changed = both[both["n_segments_v316"] != both["n_segments_v21"]]
    cols = ["outlet_feature_id", "n_segments_v316", "n_segments_v21", "longest_path_segments_v316",
            "longest_path_segments_v21"]
    return {
        "n_networks_v316": len(new), "n_networks_v21": len(old),
        "outlets_only_in_v316": m.loc[m["_merge"] == "left_only", "outlet_feature_id"].astype(int).tolist(),
        "outlets_only_in_v21": m.loc[m["_merge"] == "right_only", "outlet_feature_id"].astype(int).tolist(),
        "n_same_outlet_different_size": len(changed),
        "same_outlet_different_size": changed[cols].astype(int).to_dict(orient="records")[:50],
    }


if __name__ == "__main__":
    sys.exit(main())
