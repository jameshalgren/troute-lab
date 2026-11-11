"""Figures for the extension (reads results/extended_summary.json, extended_outlet.csv and
results/extended_closure/*.npz written by run_extended.py).

Palette (validated with the dataviz skill's validate_palette.js, light mode):
  * dt: one-hue sequential blue ramp (steps 250 -> 700), position by log(dt); 13 dt values
    cannot be told apart by color alone, so hydrographs carry direct dt labels.
  * variants: categorical slots 1-5 in fixed order (blue, orange, aqua, yellow, magenta),
    each with its own marker (secondary encoding; three slots sit below 3:1 contrast).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

RAMP = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab",
        "#184f95", "#104281", "#0d366b"]
VAR_STYLE = {
    "core_point": ("#2a78d6", "o", "core, point-sampled forcing"),
    "core_volume": ("#eb6834", "s", "core, volume-consistent forcing"),
    "short_ts": ("#1baf7a", "^", "short-time-step assumption on"),
    "slope_1e-4": ("#eda100", "D", "s0 = 1e-4"),
    "slope_1e-5": ("#e87ba4", "v", "s0 = 1e-5"),
}
INK, MUTED, GRID, SPINE = "#1f1f1e", "#6b6a64", "#e6e5e0", "#b5b4ad"


def dt_color(dt, dts):
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seqblue", RAMP)
    lo, hi = np.log(min(dts)), np.log(max(dts))
    return cmap((np.log(dt) - lo) / (hi - lo))


def style(ax):
    ax.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(SPINE)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.xaxis.label.set_color(INK)
    ax.yaxis.label.set_color(INK)
    ax.title.set_color(INK)


def load():
    summ = json.loads((RESULTS / "extended_summary.json").read_text())
    outl = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    with open(RESULTS / "extended_outlet.csv") as f:
        for row in csv.DictReader(f):
            o = outl[row["variant"]][int(row["dt_s"])]
            for k in ("time_h", "ql_segment0_cms", "q_outlet_cms"):
                o[k].append(float(row[k]))
    return summ, outl


def hydro_panel(ax, outl_v, dts, title, xlim, label_min_dt=300):
    placed = []
    for dt in dts:
        o = outl_v[dt]
        t, q = np.array(o["time_h"]), np.array(o["q_outlet_cms"])
        ax.plot(t, q, color=dt_color(dt, dts), lw=1.6, label=f"{dt} s", drawstyle="default")
        k = int(np.argmax(q))
        clash = any(abs(t[k] - tp) < 0.06 * (xlim[1] - xlim[0]) and abs(q[k] - qp) < 25 for tp, qp in placed)
        if dt >= label_min_dt and t[k] < xlim[1] and not clash:
            placed.append((t[k], q[k]))
            ax.annotate(f"{dt}", (t[k], q[k]), xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=6.5, color=INK)
    o = outl_v[dts[0]]
    ax.plot(o["time_h"], o["ql_segment0_cms"], "--", color=MUTED, lw=1.0,
            label=f"forcing at dt = {dts[0]} s")
    ax.set_xlim(*xlim)
    ax.set_title(title, fontsize=9, loc="left")
    ax.set_ylabel("Outlet flow (m³/s)", fontsize=8)
    style(ax)


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    summ, outl = load()
    dts = summ["parameters"]["dt_list_s"]
    runs = summ["runs"]

    # 1. core hydrographs, both forcing variants
    fig, axs = plt.subplots(2, 1, figsize=(9, 8), sharex=True)
    hydro_panel(axs[0], outl["core_point"], dts,
                "(a) Point-sampled forcing (notebook formula): injected volume changes with dt", (0, 60))
    hydro_panel(axs[1], outl["core_volume"], dts,
                "(b) Volume-consistent forcing: same pulse volume at every dt", (0, 60))
    axs[1].set_xlabel("Time (h)", fontsize=8)
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, loc="center right", fontsize=7, title="routing dt", title_fontsize=7, frameon=False)
    fig.suptitle("Outlet hydrographs, 20 km uniform channel (s0 = 0.008), dx = 2000 m, dt = 30 s to 4 h\n"
                 "(extension of courant_test.ipynb; labels mark each peak's dt)", fontsize=10, color=INK)
    fig.tight_layout(rect=(0, 0, 0.86, 0.95))
    fig.savefig(RESULTS / "extended_hydrographs_core.png", dpi=150)
    plt.close(fig)

    # 2. forcing per dt
    fig, axs = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, v, title in ((axs[0], "core_point", "(a) Point-sampled (notebook formula)"),
                         (axs[1], "core_volume", "(b) Step-averaged (volume-consistent)")):
        for dt in dts:
            o = outl[v][dt]
            ax.step(o["time_h"], o["ql_segment0_cms"], where="pre", color=dt_color(dt, dts), lw=1.3,
                    label=f"{dt} s ({runs[v][dts.index(dt)]['injected_over_pulse_volume']:.2f}× volume)")
        ax.set_xlim(0, 16)
        ax.set_title(title, fontsize=9, loc="left")
        ax.set_xlabel("Time (h); value applied over the step ending at t", fontsize=8)
        style(ax)
        ax.legend(fontsize=5.8, frameon=False, loc="upper right", title="dt (injected / true pulse volume)",
                  title_fontsize=6)
    axs[0].set_ylabel("Lateral inflow, segment 0 (m³/s)", fontsize=8)
    fig.suptitle("Forcing as the kernel sees it at each dt (Gaussian pulse, σ = 0.5 h, on 2000 m³/s)",
                 fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(RESULTS / "extended_forcing.png", dpi=150)
    plt.close(fig)

    # 3. variant hydrographs
    fig, axs = plt.subplots(3, 1, figsize=(9, 10), sharex=True)
    for ax, v, title in ((axs[0], "short_ts", "(a) Short-time-step assumption enabled (quc = qup), s0 = 0.008"),
                         (axs[1], "slope_1e-4", "(b) s0 = 1e-4 (normal-depth start)"),
                         (axs[2], "slope_1e-5", "(c) s0 = 1e-5 (normal-depth start)")):
        hydro_panel(ax, outl[v], dts, title + ", volume-consistent forcing", (0, 80))
    axs[2].set_xlabel("Time (h)", fontsize=8)
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, loc="center right", fontsize=7, title="routing dt", title_fontsize=7, frameon=False)
    fig.suptitle("Outlet hydrographs, variants (same channel otherwise; unlabeled peaks coincide with a labeled one)", fontsize=10, color=INK)
    fig.tight_layout(rect=(0, 0, 0.86, 0.97))
    fig.savefig(RESULTS / "extended_hydrographs_variants.png", dpi=150)
    plt.close(fig)

    # 4. metrics vs max C
    fig, axs = plt.subplots(2, 2, figsize=(10, 7.5))
    panels = [("peak_time_shift_vs_dt30_h", "Peak time shift vs dt = 30 s (h)"),
              ("travel_time_centroid_h", "Centroid travel time, forcing → outlet (h)"),
              ("peak_excess_change_vs_dt30_pct", "Peak (above baseflow) change vs dt = 30 s (%)"),
              ("volume_ratio_out_over_in", "Outlet / injected pulse volume")]
    for ax, (key, lab) in zip(axs.flat, panels):
        for v, (col, mk, vl) in VAR_STYLE.items():
            x = [r["max_courant"] for r in runs[v]]
            y = [r[key] for r in runs[v]]
            ax.plot(x, y, color=col, marker=mk, ms=5, lw=1.6, label=vl)
        ax.set_xscale("log")
        ax.axvline(1, color=SPINE, lw=0.9, ls=":")
        ax.set_ylabel(lab, fontsize=8)
        ax.set_xlabel("Maximum Courant number in the run", fontsize=8)
        style(ax)
    axs[0, 0].legend(fontsize=7, frameon=False)
    axs[1, 1].axhline(1, color=SPINE, lw=0.9)
    fig.suptitle("What C > 1 does in this kernel: delay, attenuation, volume (dt = 30 s ... 4 h; dotted line C = 1)",
                 fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(RESULTS / "extended_metrics_vs_courant.png", dpi=150)
    plt.close(fig)

    # 5. clamp / floor / sign fractions vs dt
    fig, axs = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    for ax, (key, lab) in zip(axs, (("frac_Km_clamped_to_dt", "Km clamped to dt (dx/Ck < dt)"),
                                     ("frac_X2_floor_0p25", "X on the 0.25 floor"),
                                     ("frac_C2_negative", "C2 < 0"))):
        for i, (v, (col, mk, vl)) in enumerate(VAR_STYLE.items()):
            y = [r["closure"][key] + (i - 2) * 0.012 for r in runs[v]]   # small offset: overlapping lines
            ax.plot(dts, y, color=col, marker=mk, ms=5, lw=1.4, label=vl)
        ax.set_xscale("log")
        ax.set_title(lab, fontsize=9, loc="left")
        ax.set_xlabel("Routing dt (s)", fontsize=8)
        style(ax)
    axs[0].set_ylabel("Fraction of segment-steps\n(lines offset ±0.024 to stay visible)", fontsize=8)
    axs[0].legend(fontsize=7, frameon=False)
    fig.suptitle("Where the closure's limits bind (X cap 0.5 and C3 < 0: never in any run)", fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(RESULTS / "extended_clamp_floor_vs_dt.png", dpi=150)
    plt.close(fig)

    # 6. K, X, C, D distributions vs dt
    fig, axs = plt.subplots(2, 2, figsize=(11, 8))
    specs = [("Km_s", "Km (s): median, band = min–max", "log"),
             ("X2_raw", "Unclamped X (interval 2): median, band = min–max", "symlog"),
             ("courant_kernel", "Courant number C = Ck·dt/dx", "log"),
             ("D_cell", "Cell Reynolds number D = Q/(B·S0·Ck·dx)", "log")]
    for ax, (key, lab, scale) in zip(axs.flat, specs):
        for v, (col, mk, vl) in VAR_STYLE.items():
            st = [r["closure"][key] for r in runs[v]]
            ax.plot(dts, [s["median"] for s in st], color=col, marker=mk, ms=5, lw=1.4, label=vl)
            ax.fill_between(dts, [s["min"] for s in st], [s["max"] for s in st], color=col, alpha=0.12, lw=0)
        ax.set_xscale("log")
        ax.set_yscale(scale, **({"linthresh": 0.5} if scale == "symlog" else {}))
        ax.set_title(lab, fontsize=9, loc="left")
        ax.set_xlabel("Routing dt (s)", fontsize=8)
        style(ax)
    axs[0, 0].plot(dts, dts, color=INK, lw=0.9, ls="--", label="Km = dt (clamp)")
    axs[0, 1].axhline(0.25, color=INK, lw=0.9, ls="--", label="0.25 floor (final X)")
    axs[0, 1].axhline(0.5, color=MUTED, lw=0.9, ls=":", label="0.5 cap")
    axs[1, 0].axhline(1, color=INK, lw=0.9, ls="--", label="C = 1")
    axs[1, 1].axhline(1, color=INK, lw=0.9, ls="--", label="D = 1: kernel X = 0.25")
    axs[0, 0].legend(fontsize=6.5, frameon=False)
    for ax in list(axs.flat)[1:]:          # variant key is in panel (a); here only the reference lines
        refs = [(h, l) for h, l in zip(*ax.get_legend_handles_labels()) if l not in
                {vl for _, _, vl in VAR_STYLE.values()}]
        ax.legend(*zip(*refs), fontsize=6.5, frameon=False)
    fig.suptitle("Routing parameters produced by the kernel's Cunge closure (secant2_h), all segment-steps\n"
                 "final X = clamp(unclamped X, 0.25, 0.5); core runs overlap", fontsize=10, color=INK)
    fig.tight_layout()
    fig.savefig(RESULTS / "extended_K_X_vs_dt.png", dpi=150)
    plt.close(fig)
    print("wrote results/extended_{hydrographs_core,hydrographs_variants,forcing,metrics_vs_courant,"
          "clamp_floor_vs_dt,K_X_vs_dt}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
