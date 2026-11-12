# Diffusive mainstem: where would diffusive routing remove known MC error and MC parameter effects, and can we survey it?

*AI-assembled screening (Claude, 2026-10-08; revised 2026-10-20: known error and parameter
effects reported separately, "mainstem" wording; revised 2026-10-28: mainstem selected by
divergence-routed drainage area); not yet reviewed by the author. No model is run.*

## Question
The need here is to work towards accurate overall routing. We know that the MC algorithm
has difficulty on low-slope reaches and near confluences, where backwater from the larger
river matters; many of these reaches are on the downstream "mainstem" network. (This is
broadly the "mainstems" network that OWP's flood inundation mapping uses, the NWM reaches
downstream of RFC forecast points and selected USGS gages, but it is not strictly
constrained to that extent.) There are also limits on the parameters of the MC algorithm
that are design choices but that affect the calculated flows. If we assume that diffusive
routing is used on that mainstem network and that it removes both the errors and the
parameter effects, how much of each would be avoided, just by not using MC on those
reaches?

Restated as research questions:
1. Which segments carry known MC error (low slope; backwater near confluences, outlets and
   lake inlets)? Which segments are affected by the design limits on the MC parameters (the
   X ≥ 0.25 floor, and K clamped to dt where the Courant number exceeds 1)?
2. Assuming diffusive routing removes both, how much of the known error, and separately how
   much of the parameter effect, is removed by routing a mainstem selection of reaches
   diffusively?
3. Which selection of mainstem reaches gives the best balance, if the reaches converted
   must also allow bathymetry collection by ADCP (or other towed instruments), i.e. are deep
   enough at typical flows?

The screen measures both as exposure: mean annual flow × length on the flagged segments.
It does not measure the size of either. The parameter limits are evaluated at bankfull,
with the NWM's 300 s channel timestep for the K clamp.

T-Route has demonstrated diffusive routing on the Lower Mississippi, Amite–Comite and Falls
Lake (Beg et al. 2023, JAWRA 59(2):257–280, online December 2022,
[doi:10.1111/1752-1688.13080](https://doi.org/10.1111/1752-1688.13080)).

## Assumption (stated once, applies to every number below)
**Assuming diffusive routing removes the listed MC errors and parameter effects on the
segments it is applied to.** That is not demonstrated here. The screen only says *where*
the known MC error regimes and parameter limits are, and how big the treated network would
be. It does not estimate how well a diffusive model with real (or approximate) bathymetry
would do there.

## Results (macOS arm64, 2026-10-28; all values in `results/results.json`)

### 1. Where the known-MC-error regimes and parameter limits are (CONUS, 2,703,798 MC segments, 5.38 M km)
Lake segments (72,936 inside NWM level-pool lakes) are excluded throughout.

| indicator (at bankfull, RouteLink geometry) | km | % of network km |
|---|---|---|
| **Known MC error** | | |
| LS: S0 < 2.5e-4 (Tang et al. 1999 loss beyond "just about tolerable") | 396,137 | 7.4 |
| … of which at RouteLink's slope floor, S0 = 1e-5 | 283,463 | 5.3 |
| BW: within a Samuels backwater length of a confluence / outlet / lake inlet | 187,060 | 3.5 |
| … (i) confluence with a larger river ("fringing" tributaries) | 148,515 | 2.8 |
| … (ii) network outlet | 39,532 | 0.7 |
| … (iii) NWM lake inlet | 28,060 | 0.5 |
| **error-flagged (LS or BW)** | **418,547** | **7.8** |
| **MC parameter limits (design choices)** | | |
| XF: the kernel's X ≥ 0.25 floor binds | 397,624 | 7.4 |
| KC: K clamped to dt (Courant ck·dt/Δx > 1 at dt = 300 s) | 112,124 | 2.1 |
| **effect-flagged (XF or KC)** | **505,189** | **9.4** |
| … of which also error-flagged | 364,479 | 6.8 |
| Ponce et al. (1978): dynamic needed for a 1 / 3 / 10-day wave | | 6.2 / 5.5 / 2.2 |

Error score (LS + BW): 0 on 92.2% of km, 1 on 4.7%, 2 on 3.1%. AK, HI and PRVI
(RouteLink-only indicators) are error-flagged on 5.1%, 4.4% and 10.0% of km, and
effect-flagged on 51%, 38% and 25%. In those three domains most of the effect is the K
clamp (46%, 33% and 15% of km): short, steep island and coastal segments.

**Known-error budget.** Each error-flagged segment is weighted by mean annual flow × length
(m³/s·km). Volume loss in variable-parameter MC is proportional to the water passing and
"cumulative in space" (Tang et al. 1999), so this weight sizes how much of the routed water
is exposed to the error. The error-flagged 7.8% of km carry **87% of all flow × km**,
because big rivers are low-slope (LS alone covers 99.5% of the budget; BW 18%). Because
that weighting favours big rivers by construction, every configuration is also scored by
the *unweighted* share of error-flagged km it covers. The two measures disagree, and both
are reported.

**Parameter-effect budget** (reported separately, never added to the known-error budget).
The effect-flagged 9.4% of km carry **91% of all flow × km**. Almost all of it is the X
floor (99.5% of the budget); the K clamp adds 1%, because at dt = 300 s it binds on short,
fast segments that carry little flow (median bankfull Courant number 0.21). 95% of the
parameter-effect budget sits on segments that are also error-flagged: on big rivers the two
kinds of flag coincide.

### 2. Configurations

| | rule | km | % network km | % known-error budget | % parameter-effect budget | % error-flagged km | % km depth ≥ 1 m / ≥ 2 m | % km on NWN | % km eHydro | top-3 networks' share of km | longest diffusive path |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **A** | **mainstem:** divergence-routed drainage area ≥ 10,000 km² | 67,141 | 1.25 | 95.4 | 95.1 | 9.8 | 70 / 59 | 27 | 12 | 62% (Mississippi 46%) | 3,851 km |
| **B** | **mainstem + confluence fringes:** A + tributary segments within backwater L of A | 97,295 | 1.81 | 95.8 | 95.5 | 16.9 | 58 / 46 | 22 | 10 | 57% | 3,851 km |
| **C1** | **low-slope:** all S0 < 2.5e-4 | 396,137 | 7.37 | 99.5 | 94.7 | 94.6 | 36 / 21 | 7 | 3 | 52% | 530 km |
| **C2** | **low-slope, stricter:** all S0 < 1e-4 | 332,177 | 6.18 | 86.6 | 83.2 | 79.4 | 37 / 23 | 8 | 4 | 51% | 436 km |
| **D1** | **flat:** Mississippi Alluvial Plain section (USGS physiography) | 101,672 | 1.89 | 50.1 | 48.8 | 12.4 | 16 / 9 | 4 | 2 | 95% | 1,336 km |
| **D2** | **coastal:** Coastal Plain province (Atlantic, Gulf, embayment) | 728,934 | 13.56 | 58.9 | 57.3 | 35.7 | 10 / 5 | 2 | 1 | 41% | 1,589 km |
| **E** | **navigable:** National Waterway Network (midpoint within 200 m) | 32,107 | 0.60 | 76.8 | 75.6 | 6.8 | 85 / 77 | 100 | 38 | 47% | 1,072 km |
| **F** | **candidate:** B ∩ error-flagged ∩ surveyable (depth ≥ 2 m or on NWN) | **38,636** | **0.72** | **95.4** | **90.9** | **9.2** | **96 / 95** | **49** | **23** | 58% (Mississippi 42%) | 513 km |

A and B are the mainstem selections. C1/C2 (low-slope), D1 (flat) and D2 (coastal) are
alternative selections, kept for comparison; E (navigable) is the waterway network.

As shares of MC *segments*, A is 1.5% and F 1.1% (`pct_network_segments`). Sensitivity
(`results.json` → `sensitivity`): the mainstem at DA ≥ 2,500 / 50,000 km² covers 2.6% / 0.5%
of km and 98% / 86% of the known-error budget. Strahler order ≥ 6 / 7 / 8 covers 2.1 / 0.8 /
0.3% of km and 97 / 92 / 80%. NWN tolerance 100 / 500 m covers 28,612 / 40,042 km.

**Pareto** (`fig_pareto.png`): adding error-flagged segments in decreasing mean flow
captures 98% of the known-error budget with 1% of network km, 99.6% with 2%. The same
ordering covers 93% / 95% of the parameter-effect budget at 1 / 5% of km, but only 13% /
26% / 64% of error-flagged km at 1 / 2 / 5%. The error-flagged km that a big-river
mainstem leaves out are mostly small, flat, shallow channels: 66% of error-flagged km have
mean-flow depth < 1 m, and 68% sit at the slope floor.

**What the fringes add.** B adds 30,154 km to A (+45%) but only 0.4 points of known-error
budget. It raises the mainstem's share of confluence-backwater km (BW-i) from 1% to 21%.
The fringes matter for stage and timing near confluences, which a volume-type weight does
not measure.

### 3. Survey feasibility
- Only **4.5%** of CONUS MC km has a mean-flow depth ≥ 1 m, and **2.1%** ≥ 2 m (primary
  method). The Manning sensitivity gives 6.0% / 3.1%. Bankfull depth ≥ 1 / 2 m: 11.6% / 1.7%.
- The configurations that capture most of the known-error budget are also the deep ones:
  F is 95% ≥ 2 m, E 77%, A 59%. The low-slope and coastal rules are shallow: D2 is 5%, C1 21%.
- **Bounding the need for bathymetry:** F is 38,636 km in 58 networks. 36,700 km of it
  has mean-flow depth ≥ 2 m, 49% lies on the National Waterway Network, and 23% already has
  USACE eHydro survey footprints.

### 4. Validation against our only model evidence (Potomac, `potomac_check.json`)
`repro/short_ts_switch` measured where T-Route's MC loses volume with
`assume_short_ts = False` (8.73% of the storm at dt = 300 s with the corrected kernel of
`repro/kernel_fixes`, rebuilt here exactly). Share of that loss inside each configuration,
restricted to the Potomac:

| | % Potomac km | % measured loss | % predicted by the known-error budget | % predicted by the parameter-effect budget | % of segments with > 5% True/False peak difference |
|---|---|---|---|---|---|
| A mainstem | 1.4 | 16.2 | 88.6 | 86.8 | 15.0 |
| B mainstem + fringes | 5.1 | 32.9 | 89.9 | 87.9 | 30.7 |
| C1 low-slope | 7.0 | 58.5 | 99.7 | 88.3 | 49.3 |
| E navigable | 0.8 | 7.0 | 21.9 | 19.6 | 5.3 |
| F candidate | 1.9 | 25.3 | 89.6 | 79.8 | 17.4 |
| error-flagged | 7.3 | 58.6 | 100 | 88.4 | 50.5 |
| effect-flagged | 9.6 | 58.9 | 99.2 | 100 | 66.1 |

**Candidly:** the indicators point at the right places, but the flow-weighted budget points
too strongly at the mainstem.
- Error-flagged segments (7% of km) hold 59% of the measured loss, an 8× enrichment. The
  top 1% of loss segments, which carry 59% of the loss, are 64% error-flagged and 65% at the
  slope floor.
- But the budget predicts the mainstem holds 89% of the error, and it holds only 16% of the
  measured loss. B holds 33%.
- The measured loss sits in flat tributaries. Slope-floor segments are 6% of km and carry
  58% of the loss. The 2.5e-4–1e-3 slope class, which LS does not flag, carries another 20%.
- The K clamp is not where this loss arises: KC segments (2.0% of Potomac km) hold 0.03% of
  it. XF segments hold 59%, about the same as LS (58%); the two flags mark largely the
  same flat segments.
- This is one network and one synthetic storm. The loss is spread evenly over tributaries
  by design (lateral inflow ∝ length). It comes from the `False` setting; the NWM-parity
  `True` setting does not lose volume this way.

## Most defensible candidate (conjectural)
**F, the "surveyable mainstem" (0.72% of CONUS MC km, 38,636 km in 58 networks).**
- It covers 95.4% of the known-error budget and 91% of the parameter-effect budget.
- 95% of its km has mean-flow depth ≥ 2 m (boat-surveyable by the sources below), 49% is
  on the National Waterway Network, and 23% already has eHydro footprints.
- 42% of it is in the Mississippi, then the Columbia, Atchafalaya, Mobile and Colorado (TX).
- The cost proxy is two network passes per timestep over its segments (see Cost). The
  critical path is a few hundred to 513 km per network.

Two qualifications go with it:
1. **The mainstem does not remove the small-tributary error.** A mainstem selection removes
   the error where most of the *water* is, not where most of the *error-flagged channel*
   is. Flat, shallow tributaries (66% of error-flagged km have depth < 1 m) stay in MC. The
   Potomac shows they carry most of the measured MC volume loss. For those, a
   mass-conservative MC update (Tang et al. 1999; Cunge's 2001 discussion) and better slopes
   are the matching remedies, not bathymetry.
2. **Even diffusive may be marginal on the floor slope.** Ponce's criteria, applied with
   RouteLink slopes, put 83% / 72% of F's km in the "dynamic needed" class for 3- / 10-day
   waves. That is because 76% of F's km sits at S0 = 1e-5, an NHDPlus minimum rather than a
   measured slope. The same bathymetry and slope work that a diffusive mainstem needs would
   decide this.

B (adding the confluence fringes) is the version to propose if stage near tributary mouths
is the goal. D1 and D2 (whole flat or coastal regions) cost 3–19× more km, are mostly too
shallow to survey, and capture less of either budget.

## Cost
The diffusive algorithm of Beg and Meselhe is one of the most efficient available. It needs
exactly two passes of the network per timestep, which, with the network in topological
order, can be parallelized across the network's width, with branches grouped to limit
communication. That algorithm is implemented in T-Route, but we do not examine its
performance here; it is enough to note that T-Route's topological ordering makes such an
implementation possible. Experiments with the diffusive solution so far have used the MC
algorithm for the upper parts of the network and the diffusive algorithm for the lower
parts, with the MC-computed flow as the upstream boundary.

How the screen models cost:
- **Work.** Roughly two passes per timestep over the mainstem's diffusive segments, so work
  is near-linear in the segment count. The MC tributaries are computed upstream as boundary
  inputs.
- **Proxies reported:** segments and km per configuration, and the **longest diffusive
  path per network**, which is the critical path (`longest_diffusive_path_km`).
- **Today's T-Route** loops diffusive domains serially:
  `for tw in diffusive_network_data: # <------- TODO - by-network parallel loop, here.`
  ([compute.py L1762](https://github.com/NOAA-OWP/t-route/blob/12a8eae0cdfed437143c590659fa7077605a5e70/src/troute-routing/troute/routing/compute.py#L1762)).
  Improving that is out of scope here.

## Methods
**Network and geometry.** NWM v3.1.7 RouteLink (`link`/`to` topology; `Length`, `So`, `n`,
`BtmWdth`, `TopWdth`, `ChSlp`, `TopWdthCC`, `nCC`). `ChSlp` is rise over run: the kernel sets
z = 1/ChSlp, and bankfull depth bfd = (TopWdth − BtmWdth)/(2z) = (TopWdth − BtmWdth)·ChSlp/2.
- Sources: [MCsingleSegStime_f2py_NOLOOP.f90 L48–L61 @d29f663](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90#L48-L61);
  T-Route maps `cs: 'ChSlp'` in its test configs; WRF-Hydro is identical.
- The formula D = (TopWdth − BtmWdth)/(2·ChSlp) in the request would give 108.7 m at the
  Potomac outlet instead of 2.85 m. It is not used.
- Bankfull hydraulics use the in-channel trapezoid with Manning. Celerity ck is the
  kernel's own expression at h = D. Fr = V/√(g·A/T).

**Indicators** (`indicators.py`, `analyze.py`; all at bankfull). LS and BW are known MC
error; XF and KC are parameter limits, flagged and budgeted separately.

| | definition | source |
|---|---|---|
| LS | S0 < 2.5e-4. Tiers 1e-4 and 1e-3 reported. Per-segment Tang Eq. 25 (inbank, % per 100 km: 1/(0.113 + 2,102,084.6 S²)) and Eq. 29 (compound, 20-km channel: −0.3813 + 0.006251 S^−0.8) are in `segments_conus.parquet` for reference. Eq. 29 is fitted on S ≥ 1e-4 data: 9.5% at 1e-4, but 62% extrapolated to 1e-5 | Tang, Knight & Samuels (1999a) J. Hydraul. Eng. 125(6) Eq. 25 and §"Effect of Δx/L"; (1999b) J. Hydraul. Res. 37(5) Eq. 29, Table 5 (Eq. 29 read from the PDF image 2026-10-08) |
| BW | L = 0.7(1 − Fr²)·D/S0 (0 if Fr ≥ 1). Backwater decays upstream as exp(−3.3∫S0/D dx), so a segment is "within L" of a control if Σ(Length/L) along the path to its midpoint is < 1. Each segment's own L is used, which generalizes "each tributary's own L" to non-uniform channels. Controls: (i) every non-dominant upstream branch of a junction (dominant = largest mean annual flow), (ii) network outlets, (iii) the last non-lake segment above an NWM lake. Paths stop at lake segments | Samuels (1989) Proc. ICE 87(4) |
| XF | the kernel's second-estimate X = ½(1 − Q/(2·T·S0·ck·Δx)) < 0.25, so the floor binds. With Cunge's ε = ½(1 − Q/(B·S0·c·Δx)) < 0.25 (ratio > 0.5) the flag would cover 9.1% of km instead of 7.4% | kernel L281–L291 @d29f663; WRF-Hydro [module_channel_routing.F90 L374–L377 @32a53e6a33](https://github.com/NCAR/wrf_hydro_nwm_public/blob/32a53e6a33/src/Routing/module_channel_routing.F90#L374-L377); Tang et al. (1999a) Table 3 (truncating ε changes peaks by up to 26%) |
| KC | ck·dt/Δx > 1 at bankfull with dt = 300 s (the NWM channel timestep), so Km = max(dt, Δx/ck) = dt | `Km = max(dt,dx/Ck)` in WRF-Hydro's `SUBMUSKINGCUNGE` and T-Route's port |
| Ponce | kinematic if T·S0·u0/d0 > 171; else diffusion if T·S0·(g/d0)^½ > 30; else dynamic. u0 and d0 are bankfull velocity and hydraulic depth; T = 1, 3, 10 days | Ponce, Li & Simons (1978) Eqs. 14, 17 (online version, [ponce.sdsu.edu](https://ponce.sdsu.edu/applicability_of_kinematic_and_diffusion_models.html), accessed 2026-10-08). Kinematic: "for at least 95% accuracy … τ* has to be greater than 171". Diffusion: "a value of τ*/Fo > 30 is postulated". Also restated by Fread (NWS HRL, "Applicability criteria for kinematic and diffusion routing models", Eqs. 54, 57) |

**The kernel's X formula carries a factor 2 that Cunge's does not.** Numerical diffusion is
about (½ − X)·c·Δx. With the kernel's X this is Q/(4·T·S0), half the physical diffusivity
Q/(2·B·S0) that Cunge's matching targets. WRF-Hydro has the same factor (L291, L294, L374,
L377 at the commit above); the fix is proposed in
[NCAR/wrf_hydro_nwm_public#921](https://github.com/NCAR/wrf_hydro_nwm_public/issues/921) /
[#923](https://github.com/NCAR/wrf_hydro_nwm_public/pull/923), with evidence in
[`../wrfhydro_mc_x_factor/`](../wrfhydro_mc_x_factor/). XF uses the kernel's own formula.

**Flows and depths** (`prepare_flows.py`, `analyze.py`):
- Mean annual flow is EROM `Q0001E` (gage-adjusted, cfs → m³/s) with velocity `V0001E`
  (ft/s → m/s), joined by COMID. 96.0% of RouteLink segments match. The rest (non-NHDPlus
  IDs, Canada/Mexico) get flow and drainage area by summing upstream values.
- Drainage area is `DivDASqKM` (divergence-routed) from the VAA. `TotDASqKM` counts area
  through minor divergences, so side channels and distributaries would inherit the whole
  upstream area (the last reach of Antietam Creek, COMID 5894726: 16,124 vs 730 km²).
- **Mean-flow depth (primary):** A = Q/V, solved for depth on the RouteLink in-channel
  trapezoid extended upward with the same side slopes (no floodplain). Where EROM velocity
  is missing or ≤ 0 (12% of MC segments, mostly lake and wide-river artificial paths), V
  comes from Manning on the same trapezoid.
- **Sensitivities:** Manning normal depth on the kernel's compound geometry, and bankfull
  depth D.
- **Why Q/V is primary:** Manning on RouteLink slopes inflates depth exactly where the
  slope sits at the 1e-5 floor. The Potomac outlet is 11.5 m deep at baseflow
  (short_ts_switch, G).

**Survey thresholds (1 m, 2 m).** No source states a "1 m" or "2 m" rule; the thresholds
are inferred from:
- **Single-beam / ADCP floor, about 0.3–0.8 m:**
  - Mueller et al. (2013), USGS TM 3-A22 v2.0, p. 1: ADCPs are now "commonly used to
    measure water velocity and discharge in streams as shallow as 1.0 ft deep"
    ([pdf](https://pubs.usgs.gov/tm/3a22/pdf/tm3a22.pdf)).
  - Wilson & Richards (2006), USGS SIR 2006-5208, p. 4: a minimum echo-sounder depth of
    "approximately 2.6 ft" ([pdf](https://pubs.usgs.gov/sir/2006/5208/pdf/SIR-06-5208.pdf)).
  - Legleiter & Harrison (2024), doi:10.3389/frsen.2024.1305991: a single-beam sounder
    unable "to measure depths shallower than about 0.4 m".
  - So 1 m is a practical floor for boat-based single-beam/ADCP work.
- **Multibeam, about 2 m (6 ft) and more:**
  - Huizinga (2015), USGS SIR 2015-5048: piers were skipped in "very shallow water (less
    than about 6 feet)" ([abstract](https://pubs.usgs.gov/publication/sir20155048)).
  - USACE EM 1110-2-1003 (2013), p. 2-4: multibeam's "primary application" is "deep-draft
    navigation projects--typically those projects over 10 to 15 ft in depth", with swath
    "twice to seven times the water depth". Retrieved from a
    [Wayback copy](https://web.archive.org/web/20261005075424id_/https://www.publications.usace.army.mil/Portals/76/Publications/EngineerManuals/EM_1110-2-1003.pdf);
    the official URL returned 403.
- All accessed 2026-10-08 (literature search by a research subagent; the Ponce and
  Huizinga quotes were re-checked directly).

**Spatial layers** (`spatial.py`, EPSG:5070):
- RouteLink `lat`/`lon` are the flowlines' along-line midpoints. `geometry_check.py`
  confirmed this against the NWM v3 channel hydrofabric: median 1.3 m, 99th percentile
  38 m, over 5,000 features. Matching by midpoint avoids counting tributaries whose
  downstream end touches a waterway.
- NWN: midpoint within 200 m of a waterway line.
- eHydro: midpoint inside a survey outline.
- Physiography: midpoint within a section or province polygon.

**Configuration B fringe.** Controls are placed at the mouths of non-mainstem branches
joining a mainstem segment. Propagation stops at mainstem and lake segments.

**"Mainstem" here** is drainage area ≥ 10,000 km² (NHDPlusV2 `DivDASqKM`, divergence-routed),
with the sensitivities above. With `TotDASqKM` instead, another 29,023 segments (19,418 km),
side channels, distributaries and the reaches they flow into, would count as mainstem
(`results.json` → `drainage_area_choice`). OWP's flood inundation mapping defines its "mainstems network"
differently: the NWM segments at and downstream of GAGES-II reference headwater gages, RFC
forecast points, evaluated sites and HI/PR sites (`mainstem_nwm_segs` in
[NOAA-OWP/inundation-mapping](https://github.com/NOAA-OWP/inundation-mapping/blob/a4effab4fbb935b3f3f84b8cdef1b1057a663d0c/tools/tools_shared_functions.py#L1140-L1237),
about 140,000 segments by its docstring). The overlap has not been computed.

**Network names** come from `../network_stats/results/T_basins.csv` (top 500 networks), so
run `repro/network_stats` first.

## Sources
| input | version / date | licence | SHA-256 / record |
|---|---|---|---|
| NWM v3.1.7 RouteLink_{CONUS,AK,HI,PRVI}.nc, [NCEP](https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/parm/) | file history 2025-08-05 (Lynker) | NOAA, public domain | in `fetch_data.py` (same as `network_stats`) |
| NHDPlusV2 VAA parquet (nhdplusTools), [HydroShare 6092c8a6…](https://www.hydroshare.org/resource/6092c8a62fac45be97a09bfd0b0bf726/) | file 2021-02-26 | from EPA/USGS NHDPlusV2 (public domain); HydroShare resource terms | `33f2bfdd…` |
| NHDPlusV2.1 EROMExtension, 21 CONUS VPUs, [EPA S3](https://dmap-data-commons-ow.s3.amazonaws.com/NHDPlusV21/Data/) | per-VPU versions in file names (e.g. `MS_10U_EROMExtension_07`); S3 2022-12-16 | US EPA/USGS, public domain | 21 hashes in `fetch_data.py`. Field meanings: NHDPlusV2 User Guide (McKay et al. 2012), EROM section |
| Physiographic divisions (Fenneman & Johnson 1946), [physio_shp.zip](https://water.usgs.gov/GIS/dsdl/physio_shp.zip), doi:10.5066/P9B1S3K8 | Last-Modified 2015-02-27; 1:7,000,000 | USGS, public domain | `3fd98856…` |
| National Waterway Network Lines (BTS NTAD / USACE), [FeatureServer layer 1](https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/Waterway_Networks/FeatureServer/1), doi:10.21949/1522176 | 6,859 features (6,856 with geometry); data last edited 2025-09-30; retrieved 2026-10-08 | CC0 1.0 (data.gov) | `d799e4ba…` (paged, written deterministically; re-download verified identical) |
| USACE eHydro SurveyJob outlines, [FeatureServer layer 0](https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/eHydro_Survey_Data/FeatureServer/0) | **live**; 123,284 outlines with survey start ≤ 2026-10-08; generalized to 0.0002° | no formal licence; "no explicit constraints" (ArcGIS item) | `f7e5b7dc…`. A changed hash is a warning; `check.py` allows ±2 points on eHydro shares |
| River names | `../network_stats/results/T_basins.csv` | — | built by `repro/network_stats` |
| Potomac runs | `../short_ts_switch` results (dt = 300 s) | — | optional; skipped if absent |

## How to run
```bash
repro/network_stats/run.sh          # once, for the river names
repro/diffusive_mainstem/run.sh     # fetch (~1.8 GB) -> flows -> analyze -> Potomac -> figures -> check
NWM_HYDROFABRIC_GDB=<path to extracted NWM v3 .gdb> repro/diffusive_mainstem/run.sh   # adds geometry_check
```
- Runtime after download: about 2 min for `prepare_flows.py` and 2.5 min for `analyze.py`.
- RouteLink files are hard-linked from `../network_stats/data` if verified copies exist.

**Outputs (`results/`):**
- `results.json`; `segments_conus.parquet` (every indicator, depth, layer flag and
  configuration per segment); `pareto.parquet`; `potomac_check.json`
- `fig_config_maps.png`, `fig_pareto.png`, `fig_depth_feasibility.png`
- `provenance.json`; `geometry_check.json` (optional)

## Checks (`check.py`; 228/228 pass, macOS arm64, 2026-10-28)
**Self-consistency:**
- Error-score classes partition the network; error-flagged km ≥ LS and BW km;
  effect-flagged km ≥ XF and KC km; effect-only + overlap = effect-flagged.
- BW equals the union of its parts.
- Nesting holds at segment level: A ⊂ B, F ⊂ B, C2 ⊂ C1, D1 ⊂ D2 (km and both budgets).
- No lake segment is in any configuration.
- Percentages lie in [0, 100], and both Pareto curves are monotone and complete.

**Literature and model reproduction:**
- Tang Eq. 25 gives 0.45 / 4.1 / 7.5%.
- Eq. 29 at 1e-4 is within 0.5 points of Table 5.
- Samuels L = 350 km at D = 5 m, S0 = 1e-5.
- Potomac outlet bankfull depth is 2.85 m.
- The rebuilt Potomac `False` loss equals `short_ts_switch/mechanism.json` (8.728 vs 8.7279%).

**Regression:** 192 values against `expected/expected.json`.

## Caveats
- **Assumption, not result:** diffusive routing is assumed to remove these errors and
  parameter effects. Its own errors with poor or approximate bathymetry are not counted.
- **Parameter effects are not errors.** The X floor and the K clamp are design choices of
  the MC algorithm (the floor sets X ≥ 0.25; the clamp sets Km ≥ dt). They
  change the computed flows, which is why they are screened, but they are budgeted
  separately and never added to the known-error budget.
- **The K clamp depends on dt and flow.** It is evaluated here at bankfull with dt = 300 s.
  At lower flows ck is smaller and the clamp binds less; above bankfull it can bind more. In
  `repro/short_ts_switch`'s Potomac storm (dt = 300 s) it bound at 11% of segments at their
  peak and on 9.9% of the routed volume, while this bankfull screen gives the K clamp about
  1% of the CONUS parameter-effect budget. Storm peaks there go overbank on most segments,
  so the bankfull screen probably understates the clamp during floods.
- **RouteLink slope floor.**
  - 381,463 MC segments (5.3% of km) sit at S0 = 1e-5. For 342,881 of them NHDPlusV2's
    own slope is 0–1e-5, i.e., NHDPlus's minimum; 23,654 have no NHDPlus slope (−9998).
  - The floor drives LS, BW (L ∝ 1/S0), XF and the Ponce "dynamic" class, and carries 63%
    of the known-error budget.
  - Many of these flags describe the parameter file, not the river. Measured slopes would
    move them, in either direction.
- **Bankfull depth is NWM's regression geometry.** It caps at 6.5 m, so big rivers are far
  shallower and narrower than in reality: on the 308 segments with mean annual flow above
  14,000 m³/s (the lower Mississippi), NWM bankfull Q has a median of about 470 m³/s. The
  indicators describe the NWM's MC as parameterized, which is the point for "known MC
  error". Samuels's L with bankfull depth is an upper bound for moderate flows.
- **Mean-flow depth.** It is EROM's mean annual Q/V on NWM widths. Narrow NWM widths
  overstate depth on very large rivers; that does not change the ≥ 1–2 m verdict there.
  Velocities are regression-based (Jobson 1996, per EROM), and 12% of segments use the
  Manning fallback.
- **Flow-weighting favours the mainstem.** The Potomac check shows the measured MC volume
  loss sits mostly in flat tributaries. Read the budget and error-flagged-km columns
  together.
- **Coastal zone.** In NWM v3 coastal configurations, SCHISM represents tidal and surge
  reaches. Some outlet-backwater (BW-ii) segments and the lowest mainstem segments would be
  handled there, not by a T-Route diffusive mainstem.
- **Structures and locks.** Navigable rivers (E, much of F) are lock-and-dam pools. Pool
  stages are controlled by structures that neither MC nor a plain diffusive model
  represents; the reservoir/structure coupling is a separate requirement.
- **Matching tolerance.** NWN at 200 m (sensitivity 100–500 m: 28,600–40,000 km). eHydro
  outlines are generalized to about 20 m and are a live snapshot.
- **Single storm validation.** One network (Potomac), synthetic uniform storm, `False`
  setting. Not a validation of the indicators for NWM operations (`True`).
- **Calibration.** NWM parameters were calibrated under MC with the short-time-step
  assumption. A diffusive mainstem would need its own calibration.
- **Physiography** is at 1:7,000,000. D1 and D2 are broad regional definitions.

## Updating `expected/`
Only with a written reason here.
- **2026-10-08:** first run.
- **2026-10-20:** rebuilt after three changes, each with its reason:
  - The X ≥ 0.25 floor was moved out of the known-error score into a separate
    parameter-effect flag, and the K clamp was added there. Reason: both are design limits
    of the algorithm, not errors, so they are budgeted separately. This changed the
    error-flagged share (8.4% → 7.8% of km), the known-error budget shares, configuration F
    (now B ∩ error-flagged ∩ surveyable: 43,569 → 40,420 km) and the Potomac shares.
  - Configurations and keys were renamed from "trunk"/"skeleton" to "mainstem", with C/D/E
    named low-slope / flat / coastal / navigable. No values changed with the names.
  - `repro/short_ts_switch` now builds the corrected kernel of `repro/kernel_fixes`, so the
    rebuilt Potomac `False` loss is 8.728% of the storm (8.119% with the earlier kernel).
  - Values that the change should not touch (LS, BW, Ponce, depths, layers, the D2 and E
    configurations' km and depths) were compared with the 2026-10-08 baseline before
    rebuilding, and were identical.
- **2026-10-28:** the mainstem (configuration A, and so B and F, which build on it) is
  selected by NHDPlusV2 `DivDASqKM` (divergence-routed drainage area) instead of
  `TotDASqKM` (approved by James Halgren, 2026-10-28). Reason: `TotDASqKM` counts area
  through minor divergences, so side channels and distributaries get the whole upstream
  area. The last reach of Antietam Creek (COMID 5894726) has `TotDASqKM` 16,124 km² but
  `DivDASqKM` 730 km² (USGS: 728), because a minor-divergence side channel off the Potomac
  (COMID 5894756, divergence = 2) enters it. Mississippi-delta bayous such as Bayou Perault
  have `TotDASqKM` about 3.1 million km² against `DivDASqKM` about 17. 29,023 segments
  (19,418 km) were mainstem only by `TotDASqKM` (`results.json` → `drainage_area_choice`).
  Only A, B and F values (and the A drainage-area sensitivity rows and the Potomac A/B
  shares) changed; all other regression values were identical before rebuilding.
