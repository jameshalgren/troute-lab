# repro/: reproducible experiments

Each subdirectory is one **self-contained, reproducible experiment** behind a
claim or figure in the paper. To the extent possible, we have specified library
versions and included data downloading automation to ensure reproducibility. 
In each case, `run.sh` executes the tests for that experiment. See notes below the
table for further details.

This folder and its scripts were assembled using extensive support from 
AI (Claude, primarily) and are being actively reviewed.

If you have any problems, please don't hesitate to post and issue or to reach out.

| Experiment | Question | Answer | Inputs | Runtime | Status (2026-10-05) |
|---|---|---|---|---|---|
| [`short_ts_switch/`](short_ts_switch/) | What does T-Route's `assume_short_ts` (WRF-Hydro's short-time-step assumption: previous-step upstream inflow) do to routed flows, how does it build up through a network, and how does it depend on dt? T-Route itself (CIROH-UA `d29f663`, built from source), True/False × dt 60/300/900/3600 s | A lot. On the Potomac at dt = 300 s, the NWM setting raises the outlet peak 38% and brings it 78 h earlier. The effect grows with the number of upstream segments, and reverses at dt = 3600 s (−4%, 72 h later). | t-route source and its `test/LowerColorado_TX` (recorded NWM forcing) fetched by commit SHA; NWM v3.1.6 RouteLink_CONUS.nc (Potomac extracted, synthetic storm) | ~7.5 min (clean, 4 jobs); optional closure diagnostics ~15 min | `check.py` passes (122/122), macOS arm64, 2026-10-07; clean rerun identical. Not yet reviewed by the author. **Closure diagnostics (2026-10-08, AI-assembled, not yet reviewed; optional `closure.sh`):** every kernel call of the 16 runs replayed through an instrumented float32 port (matches the Qj-patched T-Route bitwise in 90–98% of calls, < 6e-6 off by > 1e-3) to report the K, X, C, D the Cunge closure produced, where the X floor and K clamp bind, how the volume loss splits by regime, and the negative-flow guard's water gain; `check.py` 487/487 with it. **Rerun 2026-10-09 with the corrected kernel (`../kernel_fixes`, default; `KERNEL=unpatched` opt-in): 483/483; old → new values in `expected/kernel_update_2026-10-09.json`** |
| [`jit_scheduling/`](jit_scheduling/) | Scheduling model of routing work on P cores: 2020-style rounds, naive first-ready, JIT strides, and JIT priority without barriers (Hu's rule), plus work stealing, at segment, reach and subnetwork granularity; saturation (idle core-time, busy profile, one-core tail) and makespan. Why it was rerun: `RERUN_PLAN.md` | JIT strides keep cores busier than 2020-style rounds or naive first-ready (Mississippi, 36 cores: 4.8% idle vs 7.6% and 6.9%). JIT priority without barriers (Hu's rule) does better still (0.3%). | NWM v3.1.6 RouteLink_CONUS.nc (from `network_stats`); t-route `test/LowerColorado_TX` RouteLink pinned to `12a8eae0` (SHA-256 checked) | ~8 min CPU | `check.py` passes, macOS arm64, 2026-10-30. AI-built, independently reviewed 2026-10-29 and revised; not yet reviewed by the author |
| [`network_stats/`](network_stats/) | How many independent drainage networks does the NWM RouteLink have, and how large are they? Does the largest (Mississippi, 40.2% of CONUS) cap by-network parallelism at 3 processors? Transboundary cuts; Rio Grande continuity; comparison with NWM v2.1 and the 2020 counts; sizes of ~160 named sub-rivers (Ohio, Missouri, ...) found by their mouth segments | 12,820 CONUS networks. The Mississippi holds 40.2% of segments, so splitting work by whole network gives at most a 2.49× speedup (3 processors' worth). | NWM v3.1.6 RouteLink_{CONUS,AK,HI,PRVI}.nc (NCEP, ~320 MB), optional NWM v2.1 CONUS RouteLink (HydroShare, 269 MB), Natural Earth borders (pinned commit), committed USGS NHDPlus/NLDI snapshots `river_names.json` and `subriver_gnis.json` (SHA-256 checked) | ~1 min after download | `check.py` passes (398/398, of which 157 are sub-river checks), macOS arm64, 2026-10-06 |
| [`kernel_fixes/`](kernel_fixes/) | Corrections to T-Route's MC kernel (CIROH-UA `d29f663`): a patch series (Taher Chegini's NGWPC #123/#127 fixes, Brodie Alexander's rs_route #7, three new), a 46,128-case kernel harness (uninitialized reads, per-patch path tests, NGWPC comparison) and T-Route network runs (Potomac, LowerColorado) measuring each patch. **Since 2026-10-09 the corrected kernel is the default of every T-Route build in repro/** | Eight patches remove coding errors in T-Route's kernel. Applied together they change results little (Potomac outlet ±0.06%, volumes < 0.25%). The solver fixes without patch 0008 lose 13–16% of volume. | t-route source by SHA; NGWPC kernels at `34e6984d`/`9a3c303e` by SHA-256; `../short_ts_switch` inputs | ~1 min harness, ~40 min with network runs | `check.py` passes (140/140), macOS arm64, 2026-10-09. AI-written, not yet reviewed by the author |
| [`diffusive_mainstem/`](diffusive_mainstem/) | Screening, no model runs: assuming diffusive routing removes known Muskingum-Cunge errors (low slope, backwater) and MC parameter-limit effects (the X ≥ 0.25 floor, K clamped to dt), reported as two separate budgets, where are they on the NWM network, how much would a diffusive mainstem (or the alternatives: mainstem + confluence fringes, low-slope, flat, coastal, navigable) capture, and how much of each is deep enough to survey by boat? Potomac check against `short_ts_switch` | A diffusive mainstem (drainage area ≥ 10,000 km²) would cover 1.25% of network km but 95% of the known-MC-error budget and 95% of the parameter-effect budget. 59% of it is at least 2 m deep, enough to survey by boat. | NWM v3.1.6 RouteLink (4 domains), NHDPlusV2 VAA (HydroShare) and EROM mean annual flow (EPA, 21 VPUs), USGS physiographic divisions, BTS/USACE National Waterway Network, USACE eHydro outlines (live; snapshot 2026-10-08); ~1.8 GB; river names from `network_stats` | ~5 min after download | `check.py` passes (228/228), macOS arm64, 2026-10-28 (renamed from `diffusive_skeleton/`; error / parameter-effect split; mainstem selected by DivDASqKM). Not yet reviewed by the author |
| [`nwm_scale/`](nwm_scale/) | How many channel-routing calculations does the operational NWM do per day, now vs the author's 2020 sheet? Full NOMADS catalog of one day (every channel_rt file), per domain | 6.75×10¹¹ channel-routing calculations per day across all domains (CONUS 6.40×10¹¹), up from 5.79×10¹¹ in the 2020 estimate. | NOMADS `nwm/prod` listings and the S3 mirror (catalog committed in `expected/`), NWM v3.1.6 namelists, RouteLink segment counts | < 1 min from the committed catalog | 2026-10-29/30: 6.75×10¹¹/day all domains (CONUS 6.40×10¹¹) vs 5.79×10¹¹ in 2020. AI-assembled, not reviewed |
| [`mc_cost_variability/`](mc_cost_variability/) | How much does the MC kernel's per-call cost (secant iterations) vary, calm vs flood, across segments and over T-Route's 24-h chunk window? Cost vectors for `jit_scheduling` | A flood-time call does about 25% more solver work than a calm one (2.9 vs 2.3 iterations on average; typically 3 vs 2). | `../short_ts_switch` Potomac case (inputs rebuilt read-only), float32 kernel port copied from `closure_port.py` | ~7.5 min | `check.py` passes (57/57), macOS arm64, 2026-10-30; counting copy bitwise identical to the port over 1.14×10⁹ calls. Port, not the compiled kernel. AI-built, not reviewed |
| [`upstream_inflow_patch/`](upstream_inflow_patch/) | A patch for CIROH-UA T-Route (`d29f663`) that clips the network at named segments and reads their inflow series from CSV/NetCDF (MC). Does a clipped run fed the full run's boundary outflow reproduce the full run? Two builds: the patch alone, and the patch plus the kernel's Qj fix | Yes. With the kernel's Qj fix, clipped runs reproduce full runs bitwise. With the shipped kernel there are small differences (outlets unchanged). | `../short_ts_switch` inputs (LowerColorado_TX, Potomac storm) and its t-route source | ~3.7 min (clean, 4 jobs) | `check.py` passes (68/68), macOS arm64, 2026-10-08: bitwise with the Qj fix; rerun 2026-10-09 with the corrected kernel (`corrected`, default; `unpatched` opt-in): 68/68, bitwise. Not yet reviewed by the author |
| [`mc_courant_timestep/`](mc_courant_timestep/) | Reproduce Wlostowski's 2020 synthetic-channel experiment: Muskingum-Cunge with C > 1 delays and attenuates waves | Reproduced exactly: with C > 1, waves arrive later, peaks are lower, and hydrographs are more diffuse. | Fortran MC kernels, notebooks, helpers pinned by commit SHA on GitHub | ~3 min | Primary reproduced exactly (macOS arm64 and Docker linux/arm64). Exploratory notebook: 4 of 7 runs reproduced; its 2020 kernel reads uninitialized memory (see its README). **Extension (2026-10-08, AI-assembled, not yet reviewed):** same channel at dt = 30 s to 4 h (14400 s), two forcing variants, short-time-step and low-slope variants, and the K/X/C/D values the kernel's Cunge closure produces (instrumented port, matches the compiled kernel to 3e-7); `check.py` passes, macOS arm64 only |
| [`routelink_topwidth/`](routelink_topwidth/) | How is `TopWdthCC` (compound-channel top width) derived from `TopWdth` in the NWM v3 RouteLink files? | TopWdthCC = max(3·TopWdth, a stream-order floor) in CONUS; 3·TopWdth in AK, HI and PRVI. | NWM v3.1.6 RouteLink_{CONUS,AK,HI,PRVI}.nc from NCEP (~320 MB) | < 1 min after download | `check.py` passes (23/23), macOS arm64 |
| [`perf_2022/`](perf_2022/) | Repeat the 2022 1-year CONUS channel-only t-route run of NOAA-OWP/t-route#526 (22 h vs 4.5 h for WRF-Hydro) with 2022-era code (`a6efbf4e`) and current code (CIROH `d29f663`), each with and without the `kernel_fixes` patches; staged from a CONUS week and a Potomac year on a laptop to the CONUS year on the lab Mac | Not yet run. | NWM v2.1 retrospective CHRTOUT (slim download of the lateral-inflow variables), NWM v2.1 RouteLink; reference timings with sources in `perf_2022/reference_2022.json` | not yet run (needs gfortran/netCDF-Fortran, a ~60–90 GB download and the lab Mac; author approval pending) | Plan and setup scripts only, 2026-11-04. AI-written, not reviewed |
| [`wrfhydro_mc_x_factor/`](wrfhydro_mc_x_factor/) | What does removing the extra factor of 2 from WRF-Hydro's `SUBMUSKINGCUNGE` X formula ([NCAR/wrf_hydro_nwm_public#921](https://github.com/NCAR/wrf_hydro_nwm_public/issues/921), PR [#923](https://github.com/NCAR/wrf_hydro_nwm_public/pull/923)) change under NWM conditions (short-time-step assumption on, dt = 300 s)? The verbatim routine, original and patched, on the NWM v3.1.6 Potomac network with a synthetic storm, with T-Route on the same storm; single reaches built from NWM links; and, as theory, a prismatic channel against the exact convection–diffusion solution and a zero-inertia reference. Every part also runs with the assumption off | Yes: the extra 2 halves the physical diffusion. Under NWM settings the fix lowers flood peaks 1.5–3.7% on rivers above ~650 km² and delays them 1–3 h (Potomac outlet −1.7%, +2.5 h). Small streams barely change. T-Route agrees within 0.02 points. | `module_channel_routing.F90` fetched by commit SHA (`55ed71c8`), the patch in the folder; NWM v3.1.6 RouteLink_CONUS.nc (NCEP, SHA-256 checked); river names from NHDPlusV2.1 (live, labels only); part 3 reuses `../short_ts_switch` inputs and `../kernel_fixes` | ~6.5 min clean (T-Route builds), ~2.5 min after | `check.py` passes (462/462), macOS arm64, 2026-11-02, clean rerun identical; also 462/462 against a `-ffp-contract=off` build (STS OFF checks use build-to-build tolerances). Reviewed in part by the author (README, 2026-11-02) |

## Running an experiment

Prerequisites: [`uv`](https://docs.astral.sh/uv/) (it installs the pinned Python
itself), network access to the input URLs, and for `mc_courant_timestep/` a
Fortran compiler (`gfortran`) plus a C compiler. `short_ts_switch/` also needs `make`,
`git`, and netCDF-C/netCDF-Fortran (`nc-config`, `nf-config`) to build T-Route. Then:

```bash
repro/<experiment>/run.sh          # fetch -> run -> check; exit status 0 = reproduced
```

`mc_courant_timestep/` also ships a `Dockerfile` (base image pinned by digest) for a
platform-independent run. Docker images are derived from lean, pinned base images
(e.g. Debian slim by digest, as here). Everything else is installed explicitly and
pinned, rather than from pulling prebuilt science images.

## Conventions (every experiment directory)

| File | Purpose |
|---|---|
| `README.md` | The question, provenance of inputs and method, how to run, expected results, known caveats |
| `pyproject.toml` | **Exact** (`==`) pins for every direct dependency; `requires-python` set precisely |
| `.python-version` | The exact interpreter `uv` installs and uses |
| `uv.lock` | Committed lock file: the full resolved dependency tree with hashes. `run.sh` uses `uv sync --locked`, so a stale lock fails loudly instead of drifting |
| `fetch_data.py` | Downloads every input from a public URL into `data/` (gitignored). Verifies SHA-256 against hashes recorded in the script; idempotent (skips verified files); fails with a clear message if a URL is gone or a hash differs |
| analysis script(s) | Do the work; write everything into `results/` (gitignored) |
| `expected/` | Machine-readable expected results (JSON), with the source of each value |
| `check.py` | Compares `results/` with `expected/` using stated tolerances; exits non-zero on mismatch |
| `run.sh` | One command: `uv sync --locked` → fetch → run → check |
| `provenance.py` | Writes `results/provenance.json`: UTC timestamp, platform, Python and `uv` versions, resolved package versions, input checksums, source commit SHAs, compiler versions |

Generated, never committed (see `.gitignore`): `data/`, `results/`, `build/`, `.venv/`.

### Pinning rules (mostly for AI tools interacting with this repository)
- Pin direct dependencies with `==` in `pyproject.toml`; `uv.lock` pins the rest
  (transitive dependencies, wheel hashes).
- Pin remote sources by **immutable** identifiers: git commit SHAs in raw URLs, and a
  SHA-256 for every downloaded file. Operational URLs that can change (e.g., NCEP's
  `nwprod` tree) are recorded with the hash and download date we observed; if NCEP
  replaces a file, `fetch_data.py` stops and says so rather than silently using new data.
- System tools that `uv` cannot pin (compilers) are recorded in `provenance.json`, and
  pinned in the experiment's Dockerfile where one exists.

### Updating an experiment
Change `pyproject.toml`, then `uv lock` in the experiment directory, rerun `run.sh`, and
update `expected/` only with a written reason in the experiment's README.

## Citing and archiving
Cite an experiment by repository URL **and commit SHA** (e.g.,
`https://github.com/jameshalgren/troute-lab/tree/<sha>/repro/routelink_topwidth`).
For publication, the plan is to archive a tagged release of this repository on
[Hydroshare](https://hydroshare.org/). Large public inputs (RouteLink
files) are not redistributed; they are cited by URL plus SHA-256. If NOAA/NCEP removes them,
a deposit of the exact files (with NOAA's public-domain status noted) would be needed.
No deposit has been made yet.
