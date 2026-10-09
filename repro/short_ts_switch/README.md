# `assume_short_ts`: what the short-time-step assumption does in T-Route

*AI-assembled (Claude, 2026-10-07; mechanism checks, terminology and mass balance
2026-10-08 after the author's comments); not yet reviewed by the author.*

## Question
T-Route's Muskingum-Cunge (MC) kernel has a switch, `compute_parameters.assume_short_ts`.
- **`True`: short-time-step assumption enabled.** Each segment's current-step upstream
  inflow is replaced by the previous-step value. This is WRF-Hydro's behaviour, so the
  NWM's MC routing has always run this way. It made reach routing parallel under MPI, and
  it is the setting for NWM parity.
- **`False`: short-time-step assumption disabled.** T-Route uses the upstream outflow it
  has just computed in the same step (current-step upstream inflow).

In the pinned T-Route, `False` is the configuration default:
`src/troute-config/troute/config/compute_parameters.py` L47 reads
`assume_short_ts: bool = False`. The setting that reproduces WRF-Hydro/NWM is `True`.
This README speaks of "True" and "False" (or "assumption enabled / disabled"). It does not
call either one "the lag", because, as shown below, that word suggests the wrong sign.

No evaluation of the switch existed. The author
calls it "a near-term priority". How much does the switch change routed flows, how does
the change build up through a network, and how does it depend on the routing timestep dt?

## What one would expect, and what happens
**Expectation (the author's reasoning, 2026-10-08).** With `False`, a segment sees the
inflow its upstream neighbour has just produced. With `True`, it sees last step's value.
During a fast rise, the information therefore waits one extra timestep at every segment
before it is passed on. Over many segments, `True` should *delay* the flood wave by at
least a timestep per segment.

**What the runs show.** At the NWM timestep (300 s), `True` brings the Potomac storm peak
78 h *earlier* and 38% *higher*. Only at dt = 3600 s does it delay the wave.

**Why, in plain terms.** In Muskingum-Cunge, a segment's outflow is a weighted sum of four
terms: last step's inflow (weight C1), this step's inflow (C2), last step's outflow (C3),
and lateral inflow (C4). When the Courant number is small, the weight C2 on this step's
inflow is *negative*. A rising inflow first *holds the outflow back*: this is the
Muskingum "wedge storage" term, K·X·dI/dt, which stores water while the inflow rises.
`True` replaces this step's inflow with last step's. The negative C2 then lands on last
step's inflow, and C1 + C2 together equal dt/D > 0. So the hold-back term disappears, and
the segment behaves like a plain linear reservoir. The one-step wait (+dt/2 on average)
is real. But removing the wedge storage advances the response by K·X, and at
NWM-like settings K·X is much larger than dt/2. The net shift per segment is
**Δ = dt/2 − Km·X**, negative (earlier) whenever the Courant number is below 2X. When dt
is so large that T-Route clamps Km to dt (Courant ≥ 1), Δ = dt(1/2 − X) ≥ 0, and the
expected delay appears. That is the dt = 3600 s case.

**Status.** The author asked for this to be confirmed in depth and flagged for review by
a numerical-methods reader.
The checks are in "Mechanism checks" below.

## Design
**Model under test: T-Route itself.** The pinned commit is
[CIROH-UA/t-route `d29f663`](https://github.com/CIROH-UA/t-route/commit/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6),
the head of branch `ngiab` on 2026-09-18. It is built from source by `build_troute.py`,
which follows t-route's own `compiler.sh`/`Dockerfile` (gfortran kernels, Cython
packages). Each run goes through T-Route's normal V4 entry point
(`nwm_routing.__main__.main_v04`, i.e. `python -m nwm_routing -f -V4 <yaml>`). The only
intervention is that T-Route's output writer is replaced by an in-memory collector
(`run_troute.py`). The switch acts in
[`mc_reach.pyx`](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/troute-routing/troute/routing/fast_reach/mc_reach.pyx)
in two places: at reach heads (L514–515, `upstream_flows = previous_upstream_flows`) and
segment to segment inside a reach (L143–146). This commit was chosen because it builds
cleanly with the published `uv`-based Dockerfile recipe, and its MC path is the
V02-structured kernel shared with NOAA-OWP `master`.

**Domains**

| Case | Network | Forcing | Initial state | Length |
|---|---|---|---|---|
| `lc_nwm` | `test/LowerColorado_TX` shipped with t-route: the Colorado River (TX) network, 11,248 NWM segments, longest path 1654 km / 649 segments | Recorded NWM AnA lateral inflow, 28 hourly CHRTOUT files from 2021-08-23 13:00 UTC (T-Route reads `qBucket + qSfcLatRunoff`) | NWM routed `streamflow` at t0, by feature_id (341 missing values set to 0) | 28 h |
| `potomac_storm` | Potomac River: all 16,454 segments upstream of NWM feature 4539621, extracted from NWM v3.1.6 `RouteLink_CONUS.nc`; longest path 688 km / 527 segments. The outlet is the river's mouth at Chesapeake Bay (38.00 N, 76.31 W), 193 km below the Little Falls gage (USGS 01646500) | Synthetic storm: lateral inflow proportional to segment length (nominal 1.25 km² per km of channel), 0.01 m³ s⁻¹ km⁻² baseflow, plus 25 mm runoff released as a gamma pulse (shape 3, scale 4 h) starting at 24 h | Exact steady state of the baseflow | 40 days |

The shipped HYDRO_RST restart was not used. It has 11,141 links against 11,248 RouteLink
rows, and T-Route's reader maps restart values by position. The 40-day Potomac run lets
every segment return to baseflow (checked). A synthetic storm on the LowerColorado
network was tried and dropped: with these parameters its outlet had passed only 15% of
the storm volume after 21 days.

**Held fixed:** NHDNetwork, MC `V02-structured` kernel, serial compute, waterbodies not
broken out (lakes routed as MC channels), no data assimilation, 24-h forcing loops.

**Runs:** `assume_short_ts` ∈ {True, False} × dt ∈ {60, 300 (NWM default), 900, 3600} s
× 2 cases = 16 runs. Four of them are repeated for a bitwise self-consistency check.

**Metrics (`analyze.py`):** outlet peak flow and time (native resolution, parabolic peak
refinement), volume, NSE/KGE of True against False, max |difference|. Per segment: peak-time
shift (True − False) and relative peak difference, binned by the longest upstream path
(number of segments), distance to the outlet, and stream order; hydrograph-centroid
shifts. Courant number Cn = ck·dt/dx and Muskingum X at each segment's peak, from
T-Route's own formulas, checked against the compiled Fortran kernel through ctypes.
Mass balance. All values are in `results/results.json`. `mechanism.py` adds the checks
described under "Mechanism checks" (`results/mechanism.json`).

## Linear theory: the shift per segment
The kernel (`MCsingleSegStime_f2py_NOLOOP.f90`) computes
`qdc = C1·qup + C2·quc + C3·qdp + C4`, with
D = Km(1−X) + dt/2, C1 = (Km·X + dt/2)/D, **C2 = (dt/2 − Km·X)/D**,
C3 = (Km(1−X) − dt/2)/D, **Km = max(dt, dx/ck)**, and X clipped to [0.25, 0.5].
`True` replaces `quc` (current upstream inflow) with `qup` (previous). For one segment
with fixed coefficients, the mean delay (first moment) of the response is
(1 − C2)/(1 − C3) steps = Km with `False`, and 1/(1 − C3) steps = Km(1−X) + dt/2 with
`True`. Enabling the assumption therefore shifts each segment's response by

> **Δ = dt/2 − Km·X** (seconds; negative = `True` is *earlier*).

- When Km = dx/ck > dt (Cn < 1), Δ < 0 whenever Cn < 2X. Enabling the assumption
  *advances* the wave.
- When Km is clamped to dt (Cn ≥ 1), Δ = dt(1/2 − X) ∈ [0, dt/4]. Enabling it *delays*
  the wave.
- As dt → 0, Δ → −K·X, which does **not** vanish. `False` converges to the Muskingum
  equation K[X·dI/dt + (1−X)·dO/dt] = I − O. `True` converges to K(1−X)·dO/dt = I − O,
  a linear reservoir that drops the X·dI/dt term. With X ≈ 0.5 (the Potomac median is
  0.49), the mean travel time per segment is roughly halved. So the "short time-step
  assumption" does not become exact as the timestep shrinks.
- The variances per segment (exact, discrete) are r(1+r) with `True` and
  r(1+r) + p(1−p) with `False`, in steps², where r = C3/(1−C3) and p = C1/(C1+C2). When
  C2 < 0, p > 1 and p(1−p) < 0. So in the *linear* scheme `True` is earlier but also
  **more** dispersed, with a *lower* peak. The higher `True` peaks on the Potomac are
  therefore not linear behaviour (see "Mechanism checks", C).

First moments add along a cascade. `analyze.py` therefore predicts each segment's
centroid shift as the storm-volume-weighted sum of Δ over the paths from where the water
entered, with Km and X taken at each segment's `False` peak. "Mechanism checks", F, tests
this predictor and an improved one.

## Results (macOS arm64, 2026-10-07; full numbers in `results/results.json`)
**Potomac, synthetic storm: outlet**

| dt (s) | Cn at peak, median (share > 1) | outlet peak False → True (m³/s) | peak diff | peak-time shift | centroid shift, measured / predicted | NSE (True vs False) |
|---|---|---|---|---|---|---|
| 60 | 0.04 (2%) | 1578 → 2340 | +48.3% | −96.1 h | −87.3 / −43.1 h | −0.49 |
| 300 | 0.20 (11%) | 1587 → 2195 | +38.3% | −77.6 h | −74.8 / −33.6 h | −0.17 |
| 900 | 0.60 (35%) | 1556 → 1748 | +12.4% | −33.8 h | −47.1 / −13.2 h | 0.51 |
| 3600 | 2.46 (84%) | 955 → 919 | −3.7% | +72.0 h | +35.4 / +51.5 h | 0.80 |

"Peak with the short-time-step assumption enabled" is the True column. Negative shifts
mean the True peak arrives earlier.

**How the effect builds up downstream (Potomac, dt = 300 s).** The effect scales with
the number of segments upstream, not with distance from the outlet. The Spearman rank
correlation of peak-time shift with the longest upstream path is −0.85; with distance to
the outlet it is +0.12. Medians by longest upstream path:

| upstream path (segments) | 10–25 | 25–50 | 50–100 | 100–200 | 200–300 | 300–400 | 400–500 | ≥ 500 |
|---|---|---|---|---|---|---|---|---|
| peak-time shift (h) | −1.3 | −3.3 | −7.0 | −11.0 | −22.3 | −37.4 | −63.8 | −75.4 |
| peak difference (%) | +2.0 | +10.0 | +25.1 | +31.3 | +29.7 | +42.1 | +39.5 | +38.4 |

That is roughly −0.14 h per upstream segment. By stream order, orders 1–2 (12,460 of
16,454 segments) are unchanged. The median shift and peak change are −2.5 h / +7% for
order 4, −6.1 h / +23% for order 5, −16.3 h / +31% for order 6, and −51.0 h / +41% for
order 7. Network-wide, 12.7% of segments change their peak by more than 5%, and 18.8%
shift it by more than 1 h. At dt = 60 s the ≥ 500-segment bin reaches −93 h / +49%. At
dt = 3600 s the sign reverses: +69 h / −3.7%. See `results/fig_shift_vs_distance.png` and
`results/fig_outlet_hydrographs.png`.

**Theory vs measurement.** The prediction gets the sign at every dt (a `check.py` test).
It also ranks segments well: Spearman 0.78 / 0.74 / 0.59 / 0.59 for dt = 60 / 300 / 900 /
3600 s, with a median absolute error of 0.3 h. But for dt ≤ 900 s it underestimates the
magnitude about 2–3× (regression slopes 2.1 / 2.3 / 3.2). "Mechanism checks", C and F,
explain most of the gap.

**Mass balance.** Every Potomac segment returns to baseflow by day 40. At the outlet,
`False` delivers only 91.0 / 91.9 / 94.0 / 97.7% of the upstream storm volume (dt = 60 /
300 / 900 / 3600 s). `True` delivers 100.2 / 100.5 / 101.1 / 101.3%. The network
1st–99th percentiles are 0.89–1.02 for `False` and 1.00–1.01 for `True` at dt = 300 s.
The cause is in "Mechanism checks", D.

**Accuracy against `False` at dt = 60 s.** At dt = 300 s, `False` is within +0.6% / +2.1 h
of it at the outlet; `True` is +39% / −75 h. At dt = 3600 s (84% of segments at Cn > 1)
both settings are far off: outlet peak −39% (`False`) and −42% (`True`), and 275 h and
347 h late. This is the C > 1 delay and attenuation seen in the synthetic-channel experiment (`../mc_courant_timestep/`), here at network scale.

**LowerColorado, recorded NWM forcing, 28-h window.** The window is too short for the
outlet to peak. Outlet flow at the end of the window is 76.94 vs 75.30 m³/s with `True`
vs `False` at dt = 300 s (+2.2%), and +1.9 to +2.3% at dt = 60–900 s. Among the 330
segments whose `False` peak falls inside the window and is ≥ 1 m³/s, the median
peak-time shift is −1.7 h (5th percentile −20.4 h). 25% of them differ by more than 5% in
peak, and here `True` is mostly *lower* (5th percentile −18%). The largest hourly
difference anywhere in the network is 42.6 m³/s.

**Cost.** Serial runtime is the same with either setting (Potomac, dt = 300 s: 61.4 s vs
61.5 s). The parallel benefit of the assumption was not tested.

## Mechanism checks (`mechanism.py`, 2026-10-08; `results/mechanism.json`)
Figures: `results/fig_mechanism_cascade.png`, `results/fig_mass_balance.png`.

**A. A kernel port for diagnostics.** `mc_port.py` is a line-by-line Python (float64)
port of the kernel. It also returns what the compiled kernel does not: the C1..C4, Km
and X actually used, and whether the negative-flow guard fired. Replaying 116 Potomac
mainstem segments (those with a single upstream segment) from their upstream
neighbour's native-resolution outflow reproduces T-Route's own outputs. The maximum
difference is 2.0e-4 (False) and 4.2e-5 (True) of the segment peak, and the median is
7e-7. Against the compiled kernel, the comparison is only meaningful with the patched
build (E), because the unpatched kernel's output varies between processes. On 6,000
random non-steady calls the port agrees with the patched kernel to 5e-8 (median) and 2e-6
(99th percentile); the maximum, 8.5%, is on a slope-floor segment, where the depth secant
is ill-conditioned (`results/qj_patch_check.json`).

**B. Linear MC (constant Km, X; one reach and cascades of 10 and 50).** With smooth
inflow, the measured shift per reach equals dt/2 − Km·X to the second in all 18 cases,
including the clamped case K = 0.25 h, dt = 3600 s (+360 s). The variances match the
exact discrete values. Volume is conserved in both settings. `True` peaks are *lower*:
for K = 1 h, X = 0.4, dt = 300 s, N = 50, the True peak is 7.8% lower and 17.4 h earlier.
With **sharp** inflow (gamma, scale 15 min), the False scheme's negative C2 drives the raw
MC value below zero at the front. T-Route's negative-flow guard (kernel L149–156) then
replaces it with a larger positive value and *creates* water: in every sharp case where
the guard fired, False's output volume was 1.07 to 7.9 times its input, with the extreme
case at X = 0.5, N = 50. This never happens with
True, where C1 + C2 > 0. The guard did **not** fire in any replayed Potomac segment (D).

**C. T-Route's kernel on uniform cascades (40 segments, dx = 2 km, Potomac mainstem
cross-section, base 150 m³/s, gamma storm).** Two slopes were tested: 0.002, and the
RouteLink floor of 1e-5.

| dt = 300 s, after 40 segments | So = 0.002 | So = 1e-5 |
|---|---|---|
| Km range over the event (h) | 0.28–0.65 | 1.37–8.97 |
| centroid shift, measured | −5.6 h | −26.4 h |
| predicted, Km·X at False peak (as `analyze.py`) | −2.3 h | −15.1 h |
| predicted, inflow-weighted Km·X | −4.1 h | −13.1 h |
| True peak vs False peak | +0.1% | +32% |
| volume out/in, False / True | 0.94 / 1.00 | 0.79 / 1.01 |

The gap between theory and runs (1.7–2.5×) appears in a single uniform channel, so it is
not a network effect. It has three causes:
1. **Km·X at the peak is the event minimum.** Km = dx/ck is smallest at peak flow.
   The effective value for the first moment is the inflow-weighted
   −Σ t·Km·X·ΔI / V. That reduces to Km·X when the coefficients are constant, and it
   includes the hysteresis of Km(outflow) against the inflow. For a single segment on the
   0.002 slope it predicts −0.120 h against −0.127 h measured (at-peak prediction:
   −0.057 h).
2. **False loses volume on the rising limb** (D). That moves False's centroid later and
   adds apparent shift. This dominates on the slope-floor channel, where False lost 21% of
   the water over 40 segments.
3. **The nonlinear kernel turns the earlier arrival into a higher peak.** True's peak is
   +32% higher on the slope-floor channel, while linear theory says it should be lower.
   Part of this is False's lost volume. Part is steepening (point H): ck rises with flow,
   so a front that keeps more water arrives sharper.

**D. Mass balance: cause found.** Multiply the kernel's update by D and rearrange. Each
step is an exact discrete storage equation:

> dt/2·(qup + quc) + ql·dt − dt/2·(qdp + qdc) = Km·X·(quc − qup) + Km·(1−X)·(qdc − qdp)

Summed over an event, in − out = Σ Km·X·ΔI + Σ Km·(1−X)·ΔO. This is zero only if Km and
X are constant. In the kernel they are recomputed every step from the new depth, which
follows the *outflow*. On the rising limb the inflow rises while the outflow is still low
(large Km); on the falling limb it falls while the outflow is high (small Km). So
Σ Km·X·ΔI is a hysteresis-loop integral, it is positive, and it is a net **loss**. It
does not shrink as dt → 0. **With True, quc = qup, so this term is identically zero.**
Only Σ Km(1−X)ΔO remains. Km(1−X) is a function of the outflow alone, so that sum nearly
closes, leaving a small first-order discretization error that is a slight gain and grows
with dt (+0.2% at 60 s to +1.3% at 3600 s). This is the time-varying-parameter mass
error known for variable-parameter MC; Todini (2007, doi:10.5194/hess-11-1645-2007)
attributes it to time-variant parameters, "particularly when dealing with very mild
slopes".

Evidence:
- **Accounting closes.** Per-segment balances (upstream volume + lateral − own volume)
  add up to the outlet deficit at every dt for both settings (`check.py`). The
  storage-change term is zero because all flows return to baseflow.
- **Where the loss is.** At dt = 300 s, 52% of False's loss is in the 16% of segments at
  the slope floor (6% of channel length). The top 1% of segments carry 72% of it. These
  are long (3–17 km), deep-overbank segments (peak depth 3–13 × bankfull). Individual
  segments lose up to 17% of the storm water reaching them. The mainstem carries 26%.
- **The term matches the loss segment by segment.** On the 116 replayed mainstem
  segments, in − out equals the two sums to 4e-10 (relative). False:
  Σ Km·X·ΔI = 2.01e6 m³ and Σ Km(1−X)ΔO = −0.17e6 m³, against a T-Route loss of
  1.82e6 m³. True: Σ Km·X·ΔI = 0, and the loss is −0.21e6 m³ (a gain). See
  `fig_mass_balance.png`.
- **Not the guard, not the solver floors.** The negative-flow guard fired at no step of
  any replayed segment. The secant's depth floors and its 1% tolerance do not enter the
  identity, which holds for whatever depth the secant returns.
- **Also in single segments.** The uniform cascades (C) lose 0.06% (So = 0.002) to 1%
  (So = 1e-5) per segment with False and conserve with True. Linear MC with constant
  coefficients conserves exactly.
- **dt dependence.** False's loss shrinks at large dt (9.0 / 8.1 / 6.0 / 2.3% at 60 /
  300 / 900 / 3600 s) because Km is clamped to dt (a constant) on more segments.

**Parity.** WRF-Hydro, and T-Route runs set up for NWM parity, use True, so they do not
have the loss term. The loss belongs to T-Route's configuration default (False). It also
contaminates every False-vs-True comparison: part of each "True is higher" difference
is water that False lost.

**E. A second, unrelated defect: an uninitialized read in the kernel.** Under
dt = 3600 s, 139 of the 6,069 headwater segments differ between True and False, by up
to 0.35 m³/s, or 22% of the segment's peak (dt = 300 s: 26 segments, 0.5%). They
should be identical, because headwaters have qup = quc = 0 in both settings. T-Route's
reach structure is correct (checked on a 7-segment subnetwork). The cause is in
`secant2_h`: on the first secant iteration, the X formula (L281, L291) reads its
`intent(out)` argument `Qj`, i.e. the caller's `Qj_0`, before anything sets it. The port
reproduces T-Route's True series with `Qj_0` = 0 and T-Route's False series with
`Qj_0` = 1. The value the compiled code uses depends on what the surrounding code left
in memory, so it changes with the setting. Called through ctypes on the same 6,000
inputs in two fresh processes, the unpatched kernel returned different outflows for 38%
of the calls (up to 99.8% relative difference). The patched kernel returned identical
outflows. Inside T-Route the calling sequence is fixed, which is why reruns are bitwise
identical. Adding `Qj_0 = 0` alone changes nothing: the
compiler removes the store, because the argument is `intent(out)` (identical
disassembly). Also declaring `Qj` `intent(inout)` (`build_troute.py --patch-qj`;
`qj_patch_check.sh` → `results/qj_patch_check.json`) makes all headwaters agree. At
dt = 300 s, it moves individual False segments by up to 80% of their peak (8% of
segments by > 1%) and True segments by < 0.7%. It leaves the outlet comparison
essentially unchanged: +38.2% / −77.6 h, against +38.3% / −77.6 h. Event balance 0.918
vs 0.919 (False), 1.0055 vs 1.0054 (True). So the network-scale results above stand, but
per-segment values, especially for False, carry this compiler-dependent noise. This is
probably the same defect class as the C1..C4 uninitialized-read reports (rs_route #7,
NGWPC #123). Not yet compared with WRF-Hydro's source.

**F. The network predictor, revisited.** Two corrections, tested at all four dt:
- **Lateral inflow does not see the switch.** It enters through C4 = ql·dt/D, identical
  in both settings. So a segment's Δ applies only to water arriving from upstream, and
  headwaters do not shift (measured: zero, apart from E). Excluding lateral inflow from
  each segment's own Δ raises the Spearman correlation from 0.74 to 0.95 and cuts the
  median error from 0.27 to 0.03 h (dt = 300 s). The slope stays at 2.37.
- **Inflow-weighted Km·X** (hourly False flows; depth by inverting T-Route's Manning
  relation) lowers the slope to 1.38 / 1.40 / 1.45 / 0.92 (dt = 60 / 300 / 900 / 3600 s).
  The outlet prediction becomes −55.8 h, against −74.8 h measured (dt = 300 s; at-peak
  predictor: −33.6 h). The remaining ~30% is consistent with False's mass loss (C,
  item 2), which this first-moment argument does not include.

**G. Why the Potomac outlet responds so slowly (peak 263 h after the storm centroid,
False, dt = 300 s).** The behaviour follows from the NWM v3.1.6 channel parameters; it is
not a T-Route bug or an artifact of the storm design.
- The network outlet is the **river mouth**. The 194 km below Little Falls is the tidal
  estuary, and RouteLink represents it as a 264-m-wide compound channel. 97% of that
  length sits at RouteLink's **slope floor, So = 1e-5**.
- On the whole mainstem, 280 of 516 segments (325 of 688 km) are at the floor. At the
  floor, normal depth at the peak is 26–34 m, about 10× the 2.8 m bankfull depth (checked
  by hand against Manning: 1,586 m³/s at 26.2 m). The median ck is 0.48 m/s at the peak
  and 0.23 m/s at baseflow, against 1.8 / 0.9 m/s on the other segments.
- Σ dx/ck along the mainstem at the peak is 253 h. The floor segments carry 187 h of it,
  and the estuary 112 h.
- At Little Falls the False peak arrives 141 h (True 103 h) after the storm centroid.
- Even off the floor, the peak is 3.6× bankfull. NWM's floodplain (TwCC = 3·Tw,
  nCC = 2n) is narrow and rough.

Whether NWM routing is this slow on the real Potomac was not checked against
observations. An event at USGS 01646500 would test it. The outlet choice matters: the
estuary inflates both the travel time and the True/False differences at the outlet.

**H. The sharp step in the False outlet hydrographs.** At dt = 300 s the outlet flow
first rises to a hump of 966 m³/s at about 220 h (lower-basin tributaries), recedes to
817 m³/s, then jumps from 837 to 1,497 m³/s within 12 h at about 287 h. The maximum rise
is 80 m³/s per hour. This is the steep front of the upper-basin flood wave arriving.
- It is not a timestep artifact: at dt = 60 s the same front arrives at 285.6 h with
  82 m³/s per hour.
- It is not the bankfull transition: the outlet is already 11.5 m deep (4× bankfull) at
  baseflow.
- The front forms because ck roughly doubles from baseflow to peak on the mainstem. The
  higher flows catch up with the lower ones and the rising limb steepens toward a
  kinematic shock. The uniform slope-floor cascade (C) reproduces a sharp front with no
  tributaries (`fig_mechanism_cascade.png`, right).
- True shows the same front about 78 h earlier (the spike at about 210 h). Arriving on
  top of the tributary hump instead of after it, it makes True's outlet peak larger.

## Calibration caveat (author, 2026-10-08)
The NWM's channel and other parameters were calibrated with the short-time-step
assumption in place (WRF-Hydro, i.e. True). Some of the True/False difference may
therefore already be absorbed by calibration: parameters tuned under True may be
compensating for its earlier, sharper response. Running False with those parameters
mixes the scheme change with a calibration mismatch. Separating the two would require
recalibrating the whole system under False. Until then, these results describe what the
switch does to the scheme, not which setting gives better NWM forecasts.

## How to run
```bash
repro/short_ts_switch/run.sh          # fetch -> build T-Route -> 16 runs -> analyze -> mechanism -> check
JOBS=8 repro/short_ts_switch/run.sh   # more parallel processes (default 4)
repro/short_ts_switch/qj_patch_check.sh   # optional: second, Qj-patched build (E); about 5 min
```
Needs `uv`, gfortran, a C compiler, make, git, and netCDF-C + netCDF-Fortran with
`nc-config`/`nf-config` (Homebrew `gcc netcdf netcdf-fortran` on macOS). A clean run
(empty `.venv/`, `data/t-route`, `build/`, `results/`), including the T-Route build, took
7 min 20 s with 4 jobs on a 16-core Apple-silicon Mac (2026-10-07, before
`mechanism.py`, which adds about 75 s with 6 jobs). It reproduced every value in
`results.json` exactly (wall times aside). One exception was found on 2026-10-08:
`kernel_check/max_abs_diff_X` (lc_nwm) changed in the 8th digit between two runs. It
calls the compiled kernel through ctypes, whose output depends on uninitialized memory
(E); `check.py` tolerates this. `mechanism.json` was identical in repeated runs. The two dt = 60 s Potomac runs take about
4.5 minutes each.

Steps: `uv sync --locked --inexact` → `fetch_data.py` → `build_troute.py` →
`make_inputs.py` → `run_experiment.py` → `analyze.py` → `mechanism.py` → repeat 4 runs
into `results/rerun/` → `provenance.json` → `check.py`.
- `fetch_data.py` fetches t-route by commit SHA (`git fetch --depth 1 <sha>`) into
  `data/t-route` and verifies the SHA-256 of the 29 LowerColorado files used. It fetches
  `RouteLink_CONUS.nc` (NWM v3.1.6, NCEP; same URL and SHA-256 as `network_stats/`),
  reusing a verified sibling copy if one exists.
- `build_troute.py` builds from a `git archive` copy in `build/t-route` (the fetched source
  stays pristine). It installs the four t-route packages with `uv pip install --no-deps
  --no-build-isolation` against the locked numpy 1.26.4 / Cython 3.0.12, and writes
  `build/build_info.json` (compiler versions, every command, patches: none by default).
- `mechanism.py` uses `mc_port.py` and the runs; it does not run T-Route again.
- `--inexact` deviates from `repro/README.md` (`uv sync --locked`). A plain `uv sync`
  would uninstall the t-route packages, which are built from the pinned commit rather
  than locked, because they are not on PyPI.

Outputs in `results/`: `results.json`, `mechanism.json`, `summary_table.csv`,
`fig_outlet_hydrographs.png`, `fig_shift_vs_distance.png`, `fig_accuracy_vs_dt.png`,
`fig_mechanism_cascade.png`, `fig_mass_balance.png`,
`runs/<case>/dt<dt>_sts<0|1>.{npz,yaml,log}` (the YAML is the exact T-Route
configuration), `provenance.json`, and (optional) `qj_patch_check.json`.

## Checks (`check.py`, 130 checks; all pass, macOS arm64, 2026-10-08)
1. **Self-consistency:** four runs repeated in fresh processes are bitwise identical.
2. **Sanity:**
   - All outputs are finite.
   - In the Potomac spin-up (first 24 h, steady), True and False agree to < 1e-3 m³/s.
   - The numpy Courant/X formulas match the compiled Fortran kernel: relative difference
     about 2e-7 in ck and Cn, and < 0.01 in X (the kernel's X uses an intermediate secant
     flow).
3. **Theory:** predicted and measured outlet centroid shifts have the same sign at every
   dt.
4. **Mechanism (8 checks):** the port reproduces T-Route's mainstem outputs (< 1e-3 of
   peak). Linear MC shift = dt/2 − Km·X within 1 s, variances within 1%, and volume
   conserved (smooth inflow, N ≤ 10). Per-segment balances add up to the outlet deficit.
   The storage identity holds on replayed segments; the inflow term is zero with True;
   the port's segment losses match T-Route's within 5%.
5. **Regression:** 92 values against `expected/expected.json`, which holds the values from
   the first reproduction. Tolerances:
   - flows: relative 2e-3
   - times: ± max(0.05 h, dt)
   - percentages: ± 0.5 points
   - indices: ± 0.005

`expected/` was not changed on 2026-10-08. Only figure labels and one results.json key
were renamed (`frac_negative_(lag_advances)` → `frac_negative_(short_ts_earlier)`, not
regression-checked).

## Caveats
- **No observations.** Neither setting is validated here. `False` is the consistent MC
  discretization (it converges to Muskingum as dt → 0) but loses volume (D). `True`
  converges to a different model. Which is closer to real rivers is a separate question.
- **Calibration** (see above): NWM parameters were tuned with True.
- **Synthetic forcing for the Potomac.** The storm is spatially uniform, and contributing
  area is assumed proportional to channel length (RouteLink has no catchment area).
  Magnitudes depend on this design. The mechanism and its scaling should not. The outlet
  is the estuary mouth (G), which inflates outlet-level differences.
- **Waterbodies routed as channels, no data assimilation.** In the NWM, reservoirs (30 in
  the Colorado network) and nudging would damp and reset these differences. The switch
  also affects reservoir inflows (`mc_reach.pyx` L514–515), which is not exercised here.
- **LowerColorado** starts from NWM `streamflow`, which was computed by WRF-Hydro with
  True, reservoirs, and nudging. So its 28 h include adjustment transients that differ
  between settings.
- **Peak metrics.** In `lc_nwm`, peaks at the window edges are excluded. Single-peak
  comparisons can jump between humps of multi-peaked hydrographs (e.g. Potomac dt =
  3600 s, 400 km above the outlet). Centroids are more robust.
- **Loops.** 24-h forcing loops change results only at float32 noise level (max 1.2e-5
  m³/s; tested 7-h vs 28-h loops on `lc_nwm`). All runs use the same loop length.
- **Kernel state.** The kernel reads `Qj` before setting it (E). Reruns are bitwise
  identical on one build, but per-segment values can change with compiler, flags or
  platform. In `compute_reach_kernel` the output struct `rv` is not initialized; the
  Fortran's `qdc` read in its "water to route?" test sees 0, because `reach.pyx`
  initializes the local it passes.
- **Platform.** Tested natively on macOS arm64 (gfortran 15.2.0) only. There is no
  Dockerfile yet; a Debian-slim image pinned by digest, as in `mc_courant_timestep/`,
  would be the next step.
- **Updating `expected/`.** Do so only with a written reason here.
