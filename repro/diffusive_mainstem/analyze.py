"""Screen the NWM v3.1.6 channel network for known Muskingum-Cunge (MC) error regimes and
MC parameter-limit effects, and size candidate diffusive-routing "mainstem" selections.

ASSUMPTION (not demonstrated here): switching a segment from MC to diffusive routing
removes the MC errors and parameter effects listed below for that segment. No model is run.

Steps (CONUS; AK/HI/PRVI get the RouteLink-only indicators):
 1. Topology and bankfull hydraulics from RouteLink (indicators.py).
 2. Per segment, two separate kinds of flag:
    Known MC error ("error"):
      LS  low slope, S0 < 2.5e-4 (Tang et al. 1999: VPMC volume loss beyond "just about
          tolerable"); tiers 1e-4, 1e-3 and the RouteLink floor 1e-5 are reported too
      BW  inside a Samuels (1989) backwater length of (i) a confluence with a larger river,
          (ii) the network outlet, or (iii) an NWM lake inlet
    error score = LS + BW (0-2); "error-flagged" = error score >= 1.
    MC parameter-limit effects ("effect"; design choices of the algorithm, not errors):
      XF  the kernel's X >= 0.25 floor binds at bankfull
      KC  K is clamped to dt (Km = max(dt, dx/ck)) at bankfull with the NWM's dt = 300 s,
          i.e. the Courant number ck dt / dx > 1
    "effect-flagged" = XF or KC. The two budgets are reported separately, never summed.
    Ponce, Li & Simons (1978) kinematic / diffusion / dynamic classes for T = 1, 3, 10 days
    are reported separately (where even diffusive routing is not enough).
 3. Mean annual flow and velocity (NHDPlusV2 EROM, Q0001E/V0001E) -> mean-flow depth.
 4. Survey-feasibility layer: depth thresholds; USACE/BTS National Waterway Network;
    USACE eHydro survey footprints; USGS physiographic divisions.
 5. Configurations A-F, their metrics, the Pareto curve, cost proxies.
Outputs: results/results.json, results/segments_conus.parquet (per-segment table),
results/pareto.parquet. Figures: figures.py. Potomac check: potomac_check.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

import indicators as I
import provenance
import spatial

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"
NAMES = HERE.parent / "network_stats" / "results" / "T_basins.csv"   # run ../network_stats first

# ---- screening parameters (all stated in README.md) ----
LS_MAIN = 2.5e-4
LS_TIERS = (1e-4, 2.5e-4, 1e-3)
PERIODS = (1, 3, 10)
DEPTH_T = (1.0, 2.0)
MAINSTEM_DA_KM2 = 10_000.0
MAINSTEM_DA_SENS = (2_500.0, 50_000.0)
DT_NWM_S = 300.0                 # NWM channel timestep, for the K-clamp indicator
NWN_TOL_M = 200.0
NWN_TOL_SENS = (100.0, 500.0)
TOP_NETWORKS = 5


def r(x, nd=4):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


# ------------------------------------------------------------------ indicators
def domain_indicators(rl: dict, topo: dict, size_key: np.ndarray | None) -> dict:
    """Indicators that need only RouteLink (+ optional branch-size key for confluences)."""
    hb = I.bankfull(rl)
    so, km = rl["so"], rl["length_m"] / 1000.0
    lake = rl["wb"] != -9999
    Lkm = I.backwater_length_km(hb, so)
    u = np.where(Lkm > 0, km / np.where(Lkm > 0, Lkm, 1.0), np.inf)   # segment length in units of L
    down = topo["down"]
    n = so.size

    # (ii) network outlet
    t0 = np.full(n, np.inf)
    t0[topo["outlets"]] = 0.0
    tau_out = I.propagate_up(t0, u, topo, lake)
    # (iii) NWM lake inlets: non-lake segment draining into a lake segment
    t0 = np.full(n, np.inf)
    inlet = (~lake) & (down >= 0) & lake[np.maximum(down, 0)]
    t0[inlet] = 0.0
    tau_lake = I.propagate_up(t0, u, topo, lake)
    # (i) confluences: every non-dominant upstream branch of a junction
    if size_key is None:
        size_key = topo["up_len_km"]
    up_seg = np.flatnonzero(down >= 0)
    J = down[up_seg]
    junction = topo["indeg"][J] >= 2
    up_seg, J = up_seg[junction], J[junction]
    o = np.lexsort((size_key[up_seg], J))           # by junction, then size ascending
    up_seg, J = up_seg[o], J[o]
    last = np.r_[J[1:] != J[:-1], True]              # largest branch of each junction
    trib = up_seg[~last]
    trib = trib[~lake[trib] & ~lake[down[trib]]]
    t0 = np.full(n, np.inf)
    t0[trib] = 0.0
    tau_conf = I.propagate_up(t0, u, topo, lake)

    def mid(tau):
        return (tau + 0.5 * u) < 1.0

    bw_i, bw_ii, bw_iii = mid(tau_conf), mid(tau_out), mid(tau_lake)
    bw_i, bw_ii, bw_iii = bw_i & ~lake, bw_ii & ~lake, bw_iii & ~lake
    LS = (so < LS_MAIN) & ~lake
    BW = bw_i | bw_ii | bw_iii
    XF = (hb["x_kernel_raw_bf"] < 0.25) & ~lake
    courant_bf = hb["ck_bf"] * DT_NWM_S / np.maximum(rl["length_m"], 1.0)
    KC = (courant_bf > 1.0) & ~lake
    score = LS.astype(np.int8) + BW.astype(np.int8)          # known-error score, 0-2
    effect = XF | KC
    pon = I.ponce_classes(hb, so, PERIODS)
    return {"hb": hb, "L_km": Lkm, "u": u, "lake": lake, "LS": LS, "BW": BW, "BW_i": bw_i, "BW_ii": bw_ii,
            "BW_iii": bw_iii, "XF": XF, "XF_cunge": (hb["eps_cunge_bf"] < 0.25) & ~lake, "KC": KC,
            "courant_bf": courant_bf, "score": score, "error": score >= 1, "effect": effect,
            "ponce": pon, "tau_conf": tau_conf, "trib_sources": trib, "floor": so <= I.FLOOR_TOL}


def indicator_summary(rl, ind) -> dict:
    km = rl["length_m"] / 1000.0
    ok = ~ind["lake"]
    K, N = km[ok].sum(), ok.sum()

    def sh(m):
        m = m & ok
        return {"segments": int(m.sum()), "pct_segments": r(100 * m.sum() / N, 3),
                "km": r(km[m].sum(), 1), "pct_km": r(100 * km[m].sum() / K, 3)}

    so = rl["so"]
    out = {"segments_total": int(rl["so"].size), "lake_segments_excluded": int(ind["lake"].sum()),
           "mc_segments": int(N), "mc_km": r(K, 1),
           "LS_S0_lt_2.5e-4": sh(ind["LS"]), "BW_any": sh(ind["BW"]), "BW_i_confluence": sh(ind["BW_i"]),
           "BW_ii_outlet": sh(ind["BW_ii"]), "BW_iii_lake_inlet": sh(ind["BW_iii"]),
           "error_flagged": sh(ind["error"]),
           "error_score": {str(k): sh(ind["score"] == k) for k in range(3)},
           "XF_x_floor_binds_bankfull": sh(ind["XF"]), "XF_cunge_eps_lt_0.25_bankfull": sh(ind["XF_cunge"]),
           "KC_k_clamp_dt300_bankfull": sh(ind["KC"]),
           "effect_flagged": sh(ind["effect"]),
           "error_and_effect": sh(ind["error"] & ind["effect"]),
           "effect_only": sh(ind["effect"] & ~ind["error"]),
           "slope_floor_1e-5": sh(ind["floor"])}
    for t in LS_TIERS:
        out[f"S0_lt_{t:g}"] = sh(so < t)
    for T, c in ind["ponce"].items():
        out[f"ponce_T{T}d"] = {name: sh(c == k) for k, name in enumerate(("kinematic", "diffusion", "dynamic"))}
    return out


# ------------------------------------------------------------------ CONUS extras
def conus_attributes(rl, topo) -> pd.DataFrame:
    link = rl["link"]
    vaa = pd.read_parquet(DATA / "nhdplusVAA.parquet",
                          columns=["comid", "totdasqkm", "divdasqkm", "ftype", "hydroseq", "dnhydroseq", "terminalfl",
                                   "gnis_name"])
    vaa = vaa.drop_duplicates("comid").set_index("comid")
    erom = pd.read_parquet(DATA / "erom_ma.parquet").set_index("comid")
    df = pd.DataFrame({"link": link})
    v = vaa.reindex(link)
    e = erom.reindex(link)
    df["in_vaa"] = v["divdasqkm"].notna().to_numpy()
    # Divergence-routed drainage area (DivDASqKM): a minor divergence path gets only its own
    # upstream area. TotDASqKM counts everything upstream through divergences, so side channels
    # and distributaries (e.g. delta bayous, or the side channel that gives Antietam Creek's
    # last reach 16,124 km2 instead of 730) would wrongly look like main stems.
    da = v["divdasqkm"].to_numpy(dtype=float)
    df["totdasqkm"] = v["totdasqkm"].to_numpy(dtype=float)
    da = np.where(da > 0, da, np.nan)
    q = e["qe_ma_cms"].to_numpy(dtype=float)
    vel = e["ve_ma_ms"].to_numpy(dtype=float)
    df["q_erom_raw"] = q
    df["v_erom_raw"] = vel
    df["da_km2"] = I.accumulate_missing(da, topo)
    df["da_filled"] = np.isnan(da)
    qv = np.where(q >= 0, q, np.nan)
    df["q_cms"] = I.accumulate_missing(qv, topo)
    df["q_filled"] = np.isnan(qv)
    df["gnis_name"] = v["gnis_name"].to_numpy()
    # outlet class: NHDPlus downstream feature of the outlet COMID is a Coastline flowline
    hs = vaa.reset_index().set_index("hydroseq")
    outl = topo["outlets"]
    dn = v["dnhydroseq"].to_numpy()[outl]
    dft = hs["ftype"].reindex(dn).to_numpy()
    cls = np.where(pd.isna(v["hydroseq"].to_numpy()[outl]), "non_nhdplus",
                   np.where(dft == "Coastline", "coastal", np.where(dn == 0, "terminal", "other")))
    oc = np.full(link.size, "", dtype=object)
    oc[:] = np.asarray(cls, dtype=object)[topo["net"]]
    df["outlet_class"] = oc
    return df


def mean_flow_depth(rl, hb, q, vel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Primary: A = Q/V (EROM), depth on the extended in-channel trapezoid. Where EROM
    velocity is missing (<= 0), V from Manning on the same extended trapezoid.
    Returns (h_primary, method code 0 = Q/V, 1 = Manning fallback, h_manning_compound)."""
    z = hb["z"]
    h_man_ext = I.manning_depth(q, rl, hb, compound=False)
    A_man = (rl["bw"] + z * h_man_ext) * h_man_ext
    good_v = vel > 0
    A = np.where(good_v, q / np.where(good_v, vel, 1.0), A_man)
    h = I.trapezoid_depth_from_area(A, rl["bw"], z)
    h_man_cmp = I.manning_depth(q, rl, hb, compound=True)
    return h, np.where(good_v, 0, 1).astype(np.int8), h_man_cmp


# ------------------------------------------------------------------ configurations
def longest_path_km(mask, km, topo) -> np.ndarray:
    """Longest contiguous path (km) of `mask` segments ending at each segment, measured
    upstream-to-downstream; max over a network = longest diffusive path (critical path)."""
    down = topo["down"]
    best_up = np.zeros_like(km)                 # longest masked path arriving from upstream
    path = np.zeros_like(km)
    for lev in reversed(topo["levels"]):
        path[lev] = np.where(mask[lev], km[lev] + best_up[lev], 0.0)
        d = down[lev]
        ok = d >= 0
        np.maximum.at(best_up, d[ok], path[lev][ok])
    return path


def config_metrics(name, rule, mask, ctx) -> dict:
    km, w, ok, err, eff = ctx["km"], ctx["w"], ctx["ok"], ctx["error"], ctx["effect"]
    m = mask & ok
    K = km[m].sum()
    out = {"rule": rule, "segments": int(m.sum()), "km": r(K, 1),
           "pct_network_km": r(100 * K / km[ok].sum(), 3),
           "pct_network_segments": r(100 * m.sum() / ok.sum(), 3),
           # known MC error (LS, BW)
           "pct_known_error_budget": r(100 * w[m & err].sum() / w[ok & err].sum(), 3),
           "pct_known_error_budget_score_weighted": r(100 * (w * ctx["score"])[m].sum() / (w * ctx["score"])[ok].sum(), 3),
           "pct_error_km_captured": r(100 * km[m & err].sum() / km[ok & err].sum(), 3),
           "pct_km_error_flagged": r(100 * km[m & err].sum() / max(K, 1e-9), 3),
           # MC parameter-limit effects (XF, KC), reported separately
           "pct_parameter_effect_budget": r(100 * w[m & eff].sum() / w[ok & eff].sum(), 3),
           "pct_effect_km_captured": r(100 * km[m & eff].sum() / km[ok & eff].sum(), 3),
           "pct_km_effect_flagged": r(100 * km[m & eff].sum() / max(K, 1e-9), 3),
           "pct_flow_km_total": r(100 * w[m].sum() / w[ok].sum(), 3)}
    for t in DEPTH_T:
        out[f"pct_km_depth_ge_{t:g}m"] = r(100 * km[m & (ctx["h"] >= t)].sum() / max(K, 1e-9), 2)
        out[f"pct_km_depth_ge_{t:g}m_manning_compound"] = r(100 * km[m & (ctx["h_mc"] >= t)].sum() / max(K, 1e-9), 2)
        out[f"pct_km_bankfull_ge_{t:g}m"] = r(100 * km[m & (ctx["D"] >= t)].sum() / max(K, 1e-9), 2)
    out["pct_km_on_nwn"] = r(100 * km[m & ctx["nwn"]].sum() / max(K, 1e-9), 2)
    out["pct_km_ehydro"] = r(100 * km[m & ctx["ehydro"]].sum() / max(K, 1e-9), 2) if ctx["ehydro"] is not None else None
    for T, c in ctx["ponce"].items():
        out[f"pct_km_ponce_dynamic_T{T}d"] = r(100 * km[m & (c == 2)].sum() / max(K, 1e-9), 2)
    # share of each indicator captured (by km and by flow x km)
    out["pct_of_indicator_captured"] = {
        k: {"km": r(100 * km[m & ctx["ind"][k]].sum() / max(km[ok & ctx["ind"][k]].sum(), 1e-9), 2),
            "flow_km": r(100 * w[m & ctx["ind"][k]].sum() / max(w[ok & ctx["ind"][k]].sum(), 1e-9), 2)}
        for k in ("LS", "BW", "BW_i", "BW_ii", "BW_iii", "XF", "KC")}
    out["pct_km_slope_floor"] = r(100 * km[m & ctx["floor"]].sum() / max(K, 1e-9), 2)
    # concentration in a few networks
    net = ctx["net"]
    bynet = pd.Series(km[m]).groupby(net[m]).sum().sort_values(ascending=False)
    names = ctx["net_names"]
    out["top_networks"] = [{"network": names.get(int(k), f"outlet {int(ctx['outlet_link'][k])}"),
                            "km": r(v, 1), "pct_of_config_km": r(100 * v / max(K, 1e-9), 2)}
                           for k, v in bynet.head(TOP_NETWORKS).items()]
    out["pct_km_in_top3_networks"] = r(100 * bynet.head(3).sum() / max(K, 1e-9), 2)
    out["n_networks_touched"] = int(bynet.size)
    lp = longest_path_km(m, km, ctx["topo"])
    lpn = pd.Series(lp).groupby(net).max()
    out["longest_diffusive_path_km"] = r(lpn.max(), 1)
    out["longest_diffusive_path_network"] = names.get(int(lpn.idxmax()), "") if lpn.max() > 0 else ""
    out["n_networks_with_path_gt_100km"] = int((lpn > 100).sum())
    return out


def pareto(ctx, n_pts=400) -> pd.DataFrame:
    """Greedy ordering: treat error-flagged segments in decreasing mean annual flow (budget
    per km = Q for a flagged segment), then the rest. Returns cumulative shares of the
    known-error budget and, along the same ordering, of the parameter-effect budget."""
    km, w, ok, flagged, h = ctx["km"], ctx["w"], ctx["ok"], ctx["error"], ctx["h"]
    eff = ctx["effect"]
    idx = np.flatnonzero(ok)
    key = np.where(flagged[idx], ctx["q"][idx], -1.0)
    o = idx[np.argsort(-key, kind="stable")]
    ckm = np.cumsum(km[o])
    cb = np.cumsum(np.where(flagged[o], w[o], 0.0))
    cfk = np.cumsum(np.where(flagged[o], km[o], 0.0))
    ce = np.cumsum(np.where(eff[o], w[o], 0.0))
    shallow = np.cumsum(np.where(h[o] < 1.0, km[o], 0.0))
    sel = np.unique(np.r_[np.linspace(0, o.size - 1, n_pts).astype(int), o.size - 1])
    return pd.DataFrame({"pct_km": 100 * ckm[sel] / ckm[-1], "pct_budget": 100 * cb[sel] / cb[-1],
                         "pct_flagged_km": 100 * cfk[sel] / cfk[-1],
                         "pct_effect_budget": 100 * ce[sel] / ce[-1],
                         "km": ckm[sel], "shallow_km_lt_1m": shallow[sel],
                         "q_threshold_cms": np.maximum(key[np.argsort(-key, kind='stable')][sel], 0)})


def main() -> int:
    RESULTS.mkdir(exist_ok=True)
    res = {"assumption": "assuming diffusive routing removes the listed MC errors on the segments it is applied to "
                         "(not demonstrated here)",
           "parameters": {"LS_threshold": LS_MAIN, "LS_tiers": LS_TIERS, "ponce_periods_days": PERIODS,
                          "depth_thresholds_m": DEPTH_T, "mainstem_drainage_area_km2": MAINSTEM_DA_KM2,
                          "mainstem_sensitivity_km2": MAINSTEM_DA_SENS, "k_clamp_dt_s": DT_NWM_S, "nwn_tolerance_m": NWN_TOL_M,
                          "nwn_tolerance_sensitivity_m": NWN_TOL_SENS}}

    # ---------------- all domains: RouteLink-only indicators
    res["domains"] = {}
    for dom in ("CONUS", "AK", "HI", "PRVI"):
        rl = I.load_routelink(DATA / f"RouteLink_{dom}.nc")
        topo = I.topology(rl["link"], rl["to"], rl["length_m"])
        ind = domain_indicators(rl, topo, None)
        res["domains"][dom] = indicator_summary(rl, ind)
        print(f"{dom}: {res['domains'][dom]['mc_segments']:,} MC segments")

    # ---------------- CONUS in full
    rl = I.load_routelink(DATA / "RouteLink_CONUS.nc")
    topo = I.topology(rl["link"], rl["to"], rl["length_m"])
    att = conus_attributes(rl, topo)
    q = att["q_cms"].to_numpy()
    # confluence dominance by mean annual flow (filled), ties broken by upstream length
    size_key = q + 1e-9 * topo["up_len_km"]
    ind = domain_indicators(rl, topo, size_key)
    res["conus_indicators_flow_dominance"] = indicator_summary(rl, ind)
    hb = ind["hb"]
    h, hmeth, h_mc = mean_flow_depth(rl, hb, q, att["v_erom_raw"].to_numpy())
    km = rl["length_m"] / 1000.0
    ok = ~ind["lake"]

    # ---------------- spatial layers
    pts = gpd.GeoSeries(shapely.points(rl["lon"], rl["lat"]), crs="EPSG:4269")
    sp = spatial.load_all(DATA)
    pts_p = pts.to_crs(spatial.CRS)
    nwn_dist = spatial.distance_to_lines(pts_p, sp["nwn"])
    nwn = nwn_dist <= NWN_TOL_M
    ehy = spatial.points_in_polygons(pts_p, sp["ehydro"]) if sp["ehydro"] is not None else None
    phys = spatial.physio_attributes(pts_p, sp["physio"])

    # ---------------- context
    w = q * km
    net = topo["net"]
    outlet_link = rl["link"][topo["outlets"]]
    names_df = pd.read_csv(NAMES)
    name_by_outlet = dict(zip(names_df["outlet_feature_id"].astype(np.int64), names_df["river_name"]))
    net_names = {i: name_by_outlet[int(l)] for i, l in enumerate(outlet_link) if int(l) in name_by_outlet}
    flagged = ind["error"]
    ctx = {"km": km, "w": w, "ok": ok, "error": flagged, "effect": ind["effect"], "score": ind["score"].astype(float), "h": h,
           "h_mc": h_mc, "D": hb["D"], "nwn": nwn, "ehydro": ehy, "ponce": ind["ponce"], "ind": ind, "floor": ind["floor"],
           "net": net, "net_names": net_names, "outlet_link": outlet_link, "topo": topo, "q": q}

    # ---------------- configurations
    da = att["da_km2"].to_numpy()
    mainstem = (da >= MAINSTEM_DA_KM2) & ok        # configuration A
    tot = att["totdasqkm"].to_numpy()
    tot_only = (tot >= MAINSTEM_DA_KM2) & ~mainstem & ok
    res["drainage_area_choice"] = {
        "attribute": "DivDASqKM (divergence-routed)",
        "segments_mainstem_by_TotDASqKM_only": int(tot_only.sum()),
        "km_mainstem_by_TotDASqKM_only": r(km[tot_only].sum(), 1)}
    # B: mainstem + tributary backwater zones of confluences on the mainstem
    n = km.size
    down = topo["down"]
    t0 = np.full(n, np.inf)
    src = np.flatnonzero((down >= 0) & ~mainstem & ok)
    src = src[mainstem[down[src]]]
    t0[src] = 0.0
    tau_tr = I.propagate_up(t0, ind["u"], topo, ind["lake"] | mainstem)
    fringe = ((tau_tr + 0.5 * ind["u"]) < 1.0) & ok & ~mainstem
    in_cp = phys["province"] == spatial.COASTAL_PLAIN_PROVINCE
    in_map = phys["section"] == spatial.MISS_ALLUVIAL_SECTION
    surveyable = (h >= 2.0) | nwn
    configs = {
        "A_mainstem": (f"mainstem: drainage area >= {MAINSTEM_DA_KM2:,.0f} km2 (NHDPlusV2 DivDASqKM, divergence-routed)",
                       mainstem),
        "B_mainstem_fringes": ("A + tributary segments within a Samuels backwater length of a confluence with A "
                               "(each tributary's own L, integrated upstream)", mainstem | fringe),
        "C1_low_slope_2.5e-4": ("low-slope: all segments with S0 < 2.5e-4", ok & (rl["so"] < 2.5e-4)),
        "C2_low_slope_1e-4": ("low-slope, stricter: all segments with S0 < 1e-4", ok & (rl["so"] < 1e-4)),
        "D1_flat_miss_alluvial_plain": ("flat: all segments whose midpoint lies in the Mississippi Alluvial Plain "
                                        "section (USGS physiographic divisions)", ok & in_map),
        "D2_coastal_plain": ("coastal: all segments whose midpoint lies in the Coastal Plain province (Atlantic, Gulf, "
                             "embayment; USGS physiographic divisions)", ok & in_cp),
        "E_navigable_nwn": (f"navigable: segments whose midpoint is within {NWN_TOL_M:g} m of the National Waterway Network", ok & nwn),
        "F_candidate": ("B restricted to segments flagged by at least one known-error indicator and surveyable "
                        "(mean-flow depth >= 2 m or on the NWN)", (mainstem | fringe) & flagged & surveyable),
    }
    res["configurations"] = {k: config_metrics(k, rule, m, ctx) for k, (rule, m) in configs.items()}
    # sensitivity: mainstem threshold and NWN tolerance
    sens = {}
    for t in MAINSTEM_DA_SENS:
        sens[f"A_mainstem_da_{t:g}"] = config_metrics("A", f"DA >= {t:g}", (da >= t) & ok, ctx)
    for k in (6, 7, 8):
        sens[f"A_mainstem_order_ge_{k}"] = config_metrics("A", f"order >= {k}", (rl["order"] >= k) & ok, ctx)
    for tol in NWN_TOL_SENS:
        sens[f"E_navigable_nwn_tol_{tol:g}m"] = config_metrics("E", f"NWN within {tol:g} m", (nwn_dist <= tol) & ok, ctx)
    res["sensitivity"] = {k: {kk: v[kk] for kk in ("segments", "km", "pct_network_km", "pct_known_error_budget",
                                                    "pct_parameter_effect_budget", "pct_km_depth_ge_2m", "pct_km_on_nwn")}
                          for k, v in sens.items()}

    # ---------------- budget, flows, depth, layers
    W = w[ok & flagged].sum()
    res["known_error_budget"] = {
        "definition": "sum over error-flagged (LS or BW), non-lake CONUS segments of mean annual flow (m3/s) x length (km)",
        "total_flow_km": r(w[ok].sum(), 1), "flagged_flow_km": r(W, 1),
        "flagged_share_of_flow_km_pct": r(100 * W / w[ok].sum(), 3),
        "flagged_share_of_km_pct": r(100 * km[ok & flagged].sum() / km[ok].sum(), 3),
        "by_indicator_pct_of_budget": {k: r(100 * w[ok & ind[k]].sum() / W, 3) for k in ("LS", "BW")},
        "by_backwater_type_pct_of_budget": {k: r(100 * w[ok & ind[k]].sum() / W, 3) for k in ("BW_i", "BW_ii", "BW_iii")},
        "by_outlet_class_pct_of_budget": {c: r(100 * w[ok & flagged & (att["outlet_class"].to_numpy() == c)].sum() / W, 3)
                                          for c in ("coastal", "terminal", "other", "non_nhdplus")},
    }
    eff = ind["effect"]
    WE = w[ok & eff].sum()
    res["parameter_effect_budget"] = {
        "definition": "sum over effect-flagged (XF: X >= 0.25 floor binds, or KC: K clamped to dt = 300 s; both at "
                      "bankfull), non-lake CONUS segments of mean annual flow (m3/s) x length (km). Design limits "
                      "of the MC algorithm, reported separately from the known-error budget and never added to it",
        "flagged_flow_km": r(WE, 1),
        "flagged_share_of_flow_km_pct": r(100 * WE / w[ok].sum(), 3),
        "flagged_share_of_km_pct": r(100 * km[ok & eff].sum() / km[ok].sum(), 3),
        "by_indicator_pct_of_budget": {k: r(100 * w[ok & ind[k]].sum() / WE, 3) for k in ("XF", "KC")},
        "overlap_with_known_error_pct_of_budget": r(100 * w[ok & eff & flagged].sum() / WE, 3),
        "median_courant_bf_dt300": r(np.median(ind["courant_bf"][ok]), 4),
    }
    hm = hmeth[ok]
    res["flows"] = {
        "routelink_segments_matched_to_erom": int(np.isfinite(att["q_erom_raw"]).sum()),
        "share_matched": r(np.isfinite(att["q_erom_raw"]).mean(), 4),
        "q_filled_by_upstream_accumulation": int(att["q_filled"].sum()),
        "da_filled_by_upstream_accumulation": int(att["da_filled"].sum()),
        "depth_method_share_q_over_v": r((hm == 0).mean(), 4),
        "depth_method_share_manning_fallback": r((hm == 1).mean(), 4),
        "median_mean_flow_depth_m": r(np.median(h[ok]), 3),
        "pct_km_depth_ge": {f"{t:g}m": {"q_over_v_primary": r(100 * km[ok & (h >= t)].sum() / km[ok].sum(), 3),
                                        "manning_compound": r(100 * km[ok & (h_mc >= t)].sum() / km[ok].sum(), 3),
                                        "bankfull_D": r(100 * km[ok & (hb['D'] >= t)].sum() / km[ok].sum(), 3)}
                            for t in DEPTH_T},
    }
    res["layers"] = {"nwn": sp["meta"]["nwn"], "ehydro": sp["meta"]["ehydro"], "physio": sp["meta"]["physio"],
                     "pct_network_km_on_nwn": r(100 * km[ok & nwn].sum() / km[ok].sum(), 3),
                     "nwn_km_matched": r(km[ok & nwn].sum(), 1),
                     "pct_network_km_ehydro": r(100 * km[ok & ehy].sum() / km[ok].sum(), 3) if ehy is not None else None,
                     "pct_network_km_coastal_plain": r(100 * km[ok & in_cp].sum() / km[ok].sum(), 3),
                     "pct_network_km_miss_alluvial_plain": r(100 * km[ok & in_map].sum() / km[ok].sum(), 3)}
    # slope floor provenance: NHDPlus slope of floor segments
    vslope = pd.read_parquet(DATA / "nhdplusVAA.parquet", columns=["comid", "slope"]).drop_duplicates("comid")
    vs = vslope.set_index("comid")["slope"].reindex(rl["link"]).to_numpy()
    fl = ind["floor"] & ok
    res["slope_floor_provenance"] = {
        "floor_segments": int(fl.sum()),
        "nhdplus_slope_missing_-9998": int((fl & (vs <= -9997)).sum()),
        "nhdplus_slope_0_to_1e-5": int((fl & (vs >= 0) & (vs <= 1.0001e-5)).sum()),
        "nhdplus_slope_gt_1e-5": int((fl & (vs > 1.0001e-5)).sum()),
        "not_in_nhdplus_vaa": int((fl & np.isnan(vs)).sum()),
        "pct_of_budget_on_floor": r(100 * w[ok & flagged & ind["floor"]].sum() / W, 3),
    }

    # ---------------- Pareto
    par = pareto(ctx)
    par.to_parquet(RESULTS / "pareto.parquet", index=False)
    res["pareto"] = {f"pct_budget_at_{p}pct_km": r(np.interp(p, par["pct_km"], par["pct_budget"]), 2)
                     for p in (1, 2, 5, 10, 20)}
    for p_ in (1, 2, 5):
        res["pareto"][f"pct_flagged_km_at_{p_}pct_km"] = r(np.interp(p_, par["pct_km"], par["pct_flagged_km"]), 2)
    for p_ in (1, 2, 5):
        res["pareto"][f"pct_effect_budget_at_{p_}pct_km"] = r(np.interp(p_, par["pct_km"], par["pct_effect_budget"]), 2)
    res["pareto"]["shallow_km_lt_1m_at_5pct_km"] = r(np.interp(5, par["pct_km"], par["shallow_km_lt_1m"]), 1)

    # ---------------- per-segment table
    seg = pd.DataFrame({
        "link": rl["link"], "net": net, "order": rl["order"], "lat": rl["lat"].astype(np.float32),
        "lon": rl["lon"].astype(np.float32), "km": km, "so": rl["so"], "lake": ind["lake"],
        "D_bf": hb["D"], "Fr_bf": hb["Fr_bf"], "L_bw_km": ind["L_km"], "x_kernel_raw_bf": hb["x_kernel_raw_bf"],
        "LS": ind["LS"], "BW_i": ind["BW_i"], "BW_ii": ind["BW_ii"], "BW_iii": ind["BW_iii"], "BW": ind["BW"],
        "XF": ind["XF"], "KC": ind["KC"], "courant_bf_dt300": ind["courant_bf"].astype(np.float32),
        "error_score": ind["score"], "error": ind["error"], "effect": ind["effect"], **{f"ponce_T{T}d": c for T, c in ind["ponce"].items()},
        "q_cms": q, "q_filled": att["q_filled"].to_numpy(), "da_km2": da, "totdasqkm": att["totdasqkm"].to_numpy(), "h_mean": h, "h_method": hmeth,
        "h_manning_compound": h_mc, "nwn_dist_m": nwn_dist.astype(np.float32), "nwn": nwn,
        "ehydro": ehy if ehy is not None else np.zeros(n, bool),
        "province": phys["province"], "section": phys["section"], "outlet_class": att["outlet_class"].to_numpy(),
        **{f"cfg_{k}": m for k, (_, m) in configs.items()},
        "tang_inbank_pct_100km": I.tang_inbank_loss_pct(rl["so"]),
        "tang_compound_pct_20km": I.tang_compound_loss_pct(rl["so"]),
    })
    seg.to_parquet(RESULTS / "segments_conus.parquet", index=False)

    (RESULTS / "results.json").write_text(json.dumps(res, indent=2) + "\n")
    inputs = {f"RouteLink_{d}.nc": DATA / f"RouteLink_{d}.nc" for d in ("CONUS", "AK", "HI", "PRVI")}
    inputs.update({"nhdplusVAA.parquet": DATA / "nhdplusVAA.parquet", "erom_ma.parquet": DATA / "erom_ma.parquet"})
    inputs.update(spatial.input_files(DATA))
    provenance.write(HERE, RESULTS, inputs=inputs, sources=spatial.SOURCES)
    print(json.dumps(res["configurations"], indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
