# Opportunistic vs. just-in-time (JIT) scheduling of the NWM channel network

*AI-assembled (Claude) at James Halgren's request; not reviewed by the author.*
- *2026-10-29: first version, then revised after an independent review (tail metric,
  subnetwork listing order, upstream order in the BFS, the 2020 "rounds" policy, wording).*
- *2026-10-30: reworked per [`RERUN_PLAN.md`](RERUN_PLAN.md) item 1, following the
  author's clarification (2026-10-30): the 2020 tests were on segments and measured
  saturation, used as a surrogate for performance. Segments are now the primary
  granularity, saturation is reported first, and the policies have plain names. Added: a
  reach-level JIT ordered by segment distance, the Potomac scope, and hooks for the
  unequal-cost phase.*

Every number below comes from the code in this directory, run on the dates above.
Sources quoted from other repositories were fetched on 2026-10-29.

## Question
T-Route must compute the river network upstream to downstream. With a fixed number of
cores, how well does each scheduling policy keep the cores busy, and how long does the
run take?

**The author's recollection** (2026-10-06; clarified 2026-10-30, see
`RERUN_PLAN.md`). A 2020 spreadsheet experiment on segments showed that "we could saturate
cores more effectively by this JIT orderering than by opportunistic ordering where every
independent node in a particular network calculates right away". Saturation, meaning few
idle cores, was the measure, as a surrogate for performance. The cache argument ("those
numbers have to wait in memory [...], we suppose") was an additional supposition.

**rs_route.** Josh Cunningham's rs_route challenges JIT with an opportunistic scheme.

This experiment tests the recollection; it does not assume it.

## The policies (plain names; code labels in brackets)
| Name used here | Code label | What it does |
|---|---|---|
| **2020-style rounds** | `opp_rounds` | Every unit whose upstreams are done runs in the next round; a barrier after each round. This is the 2020 method `compute_network_parallel_opportunistic` in [`nhd_reach_parallel_test.py`](https://github.com/NOAA-OWP/t-route/blob/39810e4ddea3f8a40a20ac59558f472bd08b109f/src/python_framework/nhd_reach_parallel_test.py) (2020-04-10); PR #188 describes it as "all the subnetworks that could execute simultaneously in a first pass, and so on down". |
| **Naive first-ready** | `opp_fifo` | No barriers. A ready unit starts as soon as a core is free, in the order units became ready (ties by unit index). |
| **JIT strides** | `jit` | Strides of equal distance from the outlet, furthest first, pooled over networks, a barrier after each stride. Distance is in segments (hops) for segments and reaches, and is the subnetwork order for subnetworks. Within a stride the longest unit goes first, which favours JIT. `jit_list` uses list order within a stride instead, as joblib does. |
| **JIT priority without barriers (Hu's rule)** | `opp_lrp` | No barriers. Whenever a core is free, it runs the ready unit furthest from the outlet. |
| JIT timetable | `jit_release` | Each unit is released at its just-in-time start (critical path minus its distance from the outlet), then runs when a core is free, furthest first. No barriers. |
| Work stealing (costs unknown) | `work_steal` | A sketch for the unequal-cost phase (see "Unequal costs"). Per-core deques: a core runs the newest unit it made ready, or steals the oldest from another core. It never looks at costs. |
| By network only | `by_network` | Each independent network is one serial job, LPT over cores. |

**Hu's rule, checked.** The priority of `opp_lrp` is the cost-weighted longest path from a
unit, itself included, to a sink. On an in-forest (segments, reaches) every unit has
exactly one downstream unit, so this is exactly the unit's distance from its outlet in
cost units. For unit costs that is Hu's level. `check.py` test 3b verifies the equality
on random forests with random costs. Ties go to the lowest unit index.

Two cases go beyond the theorem verified below (unit-time in-trees):
- with unequal costs the rule is the same, but the optimality result no longer applies;
- on clustered subnetworks (a DAG, not a tree) the priority is the longest path to any
  sink.

## Verdict
**The recollection is supported on its own terms, and the result points past it.**
- *Segments, saturation.* JIT strides keep the cores busier than both opportunistic
  policies the 2020 test could have meant. On the Mississippi at 36 cores, idle core-time
  is 4.8% of core-time for JIT strides, against 7.6% for 2020-style rounds and 6.9% for
  naive first-ready. At 128 cores it is 15.9% against 24.7% and 23.8%.
- *The JIT priority without the barriers does better still.* Mississippi: 0.3% idle at 36
  cores, 1.5% at 128. The per-stride barrier is what costs JIT the remaining idle time.
- *When cores are idle differs.* JIT strides lose two-thirds of their idle core-time in
  the first half of the run, because the far strides are narrow. Both opportunistic
  policies lose all of it at the end, waiting on the mainstem. Hu's rule loses almost none.
- *Saturation and performance are one objective.* With fixed total work W and zero
  overhead, idle core-time = P x makespan - W. Minimizing idle cores and minimizing run
  time are therefore the same objective in this model, so saturation was an exact
  surrogate for performance here, not an approximation.

**Saturation by segment** (`tables/saturation_segments.md`). Idle core-time is in
segment-cycles, with its share of P x makespan in brackets. "First half" is the share of
the idle time that falls in the first half of the run.

| Network, cores | 2020-style rounds | Naive first-ready | JIT strides | Hu's rule (JIT priority, no barriers) |
|---|---|---|---|---|
| Mississippi, 36 | 92,396 (7.6%), first half 0% | 83,324 (6.9%), 0% | 56,540 (4.8%), 67% | 2,936 (0.3%), 0% |
| Mississippi, 128 | 365,824 (24.7%), 0% | 349,056 (23.8%), 0% | 210,560 (15.9%), 66% | 17,280 (1.5%), 0% |
| CONUS, 36 | 87,894 (3.1%), 0% | 75,546 (2.6%), 0% | 57,474 (2.0%), 85% | 18 (0.0%) |
| CONUS, 128 | 353,378 (11.3%), 0% | 328,162 (10.6%), 0% | 208,866 (7.0%), 84% | 98 (0.0%) |
| Colorado TX, 36 | 21,404 (65.6%), 26% | 20,972 (65.1%), 26% | 15,824 (58.5%), 35% | 12,116 (51.9%), 6% |
| Potomac, 36 | 16,882 (50.6%), 6% | 16,270 (49.7%), 4% | 9,358 (36.3%), 50% | 2,590 (13.6%), 0% |

Makespan in segment-cycles for the same rows, with the lower bound max(W/P, critical
path) in brackets:

| Network, cores | Rounds | Naive | JIT strides | Hu's rule |
|---|---:|---:|---:|---:|
| Mississippi, 36 [31,036] | 33,603 | 33,351 | 32,607 | 31,118 |
| Mississippi, 128 [8,729] | 11,587 | 11,456 | 10,374 | 8,864 |
| CONUS, 36 [77,132] | 79,573 | 79,230 | 78,728 | 77,132 |
| CONUS, 128 [21,693] | 24,454 | 24,257 | 23,325 | 21,694 |
| Colorado TX, 36 [649] | 907 | 895 | 752 | 649 |
| Potomac, 36 [527] | 926 | 909 | 717 | 529 |

**Notes on these tables.**
- *Small networks are path-bound.* For networks the size of the Texas Colorado or the
  Potomac, the critical path (649 and 527 segments) exceeds W/P at 36 cores. Most cores
  are then idle under any policy; Hu's rule reaches the bound, the others do not. By 128
  cores, JIT strides and Hu's rule both reach the critical path on every network except
  the Mississippi and CONUS.
- *The single-core tail.* The author asked how long it is under pure opportunistic
  scheduling. On the Mississippi by segment it is 1,163 cycles under rounds at every core count from 8 to 1,024, and 978 to
  1,158 under naive first-ready (1,119 at 36 cores). JIT strides end with 5.
  The network forces 1,163 cycles on one core even with unlimited cores (the structural
  tail), because the last stretch of the mainstem cannot be split. What JIT and Hu's rule
  do is run other work alongside that stretch. So the tail is real, but its length alone
  does not separate the policies; idle core-time does.
- *Many cores.* The gap grows with cores. At 1,024 cores on the Mississippi, JIT strides
  and Hu's rule reach the 3,174-segment critical path, while rounds take 4,169 and naive
  first-ready 4,132. The AGU 2020 "about 1000x" argument lives in this regime
  (`tables/makespan_by_cores.md`).
- *Reaches.* A reach implementation keeps the segment result only with segment-distance
  priorities. On reaches with cost = segments:
  - JIT strides counted in reach hops: 33,709 on the Mississippi at 36 cores, 16,086 at
    1,024 cores.
  - The JIT timetable with segment distances: exactly the segment JIT timetable (31,234
    and 3,174).
  - Hu's rule with segment distances: exactly the segment result (31,118 and 3,174).

  See `tables/reach_vs_segment.md`.
- *Equal costs.* Everything above assumes equal cost per segment. For measured, unequal
  costs on the Potomac, see "Unequal costs: measured MC costs on the Potomac". In short:
  cost knowledge is worth at most about 2% of makespan, but the equal-cost model
  underpredicts path-bound run times in calm flow by up to 38%.

## What was built
| File | Purpose |
|---|---|
| `jitsched.py` | numba scheduling kernels, metrics, RouteLink to segment/reach graphs, a replica of T-Route's `build_subnetworks`, the clustering rules, `POLICY_NAMES` |
| `run_experiments.py` | the full grid, the dispatch-overhead sensitivity, the subnetwork-order sensitivity |
| `worked_example.py` | the 15-segment schematic (`results/fig_worked_example.{png,pdf}`) |
| `cluster_stats.py` | cluster-size statistics, old rule vs bin packing |
| `make_figures.py` | figures in `results/` and the committed tables in `tables/` |
| `check.py` | validation (below) |
| `cost_scheduling.py` | Potomac schedules under measured per-segment MC costs (needs `../mc_cost_variability/results/cost/`) |
| `fetch_testcase.py` | downloads the t-route test-case RouteLink (pinned to commit `12a8eae0`, SHA-256 asserted) |
| `run.sh` | everything in order |
| `tables/` | committed tables: `saturation_segments.{csv,md}` (primary), `cost_scheduling.{csv,md}`, `reach_vs_segment.{csv,md}`, `headline_P36.{csv,md}`, `makespan_by_cores.{csv,md}`, `cluster_order_ranges.{csv,md}`, `cluster_stats.csv`, `summary.json`, `worked_example.csv` |
| `RERUN_PLAN.md` | the coordinator's plan for this rerun (not edited here) |

`results/` (all runs, figures) and `data/` (graph caches, about 360 MB) are gitignored;
`run.sh` regenerates both.

**Environment and run time.** All Python runs through `uv` (PEP 723 headers, exact pins:
Python 3.12, numpy 2.5.4, numba 0.68.1, netCDF4 1.7.5.1.post1, pandas 3.0.6, matplotlib
3.11.2). On the machine used (macOS, Apple silicon), `run_experiments.py` took 8.1 min of
CPU time, but 40 min of wall clock while the machine was loaded (20% CPU share). Most of
it is work stealing on CONUS and the Mississippi at 64 to 128 cores, where victim scans
cost O(cores). Work stealing is skipped where units x cores > 4 x 10^8 (Mississippi and
CONUS above 128 cores). `check.py` takes about 20 s; the RouteLink download (270 MB) is
extra.

## Figures (`results/`, png and pdf)
- **`fig_saturation_segments` (paper figure).** Cores busy over time, by segment, for the
  Mississippi and the Texas Colorado test network at 36 and 128 cores, with the four main
  policies. Time is divided by the lower bound, so 1.0 is the best possible finish. Each
  panel lists idle core-time. JIT strides ramp up at the start; the opportunistic
  policies collapse at the end; Hu's rule stays full.
- `fig_worked_example`: the 15-segment schematic with the four policies.
- `fig_speedup_vs_cores`, `fig_utilization_excess_P36`, `fig_busy_profile_P36`,
  `fig_overhead_sensitivity`, `fig_cluster_thresholds_P36`: secondary comparisons
  (reaches, clusters, overhead).

## Input and the networks
Input: NWM v3.1.6 `RouteLink_CONUS.nc` (2,776,734 segments, 12,820 networks), downloaded
by `../network_stats/fetch_data.py` (URL and SHA-256
`4957655896f4f27854f893d02fa084f9f79c1cf8e80ce77565a7356dadb6fc0e` pinned there). The
graph agrees with `../network_stats/expected/expected.json` (`check.py` test 4): 2,114,380
reaches; Mississippi 1,117,312 segments, 868,651 reaches, longest path 3,174 segments =
2,219 reaches.

| Scope | Outlet feature_id(s) | Segments | Reaches | Longest path (seg.) | Identification |
|---|---|---:|---:|---:|---|
| Mississippi | 22811611 | 1,117,312 | 868,651 | 3,174 | `../network_stats/README.md` |
| CONUS | 12,820 outlets | 2,776,734 | 2,114,380 | 3,174 | all networks, pooled |
| Rio Grande | 626220 | 54,182 | 45,074 | 1,739 | The outlet's NHDPlus `gnis_name` is blank. `../network_stats/README.md` identifies the network from the NLDI Rio Grande mainstem and shows the Rio Chama and the Pecos River inside it |
| Colorado River, Texas (t-route test case) | 3766342 | 11,248 | 7,734 | 649 | NHDPlus V2 `gnis_name` "Colorado River" (USGS geoserver, queried 2026-10-29) |
| Brazos River | 3125212 | 14,293 | 9,871 | 742 | `gnis_name` "Brazos River" |
| Colorado TX + Brazos | 3766342 + 3125212 | 25,541 | 17,605 | 742 | the two independent networks pooled |
| Trinity River | 1523997 | 9,616 | 6,533 | 336 | `gnis_name` "Trinity River" |
| Potomac River | 4539621 | 16,454 | 12,111 | 527 | All segments upstream of NWM feature 4539621 (a network outlet in v3.1.6, the mouth at Chesapeake Bay), as in `../short_ts_switch/README.md` (`potomac_storm`). The scope of the measured per-segment costs (RERUN_PLAN item 2; see "Unequal costs") |

**The t-route test case.** The author asked (2026-10-29): *please use
the "Little Colorado" river in Texas as the small network. Do it alone and together with
the Brazos as you can see happens in the test case in the T-route application folder.*
What the repository shows (`NOAA-OWP/t-route` at `12a8eae0`, checked 2026-10-29):
- `test/LowerColorado_TX/domain/RouteLink.nc` (1,117,660 bytes, SHA-256
  `e7ab06e5a93c664a91b10650063e0994279ef5ecc355024a780594d44e1aab47`) holds **one**
  network, outlet 3766342, 11,248 segments, at 28.60 N, 95.98 W (Matagorda Bay). It is
  exactly the v3.1.6 CONUS network of that outlet (`check.py` test 7 compares all segment
  ids). NHDPlus names it "Colorado River" (the lower Colorado of Texas). I took this to be
  the network meant by "Little Colorado".
- `test/LowerColorado_TX/test_AnA.yaml` runs it with `parallel_compute_method:
  by-subnetwork-jit-clustered`, `subnetwork_target_size: 10000`, `cpu_pool: 36`.
- **The test case does not route the Brazos with the Colorado.** The Brazos is not in
  that RouteLink. It appears only in coastal-boundary files:
  `test/LowerColorado_TX/domain/coastal_boundary_domain.yaml` lists `3125212: 1964002 #
  in TX` beside `3766342: 252935 # Lower Colorado River`, and
  `test/LowerColorado_TX_v4/domain/coastal_domain_LC_US_DS.yaml` lists "Brazos River, TX"
  among six Texas rivers (with ids that are not RouteLink ids). The "Colorado TX + Brazos"
  scope here is my own union of the two RouteLink networks. Whether a different pairing
  was meant is a question for the author.

## Definitions and assumptions
- **Segment** = one RouteLink row. **Network** = all segments draining to one outlet.
- **Reach** = T-Route's definition: a segment joins the reach of its upstream neighbour
  only if it has exactly one upstream segment (`split_at_junction`,
  [nhd_network.py L278-L290 @12a8eae0](https://github.com/NOAA-OWP/t-route/blob/12a8eae0cdfed437143c590659fa7077605a5e70/src/troute-network/troute/nhd_network.py#L278-L290),
  used by `dfs_decomposition` L503-L557), so #reaches = #headwaters + #junctions. Real
  T-Route also splits reaches at gages and waterbodies when those inputs are given; this
  experiment does not.
- **Subnetworks** = `build_subnetworks`
  ([L691-L771 @12a8eae0](https://github.com/NOAA-OWP/t-route/blob/12a8eae0cdfed437143c590659fa7077605a5e70/src/troute-network/troute/nhd_network.py#L691-L771)).
  - *The search.* A BFS from each outlet, with depth counted in junctions. Once more than
    `min_size` = T segments are reached, the BFS finishes the current junction depth and
    restarts at the cut points. A subnetwork's order is its restart depth, pooled over
    networks.
  - *Upstream order.* The BFS visits upstream segments in ascending feature id, because
    T-Route sorts the parameter frame by id before building the connections
    ([NHDNetwork.py L189](https://github.com/NOAA-OWP/t-route/blob/12a8eae0cdfed437143c590659fa7077605a5e70/src/troute-network/troute/NHDNetwork.py#L189),
    [nhd_network_utilities_v02.py L86](https://github.com/NOAA-OWP/t-route/blob/12a8eae0cdfed437143c590659fa7077605a5e70/src/troute-network/troute/nhd_network_utilities_v02.py#L86)),
    and `reverse_network` keeps that order. `jitsched.upstream_csr` does the same.
  - *Verification.* `check.py` test 5 shows the array replica equals a literal
    transliteration of the T-Route code on random forests with shuffled ids, on the Rio
    Grande (T = 1000 and 10000: 398 and 83 subnetworks), and for the cached CONUS
    decomposition on the Rio Grande.
- **Clustering** per order, pooled over the networks in scope:
  - the old rule
    ([CIROH-UA/t-route @dd43a7d2, compute.py L604-L640](https://github.com/CIROH-UA/t-route/blob/dd43a7d218274c526306041369f4e5e8e76a2cb1/src/troute-routing/troute/routing/compute.py#L604-L640)):
    close a cluster at 0.65 T, no upper bound;
  - the bin packing of CIROH-UA/t-route#26
    ([@8abd3f49, compute.py L602-L643](https://github.com/CIROH-UA/t-route/blob/8abd3f49ce34fe49a37f21fff8032b37084cf82b/src/troute-routing/troute/routing/compute.py#L602-L643)):
    a max-heap on remaining capacity, cap 1.1 T.

  The main grid lists subnetworks in ascending id. T-Route's own dict/set order is
  deterministic in principle but not replicated here; `order_sensitivity.csv` adds five
  random orders.
- **Units and cost.**
  - Primary: by segment, cost 1.
  - Secondary: by reach, with unit cost (`reach_unit`) or cost = segments in the reach
    (`reach_cost`).
  - Secondary: by subnetwork, unclustered (`subnet`), and by clustered subnetwork
    (`cluster_old`, `cluster_bin`), at T = 100, 1000, 10000, 100000, cost = segments.
- **Assumptions.**
  1. Equal cost per segment.
  2. Zero dispatch overhead, except in the sensitivity run.
  3. No memory, cache or communication effects.
  4. Barriers after each JIT stride and each round.
  5. A unit is one indivisible job over the whole simulation; timesteps are not modelled.
  6. Dispatch overhead, when added, is paid by the core that runs the unit.
- **Saturation metrics.**
  - *Idle core-time* = P x makespan - busy core-time, in segment-cycles. With zero
    overhead the busy time is W, so idle = P x makespan - W and makespan = (W + idle) / P.
    For fixed W, minimizing idle core-time and minimizing makespan are the same objective.
  - *Mean utilization* = W / (P x makespan).
  - *Idle in first half* = the share of the idle core-time that falls in the first half
    of the run.
  - *Busy profile* = mean busy cores over 400 equal time bins.
  - *One-core tail* = makespan minus the last instant two or more cores were busy. The
    *structural tail* is the same quantity for Hu's rule with unlimited cores.
- **Performance metrics.** Makespan in segment-cycles; lower bound = max(W / P, critical
  path); speedup = W / makespan.
- **Core counts.** 1, 2, 4, 8, 16, 36, 64, 128, 1024, infinity.

## Unequal costs: measured MC costs on the Potomac (RERUN_PLAN item 2, scheduling part)
`cost_scheduling.py` schedules the Potomac network (outlet 4539621) with per-segment costs
from `../mc_cost_variability/`. The cost unit is the secant iterations of the
Muskingum-Cunge kernel (float32 port), counted per segment from that directory's
`results/cost/` files, which are gitignored there (create them with
`bash ../mc_cost_variability/run.sh`).

**Inputs, verified.** The script asserts that the cost file's 16,454 feature ids are
exactly this study's Potomac scope and that every `to_feature_id` matches RouteLink.

**Cost cases** (true costs):
- a calm 24-h window;
- the storm peak 24-h window (k = 1) for 25, 100 and 250 mm;
- run totals over 40 days for calm, 25 mm and 250 mm.

A 24-h window is the shape of one T-Route subnetwork call (288 steps). Reach and
subnetwork costs are sums over their segments. Clusters are formed by segment count, as
T-Route does, and costed by summed iterations.

**Schedulers** (code label and estimate in brackets):
- the 2020-style rounds, naive first-ready and JIT strides, all given equal-cost estimates;
- work stealing, which is cost-blind;
- Hu's rule with three levels of cost knowledge:
  - equal-cost priorities, i.e. costs unknown (`opp_lrp`, est = equal);
  - calm costs used as estimates while the true cost is the flood's (`opp_lrp`, est =
    calm). These are stale estimates, and the realistic case, because calm cost is static
    and could be precomputed;
  - exact costs, the oracle (`opp_lrp`, est = true);
- cost-aware dynamic (`opp_lrp_dyn`): a unit's own cost is known when it becomes ready,
  and the rest of its path to the outlet is estimated (equal or calm). Since every
  downstream unit is still unfinished at that moment, the priority is fixed on release.

"Equal" means mean calm cost per segment x segments in the unit. All of this is at 8, 36
and 128 cores. Results are in `tables/cost_scheduling.{csv,md}` and
`results/fig_cost_scheduling` (36 cores).

**Results, 36 cores.** Makespan above the lower bound max(W/P, cost-weighted critical
path), in %, with the idle share of core-time in brackets:

| Scheduler | Segments, calm 24 h | Segments, 250 mm peak 24 h | Reaches, 250 mm peak 24 h | Clusters T=1000, 250 mm peak 24 h |
|---|---|---|---|---|
| 2020-style rounds | 60.9 (61%) | 77.0 (52%) | 104.7 (58%) | 1.9 (94%) |
| naive first-ready | 50.2 (58%) | 71.3 (50%) | 71.8 (50%) | 0.0 (94%) |
| JIT strides | 49.7 (58%) | 38.9 (39%) | 179.0 (69%) | 1.1 (94%) |
| work stealing (cost-blind) | 50.1 (58%) | 73.6 (51%) | 73.6 (51%) | 0.0 (94%) |
| Hu, equal-cost priorities (costs unknown) | 0.0 (37%) | 1.3 (16%) | 1.3 (16%) | 0.0 (94%) |
| Hu, calm costs as estimates (stale) | 0.0 (37%) | 2.3 (17%) | 2.3 (17%) | 0.0 (94%) |
| cost-aware dynamic, calm estimates downstream | 0.0 (37%) | 2.2 (17%) | 2.2 (17%) | 0.0 (94%) |
| Hu, exact costs (oracle) | 0.0 (37%) | 0.6 (15%) | 0.6 (15%) | 0.0 (94%) |

**What cost knowledge is worth: very little here.**
- *Segments and reaches.* Across all seven cost cases and 8, 36 and 128 cores, Hu's rule
  with equal-cost priorities stays within 1.3% of the lower bound. The oracle gets within
  0.6%. The calm-cost (stale) estimates within 2.3%.
- *Stale estimates.* In the flood peak, stale calm estimates do slightly worse than
  assuming equal costs (2.3% vs 1.3% at 250 mm), consistent with the cost study's finding
  that the ranking of segment costs reshuffles in the peak window.
- *Cost-aware dynamic.* It behaves like Hu's rule with the same downstream estimates.
- *Policy vs knowledge.* The choice of policy matters far more than the cost knowledge:
  at 36 cores the policies without distance priorities sit 39 to 184% above the bound
  on segments and reaches, under every cost case.
- *Work stealing,* cost-blind and distance-blind, behaves like naive first-ready.

**Is the 2020 equal-cost assumption adequate for the MC kernel? For choosing the
schedule, yes; for predicting run time on many cores, not fully.**
- *Ranking.* With measured costs the ranking of policies is the same as with equal costs,
  and the distance-from-outlet priority stays near-optimal.
- *Run-time prediction.* When the run is bound by the critical path (36 and 128 cores on
  this 16,454-segment network), the equal-cost model underpredicts the makespan in calm
  flow: by 34 to 38% for Hu's rule, and by up to 83% for JIT strides. The longest path (527 segments, 87% mainstem) is costlier per segment
  than average: 1.38 times the mean calm cost, because 54% of it is slope-floor segments
  (16% network-wide), which take about 3.2 iterations per call against 2.1 on steep
  segments (cost study).
- *Floods narrow that gap.* In the storm peak window the per-segment spread shrinks, the
  critical path costs 1.02 times the mean, and the error falls to about 2%.
- *Work-bound case.* At 8 cores (bound by W/P) the equal-cost model is within 0.1% for
  Hu's rule.

**At T-Route's own granularity, cost variation does not matter on this network.** With
clustered subnetworks (T = 1000: 19 jobs; T = 100: 169 jobs, bin packing), the cluster
critical path dominates:
- *The bound.* At T = 1000 the cluster chain sets 5.7 x 10^6 iterations against W/P =
  0.3 x 10^6 at 36 cores, so cores are idle 94 to 98% of the time.
- *T = 1000.* Every policy is within 0 to 3% of the bound at 8, 36 and 128 cores.
- *T = 100.* At 8 cores the policies still differ: rounds 34 to 41% above the bound,
  naive 29 to 36%, work stealing 16 to 23%, JIT strides 8 to 13%, and every Hu variant
  0%. From 36 cores on, all are within 0 to 7%.
- *Cost knowledge.* In none of these cases does it change the Hu variants' result.
- *Equal-cost prediction.* Within -1.5% to +3.9% at T = 1000, and -3.6% to +12.9% at
  T = 100.

The limit at that granularity is the decomposition, not the costs.

**Caveats.**
- The storm is synthetic and spatially uniform, on one network; uniform rain is the
  weakest spatial clustering of cost a real event could have.
- Costs are the float32 port's iteration counts, not timed compiled-kernel calls, and
  T-Route's per-segment overhead outside the kernel is not included.
- No waterbodies or data assimilation; dt = 300 s.
- Zero dispatch overhead and no memory effects, as everywhere in this study.

**How the hooks plug in.**
- `Graph.cost` takes any per-unit cost vector.
- `schedule(..., est_cost=...)` separates what the scheduler believes from the true
  durations (`check.py` test 2b).
- `opp_lrp_dyn` is the cost-aware dynamic policy. `check.py` verifies that with exact
  estimates it equals Hu's rule, and that it is valid with unit estimates.
- `work_steal` is a deterministic, cost-blind work-stealing sketch.

## Validation (`uv run check.py`, all pass)
1. An independent numpy validator checks every schedule: dependencies respected, no core
   double-booked, core ids in range, strides and rounds ordered and not overlapping,
   makespan at least the critical path and total work / P.
2. 7,320 schedules on random trees and layered DAGs, all policies, with overhead. The
   rounds are checked against levels computed independently.
   - 2b. The JIT timetable reaches the critical path with unlimited cores, and the
     estimated-cost hook behaves as specified.
3. Brute-force optimum on 240 tiny unit-cost in-tree cases: Hu's rule is always optimal,
   and no policy ever beats the optimum. This is Hu's result for unit-time in-trees: T. C.
   Hu, "Parallel Sequencing and Assembly Line Problems", Operations Research
   9(6):841-848, 1961, DOI 10.1287/opre.9.6.841, resolved through Crossref 2026-10-29.
   - 3b. The Hu priority equals the cost-weighted distance from the outlet on in-forests.
4. The graph agrees with `../network_stats/expected/expected.json`.
5. The subnetwork replica equals the literal T-Route code; the clustering rules reproduce
   PR #26's example (300, 340, 1400, 300 at T = 1000: old 2040/300, new 940/1400).
6. 224 full-size schedules validated (Rio Grande at six granularities, Mississippi by
   segment, all policies).
7. The t-route test-case RouteLink equals the network of outlet 3766342.

`run_experiments.py` also asserts makespan >= lower bound in every run.

## Secondary results
All runs: `results/results.csv`. Short names: rounds = 2020-style rounds; naive = naive
first-ready; JIT = JIT strides; Hu = Hu's rule.

### Worked example (`fig_worked_example`)
15 segments, 3 cores, unit cost. Makespan: rounds 9 cycles, naive 8, JIT 7, Hu 7. Lower
bounds: work/P = 5, critical path = 7. The last 3 segments of the mainstem (m2, m1, m0)
run on one core under every policy, even with unlimited cores.

### Reaches
**Unit cost per reach.** Mississippi makespan, rounds / naive / Hu / JIT:
- 36 cores: 25,916 / 25,723 / 24,161 / 25,214 (bound 24,129);
- 128 cores: 8,774 / 8,669 / 6,854 / 7,950;
- 1,024 cores: 2,991 / 2,961 / 2,219 / 2,219.

With unlimited cores every policy takes 2,219 cycles (the reach depth), and CONUS speeds
up by 2,114,380 / 2,219 = 953x. This matches the AGU 2020 poster's "about 1000x"
arithmetic ("2.1M / 2218 (i.e., ~1000x)",
[`doc/AGU_Poster.md` L225-228](https://github.com/NOAA-OWP/t-route/blob/0d512ba026e3b10a432fb707fc80655a6c2f63e2/doc/AGU_Poster.md#L225-L228)). The policies
differ in how many cores they need to get close to that.

**Cost = segments per reach.** JIT strides counted in reach hops wait for the longest
reach in each stride. Mississippi, rounds / naive / Hu / JIT strides (hops) / JIT
timetable (segment distance):
- 36 cores: 35,064 / 33,290 / 31,118 / 33,709 / 31,234;
- 128 cores: 13,681 / 11,442 / 8,864 / 16,833 / 9,183;
- 1,024 cores: 6,923 / 4,133 / 3,174 / 16,086 / 3,174.

Ordering reaches by segment distance recovers the segment results exactly
(`tables/reach_vs_segment.md`).

### Clustered subnetworks (the T-Route modes), 36 cores
Mississippi makespan, rounds / naive / Hu / JIT / JIT list order. For the old rule, the
range over five random listing orders is in brackets.

| T | Rule | Units | Makespan |
|---|---|---:|---|
| 100 | unclustered | 28,930 | 48,961 / 47,154 / 31,908 / 36,708 / 43,648 |
| 100 | bin packing | 10,625 | 48,871 / 46,946 / 31,936 / 41,650 / 42,990 |
| 1,000 | unclustered | 7,792 | 74,316 / 72,695 / 51,441 / 54,668 / 65,308 |
| 1,000 | old rule, ascending id | 1,062 | 87,606 / 77,725 / 64,715 / 77,755 / 82,586 |
| 1,000 | old rule, 5 shuffled orders | | [84,504-85,647] / [82,605-83,591] / [73,520-74,495] / [75,990-77,207] / [79,435-81,851] |
| 1,000 | bin packing | 1,107 | 73,607 / 71,697 / 52,037 / 63,604 / 64,214 |
| 10,000 | old rule, ascending id | 118 | 210,383 / 190,679 / 183,546 / 200,784 / 200,784 |
| 10,000 | old rule, 5 shuffled orders | | [201,549-211,033] / [194,890-210,910] / [188,096-204,311] / [194,769-207,202] / same as JIT |
| 10,000 | bin packing | 115 | 164,193 / 163,728 / 153,804 / 159,395 / 159,395 |

- **Small subnetworks are not uniform.** At T = 100, unclustered Mississippi subnetworks
  have mean 38.6 segments, sd 42.2, max 203 (`tables/cluster_stats.csv`). JIT finishes 18%
  above the bound and rounds 58% above. The "bottleneck towards the end" that PR #188
  attributes to opportunistic ordering is the structural tail not being overlapped:
  naive spends its last 10,693 cycles on one core, against a structural 10,747.
- **Listing order.** With the old rule, ascending id is an outlier: in all five shuffled
  orders JIT beats naive (75,990-77,207 vs 82,605-83,591). Ascending id also flatters Hu
  (64,715 vs 73,520-74,495). The order-robust results are that Hu's rule is fastest and
  JIT beats rounds. With bin packing the order matters little
  (`tables/cluster_order_ranges.md`).
- **Within-stride order.** List order instead of longest-first costs JIT 1% (bin packing,
  T = 1000) to 6% (old rule), and about 20% for unclustered subnetworks.
- **Threshold.** With bin packing, Mississippi JIT speedup at 36 cores is 26.8 (T = 100),
  17.6 (T = 1000), 7.0 (T = 10000) and 2.4 (T = 100000). The Texas Colorado gets at most
  1.79x at T = 1000 (13 clusters). At the test case's own T = 10000 it splits into 2
  chained clusters, so no policy gets any parallel speedup.
- **Balancing (PR #26).**
  - *Cluster sizes.* Standard deviation on the Mississippi: 307 segments (old rule) vs 89
    (bin packing) at T = 1000; 3,749 vs 1,495 at T = 10000. The PR reports 318.13 vs
    88.74 without stating the domain or target size, so the closeness is suggestive, not
    a confirmation.
  - *Makespan.* JIT with bin packing vs the old rule, over all listing orders: 16 to 18%
    shorter at T = 1000, 18 to 24% shorter at T = 10000.
  - *The PR's "nearly 45% faster".* It compares measured runs of unstated size and core
    count, so the model's equivalent (68% shorter) is not comparable.

### Dispatch overhead (`results/overhead_sensitivity.csv`, `fig_overhead_sensitivity`)
Speedup over serial, Mississippi, 36 cores; the overhead o is in units of one segment's
compute, per dispatched unit:

| Unit, policy | o = 0 | 0.1 | 0.3 | 1 | 3 | 10 | 30 |
|---|---:|---:|---:|---:|---:|---:|---:|
| segment, Hu | 35.9 | 32.6 | 27.6 | 18.0 | 9.0 | 3.3 | 1.2 |
| segment, JIT | 34.3 | 31.2 | 26.4 | 17.1 | 8.6 | 3.1 | 1.1 |
| segment, rounds | 33.3 | 30.2 | 25.6 | 16.6 | 8.3 | 3.0 | 1.1 |
| reach (cost), Hu | 35.9 | 33.3 | 29.1 | 20.2 | 10.8 | 4.1 | 1.5 |
| reach (cost), JIT | 33.1 | 31.0 | 27.3 | 19.2 | 10.3 | 3.9 | 1.4 |
| clustered T = 1000, Hu | 21.5 | 21.5 | 21.5 | 21.5 | 21.4 | 21.3 | 20.9 |
| clustered T = 1000, JIT | 17.6 | 17.6 | 17.6 | 17.6 | 17.5 | 17.4 | 17.1 |
| by network | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |

- **Where clustering wins.** By-reach beats clustering at T = 1000 only while o stays
  below a value between 0.3 and 1 (Hu) or between 1 and 3 (JIT). This supports, as a
  mechanism, the reason
  [NOAA-OWP/t-route#175](https://github.com/NOAA-OWP/t-route/pull/175) gave for grouping
  reaches into subnetworks and clustering them: per-reach parallel calls cost more
  overhead than they saved.
- **Barrier cost.** Adding a cost equal to o per JIT stride changes the Mississippi and
  CONUS little (3,174 strides by segment, 2,219 by reach).
- **No calibration.** T-Route's real overhead was not measured here.

### rs_route
[`rs_route/src/routing.rs` @1ed548a, L145-L212](https://github.com/CIROH-UA/rs_route/blob/1ed548a249aa7031a5fc1f625003b5459520369d/src/routing.rs#L145-L212)
(fetched 2026-10-29):
- A scheduler thread drains `ready_nodes` into a shared work queue on every loop
  iteration.
- A node made ready is pushed with `push_front` ("Prioritize downstream nodes to free
  inflow buffers sooner").
- Because the list is drained after each completion, at most one such node is in it at a
  time, so the queue the workers see is first-ready, first-served. That is naive
  first-ready here.

This is my reading of the code, not a run of rs_route. If it is right, rs_route's
reported speed-up (12x over T-Route on a Mississippi NextGen subset;
[NOAA-OWP/t-route#874](https://github.com/NOAA-OWP/t-route/issues/874#issuecomment-4270274683))
would have to come from
factors outside this model:
- its unit is a node over all timesteps, which amortizes dispatch;
- there are no barriers;
- T-Route's 55.89 s total in that comparison includes non-routing time.

## Limitations
- This is a scheduling model, not a T-Route run; there are no measured timings.
- Equal cost per segment is assumed except in the Potomac measured-cost section.
- T-Route's own listing order of subnetworks is not replicated; it matters for the old
  clustering rule.
- Not modelled: waterbody and gage reach splits, reservoirs, and the serial diffusive loop.
- Dispatch overhead is a free parameter. Memory and cache effects are not modelled.
- The 2020 spreadsheet is unavailable. `opp_rounds` reconstructs its opportunistic method
  from `nhd_reach_parallel_test.py`; its numbers are not replicated.
- Only the NWM v3.1.6 CONUS RouteLink was used.
