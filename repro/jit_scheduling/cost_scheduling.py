# /// script
# requires-python = "==3.12.*"
# dependencies = ["numpy==2.5.4", "numba==0.68.1", "netCDF4==1.7.5.1.post1", "pandas==3.0.6", "matplotlib==3.11.2"]
# ///
"""Scheduling the Potomac network with measured per-segment Muskingum-Cunge costs
(RERUN_PLAN.md item 2, scheduling part).

    uv run cost_scheduling.py   -> results/cost_scheduling.csv, tables/cost_scheduling.{csv,md},
                                   results/fig_cost_scheduling.{png,pdf}

Input: ../mc_cost_variability/results/cost/ (gitignored there; create it with
`bash ../mc_cost_variability/run.sh`). Costs are secant iterations of the MC kernel (float32
port), per segment: a 24-h window (one T-Route-like subnetwork call over 288 steps) or the
whole 40-day run. Unit costs at reach and subnetwork granularity are sums over segments.

Cost knowledge given to the schedulers ("estimates"):
  equal  - every segment costs the same (the 2020 assumption): estimate = mean calm cost
           per segment x number of segments in the unit;
  stale  - the calm cost of each segment (static in calm flow, so it could be precomputed),
           used while the true cost is the flood's;
  true   - the true cost (oracle).
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import jitsched as J
from run_experiments import RL, SCOPE_OUTLETS, Scopes, THRESHOLDS

HERE = Path(__file__).resolve().parent
COST = HERE.parent / "mc_cost_variability" / "results" / "cost"
OUT = HERE / "results"
TABLES = HERE / "tables"
CORES = (8, 36, 128)
PEAK = 1                      # the storm's peak 24-h window (k = 1 in every storm run)

# (label, policy, estimate kind)
SCHEDULERS = [
    ("2020-style rounds", "opp_rounds", "equal"),
    ("naive first-ready", "opp_fifo", "equal"),
    ("JIT strides", "jit", "equal"),
    ("work stealing (cost-blind)", "work_steal", "equal"),
    ("Hu, equal-cost priorities (costs unknown)", "opp_lrp", "equal"),
    ("Hu, calm costs as estimates (stale)", "opp_lrp", "stale"),
    ("cost-aware dynamic, equal estimates downstream", "opp_lrp_dyn", "equal"),
    ("cost-aware dynamic, calm estimates downstream", "opp_lrp_dyn", "stale"),
    ("Hu, exact costs (oracle)", "opp_lrp", "true"),
]


def load_costs(D, seg_idx_of):
    if not (COST / "segment_cost.csv").exists():
        sys.exit(f"missing {COST}; run `bash ../mc_cost_variability/run.sh` first")
    tab = pd.read_csv(COST / "segment_cost.csv")
    fid = tab.feature_id.to_numpy(np.int64)
    idx = seg_idx_of(fid)
    # the cost file's network must be exactly our Potomac scope, with the same links
    out = int(np.nonzero(D["link"] == SCOPE_OUTLETS["Potomac"][0])[0][0])
    scope = np.nonzero(D["net"] == out)[0]
    assert len(fid) == len(scope) == 16454 and np.array_equal(np.sort(idx), scope), "feature ids differ from scope"
    down = D["down"][idx]
    to = np.where(down >= 0, D["link"][np.clip(down, 0, None)], 0)
    assert np.array_equal(to, tab.to_feature_id.to_numpy(np.int64)), "to_feature_id differs from RouteLink"
    win = {}
    for sc in ("calm", "s25", "s100", "s250"):
        z = np.load(COST / f"segment_window_cost_{sc}.npz")
        assert np.array_equal(z["feature_id"], fid), "window file row order differs"
        win[sc] = z
    cases = {   # name -> (true per-segment cost in csv row order, stale estimate)
        "calm, 24-h window": (win["calm"]["iters_24h"][:, PEAK], win["calm"]["iters_24h"][:, PEAK]),
        "storm 25 mm, peak 24-h window": (win["s25"]["iters_24h"][:, PEAK], win["calm"]["iters_24h"][:, PEAK]),
        "storm 100 mm, peak 24-h window": (win["s100"]["iters_24h"][:, PEAK], win["calm"]["iters_24h"][:, PEAK]),
        "storm 250 mm, peak 24-h window": (win["s250"]["iters_24h"][:, PEAK], win["calm"]["iters_24h"][:, PEAK]),
        "calm, run total (40 d)": (tab.iters_calm.to_numpy(), tab.iters_calm.to_numpy()),
        "storm 25 mm, run total": (tab.iters_s25.to_numpy(), tab.iters_calm.to_numpy()),
        "storm 250 mm, run total": (tab.iters_s250.to_numpy(), tab.iters_calm.to_numpy()),
    }
    return idx, cases


def to_full(n, idx, v):
    f = np.zeros(n, np.int64)
    f[idx] = np.asarray(v).astype(np.int64)
    return f


def graphs(D, S, sc, cost_full):
    """Potomac work-unit graphs with per-unit cost = summed segment costs."""
    G = {}
    g = J.subset(J.segment_graph(D), sc.seg_mask)
    G["segment"] = J.Graph(cost_full[sc.seg_mask], g.stride, g.esrc, g.edst)
    rc = np.bincount(D["rid"], weights=cost_full, minlength=len(D["rcost"]))
    r = J.subset(J.reach_graph(D, False), sc.reach_mask)
    G["reach"] = J.Graph(np.round(rc[sc.reach_mask]).astype(np.int64), r.stride, r.esrc, r.edst)
    for T in (100, 1000):
        sub_cost = np.bincount(S[T]["sub"], weights=cost_full, minlength=len(S[T]["order"]))
        G[f"clustered T={T}"] = J.subnetwork_graph(S[T], sc.sub_ids(T), "bin", T, sub_cost=sub_cost)
    return G


def main():
    D, S = J.load_cached(HERE / "data", RL, THRESHOLDS)
    srt = np.argsort(D["link"])

    def seg_idx_of(fid):
        p = np.searchsorted(D["link"][srt], fid)
        assert (D["link"][srt][p] == fid).all()
        return srt[p]

    idx, cases = load_costs(D, seg_idx_of)
    sc = Scopes(D, S, "Potomac", SCOPE_OUTLETS["Potomac"])
    n = len(D["down"])
    calm_mean = float(np.mean(cases["calm, 24-h window"][0]))
    calm_mean_run = float(np.mean(cases["calm, run total (40 d)"][0]))
    rows = []
    for case, (true, stale) in cases.items():
        run_total = "run total" in case
        m_eq = calm_mean_run if run_total else calm_mean
        Gt = graphs(D, S, sc, to_full(n, idx, true))
        Gs = graphs(D, S, sc, to_full(n, idx, stale))
        Ge = graphs(D, S, sc, to_full(n, idx, np.full(len(idx), m_eq)))
        for gran in Gt:
            g = Gt[gran]
            cv = float(g.cost.std() / g.cost.mean())
            for P in CORES:
                for label, pol, kind in SCHEDULERS:
                    est = {"equal": Ge[gran].cost, "stale": Gs[gran].cost, "true": None}[kind]
                    sch = J.schedule(g, pol, P, est_cost=est)
                    m = J.summarize(g, sch, P)
                    # the 2020 equal-cost model of the same unit graph (equal cost per segment,
                    # scaled to the same total work): how well does it predict this makespan?
                    ge = Ge[gran]
                    me = J.summarize(ge, J.schedule(ge, pol, P), P)
                    pred = me["makespan"] * float(g.cost.sum()) / float(ge.cost.sum())
                    lb = max(m["lb_work"], m["lb_cp"])
                    assert m["makespan"] >= lb - 1e-9
                    rows.append(dict(case=case, granularity=gran, P=P, scheduler=label, policy=pol, estimate=kind,
                                     n_units=g.n, unit_cost_cv=cv, work=float(g.cost.sum()), lb=lb,
                                     makespan=m["makespan"], excess_pct=(m["makespan"] / lb - 1) * 100,
                                     idle_core_time=m["idle_core_time"],
                                     idle_pct=m["idle_core_time"] / (P * m["makespan"]) * 100,
                                     tail=m["tail_len"], tail_pct=m["tail_frac"] * 100,
                                     equal_model_error_pct=(m["makespan"] / pred - 1) * 100))
        print(case, "done", file=sys.stderr)
    df = pd.DataFrame(rows)
    OUT.mkdir(exist_ok=True)
    TABLES.mkdir(exist_ok=True)
    df.to_csv(OUT / "cost_scheduling.csv", index=False)
    df.round(4).to_csv(TABLES / "cost_scheduling.csv", index=False)
    write_md(df)
    figure(df)


def write_md(df):
    with open(TABLES / "cost_scheduling.md", "w") as f:
        f.write("Potomac (16,454 segments), per-unit cost = measured MC secant iterations "
                "(../mc_cost_variability). Each cell: makespan above the lower bound max(W/P, cost-weighted "
                "critical path), in %, and idle share of core-time in brackets. Generated by cost_scheduling.py.\n")
        for gran in df.granularity.unique():
            for P in CORES:
                d = df[(df.granularity == gran) & (df.P == P)]
                cases = list(d.case.unique())
                f.write(f"\n### {gran}, {P} cores (units: {int(d.n_units.iloc[0]):,})\n\n| scheduler | "
                        + " | ".join(cases) + " |\n|---|" + "---|" * len(cases) + "\n")
                for lab in d.scheduler.unique():
                    cells = []
                    for c in cases:
                        x = d[(d.scheduler == lab) & (d.case == c)].iloc[0]
                        cells.append(f"{x.excess_pct:.1f} ({x.idle_pct:.0f}%)")
                    f.write(f"| {lab} | " + " | ".join(cells) + " |\n")
                err = d.equal_model_error_pct
                f.write(f"\nEqual-cost model (2020 assumption) vs measured costs, makespan prediction error over all "
                        f"schedulers and cases: {err.min():+.1f}% to {err.max():+.1f}% (median {err.median():+.1f}%).\n")
                cv = " / ".join(f"{d[d.case == c].unit_cost_cv.iloc[0]:.2f}" for c in cases)
                f.write(f"\nUnit-cost CV across units (same case order): {cv}\n")


def figure(df):
    cases = ["calm, 24-h window", "storm 25 mm, peak 24-h window", "storm 250 mm, peak 24-h window",
             "storm 250 mm, run total"]
    col = dict(zip(cases, ["#0072B2", "#E69F00", "#009E73", "#D55E00"]))
    mk = dict(zip(cases, ["o", "s", "^", "D"]))
    grans = ["segment", "reach", "clustered T=1000"]
    labs = [s[0] for s in SCHEDULERS]
    plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.color": "#e6e6e6", "figure.facecolor": "white"})
    fig, axs = plt.subplots(1, 3, figsize=(9.0, 4.6), sharey=False)
    y = np.arange(len(labs))[::-1]
    for ax, gran in zip(axs, grans):
        for k, c in enumerate(cases):
            d = df[(df.granularity == gran) & (df.P == 36) & (df.case == c)].set_index("scheduler").loc[labs]
            ax.scatter(d.excess_pct, y + (k - 1.5) * 0.15, color=col[c], marker=mk[c], s=16, label=c, zorder=3)
        ax.set_yticks(y)
        ax.set_yticklabels(labs if gran == "segment" else [""] * len(labs), fontsize=7)
        ax.set_xscale("symlog", linthresh=1)
        ax.set_xlim(0, 300)
        ax.set_xticks([0, 1, 10, 100])
        ax.set_xticklabels(["0", "1", "10", "100"])
        ax.set_title({"segment": "segments", "reach": "reaches (summed costs)",
                      "clustered T=1000": "clustered subnetworks, T = 1000"}[gran], fontsize=8.5, fontweight="bold")
        ax.set_xlabel("makespan above lower bound (%)")
    fig.suptitle("Potomac (16,454 segments), 36 cores, measured MC costs", fontsize=9, fontweight="bold")
    h, l = axs[0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=2, bbox_to_anchor=(0.6, -0.12), fontsize=7.5, frameon=False)
    fig.tight_layout()
    for ext in ("png", "pdf"):
        fig.savefig(OUT / f"fig_cost_scheduling.{ext}", dpi=200, bbox_inches="tight")


if __name__ == "__main__":
    main()
