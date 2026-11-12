# /// script
# requires-python = "==3.12.*"
# dependencies = ["numpy==2.5.4", "numba==0.68.1", "netCDF4==1.7.5.1.post1", "pandas==3.0.6"]
# ///
"""Validate the schedules and the graph/decomposition code.

    uv run check.py

Tests (all must pass; any failure raises AssertionError):
 1. Independent schedule validator (plain numpy, shares no code with the numba kernels):
    dependencies respected, no core double-booked, core ids in range, JIT strides do not
    overlap and are ordered, makespan >= both lower bounds (total work / P, critical path).
 2. Random in-trees and random DAGs, all policies, several core counts, with overhead.
 3. Brute-force optimum on tiny unit-cost in-trees: longest-remaining-path-first is
    optimal (Hu's result for unit-time in-trees); no policy beats the optimum.
 4. Real network against ../network_stats/expected/expected.json (segments, reaches,
    networks, Mississippi segments / reaches / longest paths).
 5. The numba replica of T-Route's build_subnetworks equals a literal pure-Python
    transliteration of the T-Route code on the Rio Grande network and random forests.
 6. Full-size schedules (Rio Grande all granularities; Mississippi segments) validated.
"""
from __future__ import annotations

import itertools
import json
from collections import deque
from pathlib import Path

import numpy as np

import jitsched as J

HERE = Path(__file__).resolve().parent
RL = HERE.parent / "network_stats" / "data" / "RouteLink_CONUS.nc"
EXPECTED = HERE.parent / "network_stats" / "expected" / "expected.json"


# ------------------------------------------------------------------------------ 1
def validate(G, sch, P, policy, overhead=0.0, barrier=0.0):
    start, dur, core, Pn = sch["start"], sch["dur"], sch["core"], sch["Pn"]
    fin = start + dur
    assert (start >= 0).all()
    assert (dur == G.cost * J.SCALE + int(round(overhead * J.SCALE))).all()
    # dependencies
    if len(G.esrc):
        assert (start[G.edst] >= fin[G.esrc]).all(), "dependency violated"
    # cores in range and never double-booked
    assert core.min() >= 0 and core.max() < Pn, "core id out of range"
    o = np.lexsort((start, core))
    c, s, f = core[o], start[o], fin[o]
    same = c[1:] == c[:-1]
    assert (s[1:][same] >= f[:-1][same]).all(), "core double-booked"
    # at most Pn units run at any instant (redundant with the check above, cheap)
    t = np.concatenate([start * 2 + 1, fin * 2])
    t.sort()
    run = np.cumsum(np.where(t & 1, 1, -1))
    assert run.max() <= Pn
    # JIT: strides are disjoint in time and ordered furthest first
    if policy in ("jit", "jit_list", "jit_barrier", "opp_rounds"):
        st = sch["stride"]
        for a, b in zip(np.unique(st)[::-1][:-1], np.unique(st)[::-1][1:]):
            assert fin[st == a].max() + int(round(barrier * J.SCALE)) <= start[st == b].min() + 0, "stride barrier"
    # lower bounds
    M = fin.max()
    sp, si, indeg = G.csr()
    order, cnt = J.topo_order(sp, si, indeg)
    assert cnt == G.n
    cp = J.bottom_level(order, dur, sp, si).max()
    assert M >= cp, "makespan below critical path"
    if np.isfinite(P):
        assert M * P >= dur.sum(), "makespan below total work / P"
    return M


# ------------------------------------------------------------------------------ 2
def random_intree(rng, n):
    down = np.full(n, -1)
    for u in range(1, n):
        down[u] = rng.integers(0, u)          # parent has a smaller index: acyclic
    # relabel so the outlet is not always 0 and indices are shuffled
    perm = rng.permutation(n)
    inv = np.empty(n, int); inv[perm] = np.arange(n)
    d2 = np.full(n, -1)
    for u in range(n):
        if down[u] >= 0:
            d2[perm[u]] = perm[down[u]]
    depth = np.zeros(n, int)
    order = np.argsort(inv)                    # parents (small original index) first
    for u in order:
        if d2[u] >= 0:
            depth[u] = depth[d2[u]] + 1
    src = np.nonzero(d2 >= 0)[0]
    return d2, depth, src


def test_random():
    rng = np.random.default_rng(1)
    nchk = 0
    for trial in range(60):
        n = int(rng.integers(2, 60))
        d2, depth, src = random_intree(rng, n)
        cost = rng.integers(1, 6, n) if trial % 2 else np.ones(n, int)
        G = J.Graph(cost.astype(np.int64), depth.astype(np.int64), src.astype(np.int64), d2[src].astype(np.int64))
        for P in (1, 2, 3, 5, 100, np.inf):
            for o in (0.0, 0.37):
                for pol in ("opp_fifo", "opp_lrp", "opp_rounds", "jit", "jit_list", "jit_barrier", "jit_release",
                            "work_steal", "lpt_independent"):
                    if pol == "lpt_independent":
                        Gi = J.Graph(G.cost, np.zeros(n, np.int64), np.zeros(0, np.int64), np.zeros(0, np.int64))
                        sch = J.schedule(Gi, pol, P, overhead=o)
                        validate(Gi, sch, P, pol, o)
                    else:
                        b = 0.5 if pol == "jit_barrier" else 0.0
                        sch = J.schedule(G, pol, P, overhead=o, barrier=b)
                        validate(G, sch, P, pol, o, b)
                        if pol == "opp_rounds":       # rounds = ASAP levels, computed independently
                            lev = np.zeros(n, int)
                            for _ in range(n):
                                np.maximum.at(lev, d2[src], lev[src] + 1)
                            assert (sch["stride"] == lev.max() - lev).all(), "rounds != ASAP levels"
                    nchk += 1
    # general DAG (clusters): random layered DAG with multi-parent edges
    for trial in range(30):
        L = int(rng.integers(2, 6)); w = rng.integers(1, 6, L)
        ids = np.cumsum(np.r_[0, w]); n = ids[-1]
        stride = np.repeat(np.arange(L)[::-1], w)               # layer 0 = furthest = highest stride
        es, ed = [], []
        for l in range(L - 1):
            for u in range(ids[l], ids[l + 1]):
                for v in rng.choice(np.arange(ids[l + 1], ids[l + 2]), size=1 + rng.integers(0, 2)):
                    es.append(u); ed.append(v)
        G = J.Graph(rng.integers(1, 9, n).astype(np.int64), stride.astype(np.int64),
                    np.array(es, np.int64), np.array(ed, np.int64))
        for P in (1, 2, 4, np.inf):
            for pol in ("opp_fifo", "opp_lrp", "opp_rounds", "jit", "jit_list", "jit_release", "work_steal"):
                validate(G, J.schedule(G, pol, P), P, pol)
                nchk += 1
    print(f"[2] random trees / DAGs: {nchk} schedules validated")


# ------------------------------------------------------------------------------ 3
def brute_optimum(down, P):
    """Exact minimum makespan for unit-cost in-tree by BFS over sets of finished nodes."""
    n = len(down)
    need = [0] * n
    for u in range(n):
        if down[u] >= 0:
            need[down[u]] |= 1 << u
    full = (1 << n) - 1
    frontier = {0}
    t = 0
    while True:
        if full in frontier:
            return t
        nxt = set()
        for done in frontier:
            ready = [u for u in range(n) if not done >> u & 1 and need[u] & ~done == 0]
            k = min(P, len(ready))
            for comb in itertools.combinations(ready, k):
                m = done
                for u in comb:
                    m |= 1 << u
                nxt.add(m)
        frontier = nxt
        t += 1


def test_hu():
    rng = np.random.default_rng(7)
    n_ok = 0
    for trial in range(120):
        n = int(rng.integers(3, 13))
        d2, depth, src = random_intree(rng, n)
        G = J.Graph(np.ones(n, np.int64), depth.astype(np.int64), src.astype(np.int64), d2[src].astype(np.int64))
        for P in (2, 3):
            opt = brute_optimum(list(d2), P)
            got = {}
            for pol in ("opp_fifo", "opp_lrp", "opp_rounds", "jit", "jit_list", "jit_release", "work_steal"):
                sch = J.schedule(G, pol, P)
                got[pol] = validate(G, sch, P, pol) // J.SCALE
                assert got[pol] >= opt, ("beat the optimum?", pol, got, opt)
            assert got["opp_lrp"] == opt, ("LRP not optimal on unit in-tree", got, opt, list(d2))
            n_ok += 1
    print(f"[3] brute-force optimum: {n_ok} (tree, P) cases; opp_lrp optimal in all, none beat the optimum")


# ------------------------------------------------------------------------------ 4/5/6
def pure_python_build_subnetworks(connections, rconn, min_size):
    """Literal transliteration of NOAA-OWP/t-route nhd_network.build_subnetworks
    (commit 12a8eae0, L691-L771) with headwaters(N) = N.keys() - chain(N.values())."""
    def headwaters(N):
        return N.keys() - itertools.chain.from_iterable(N.values())
    sources = headwaters(rconn)
    all_hws = headwaters(connections)
    master = {}
    for net in sources:
        new_sources = {net}
        subnetworks = {}
        group_order = 0
        while new_sources:
            rv = {}
            for h in new_sources:
                reachable = set()
                Q = deque([(h, 0)])
                stop_depth = 1000000
                while Q:
                    x, y = Q.popleft()
                    reachable.add(x)
                    rx = rconn.get(x, ())
                    us_depth = y + 1 if len(rx) > 1 else y
                    if len(reachable) > min_size:
                        stop_depth = y
                    if us_depth <= stop_depth:
                        Q.extend(zip(rx, [us_depth] * len(rx)))
                rv[h] = reachable
            new_sources = set()
            for tw, seg in rv.items():
                c = {key: connections[key] for key in seg}
                sub_hws = headwaters(c)
                srcs = sub_hws - all_hws
                new_sources.update(srcs)
                rv[tw].difference_update(srcs)
            subnetworks[group_order] = rv
            group_order += 1
        master[net] = subnetworks
    return master


def tr_reverse_network(N):
    """Literal copy of t-route nhd_network.reverse_network (@12a8eae0 L111-L131)."""
    from collections import defaultdict
    rg = defaultdict(list)
    for src, dst in N.items():
        rg[src]
        for n in dst:
            rg[n].append(src)
    rg.default_factory = None
    return rg


def tr_connections(link, down):
    """connections as t-route builds them: dict keyed by feature id in ascending id order
    (the frame is sorted by key before extract_connections), value = [downstream id]."""
    o = np.argsort(link)
    return {int(link[u]): ([int(link[down[u]])] if down[u] >= 0 else []) for u in o}


def reference_subnets(link, down, min_size):
    connections = tr_connections(link, down)
    rconn = tr_reverse_network(connections)
    ref = pure_python_build_subnetworks(connections, rconn, min_size)
    out = {}
    for net, orders in ref.items():
        for k, rv in orders.items():
            for tw, seg in rv.items():
                out[(k, tw)] = frozenset(seg)
    return out


def replica_subnets(link, down, min_size):
    """Our pipeline: J.upstream_csr (the function load_network uses) + J._build_subnetworks."""
    n = len(down)
    up_ptr, up_idx = J.upstream_csr(link, down)
    outlets = np.nonzero(down < 0)[0].astype(np.int64)
    sub, so, stw = J._build_subnetworks(up_ptr, up_idx, outlets, int(min_size), n)
    order = np.argsort(sub, kind="stable")
    bounds = np.searchsorted(sub[order], np.arange(len(so) + 1))
    return {(int(so[s]), int(link[stw[s]])): frozenset(link[order[bounds[s]:bounds[s + 1]]].tolist())
            for s in range(len(so))}


def compare_subnets(link, down, min_size):
    ref = reference_subnets(link, down, min_size)
    mine = replica_subnets(link, down, min_size)
    assert mine.keys() == ref.keys(), "different subnetwork set"
    for k in mine:
        assert mine[k] == ref[k], ("different membership", k)
    return len(mine)


def test_subnets():
    rng = np.random.default_rng(3)
    tot = 0
    for trial in range(40):
        n = int(rng.integers(5, 300))
        d2, _, _ = random_intree(rng, n)
        cut = rng.random(n) < 0.03                      # a forest
        d2 = np.where(cut, -1, d2)
        link = rng.permutation(n).astype(np.int64) * 7 + 1000   # feature ids unrelated to row order
        for ms in (1, 2, 5, 17):
            tot += compare_subnets(link, d2, ms)
    # the test must be able to see the upstream order: with row-order upstreams the
    # replica has to disagree with T-Route somewhere on these forests
    disagree = 0
    for trial in range(40):
        n = int(rng.integers(30, 300))
        d2, _, _ = random_intree(rng, n)
        link = rng.permutation(n).astype(np.int64) * 7 + 1000
        ref = reference_subnets(link, d2, 5)
        up_ptr = np.zeros(n + 1, np.int64)
        np.cumsum(np.bincount(d2[d2 >= 0], minlength=n), out=up_ptr[1:])
        src = np.nonzero(d2 >= 0)[0]
        up_idx = src[np.argsort(d2[src], kind="stable")].astype(np.int64)    # row order (wrong)
        sub, so, stw = J._build_subnetworks(up_ptr, up_idx, np.nonzero(d2 < 0)[0].astype(np.int64), 5, n)
        wrong = {(int(so[s]), int(link[stw[s]])): frozenset(link[sub == s].tolist()) for s in range(len(so))}
        disagree += wrong != ref
    assert disagree > 0, "test 5 cannot detect upstream ordering"
    print(f"[5a] replica == literal T-Route code on random forests with shuffled feature ids "
          f"({tot} subnetworks); row-order upstreams would fail in {disagree} of 40 trees")


def test_pr26_example():
    """The worked example in CIROH-UA/t-route PR #26: target 1000, subnetworks 300, 340, 1400, 300.
    Old rule -> clusters 2040 and 300; bin packing -> 940 and 1400."""
    sizes = np.array([300, 340, 1400, 300])
    for fn, want in ((J._cluster_old, [2040, 300]), (J._cluster_bin, [940, 1400])):
        cl = fn(sizes, 1000)
        got = sorted(np.bincount(cl, weights=sizes).astype(int).tolist(), key=lambda v: (v != want[0], v))
        assert sorted(got) == sorted(want), (fn.__name__, got, want)
    print("[5c] clustering rules reproduce the PR #26 worked example (old: 2040/300, bin packing: 940/1400)")


def test_hu_priority_is_distance():
    """On an in-forest the longest-path-first priority (bottom level) is exactly the unit's
    cost-weighted distance from its outlet, itself included (Hu's level for unit costs)."""
    rng = np.random.default_rng(11)
    for trial in range(50):
        n = int(rng.integers(2, 200))
        d2, depth, src = random_intree(rng, n)
        d2 = np.where(rng.random(n) < 0.05, -1, d2)            # a forest
        src = np.nonzero(d2 >= 0)[0]
        cost = rng.integers(1, 9, n).astype(np.int64)
        G = J.Graph(cost, np.zeros(n, np.int64), src.astype(np.int64), d2[src].astype(np.int64))
        sp, si, indeg = G.csr()
        order, _ = J.topo_order(sp, si, indeg)
        bl = J.bottom_level(order, cost, sp, si)
        for u in range(n):                                      # walk to the outlet
            dist, v = 0, u
            while v >= 0:
                dist += cost[v]
                v = d2[v]
            assert bl[u] == dist, "priority != distance from outlet"
    print("[3b] longest-path-first priority == cost-weighted distance from the outlet on in-forests (Hu's level)")


def test_new_policies():
    """JIT timetable reaches the critical path with unlimited cores; estimated-cost mode:
    est = true costs reproduces the default exactly; cost-blind policies ignore est;
    any est gives a valid schedule of the true durations."""
    rng = np.random.default_rng(5)
    for trial in range(40):
        n = int(rng.integers(2, 120))
        d2, depth, src = random_intree(rng, n)
        cost = rng.integers(1, 9, n).astype(np.int64)
        G = J.Graph(cost, depth.astype(np.int64), src.astype(np.int64), d2[src].astype(np.int64))
        cp = J.critical_path(G)
        s = J.schedule(G, "jit_release", np.inf)
        assert (s["start"] + s["dur"]).max() == cp, "JIT timetable misses the critical path with unlimited cores"
        est = rng.integers(1, 9, n)
        for P in (1, 3, 7):
            for pol in ("opp_fifo", "opp_lrp", "opp_rounds", "jit", "jit_list", "jit_release", "work_steal"):
                a = J.schedule(G, pol, P)
                b = J.schedule(G, pol, P, est_cost=cost)
                assert (a["start"] == b["start"]).all(), (pol, "est=true differs")
                e = J.schedule(G, pol, P, est_cost=est)
                validate(G, e, P, pol)
                if pol in ("opp_fifo", "work_steal"):
                    assert (a["start"] == e["start"]).all(), (pol, "cost-blind policy used est")
    # cost-aware dynamic with exact estimates == Hu's rule with exact costs
    for trial in range(30):
        n = int(rng.integers(2, 120))
        d2, depth, src = random_intree(rng, n)
        cost = rng.integers(1, 9, n).astype(np.int64)
        G = J.Graph(cost, depth.astype(np.int64), src.astype(np.int64), d2[src].astype(np.int64))
        for P in (2, 5):
            a = J.schedule(G, "opp_lrp", P)
            b = J.schedule(G, "opp_lrp_dyn", P)
            assert (a["start"] == b["start"]).all(), "cost-aware dynamic with exact estimates != Hu"
            e = J.schedule(G, "opp_lrp_dyn", P, est_cost=np.ones(n, np.int64))
            validate(G, e, P, "opp_lrp_dyn")
    print("[2b] JIT timetable = critical path at unlimited cores; est_cost hook: est=true identical, "
          "cost-blind policies unaffected, arbitrary estimates valid")


def main():
    test_hu_priority_is_distance()
    test_new_policies()
    test_pr26_example()
    test_random()
    test_hu()
    test_subnets()
    D, S = J.load_cached(HERE / "data", RL, (1000,))
    exp = json.loads(EXPECTED.read_text())["domains"]["CONUS"]
    n = len(D["down"])
    assert n == exp["n_segments"] and int((D["down"] < 0).sum()) == exp["n_networks"]
    assert len(D["rcost"]) == exp["n_reaches"]
    mis = int(np.nonzero(D["link"] == exp["largest"]["outlet_feature_id"])[0][0])
    m = D["net"] == mis
    assert int(m.sum()) == exp["largest"]["n_segments"]
    assert int(D["depth"][m].max()) + 1 == exp["largest"]["longest_path_segments"]
    rm = D["rnet"] == mis
    assert int(rm.sum()) == exp["largest"]["n_reaches"]
    assert int(D["rdepth"][rm].max()) + 1 == exp["largest"]["longest_path_reaches"]
    # reach graph: every segment in exactly one reach; unit-cost critical path = longest reach path
    assert D["rcost"].sum() == n
    print("[4] segments, networks, reaches, Mississippi size / longest paths match network_stats/expected.json")

    rg = int(np.nonzero(D["link"] == 626220)[0][0])
    seg_mask = D["net"] == rg
    idx = np.cumsum(seg_mask) - 1
    d = D["down"][seg_mask]
    d = np.where(d >= 0, idx[np.clip(d, 0, n - 1)], -1)
    lk = D["link"][seg_mask]
    for ms in (1000, 10000):
        k = compare_subnets(lk, d, ms)
        print(f"[5b] Rio Grande (54,182 segments), min_size={ms}: replica == literal code ({k} subnetworks)")
    # and the cached CONUS decomposition used by the experiment agrees on the Rio Grande
    ref = reference_subnets(lk, d, 1000)
    S1 = S[1000]
    sel = np.nonzero(S1["net"] == rg)[0]
    mine = {}
    for s in sel:
        mine[(int(S1["order"][s]), int(D["link"][S1["tw"][s]]))] = frozenset(D["link"][S1["sub"] == s].tolist())
    assert mine == ref, "cached CONUS subnetworks differ from the literal code on the Rio Grande"
    print("[5b] cached CONUS decomposition (T=1000) == literal code on the Rio Grande")

    # 6: full-size validation
    from run_experiments import Scopes
    sc = Scopes(D, {1000: S[1000]}, "RioGrande", [626220])
    cnt = 0
    for gran, T in (("segment", None), ("reach_unit", None), ("reach_cost", None),
                    ("subnet", 1000), ("cluster_old", 1000), ("cluster_bin", 1000)):
        G = sc.graph(gran, T)
        for P in (1, 3, 36, 1024, np.inf):
            for pol in ("opp_fifo", "opp_lrp", "opp_rounds", "jit", "jit_list", "jit_release", "work_steal"):
                validate(G, J.schedule(G, pol, P), P, pol)
                cnt += 1
        if gran.startswith("cluster"):                   # clusters partition the segments exactly
            assert G.cost.sum() == sc.n_seg
    Gm = J.subset(J.segment_graph(D), m)
    for P in (36, np.inf):
        for pol in ("opp_fifo", "opp_lrp", "opp_rounds", "jit", "jit_list", "jit_release", "work_steal"):
            validate(Gm, J.schedule(Gm, pol, P), P, pol)
            cnt += 1
    # 7: the t-route test case network (test/LowerColorado_TX/domain/RouteLink.nc) is the whole CONUS network
    tc = HERE / "data" / "lc_test" / "RouteLink.nc"
    if tc.exists():
        from netCDF4 import Dataset
        with Dataset(tc) as ds:
            tl = np.sort(np.asarray(ds["link"][:]).astype(np.int64))
        o = int(np.nonzero(D["link"] == 3766342)[0][0])
        cl = np.sort(D["link"][D["net"] == o])
        assert len(tl) == len(cl) == 11248 and (tl == cl).all(), "test-case RouteLink differs from CONUS network"
        print("[7] t-route test/LowerColorado_TX RouteLink.nc == network of outlet 3766342 in v3.1.7 (11,248 segments, same ids)")
    else:
        print("[7] skipped (run fetch_testcase.py to download the t-route test-case RouteLink)")
    print(f"[6] {cnt} full-size schedules validated (Rio Grande x 6 granularities, Mississippi segments)")
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
