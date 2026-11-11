"""Per-segment hydraulics and known-MC-error indicators for one RouteLink domain.

Everything here depends only on RouteLink columns (plus optional per-segment mean annual
flow), so it runs for CONUS, AK, HI and PRVI alike. Formulas and their sources are listed
in README.md ("Indicators"). Conventions:

* Side slope. RouteLink `ChSlp` is the bank slope as rise over run. The MC kernel sets
  z = 1/ChSlp (horizontal per vertical) and bankfull depth
  bfd = (TopWdth - BtmWdth) / (2 z) = (TopWdth - BtmWdth) * ChSlp / 2
  (CIROH-UA/t-route d29f663, MCsingleSegStime_f2py_NOLOOP.f90 L48-61; WRF-Hydro
  module_channel_routing.F90 identical). D below is that bfd.
* Bankfull hydraulics on the in-channel trapezoid (bottom width BtmWdth, z, depth D):
  area A, wetted perimeter P, R = A/P, Manning Q, mean velocity V = Q/A,
  hydraulic depth Dh = A/TopWdth, Froude Fr = V/sqrt(g Dh).
* Kinematic celerity ck: the kernel's own in-channel expression (secant2_h) at h = D.
* Muskingum X: the kernel's second-estimate formula
  X = 0.5 (1 - Q / (2 T S0 ck dx)), clamped to [0.25, 0.5] (L281-L291), with T the
  top width at depth h (= TopWdth at bankfull). Cunge's (1969) matching, as written by
  Tang et al. (1999, Eq. 6), is eps = 0.5 (1 - Q / (B S0 c dx)) without the factor 2.
"""
from __future__ import annotations

import numpy as np
import xarray as xr

G = 9.81
SLOPE_FLOOR = 1e-5          # RouteLink minimum So (observed min 9.99999975e-06)
FLOOR_TOL = 1.0001e-5
LN10 = np.log(10.0)


def load_routelink(path) -> dict:
    ds = xr.open_dataset(path, decode_times=False)
    out = {
        "link": ds["link"].values.astype(np.int64),
        "to": ds["to"].values.astype(np.int64),
        "length_m": ds["Length"].values.astype(np.float64),
        "so": ds["So"].values.astype(np.float64),
        "n": ds["n"].values.astype(np.float64),
        "ncc": ds["nCC"].values.astype(np.float64),
        "bw": ds["BtmWdth"].values.astype(np.float64),
        "tw": ds["TopWdth"].values.astype(np.float64),
        "twcc": ds["TopWdthCC"].values.astype(np.float64),
        "cs": ds["ChSlp"].values.astype(np.float64),
        "order": ds["order"].values.astype(np.int64),
        "lat": ds["lat"].values.astype(np.float64),
        "lon": ds["lon"].values.astype(np.float64),
        "wb": ds["NHDWaterbodyComID"].values.astype(np.int64),
    }
    ds.close()
    return out


# ------------------------------------------------------------------ topology
def topology(link: np.ndarray, to: np.ndarray, length_m: np.ndarray) -> dict:
    """Downstream index, upstream CSR, breadth-first levels from the outlets (parents
    before children), network id, distance to outlet, upstream channel length."""
    n = link.size
    srt = np.argsort(link)
    pos = np.clip(np.searchsorted(link[srt], to), 0, n - 1)
    found = (link[srt][pos] == to) & (to != 0)
    down = np.where(found, srt[pos], -1)
    indeg = np.bincount(down[down >= 0], minlength=n)
    up_order = np.argsort(down, kind="stable")
    up_order = up_order[down[up_order] >= 0]
    up_ptr = np.concatenate([[0], np.cumsum(indeg)])
    net = np.full(n, -1, np.int64)
    dist_out = np.zeros(n)                       # km from segment's downstream end to outlet end
    front = np.flatnonzero(down < 0)
    net[front] = np.arange(front.size)
    levels = [front]
    while True:
        counts = indeg[front]
        if counts.sum() == 0:
            break
        rep = np.repeat(np.arange(front.size), counts)
        offs = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
        ups = up_order[np.repeat(up_ptr[front], counts) + offs]
        par = front[rep]
        net[ups] = net[par]
        dist_out[ups] = dist_out[par] + length_m[par] / 1000.0
        front = ups
        levels.append(front)
    if (net < 0).any():
        raise SystemExit(f"{int((net < 0).sum())} segments not reachable from an outlet (cycles?)")
    # upstream channel length (km, including the segment): children before parents
    up_len = length_m / 1000.0
    up_len = up_len.copy()
    for lev in reversed(levels[1:]):
        np.add.at(up_len, down[lev], up_len[lev])
    return {"down": down, "indeg": indeg, "up_order": up_order, "up_ptr": up_ptr,
            "levels": levels, "net": net, "outlets": levels[0], "dist_out_km": dist_out,
            "up_len_km": up_len}


def accumulate_missing(value: np.ndarray, topo: dict) -> np.ndarray:
    """Fill NaNs by summing the (filled) values of upstream segments; headwaters with no
    value get 0. Used for drainage area and mean flow on non-NHDPlus segments."""
    v = value.copy()
    miss = np.isnan(v)
    acc = np.zeros_like(v)
    down = topo["down"]
    for lev in reversed(topo["levels"]):
        vl = np.where(np.isnan(v[lev]), acc[lev], v[lev])
        v[lev] = vl
        d = down[lev]
        ok = d >= 0
        np.add.at(acc, d[ok], vl[ok])
    v[miss & np.isnan(v)] = 0.0
    return v


def propagate_up(tau0: np.ndarray, u: np.ndarray, topo: dict, block: np.ndarray) -> np.ndarray:
    """Backwater decay coordinate tau (in units of the local backwater length) at each
    segment's DOWNSTREAM end: tau[s] = min(tau0[s], tau[down] + u[down]), with the path
    cut at blocked segments (lakes). tau0 = 0 at control points, inf elsewhere."""
    tau = tau0.copy()
    down = topo["down"]
    for lev in topo["levels"][1:]:
        d = down[lev]
        cand = np.where(block[d], np.inf, tau[d] + u[d])
        tau[lev] = np.minimum(tau[lev], cand)
    return tau


# ------------------------------------------------------------------ hydraulics
def bankfull(rl: dict) -> dict:
    bw, tw, cs, so, n = rl["bw"], rl["tw"], rl["cs"], rl["so"], rl["n"]
    z = 1.0 / cs
    D = np.where(bw > tw, bw / 1e-5, np.where(bw == tw, bw / (2 * z), (tw - bw) / (2 * z)))
    A = (bw + z * D) * D
    P = bw + 2 * D * np.sqrt(1 + z * z)
    R = A / P
    Q = A * R ** (2 / 3) * np.sqrt(so) / n
    V = Q / A
    Dh = A / tw
    Fr = V / np.sqrt(G * Dh)
    ck = np.maximum(0.0, (np.sqrt(so) / n) * ((5 / 3) * R ** (2 / 3)
                                               - (2 / 3) * R ** (5 / 3) * (2 * np.sqrt(1 + z * z) / (bw + 2 * D * z))))
    dx = rl["length_m"]
    ratio = Q / (tw * so * ck * dx)                    # Q / (B S0 c dx), Cunge's term
    x_kernel_raw = 0.5 * (1 - ratio / 2)               # kernel: Q / (2 T S0 ck dx)
    eps_cunge = 0.5 * (1 - ratio)
    return {"z": z, "D": D, "A_bf": A, "Q_bf": Q, "V_bf": V, "Dh_bf": Dh, "Fr_bf": Fr, "ck_bf": ck,
            "ratio_bf": ratio, "x_kernel_raw_bf": x_kernel_raw, "eps_cunge_bf": eps_cunge}


def backwater_length_km(hb: dict, so: np.ndarray) -> np.ndarray:
    """Samuels (1989): L = 0.7 (1 - Fr^2) D / S0 with bankfull depth D; 0 if Fr >= 1."""
    fr2 = hb["Fr_bf"] ** 2
    return np.where(fr2 < 1, 0.7 * (1 - fr2) * hb["D"] / so, 0.0) / 1000.0


def tang_inbank_loss_pct(so: np.ndarray) -> np.ndarray:
    """Tang, Knight & Samuels (1999, JHE) Eq. 25, VPMC4-1, 100-km channel, dt 1 h, dx 5 km;
    fitted on S in [6e-5, 3e-3]."""
    return 1.0 / (0.113 + 2102084.6 * so ** 2)


def tang_compound_loss_pct(so: np.ndarray) -> np.ndarray:
    """Tang, Knight & Samuels (1999, JHR) Eq. 29, VPMC4-1, 20-km compound channel; stated
    range S in [1e-5, 3e-3] but tested only down to 1e-4 (Table 5)."""
    return -0.3813 + 0.006251 * so ** -0.8


def ponce_classes(hb: dict, so: np.ndarray, periods_days=(1, 3, 10)) -> dict:
    """Ponce, Li & Simons (1978) 95%-accuracy criteria after one wave period, as restated by
    Fread (NWS HRL) Eqs. 54 and 57: kinematic if T S0 u0/d0 > 171; diffusion if
    T S0 sqrt(g/d0) > 30; otherwise dynamic. u0, d0 = bankfull mean velocity and hydraulic
    depth. Returns class codes 0 kinematic, 1 diffusion, 2 dynamic for each period."""
    u0, d0 = hb["V_bf"], hb["Dh_bf"]
    out = {}
    for T in periods_days:
        Ts = T * 86400.0
        tk = Ts * so * u0 / d0
        td = Ts * so * np.sqrt(G / d0)
        out[T] = np.where(tk > 171, 0, np.where(td > 30, 1, 2)).astype(np.int8)
    return out


def trapezoid_depth_from_area(A: np.ndarray, bw: np.ndarray, z: np.ndarray) -> np.ndarray:
    """Depth h on the in-channel trapezoid, extended upward with the same side slopes,
    such that (bw + z h) h = A."""
    return (-bw + np.sqrt(bw * bw + 4 * z * A)) / (2 * z)


def manning_depth(Q: np.ndarray, rl: dict, hb: dict, compound: bool = True, iters: int = 60) -> np.ndarray:
    """Normal depth for discharge Q on the kernel's geometry (trapezoid; above bankfull a
    rectangular floodplain of width TopWdthCC with roughness nCC, per hydraulic_geometry and
    the kernel's composite-n conveyance) by bisection."""
    bw, z, D, so, n = rl["bw"], hb["z"], hb["D"], rl["so"], rl["n"]
    twcc, ncc = rl["twcc"], rl["ncc"]

    def q_of(h):
        hl = np.minimum(h, D) if compound else h
        hg = np.maximum(h - D, 0) if compound else np.zeros_like(h)
        A = (bw + hl * z) * hl
        WP = bw + 2 * hl * np.sqrt(1 + z * z)
        AC = twcc * hg
        WPC = np.where(hg > 0, twcc + 2 * hg, 0.0)
        R = (A + AC) / (WP + WPC)
        neff = (WP * n + WPC * ncc) / (WP + WPC)
        return (A + AC) * R ** (2 / 3) * np.sqrt(so) / neff

    lo = np.zeros_like(Q)
    hi = np.full_like(Q, 1.0)
    for _ in range(40):                      # grow the bracket
        small = q_of(hi) < Q
        if not small.any():
            break
        hi = np.where(small, hi * 2, hi)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        f = q_of(mid) < Q
        lo = np.where(f, mid, lo)
        hi = np.where(f, hi, mid)
    return np.where(Q > 0, 0.5 * (lo + hi), 0.0)
