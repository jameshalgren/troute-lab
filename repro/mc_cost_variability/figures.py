"""Figures for the MC cost-variability experiment (results/figs/*.png).

    uv run --locked python figures.py

Reads tables/*.csv, tables/summary.json and (if present) results/timing.json and
results/timing/<scenario>.npz. Palette: the dataviz reference palette (light surface);
storm size is ordinal, so the storms use one blue ramp (light -> dark = 25 -> 250 mm),
calm is neutral gray; the space-time map is diverging (blue = cheaper than calm, red =
costlier, gray = equal).
"""
from __future__ import annotations

import json
import sys

import common as C
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
COL = {"calm": "#8a8984", "s25": "#86b6ef", "s100": "#2a78d6", "s250": "#104281"}
LAB = {"calm": "calm (baseflow only)", "s25": "25 mm storm", "s100": "100 mm storm", "s250": "250 mm storm"}
DIVERGING = LinearSegmentedColormap.from_list("bgr", ["#1c5cab", "#86b6ef", "#f0efec", "#f0a3a2", "#b8302f"])

plt.rcParams.update({"figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
                     "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
                     "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 9,
                     "axes.titlesize": 10, "axes.titleweight": "bold", "lines.linewidth": 2})


def fig_hourly(out):
    h = pd.read_csv(C.TABLES / "hourly_network_cost.csv")
    n = json.loads((C.CASE_DIR / "case.json").read_text())["n_segments"]
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    days = h["hour"] / 24
    for k in ["calm", "s25", "s100", "s250"]:
        y = h[k] / (n * C.QTS)
        ax.plot(days, y, color=COL[k], label=LAB[k])
    ax.set_xlim(0, 16)
    ax.set_xlabel("time since start of run (days); storm runoff starts at day 1")
    ax.set_ylabel("secant iterations per call\n(network mean, per hour)")
    ax.set_title("Kernel work per call rises about 40% during the storm, then returns to calm")
    ax.legend(frameon=False, loc="upper right")
    fig.tight_layout()
    fig.savefig(out / "fig_hourly_network_cost.png", dpi=160)
    plt.close(fig)


def fig_distribution(out):
    pc = pd.read_csv(C.TABLES / "iterations_per_call.csv")
    rows = [("calm", "all", "calm run, all calls"), ("s25", "flood_all", "25 mm, flood calls"),
            ("s100", "flood_all", "100 mm, flood calls"), ("s250", "flood_all", "250 mm, flood calls")]
    cats = ["share_1", "share_2", "share_3", "share_4", "share_5", "share_6", "share_7plus"]
    xl = ["1", "2", "3", "4", "5", "6", "7+"]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    w = 0.2
    for i, (sc, cl, lab) in enumerate(rows):
        r = pc[(pc.scenario == sc) & (pc.calls_in == cl)].iloc[0]
        y = [max(float(r[c]), 1e-7) for c in cats]
        ax.bar(np.arange(len(cats)) + (i - 1.5) * w, y, width=w - 0.03, color=COL[sc], label=lab)
    ax.set_yscale("log")
    ax.set_xticks(np.arange(len(cats)), xl)
    ax.set_xlabel("secant iterations in one kernel call")
    ax.set_ylabel("share of calls (log scale)")
    ax.set_title("Flood calls take 3 iterations where calm calls take 2; long searches stay rare")
    ax.legend(frameon=False, ncols=2, loc="upper right")
    fig.tight_layout()
    fig.savefig(out / "fig_iterations_per_call.png", dpi=160)
    plt.close(fig)


def fig_space_time(out, name="s25"):
    st = pd.read_csv(C.TABLES / "space_time_3h.csv")
    st = st[st.scenario == name]
    cols = [c for c in st.columns if c.startswith("over_calm ")]
    M = st[cols].to_numpy().T
    days = st["start_h"].to_numpy() / 24
    keep = days < 16
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    im = ax.imshow(M[:, keep], aspect="auto", origin="lower", cmap=DIVERGING,
                   norm=TwoSlopeNorm(vcenter=1.0, vmin=min(0.8, M.min()), vmax=max(1.6, M.max())),
                   extent=[0, days[keep].max() + 0.125, -0.5, len(cols) - 0.5], interpolation="nearest")
    ax.set_yticks(range(len(cols)), [c.replace("over_calm ", "") for c in cols])
    ax.grid(False)
    ax.set_xlabel("time since start of run (days)")
    ax.set_ylabel("distance to outlet")
    ax.set_title(f"Where the extra work is: cost over calm, 3-h windows ({LAB[name]})")
    cb = fig.colorbar(im, ax=ax, pad=0.01)
    cb.set_label("iterations / calm iterations")
    fig.tight_layout()
    fig.savefig(out / f"fig_space_time_{name}.png", dpi=160)
    plt.close(fig)


def fig_windows(out):
    w = pd.read_csv(C.TABLES / "windows.csv")
    order = ["call", "1h", "3h", "24h", "run"]
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 3.2))
    for k in ["calm", "s25", "s100", "s250"]:
        d = w[w.scenario == k].set_index("window").reindex(order)
        x = np.arange(len(order))
        # calm has no peak window (its window 0 holds the restart spin-up): median window
        which = "median" if k == "calm" else "peak"
        cv = d[f"cv_across_segments_{which}_window"].to_numpy(dtype=float)
        cv[0] = d.loc["call", "cv_pooled"]
        axs[0].plot(x, cv, marker="o", ms=4, color=COL[k], label=LAB[k])
        mm = d[f"worst_over_mean_{which}_window"].to_numpy(dtype=float)
        mm[0] = d.loc["call", "worst_over_mean_pooled"]
        axs[1].plot(x, mm, marker="o", ms=4, color=COL[k], label=LAB[k])
    for ax in axs:
        ax.set_xticks(np.arange(len(order)), ["1 call", "1 h", "3 h", "24 h", "40 d"])
        ax.set_xlabel("unit = one segment over a window of")
    axs[0].set_ylabel("CV of unit cost across segments")
    axs[1].set_ylabel("worst unit / mean unit")
    axs[1].set_yscale("log")
    axs[0].set_title("Spread across segments")
    axs[1].set_title("Worst / mean")
    axs[1].legend(frameon=False, fontsize=8, loc="upper right")
    fig.suptitle("Unit cost in the storm's peak window (calm: median window; single calls: whole run)",
                 fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out / "fig_cost_vs_window.png", dpi=160)
    plt.close(fig)


def fig_timing(out):
    p = C.RESULTS / "timing.json"
    if not p.exists():
        return
    pc = pd.read_csv(C.TABLES / "timing_per_call.csv")
    t = json.loads(p.read_text())
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 3.3))
    for k in ["calm", "s25", "s250"]:
        d = pc[pc.scenario == k]
        if d.empty:
            continue
        axs[0].plot(d["mean_iterations"], d["ns_per_call"], marker="o", ms=4, lw=1.2, color=COL[k], label=LAB[k])
    axs[0].set_xscale("log")
    axs[0].set_yscale("log")
    axs[0].set_xlabel("secant iterations in the call (class mean)")
    axs[0].set_ylabel("port time per call (ns)")
    axs[0].set_title("Single calls by iteration class")
    axs[0].legend(frameon=False, fontsize=8)
    z = np.load(C.RESULTS / "timing" / "s25.npz")
    W = int(z["window_steps"])
    x = z["iters"][:, 1:].ravel() / W
    y = z["ns"][:, 1:].ravel() / W
    axs[1].hexbin(x, y, gridsize=60, bins="log", cmap=LinearSegmentedColormap.from_list(
        "b", ["#cde2fb", "#2a78d6", "#0d366b"]), mincnt=1)
    u = t["units"]["s25"]
    xs = np.linspace(x.min(), x.max(), 10)
    axs[1].plot(xs, u["ns_per_call_fixed_a"] + u["ns_per_iteration_b"] * xs, color="#eb6834", lw=1.5)
    axs[1].set_xlabel("iterations per call, unit mean (24-h unit)")
    axs[1].set_ylabel("port time per call, unit mean (ns)")
    axs[1].set_title(f"24-h units, 25 mm storm (R² {u['r2_time_vs_model']:.2f})")
    axs[1].grid(False)
    fig.tight_layout()
    fig.savefig(out / "fig_timing.png", dpi=160)
    plt.close(fig)


def main() -> int:
    out = C.RESULTS / "figs"
    out.mkdir(parents=True, exist_ok=True)
    fig_hourly(out)
    fig_distribution(out)
    fig_space_time(out, "s25")
    fig_space_time(out, "s250")
    fig_windows(out)
    fig_timing(out)
    print(f"ok      {', '.join(sorted(p.name for p in out.glob('*.png')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
