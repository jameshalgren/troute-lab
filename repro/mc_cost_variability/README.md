# How much does one Muskingum-Cunge call cost? Calm vs flood on the Potomac

*AI-assembled (Claude), 2026-10-30, for item 2 of
[`../jit_scheduling/RERUN_PLAN.md`](../jit_scheduling/RERUN_PLAN.md) (measurement part);
not yet reviewed by the author.*

## Question

The scheduling study in [`../jit_scheduling/`](../jit_scheduling/README.md) assumes every
segment costs the same. The author points out that significant floods "take at least
slightly longer to converge in each calculation" (2026-10-30; `../jit_scheduling/RERUN_PLAN.md`). T-Route's
Muskingum-Cunge (MC) kernel solves for depth with a secant iteration (`secant2_h`, called
from `muskingcungenwm`), so the work per call depends on the flow. How large is that
variation, calm vs flood, call by call, segment by segment, and over the chunk of
timesteps that T-Route computes in one call per subnetwork? And how spatially clustered
is it? The answer is a measured cost per segment (and per segment per window) for the
scheduling model.

## Method

**Case.** The Potomac case of [`../short_ts_switch/`](../short_ts_switch/README.md)
(`potomac_storm`): all 16,454 segments upstream of NWM v3.1.7 feature 4539621, synthetic
storm released as a gamma pulse (shape 3, scale 4 h) from hour 24, baseflow 0.01 m³ s⁻¹
km⁻², 40 days, dt = 300 s, initial state the exact baseflow steady state. Its inputs are
rebuilt by `make_case.py` with that experiment's own `make_inputs.py`, imported read-only
(`extract_potomac`, `topology`, `storm_series`, `steady_state`). Only the storm depth
changes between scenarios:

| Scenario | Storm runoff | `assume_short_ts` | Role |
|---|---|---|---|
| `calm` | 0 mm (baseflow only) | True | calm reference: the steady state every storm starts from |
| `s25` | 25 mm | True | the existing `potomac_storm` forcing |
| `s100` | 100 mm | True | large flood (outlet peak 13,200 m³/s) |
| `s250` | 250 mm | True | stress test (outlet peak 46,500 m³/s, far beyond any recorded Potomac flood) |
| `s25_f`, `s250_f` | 25, 250 mm | False | check of the other setting |

`assume_short_ts = True` is the primary case: it is the NWM-parity setting that every
distributed T-Route configuration uses (`../short_ts_switch/README.md`, "Question").

**Routing with a counting kernel instead of T-Route.** T-Route could not be built on the
machine used: no Fortran compiler or netCDF-Fortran (`gfortran`, `nf-config` not found,
2026-10-30). The compiled kernel would not report its iterations anyway:
`muskingcungenwm` returns only qdc, velc, depthc, ck, cn and X; `iter` and `tries` are
locals ([`MCsingleSegStime_f2py_NOLOOP.f90` L8-9, L24-25, L32-33 @ d29f663](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90#L8-L33)).
So the network is routed by the float32 kernel port of `../short_ts_switch/`, in
T-Route's order and with T-Route's inputs (`simulate.py`):

- every step, every segment upstream before downstream; qup = float32 sum of the upstream
  flows at t−1 in ascending feature id, quc = qup (True) or the same sum at t (False),
  qdp and depthp the segment's own previous flow and depth, ql the hourly lateral inflow
  ([`mc_reach.pyx` L502-514, L733, L748 @ d29f663](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/troute-routing/troute/routing/fast_reach/mc_reach.pyx#L502-L514));
  the same semantics `../short_ts_switch/closure_replay.py` uses to replay T-Route
  recordings;
- the kernel is `mc_count.py`: a copy of `../short_ts_switch/closure_port.py` (the
  corrected kernel, `../kernel_fixes/patches/0001-0008`, Qj_0 = 0) whose helper functions
  are that file's text verbatim, with `mc_kernel`'s diagnostics replaced by work counters.

**What is counted, per call** (`counts.npz`):

| Counter | Kernel code | Cost |
|---|---|---|
| `n_iter` | passes of the secant loop, summed over all restarts ([L83-123](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90#L83-L123)) | 2 `secant2_h` calls each (L92-95) |
| `n_restart` | jumps back to label 110: collapsed-search restarts (patch 0008) and non-converged retries ([L126-133](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90#L126-L133), patches 0002-0007) | each adds a new loop with maxiter + 25 |
| `fail` | fifth try reached; corrected kernel holds the previous depth (patch 0007) | 2 more `secant2_h` calls |
| `guard` | negative-flow guard ([L149-158](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90#L149-L158)) | O(1) |

Everything else in a call is fixed work. `n_iter` is the cost proxy; `timing.py` tests it
against measured time.

**Chunk windows.** T-Route calls each unit once per forcing loop and runs all of the
loop's steps inside that call: `compute_network_structured` loops
`while timestep < nsteps+1: for i in range(num_reaches)`
([`mc_reach.pyx` L502-503](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/troute-routing/troute/routing/fast_reach/mc_reach.pyx#L502-L503)),
and the parallel modes dispatch `delayed(compute_func)(nts, ...)` per subnetwork or
cluster ([`compute.py` L555, L790-791](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/troute-routing/troute/routing/compute.py#L555)).
The loop length is `max_loop_size`, default 24 h, with `qts_subdivisions` = 12 and
dt = 300 s ([`compute_parameters.py` L431, L436, L445](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/troute-config/troute/config/compute_parameters.py#L431-L445));
`../short_ts_switch/run_troute.py` uses the same 24 h. So the default unit of work is
one segment over **288 steps (24 h)**. Costs are also aggregated over 1 h (12 steps, one
forcing interval), 3 h (36) and the whole 40-day run (11,520).

**Conventions.** Per-call statistics leave out the first hour: T-Route's lite restart
starts every depth at 0, so the first secant searches are artificial (as in
`closure_replay.py`). Window and run totals include every step, as T-Route would run
them. "Flood calls" are calls whose segment flow (end of the hour) is at least twice its
baseflow; "rising" when that flow is higher than the hour before.

## Verification

1. **The counting copy is the port.** Every call of every run (6 × 189,550,080) was
   replayed from the stored trajectories through the unmodified
   `../short_ts_switch/closure_port.mc_kernel`: outflow and depth bitwise identical, and
   its own iteration and try counters equal to `mc_count`'s, in all 1.14 × 10⁹ calls
   (`verify.json`; `check.py` 1).
2. **Port-driven routing reproduces T-Route** (25 mm, against T-Route's own values for
   this case in `../short_ts_switch/expected/`, corrected kernel):

   | Quantity | True: port / T-Route | False: port / T-Route |
   |---|---|---|
   | outlet peak (m³/s) | 2195.560 / 2195.560 (rel 2 × 10⁻⁷) | 1583.62 / 1586.02 (rel −1.5 × 10⁻³) |
   | outlet event volume balance | 1.0053 / 1.0053 | 0.9094 / 0.9127 |
   | K clamp / X floor / overbank, share of segment-steps | 0.05266 / 0.18409 / 0.15751 vs 0.05266 / 0.1841 / 0.1575 | 0.05262 / 0.18413 / 0.15811 vs 0.05262 / 0.1841 / 0.1581 |
   | negative-flow guard steps | 0 / 0 | 664 / 686 |
   | outlet peak-time shift True − False | −77.68 h / −77.56 h | |

   With True the port reproduces T-Route to float32 noise. With False it drifts slightly:
   the port and the compiled kernel differ in float32 rounding on a few hundred calls,
   which can send a call down a different restart branch
   (`../short_ts_switch/README.md`, "Kernel update"), and here the port's own outflow
   feeds the next segment, so the difference travels downstream (outlet peak 1.5 steps
   later). `check.py` 2 applies `../short_ts_switch/check.py`'s tolerances, except 0.25 h
   instead of 0.083 h for the peak-time shift.
3. **`replay_record.py`**, which counts the work on a T-Route recording
   (`../short_ts_switch/closure_record.py` format), reproduces `simulate.py`'s counts
   exactly when fed `simulate.py`'s own trajectory in that format (self-test).
4. **What was not verified:** iteration counts of the compiled kernel itself. They can be
   counted directly with `../kernel_fixes/`: `kernels.instrument()` adds per-call event
   counters to the Fortran (ev(8) = secant iterations, ev(4) retries, ev(9) collapse
   restarts, ev(5) abandoned searches) and `harness/driver.F90` built with `-DTRACE`
   writes them per call. Feeding it a sample of these runs' calls would compare compiled
   and ported counts call by call; it needs gfortran.

## Results

All numbers from `tables/` (generated by `analyze.py` and `timing.py`).

**1. Per call: a flood call does about 25% more secant work.** (`tables/iterations_per_call.md`)

| Calls | Mean iterations | 1 | 2 | 3 | 4 | 5 | 6 | ≥ 7 | Max | Restarts per 10⁶ calls |
|---|---|---|---|---|---|---|---|---|---|---|
| calm run, all | 2.33 | 0.12% | 75.2% | 18.8% | 4.1% | 1.3% | 0.5% | 0 | 6 | 91 |
| 25 mm, flood | 2.91 | 0.05% | 30.4% | 55.7% | 8.3% | 3.7% | 1.8% | 0.06% | 155 | 610 |
| 25 mm, flood rising | 3.04 | 0.14% | 20.7% | 62.6% | 10.8% | 3.8% | 1.9% | 0.07% | 155 | 860 |
| 100 mm, flood | 2.90 | 0.08% | 23.6% | 67.1% | 5.8% | 2.3% | 1.0% | 0.05% | 142 | 442 |
| 250 mm, flood | 2.88 | 0.08% | 23.3% | 69.4% | 4.4% | 1.9% | 0.8% | 0.05% | 388 | 563 |

- The typical calm call takes 2 iterations, the typical flood call 3. Bigger storms do
  not raise the mean further (2.88–2.91 for 25–250 mm).
- Long searches are rare and come during the storm: calls with ≥ 10 iterations are 410
  of 1.9 × 10⁸ (on 66 segments, hours 25–58) at 25 mm, 321 (97 segments) at 100 mm and
  760 (549 segments, hours 24–109) at 250 mm. Worst / mean per call: 2.6 calm, 66
  (25 mm), 165 (250 mm).
- Restarts of the depth search happen on 2 segments in the calm run (at every step) and
  on 1,643 (25 mm) / 3,235 (250 mm) segments in the storms, nearly all steeper than
  10⁻³. Extra restarts peak on the storm's first day (4,738 restarts against 432 in a
  calm day at 25 mm).
- **The kernel's cost has a memory.** After the storm, with every segment back within
  1% of its baseflow, 4 steep first-order headwaters (feature ids 22341005, 5891626,
  22339621, 22340919) restart at every step for the rest of the run, which they never
  do in the calm run, and 204–211 segments end the run with a different iteration count
  per step than before the storm (`tables/summary.json`,
  `long_searches_restarts_and_history`). A likely reason (not tested): the secant stops
  anywhere within its 1% tolerance (Fortran L83), and each step starts from the
  previous depth, so the depth a segment carries after a flood need not be the one it
  had before.
- With `assume_short_ts = False` the tail is much longer: 6,577 (25 mm) and 19,757
  (250 mm) calls take ≥ 10 iterations, and 133 / 1,079 calls exhaust every restart
  (981 iterations, the largest possible: 101 + 126 + 151 + 176 + 201 + 226 passes),
  along with the negative-flow guard steps (`../short_ts_switch/README.md`, "Closure
  diagnostics").

**2. Over time: up to 40% more work network-wide in the storm's peak hour, about 1% over
the run.** (`results/figs/fig_hourly_network_cost.png`, `tables/hourly_network_cost.csv`)
Network-wide, iterations per hour peak at 1.41× calm (25 mm), 1.41× (100 mm) and 1.44×
(250 mm), 1–4 h after runoff starts, and stay above 1.05× for 31, 38 and 43 hours
(`tables/windows.csv`, 1-h rows). Over the 40 days, total work rises only 0.8% (25 mm)
to 1.1% (250 mm).

**3. Per segment: cost differs by segment even in calm flow, and that difference is
static.** (`tables/segment_totals.md`)

| Run total per segment | calm | 25 mm | 100 mm | 250 mm |
|---|---|---|---|---|
| CV across segments | 0.278 | 0.262 | 0.259 | 0.256 |
| worst / mean | 2.58 | 2.50 | 2.48 | 2.47 |
| cheapest / mean | 0.43 | 0.44 | 0.44 | 0.44 |
| Spearman with calm | 1 | 0.80 | 0.81 | 0.81 |

- In the calm run 97.4% of segments use the same number of iterations at every step.
- The difference follows the channel: segments at RouteLink's slope floor (S0 = 10⁻⁵)
  average 3.2 iterations per call, segments steeper than 10⁻³ 2.1. Slope class explains
  46% of the variance of the calm per-segment cost (η²), stream order 29%, tributary 7%,
  distance to outlet 5%. 53% of the costliest decile are slope-floor segments.

**4. Chunk windows: aggregation removes the single-call spikes, and floods make units
more alike, not less.** (`tables/windows.md`, `results/figs/fig_cost_vs_window.png`).
Unit = one segment over the window; "peak window" = the window where the storm adds most
work (hours 24–48 for 24-h windows). Calm has no peak window; its column is the median
window (every calm window is the same apart from the first, which holds the restart
transient).

| Unit | calm: CV / worst÷mean | 25 mm peak window: CV / worst÷mean | 25 mm peak window, network cost ÷ calm | unit cost ÷ its calm cost, 25 mm, peak window: max / min | Spearman with calm cost, peak window |
|---|---|---|---|---|---|
| one call | 0.29 / 2.6 | 0.29 / 66 (whole run) | – | – | – |
| 1 h (12 steps) | 0.28 / 2.6 | 0.20 / 2.3 | 1.41 | 10.0 / 0.38 | −0.04 |
| 3 h (36) | 0.28 / 2.6 | 0.15 / 2.1 | 1.40 | 7.0 / 0.42 | −0.14 |
| **24 h (288, T-Route default)** | **0.28 / 2.6** | **0.12 / 1.8** | **1.30** | **2.7 / 0.48** | **0.00** |
| 40 days | 0.28 / 2.6 | 0.26 / 2.5 | 1.01 | 2.0 / 0.85 | 0.80 |

- Over a 24-h window the 66× single-call worst case disappears: in the storm's peak
  window the worst unit is 1.8× (25 mm), 1.5× (100 mm) and 1.5× (250 mm) the mean;
  over all 40 windows the worst is 2.65–2.85× the mean, i.e. the static calm spread.
- In the flood window most segments move to 3 iterations per call, so the spread across
  segments drops from CV 0.28 to 0.12 (25 mm), 0.07 (100 mm) and 0.09 (250 mm).
- But *which* segments are expensive changes: in the peak window, unit cost is
  uncorrelated with the same segment's calm cost (Spearman 0.00 at 25 mm, −0.21 at
  100 mm, −0.18 at 250 mm). Slope-floor segments get cheaper in the flood (0.93× calm),
  steep ones dearer (1.44×). A scheduler that learned costs in calm weather would
  misjudge the flood window, but not by much: pooled over all 24-h units of a storm run,
  98% cost between 0.96× and 1.55× their calm cost (extremes 0.38–0.48× and 2.7–3.1×).
- With False, single searches that exhaust every restart make a few units very
  expensive: worst 24-h unit 7.3× the mean of its window (25 mm), 1-h unit 43×.

**5. Spatial clustering.** (`tables/spatial.md`, `results/figs/fig_space_time_s25.png`)
- *Static (calm) cost* clusters along flow paths: a top-decile segment's downstream
  neighbour is top-decile 3.6 times as often as chance. It sits on slope-floor and
  high-order channels (the lower basin: 0–50 km from the outlet averages 2.9 iterations
  per call, 500–700 km 2.2; orders 4–7 3.0–3.2, orders 1–2 2.1–2.2), not in particular
  tributaries (η² 0.07). Statistics from the calm run's last 24-h window
  (`clustering_peak_24h_window` in `tables/summary.json`).
- *Flood excess* in the peak 24-h window (25 mm): every major tributary does 1.24–1.39×
  its calm work, the mainstem 0.98× and the lowest 50 km 1.04×. Tributary explains 4.5%
  of the variance of the excess, slope class 40%; the top decile of segments holds 20%
  of the positive excess; excess clusters along flow paths (lift 4.6).
- *In time*, the extra work is concentrated in the storm's first one to two days at
  every distance from the outlet (`fig_space_time_s25.png`): the storm's lateral inflow
  reaches every segment at once, and most segments are small channels that respond
  within hours. As the flood moves into the lower basin, the segments of the lowest
  50 km (60% at the slope floor, against 16% network-wide) get *cheaper* than calm, not
  dearer: below 0.98× from hour 51 to 126, minimum 0.93× (25 mm; 0.85× at 250 mm).
- This is the clustering a spatially uniform storm produces. A real storm on part of
  the basin would concentrate the excess in the subbasins it hits.

**6. Iterations predict the port's run time well.** (`results/timing.json`,
`tables/timing_*.csv`, `results/figs/fig_timing.png`) Single thread, Apple-silicon Mac,
float32 port (numba), minimum of 3 repetitions per unit; numbers from the final run,
with the range over the two full runs made where they differ:
- per call, time grows about linearly, 44–49 ns per secant iteration with almost no
  fixed part (25 mm: 1 iteration 45 ns, 2: 83 ns, 3: 130 ns, 4: 191 ns; per-class fit
  R² 0.999 for the storms, 0.90 calm, which has only six classes). It is not exactly
  linear: 5-iteration calls (275 ns) cost more than 6-iteration calls (238 ns), so the
  path through the kernel matters too, not only the count. The calm classes ran about
  10% slower than the storm classes in the final run (93 vs 83 ns at 2 iterations) and
  not in the first, which gives the size of run-to-run timing noise;
- per 24-h unit, `time = a·calls + b·iterations` explains 88–96% of the variance of
  measured unit time (b ≈ 50 ns per iteration), and the proportional model
  `time = c·iterations` (c ≈ 42 ns), which is what a scheduler using iteration counts
  assumes, 85–93%. Much of the rest looks like timing outliers (units measured far
  above the line at the same iteration count, the vertical streaks in `fig_timing.png`). Measured unit times vary somewhat more than iterations
  (CV 0.34–0.36 vs 0.27–0.28).
- The port is not the compiled kernel: T-Route's compiled kernel also computes velocity
  and calls `courant` after the loop (L169, L183), and T-Route adds per-segment Cython
  work (buffer fill, upstream sums) that does not depend on iterations. Both dilute the
  relative variation. For scale: T-Route's whole serial run of this case took 61.4 s
  (`../short_ts_switch/README.md`, "Cost"; published kernel, 2026-10-07), at most
  324 ns per segment-step all included, against 95–97 ns per call for the port's kernel
  alone. How much of T-Route's time per segment-step the secant loop takes was not
  measured.

## Cost vectors for `../jit_scheduling/`

Written by `analyze.py` into `results/cost/` (gitignored; `./run.sh` regenerates them in
about 7.5 minutes, or 4 without timing). Segment ids are NWM v3.1.7 feature ids of the
Potomac network (the `link` of `RouteLink_CONUS.nc`, the same ids as
`../jit_scheduling/`'s RouteLink graph); `to_feature_id` is RouteLink `to`, 0 at the
outlet 4539621.

`results/cost/segment_cost.csv`, one row per segment (16,454 rows):

| Column | Meaning |
|---|---|
| `feature_id`, `to_feature_id` | segment and its downstream segment |
| `dist_to_outlet_km`, `n_down`, `up_path_segs`, `order`, `slope_class`, `subbasin`, `mainstem` | topology and channel class (slope class 0 = RouteLink floor 10⁻⁵, 1 < 2.5 × 10⁻⁴, 2 ≤ 10⁻³, 3 > 10⁻³; subbasin = tributary of ≥ 300 segments, by the feature id of its mouth, or `mainstem` / `minor_tributaries`) |
| `calls` | kernel calls per segment in the run (11,520) |
| `iters_<scenario>` | total secant iterations over the run, all steps (integer ≥ 1): the cost |
| `rel_<scenario>` | `iters_<scenario>` divided by the calm mean over segments (26,810.7): cost relative to an average calm segment |
| `port_us_<scenario>` | measured port time over the run (µs, sum of the 24-h units), for `calm`, `s25`, `s250` |

`results/cost/segment_window_cost_<scenario>.npz`, per segment per window:
`feature_id`, `to_feature_id`, `iters_1h` (16,454 × 960), `iters_3h` (× 320),
`iters_24h` (× 40; window k covers steps 288k to 288k + 287, i.e. hours 24k to 24k + 24),
`iters_run`, `steps_*` (window lengths), `dt_s`, `scenario`, `storm_mm`,
`assume_short_ts`, and for timed scenarios `port_ns_24h` (measured port time per 24-h
unit). Row order is that of `segment_cost.csv`.

For `jitsched.Graph.cost` (positive integers) the iteration totals can be used directly,
or rescaled, e.g. `max(1, round(100 · iters / mean))`. A schedule of the 24-h loops is
`iters_24h[:, k]`; the storm's peak loop is k = 1 in every storm run.

## Caveats

- **Synthetic, spatially uniform storm** on **one network**, scaled by channel length
  (no catchment areas; `../short_ts_switch/README.md`, "Caveats"). Uniform rain gives the
  weakest spatial clustering a real event could have; 250 mm is far beyond the Potomac's
  record. The calm run is a steady state, the most regular case possible.
- **Port vs compiled kernel.** Counts are the float32 port's. With True the port-routed
  network reproduces T-Route's outlet to 2 × 10⁻⁷ and its closure statistics to the
  digits stored; call-by-call iteration counts of the compiled kernel were not checked
  (Verification 4). With False the trajectories drift slightly and the long tail depends
  on float32 branch choices.
- **Timing** is the port on one Apple-silicon Mac, single thread; the compiled kernel and
  T-Route's per-segment overhead (velocity, Courant number, Cython buffers) are not
  timed and would dilute the variation in time.
- **Corrected kernel only** (`../kernel_fixes/`, patches 0001–0008, the default build of
  `../short_ts_switch/`). The published d29f663 kernel has different restart logic and
  an uninitialized read (fixed by `../kernel_fixes` patch 0001) that changes its
  iteration path.
- **No waterbodies, no data assimilation**, NHD network, dt = 300 s; the first hour is a
  restart transient (depth 0).
- Flow-state classes use end-of-hour flows; the ≥ 2 × baseflow threshold is a choice.

## Candidate claims

- **MC-cost-1.** On the Potomac network (NWM v3.1.7, 16,454 segments, dt = 300 s,
  `assume_short_ts` = True, corrected kernel), a Muskingum-Cunge call takes 2.33 secant
  iterations on average at baseflow and 2.9 during a flood (flow ≥ 2× baseflow): about
  25% more work per call; the typical count goes from 2 to 3. Source:
  `repro/mc_cost_variability/tables/iterations_per_call.md`. Caveat: float32 port;
  synthetic uniform storm.
- **MC-cost-2.** Kernel cost per segment varies even in calm flow (CV 0.28 across
  segments, costliest 2.6× the mean), and the variation is static: 97% of segments
  repeat the same iteration count at every step; slope-floor segments average 3.2
  iterations, steep ones 2.1. Source: `tables/segment_totals.md`, `tables/spatial.md`.
- **MC-cost-3.** A uniform storm of 25–250 mm raises network-wide kernel work by 41–44%
  in its peak hour and 25–30% over T-Route's default 24-h loop, but by about 1% over a
  40-day run. Source: `tables/windows.md`, `tables/hourly_network_cost.csv`.
- **MC-cost-4.** Over T-Route's 24-h loop, a flood makes segment costs more alike (CV
  0.28 → 0.07–0.12) but reshuffles which segments are expensive (Spearman with calm cost
  −0.21 to 0.00); 98% of segment-loops cost 0.96–1.55× their calm cost. Source:
  `tables/windows.md`, `tables/windows.csv`.
- **MC-cost-5.** Single calls can take 155 (25 mm) to 388 (250 mm) iterations, 66–165×
  the mean, but these are rare (≤ 760 of 1.9 × 10⁸ calls with ≥ 10 iterations) and
  vanish in 24-h aggregation (worst segment-loop ≤ 2.9× the mean over all loops, ≤ 1.8×
  in the storm's peak loop). With `assume_short_ts` = False, 133–1,079 calls exhaust
  every restart (981 iterations). Source: `tables/iterations_per_call.md`,
  `tables/windows.md`.
- **MC-cost-6.** In the float32 port, run time per call is roughly 44–49 ns per secant
  iteration with almost no fixed part, and iterations explain 85–96% of the variance of
  measured time per segment-loop (proportional or linear model). Source:
  `results/timing.json`, `tables/timing_*.csv` (machine-dependent, noisy between runs;
  not the compiled kernel).
- **MC-cost-7.** The kernel's per-step cost depends on history: after a 25 mm or 250 mm
  storm, with all flows back to baseflow, 4 steep headwater segments restart the depth
  search at every step (never in the calm run) and 204–207 segments end with a different
  iteration count per step than before the storm. Source: `tables/summary.json`,
  `long_searches_restarts_and_history`. Caveat: the cause (depth tolerance band) is a
  hypothesis, not tested.

## How to run

```bash
repro/mc_cost_variability/run.sh            # everything, 7 min 22 s (3 jobs, 10-core Apple-silicon Mac, 2026-10-30)
TIMING=0 repro/mc_cost_variability/run.sh   # without the timing study
```

Needs only `uv`. The RouteLink file is the SHA-256-verified copy of
`../network_stats/data/` or `../short_ts_switch/data/` if present; otherwise
`fetch_data.py` downloads it into `data/`. Steps: `fetch_data.py` → `make_case.py`
(`data/inputs/potomac/`) → `simulate.py <scenario>` × 6 (about 25 s routing + 12 s
verification replay each) → `replay_record.py --self-test s25` → `timing.py` (about
1 min per scenario plus routing; run alone) → `analyze.py` → `figures.py` → `check.py`.
On a machine with T-Route built (`../short_ts_switch/run.sh`), `replay_record.py
<record_dir> <name>` counts the work on a `closure_record.py` recording, i.e. on T-Route's
own trajectories, and writes `results/runs/<name>/` in the same format.

Files: `common.py` (paths, scenarios, windows), `mc_count.py` (counting kernel copy),
`simulate.py`, `replay_record.py`, `timing.py`, `analyze.py`, `figures.py`, `check.py`,
`expected/expected.json` (regression values of the first reproduction), `tables/`
(committed summaries), `results/` and `data/` (gitignored).
Imports from `../short_ts_switch/` (`make_inputs.py`, `closure_port.py`) are read-only;
`common.py` keeps their numba cache and bytecode out of that folder.
