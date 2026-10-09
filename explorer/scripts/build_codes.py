# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas==2.3.3", "pyarrow==21.0.0", "xarray==2025.9.0", "netcdf4==1.7.2", "numpy==2.3.3"]
# ///
"""Step 1 of the basin-explorer data build: river codes for every segment, all NWM domains.

Assigns an integer code to every river the explorer can select, and tags every segment of
the four NWM v3.1.6 domains (CONUS, AK, HI, PRVI) with
  dom        0 CONUS, 1 AK, 2 HI, 3 PRVI
  net        code of its independent network if that network is listed, else 0
  river      code of the innermost listed river it drains to (a sub-river code, else the
             network code, else 0)
  d_seg      topological distance from its network outlet, in segments (outlet = 0)
  d_reach    the same distance in reaches (a segment starts a new reach unless it has
             exactly one upstream segment; the outlet's reach = 0)
  p, z       depth-first preorder index (upstream traversal from each outlet) and the size
             of the segment's upstream subtree, so "everything upstream of segment s" is
             exactly the segments with p in [p_s, p_s + z_s). p is unique across ALL
             domains (domains are numbered one after the other: CONUS, AK, HI, PRVI).
  xb         hydrography source: 1 if the segment is not from the domain's NHDPlus
             (CONUS: feature_id >= 1e9; AK: Arc-Hydro IDs 190201xxxxxxxx and the six
             synthetic lake links < 100), else 0. NOT a transboundary flag.
  tb         position relative to the U.S. international boundary (build_boundary.py):
             0 inside the U.S., 1 outside (Canada/Mexico), 2 on the boundary
Codes (unique across domains): code = base + rank for listed networks (rank 1..999) and
base + 1001 + i for listed sub-rivers (i in table order), with base = 0 (CONUS),
10000 (AK), 20000 (HI), 30000 (PRVI). CONUS codes are unchanged (networks 1..500,
sub-rivers 1001..). Primary rivers in the sub-river tables reuse their network's code.

Inputs:  data/RouteLink_{CONUS,AK,HI,PRVI}.nc (NWM v3.1.6; repro/network_stats/fetch_data.py)
         repro/network_stats/results/T_basins.csv, T_basins_{AK,HI,PRVI}.csv, T_subrivers.csv,
         T_subrivers_ext.csv (AK/HI/PRVI sub-rivers and, for every domain, the inflows of
         networks renamed by the lake-outlet / outlet-confluence rules)
         data/explorer/segment_boundary.parquet (explorer/scripts/build_boundary.py)
Outputs: explorer/data/rivers.json   (web data bundle: tree, codes, stats)
         data/explorer/segment_attrs.parquet (gitignored: one row per segment)
Usage:   uv run explorer/scripts/build_codes.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

ROOT = Path(__file__).resolve().parents[2]
T = ROOT / "repro" / "network_stats" / "results"
OUT_JSON = ROOT / "explorer" / "data" / "rivers.json"
OUT_PQ = ROOT / "data" / "explorer" / "segment_attrs.parquet"
BOUNDARY = ROOT / "data" / "explorer" / "segment_boundary.parquet"
DOMAINS = ["CONUS", "AK", "HI", "PRVI"]
DOM_INDEX = {d: i for i, d in enumerate(DOMAINS)}
BASE = {"CONUS": 0, "AK": 10000, "HI": 20000, "PRVI": 30000}
LABEL = {"CONUS": "Contiguous U.S.", "AK": "Alaska (Cook Inlet and Copper River)", "HI": "Hawaii",
         "PRVI": "Puerto Rico and U.S. Virgin Islands"}
TB_CODE = {"in": 0, "out": 1, "on": 2}


def clean(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def domain(dom, p_offset, bnd):
    basins = pd.read_csv(T / ("T_basins.csv" if dom == "CONUS" else f"T_basins_{dom}.csv"))
    ext = pd.read_csv(T / "T_subrivers_ext.csv")
    ext = ext[ext["domain"] == dom]
    if dom == "CONUS":   # CONUS list first (codes 1001.. unchanged), then lake/confluence inflows
        subs = pd.read_csv(T / "T_subrivers.csv")
        subs["pct_domain"] = subs["pct_conus"]
        subs = pd.concat([subs, ext], ignore_index=True)
    else:
        subs = ext.reset_index(drop=True)
    base = BASE[dom]

    ds = xr.open_dataset(ROOT / "data" / f"RouteLink_{dom}.nc")
    link = ds["link"].values.astype(np.int64)
    to = ds["to"].values.astype(np.int64)
    order = ds["order"].values.astype(np.int16)
    lat = ds["lat"].values.astype(np.float32)
    lon = ds["lon"].values.astype(np.float32)
    length_m = ds["Length"].values.astype(np.float64)
    n = len(link)
    idx = pd.Series(np.arange(n), index=link)
    down = idx.reindex(to).to_numpy()                     # NaN where outlet
    is_out = np.isnan(down)
    down = np.where(is_out, -1, down).astype(np.int64)
    has_dn = down >= 0
    src = np.nonzero(has_dn)[0]
    dst = down[has_dn]
    order_up = np.argsort(dst, kind="stable")
    up_src = src[order_up]
    up_ptr = np.zeros(n + 1, dtype=np.int64)
    np.add.at(up_ptr, dst + 1, 1)
    up_ptr = np.cumsum(up_ptr)
    n_up = np.diff(up_ptr)

    rank_of_outlet = dict(zip(basins["outlet_feature_id"].astype(np.int64), base + basins["rank"].astype(int)))
    sub_rows = subs[subs["kind"] == "sub"].dropna(subset=["mouth_feature_id"]).reset_index(drop=True)
    sub_code = {int(fid): base + 1001 + i for i, fid in enumerate(sub_rows["mouth_feature_id"].astype(np.int64))}

    net = np.zeros(n, dtype=np.int32)
    river = np.zeros(n, dtype=np.int32)
    d_seg = np.zeros(n, dtype=np.int32)
    d_reach = np.zeros(n, dtype=np.int32)
    # depth-first preorder (upstream); parents come before children, so one pass in
    # preorder also propagates net/river/distances
    p = np.empty(n, dtype=np.int64)
    order_list = np.empty(n, dtype=np.int64)
    k = 0
    for o in np.nonzero(is_out)[0]:
        r = rank_of_outlet.get(int(link[o]), 0)
        net[o] = r
        river[o] = sub_code.get(int(link[o]), r)
        stack = [o]
        while stack:
            x = stack.pop()
            p[x] = p_offset + k; order_list[k] = x; k += 1
            ups = up_src[up_ptr[x]:up_ptr[x + 1]]
            for u in ups:
                net[u] = net[x]
                river[u] = sub_code.get(int(link[u]), river[x])
                d_seg[u] = d_seg[x] + 1
                d_reach[u] = d_reach[x] + (0 if n_up[x] == 1 else 1)
            if len(ups):
                stack.extend(ups[::-1].tolist())
    assert k == n
    z = np.ones(n, dtype=np.int64)
    for x in order_list[::-1]:
        dn = down[x]
        if dn >= 0:
            z[dn] += z[x]

    if dom == "CONUS":
        xb = (link >= 1_000_000_000).astype(np.int8)
    elif dom == "AK":
        xb = ((link // 10**8 == 190201) | (link < 100)).astype(np.int8)
    else:
        xb = np.zeros(n, np.int8)
    # transboundary status per segment (0 in, 1 out, 2 on); segments without geometry: in
    b = bnd[bnd["dom"] == DOM_INDEX[dom]].set_index("feature_id")
    tb = b["status"].map(TB_CODE).reindex(link).fillna(0).to_numpy().astype(np.int8)
    missing_geom = int(b.reindex(link)["status"].isna().sum())
    # crossings with hysteresis: compare each clear (in/out) segment with the next clear
    # segment downstream, skipping "on the boundary" segments
    nclear = np.full(n, -1, np.int64)
    for x in order_list:                      # parents first
        dn = down[x]
        if dn >= 0:
            nclear[x] = dn if tb[dn] != 2 else nclear[dn]
    clear = (tb != 2) & (nclear >= 0)
    nc_tb = np.where(nclear >= 0, tb[np.maximum(nclear, 0)], -1)
    cross_in = (clear & (tb == 1) & (nc_tb == 0)).astype(np.int64)
    cross_out = (clear & (tb == 0) & (nc_tb == 1)).astype(np.int64)

    OUT_cols = pd.DataFrame({"feature_id": link, "dom": np.int8(DOM_INDEX[dom]), "net": net, "river": river,
                             "order": order, "d_seg": d_seg, "d_reach": d_reach, "p": p.astype(np.int32),
                             "z": z.astype(np.int32), "xb": xb, "tb": tb, "lat": lat, "lon": lon})

    csum = lambda v: np.concatenate([[0], np.cumsum(v[order_list])])
    L = length_m / 1000.0
    S = {"xb_segments": csum(xb.astype(np.int64)), "xb_km": csum(xb * L),
         "tb_out_segments": csum((tb == 1).astype(np.int64)), "tb_out_km": csum((tb == 1) * L),
         "tb_on_km": csum((tb == 2) * L), "tb_in_segments": csum((tb == 0).astype(np.int64)),
         "tb_cross_in": csum(cross_in), "tb_cross_out": csum(cross_out)}
    country = b["country"].reindex(link).fillna("").to_numpy()

    def subtree(fid):
        i = int(idx[fid]); a = int(p[i]) - p_offset; e = a + int(z[i])
        v = {k: (S[k][e] - S[k][a]) for k in S}
        out = {"p": int(p[i]), "z": int(z[i]), "xb_segments": int(v["xb_segments"]), "xb_km": round(float(v["xb_km"]), 1)}
        n_out, n_in = int(v["tb_out_segments"]), int(v["tb_in_segments"])
        ci, co = int(v["tb_cross_in"]), int(v["tb_cross_out"])
        outlet_st = {0: "in", 1: "out", 2: "on"}[int(tb[i])]
        tbflag = n_out > 0 and n_in > 0
        if tbflag or n_out > 0 or v["tb_on_km"] > 0:
            ctry = sorted(set(country[order_list[a:e]][tb[order_list[a:e]] == 1]) - {""})
            out.update(tb=bool(tbflag), tb_out_segments=n_out, tb_out_km=round(float(v["tb_out_km"]), 1),
                       tb_on_km=round(float(v["tb_on_km"]), 1), tb_cross_in=ci, tb_cross_out=co,
                       tb_dir=("both" if ci and (co or outlet_st == "out") else "inbound" if ci else
                               "outbound" if (co or outlet_st == "out") else ""),
                       tb_outlet=outlet_st, tb_countries=ctry)
            if n_in == 0 and n_out > 0:
                out["tb_foreign_only"] = True
        else:
            out["tb"] = False
        return out

    river_s = pd.Series(river, index=link)
    nodes = []
    name_col = "display_name" if "display_name" in basins.columns else "river_name"
    for _, bs in basins.iterrows():
        nm = clean(bs[name_col]) or clean(bs["river_name"])
        nd = {"code": base + int(bs["rank"]), "dom": dom, "rank": int(bs["rank"]), "kind": "network", "parent": None,
              "name": nm or f"Unnamed network #{int(bs['rank'])}", "feature_id": int(bs["outlet_feature_id"]),
              **{k: clean(bs[k]) for k in ["outlet_class", "outlet_lat", "outlet_lon", "n_segments",
                 "pct_domain_segments", "n_reaches", "length_km", "max_order", "longest_path_reaches",
                 "longest_path_km", "n_gages", "n_waterbodies"] if k in bs}}
        if "name_rule" in bs and clean(bs["name_rule"]):
            nd["name_rule"] = clean(bs["name_rule"])
        if "name_note" in bs and clean(bs["name_note"]):
            nd["notes"] = clean(bs["name_note"])
        if nd.get("name_rule") == "lake_outlet":
            nd["level_path_name"] = clean(bs["river_name"])
        nodes.append(nd)
    prim = subs[subs["kind"] == "primary"]
    primary_names = {base + int(r["network_rank"]): r["label"] for _, r in prim.iterrows()
                     if not pd.isna(r.get("network_rank")) and r.get("mouth_feature_id") == r.get("network_outlet_feature_id")}
    for nd in nodes:
        if nd["code"] in primary_names:
            nd["list_label"] = primary_names[nd["code"]]
    for i, r in sub_rows.iterrows():
        fid = int(r["mouth_feature_id"])
        dn = to[idx[fid]]
        parent = int(river_s.get(dn, 0)) if dn else None
        nd = {"code": base + 1001 + i, "dom": dom, "kind": "sub", "parent": parent or None, "name": r["label"],
              "feature_id": fid, "network": base + int(r["network_rank"]) if not pd.isna(r["network_rank"]) else None,
              **{k: clean(r[k]) for k in ["source", "city", "status", "joins", "notes", "mouth_lat", "mouth_lon",
                 "n_segments", "pct_parent", "pct_domain", "n_reaches", "length_km", "max_order",
                 "longest_path_reaches", "longest_path_km", "n_gages", "n_waterbodies"] if k in r}}
        nodes.append(nd)
    for nd in nodes:
        nd.update(subtree(nd["feature_id"]))
    info = {"code_base": base, "label": LABEL[dom], "n_segments": int(n), "n_networks": int(is_out.sum()),
            "n_listed_networks": int(len(basins)), "n_listed_subrivers": int(len(sub_rows)),
            "bbox": [round(float(lon.min()), 3), round(float(lat.min()), 3), round(float(lon.max()), 3),
                     round(float(lat.max()), 3)],
            "p_range": [int(p_offset), int(p_offset + n)], "segments_without_geometry": missing_geom,
            "tb_segments": {"out": int((tb == 1).sum()), "on": int((tb == 2).sum())}}
    return OUT_cols, nodes, info


def main():
    bnd = pd.read_parquet(BOUNDARY)
    frames, nodes, info, off = [], [], {}, 0
    for dom in DOMAINS:
        f, nd, inf = domain(dom, off, bnd)
        off += len(f)
        frames.append(f); nodes += nd; info[dom] = inf
        print(f"{dom}: {inf['n_segments']:,} segments; {inf['n_networks']:,} networks; listed "
              f"{inf['n_listed_networks']} networks + {inf['n_listed_subrivers']} sub-rivers; tb {inf['tb_segments']}; "
              f"p {inf['p_range']}")
    attrs = pd.concat(frames, ignore_index=True)
    assert attrs["p"].is_unique, "preorder index p must be unique across domains"
    OUT_PQ.parent.mkdir(parents=True, exist_ok=True)
    attrs.to_parquet(OUT_PQ, index=False)
    codes = [nd["code"] for nd in nodes]
    assert len(codes) == len(set(codes)), "codes must be unique across domains"
    meta = {"routelink": "NWM v3.1.6 RouteLink_{CONUS,AK,HI,PRVI}.nc",
            "codes": "code = base + rank (listed networks) or base + 1001 + i (listed sub-rivers); "
                     "base CONUS 0, AK 10000, HI 20000, PRVI 30000",
            "domains": info,
            "reach_rule": "a segment starts a new reach unless it has exactly one upstream segment",
            "hydrography_source": "xb_segments / xb_km: channel not from the domain's NHDPlus (CONUS feature_id >= 1e9, "
                                  "AK Arc-Hydro and synthetic links); not a transboundary measure",
            "transboundary": "tb: the river has channel both inside and outside the U.S. (TIGER/Line 2024 states); "
                             "tb_out_km: channel outside the U.S. (segments > 50% outside and not on the boundary); "
                             "tb_on_km: channel within 500 m of the international boundary (border rivers); "
                             "tb_cross_in/out: boundary crossings along the flow, counted between clearly-inside "
                             "and clearly-outside segments only; tb_outlet: in/out/on for the outlet or mouth segment",
            "upstream_interval": "segments upstream of a node (inclusive) have DFS preorder p in [p, p+z); "
                                 "p is unique across domains",
            "total_segments": int(len(attrs))}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({"meta": meta, "nodes": nodes}, separators=(",", ":"), ensure_ascii=False))
    print(f"segments {len(attrs):,}; nodes {len(nodes)}; rivers.json {OUT_JSON.stat().st_size / 1e6:.2f} MB")
    by = {nd["code"]: nd for nd in nodes}
    print("Mississippi z (expect 1,117,312):", by[1]["z"], "| Mississippi n_segments:", by[1]["n_segments"])
    assert by[1]["z"] == 1_117_312
    bad = [nd["code"] for nd in nodes if nd["kind"] == "network" and nd["z"] != nd["n_segments"]]
    print("networks whose outlet subtree size != n_segments:", bad[:10])
    assert not bad
    print("transboundary networks:")
    for nd in sorted((x for x in nodes if x["kind"] == "network" and x.get("tb")), key=lambda x: -x["tb_out_km"])[:25]:
        print(f"  {nd['dom']:5} {nd['code']:>6} {nd['name'][:40]:40} out {nd['tb_out_km']:>9,.1f} km "
              f"({nd['tb_out_segments']:,} seg) on {nd['tb_on_km']:>7,.1f} km  in/out crossings "
              f"{nd['tb_cross_in']}/{nd['tb_cross_out']} {nd['tb_dir']:8} outlet {nd['tb_outlet']} {nd['tb_countries']}")
    print("n transboundary networks:", sum(1 for x in nodes if x["kind"] == "network" and x.get("tb")),
          "; listed sub-rivers:", sum(1 for x in nodes if x["kind"] == "sub" and x.get("tb")))


if __name__ == "__main__":
    main()
