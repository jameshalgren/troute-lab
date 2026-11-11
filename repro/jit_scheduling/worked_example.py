# /// script
# requires-python = "==3.12.*"
# dependencies = ["numpy==2.5.4", "numba==0.68.1", "netCDF4==1.7.5.1.post1", "matplotlib==3.11.2"]
# ///
"""Tiny worked example (15 segments, unit cost, 3 cores): schedules under
opportunistic (FIFO and longest-remaining-path-first) and just-in-time scheduling.

    uv run worked_example.py   ->  results/fig_worked_example.{png,pdf}, results/worked_example.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Rectangle

import jitsched as J

OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)
P = 3

# name: (downstream, x, y); x = -distance from outlet, y = drawing row
TREE = {
    "m0": (None, 0, 0), "m1": ("m0", -1, 0), "m2": ("m1", -2, 0), "m3": ("m2", -3, 0),
    "m4": ("m3", -4, 0), "m5": ("m4", -5, 0),
    "a1": ("m3", -4, 1), "a2": ("a1", -5, 1), "a3": ("a2", -6, 1),
    "b1": ("m1", -2, -1), "b2": ("b1", -3, -1),
    "c1": ("m2", -3, 2), "c2": ("c1", -4, 2), "c3": ("c2", -5, 2), "c4": ("c3", -6, 2),
}
names = list(TREE)
ix = {k: i for i, k in enumerate(names)}


def depth(k):
    return 0 if TREE[k][0] is None else 1 + depth(TREE[k][0])


dep = np.array([depth(k) for k in names])
src = np.array([ix[k] for k in names if TREE[k][0]])
dst = np.array([ix[TREE[k][0]] for k in names if TREE[k][0]])
G = J.Graph(np.ones(len(names), np.int64), dep.astype(np.int64), src.astype(np.int64), dst.astype(np.int64))

POL = [("opp_rounds", "2020-style rounds: every ready segment, barrier after each round"),
       ("opp_fifo", "Naive first-ready: ready segments start as cores free up"),
       ("jit", "JIT strides: furthest from the outlet first, barrier after each stride"),
       ("opp_lrp", "JIT priority without barriers (Hu's rule): furthest-from-outlet ready segment first")]
sched = {}
rows = []
for pol, label in POL:
    s = J.schedule(G, pol, P)
    m = J.summarize(G, s, P)
    sched[pol] = (s, m)
    for i, k in enumerate(names):
        rows.append(dict(policy=pol, node=k, distance_from_outlet=int(dep[i]),
                         start_cycle=int(s["start"][i] // J.SCALE), core=int(s["core"][i]) + 1))
    print(f"{pol:9s} P={P}: makespan {m['makespan']:.0f} cycles, busy {m['util']*100:.0f}%, "
          f"final stretch with one core busy: {m['tail_len']:.0f} cycles; lower bounds "
          f"work/P={m['lb_work']:.1f}, critical path={m['lb_cp']:.0f}")
_s = J.schedule(G, "opp_lrp", np.inf)
STRUCT = J.summarize(G, _s, np.inf)["tail_len"]
print(f"structural one-core tail (Hu's rule, unlimited cores): {STRUCT:.0f} cycles")
with open(OUT / "worked_example.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

# ------------------------------------------------------------------ figure
plt.rcParams.update({"font.size": 9, "axes.titlesize": 9.5, "axes.titleweight": "bold",
                     "font.family": "DejaVu Sans", "figure.facecolor": "white", "axes.facecolor": "white"})
cmap = plt.get_cmap("Blues")
dmax = dep.max()
col = {k: cmap(0.18 + 0.72 * dep[ix[k]] / dmax) for k in names}
txt = {k: ("white" if dep[ix[k]] / dmax > 0.45 else "#111111") for k in names}
ORANGE = "#E69F00"

fig = plt.figure(figsize=(7.2, 9.0))
gs = fig.add_gridspec(5, 1, height_ratios=[1.25, 1, 1, 1, 1], hspace=0.85)
ax = fig.add_subplot(gs[0])
for k, (d, x, y) in TREE.items():
    if d:
        ax.plot([x, TREE[d][1]], [y, TREE[d][2]], color="#555555", lw=1.2, zorder=1)
for k, (d, x, y) in TREE.items():
    ax.scatter([x], [y], s=520, color=col[k], edgecolor="#222222", lw=1.8 if k.startswith("m") else 0.6, zorder=2)
    ax.text(x, y, k, ha="center", va="center", color=txt[k], fontsize=8.5, zorder=3)
ax.annotate("outlet", (0.25, 0), xytext=(0.55, 0), va="center", fontsize=9, arrowprops=dict(arrowstyle="-", color="#555"))
ax.set_xlim(-6.7, 1.3)
ax.set_ylim(-1.6, 2.6)
ax.axis("off")
ax.set_title("(a) A 15-segment network, flow to the right. Shade = distance from the outlet\n"
             "(darker = further away, run first by JIT). Heavy ring = mainstem.", loc="left", fontsize=9)

Mmax = max(m["makespan"] for _, m in sched.values())
for r, (pol, label) in enumerate(POL):
    a = fig.add_subplot(gs[r + 1])
    s, m = sched[pol]
    M = m["makespan"]
    tail = m["tail_len"]
    a.add_patch(Rectangle((M - tail, -0.5), tail, P, color=ORANGE, alpha=0.18, lw=0, zorder=0))
    for i, k in enumerate(names):
        t0 = s["start"][i] / J.SCALE
        c = int(s["core"][i])
        a.add_patch(Rectangle((t0, c - 0.42), 1, 0.84, facecolor=col[k], edgecolor="white", lw=1.2, zorder=2))
        a.text(t0 + 0.5, c, k, ha="center", va="center", color=txt[k], fontsize=8.5, zorder=3)
    a.axvline(M, color="#222222", lw=1, ls=(0, (4, 2)))
    a.set_xlim(0, Mmax + 0.3)
    a.set_ylim(-0.55, P - 0.45)
    a.set_yticks(range(P))
    a.set_yticklabels([f"core {c+1}" for c in range(P)])
    a.set_xticks(range(0, int(Mmax) + 1))
    a.tick_params(length=0)
    for sp in ("top", "right", "left"):
        a.spines[sp].set_visible(False)
    a.set_xlabel("cycle" if r == len(POL) - 1 else "")
    a.set_title(f"({'bcde'[r]}) {label}\n{M:.0f} cycles; cores busy {m['util']*100:.0f}% of the time; "
                f"last {tail:.0f} cycle{'s' if tail != 1 else ''} on one core", loc="left", fontsize=9)
fig.text(0.01, 0.005, f"{P} cores, equal unit cost, zero dispatch overhead. Orange band: final stretch with only one core busy\n"
         f"(with unlimited cores it is still {STRUCT:.0f} cycles: m2-m1-m0 cannot overlap). "
         f"Lower bounds: work/P = {sched['jit'][1]['lb_work']:.0f} cycles, critical path = {sched['jit'][1]['lb_cp']:.0f} cycles.",
         fontsize=7.5, color="#333333")
fig.subplots_adjust(left=0.08, right=0.985, bottom=0.085, top=0.95)
for ext in ("png", "pdf"):
    fig.savefig(OUT / f"fig_worked_example.{ext}", dpi=200)
print("wrote", OUT / "fig_worked_example.png")
