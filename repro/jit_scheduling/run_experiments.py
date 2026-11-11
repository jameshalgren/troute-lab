# /// script
# requires-python = "==3.12.*"
# dependencies = ["numpy==2.5.4", "numba==0.68.1", "netCDF4==1.7.5.1.post1", "pandas==3.0.6"]
# ///
"""Run the scheduling experiment on the NWM v3.1.6 CONUS RouteLink.

    uv run run_experiments.py            # main grid + sensitivities (see README for run time)
    uv run run_experiments.py --quick    # Rio Grande only, few core counts

Input: ../network_stats/data/RouteLink_CONUS.nc (fetch with ../network_stats/fetch_data.py;
SHA-256 pinned there). Outputs in results/: results.csv, overhead_sensitivity.csv,
order_sensitivity.csv, busy_profile.csv, summary.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import jitsched as J

HERE = Path(__file__).resolve().parent
RL = HERE.parent / "network_stats" / "data" / "RouteLink_CONUS.nc"
OUT = HERE / "results"
THRESHOLDS = (100, 1000, 10000, 100000)
CORES = (1, 2, 4, 8, 16, 36, 64, 128, 1024, np.inf)
# RouteLink `link` ids of the network outlets (names checked 2026-10-29 against the USGS NHDPlus
# V2 `gnis_name` of the outlet COMID, see README)
SCOPE_OUTLETS = {
    "Mississippi": [22811611],
    "RioGrande": [626220],
    "LowerColorado_TX": [3766342],           # "Colorado River", Texas: the t-route test/LowerColorado_TX network
    "Brazos": [3125212],                      # "Brazos River"
    "LowerColorado_TX+Brazos": [3766342, 3125212],   # two independent networks routed together
    "Trinity": [1523997],                     # "Trinity River"
    # Potomac: all 16,454 segments upstream of NWM feature 4539621 (the river's mouth at
    # Chesapeake Bay; a network outlet in v3.1.6). Same network as ../short_ts_switch
    # (potomac_storm) and the planned per-segment cost measurements.
    "Potomac": [4539621],
}
ALL_SCOPES = ["Mississippi", "CONUS", "RioGrande", "LowerColorado_TX", "Brazos",
              "LowerColorado_TX+Brazos", "Trinity", "Potomac"]
SENS_SCOPES = ["Mississippi", "CONUS", "RioGrande", "LowerColorado_TX", "LowerColorado_TX+Brazos", "Potomac"]
PROFILE_SCOPES = ("Mississippi", "CONUS", "LowerColorado_TX", "Potomac")
POLICIES = ("opp_fifo", "opp_rounds", "jit", "jit_list", "opp_lrp", "jit_release", "work_steal")
WS_LIMIT = 4e8          # skip work stealing when units x cores exceeds this (victim scans are O(P))


def skip(G, pol, P):
    if pol != "work_steal":
        return False
    pn = G.n if not np.isfinite(P) else min(P, G.n)
    return G.n * pn > WS_LIMIT


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


class Scopes:
    """Builds the work-unit graphs of every granularity for one scope (set of networks)."""

    def __init__(self, D, S, name, outlet_ids):
        self.D, self.S, self.name = D, S, name
        if outlet_ids is None:
            self.seg_mask = np.ones(len(D["down"]), bool)
            self.reach_mask = np.ones(len(D["rcost"]), bool)
            self.net_ids = None
        else:
            o = np.array([np.nonzero(D["link"] == i)[0][0] for i in outlet_ids])
            self.seg_mask = np.isin(D["net"], o)
            self.reach_mask = np.isin(D["rnet"], o)
            self.net_ids = set(int(x) for x in o)
        self.n_seg = int(self.seg_mask.sum())
        nets, cnt = np.unique(D["net"][self.seg_mask], return_counts=True)
        self.net_cost = cnt.astype(np.int64)
        self.n_nets = len(nets)
        self._seg = self._reach = None

    def sub_ids(self, T):
        S = self.S[T]
        if self.net_ids is None:
            return np.arange(len(S["order"]))
        return np.nonzero(np.isin(S["net"], list(self.net_ids)))[0]

    def graph(self, gran, T=None, shuffle_seed=None):
        if gran == "segment":
            if self._seg is None:
                self._seg = J.subset(J.segment_graph(self.D), self.seg_mask)
            return self._seg
        if gran in ("reach_unit", "reach_cost"):
            return J.subset(J.reach_graph(self.D, gran == "reach_unit"), self.reach_mask)
        mode = {"subnet": "subnet", "cluster_old": "old", "cluster_bin": "bin"}[gran]
        return J.subnetwork_graph(self.S[T], self.sub_ids(T), mode, T, shuffle_seed)

    def network_graph(self):
        n = self.n_nets
        return J.Graph(self.net_cost, np.zeros(n, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64))


def write_merged(df, name, scopes_run):
    """Write df to results/name, keeping rows of earlier runs for scopes not in scopes_run."""
    f = OUT / name
    if f.exists():
        old = pd.read_csv(f)
        old = old[~old.scope.isin(scopes_run)]
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(f, index=False)


def one(G, policy, P, scope, o=0.0, b=0.0, serial=None):
    pol = "lpt_independent" if policy == "by_network" else policy
    sch = J.schedule(G, pol, P, overhead=o, barrier=b)
    m = J.summarize(G, sch, P, overhead=o, serial_work=serial)
    lb = max(m["lb_work"], m["lb_cp"])
    assert m["makespan"] >= lb - 1e-9, (policy, P, m)
    m["lb"] = lb
    m["efficiency_vs_lb"] = lb / m["makespan"]
    return m, sch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--scopes", nargs="*", default=None, help=f"subset of {ALL_SCOPES}; results of other scopes are kept")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    D, S = J.load_cached(HERE / "data", RL, THRESHOLDS)
    log("loaded", len(D["down"]), "segments")
    scopes = {"CONUS": Scopes(D, S, "CONUS", None)}  # noqa
    for k, v in SCOPE_OUTLETS.items():
        scopes[k] = Scopes(D, S, k, v)
    cores = (1, 4, 36, np.inf) if a.quick else CORES
    use = ["RioGrande"] if a.quick else (a.scopes or ALL_SCOPES)

    gran_list = [("segment", None), ("reach_unit", None), ("reach_cost", None)]
    for T in THRESHOLDS:
        gran_list += [("subnet", T), ("cluster_old", T), ("cluster_bin", T)]
    prof_cfg = {("segment", None), ("reach_cost", None), ("cluster_bin", 1000), ("cluster_old", 1000)}
    prof_rows, rows = [], []
    for sn in use:
        sc = scopes[sn]
        log("scope", sn, sc.n_seg, "segments", sc.n_nets, "networks")
        for gran, T in gran_list:
            G = sc.graph(gran, T)
            log("  ", gran, T, "units", G.n)
            for P in cores:
                for pol in POLICIES:
                    if skip(G, pol, P):
                        continue
                    m, sch = one(G, pol, P, sn)
                    rows.append(dict(scope=sn, granularity=gran, T=T or 0, policy=pol, P=P, overhead=0.0, **m))
                    if (gran, T) in prof_cfg and P in (36, 128) and sn in PROFILE_SCOPES:
                        bb = J.binned_busy(sch["start"], sch["dur"], m["makespan"] * J.SCALE, 400)
                        prof_rows += [dict(scope=sn, granularity=gran, T=T or 0, policy=pol, P=P, bin=i,
                                           t_frac=(i + 0.5) / 400, busy=float(x)) for i, x in enumerate(bb)]
        Gn = sc.network_graph()
        for P in cores:                   # by-network baseline (independent of granularity)
            m, sch = one(Gn, "by_network", P, sn, serial=sc.n_seg)
            rows.append(dict(scope=sn, granularity="network", T=0, policy="by_network", P=P, overhead=0.0, **m))
            if P in (36, 128) and sn in PROFILE_SCOPES:
                bb = J.binned_busy(sch["start"], sch["dur"], m["makespan"] * J.SCALE, 400)
                prof_rows += [dict(scope=sn, granularity="network", T=0, policy="by_network", P=P, bin=i,
                                   t_frac=(i + 0.5) / 400, busy=float(x)) for i, x in enumerate(bb)]
    write_merged(pd.DataFrame(rows), "results.csv", use)
    if prof_rows:
        write_merged(pd.DataFrame(prof_rows), "busy_profile.csv", use)
    log("main grid done", len(rows), "rows")

    # ---- sensitivity 1: per-unit dispatch overhead (and a per-stride barrier cost for JIT)
    srows = []
    ovs = (0.0, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0)
    s_use = [x for x in use if x in SENS_SCOPES]
    s_P = (36,) if a.quick else (36, 128)
    s_gran = [("segment", None), ("reach_cost", None), ("cluster_bin", 1000), ("cluster_bin", 10000)]
    for sn in s_use:
        sc = scopes[sn]
        for gran, T in s_gran:
            G = sc.graph(gran, T)
            for P in s_P:
                for o in ovs:
                    for pol in POLICIES + ("jit_barrier",):
                        if skip(G, pol, P):
                            continue
                        m, _ = one(G, pol, P, sn, o=o, b=o if pol == "jit_barrier" else 0.0, serial=sc.n_seg)
                        srows.append(dict(scope=sn, granularity=gran, T=T or 0, policy=pol, P=P, overhead=o, **m))
        Gn = sc.network_graph()
        for P in s_P:
            for o in ovs:
                m, _ = one(Gn, "by_network", P, sn, o=o, serial=sc.n_seg)
                srows.append(dict(scope=sn, granularity="network", T=0, policy="by_network", P=P, overhead=o, **m))
        log("overhead sens", sn)
    write_merged(pd.DataFrame(srows), "overhead_sensitivity.csv", s_use)

    # ---- sensitivity 2: order of subnetworks inside an order (real code: dict/set order)
    orows = []
    n_seeds = 2 if a.quick else 5
    for sn in s_use:
        sc = scopes[sn]
        for T in (1000, 10000):
            for mode in ("cluster_old", "cluster_bin"):
                for seed in [None] + list(range(n_seeds)):
                    G = sc.graph(mode, T, shuffle_seed=seed)
                    for P in (36, 128):
                        for pol in POLICIES:
                            m, _ = one(G, pol, P, sn)
                            orows.append(dict(scope=sn, granularity=mode, T=T, seed=-1 if seed is None else seed,
                                              policy=pol, P=P, **m))
        log("order sens", sn)
    write_merged(pd.DataFrame(orows), "order_sensitivity.csv", s_use)

    info = {n: dict(segments=s.n_seg, networks=s.n_nets) for n, s in scopes.items()}
    info["subnetworks"] = {str(T): dict(n=int(len(S[T]["order"])), max_order=int(S[T]["order"].max())) for T in THRESHOLDS}
    (OUT / "summary.json").write_text(json.dumps(info, indent=1))
    log("done")


if __name__ == "__main__":
    main()
