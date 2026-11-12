"""Figures for the diffusive-mainstem screening (static PNG, light surface).

Palette: the dataviz skill's validated reference palette (categorical slots 1-3 blue,
orange, aqua, which validate all-pairs; gray context). One configuration per map panel
(small multiples), so no map needs more than one data hue.

  results/fig_config_maps.png   CONUS small multiples: each configuration over the network
  results/fig_pareto.png        known-error budget captured vs network km treated
  results/fig_depth_feasibility.png  share of each configuration's km surveyable
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SURFACE = "#fcfcfb"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8984"
GRID = "#e4e3df"
CONTEXT = "#d3d2cd"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
LABELS = {
    "A_mainstem": "A  Mainstem (DA ≥ 10,000 km²)",
    "B_mainstem_fringes": "B  Mainstem + confluence fringes",
    "C1_low_slope_2.5e-4": "C1  Low-slope (S0 < 2.5e-4)",
    "C2_low_slope_1e-4": "C2  Low-slope (S0 < 1e-4)",
    "D1_flat_miss_alluvial_plain": "D1  Flat: Mississippi Alluvial Plain",
    "D2_coastal_plain": "D2  Coastal: Coastal Plain province",
    "E_navigable_nwn": "E  Navigable: National Waterway Network",
    "F_candidate": "F  Candidate (B ∩ error-flagged ∩ surveyable)",
}
MAP_PANELS = ["A_mainstem", "B_mainstem_fringes", "C1_low_slope_2.5e-4", "D2_coastal_plain", "E_navigable_nwn",
              "F_candidate"]


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(MUTED)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(True, color=GRID, lw=0.6)
    ax.set_axisbelow(True)


def fig_maps(seg, res):
    fig, axes = plt.subplots(3, 2, figsize=(12, 11), facecolor=SURFACE)
    ctxm = (~seg["lake"]) & (seg["order"] >= 3)
    for ax, k in zip(axes.ravel(), MAP_PANELS):
        ax.set_facecolor(SURFACE)
        ax.scatter(seg.loc[ctxm, "lon"], seg.loc[ctxm, "lat"], s=0.02, c=CONTEXT, lw=0, rasterized=True)
        m = seg[f"cfg_{k}"].to_numpy(bool)
        ax.scatter(seg.loc[m, "lon"], seg.loc[m, "lat"], s=0.15 if m.sum() > 2e5 else 0.4, c=S1, lw=0, rasterized=True)
        c = res["configurations"][k]
        ax.set_title(LABELS[k], loc="left", fontsize=11, color=INK)
        ax.text(0.01, 0.02, f"{c['km']:,.0f} km · {c['pct_network_km']:.1f}% of network km · "
                f"{c['pct_known_error_budget']:.0f}% known-error · "
                f"{c['pct_parameter_effect_budget']:.0f}% parameter-effect budget",
                transform=ax.transAxes, fontsize=8.5, color=INK2)
        ax.set_xlim(-125, -66.5)
        ax.set_ylim(24, 50)
        ax.set_aspect(1.25)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
    fig.suptitle("Candidate diffusive-routing configurations on the NWM v3.1.7 CONUS network "
                 "(blue = in configuration; gray = Strahler order ≥ 3 context)", fontsize=11.5, color=INK, x=0.02,
                 ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(RESULTS / "fig_config_maps.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)


def fig_pareto(par, res):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5.6), facecolor=SURFACE)
    for ax in (a1, a2):
        style(ax)
    a1.plot(par["pct_km"], par["pct_budget"], color=S1, lw=2, label="known-error budget (flagged mean flow × km)")
    a1.plot(par["pct_km"], par["pct_flagged_km"], color=S2, lw=2, label="error-flagged km (unweighted)")
    a1.plot(par["pct_km"], par["pct_effect_budget"], color=S3, lw=2, ls="--",
            label="parameter-effect budget (same ordering)")
    xs = np.logspace(-1, 2, 100)
    a1.plot(xs, xs, color=MUTED, lw=1, ls=":", label="untargeted (share captured = share treated)")
    for k, c in res["configurations"].items():
        a1.plot(c["pct_network_km"], c["pct_known_error_budget"], "o", ms=8, mfc=INK, mec=SURFACE, mew=2)
        a1.annotate(k.split("_")[0], (c["pct_network_km"], c["pct_known_error_budget"]), xytext=(6, -3),
                    textcoords="offset points", fontsize=9, color=INK)
    a1.set_xscale("log")
    a1.set_xlim(0.1, 100)
    a1.set_ylim(0, 102)
    a1.set_xlabel("network km treated with diffusive routing (% of CONUS MC km, log scale)", color=INK2)
    a1.set_ylabel("share captured (%)", color=INK2)
    a1.legend(frameon=False, fontsize=8.5, loc="upper center", labelcolor=INK2, bbox_to_anchor=(0.5, -0.13), ncol=2)
    a1.text(0.98, 0.03, "curves: error-flagged segments added in decreasing mean annual flow\n"
            "dots: configurations (known-error budget)", transform=a1.transAxes, ha="right",
            fontsize=8, color=INK2)
    a1.set_title("Known error captured vs share of network treated", loc="left", fontsize=11, color=INK)
    for k, c in res["configurations"].items():
        shallow = c["km"] * (100 - c["pct_km_depth_ge_1m"]) / 100 / 1000
        a2.plot(shallow, c["pct_known_error_budget"], "o", ms=8, mfc=S1, mec=SURFACE, mew=2)
        a2.plot(shallow, c["pct_error_km_captured"], "s", ms=7, mfc=S2, mec=SURFACE, mew=2)
        a2.annotate(k.split("_")[0], (shallow, c["pct_known_error_budget"]), xytext=(6, 2),
                    textcoords="offset points", fontsize=9, color=INK)
    a2.plot([], [], "o", ms=8, mfc=S1, mec=SURFACE, label="known-error budget captured")
    a2.plot([], [], "s", ms=7, mfc=S2, mec=SURFACE, label="error-flagged km captured")
    a2.legend(frameon=False, fontsize=8.5, loc="center left", labelcolor=INK2, bbox_to_anchor=(0.02, 0.42))
    a2.set_xscale("symlog", linthresh=1)
    a2.set_xlabel("km with mean-flow depth < 1 m (thousand km, symlog)", color=INK2)
    a2.set_ylabel("share captured (%)", color=INK2)
    a2.set_ylim(0, 102)
    a2.set_title("Error captured vs shallow km needing bathymetry", loc="left", fontsize=11,
                 color=INK)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_pareto.png", dpi=170, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def fig_depth(res):
    keys = list(res["configurations"].keys())
    c = res["configurations"]
    series = [("mean-flow depth ≥ 1 m", "pct_km_depth_ge_1m", S1), ("mean-flow depth ≥ 2 m", "pct_km_depth_ge_2m", S2),
              ("on National Waterway Network", "pct_km_on_nwn", S3)]
    fig, ax = plt.subplots(figsize=(10, 6.5), facecolor=SURFACE)
    style(ax)
    ax.grid(axis="y", visible=False)
    y = np.arange(len(keys))[::-1]
    h = 0.26
    for j, (lab, f, col) in enumerate(series):
        vals = [c[k][f] or 0 for k in keys]
        ax.barh(y + (1 - j) * h, vals, height=h - 0.03, color=col, label=lab, edgecolor=SURFACE, lw=1)
        for yy, v in zip(y + (1 - j) * h, vals):
            ax.text(v + 0.8, yy, f"{v:.0f}", va="center", fontsize=8, color=INK2)
    ax.set_yticks(y)
    ax.set_yticklabels([LABELS[k] for k in keys], fontsize=9, color=INK)
    ax.set_xlim(0, 108)
    ax.set_xlabel("% of the configuration's channel km", color=INK2)
    ax.legend(frameon=False, fontsize=9, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, labelcolor=INK2)
    ax.set_title("Survey feasibility of each configuration\n(depth: NHDPlusV2 EROM mean annual Q/V on the "
                 "RouteLink trapezoid)", loc="left", fontsize=10.5, color=INK, pad=28)
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_depth_feasibility.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)


def main() -> int:
    res = json.loads((RESULTS / "results.json").read_text())
    seg = pd.read_parquet(RESULTS / "segments_conus.parquet",
                          columns=["lon", "lat", "lake", "order"] + [f"cfg_{k}" for k in LABELS])
    par = pd.read_parquet(RESULTS / "pareto.parquet")
    fig_maps(seg, res)
    fig_pareto(par, res)
    fig_depth(res)
    print("figures written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
