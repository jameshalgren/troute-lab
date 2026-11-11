"""Scheduling kernels, graph construction and T-Route subnetwork clustering.

Library module for the JIT-vs-opportunistic experiment (see README.md). No script
entry point; it is imported by run_experiments.py, check.py, worked_example.py and
make_figures.py.

Model (all integer arithmetic, so schedules are exact and reproducible):
  * a work UNIT has an integer duration. One NWM segment of compute = SCALE sub-units, so
    a per-unit dispatch overhead can be fractional in segment-compute units;
  * a unit may start only after every upstream unit has finished (in-tree for
    segment/reach units, general DAG for clustered subnetworks);
  * policies: opportunistic list scheduling (event driven; ready units start as soon as a
    core is free; FIFO or longest-remaining-path-first priority), JIT (strides of equal
    "distance from outlet", furthest first, barrier between strides), by-network
    (each independent network is one job on one core, LPT bin packing).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numba import njit

SHIFT = 23                     # unit / core ids must be < 2**23 = 8,388,608
MASK = (1 << SHIFT) - 1
SCALE = 100                    # sub-units per segment of compute


# ----------------------------------------------------------------------------- heaps
@njit
def _push(h, n, key):
    i = n
    n += 1
    while i > 0:
        p = (i - 1) >> 1
        if h[p] > key:
            h[i] = h[p]
            i = p
        else:
            break
    h[i] = key
    return n


@njit
def _pop(h, n):
    top = h[0]
    n -= 1
    if n > 0:
        key = h[n]
        i = 0
        while True:
            lc = 2 * i + 1
            if lc >= n:
                break
            c = lc
            if lc + 1 < n and h[lc + 1] < h[lc]:
                c = lc + 1
            if h[c] < key:
                h[i] = h[c]
                i = c
            else:
                break
        h[i] = key
    return top, n


# ------------------------------------------------------------------- DAG utilities
@njit
def topo_order(sp, si, indeg0):
    n = len(indeg0)
    indeg = indeg0.copy()
    order = np.empty(n, np.int64)
    head = 0
    tail = 0
    for u in range(n):
        if indeg[u] == 0:
            order[tail] = u
            tail += 1
    while head < tail:
        u = order[head]
        head += 1
        for k in range(sp[u], sp[u + 1]):
            v = si[k]
            indeg[v] -= 1
            if indeg[v] == 0:
                order[tail] = v
                tail += 1
    return order, tail


@njit
def bottom_level(order, dur, sp, si):
    """Longest duration-weighted path from each unit (inclusive) to a sink."""
    n = len(dur)
    bl = np.zeros(n, np.int64)
    for k in range(n - 1, -1, -1):
        u = order[k]
        m = 0
        for e in range(sp[u], sp[u + 1]):
            if bl[si[e]] > m:
                m = bl[si[e]]
        bl[u] = dur[u] + m
    return bl


@njit
def asap_level(order, sp, si, n):
    """Round number of each unit when every unit runs as soon as its upstreams are done
    (0 for units with no upstream unit)."""
    lev = np.zeros(n, np.int64)
    for k in range(n):
        u = order[k]
        for e in range(sp[u], sp[u + 1]):
            v = si[e]
            if lev[u] + 1 > lev[v]:
                lev[v] = lev[u] + 1
    return lev


@njit
def list_schedule(dur, sp, si, indeg0, prio, mode, P):
    """Event-driven greedy list scheduling.

    mode 0: FIFO (key = time the unit became ready; ties by unit index)
    mode 1: priority array `prio` (smaller first; ties by unit index)
    Returns start, core.
    """
    n = len(dur)
    pe = min(P, n)
    indeg = indeg0.copy()
    ready = np.empty(n, np.int64)
    nr = 0
    run = np.empty(pe, np.int64)
    nrun = 0
    freec = np.empty(pe, np.int64)
    for c in range(pe):
        freec[c] = pe - 1 - c
    nfree = pe
    start = np.empty(n, np.int64)
    core = np.empty(n, np.int64)
    for u in range(n):
        if indeg[u] == 0:
            k1 = 0 if mode == 0 else prio[u]
            nr = _push(ready, nr, (k1 << SHIFT) | u)
    t = 0
    done = 0
    while done < n:
        while nfree > 0 and nr > 0:
            key, nr = _pop(ready, nr)
            u = key & MASK
            nfree -= 1
            c = freec[nfree]
            start[u] = t
            core[u] = c
            nrun = _push(run, nrun, ((t + dur[u]) << SHIFT) | u)
        if nrun == 0:
            raise ValueError("deadlock: graph has a cycle")
        key, nrun = _pop(run, nrun)
        t = key >> SHIFT
        while True:
            u = key & MASK
            freec[nfree] = core[u]
            nfree += 1
            done += 1
            for e in range(sp[u], sp[u + 1]):
                v = si[e]
                indeg[v] -= 1
                if indeg[v] == 0:
                    k1 = t if mode == 0 else prio[v]
                    nr = _push(ready, nr, (k1 << SHIFT) | v)
            if nrun > 0 and (run[0] >> SHIFT) == t:
                key, nrun = _pop(run, nrun)
            else:
                break
    return start, core


@njit
def release_schedule(dur, sp, si, indeg0, prio, release, P):
    """List scheduling with release times: a unit may start only when its upstream units
    are done AND t >= release[u]; among startable units the smallest prio goes first."""
    n = len(dur)
    pe = min(P, n)
    indeg = indeg0.copy()
    ready = np.empty(n, np.int64)
    nr = 0
    pend = np.empty(n, np.int64)
    npd = 0
    run = np.empty(pe, np.int64)
    nrun = 0
    freec = np.empty(pe, np.int64)
    for c in range(pe):
        freec[c] = pe - 1 - c
    nfree = pe
    start = np.empty(n, np.int64)
    core = np.empty(n, np.int64)
    for u in range(n):
        if indeg[u] == 0:
            npd = _push(pend, npd, (release[u] << SHIFT) | u)
    t = 0
    done = 0
    while done < n:
        while npd > 0 and (pend[0] >> SHIFT) <= t:
            key, npd = _pop(pend, npd)
            u = key & MASK
            nr = _push(ready, nr, (prio[u] << SHIFT) | u)
        while nfree > 0 and nr > 0:
            key, nr = _pop(ready, nr)
            u = key & MASK
            nfree -= 1
            c = freec[nfree]
            start[u] = t
            core[u] = c
            nrun = _push(run, nrun, ((t + dur[u]) << SHIFT) | u)
        tn = -1
        if nrun > 0:
            tn = run[0] >> SHIFT
        if npd > 0 and nfree > 0:
            tr = pend[0] >> SHIFT
            if tn < 0 or tr < tn:
                tn = tr
        if tn < 0:
            raise ValueError("deadlock")
        t = tn
        while nrun > 0 and (run[0] >> SHIFT) == t:
            key, nrun = _pop(run, nrun)
            u = key & MASK
            freec[nfree] = core[u]
            nfree += 1
            done += 1
            for e in range(sp[u], sp[u + 1]):
                v = si[e]
                indeg[v] -= 1
                if indeg[v] == 0:
                    npd = _push(pend, npd, (max(release[v], t) << SHIFT) | v)
    return start, core


@njit
def work_steal_schedule(dur, sp, si, indeg0, P):
    """Work stealing that never looks at costs (a sketch for the unknown-cost phase).
    Each core owns a deque. Initial ready units are dealt round-robin. A unit made ready
    by a completion goes to the bottom of the deque of the core that completed it. An
    idle core pops the bottom of its own deque (newest first, which follows the river
    downstream); if empty, it steals the top (oldest) of the first non-empty deque found
    scanning from the next core. Deterministic."""
    n = len(dur)
    pe = min(P, n)
    indeg = indeg0.copy()
    nxt = np.full(n, -1, np.int64)
    prv = np.full(n, -1, np.int64)
    head = np.full(pe, -1, np.int64)
    tail = np.full(pe, -1, np.int64)
    qcount = 0
    run = np.empty(pe, np.int64)
    nrun = 0
    idle = np.empty(pe, np.int64)
    nidle = pe
    for c in range(pe):
        idle[c] = pe - 1 - c
    start = np.empty(n, np.int64)
    core = np.empty(n, np.int64)
    k = 0
    for u in range(n):
        if indeg[u] == 0:
            c = k % pe
            k += 1
            prv[u] = tail[c]
            nxt[u] = -1
            if tail[c] >= 0:
                nxt[tail[c]] = u
            else:
                head[c] = u
            tail[c] = u
            qcount += 1
    t = 0
    done = 0
    while done < n:
        # give work to idle cores
        i = nidle - 1
        while i >= 0 and qcount > 0:
            c = idle[i]
            u = -1
            if tail[c] >= 0:                        # own deque, bottom
                u = tail[c]
                tail[c] = prv[u]
                if tail[c] >= 0:
                    nxt[tail[c]] = -1
                else:
                    head[c] = -1
            else:                                   # steal the oldest from another core
                for j in range(1, pe):
                    v = (c + j) % pe
                    if head[v] >= 0:
                        u = head[v]
                        head[v] = nxt[u]
                        if head[v] >= 0:
                            prv[head[v]] = -1
                        else:
                            tail[v] = -1
                        break
            if u >= 0:
                qcount -= 1
                start[u] = t
                core[u] = c
                nrun = _push(run, nrun, ((t + dur[u]) << SHIFT) | u)
                idle[i] = idle[nidle - 1]
                nidle -= 1
            i -= 1
        if nrun == 0:
            raise ValueError("deadlock")
        key, nrun = _pop(run, nrun)
        t = key >> SHIFT
        while True:
            u = key & MASK
            c = core[u]
            idle[nidle] = c
            nidle += 1
            done += 1
            for e in range(sp[u], sp[u + 1]):
                v = si[e]
                indeg[v] -= 1
                if indeg[v] == 0:
                    prv[v] = tail[c]
                    nxt[v] = -1
                    if tail[c] >= 0:
                        nxt[tail[c]] = v
                    else:
                        head[c] = v
                    tail[c] = v
                    qcount += 1
            if nrun > 0 and (run[0] >> SHIFT) == t:
                key, nrun = _pop(run, nrun)
            else:
                break
    return start, core


@njit
def busy_window(start, dur, a, b):
    """Busy core-time inside [a, b)."""
    s = 0
    for i in range(len(start)):
        lo = max(start[i], a)
        hi = min(start[i] + dur[i], b)
        if hi > lo:
            s += hi - lo
    return s


@njit
def stride_schedule(dur, order, stride, P, barrier):
    """JIT: `order` lists units by stride (descending) and, within a stride, by duration
    (descending). All units of a stride are list-scheduled on min(P, size) cores starting
    when the previous stride has ended (+barrier). Also used with one stride for LPT."""
    n = len(dur)
    pe = min(P, n)
    heap = np.empty(pe, np.int64)
    start = np.empty(n, np.int64)
    core = np.empty(n, np.int64)
    T = 0
    i = 0
    while i < n:
        s = stride[order[i]]
        j = i
        while j < n and stride[order[j]] == s:
            j += 1
        p = min(pe, j - i)
        for c in range(p):
            heap[c] = (T << SHIFT) | c
        hn = p
        end = T
        for k in range(i, j):
            u = order[k]
            top, hn = _pop(heap, hn)
            f = top >> SHIFT
            c = top & MASK
            start[u] = f
            core[u] = c
            fin = f + dur[u]
            if fin > end:
                end = fin
            hn = _push(heap, hn, (fin << SHIFT) | c)
        T = end + barrier
        i = j
    return start, core


@njit
def profile_metrics(start, dur, P):
    """Returns (makespan, time with >= P cores busy, last instant with >= 2 cores busy)."""
    n = len(start)
    ev = np.empty(2 * n, np.int64)
    for i in range(n):
        ev[2 * i] = (start[i] << 1) | 1
        ev[2 * i + 1] = (start[i] + dur[i]) << 1
    ev.sort()
    cnt = 0
    prev = 0
    full = 0
    last2 = 0
    for k in range(2 * n):
        t = ev[k] >> 1
        if t > prev:
            if cnt >= P:
                full += t - prev
            if cnt >= 2:
                last2 = t
            prev = t
        if ev[k] & 1:
            cnt += 1
        else:
            cnt -= 1
    return prev, full, last2


@njit
def binned_busy(start, dur, M, nb):
    """Mean number of busy cores in each of nb equal time bins over [0, M]."""
    out = np.zeros(nb, np.float64)
    w = M / nb
    for i in range(len(start)):
        a = start[i]
        b = start[i] + dur[i]
        k0 = int(a / w)
        k1 = int((b - 1) / w)
        if k1 >= nb:
            k1 = nb - 1
        for k in range(k0, k1 + 1):
            lo = max(a, k * w)
            hi = min(b, (k + 1) * w)
            if hi > lo:
                out[k] += hi - lo
    return out / w


# ----------------------------------------------------------------------- graph class
@dataclass
class Graph:
    cost: np.ndarray      # int64, in segments (not scaled)
    stride: np.ndarray    # int64, JIT stride; larger = further from the outlet = earlier
    esrc: np.ndarray      # edge u -> v: v may start only after u has finished
    edst: np.ndarray

    @property
    def n(self):
        return len(self.cost)

    def csr(self):
        n = self.n
        o = np.argsort(self.esrc, kind="stable")
        si = self.edst[o].astype(np.int64)
        sp = np.zeros(n + 1, np.int64)
        np.cumsum(np.bincount(self.esrc, minlength=n), out=sp[1:])
        indeg = np.bincount(self.edst, minlength=n).astype(np.int64)
        return sp, si, indeg


def subset(G: Graph, mask: np.ndarray) -> Graph:
    idx = np.cumsum(mask) - 1
    keep = mask[G.esrc] & mask[G.edst]
    return Graph(G.cost[mask], G.stride[mask], idx[G.esrc[keep]].astype(np.int64),
                 idx[G.edst[keep]].astype(np.int64))


# -------------------------------------------------------------------- run a policy
# Plain names used in the README, tables and figures (code labels stay short).
POLICY_NAMES = {
    "opp_rounds": "2020-style rounds",
    "opp_fifo": "naive first-ready",
    "jit": "JIT strides",
    "jit_list": "JIT strides, list order within a stride",
    "jit_barrier": "JIT strides + barrier cost",
    "opp_lrp": "JIT priority without barriers (Hu's rule)",
    "opp_lrp_dyn": "Hu's rule, cost known when ready (cost-aware dynamic)",
    "jit_release": "JIT timetable (just-in-time release, no barriers)",
    "work_steal": "work stealing (costs unknown)",
    "by_network": "by network only",
    "lpt_independent": "LPT, independent jobs",
}


def schedule(G: Graph, policy: str, P, overhead=0.0, barrier=0.0, est_cost=None):
    """Run one policy. P may be np.inf. overhead/barrier are in segment-compute units.

    G.cost is the TRUE per-unit cost (any non-negative integer vector, in segment-compute
    units); it sets the durations. est_cost (optional, same shape) is what the scheduler
    BELIEVES the costs are: it is used for every scheduling decision that needs costs
    (priorities, longest-first order inside a stride or round, release times). With
    est_cost=None the scheduler knows the true costs. This is the hook for "costs unknown
    until execution" (e.g. est_cost = ones while the true costs vary). Policies that never
    look at costs (opp_fifo, work_steal, JIT stride membership) are unaffected.
    Returns dict(start, dur, core, Pn, o) with times in SCALE sub-units."""
    o = int(round(overhead * SCALE))
    b = int(round(barrier * SCALE))
    dur = G.cost.astype(np.int64) * SCALE + o
    est = dur if est_cost is None else np.asarray(est_cost).astype(np.int64) * SCALE + o
    assert est.shape == dur.shape and (dur > 0).all() and (est > 0).all()
    Pn = G.n if not np.isfinite(P) else int(min(P, G.n))
    sp, si, indeg = G.csr()
    stride = None
    if policy == "opp_fifo":
        start, core = list_schedule(dur, sp, si, indeg, np.zeros(1, np.int64), 0, Pn)
    elif policy == "opp_lrp_dyn":
        # Cost-aware dynamic: a unit's own cost becomes known when it becomes ready; the
        # rest of its path to the outlet (all downstream units, none started yet) is
        # estimated. priority = true cost(u) + estimated distance of its downstream unit.
        # The value is fixed once the unit is ready, so it can be precomputed.
        order, cnt = topo_order(sp, si, indeg)
        assert cnt == G.n, "cycle"
        bl_est = bottom_level(order, est, sp, si)
        val = dur + (bl_est - est)
        prio = val.max() - val
        start, core = list_schedule(dur, sp, si, indeg, prio, 1, Pn)
    elif policy in ("opp_lrp", "jit_release"):
        # Priority = bottom level = cost-weighted longest path from the unit (inclusive) to a
        # sink. On an in-forest (segments, reaches) each unit has exactly one downstream
        # unit, so this is the unit's distance from its outlet in cost units, counting
        # itself: Hu's (1961) level for unit costs. Ties: lowest unit index.
        order, cnt = topo_order(sp, si, indeg)
        assert cnt == G.n, "cycle"
        bl = bottom_level(order, est, sp, si)
        prio = bl.max() - bl
        if policy == "opp_lrp":
            start, core = list_schedule(dur, sp, si, indeg, prio, 1, Pn)
        else:
            # JIT timetable: a unit is released at its just-in-time start
            # (critical path - distance to the outlet), i.e. the latest start in an
            # unlimited-core schedule; it starts at the first time it is released, its
            # upstreams are done and a core is free; among those, furthest first. No barriers.
            release = bl.max() - bl
            start, core = release_schedule(dur, sp, si, indeg, prio, release, Pn)
    elif policy == "work_steal":
        start, core = work_steal_schedule(dur, sp, si, indeg, Pn)
    elif policy in ("jit", "jit_barrier", "jit_list"):
        # jit / jit_barrier: within a stride, longest unit first (LPT; favours JIT).
        # jit_list: within a stride in list (unit index) order, as joblib dispatches the
        # list of jobs it is given.
        stride = G.stride
        if policy == "jit_list":
            order = np.lexsort((np.arange(G.n), -stride)).astype(np.int64)
        else:
            order = np.lexsort((-est, -stride)).astype(np.int64)
        start, core = stride_schedule(dur, order, stride, Pn, b if policy == "jit_barrier" else 0)
    elif policy == "opp_rounds":
        # 2020-style opportunistic rounds (nhd_reach_parallel_test.py,
        # compute_network_parallel_opportunistic): round 0 = all units with no upstream
        # unit, round k = units whose upstream units are all in rounds < k (ASAP level);
        # rounds pooled over networks, a barrier after each round; LPT within a round.
        order0, cnt = topo_order(sp, si, indeg)
        assert cnt == G.n, "cycle"
        lev = asap_level(order0, sp, si, G.n)
        stride = lev.max() - lev
        order = np.lexsort((-est, -stride)).astype(np.int64)
        start, core = stride_schedule(dur, order, stride, Pn, 0)
    elif policy == "lpt_independent":      # no dependencies; LPT onto P cores
        order = np.argsort(-est, kind="stable").astype(np.int64)
        start, core = stride_schedule(dur, order, np.zeros(G.n, np.int64), Pn, 0)
    else:
        raise ValueError(policy)
    sch = dict(start=start, dur=dur, core=core, Pn=Pn, o=o)
    if stride is not None:
        sch["stride"] = stride
    return sch


def critical_path(G: Graph, overhead=0.0):
    o = int(round(overhead * SCALE))
    dur = G.cost.astype(np.int64) * SCALE + o
    sp, si, indeg = G.csr()
    order, cnt = topo_order(sp, si, indeg)
    assert cnt == G.n
    return int(bottom_level(order, dur, sp, si).max())


def summarize(G: Graph, sch: dict, P, overhead=0.0, serial_work=None):
    """Metrics in segment-compute units. serial_work: total segments of the scope (no overhead)."""
    start, dur = sch["start"], sch["dur"]
    Pn = sch["Pn"]
    M, full, last2 = profile_metrics(start, dur, Pn)
    work = float(G.cost.sum()) * SCALE
    dsum = float(dur.sum())
    cp = critical_path(G, overhead)
    finite = np.isfinite(P)
    sw = float(G.cost.sum()) if serial_work is None else float(serial_work)
    return dict(
        n_units=G.n, work_segments=sw, makespan=M / SCALE,
        lb_work=(dsum / P / SCALE) if finite else 0.0, lb_cp=cp / SCALE,
        util=(work / (P * M)) if finite else np.nan,
        busy_frac=(dsum / (P * M)) if finite else np.nan,
        full_busy_frac=(full / M) if (finite and P > 1) else np.nan,
        tail_len=((M - last2) / SCALE) if P > 1 else np.nan,
        tail_frac=((M - last2) / M) if P > 1 else np.nan,
        speedup=sw * SCALE / M,
        n_strides=int(len(np.unique(G.stride))),
        # saturation: idle core-time = P x makespan - busy time (segment-cycles); with zero
        # overhead busy time = W, so idle = P x makespan - W and makespan = (W + idle) / P
        idle_core_time=((P * M - dsum) / SCALE) if finite else np.nan,
        idle_share_first_half=((P * (M // 2) - busy_window(start, dur, 0, M // 2)) / (P * M - dsum))
        if (finite and P * M > dsum) else np.nan,
    )


# ----------------------------------------------------------------- RouteLink -> graph
@njit
def _reach_tops(order, ds, indeg):
    n = len(ds)
    top = np.arange(n)
    for k in range(n):
        u = order[k]
        d = ds[u]
        if d >= 0 and indeg[d] == 1:
            top[d] = top[u]
    return top


@njit
def _depths(order, ds):
    n = len(ds)
    depth = np.zeros(n, np.int64)
    net = np.arange(n)
    for k in range(n - 1, -1, -1):
        u = order[k]
        d = ds[u]
        if d >= 0:
            depth[u] = depth[d] + 1
            net[u] = net[d]
    return depth, net


@njit
def _reach_depth(order, ds, rid, nr):
    rd = np.zeros(nr, np.int64)
    for k in range(len(order) - 1, -1, -1):
        u = order[k]
        d = ds[u]
        if d < 0:
            rd[rid[u]] = 0
        elif rid[d] != rid[u]:
            rd[rid[u]] = rd[rid[d]] + 1
    return rd


def load_network(routelink_nc: Path):
    """Segment-level arrays from a RouteLink file (link, to). Outlet: to == 0 or not a link."""
    from netCDF4 import Dataset
    with Dataset(routelink_nc) as ds:
        link = np.asarray(ds["link"][:]).astype(np.int64)
        to = np.asarray(ds["to"][:]).astype(np.int64)
    srt = np.argsort(link)
    pos = np.clip(np.searchsorted(link[srt], to), 0, len(link) - 1)
    found = (to != 0) & (link[srt][pos] == to)
    down = np.where(found, srt[pos], -1).astype(np.int64)
    n = len(link)
    indeg = np.bincount(down[down >= 0], minlength=n).astype(np.int64)
    # topological order (upstream first) over the segment tree
    sp = np.zeros(n + 1, np.int64)
    src = np.nonzero(down >= 0)[0]
    sp_cnt = np.bincount(src, minlength=n)
    np.cumsum(sp_cnt, out=sp[1:])
    si = down[src]
    order, cnt = topo_order(sp, si, indeg)
    if cnt != n:
        raise SystemExit("cycle in network")
    depth, net = _depths(order, down)
    top = _reach_tops(order, down, indeg)
    uniq, rid = np.unique(top, return_inverse=True)
    rid = rid.astype(np.int64)
    nr = len(uniq)
    rcost = np.bincount(rid, minlength=nr).astype(np.int64)
    cross = (down >= 0)
    cross[cross] = rid[down[cross]] != rid[cross.nonzero()[0]]
    u_cross = np.nonzero(cross)[0]
    redge_src = rid[u_cross]
    redge_dst = rid[down[u_cross]]
    rdepth = _reach_depth(order, down, rid, nr)
    rnet = net[uniq]                      # outlet segment index of each reach's network
    # upstream CSR for the BFS (children = upstream segments)
    up_ptr, up_idx = upstream_csr(link, down)
    return dict(link=link, down=down, indeg=indeg, depth=depth, net=net, rid=rid,
                rcost=rcost, redge_src=redge_src.astype(np.int64), redge_dst=redge_dst.astype(np.int64),
                rdepth=rdepth, rnet=rnet, up_ptr=up_ptr, up_idx=up_idx, topo=order)


def upstream_csr(link, down):
    """Upstream (reverse) adjacency as CSR. T-Route sorts the parameter frame by feature id
    before extract_connections (NHDNetwork.py L189, nhd_network_utilities_v02.py L86
    @12a8eae0), so reverse_network lists each segment's upstreams in ascending feature
    id; the BFS in build_subnetworks visits them in that order."""
    n = len(down)
    src = np.nonzero(down >= 0)[0]
    up_o = np.lexsort((link[src], down[src]))
    up_idx = src[up_o].astype(np.int64)
    indeg = np.bincount(down[src], minlength=n)
    up_ptr = np.zeros(n + 1, np.int64)
    np.cumsum(indeg, out=up_ptr[1:])
    return up_ptr, up_idx


def segment_graph(D) -> Graph:
    n = len(D["down"])
    u = np.nonzero(D["down"] >= 0)[0]
    return Graph(np.ones(n, np.int64), D["depth"], u.astype(np.int64), D["down"][u].astype(np.int64))


def reach_graph(D, unit_cost: bool) -> Graph:
    nr = len(D["rcost"])
    cost = np.ones(nr, np.int64) if unit_cost else D["rcost"]
    return Graph(cost, D["rdepth"], D["redge_src"], D["redge_dst"])


# -------------------------------------------------- T-Route build_subnetworks (replica)
@njit
def _build_subnetworks(up_ptr, up_idx, outlets, min_size, n):
    """Replica of NOAA-OWP/t-route nhd_network.build_subnetworks (threshold-limited BFS,
    depth counted in junctions, restarted at the cut points), on array data.
    Returns sub (subnetwork id of every segment), sub_order, sub_tw."""
    sub = np.full(n, -1, np.int64)
    sub_order = np.empty(n, np.int64)
    sub_tw = np.empty(n, np.int64)
    ns = 0
    qn = np.empty(n, np.int64)
    qy = np.empty(n, np.int64)
    mem = np.empty(n, np.int64)
    ext = np.zeros(n, np.bool_)
    cur = np.empty(n, np.int64)
    nxt = np.empty(n, np.int64)
    nc = len(outlets)
    for i in range(nc):
        cur[i] = outlets[i]
    order = 0
    while nc > 0:
        nn = 0
        for i in range(nc):
            h = cur[i]
            sid = ns
            ns += 1
            sub_order[sid] = order
            sub_tw[sid] = h
            head = 0
            tail = 1
            qn[0] = h
            qy[0] = 0
            cnt = 0
            stop = 1000000
            mc = 0
            while head < tail:
                x = qn[head]
                y = qy[head]
                head += 1
                cnt += 1
                sub[x] = sid
                mem[mc] = x
                mc += 1
                nup = up_ptr[x + 1] - up_ptr[x]
                usd = y + 1 if nup > 1 else y
                if cnt > min_size:
                    stop = y
                if usd <= stop:
                    for k in range(up_ptr[x], up_ptr[x + 1]):
                        qn[tail] = up_idx[k]
                        qy[tail] = usd
                        tail += 1
                    if nup > 0:
                        ext[x] = True
            for j in range(mc):
                x = mem[j]
                if (up_ptr[x + 1] - up_ptr[x]) > 0 and not ext[x]:
                    nxt[nn] = x
                    nn += 1
                ext[x] = False
        for i in range(nn):
            cur[i] = nxt[i]
        nc = nn
        order += 1
    return sub, sub_order[:ns].copy(), sub_tw[:ns].copy()


def build_subnetworks(D, min_size: int):
    n = len(D["down"])
    outlets = np.nonzero(D["down"] < 0)[0].astype(np.int64)
    sub, so, stw = _build_subnetworks(D["up_ptr"], D["up_idx"], outlets, int(min_size), n)
    size = np.bincount(sub, minlength=len(so)).astype(np.int64)
    down_tw = D["down"][stw]
    parent = np.where((so > 0) & (down_tw >= 0), sub[np.clip(down_tw, 0, n - 1)], -1)
    return dict(sub=sub, order=so, tw=stw, size=size, parent=parent.astype(np.int64),
                net=D["net"][stw])


# --------------------------------------------------- clustering of subnetworks per order
def _cluster_old(sizes, T):
    """Pre-PR#26 rule (CIROH-UA/t-route dd43a7d2 compute.py L604-L640): append subnetworks
    to the open cluster; once it holds >= 0.65*T segments (and the order has more
    subnetworks), open a new one. No upper bound."""
    cl = np.empty(len(sizes), np.int64)
    c = 0
    tot = 0
    m = len(sizes)
    for i, s in enumerate(sizes):
        cl[i] = c
        tot += int(s)
        if tot >= 0.65 * T and i + 1 < m:
            c += 1
            tot = 0
    return cl


def _cluster_bin(sizes, T):
    """PR#26 rule (CIROH-UA/t-route 8abd3f49 compute.py L602-L643): max-heap on remaining
    capacity; cap 1.1*T; subnetwork goes into the cluster with the most room if it fits,
    else opens a new cluster (online worst-fit; the code comment says best-fit)."""
    import heapq
    cl = np.empty(len(sizes), np.int64)
    heap = []
    nc = 0
    for i, s in enumerate(sizes):
        s = int(s)
        if heap:
            negcap, c = heap[0]
            cap = -negcap
            if s <= cap:
                cl[i] = c
                heapq.heapreplace(heap, (-(cap - s), c))
                continue
        c = nc
        nc += 1
        cl[i] = c
        heapq.heappush(heap, (-(1.1 * T - s), c))
    return cl


def subnetwork_graph(S, ids, mode: str, T: int, shuffle_seed=None, sub_cost=None) -> Graph:
    """Graph of subnetwork jobs for the subnetworks `ids`. mode: 'subnet' (one job per
    subnetwork), 'old' or 'bin' (clustered per order, pooled over the networks in `ids`).
    Within an order subnetworks are taken in ascending id (the real code's dict/set order
    is not reproducible), or shuffled when shuffle_seed is given."""
    ids = np.asarray(ids)
    ordr = S["order"][ids]
    cluster = np.empty(len(ids), np.int64)
    if mode == "subnet":
        cluster = np.arange(len(ids))
        ncl = len(ids)
    else:
        rng = np.random.default_rng(shuffle_seed) if shuffle_seed is not None else None
        base = 0
        for k in np.unique(ordr):
            sel = np.nonzero(ordr == k)[0]
            if rng is not None:
                sel = rng.permutation(sel)
            sizes = S["size"][ids[sel]]
            cl = _cluster_old(sizes, T) if mode == "old" else _cluster_bin(sizes, T)
            cluster[sel] = cl + base
            base += int(cl.max()) + 1
        ncl = base
    # clustering always uses segment counts (as T-Route does); the job cost can be any
    # per-subnetwork cost (sub_cost, aligned with S ids), e.g. summed measured segment costs
    w = S["size"][ids] if sub_cost is None else np.asarray(sub_cost)[ids]
    cost = np.round(np.bincount(cluster, weights=w, minlength=ncl)).astype(np.int64)
    stride = np.zeros(ncl, np.int64)
    stride[cluster] = ordr
    pos = np.full(len(S["order"]), -1, np.int64)
    pos[ids] = np.arange(len(ids))
    par = S["parent"][ids]
    has = par >= 0
    e_src = cluster[np.nonzero(has)[0]]
    e_dst = cluster[pos[par[has]]]
    key = np.unique(e_src * ncl + e_dst)
    return Graph(cost, stride, (key // ncl).astype(np.int64), (key % ncl).astype(np.int64))


# --------------------------------------------------------------------------- caching
def load_cached(data_dir: Path, routelink_nc: Path, thresholds=()):
    """Segment/reach arrays and subnetwork decompositions, cached as .npz under data_dir
    (data/ is gitignored)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    f = data_dir / "graph_CONUS_v2.npz"   # v2: upstreams in ascending feature id
    if f.exists():
        D = dict(np.load(f))
    else:
        D = load_network(routelink_nc)
        np.savez(f, **D)
    S = {}
    for T in thresholds:
        g = data_dir / f"subnets_CONUS_v2_T{T}.npz"
        if g.exists():
            S[T] = dict(np.load(g))
        else:
            S[T] = build_subnetworks(D, T)
            np.savez(g, **S[T])
    return D, S
