# Upstream inflow boundaries for T-Route: a patch and a clip-and-replay test

*AI-assembled (Claude, 2026-10-08); not yet reviewed by the author. The patch is a
proposal to share (for example with the CIROH-UA community version of T-Route). It is not
ready for direct inclusion.*

## Question

The question at hand is whether T-Route can route only part of a network and still produce
valid results: can we cut a network at chosen segments and supply an inflow time series at
each cut, so that only the part downstream of the cuts needs to be examined? "Valid" here
means that the clipped run, fed the full run's outflow at the cuts, reproduces the full run
downstream (the test below). Several attempts have been made in this direction: NGWPC had
something close and removed it, and the old BMI route no longer runs. None of the current
forks offers this capability (checked 2026-10-08 on NOAA-OWP, NGWPC and CIROH-UA). This
patch is intended as a partial answer to that need. It covers Muskingum-Cunge routing in
the serial and by-network compute modes. It is not fully developed and should be
considered only sufficient to support the tests and examples in this lab.

## The patch: `troute-upstream-inflow.patch`

Against [CIROH-UA/t-route `d29f663`](https://github.com/CIROH-UA/t-route/commit/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6)
(head of `ngiab`, 2026-09-18). It changes Python only, in four files (303 lines added,
7 changed), and needs no Fortran or Cython changes. Apply it with
`git apply troute-upstream-inflow.patch` in a checkout of that commit, then build as
usual.

**Configuration** (two new optional keys in `compute_parameters.forcing_parameters`):

```yaml
compute_parameters:
  forcing_parameters:
    upstream_inflow_file: boundary_inflow.csv   # or .nc
    upstream_inflow_segments: [5756826]         # optional; default: every segment in the file
```

**File formats.** Values are each boundary segment's **outflow** in m³/s, i.e. the flow it
passes to the segment below.
- CSV: one row per segment. The first column is the segment ID; the other column headers
  are UTC timestamps.
  ```
  feature_id,2021-08-23 13:00:00,2021-08-23 14:00:00,...
  5756826,168.63,172.53,...
  ```
- NetCDF: variable `flow` (or `streamflow`, `q`, `inflow`) on dimensions
  `(time, feature_id)` in either order, with coordinates `time` and `feature_id`.

**What it does.**
1. `AbstractNetwork.apply_upstream_boundaries()` runs at the end of network construction.
   It removes each boundary segment B, and everything upstream of B, from `connections`,
   the reverse connections, the independent networks and the reaches. B stays listed as an
   upstream of the segment it drains to. The removed rows stay in the parameter table but
   are not routed or written. Boundaries that lie upstream of another boundary are
   dropped with a warning.
2. For each forcing loop, `upstream_boundary_flows(t0, dt, nts)` interpolates each series
   linearly to the routing steps t0 + k·dt. Outside the series' range the end values are
   held, with a warning.
3. In `compute.py` (`serial` and `by-network` methods), each independent network finds
   the boundaries among its upstreams and passes their series to the MC kernel through
   `compute_network_structured(upstream_results=...)`. This is the hook T-Route already
   uses to pass results between sub-networks (NOAA-OWP #188, 2021). The segment below B
   adds B's prescribed outflow to its other upstream inflows exactly as it would add B's
   routed outflow. B's own lateral inflow is not added again.
4. B's initial state is its series value at t0, or the restart value if the series starts
   later. Between forcing loops, `new_q0` carries B's end-of-loop value forward.
5. `main_v04` raises an error for other compute methods and for diffusive (hybrid) runs.

**Not covered or not tested:** diffusive routing (its upstream-boundary array is a stub in
every fork); the `by-subnetwork-jit*` methods; the BMI path (`troute_model.py`); the older
`main_v03`; lakes as boundaries (`break_network_at_waterbodies`); DA gages at or upstream
of a boundary; HYFeatures networks. Boundaries are absent from the output because they are
not routed.

## Test design (`test_clip.py`)

Both domains are the inputs of [`../short_ts_switch/`](../short_ts_switch/), at dt = 300 s,
24-h forcing loops, serial MC, with `assume_short_ts` True and False:
- `lc_nwm`: LowerColorado_TX (11,248 segments), recorded NWM forcing, 28 h (2 loops).
- `potomac_storm`: Potomac (16,454 segments), synthetic storm, the first 480 h (20 loops;
  the outlet peaks at about 223 h with True and 301 h with False).

**Boundaries are chosen by a fixed rule.** B1 is the mainstem (longest-path) segment whose
upstream segment count is closest to half the network. B2 is the largest tributary entering
the mainstem below B1.
- `lc_nwm`: B1 = 5756826 (Colorado River, 31.25 N 98.59 W, 6,057 segments upstream). Its
  downstream segment has no other upstream, so the clip falls inside a reach. B2 = 5757818
  (30.65 N 98.43 W, 1,924 segments), by coordinates the Llano River mouth near Kingsland,
  TX. It enters a junction. After clipping, 3,267 segments remain.
- `potomac_storm`: B1 = 5894852 and B2 = 8445028. Both drain into 4507316 at 39.32 N
  77.73 W, the Potomac–Shenandoah confluence at Harpers Ferry by coordinates. B1 is the
  Potomac above it (7,585 segments upstream); B2 is presumably the Shenandoah mouth (1,754
  segments). The names come from coordinates only and were not checked against NHD names.
  After clipping, 7,115 segments remain.

**Procedure.**
1. Full run with the patched build and no boundaries.
2. A boundary file built from the full run: each boundary's routed outflow at every
   300-s step, with the restart flow at t0. It is written as CSV for `lc_nwm` and as
   NetCDF for `potomac_storm`. The same series is also written sampled hourly (CSV), to
   exercise the interpolation.
3. Clipped runs from each file.
4. Every remaining segment is compared at every step.
5. `lc_nwm` only: the step-resolution run is repeated with `parallel_compute_method:
   by-network`, and with `upstream_inflow_segments: [B1]` (the file holds both boundaries,
   so B2's basin is routed).

**Two builds.** `default` is the patch alone. `qj` is the patch plus the Fortran fix from
[`../short_ts_switch/`](../short_ts_switch/) (README "Mechanism checks", E). That fix
initializes the MC secant variable `Qj_0`, which the kernel reads before setting it. The
shipped kernel's results therefore depend on leftover memory, i.e. on the order in which
segments are computed, and clipping changes that order.

**Kernel update (2026-10-09).** The builds were renamed and the kernel replaced under the
author's rule that tests use a kernel without known coding errors:
- `corrected` (the default) is the patch plus the corrected MC kernel
  (`../kernel_fixes/patches/0001-0008`: Taher Chegini's NGWPC #123/#127 fixes, Brodie
  Alexander's rs_route #7, three new ones). It replaces `qj`.
- `unpatched` (opt-in, `COMPARE_UNPATCHED=1 ./run.sh`) is the patch with the kernel as
  published. It replaces `default`.

Results with the corrected kernel (`results/results_corrected.json`, 68/68 checks):
- **Step-resolution input:** the clipped runs again reproduce the full runs bitwise in
  every case, setting and method.
- **No boundary file:** the patched build equals `../short_ts_switch`'s corrected-kernel
  build bitwise.
- **Hourly input:** errors change on the LowerColorado only.
  - False: max 22.8 → 15.9 m³/s, but 1.63 → 2.42 times the worst segment's peak.
  - True: 0.65 → 0.34 m³/s (0.013 → 0.0068 of peak).
  - Potomac: 1.93 → 1.91 and 1.41 → 1.43 m³/s (≤ 0.12% of peak, as before).

The tables below are the 2026-10-08 values: `qj` there corresponds to `corrected` here, and
`default` to `unpatched`, whose numbers are unchanged. The old baseline is in
`expected/expected_qj_kernel_2026-10-08.json`.

## Results (macOS arm64, gfortran 15.2.0, 2026-10-08; `results/results_*.json`)

**Step-resolution boundary input, qj build: the clipped runs reproduce the full runs
bitwise.** This holds for every case, both settings, the by-network method and the
`upstream_inflow_segments` subset: 0 of 3,267 × 336 (`lc_nwm`) and 7,115 × 5,760
(`potomac_storm`) values differ.

**Step-resolution input, default build (the kernel as shipped):**

| Case | assume_short_ts | segments that differ | max abs error (m³/s) | max error / segment peak | outlet peak error |
|---|---|---|---|---|---|
| lc_nwm | False | 209 of 3,267 | 16.2 | 0.72 | 0 |
| lc_nwm | True | 91 | 0.161 | 0.0045 | 0 |
| potomac_storm | False | 376 of 7,115 | 0.0037 | 2.3e-6 | −7.7e-8 |
| potomac_storm | True | 281 | 0.0024 | 1.1e-6 | 0 |

These differences come from the kernel, not the patch:
- They vanish with the Qj fix.
- In the default build, segments that are not downstream of any boundary, which no
  boundary flow can reach, also change slightly: up to 1.9e-5 m³/s on the Potomac and
  1.2e-7 m³/s on the LowerColorado.
- The large `lc_nwm` False values are on the Colorado just below the Llano confluence
  (6 to 11 segments down, peaks of 20 to 60 m³/s in this 28-h window).
  `../short_ts_switch` found the same defect moving individual False segments by up to
  80% of their peak.

Without a boundary file, the patched default build reproduces the unpatched build's
end-of-hour flows in `../short_ts_switch/results/runs/` bitwise, for both cases and both
settings.

**Hourly boundary input, linearly interpolated (qj build):**

| Case | assume_short_ts | max abs error (m³/s) | max error / segment peak | outlet peak error | outlet volume error |
|---|---|---|---|---|---|
| lc_nwm | False | 22.8 | 1.63 | 0 | 0 |
| lc_nwm | True | 0.65 | 0.013 | 0 | 0 |
| potomac_storm | False | 1.93 | 0.0012 | −3.1e-5 | 3.4e-6 |
| potomac_storm | True | 1.41 | 0.0006 | −1.1e-4 | −3.5e-6 |

On the Potomac, hourly input costs about 0.1% of a segment's peak at most. On the
LowerColorado the Llano boundary jumps from 0 (its restart value) to 3.8 m³/s within the
first hour. Linear interpolation smooths that front. The False scheme reacts strongly to
sharp inflow fronts (negative C2 and the negative-flow guard; `../short_ts_switch`,
"Mechanism checks", B), so its error there is large. Within 28 h the LowerColorado
boundaries do not reach the outlet, so the outlet errors there are trivially 0.
Supplying boundary series at the routing step, or at least finer than the fronts they
carry, avoids this.

**Cost:** the clipped Potomac run (43% of the segments) took 12.7 s against 28.0 s for
the full run.

## How to run

```bash
repro/upstream_inflow_patch/run.sh          # inputs -> 2 builds -> 16 + 16 runs -> check
JOBS=8 repro/upstream_inflow_patch/run.sh
FORCE=1 repro/upstream_inflow_patch/run.sh  # rebuild and rerun everything
```

A clean run (no `.venv/`, `build/` or `results/`; the sibling's inputs already present)
took 3 min 41 s on a 16-core Apple-silicon Mac (2026-10-08). `check.py` passed 68/68.
- **Needs:** `uv`, gfortran, a C compiler, make, git, and netCDF-C + netCDF-Fortran
  (`nc-config`, `nf-config`), as for `../short_ts_switch`.
- **Inputs:** `run.sh` reads the inputs of `../short_ts_switch/build/inputs/`. It creates
  them there (`fetch_data.py`, `make_inputs.py`) only if they are missing, and never
  touches that experiment's T-Route build.
- **Source:** the T-Route source comes from `../short_ts_switch/data/t-route` if that
  holds the pinned commit, else it is fetched by SHA into `data/t-route`.
- **Regression check:** check 3 (no change without boundaries) needs
  `../short_ts_switch/results/runs/` from that experiment's `run.sh`. Without them it is
  skipped with a note.

| File | Purpose |
|---|---|
| `troute-upstream-inflow.patch` | The patch (format-patch style, against CIROH-UA d29f663) |
| `build_patched.py` | Builds T-Route + patch (`--variant default`) or + patch + Qj fix (`--variant qj`) into `build/<variant>/`, following t-route's compiler.sh/Dockerfile; records every command in `build/<variant>/build_info.json` |
| `run_troute.py` | One T-Route run through `main_v04`, recording native-step flows of chosen segments |
| `test_clip.py` | Chooses boundaries, runs full and clipped cases, writes boundary files, compares → `results/results_<variant>.json` |
| `check.py` | The checks listed in its docstring; `expected/expected.json` holds the regression values |
| `provenance.py` | Writes `results/provenance.json` (identical copy in every experiment) |
| `pyproject.toml`, `uv.lock`, `.python-version` | Same pins as `../short_ts_switch` |

The default build lives in `.venv/` and the qj build in `build/venv_qj/`, selected with
`UV_PROJECT_ENVIRONMENT`. `uv sync --locked --inexact` keeps the T-Route packages that
`build_patched.py` installs (as in `../short_ts_switch`).

## Caveats

- One commit (CIROH-UA `d29f663`), one platform. Two networks, two boundaries each, one
  timestep (300 s).
- The test checks that clipping is *consistent* with the full run. It does not test the
  use of observed or externally modelled inflows, where the boundary series and the
  routed network disagree.
- The exact-replay result needs the Qj fix, which is a separate change to the Fortran
  kernel and is not part of this patch. With the shipped kernel, replay is exact only up
  to that defect. The fix itself is not ours: Taher Chegini's
  [NGWPC/t-route PR #123](https://github.com/NGWPC/t-route/pull/123) (merged 2026-08-21)
  made `Qj` and `C1..C4` `intent(inout)`, and Brodie Alexander's
  [CIROH-UA/rs_route PR #7](https://github.com/CIROH-UA/rs_route/pull/7) fixed C1–C4.
  Credit goes to them and their teams; the CIROH-UA fork used here lacks the fix.
- NGWPC's refactored `compute.py` (NGWPC `development`, NOAA-OWP `ngwpc`) replaced the
  code paths changed here. A port there would go through its `ExecutionPlan`, as its own
  `NotImplementedError` message suggests.
