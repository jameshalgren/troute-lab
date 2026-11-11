# /// script
# requires-python = "==3.12.*"
# dependencies = ["numpy==2.5.4", "numba==0.68.1", "netCDF4==1.7.5.1.post1", "pandas==3.0.6", "matplotlib==3.11.2"]
# ///
"""Figures and headline tables from results/*.csv.   uv run make_figures.py"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import jitsched as J

R = Path(__file__).resolve().parent / "results"
res = pd.read_csv(R / "results.csv")
sens = pd.read_csv(R / "overhead_sensitivity.csv")
prof = pd.read_csv(R / "busy_profile.csv")
ordr = pd.read_csv(R / "order_sensitivity.csv")

# Okabe-Ito based, checked with the dataviz skill's validate_palette (light surface): all PASS
# opp_rounds orange warns on contrast (2.2:1); it always has a marker, a legend entry and a table
COL = {"opp_fifo": "#0072B2", "opp_rounds": "#E69F00", "opp_lrp": "#009E73", "jit": "#D55E00", "by_network": "#A6477F",
       "jit_list": "#D55E00", "jit_barrier": "#D55E00", "jit_release": "#555555", "work_steal": "#555555"}
LAB = dict(J.POLICY_NAMES)                 # plain names; code labels are the keys
MRK = {"opp_fifo": "o", "opp_rounds": "v", "opp_lrp": "s", "jit": "^", "by_network": "D", "jit_list": "<", "jit_barrier": ">",
       "jit_release": "x", "work_steal": "+"}
POL4 = ("opp_rounds", "opp_fifo", "jit", "opp_lrp")    # the four policies of the main comparison
TABLES = Path(__file__).resolve().parent / "tables"   # small, committed copies of the headline tables
GRAN = {"segment": "By segment", "reach_unit": "By reach (unit cost)", "reach_cost": "By reach (cost = segments)",
        "subnet": "By subnetwork", "cluster_old": "Clustered, old rule", "cluster_bin": "Clustered, bin packing"}
plt.rcParams.update({"font.size": 8.5, "axes.titlesize": 9, "axes.titleweight": "bold", "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6e6e6", "grid.linewidth": 0.6,
                     "figure.facecolor": "white", "axes.facecolor": "white", "legend.frameon": False})
INFX = 4096   # where P = infinity is drawn
SC_LABEL = {"Mississippi": "Mississippi (1,117,312 seg.)", "CONUS": "CONUS (2,776,734 seg.)",
            "RioGrande": "Rio Grande (54,182 seg.)", "LowerColorado_TX": "Colorado R., TX (11,248 seg.)",
            "Brazos": "Brazos R. (14,293 seg.)", "LowerColorado_TX+Brazos": "Colorado TX + Brazos (25,541 seg.)",
            "Trinity": "Trinity R. (9,616 seg.)", "Potomac": "Potomac (16,454 seg.)"}


def px(P):
    return P.where(np.isfinite(P), INFX)


def sel(df, **kw):
    m = np.ones(len(df), bool)
    for k, v in kw.items():
        m &= (df[k] == v).values
    return df[m]


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(R / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ 1. speedup vs cores
def fig_speedup():
    scopes = ["Mississippi", "CONUS", "RioGrande", "LowerColorado_TX+Brazos"]
    grans = [("segment", 0), ("reach_cost", 0), ("cluster_bin", 1000)]
    fig, axs = plt.subplots(len(scopes), len(grans), figsize=(7.4, 8.6), sharex=True)
    for i, sc in enumerate(scopes):
        for j, (g, T) in enumerate(grans):
            ax = axs[i, j]
            d = sel(res, scope=sc, granularity=g, T=T)
            for pol in POL4:
                e = sel(d, policy=pol).sort_values("P", key=lambda s: s.replace(np.inf, INFX))
                ax.plot(px(e.P), e.speedup, color=COL[pol], marker=MRK[pol], ms=3.5, lw=1.3, label=LAB[pol])
            e = sel(res, scope=sc, granularity="network").sort_values("P", key=lambda s: s.replace(np.inf, INFX))
            ax.plot(px(e.P), e.speedup, color=COL["by_network"], marker=MRK["by_network"], ms=3, lw=1.1, ls="--",
                    label=LAB["by_network"])
            e = sel(d, policy="jit")
            lb = (e.work_segments / np.maximum(e.lb_work.where(e.P.apply(np.isfinite), 0), e.lb_cp)).values
            ax.plot(px(e.P).values, lb, color="#555555", lw=0.9, ls=":", label="Bound: min(P, work / critical path)")
            ax.set_xscale("log", base=2)
            ax.set_yscale("log")
            if i == 0:
                ax.set_title(GRAN[g] + (f", T = {T}" if T else ""), fontsize=8.5)
            if j == 0:
                ax.set_ylabel(SC_LABEL[sc].replace(" (", "\n(") + "\nspeedup over serial")
            if i == len(scopes) - 1:
                ax.set_xticks([1, 4, 16, 64, 256, 1024, INFX])
                ax.set_xticklabels(["1", "4", "16", "64", "256", "1k", "∞"])
                ax.set_xlabel("cores")
    h, l = axs[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.06), fontsize=8)
    fig.tight_layout()
    save(fig, "fig_speedup_vs_cores")


# ------------------------------------------------------------------ 2. busy-core profile
def fig_profile():
    cfgs = [("Mississippi", "segment", 0), ("Mississippi", "cluster_bin", 1000),
            ("CONUS", "segment", 0), ("CONUS", "cluster_bin", 1000)]
    fig, axs = plt.subplots(2, 2, figsize=(7.4, 5.4))
    for ax, (sc, g, T) in zip(axs.ravel(), cfgs):
        P = 36
        for pol in POL4 + ("by_network",):
            gg, TT = ("network", 0) if pol == "by_network" else (g, T)
            d = sel(prof, scope=sc, granularity=gg, T=TT, policy=pol, P=P)
            if d.empty:
                continue
            ms = sel(res, scope=sc, granularity=gg, T=TT, policy=pol, P=P).makespan.iloc[0]
            ideal = sel(res, scope=sc, granularity="segment", T=0, policy="jit", P=P).work_segments.iloc[0] / P
            ax.plot(d.t_frac * ms / ideal, d.busy / P * 100, color=COL[pol], lw=0.9, label=LAB[pol])
        ax.set_ylim(0, 105)
        mx = max(sel(res, scope=sc, granularity=g, T=T, policy=p, P=36).makespan.iloc[0] for p in POL4)
        ideal = sel(res, scope=sc, granularity="segment", T=0, policy="jit", P=36).work_segments.iloc[0] / 36
        ax.set_xlim(0, mx / ideal * 1.08)
        ax.set_title(f"{SC_LABEL[sc].split(' (')[0]}, {GRAN[g].lower()}" + (f" (T = {T})" if T else ""), fontsize=8.5)
        ax.set_xlabel("time / (total work / 36 cores)")
        ax.set_ylabel("cores busy (%)")
    axs[0, 0].legend(fontsize=7, loc="lower left")
    fig.text(0.5, -0.01, "By-network curve runs off the right edge (one core busy for most of its much longer makespan).",
             ha="center", fontsize=7.5)
    fig.tight_layout()
    save(fig, "fig_busy_profile_P36")


# ------------------------------------------------------------------ 2b. saturation profile (paper figure)
def fig_saturation():
    """Cores busy over time, by segment, Mississippi and Texas Colorado test network, 36 and
    128 cores, the four main policies. Time is divided by the lower bound
    max(W/P, critical path), so 1.0 is the best any schedule can do."""
    scopes = ["Mississippi", "LowerColorado_TX"]
    fig, axs = plt.subplots(2, 2, figsize=(7.4, 5.6), sharey=True)
    for i, sc in enumerate(scopes):
        for j, P in enumerate((36, 128)):
            ax = axs[i, j]
            lines = []
            mx = 0
            for pol in POL4:
                d = sel(prof, scope=sc, granularity="segment", T=0, policy=pol, P=P)
                e = sel(res, scope=sc, granularity="segment", T=0, policy=pol, P=P).iloc[0]
                x = d.t_frac * e.makespan / e.lb
                mx = max(mx, e.makespan / e.lb)
                ax.plot(x, d.busy / P * 100, color=COL[pol], lw=1.1, label=LAB[pol])
                lines.append(f"{LAB[pol].split(' (')[0]}: {e.idle_core_time / (P * e.makespan) * 100:.1f}%")
            ax.axvline(1.0, color="#999999", lw=0.8, ls=(0, (2, 2)))
            ax.set_xlim(0, mx * 1.03)
            ax.set_ylim(0, 105)
            ax.set_title(f"{SC_LABEL[sc]}, {P} cores", fontsize=8.5)
            xy = (0.25, 0.12) if sc == "Mississippi" else (0.52, 0.62)
            ax.text(*xy, "idle core-time (% of P x makespan)\n" + "\n".join(lines), transform=ax.transAxes, fontsize=6.5,
                    color="#333333", va="bottom", bbox=dict(facecolor="white", edgecolor="#cccccc", alpha=0.9, lw=0.5))
            if i == 1:
                ax.set_xlabel("time / lower bound  (dotted line = best possible finish)")
            if j == 0:
                ax.set_ylabel("cores busy (%)")
    h, l = axs[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.07), fontsize=8)
    fig.tight_layout()
    save(fig, "fig_saturation_segments")


# ------------------------------------------------------------------ 3. utilization and tail
def fig_util_tail():
    """Utilization and makespan above the lower bound, 36 cores."""
    scopes = ["Mississippi", "CONUS", "RioGrande", "LowerColorado_TX+Brazos"]
    cats = [("segment", 0), ("reach_unit", 0), ("reach_cost", 0), ("cluster_bin", 1000), ("cluster_bin", 10000)]
    cl = ["seg.", "reach\nunit", "reach\ncost", "clus.\nT=1k", "clus.\nT=10k"]
    fig, axs = plt.subplots(2, 4, figsize=(8.2, 4.8), sharey="row")
    w = 0.2
    for j, sc in enumerate(scopes):
        for k, pol in enumerate(POL4):
            u, t = [], []
            for g, T in cats:
                e = sel(res, scope=sc, granularity=g, T=T, policy=pol, P=36).iloc[0]
                u.append(e.util * 100)
                t.append((e.makespan / e.lb - 1) * 100)
            x = np.arange(len(cats)) + (k - 1.5) * w
            axs[0, j].bar(x, u, w, color=COL[pol], label=LAB[pol])
            axs[1, j].bar(x, t, w, color=COL[pol])
        axs[0, j].set_title(SC_LABEL[sc].replace(" (", "\n("), fontsize=8)
        for r in (0, 1):
            axs[r, j].set_xticks(range(len(cats)))
            axs[r, j].set_xticklabels(cl if r else [""] * len(cats), fontsize=7)
            axs[r, j].grid(axis="x", visible=False)
    axs[0, 0].set_ylabel("core utilization (%)\n(36 cores)")
    axs[1, 0].set_ylabel("makespan above\nlower bound (%)")
    axs[1, 0].set_yscale("symlog", linthresh=10)
    h, l = axs[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.08), fontsize=8)
    fig.tight_layout()
    save(fig, "fig_utilization_excess_P36")


# ------------------------------------------------------------------ 4. overhead sensitivity
def fig_overhead():
    scopes = ["Mississippi", "CONUS", "LowerColorado_TX+Brazos"]
    fig, axs = plt.subplots(1, 3, figsize=(7.4, 3.2), sharey=False)
    ls = {"segment": "-", "reach_cost": "--", "cluster_bin": ":"}
    for ax, sc in zip(axs, scopes):
        for g, T in (("segment", 0), ("reach_cost", 0), ("cluster_bin", 1000)):
            for pol in POL4:
                e = sel(sens, scope=sc, granularity=g, T=T, policy=pol, P=36).sort_values("overhead")
                e = e[e.overhead > 0]
                ax.plot(e.overhead, e.speedup, color=COL[pol], ls=ls[g], lw=1.2)
        e = sel(sens, scope=sc, granularity="network", P=36).sort_values("overhead")
        ax.plot(e[e.overhead > 0].overhead, e[e.overhead > 0].speedup, color=COL["by_network"], lw=1.1, ls="-.")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_title(SC_LABEL[sc].replace(" (", "\n("), fontsize=8)
        ax.set_xlabel("dispatch overhead per unit\n(in segment-compute times)")
    axs[0].set_ylabel("speedup over serial, 36 cores")
    from matplotlib.lines import Line2D
    hs = [Line2D([], [], color=COL[p], lw=1.5, label=LAB[p]) for p in POL4 + ("by_network",)]
    hs += [Line2D([], [], color="#444", ls=ls[g], label=GRAN[g] + (", T=1000" if g == "cluster_bin" else ""))
           for g in ("segment", "reach_cost", "cluster_bin")]
    fig.legend(handles=hs, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.24), fontsize=7.5)
    fig.tight_layout()
    save(fig, "fig_overhead_sensitivity")


# ------------------------------------------------------------------ 5. cluster threshold and balancing
def fig_thresholds():
    fig, axs = plt.subplots(1, 3, figsize=(7.4, 3.0), sharey=False)
    Ts = [100, 1000, 10000, 100000]
    ls = {"subnet": "-", "cluster_old": "--", "cluster_bin": ":"}
    for ax, sc in zip(axs, ["Mississippi", "CONUS", "RioGrande"]):
        for g in ("subnet", "cluster_old", "cluster_bin"):
            for pol in POL4:
                y = [sel(res, scope=sc, granularity=g, T=T, policy=pol, P=36).speedup.iloc[0] for T in Ts]
                ax.plot(Ts, y, color=COL[pol], ls=ls[g], marker=MRK[pol], ms=3, lw=1.2)
        ax.axhline(sel(res, scope=sc, granularity="segment", T=0, policy="opp_lrp", P=36).speedup.iloc[0], color="#999999",
                   lw=2.5, alpha=0.5, zorder=0)
        ax.set_xscale("log")
        ax.set_title(SC_LABEL[sc].replace(" (", "\n("), fontsize=8)
        ax.set_xlabel("subnetwork_target_size T")
    axs[0].set_ylabel("speedup over serial, 36 cores")
    from matplotlib.lines import Line2D
    hs = [Line2D([], [], color=COL[p], lw=1.5, marker=MRK[p], ms=3, label=LAB[p]) for p in POL4]
    hs += [Line2D([], [], color="#444", ls=ls[g], label={"subnet": "subnetworks, unclustered", "cluster_old": "clustered, old 0.65 rule (ascending-id order)",
                                                       "cluster_bin": "clustered, bin packing (PR #26)"}[g]) for g in ls]
    hs += [Line2D([], [], color="#999999", lw=2.5, alpha=0.5, label="reference: by segment, longest-path-first")]
    fig.legend(handles=hs, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.3), fontsize=7.5)
    fig.tight_layout()
    save(fig, "fig_cluster_thresholds_P36")


# ------------------------------------------------------------------ tables
def tables():
    TABLES.mkdir(exist_ok=True)
    # structural one-core tail: longest-path-first with unlimited cores (a property of the network)
    st = sel(res, policy="opp_lrp")[np.isinf(sel(res, policy="opp_lrp").P)].set_index(["scope", "granularity", "T"]).tail_len
    r = res.copy()
    r["structural_tail"] = [st.get((a, b, c), np.nan) for a, b, c in zip(r.scope, r.granularity, r["T"])]
    r["excess_over_lb_pct"] = (r.makespan / r.lb - 1) * 100
    r["policy_name"] = r.policy.map(LAB)
    cols = ["scope", "granularity", "T", "policy", "policy_name", "P", "n_units", "makespan", "lb", "excess_over_lb_pct",
            "idle_core_time", "util", "idle_share_first_half", "tail_len", "structural_tail", "speedup"]
    t = r[r.P == 36][cols]
    t.to_csv(R / "headline_P36.csv", index=False)
    t.to_csv(TABLES / "headline_P36.csv", index=False)
    with open(TABLES / "headline_P36.md", "w") as f:
        f.write("Generated by make_figures.py from results/results.csv. 36 cores, zero overhead. "
                "tail = final stretch with one core busy; structural = that tail for longest-path-first with "
                "unlimited cores. cluster_old rows use ascending-id subnetwork order (see cluster_order_ranges.md).\n")
        for sc in t.scope.unique():
            f.write(f"\n### {sc}, 36 cores\n\n| granularity | T | policy | units | makespan | lower bound | above bound % | util % | tail | structural tail | speedup |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
            for _, x in t[t.scope == sc].iterrows():
                f.write(f"| {x.granularity} | {int(x['T']) or ''} | {x.policy} | {int(x.n_units):,} | {x.makespan:,.0f} | {x.lb:,.0f} | "
                        f"{x.excess_over_lb_pct:.1f} | {x.util*100:.1f} | {x.tail_len:,.0f} | {x.structural_tail:,.0f} | {x.speedup:.2f} |\n")
    # makespan by core count (the high-core regime matters for the author's 1000x argument)
    rows = []
    for sc in ["Mississippi", "CONUS", "RioGrande", "LowerColorado_TX", "Brazos", "LowerColorado_TX+Brazos", "Trinity"]:
        for g in ("segment", "reach_unit", "reach_cost"):
            for P in (8, 36, 128, 1024, np.inf):
                e = sel(r, scope=sc, granularity=g, T=0)
                e = e[e.P == P].set_index("policy")
                row = dict(scope=sc, granularity=g, P=P, lb=e.lb.iloc[0])
                for pol in ("opp_fifo", "opp_rounds", "opp_lrp", "jit", "jit_list"):
                    row[pol] = e.makespan[pol]
                row["jit_vs_fifo_pct"] = (1 - row["jit"] / row["opp_fifo"]) * 100
                row["jit_vs_rounds_pct"] = (1 - row["jit"] / row["opp_rounds"]) * 100
                row["lrp_vs_jit_pct"] = (1 - row["opp_lrp"] / row["jit"]) * 100
                rows.append(row)
    v = pd.DataFrame(rows)
    v.to_csv(TABLES / "makespan_by_cores.csv", index=False)
    with open(TABLES / "makespan_by_cores.md", "w") as f:
        f.write("Makespan in cost units (cycles for unit cost). jit_vs_fifo = how much shorter JIT is than "
                "first-ready-first (%); jit_vs_rounds = vs 2020-style rounds; lrp_vs_jit = how much shorter "
                "longest-path-first is than JIT. Generated by make_figures.py.\n\n"
                "| scope | granularity | cores | lower bound | first-ready | rounds | longest-path | JIT | JIT list order | JIT vs first-ready % | JIT vs rounds % | LPF vs JIT % |\n"
                "|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for _, x in v.iterrows():
            f.write(f"| {x.scope} | {x.granularity} | {'inf' if np.isinf(x.P) else int(x.P)} | {x.lb:,.0f} | {x.opp_fifo:,.0f} | "
                    f"{x.opp_rounds:,.0f} | {x.opp_lrp:,.0f} | {x.jit:,.0f} | {x.jit_list:,.0f} | {x.jit_vs_fifo_pct:.1f} | "
                    f"{x.jit_vs_rounds_pct:.1f} | {x.lrp_vs_jit_pct:.1f} |\n")
    # clustered: ascending-id order vs range over shuffled orders
    o = ordr.copy()
    g = o.groupby(["scope", "granularity", "T", "P", "policy"])
    asc = o[o.seed == -1].set_index(["scope", "granularity", "T", "P", "policy"]).makespan
    sh = o[o.seed >= 0].groupby(["scope", "granularity", "T", "P", "policy"]).makespan.agg(["min", "max"])
    c = sh.join(asc.rename("ascending_id")).reset_index()
    c.to_csv(TABLES / "cluster_order_ranges.csv", index=False)
    with open(TABLES / "cluster_order_ranges.md", "w") as f:
        f.write("Clustered subnetworks: makespan with ascending-id listing order vs min-max over 5 random "
                "listing orders (T-Route's own order is not replicated here). Generated by make_figures.py.\n\n"
                "| scope | rule | T | cores | policy | ascending id | shuffled min | shuffled max |\n|---|---|---|---|---|---|---|---|\n")
        for _, x in c.iterrows():
            f.write(f"| {x.scope} | {x.granularity} | {x['T']} | {int(x.P)} | {x.policy} | {x.ascending_id:,.0f} | {x['min']:,.0f} | {x['max']:,.0f} |\n")
    saturation_tables(r)
    for name in ("summary.json", "cluster_stats.csv", "worked_example.csv"):
        if (R / name).exists():
            (TABLES / name).write_bytes((R / name).read_bytes())
    print("wrote tables")


def saturation_tables(r):
    """Segment-first saturation tables: idle core-time across core counts, and the
    reach-vs-segment comparison (item 4 of RERUN_PLAN.md)."""
    pols = ("opp_rounds", "opp_fifo", "jit", "opp_lrp", "jit_release", "work_steal")
    rows = []
    for sc in ["Mississippi", "CONUS", "RioGrande", "LowerColorado_TX", "Brazos", "LowerColorado_TX+Brazos", "Trinity", "Potomac"]:
        for P in (8, 36, 128, 1024):
            for pol in pols:
                e = sel(r, scope=sc, granularity="segment", T=0, policy=pol)
                e = e[e.P == P]
                if e.empty:
                    continue
                e = e.iloc[0]
                rows.append(dict(scope=sc, P=int(P), policy=pol, policy_name=LAB[pol], work=e.work_segments, lb=e.lb,
                                 makespan=e.makespan, idle_core_time=e.idle_core_time,
                                 idle_pct=e.idle_core_time / (P * e.makespan) * 100, util_pct=e.util * 100,
                                 idle_share_first_half_pct=e.idle_share_first_half * 100, tail=e.tail_len,
                                 structural_tail=e.structural_tail))
    t = pd.DataFrame(rows)
    t.to_csv(TABLES / "saturation_segments.csv", index=False)
    with open(TABLES / "saturation_segments.md", "w") as f:
        f.write("By segment, zero overhead, equal cost. idle core-time = P x makespan - W, in segment-cycles; "
                "with fixed W, minimizing it is the same as minimizing the makespan. 'first half' = share of the idle "
                "core-time that falls in the first half of the run (high = idle at the start, low = idle at the end). "
                "tail = final stretch with one core busy; structural = the same for Hu's rule with unlimited cores. "
                "Generated by make_figures.py.\n")
        for sc in t.scope.unique():
            f.write(f"\n### {sc}\n\n| cores | policy | makespan | lower bound | idle core-time | idle % | idle in first half % | one-core tail | structural tail |\n|---|---|---|---|---|---|---|---|---|\n")
            for _, x in t[t.scope == sc].iterrows():
                f.write(f"| {x.P} | {x.policy_name} | {x.makespan:,.0f} | {x.lb:,.0f} | {x.idle_core_time:,.0f} | {x.idle_pct:.1f} | "
                        f"{x.idle_share_first_half_pct:.0f} | {x["tail"]:,.0f} | {x.structural_tail:,.0f} |\n")
    # reach vs segment
    rows = []
    cfg = [("segment", "jit", "segments, JIT strides (distance in segments)"),
           ("segment", "opp_lrp", "segments, Hu's rule"),
           ("segment", "jit_release", "segments, JIT timetable"),
           ("reach_cost", "jit", "reaches, JIT strides by reach hops"),
           ("reach_cost", "jit_release", "reaches, JIT timetable by segment distance"),
           ("reach_cost", "opp_lrp", "reaches, Hu's rule by segment distance")]
    for sc in ["Mississippi", "CONUS", "LowerColorado_TX", "Potomac"]:
        for P in (36, 128, 1024, np.inf):
            for g, pol, name in cfg:
                e = sel(r, scope=sc, granularity=g, T=0, policy=pol)
                e = e[e.P == P].iloc[0]
                rows.append(dict(scope=sc, P=P, variant=name, makespan=e.makespan, lb=e.lb,
                                 idle_core_time=e.idle_core_time))
    v = pd.DataFrame(rows)
    v.to_csv(TABLES / "reach_vs_segment.csv", index=False)
    with open(TABLES / "reach_vs_segment.md", "w") as f:
        f.write("Makespan in segment-cycles (cost of a reach = its segments). Generated by make_figures.py.\n\n"
                "| scope | cores | lower bound | " + " | ".join(n for _, _, n in cfg) + " |\n|---|---|---|" + "---|" * len(cfg) + "\n")
        for (sc, P), g in v.groupby(["scope", "P"], sort=False):
            f.write(f"| {sc} | {'inf' if np.isinf(P) else int(P)} | {g.lb.iloc[0]:,.0f} | " + " | ".join(f"{x:,.0f}" for x in g.makespan) + " |\n")


if __name__ == "__main__":
    fig_speedup(); fig_profile(); fig_saturation(); fig_util_tail(); fig_overhead(); fig_thresholds(); tables()
