"""Map figure for part 2: where the X correction changes flood peaks on the Potomac network.

AI-written (Claude, 2026-10-31). Reads build/potomac/links.npz, results/potomac_summary.json and
data/map/ (fetch_map_data.py); writes results/fig_potomac_map.png (200 dpi) and .pdf, and a
copy of the PNG in figures/. Style: black-and-white first with minimal color (blue water,
orange for the result), labels placed in the map, light hillshade clipped to the basin, degree
ticks on the frame only, simple scale bar and north arrow, small locator inset.

The network is drawn link to link (each link's RouteLink midpoint joined to its downstream
link's midpoint), which is accurate at this scale; RouteLink carries no flowline geometry.
Gauges are drawn at USGS's station coordinates.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import tifffile
from matplotlib.collections import LineCollection
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path as MPath
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
POT, MAPD, RESULTS, FIGS = HERE / "build" / "potomac", HERE / "data" / "map", HERE / "results", HERE / "figures"

WATER, WATER_LABEL, ACCENT, INK, INK2, GRAYEDGE = "#2f78bd", "#1f5f99", "#ef7d00", "#000000", "#333333", "#555555"
HALO = [pe.withStroke(linewidth=2.4, foreground="white")]
ORDER_LW = {2: 0.25, 3: 0.4, 4: 0.7, 5: 1.1, 6: 1.6, 7: 2.2}
plt.rcParams.update({"font.family": ["Arial Narrow", "Arial", "DejaVu Sans"], "pdf.fonttype": 42,
                     "axes.linewidth": 0.8})
TO_UTM = Transformer.from_crs(4326, 32618, always_xy=True)
TO_LL = Transformer.from_crs(32618, 4326, always_xy=True)


def short(name: str) -> str:
    n = name.replace("Potomac outlet (NWM feature 4539621)", "Potomac outlet")
    n = re.sub(r"Potomac River (at|near) ", "Potomac at ", n)
    n = n.replace("Washington, DC (Little Falls)", "Little Falls").replace("S F Shenandoah River", "S.F. Shenandoah")
    n = re.sub(r",? (MD|WV|VA|DC)$", "", n)
    n = re.sub(r" (near|at|below) .*$", "", n) if not n.startswith(("Potomac", "Shenandoah", "S.F.")) else n
    n = n.replace("Shenandoah River at Millville", "Shenandoah at Millville").replace(" near Luray", " near Luray")
    return n.replace(" River", " R.").replace(" Creek", " Cr.")


def signed(v: float, unit: str) -> str:
    s_ = f"{v:+.1f}"
    if s_ in ("+0.0", "-0.0"):
        s_ = "0.0"
    return s_.replace("-", "\u2212") + unit


def polygon_rings(geom: dict) -> list[np.ndarray]:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return [np.asarray(p[0], float) for p in polys]


def utm_path(rings: list[np.ndarray]) -> MPath:
    verts, codes = [], []
    for r in rings:
        x, y = TO_UTM.transform(r[:, 0], r[:, 1])
        v = np.column_stack([x, y])
        verts += list(v) + [v[0]]
        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(v) - 1) + [MPath.CLOSEPOLY]
    return MPath(np.asarray(verts), codes)


def hillshade(z: np.ndarray, res: float, az=315.0, alt=45.0, zf=2.0) -> np.ndarray:
    gy, gx = np.gradient(np.where(np.isfinite(z), z, np.nanmean(z)) * zf, res)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    a, b = np.radians(360 - az + 90), np.radians(alt)
    hs = np.sin(b) * np.cos(slope) + np.cos(b) * np.sin(slope) * np.cos(a - aspect)
    return np.clip(hs, 0, 1)


def degree_ticks(ax, xlim, ylim):
    """Ticks with degree labels on the neatline only (no grid)."""
    kw = dict(fontsize=8, color=INK2)
    xs = np.linspace(*xlim, 400)
    for side, y0, va, dy in (("bottom", ylim[0], "top", -2500), ("top", ylim[1], "bottom", 2500)):
        lon, _ = TO_LL.transform(xs, np.full_like(xs, y0))
        for L in np.arange(-79.5, -76.0, 0.5):
            if lon.min() < L < lon.max():
                x = np.interp(L, lon, xs)
                ax.plot([x, x], [y0, y0 + (dy * 0.6)], color=INK, lw=0.8, clip_on=False)
                if side == "bottom":
                    ax.text(x, y0 + dy * 1.4, f"{-L:.1f}°W", ha="center", va=va, **kw)
    ys = np.linspace(*ylim, 400)
    for side, x0, ha, dx in (("left", xlim[0], "right", -2500), ("right", xlim[1], "left", 2500)):
        _, lat = TO_LL.transform(np.full_like(ys, x0), ys)
        for L in np.arange(38.0, 40.6, 0.5):
            if lat.min() < L < lat.max():
                y = np.interp(L, lat, ys)
                ax.plot([x0, x0 + dx * 0.6], [y, y], color=INK, lw=0.8, clip_on=False)
                if side == "left":
                    ax.text(x0 + dx * 1.4, y, f"{L:.1f}°N", ha=ha, va="center", **kw)


def place_labels(ax, fig, items, obstacles):
    """Greedy in-map label placement: try offsets around each point, keep the first that
    overlaps neither earlier labels nor the obstacles (marker boxes)."""
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    taken = list(obstacles)
    offs = [(10, 0, "left", "center"), (-10, 0, "right", "center"), (0, 11, "center", "bottom"),
            (0, -11, "center", "top"), (10, 10, "left", "bottom"), (-10, 10, "right", "bottom"),
            (10, -10, "left", "top"), (-10, -10, "right", "top"), (22, 0, "left", "center"),
            (-22, 0, "right", "center"), (0, 24, "center", "bottom"), (0, -24, "center", "top"),
            (22, 18, "left", "bottom"), (-22, 18, "right", "bottom"), (22, -18, "left", "top"),
            (-22, -18, "right", "top")]
    for x, y, text, weight in items:
        best = None
        for dx, dy, ha, va in offs:
            t = ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points", ha=ha, va=va,
                            fontsize=8.5, color=INK, fontweight=weight, path_effects=HALO, zorder=9,
                            arrowprops=dict(arrowstyle="-", color=GRAYEDGE, lw=0.6, shrinkA=0, shrinkB=3))
            t.update_positions(rend)
            bb = matplotlib.text.Text.get_window_extent(t, rend).expanded(1.05, 1.15)   # text only, not the leader
            inside = ax.get_window_extent(rend).contains(bb.x0, bb.y0) and ax.get_window_extent(rend).contains(bb.x1, bb.y1)
            if inside and not any(bb.overlaps(o) for o in taken):
                best = (t, bb)
                break
            t.remove()
        if best is None:   # fall back to the first offset; flagged for hand-tuning
            t = ax.annotate(text, (x, y), xytext=offs[0][:2], textcoords="offset points", ha="left", va="center",
                            fontsize=8.5, color=INK, fontweight=weight, path_effects=HALO, zorder=9)
            best = (t, matplotlib.text.Text.get_window_extent(t, rend))
            print(f"label collision not resolved: {text!r}")
        taken.append(best[1])


def main() -> None:
    lk = np.load(POT / "links.npz")
    S = json.loads((RESULTS / "potomac_summary.json").read_text())
    src = json.loads((MAPD / "sources.json").read_text())
    basin = json.loads((MAPD / "basin.geojson").read_text())["features"][0]["geometry"]
    states = json.loads((MAPD / "states.geojson").read_text())["features"]

    # network, link to downstream link
    x, y = TO_UTM.transform(lk["lon"], lk["lat"])
    pos = {int(l): i for i, l in enumerate(lk["link"])}
    segs, lws = [], []
    for i, (t, o) in enumerate(zip(lk["to"], lk["order"])):
        j = pos.get(int(t))
        if j is None or o < 2:
            continue
        segs.append([(x[i], y[i]), (x[j], y[j])])
        lws.append(ORDER_LW.get(int(o), 2.2))

    d = src["dem_3dep_utm18n_150m.tif"]
    z = tifffile.imread(MAPD / "dem_3dep_utm18n_150m.tif").astype(float)
    z[z < -1000] = np.nan
    hs = hillshade(z, d["res_m"])
    x0, y0, x1, y1 = d["bbox"]
    bpath = utm_path(polygon_rings(basin))
    bx, by = bpath.vertices[:, 0], bpath.vertices[:, 1]
    pad = 8000
    xlim, ylim = (bx.min() - pad, bx.max() + pad), (by.min() - pad, by.max() + pad)

    fig = plt.figure(figsize=(12, 11.2), facecolor="white")
    ax = fig.add_axes([0.07, 0.10, 0.86, 0.82])
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    im = ax.imshow(hs, extent=(x0, x1, y0, y1), origin="upper", cmap="gray", vmin=0, vmax=1, alpha=0.22,
                   interpolation="bilinear", zorder=1)
    im.set_clip_path(PathPatch(bpath, transform=ax.transData))
    ax.add_patch(PathPatch(bpath, facecolor="none", edgecolor=GRAYEDGE, lw=1.0, zorder=2))
    ax.add_collection(LineCollection(segs, linewidths=lws, colors=WATER, capstyle="round", zorder=3))

    # gauges: color and size = peak change from the X correction (WRF-Hydro routine)
    recs = S["records"]
    gl = [r for r in recs if r["usgs"]]
    gx, gy = TO_UTM.transform([r["lon"] for r in gl], [r["lat"] for r in gl])
    chg = np.array([r["peak_change_pct"] for r in gl])
    cmap = plt.get_cmap("Oranges")
    sizes = 30 + 55 * np.abs(chg)
    sc = ax.scatter(gx, gy, s=sizes, c=np.abs(chg), cmap=cmap, vmin=0, vmax=4, edgecolors=INK, linewidths=0.7, zorder=6)
    out = next(r for r in recs if not r["usgs"])
    ox, oy = TO_UTM.transform(lk["lon"][pos[out["link"]]], lk["lat"][pos[out["link"]]])
    ax.scatter([ox], [oy], s=30 + 55 * abs(out["peak_change_pct"]), marker="s", c=[abs(out["peak_change_pct"])],
               cmap=cmap, vmin=0, vmax=4, edgecolors=INK, linewidths=0.7, zorder=6)

    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    obstacles = []
    for px, py, s in list(zip(gx, gy, sizes)) + [(ox, oy, 30 + 55 * abs(out["peak_change_pct"]))]:
        cx, cy = ax.transData.transform((px, py))
        r = (s ** 0.5) / 2 * fig.dpi / 72 + 1
        from matplotlib.transforms import Bbox
        obstacles.append(Bbox([[cx - r, cy - r], [cx + r, cy + r]]))
    items = []
    for r, px, py in zip(gl, gx, gy):
        items.append((px, py, f"{short(r['name'])}\n{signed(r['peak_change_pct'], '%')}, {signed(r['t_peak_shift_h'], ' h')}",
                      "bold" if r["usgs_area_km2"] and r["usgs_area_km2"] > 5000 else "normal"))
    items.append((ox, oy, f"Potomac outlet\n{signed(out['peak_change_pct'], '%')}, {signed(out['t_peak_shift_h'], ' h')}", "bold"))
    place_labels(ax, fig, items, obstacles)

    degree_ticks(ax, xlim, ylim)
    # scale bar (km) and north arrow, lower left
    sx, sy = xlim[0] + 12000, ylim[0] + 12000
    for k in range(4):
        ax.add_patch(Rectangle((sx + k * 12500, sy), 12500, 1800, facecolor=INK if k % 2 == 0 else "white",
                               edgecolor=INK, lw=0.6, zorder=8))
    for k, lab in ((0, "0"), (2, "25"), (4, "50 km")):
        ax.text(sx + k * 12500, sy + 3200, lab, ha="center", va="bottom", fontsize=8, color=INK, path_effects=HALO)
    ax.annotate("", xy=(sx + 3000, sy + 30000), xytext=(sx + 3000, sy + 14000),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.2), zorder=8)
    ax.text(sx + 3000, sy + 31500, "N", ha="center", va="bottom", fontsize=11, fontweight="bold")

    # legend, upper left (empty corner of the basin's frame)
    lg = ax.inset_axes([0.375, 0.035, 0.25, 0.215])
    lg.set_xlim(0, 1)
    lg.set_ylim(0, 1)
    lg.set_xticks([])
    lg.set_yticks([])
    lg.set_facecolor((1, 1, 1, 0.92))
    for s_ in lg.spines.values():
        s_.set_edgecolor("#777777")
    lg.text(0.05, 0.94, "Peak change from the X correction", fontsize=9.5, fontweight="bold", va="top")
    lg.text(0.05, 0.84, "WRF-Hydro's routine, patched vs current;\nT-Route agrees within 0.02 points", fontsize=8,
            va="top", color=INK2)
    for k, v in enumerate((0, 1, 2, 3, 4)):
        lg.scatter([0.12 + k * 0.17], [0.50], s=30 + 55 * v, c=[v], cmap=cmap, vmin=0, vmax=4, edgecolors=INK, lw=0.7)
        lg.text(0.12 + k * 0.17, 0.36, f"\u2212{v:d}%" if v else "0", ha="center", va="top", fontsize=8)
    lg.scatter([0.12], [0.15], s=40, marker="s", c=["#f9c08b"], edgecolors=INK, lw=0.7)
    lg.text(0.20, 0.15, "network outlet;  ● USGS gauge", fontsize=8, va="center")
    lg.text(0.05, 0.03, "labels: peak change, peak-time shift", fontsize=7.5, color=INK2, va="bottom")

    # locator inset, upper right
    loc = ax.inset_axes([0.012, 0.835, 0.19, 0.155])
    loc.set_xticks([])
    loc.set_yticks([])
    for s_ in loc.spines.values():
        s_.set_linewidth(1.2)
    for f in states:
        p = f["properties"]
        if p.get("adm0_a3") not in ("USA", "CAN"):
            continue
        for ring in polygon_rings(f["geometry"]):
            loc.fill(ring[:, 0], ring[:, 1], facecolor="#eeeeee", edgecolor="#9a9a9a", lw=0.5)
        if p.get("adm0_a3") == "USA" and p.get("postal") in ("PA", "MD", "VA", "WV", "NY", "NJ", "DE", "NC", "OH", "KY"):
            lx, ly = p.get("longitude"), p.get("latitude")
            if lx is not None and -83.5 < lx < -73.5 and 35.5 < ly < 42.8:
                loc.text(lx, ly, p["postal"], fontsize=7, ha="center", va="center", color=INK2)
    for ring in polygon_rings(basin):
        loc.fill(ring[:, 0], ring[:, 1], facecolor=WATER, alpha=0.75, edgecolor=INK, lw=0.6)
    loc.set_xlim(-84, -73)
    loc.set_ylim(35.6, 43.2)
    loc.set_aspect(1.3)
    loc.text(-83.6, 42.75, "Potomac basin", fontsize=7.5, color=INK, va="top", path_effects=HALO)

    fig.text(0.07, 0.955, "Potomac River network: the X correction lowers and delays flood peaks on larger rivers",
             fontsize=14, fontweight="bold", ha="left")
    fig.text(0.07, 0.935, "NWM v3.1.6 network (16,454 links; line width by stream order), synthetic 25 mm storm, "
             "dt = 300 s. Small streams barely change.", fontsize=10, color=INK2, ha="left")
    retrieved = src["dem_3dep_utm18n_150m.tif"]["retrieved"]
    fig.text(0.07, 0.035, "River network: NWM v3.1.6 RouteLink (NOAA OWP). Gauges: USGS. Basin outline: USGS NLDI "
             "(NHDPlusV2). Relief: U.S. Geological Survey, 3D Elevation Program (3DEP), retrieved "
             f"{retrieved}. States: Natural Earth.", fontsize=7.5, color=INK2, ha="left")
    fig.text(0.07, 0.018, "Projection: UTM zone 18N (EPSG:32618); scale approximate. Synthetic storm, not an observed "
             "event. github.com/jameshalgren/troute-lab, repro/wrfhydro_mc_x_factor", fontsize=7.5, color=INK2,
             ha="left")
    RESULTS.mkdir(exist_ok=True)
    FIGS.mkdir(exist_ok=True)
    fig.savefig(RESULTS / "fig_potomac_map.png", dpi=200)
    fig.savefig(RESULTS / "fig_potomac_map.pdf")
    fig.savefig(FIGS / "fig_potomac_map.png", dpi=200)
    print("map written: results/fig_potomac_map.png, .pdf; figures/fig_potomac_map.png")


if __name__ == "__main__":
    main()
