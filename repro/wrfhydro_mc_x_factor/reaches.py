"""Part 1, NWM conditions: the X change on single reaches built from NWM v3.1.7 links.

AI-written (Claude, 2026-11-02); not reviewed. Runs after part 2 (it reads part 2's outputs).

Four cases, each a uniform 80 km reach split into links of one length, routed with the
verbatim WRF-Hydro SUBMUSKINGCUNGE (current and patched) at the NWM time step (300 s):

  mid_1km    1 km links,   S0 = 1e-3   typical (by count) mid-size-river link
  mid_2p5km  2.5 km links, S0 = 1e-3   length-weighted median link length of the network
  main_2p5km 2.5 km links, S0 = 1e-5   main-stem link at RouteLink's slope floor
  mid_8km    8 km links,   S0 = 1e-3   about the 99th percentile of link length (worst case)
  cacapon    the real sequence of 56 link lengths (0.02-5.8 km) on the lower 82.5 km of the
             Cacapon River above gauge 01611500, S0 = 1e-3 (the reach's median So is 1.04e-3):
             a mid-size river with the network's mix of short and long links

Nothing is invented for the NWM cases. The channel parameters (n, ChSlp, BtmWdth,
TopWdth, TopWdthCC, nCC) are the medians of the RouteLink links in one group:
  - mid-size rivers: BtmWdth 12-30 m and So 5e-4 to 2e-3;
  - main stems: stream order >= 6 at the So floor (<= 1.5e-5).
Overbank flow goes onto the compound channel as in the NWM. The upstream inflow is
part 2's simulated storm hydrograph (current routine, short-time-step assumption on) at a
gauge whose flows match the group: Cacapon River near Great Cacapon (01611500) for the
mid-size cases, Potomac River at Shepherdstown (01618000) for the main stem.

Each case runs with the short-time-step assumption on (STS ON: qup = quc = last step's
upstream outflow; WRF-Hydro's DRIVE_CHANNEL, T-Route assume_short_ts True, the
operational NWM), which is the headline, and off (STS OFF, real qdc: this step's upstream
outflow; T-Route False), for context. The reference is a fine-grid (100 m)
zero-inertia (diffusive-wave) solution on the same compound channel, using the kernel's
own stage-discharge relation (composite Manning n) and storage widths.

For each case it also reports the network links it stands for: how many links match it
(length within 20 %, the group's slope and width), what share of their time step X sat
on its 0.25 floor in part 2, how much the patch changed their peaks there, and the GNIS
names of the rivers they lie on (NHDPlusV2.1 flowlines; looked up once, cached in
data/nhdplus_names.json).

Writes results/reaches_summary.json, results/reaches_hydrographs.csv,
results/fig_reaches.png.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import diags

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
POT = BUILD / "potomac"
RES = HERE / "results"
DATA = HERE / "data"
NAMES = DATA / "nhdplus_names.json"
NAMES_URL = ("https://services.arcgis.com/P3ePLMYs2RVChkJx/arcgis/rest/services/NHDPlusV21/"
             "FeatureServer/2/query")

DT = 300.0                 # s, the NWM channel time step
L_REACH = 80_000.0         # m
T_END_H = 16 * 24          # h of part 2's hydrograph used (storm starts at 24 h)
NSUB = 12                  # part 2: 12 routing steps per hour
NSPIN = 400
CASES = [
    # key, group, dx (m), S0, label used in the README
    ("mid_1km", "mid", 1000.0, 1e-3, "1 km links, S0 1e-3"),
    ("mid_2p5km", "mid", 2500.0, 1e-3, "2.5 km links, S0 1e-3"),
    ("main_2p5km", "main", 2500.0, 1e-5, "2.5 km links, S0 1e-5 (main stem)"),
    ("mid_8km", "mid", 8000.0, 1e-3, "8 km links, S0 1e-3 (worst case)"),
    ("cacapon", "mid", None, 1e-3, "Cacapon link lengths, S0 1e-3"),
]
CACAPON_GAUGE, CACAPON_KM = "01611500", 80.0
INFLOW_GAUGE = {"mid": "01611500", "main": "01618000"}
GEOM_KEYS = ("n", "ChSlp", "BtmWdth", "TopWdth", "TopWdthCC", "nCC")


# ---- NWM links: groups, matches, part-2 behaviour ------------------------------------------
def load_network():
    import netCDF4
    z = np.load(POT / "links.npz")
    net = json.loads((POT / "network.json").read_text())
    link = z["link"]
    n = link.size
    with netCDF4.Dataset(DATA / "RouteLink_CONUS.nc") as ds:
        la = ds["link"][:].filled()
        pos = {int(v): i for i, v in enumerate(la)}
        ii = np.array([pos[int(v)] for v in link])
        g = {k: ds[k][:][ii].filled().astype(float) for k in GEOM_KEYS}
    out = POT / "out"
    peaks = {}
    for v in ("orig", "patched"):
        with open(out / f"{v}_peaks.bin", "rb") as f:
            peaks[v] = np.fromfile(f, dtype=np.float32, count=n).astype(float)
    floor = {v: np.fromfile(out / f"{v}_floor.bin", dtype=np.int32).astype(float)
             for v in ("orig", "patched")}
    nhours = net["hours"]
    nrec = len(net["records"])
    hydro = np.fromfile(out / "orig_hydro.bin", dtype=np.float32).reshape(nhours + 1, nrec).T
    return dict(z=z, net=net, g=g, peaks=peaks, floor=floor, hydro=hydro,
                nsteps=nhours * net["nsub"])


def groups(N) -> dict:
    z, g = N["z"], N["g"]
    so = np.maximum(z["so"], 1e-5)
    bw = g["BtmWdth"]
    return {"mid": (bw >= 12) & (bw <= 30) & (so >= 5e-4) & (so <= 2e-3),
            "main": (z["order"] >= 6) & (so <= 1.5e-5)}


def gnis_names(comids: list[int]) -> dict[str, str]:
    """GNIS names of NHDPlusV2.1 flowlines (cached; a live lookup, labels only)."""
    known = json.loads(NAMES.read_text()) if NAMES.exists() else {"names": {}}
    want = [c for c in comids if str(c) not in known["names"]]
    try:
        for i in range(0, len(want), 100):
            chunk = want[i:i + 100]
            q = {"where": f"COMID IN ({','.join(map(str, chunk))})", "outFields": "COMID,GNIS_NAME",
                 "returnGeometry": "false", "f": "json"}
            req = urllib.request.Request(NAMES_URL + "?" + urllib.parse.urlencode(q),
                                         headers={"User-Agent": "byu-troute-paper"})
            with urllib.request.urlopen(req, timeout=60) as r:
                feats = json.loads(r.read())["features"]
            for f in feats:
                a = f["attributes"]
                known["names"][str(a["COMID"])] = (a.get("GNIS_NAME") or "").strip()
            for c in chunk:
                known["names"].setdefault(str(c), "")
        if want:
            known.update({"source": NAMES_URL.rsplit("/query", 1)[0],
                          "what": "Esri Living Atlas copy of EPA/USGS NHDPlusV2.1 flowlines; GNIS_NAME by COMID",
                          "retrieved": time.strftime("%Y-%m-%d")})
            DATA.mkdir(exist_ok=True)
            NAMES.write_text(json.dumps(known, indent=1, sort_keys=True) + "\n")
    except Exception as e:  # noqa: BLE001  (names are labels only)
        print(f"WARNING river names not fetched ({e}); labels fall back to the gauge basin")
    return known["names"]


def analogs(N, grp, dx_km: float) -> np.ndarray:
    L = N["z"]["length_km"]
    return np.where(grp & (np.abs(L - dx_km) <= 0.2 * dx_km))[0]


def gauge_basin_of(N) -> np.ndarray:
    """Label each link with the nearest gauge at or below it (or the outlet)."""
    z, net = N["z"], N["net"]
    link, to = z["link"], z["to"]
    idx = {int(v): i for i, v in enumerate(link)}
    gl = {idx[r["link"]]: r["usgs"] for r in net["records"] if r["usgs"]}
    lab = np.empty(link.size, dtype=object)
    for i0 in range(link.size):
        i, path = i0, []
        while lab[i] is None and i not in gl:
            path.append(i)
            t = int(to[i])
            if t not in idx:
                break
            i = idx[t]
        name = lab[i] if lab[i] is not None else gl.get(i, "outlet")
        for k in path:
            lab[k] = name
        if i in gl:
            lab[i] = gl[i]
    return lab


# ---- the compound channel of the WRF-Hydro kernel ------------------------------------------
class Channel:
    def __init__(self, S0, n, ChSlp, Bw, Tw, TwCC, nCC):
        self.S0, self.n, self.Bw, self.Tw, self.TwCC, self.nCC = S0, n, Bw, Tw, TwCC, nCC
        self.z = 1.0 / ChSlp
        self.bfd = (Tw - Bw) / (2.0 * self.z)          # the kernel's bankfull depth (Tw > Bw here)
        self.s = math.sqrt(1.0 + self.z ** 2)

    def parts(self, h):
        """area, conveyance (Q / sqrt(S)), storage width, X width (Twl or TwCC), kernel Ck."""
        h = np.asarray(h, dtype=float)
        z, Bw, bfd, s = self.z, self.Bw, self.bfd, self.s
        hb = np.minimum(h, bfd)
        A = (Bw + z * hb) * hb
        WP = Bw + 2.0 * hb * s
        over = h > bfd
        AC = np.where(over, self.TwCC * (h - bfd), 0.0)
        WPC = np.where(over, self.TwCC + 2.0 * (h - bfd), 0.0)
        R = (A + AC) / (WP + WPC)
        neff = (WP * self.n + WPC * self.nCC) / (WP + WPC)
        K = (A + AC) * R ** (2.0 / 3.0) / neff
        width = np.where(over, self.TwCC, Bw + 2.0 * z * h)
        rS = math.sqrt(self.S0)
        ck_in = (rS / self.n) * ((5. / 3.) * R ** (2. / 3.) - (2. / 3.) * R ** (5. / 3.) * (2.0 * s / (Bw + 2.0 * h * z)))
        ck_over = ((rS / self.n) * ((5. / 3.) * R ** (2. / 3.) - (2. / 3.) * R ** (5. / 3.) * (2.0 * s / (Bw + 2.0 * bfd * z))) * A
                   + (rS / self.nCC) * (5. / 3.) * np.maximum(h - bfd, 0.0) ** (2. / 3.) * AC) / (A + AC)
        ck = np.maximum(0.0, np.where(over, ck_over, ck_in))
        return A + AC, K, width, width, ck

    def q(self, h):
        return self.parts(h)[1] * math.sqrt(self.S0)

    def depth(self, Q):
        lo, hi = 1e-6, 60.0
        for _ in range(200):
            m = 0.5 * (lo + hi)
            lo, hi = (m, hi) if self.q(m) < Q else (lo, m)
        return 0.5 * (lo + hi)

    def xcell(self, Q, dx):
        """The cell number Q/(B S0 Ck dx) the kernel's X formula uses, at normal depth for Q."""
        _, _, _, B, ck = self.parts(self.depth(Q))
        return float(Q / (B * self.S0 * ck * dx))


def cacapon_path(N, rec_index) -> np.ndarray:
    """Links on the Cacapon's main path (largest upstream area) up from gauge 01611500, about 80 km."""
    z, net = N["z"], N["net"]
    link, to, A, L = z["link"], z["to"], z["model_area_km2"], z["length_km"]
    idx = {int(v): i for i, v in enumerate(link)}
    up: dict[int, list[int]] = {}
    for i, t in enumerate(to):
        up.setdefault(int(t), []).append(i)
    i = idx[net["records"][rec_index[CACAPON_GAUGE]]["link"]]
    p, tot = [i], L[i]
    while tot < CACAPON_KM and int(link[i]) in up:
        i = max(up[int(link[i])], key=lambda k: A[k])
        p.append(i)
        tot += L[i]
    return np.array(p[::-1])


def x_of(dcell: float, factor: float) -> float:
    return min(0.5, max(0.25, 0.5 * (1.0 - dcell / factor)))


def zero_inertia(ch: Channel, t_out, qin_fn, length: float, dxf: float = 100.0) -> np.ndarray:
    N = int(round(1.5 * length / dxf))
    i_out = int(round(length / dxf))
    S0 = ch.S0

    def rhs(t, h):
        h = np.maximum(h, 1e-4)
        K = ch.parts(0.5 * (h[:-1] + h[1:]))[1]
        Sf = S0 - (h[1:] - h[:-1]) / dxf
        qf = K * np.sign(Sf) * np.sqrt(np.abs(Sf))
        qin = np.concatenate(([qin_fn(t)], qf))
        qout = np.concatenate((qf, [ch.q(h[-1])]))              # normal-depth outlet
        return (qin - qout) / (dxf * ch.parts(h)[2])

    h0 = ch.depth(qin_fn(0.0))
    jac = diags([1.0, 1.0, 1.0], [-1, 0, 1], shape=(N, N))
    sol = solve_ivp(rhs, (0.0, t_out[-1]), np.full(N, h0), method="BDF", t_eval=t_out,
                    jac_sparsity=jac, rtol=1e-6, atol=1e-8, max_step=1800.0)
    if not sol.success:
        raise RuntimeError(sol.message)
    h = sol.y
    hm, hp = 0.5 * (h[i_out - 1] + h[i_out]), 0.5 * (h[i_out] + h[i_out + 1])
    Sm = S0 - (h[i_out] - h[i_out - 1]) / dxf
    Sp = S0 - (h[i_out + 1] - h[i_out]) / dxf
    Km, Kp = ch.parts(hm)[1], ch.parts(hp)[1]
    return 0.5 * (Km * np.sign(Sm) * np.sqrt(np.abs(Sm)) + Kp * np.sign(Sp) * np.sqrt(np.abs(Sp)))


def run_kernel(ch: Channel, dxs, qin, variant, mode, tag) -> np.ndarray:
    """Route through links of lengths dxs (m). Unequal lengths run one link at a time, each
    link's outflow series feeding the next; for one reach this is the same computation."""
    if len(set(dxs)) > 1:
        q = qin
        for j, dx in enumerate(dxs):
            q = run_kernel(ch, [dx], q, variant, mode, f"{tag}_{j:03d}")
        return q
    dx, nseg = dxs[0], len(dxs)
    work = BUILD / "reaches"
    work.mkdir(parents=True, exist_ok=True)
    inf = work / f"inflow_{tag}.txt"
    np.savetxt(inf, qin, fmt="%.8e")
    cfg = work / f"cfg_{tag}.txt"
    cfg.write_text(f"{nseg} {dx} {DT} {ch.S0} {ch.n} {1.0 / ch.z} {ch.Bw} {ch.Tw} {ch.TwCC} {ch.nCC} "
                   f"{NSPIN} 1\n{nseg}\n")
    out = work / f"out_{variant}_{mode}_{tag}.txt"
    r = subprocess.run([str(BUILD / "driver"), variant, str(cfg), str(inf), str(out), mode], check=True,
                       capture_output=True, text=True)
    WARNINGS[(variant, mode, tag.split("_")[0] if tag.startswith("cacapon") else tag)] = (
        WARNINGS.get((variant, mode, tag.split("_")[0] if tag.startswith("cacapon") else tag), 0)
        + r.stdout.count("Failure to converge"))
    d = np.loadtxt(out)
    return np.concatenate(([qin[0]], d[:, 2]))


WARNINGS: dict = {}   # (variant, mode, case) -> number of "Failure to converge" warnings from the routine


def peak(t, q):
    i = int(np.argmax(q))
    if 0 < i < q.size - 1:
        y0, y1, y2 = q[i - 1], q[i], q[i + 1]
        den = y0 - 2 * y1 + y2
        off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        return float(y1 - 0.25 * (y0 - y2) * off), float(t[i] + off * (t[1] - t[0]))
    return float(q[i]), float(t[i])


def main() -> int:
    if not (POT / "out" / "orig_peaks.bin").exists():
        print("skip    reaches.py: needs part 2's outputs (build/potomac/out)")
        return 0
    RES.mkdir(exist_ok=True)
    N = load_network()
    z, g, net = N["z"], N["g"], N["net"]
    G = groups(N)
    basin = gauge_basin_of(N)
    gname = {r["usgs"]: r["name"] for r in net["records"] if r["usgs"]}
    rec_index = {r["usgs"]: k for k, r in enumerate(net["records"])}
    L = z["length_km"]
    pk_chg = 100 * (N["peaks"]["patched"] - N["peaks"]["orig"]) / N["peaks"]["orig"]

    matched = {key: analogs(N, G[grp], dx / 1000) for key, grp, dx, _, _ in CASES if dx}
    matched["cacapon"] = cacapon_path(N, rec_index)
    names = gnis_names(sorted({int(z["link"][i]) for m in matched.values() for i in m}))

    t = np.arange(0.0, T_END_H * 3600.0 + DT, DT)
    summary = {"what": __doc__.split("\n\n")[0], "dt_s": DT, "reach_length_m": L_REACH,
               "network_links": int(L.size),
               "network_link_length_km": {"count_percentiles_10_25_50_75_90_99": [
                   float(np.percentile(L, p)) for p in (10, 25, 50, 75, 90, 99)],
                   "length_weighted_median": float(np.percentile(np.repeat(L, (L * 100).astype(int) + 1), 50))},
               "groups": {}, "cases": []}
    rows = {"t_h": t / 3600}
    for grp, sel in G.items():
        geo = {k: float(np.median(g[k][sel])) for k in GEOM_KEYS}
        summary["groups"][grp] = {"n_links": int(sel.sum()), "median_geometry": geo,
                                  "inflow_gauge": INFLOW_GAUGE[grp],
                                  "inflow_gauge_name": gname[INFLOW_GAUGE[grp]]}
    for key, grp, dx, S0, label in CASES:
        geo = summary["groups"][grp]["median_geometry"]
        ch = Channel(S0, geo["n"], geo["ChSlp"], geo["BtmWdth"], geo["TopWdth"], geo["TopWdthCC"], geo["nCC"])
        if dx:
            dxs = [dx] * int(round(L_REACH / dx))
        else:
            dxs = [float(v) for v in np.round(L[matched[key]] * 1000.0, 1)]
        length = float(sum(dxs))
        hy = N["hydro"][rec_index[INFLOW_GAUGE[grp]]][: T_END_H + 1].astype(float)
        th = np.arange(hy.size) * 3600.0
        qin = np.interp(t, th, hy)
        q0, qmax = float(qin[0]), float(qin.max())
        ref = zero_inertia(ch, t, lambda tt: float(np.interp(tt, th, hy)), length)
        rp, rtp = peak(t, ref)
        vin = float(np.trapezoid(qin - q0, t))
        case = {"key": key, "label": label, "group": grp, "dx_m": dx, "S0": S0, "nseg": len(dxs),
                "reach_length_m": length, "link_lengths_m": dxs if not dx else None,
                "channel": {**geo, "S0": S0, "bankfull_depth_m": ch.bfd},
                "inflow_base_m3s": q0, "inflow_peak_m3s": qmax,
                "inflow_peak_overbank": bool(ch.depth(qmax) > ch.bfd),
                "x_cell_number": {"at_base": ch.xcell(q0, dx or 1000.0), "at_peak": ch.xcell(qmax, dx or 1000.0),
                                  "dx_m": dx or 1000.0},
                "reference_peak_m3s": rp, "reference_t_peak_h": rtp / 3600}
        for at in ("at_base", "at_peak"):
            dcl = case["x_cell_number"][at]
            case["x_cell_number"][f"X_current_{at}"] = x_of(dcl, 2.0)
            case["x_cell_number"][f"X_patched_{at}"] = x_of(dcl, 1.0)
        rows[f"inflow_{key}"] = qin
        rows[f"reference_{key}"] = ref
        for mode, mk in (("lagged", "sts_on"), ("sequential", "sts_off")):
            res = {}
            for v in ("orig", "patched"):
                q = run_kernel(ch, dxs, qin, v, mode, key)
                p, tp = peak(t, q)
                res[v] = {"peak_m3s": p, "t_peak_h": tp / 3600,
                          "peak_error_pct_vs_reference": 100 * (p - rp) / rp,
                          "t_peak_error_h_vs_reference": (tp - rtp) / 3600,
                          "volume_ratio": float(np.trapezoid(q - q0, t)) / vin,
                          "min_flow_m3s": float(q.min()),
                          "rmse_vs_reference_over_peak_excess": float(np.sqrt(np.mean((q - ref) ** 2)) / (rp - q0))}
                rows[f"{v}_{mk}_{key}"] = q
            for v in ("orig", "patched"):
                res[v]["nonconvergence_warnings"] = WARNINGS.get((v, mode, key), 0)
            res["peak_change_pct"] = 100 * (res["patched"]["peak_m3s"] - res["orig"]["peak_m3s"]) / res["orig"]["peak_m3s"]
            res["t_peak_shift_h"] = res["patched"]["t_peak_h"] - res["orig"]["t_peak_h"]
            case[mk] = res
        m = matched[key]
        nm = Counter((names.get(str(int(z["link"][i])), "") or "(unnamed)") for i in m)
        bs = Counter(basin[i] for i in m)
        w = L[m]
        case["network_analogs"] = {
            "criteria": ((f"{'BtmWdth 12-30 m, So 5e-4 to 2e-3' if grp == 'mid' else 'order >= 6, So <= 1.5e-5'}; "
                          f"length {dx / 1000:g} km +/- 20 %") if dx else
                         f"the links themselves: lower {length / 1000:.1f} km of the Cacapon above {CACAPON_GAUGE}"),
            "n_links": int(m.size), "share_of_network_links_pct": 100 * m.size / L.size,
            "rivers": nm.most_common(),
            "gauge_basins": [(k, gname.get(k, "outlet"), v) for k, v in bs.most_common()],
            "part2_x_floor_share_current": float(np.average(N["floor"]["orig"][m], weights=w) / N["nsteps"]) if m.size else None,
            "part2_x_floor_share_patched": float(np.average(N["floor"]["patched"][m], weights=w) / N["nsteps"]) if m.size else None,
            "part2_peak_change_pct_median": float(np.median(pk_chg[m])) if m.size else None,
            "part2_peak_m3s_median": float(np.median(N["peaks"]["orig"][m])) if m.size else None,
        }
        summary["cases"].append(case)
    (RES / "reaches_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    keys = list(rows)
    np.savetxt(RES / "reaches_hydrographs.csv", np.column_stack([rows[k] for k in keys]), delimiter=",",
               header=",".join(keys), comments="", fmt="%.5f")
    print_table(summary)
    figure(summary, rows)
    return 0


def print_table(S) -> None:
    print("NWM CONDITIONS (STS ON, dt = 300 s): patched vs current, then error vs zero-inertia reference")
    for c in S["cases"]:
        on, off, a, x = c["sts_on"], c["sts_off"], c["network_analogs"], c["x_cell_number"]
        print(f"{c['label']:36} | peak {on['peak_change_pct']:+6.2f}% shift {on['t_peak_shift_h']:+5.2f} h | "
              f"peak err {on['orig']['peak_error_pct_vs_reference']:+6.1f}% -> {on['patched']['peak_error_pct_vs_reference']:+6.1f}% "
              f"t err {on['orig']['t_peak_error_h_vs_reference']:+5.1f} -> {on['patched']['t_peak_error_h_vs_reference']:+5.1f} h | "
              f"vol {on['orig']['volume_ratio']:.3f}/{on['patched']['volume_ratio']:.3f}")
        print(f"{'':36} | STS OFF: peak {off['peak_change_pct']:+6.2f}% shift {off['t_peak_shift_h']:+5.2f} h | "
              f"err {off['orig']['peak_error_pct_vs_reference']:+6.1f}% -> {off['patched']['peak_error_pct_vs_reference']:+6.1f}% "
              f"t err {off['orig']['t_peak_error_h_vs_reference']:+5.1f} -> {off['patched']['t_peak_error_h_vs_reference']:+5.1f} h | "
              f"vol {off['orig']['volume_ratio']:.3f}/{off['patched']['volume_ratio']:.3f}")
        print(f"{'':36} | inflow {c['inflow_base_m3s']:.1f} -> {c['inflow_peak_m3s']:.0f} m3/s (overbank {c['inflow_peak_overbank']}); "
              f"cell number {x['at_base']:.2f} (X {x['X_current_at_base']:.3f}/{x['X_patched_at_base']:.3f}) -> "
              f"{x['at_peak']:.2f} (X {x['X_current_at_peak']:.3f}/{x['X_patched_at_peak']:.3f})")
        if a["n_links"]:
            riv = ", ".join(f"{k} {v}" for k, v in a["rivers"][:5])
            print(f"{'':36} | network: {a['n_links']} links ({a['share_of_network_links_pct']:.2f} %); "
                  f"X floor {100 * a['part2_x_floor_share_current']:.0f}% -> {100 * a['part2_x_floor_share_patched']:.0f}%; "
                  f"part-2 peak change median {a['part2_peak_change_pct_median']:+.2f}%; {riv}")


def figure(S, rows) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "pdf.fonttype": 42})
    fig, axes = plt.subplots(3, 2, figsize=(10, 9.6), constrained_layout=True)
    th = rows["t_h"]
    for ax, c in zip(axes.flat, S["cases"]):
        k = c["key"]
        ax.plot(th, rows[f"inflow_{k}"], color="0.65", lw=0.9, ls=":", label="inflow (part 2, current routine)")
        if c["group"] == "mid":
            ax.plot(th, rows[f"reference_{k}"], color="black", lw=2.0, label="zero-inertia reference")
        else:   # a uniform 80 km reach at the 1e-5 So floor is not a real river: no reference shown
            ax.text(0.98, 0.95, "reference not shown: a uniform 80 km reach\nat RouteLink's 1e-5 slope floor is not a real river",
                    transform=ax.transAxes, ha="right", va="top", fontsize=7, color="0.35")
        ax.plot(th, rows[f"orig_sts_on_{k}"], color="#eb6834", lw=1.4, label="current routine, STS ON")
        ax.plot(th, rows[f"patched_sts_on_{k}"], color="#2a78d6", lw=1.4, ls="--", label="patched routine, STS ON")
        on = c["sts_on"]
        pc, sh = (0.0 if abs(v) < 0.005 else v for v in (on["peak_change_pct"], on["t_peak_shift_h"]))
        ax.set_title(f"{c['label']}\npatch vs current, STS ON: peak {pc:+.2f} %, {sh:+.2f} h", fontsize=9)
        i = int(np.argmax(rows[f"orig_sts_on_{k}"]))
        lo, hi = max(0.0, th[i] - 60), th[i] + 120
        ax.set_xlim(lo, hi)
        ax.set_xlabel("time (h)")
        ax.set_ylabel(f"flow at {c['reach_length_m'] / 1000:.1f} km (m³/s)")
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    axes.flat[0].legend(frameon=False, fontsize=7, loc="upper right")
    for ax in axes.flat[len(S["cases"]):]:
        ax.axis("off")
    fig.savefig(RES / "fig_reaches.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
