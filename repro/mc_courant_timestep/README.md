# Muskingum-Cunge Courant number vs. timestep (Wlostowski, 2020)

*AI-assembled (Claude, 2026-10-05); not yet reviewed by the author.*

## Question
On a uniform synthetic channel, what happens to Muskingum-Cunge (MC) routing when the
Courant number C exceeds 1? Adam Wlostowski's answer (`courant_test.ipynb`, 2020-10-06):

> When C > 1, insidious numerical errors change in the timing and magnitude of simulated
> wave propagation. [...] Experiment results show that when C > 1, the timing of wave
> propagation is delayed, peak flows are lowered, and waves are more temporally diffusive.

Background: Adam Wlostowski's 2020 notebooks
[`courant_test.ipynb`](https://github.com/awlostowski-noaa/t-route/blob/27e06eefc43135a767f20cd0561190af7b8f4ed1/notebooks/courant_test.ipynb)
and [`mc_numerical_dispersion.ipynb`](https://github.com/awlostowski-noaa/t-route/blob/de529705a11f0e305f9b4d46c32d65d08e289de7/notebooks/mc_numerical_dispersion.ipynb);
the Courant-number output went upstream in
[NOAA-OWP/t-route#152](https://github.com/NOAA-OWP/t-route/pull/152).

## Provenance
Everything is fetched from `awlostowski-noaa/t-route` at fixed commits (raw URLs pinned
by SHA; file SHA-256 recorded in `fetch_data.py`, observed 2026-10-05):

| Role | File | Commit |
|---|---|---|
| Primary notebook | `notebooks/courant_test.ipynb` | `27e06eefc43135a767f20cd0561190af7b8f4ed1` (merged upstream with NOAA-OWP/t-route PR #152) |
| Primary kernel (unmodified) | `.../MC_singleSeg_singleTS/courant_dev/MCsingleSegStime_f2py_NOLOOP-anw.f90` + `.../MC_singleSeg_singleTS/varPrecision.f90` (the notebook copies the latter into `courant_dev/`) | same |
| Exploratory notebook | `notebooks/mc_numerical_dispersion.ipynb` (branch `segment-merge`) | `de529705a11f0e305f9b4d46c32d65d08e289de7` |
| Exploratory kernel (unmodified) | `MCsingleSegStime_f2py_NOLOOP.f90`, `varPrecision.f90`, bind(c) wrapper `pyMCsingleSegStime_NoLoop.f90` | same |
| Exploratory helpers | `nhd_network.py` (imported unmodified), `mc_reach.pyx` and `nhd_io.py` (ported) | same |

The Fortran is compiled, never edited. Python code that drove the kernel in the
notebooks is ported (see "Fidelity of the ports").

## How to run
```bash
repro/mc_courant_timestep/run.sh            # ~3 min; QUICK=1 skips the exploratory sweep
```
Needs `uv`, `gfortran`, and a C compiler. `run.sh`: `uv sync --locked` (Python 3.12.13,
numpy 2.5.3 with f2py, meson 1.12.1, ninja 1.13.2, scipy 1.18.1, pandas 3.0.6, matplotlib
3.11.2; full tree in `uv.lock`) → `fetch_data.py` → `build_kernels.py` (into `build/`;
compiler versions and exact commands in `build/build_info.json`) → `run_experiment.py` →
`run_extended.py` + `plot_extended.py` (extension to dt = 4 h, ~15 s) →
`run_dispersion.py` (three kernel builds) → `check.py`. With `QUICK=1` the exploratory
sweep is skipped; the primary experiment and the extension still run and are checked.

Platform-independent alternative (Debian 12 + gfortran 12.2.0 from a dated
snapshot.debian.org archive, base images pinned by digest):
```bash
cd repro/mc_courant_timestep
docker build -t troute-repro-mc-courant .
docker run --rm -v "$PWD/results:/work/results" troute-repro-mc-courant
```

Outputs in `results/`: `courant_test.json`, `courant_test_outlet.csv` (outlet
hydrograph, depth, and C for every dt), `courant_test_hydrographs.png`,
`dispersion_<build>.json/.png`, `extended_*` (see "Extension to 3600 s and 4 h"), and
`provenance.json` (platform, Python, uv, package
versions, input hashes, commit SHAs, compiler versions, build commands).

## Primary experiment: `courant_test.ipynb`
20 km channel, ten 2000 m segments; bw = 50 m, tw = 100 m, twcc = 500.6 m, n = 0.028,
ncc = 0.03136, cs = 0.42, s0 = 0.008; initial Q = 2000 m³/s and depth 2.78 m everywhere;
lateral inflow on segment 0 = 2000 m³/s + a Gaussian pulse peaking at 500 m³/s at 6 h
(σ = 0.5 h); 15 h; dt = 30, 60, 120, 300, 600 s. The kernel is compiled with f2py
exactly as in the notebook.

| dt (s) | notebook max C | reproduced max C | notebook peak time (h) | reproduced peak time (h) | reproduced peak Q (m³/s) |
|---|---|---|---|---|---|
| 30 | 0.18 | 0.1802 | 6.4333 | 6.4333 | 2497.669 |
| 60 | 0.36 | 0.3603 | 6.4333 | 6.4333 | 2497.717 |
| 120 | 0.72 | 0.7206 | 6.40 | 6.40 | 2497.944 |
| 300 | 1.8 | 1.8016 | 6.75 | 6.75 | 2494.460 |
| 600 | 3.6 | 3.6031 | 7.50 | 7.50 | 2479.283 |

Notebook values: peak times from the saved cell-7 stdout (`check.py` re-parses them from
the fetched notebook); max C from the saved figure legend (2 decimals). Peak flows were
not printed by the notebook; they are a regression baseline from this reproduction.
**Reproduced exactly** (all peak times identical, all max C within rounding) on macOS
arm64 / gfortran 15.2.0 and in the Docker image (Linux arm64 / gfortran 12.2.0). The
hydrograph figure matches the notebook's saved figure.

Tolerances in `check.py`: peak time ±1 output interval (dt/3600 h); max C ±0.01; peak
flow rtol 1e-4 against the baseline.

## Corrected kernel (added 2026-10-09)
Project rule (author, batch 04, P1c): tests use a kernel without known coding errors. The
2020 kernel above has the same coding errors as T-Route's current kernel. See
[`../kernel_fixes/`](../kernel_fixes/README.md). They are:
- `Qj_0` is read before it is set;
- `Qj` and `C1..C4` are `intent(out)` but read;
- the `qdc` test reads an `intent(out)` argument;
- the Secant control flow can treat a failure as convergence (corrected with NGWPC's
  degenerate-root restart, as in T-Route's series);
- the no-flow branch leaves `X`, `velc`, `ck` and `cn` undefined, and its `courant` returns
  NaN at h = 0.

The faithful build stays as it is, because it reproduces the 2020 notebook exactly. Beside
it:
- `build_kernels.py` compiles a corrected copy (`../kernel_fixes/patches/anw2020/`) as
  `mc_sseg_stime_anw_corrected`;
- `run_corrected.py` reruns the primary experiment and the extension's volume-forcing
  variants with both kernels (`results/corrected_kernel.json`).

Result: on this channel the only corrected path ever taken is the degenerate-root
restart (FIX 0008, NGWPC 4ecefec1), in a few steps:
- the primary experiment's outlet hydrographs agree within 9.4 × 10⁻⁷ of peak (≤ 0.0023
  m³/s on 2,500 m³/s);
- all 52 extension runs (4 variants × 13 dt) agree within 0.0001% in peak flow, 0.005 h
  in travel time and 10⁻⁴ in volume ratio (`check.py`).

The numbers in this README therefore hold for the corrected kernel as well. The two kernels differ on the error paths: on a dry channel the
faithful kernel returns ck = 10.3 m/s for a depth it did not publish, and NaN at h = 0;
the corrected one returns 0.

## Exploratory configuration: `mc_numerical_dispersion.ipynb` (clearly not a result)
An earlier notebook (2020-09-07) on the same theme: 20 km, dx = 300 m (67 segments) fed by
two headwater segments, baseflow 100 m³/s + a 150 m³/s Gaussian pulse at day 2 (σ = 2 h),
6 days, dt = 5, 10, 30, 60, 120, 400, 600 s, and an `assume_short_ts` switch (the saved
run used `False`). The notebook ran t-route's Cython `mc_reach.compute_network`; here
that reach loop is ported to Python and calls the original Fortran through the original
bind(c) wrapper with ctypes.

**Finding: the 2020 kernel at this commit is not deterministic.** In
`MCsingleSegStime_f2py_NOLOOP.f90` @ de52970, subroutines `secant_h0` and `secant_h`
declare a local `AREAC` that is assigned only when depth > bankfull but is used in
`(AREA+AREAC)` on every call. gfortran warns: `'areac' may be used uninitialized`. The
result depends on whatever is in that memory, which varies with compiler, flags, and
platform. (The later kernel used by `courant_test.ipynb` sets `AREAC = 0.0` explicitly
under "new initialization" and compiles without this warning.) So three builds of the
same unmodified source are run:

| Build | Flags | What it shows |
|---|---|---|
| `init_zero` | notebook flags + `-finit-real=zero` | Deterministic. **Matches the notebook's saved output for dt = 10, 30, 400, 600 s** to ≤ 1e-6 relative (bit-identical for 400 and 600 s in Docker). `check.py` gates on these four. |
| `notebook_flags` | `-O3 -fPIC`, as in the notebook | Platform-dependent: on macOS/gfortran 15, C at peak flow is 0.2–7% lower than the notebook for the four well-behaved runs; under Linux/gfortran 12 they are instead about 0.02% higher. Reported, not checked. |
| `init_nan` | + `-finit-real=nan` | dt = 30 s only: the routed depth collapses to 0 (wrong). Shows how much the uninitialized value matters. |

Notebook vs. `init_zero` build, `assume_short_ts = False`:

| dt (s) | notebook C at peak | reproduced | notebook max outlet depth (m) | reproduced |
|---|---|---|---|---|
| 5 | 0.579 | 0.0480 | **161.9** | 1.264 |
| 10 | 0.09609824 | 0.09609824 | 1.2637823 | 1.2637823 |
| 30 | 0.28829488 | 0.28829488 | 1.2637833 | 1.2637832 |
| 60 | 6.98 | 0.577 | **451.2** | 1.264 |
| 120 | 12.29 | 1.153 | **443.4** | 1.263 |
| 400 | 3.8034992 | 3.803499 | 1.2431936 | 1.2431935 |
| 600 | 5.6340904 | 5.6340885 | 1.2192045 | 1.2192039 |

The notebook's non-physical depths at dt = 5, 60, and 120 s could **not** be reproduced
with any of the three builds. They are consistent with (but not proven to be) the
uninitialized `AREAC` taking non-zero values on the 2020 machine, and with the author's
own note that "I remain confused about the behavior of this model". With the
deterministic build, peak outlet flow and timing shift as in the primary experiment:
dt ≤ 60 s peak at day 2.082 (249.5 m³/s), dt = 400 s at 2.315 (242.8), dt = 600 s at
2.472 (235.0). Switching `assume_short_ts` to `True` changes outlet C at peak and
outlet depth by ≤ 0.02% and peak flow by < 0.05%. One exception: at dt = 120 s with
`False`, the maximum depth over *all* segments reaches 1.556 m (vs. 1.265 m with `True`),
a transient spike whose cause was not investigated. The switch acts only at the single
junction in this setup, so this is **not** an evaluation of it on a real network.

## Extension to 3600 s and 4 h (14400 s)

*AI-assembled (Claude), 2026-10-08; not yet reviewed by the author.* This extension
stretches Wlostowski's test to routing timesteps of 3600 s and up to 4 h (14,400 s), as
was done for `../short_ts_switch`, and reports the X and K values the Cunge closure
produces. Code: `run_extended.py` (runs),
`kernel_port.py` (instrumented port), `plot_extended.py` (figures); checks in `check.py`
("Extension"). The reproduction above, its code and `expected/courant_test.json` are
unchanged; as a guard, `run_extended.py` reruns the notebook configuration (15 h, dt
30–600 s) through the extended driver and `check.py` requires it to equal
`run_experiment.reach_sim` exactly (it does: max |difference| 0.0 m³/s).

### Design
- **Same channel, kernel and driver** as the notebook (20 km, ten 2000 m segments,
  s0 = 0.008, h0 = 2.78 m, Q0 = 2000 m³/s, Gaussian lateral pulse of 500 m³/s at 6 h,
  σ = 0.5 h, on segment 0; compiled `MCsingleSegStime_f2py_NOLOOP-anw.f90`; current-step
  upstream flow `quc`, i.e. `assume_short_ts = False`).
- **dt** = 30, 60, 120, 300, 600, 900, 1200, 1800, 3600, 5400, 7200, 10800, 14400 s.
- **Duration 120 h** (a multiple of every dt). At dt = 14400 s the clamped scheme moves
  the wave about one segment per step, so the outlet centroid arrives about 38 h after
  the input (table below); the slowest tails (low-slope variants) last to about 75 h. `check.py` requires the outlet
  to be back within 1e-3 of the peak excess at 120 h in every run (worst: 6.7e-4).
- **Volume balance** is measured above a no-pulse baseline run with the same dt and
  settings: V_in = Σ(ql − Q0)·dt over routed steps, V_out = Σ(Q_out − Q_base)·dt. The
  baseline stays within 0.002 m³/s of 2000 m³/s.
- **Two forcing variants, kept separate.** The pulse has σ = 0.5 h, so steps of 1800 s and
  more sample it with one or two points.
  - *point* (faithful extension): the notebook's own formula: Gaussian samples on
    `np.linspace(0, duration, int(duration/dt))`, rescaled so the largest sample is
    500 m³/s. At large dt this changes the injected volume (1.01× the true pulse at
    3600 s, 3.30× at 14400 s) and its timing.
  - *volume*: the same Gaussian averaged over each step (applied over the step ending at
    t), so every dt injects the same pulse volume (|ratio − 1| < 1e-14). The core Courant
    results below use this variant. `results/extended_forcing.png` shows both.
- **Two smaller variants**, both with volume forcing:
  - *short-time-step assumption enabled*: quc = qup (previous-step upstream flow), the
    T-Route `assume_short_ts = True` / WRF-Hydro behavior.
  - *low slope*: s0 = 1e-4 and 1e-5, everything else equal, with every segment started
    at the kernel's normal depth for 2000 m³/s (its own Manning conveyance, solved
    numerically): 13.81 m and 18.73 m, both above bankfull (10.5 m). For reference, the
    kernel's normal depth at s0 = 0.008 is 4.38 m; the notebook starts at 2.78 m, which
    only seeds the first depth iteration. The flows start at 2000 m³/s in every case.
- **Closure diagnostics.** The compiled kernel returns only Q, depth, velocity, Ck, C and
  the final X. `kernel_port.py` is a line-by-line float32 port of `muskingcungenwm`,
  `secant2_h` and `courant`. It runs beside the Fortran on the same inputs at every
  segment-step and records what the Cunge closure (`secant2_h`) produced: Ck, raw dx/Ck,
  Km = max(dt, dx/Ck) (L306), X from both secant estimates (interval 1, floor 0, L327;
  interval 2, floor 0.25, L331; clamped and unclamped), the reference discharge,
  C1–C4, and the cell Reynolds number D = Q/(B·S0·Ck·dx) (Ponce's form, with the
  kernel's own reference Q, width and Ck). **Agreement with the compiled kernel:** over
  all 65 runs, outflow within 3.4e-7 and depth within 4.3e-7 relative (float32 rounding,
  1–2 ulp; the compiled code can fuse multiply-adds), final X within 3e-8. The port
  starts `Qj_0` at 0 (the read-before-set defect fixed by ../kernel_fixes patch 0001 is present in this 2020 kernel
  too); carrying the previous call's value instead matched less often. The hydrographs
  reported here always come from the Fortran. Per segment-step arrays are written to
  `results/extended_closure/<variant>_dt<dt>.npz`.

### Results: the core channel (s0 = 0.008)

Peak shifts and changes are relative to dt = 30 s of the same variant. "Peak above
baseflow" is the outlet peak minus the no-pulse baseline. Km = dt and the X floor are
fractions of all segment-steps.

| dt (s) | max C | peak time shift (h) point / volume | peak above baseflow vs dt = 30 s (%) point / volume | injected / pulse volume, point | outlet / injected volume point / volume | centroid travel time (h), volume | Km = dt | X on 0.25 floor |
|---|---|---|---|---|---|---|---|---|
| 30 | 0.18 | +0.00 / +0.00 | +0.0 / +0.0 | 1.000 | 0.9993 / 0.9993 | 0.46 | 0.00 | 0.00 |
| 60 | 0.36 | +0.00 / +0.01 | +0.0 / -0.0 | 1.000 | 0.9995 / 0.9995 | 0.47 | 0.00 | 0.00 |
| 120 | 0.72 | +0.00 / -0.01 | +0.0 / +0.0 | 1.000 | 0.9997 / 0.9997 | 0.46 | 0.00 | 0.00 |
| 300 | 1.80 | +0.32 / +0.39 | -0.7 / -1.1 | 0.999 | 0.9995 / 0.9995 | 0.80 | 1.00 | 0.00 |
| 600 | 3.60 | +1.07 / +1.23 | -3.8 / -5.3 | 0.999 | 0.9982 / 0.9983 | 1.59 | 1.00 | 0.00 |
| 900 | 5.39 | +1.82 / +2.06 | -8.2 / -11.1 | 0.998 | 0.9963 / 0.9965 | 2.39 | 1.00 | 0.00 |
| 1200 | 7.18 | +2.57 / +2.89 | -13.3 / -17.6 | 0.998 | 0.9941 / 0.9944 | 3.18 | 1.00 | 0.00 |
| 1800 | 10.72 | +4.07 / +4.56 | -23.3 / -30.1 | 0.997 | 0.9893 / 0.9903 | 4.77 | 1.00 | 0.00 |
| 3600 | 21.11 | +8.57 / +9.56 | -43.2 / -56.0 | 1.012 | 0.9720 / 0.9850 | 9.54 | 1.00 | 0.00 |
| 5400 | 31.30 | +13.07 / +14.56 | -48.1 / -69.6 | 1.223 | 0.9590 / 0.9881 | 14.31 | 1.00 | 0.00 |
| 7200 | 41.45 | +17.57 / +19.56 | -48.6 / -77.1 | 1.597 | 0.9575 / 0.9909 | 19.08 | 1.00 | 0.00 |
| 10800 | 61.74 | +26.57 / +29.56 | -48.6 / -84.7 | 2.394 | 0.9574 / 0.9939 | 28.62 | 1.00 | 0.00 |
| 14400 | 82.82 | +33.57 / +37.56 | -47.9 / -83.3 | 3.295 | 0.9596 / 0.9858 | 38.16 | 1.00 | 0.00 |

(max C is from the volume variant; the point variant differs by < 5%.) Reading:
- **C ≤ 0.72: no change**. From C = 1.8 on, Km is clamped to dt in every
  segment-step, and the outlet centroid arrives about **0.95·dt per segment** late
  (9.54 h at 3600 s, 38.2 h at 14400 s), against 0.46 h for the unclamped scheme
  (dx/Ck = 178 s per segment). The wave can cross at most one segment per step, so it
  travels at dx/dt instead of Ck: about 20× too slow at 3600 s and 80× at 14400 s.
- **The peak falls** by 56% at 3600 s and 70–85% beyond (volume forcing). At dt ≥ 3600 s
  the pulse spans only two or three output steps, so the peak value also depends on where
  the travel time falls on the step grid (flat-topped peaks in the figure); volume and
  centroid are the robust measures there.
- **Volume:** the outlet receives 98.5–99.9% of the injected pulse with volume forcing
  (largest loss 1.5% at 3600 s). With point forcing, the loss looks larger (up to 4.3%),
  and the injected volume itself is off by up to 3.3×. That is forcing aliasing, not the
  Courant effect.
- **No oscillation at any dt.** C3 ≥ 0 and the negative-flow guard never fired. C2 < 0
  in every segment-step for dt ≤ 120 s (C < 2X), never for dt ≥ 300 s.
- **The X floor never binds on this steep channel.** D ≈ 0.16 everywhere, so the
  unclamped X ≈ 0.46 and the final X is 0.456–0.461 at every dt.

Figures: `results/extended_hydrographs_core.png`, `extended_forcing.png`,
`extended_metrics_vs_courant.png`, `extended_clamp_floor_vs_dt.png`,
`extended_K_X_vs_dt.png`. Outlet series for every run: `results/extended_outlet.csv`.
Everything else: `results/extended_summary.json`.

### Results: what the closure produced (K, X, C, D)
Over all segment-steps of each run (min / median / max), and at the outlet segment at
the outlet peak. The interval-1 X (floor 0) is reported in `extended_summary.json`: on
the core channel it sits on its 0.5 cap in 97–100% of segment-steps, on the low-slope
channels on its 0 floor in ≥ 99%. X never reached the 0.5 cap on the final (interval-2)
estimate, and C3 was never negative, in any run.

**Core (s0 = 0.008, volume forcing).** dx/Ck = 178 s (median) at every dt.

| dt (s) | Km (s) min / median / max | final X min / median / max | C min / median / max | D median | outlet peak: Km, X, C, D | outlet peak: C1, C2, C3 | C2 < 0 |
|---|---|---|---|---|---|---|---|
| 30 | 167 / 178 / 178 | 0.456 / 0.461 / 0.461 | 0.169 / 0.169 / 0.18 | 0.157 | 167, 0.456, 0.18, 0.177 | 0.860, -0.577, 0.717 | 1.00 |
| 120 | 167 / 178 / 178 | 0.456 / 0.461 / 0.461 | 0.676 / 0.676 / 0.721 | 0.157 | 167, 0.456, 0.72, 0.177 | 0.902, -0.107, 0.205 | 1.00 |
| 300 | 300 / 300 / 300 | 0.456 / 0.461 / 0.461 | 1.69 / 1.69 / 1.8 | 0.157 | 300, 0.456, 1.8, 0.177 | 0.915, 0.042, 0.042 | 0.00 |
| 600 | 600 / 600 / 600 | 0.456 / 0.461 / 0.461 | 3.38 / 3.38 / 3.6 | 0.157 | 600, 0.456, 3.59, 0.176 | 0.916, 0.042, 0.042 | 0.00 |
| 3600 | 3600 / 3600 / 3600 | 0.458 / 0.461 / 0.461 | 20.3 / 20.3 / 21.1 | 0.157 | 3600, 0.458, 20.9, 0.167 | 0.920, 0.040, 0.040 | 0.00 |
| 14400 | 14400 / 14400 / 14400 | 0.459 / 0.461 / 0.461 | 81.1 / 81.1 / 82.8 | 0.157 | 14400, 0.460, 82.1, 0.161 | 0.923, 0.039, 0.039 | 0.00 |

**Low slope (volume forcing).** dx/Ck = 1611 s (s0 = 1e-4) and 2958 s (1e-5). The
unclamped X is −3.52 (D ≈ 16) and −73.4 (D ≈ 295), so **X sits on the 0.25 floor in 100%
of segment-steps at every dt**.

| dt (s) | s0 = 1e-4: Km median, C max, outlet-peak C1/C2/C3 | s0 = 1e-5: Km median, C max, outlet-peak C1/C2/C3 |
|---|---|---|
| 30 | 1611, 0.020, 0.342 / -0.316 / 0.974 | 2958, 0.011, 0.338 / -0.324 / 0.986 |
| 300 | 1611, 0.205, 0.412 / -0.176 / 0.765 | 2958, 0.110, 0.377 / -0.246 / 0.870 |
| 1200 | 1611, 0.820, 0.565 / 0.131 / 0.304 | 2958, 0.439, 0.479 / -0.043 / 0.564 |
| 1800 | 1800 (clamped), 1.22, 0.600 / 0.200 / 0.200 | 2958, 0.658, 0.530 / 0.060 / 0.410 |
| 3600 | 3600 (clamped), 2.38, 0.600 / 0.200 / 0.200 | 3600 (clamped), 1.29, 0.600 / 0.200 / 0.200 |
| 14400 | 14400 (clamped), 9.20, 0.600 / 0.200 / 0.200 | 14400 (clamped), 5.00, 0.600 / 0.200 / 0.200 |

Full 13-row tables: `extended_summary.json` → `runs/<variant>[i]/closure`.

**When both limits bind, the channel drops out.** With Km = dt and X = 0.25,
the denominator Km(1 − X) + dt/2 is 1.25·dt, so C1, C2, C3 = 0.6, 0.2, 0.2 whatever the slope, roughness or
geometry (C4 = ql·dt/D likewise). The s0 = 1e-4 and 1e-5 channels then give *identical*
outlet hydrographs at every dt ≥ 3600 s (`check.py` tests this), and the scheme is a
fixed linear cascade that conserves volume (outlet/injected 1.0000). The routed result
depends only on dt and the number of segments.

**The kernel's X formula has half Cunge's diffusion term (the same factor is in T-Route
and in WRF-Hydro; NCAR/wrf_hydro_nwm_public#921).**
`secant2_h` computes X = ½·(1 − Q/(2·B·S0·Ck·Δx)) (L318, L321, L327, L331), i.e.
X = ½ − D/4, while Cunge's matched value (Ponce) is X = ½·(1 − D) = ½ − D/2, and the
code's own comment (L313) gives the Cunge form. So the kernel's X is larger than Cunge's
(less numerical diffusion; core: 0.461 vs 0.42), and the 0.25 floor binds at D > 1, not
at D > ½. The same expression is in T-Route's kernel (`repro/short_ts_switch/mc_port.py`
mirrors CIROH-UA d29f663 L281–291) and in WRF-Hydro (#921); this run shows it was
already in the 2020 kernel.

### Results: the two smaller variants

| dt (s) | short-ts on: peak time / centroid travel vs off (h) | short-ts on: peak above baseflow vs off (%) | s0 = 1e-4: max C, peak shift (h), peak change (%), out/in volume | s0 = 1e-5: max C, peak shift (h), peak change (%), out/in volume |
|---|---|---|---|---|
| 30 | -0.15 / -0.16 | -0.8 | 0.0205, +0.00, +0.0, 0.9878 | 0.011, +0.00, +0.0, 0.9980 |
| 60 | -0.12 / -0.12 | -0.7 | 0.041, -0.01, +0.1, 0.9856 | 0.0219, +0.01, +0.0, 0.9906 |
| 120 | -0.03 / -0.05 | -0.3 | 0.082, -0.01, +0.2, 0.9850 | 0.0438, -0.01, +0.1, 0.9888 |
| 300 | +0.00 / +0.03 | +0.8 | 0.205, -0.01, +0.5, 0.9883 | 0.11, -0.01, +0.4, 0.9891 |
| 600 | +0.00 / +0.06 | +3.0 | 0.41, -0.01, +1.3, 0.9965 | 0.219, -0.01, +0.9, 0.9935 |
| 900 | +0.00 / +0.09 | +6.2 | 0.615, +0.16, +1.5, 1.0038 | 0.329, +0.07, +1.4, 0.9982 |
| 1200 | +0.00 / +0.12 | +9.9 | 0.82, +0.16, +2.5, 1.0077 | 0.439, +0.16, +1.6, 1.0011 |
| 1800 | +0.00 / +0.18 | +17.0 | 1.22, +0.66, -11.7, 1.0000 | 0.658, +0.32, +2.2, 1.0098 |
| 3600 | +0.00 / +0.36 | +27.4 | 2.38, +5.16, -52.4, 1.0000 | 1.29, +1.82, -18.1, 1.0000 |
| 5400 | +0.00 / +0.54 | +28.5 | 3.51, +9.66, -68.0, 1.0000 | 1.91, +6.32, -44.9, 1.0000 |
| 7200 | +0.00 / +0.72 | +28.3 | 4.63, +14.16, -76.0, 1.0000 | 2.51, +10.82, -58.6, 1.0000 |
| 10800 | +0.00 / +1.07 | +28.0 | 6.87, +23.16, -84.0, 1.0001 | 3.73, +19.82, -72.4, 1.0001 |
| 14400 | +0.00 / +1.43 | +26.1 | 9.2, +34.16, -87.4, 1.0001 | 5, +30.82, -78.3, 1.0001 |

- **Short-time-step assumption** (quc = qup, core channel). The centroid shift matches
  the per-segment prediction Δ = dt/2 − Km·X (derived in ../short_ts_switch) over the nine segments that
  have an upstream neighbor: at dt = 30 s, 9 × (15 − 178·0.46) s ≈ −0.16 h (measured
  −0.16 h); at 3600 s, 9 × 3600 × (0.5 − 0.46) s ≈ +0.36 h (measured +0.36 h). The sign
  flips between C ≈ 0.7 and 1.8, as predicted. The wave is still ~20× too slow at
  3600 s with the assumption on; it only changes the clamped scheme's dispersion (the
  peak is 26–28% higher at dt ≥ 3600 s, partly through step-grid alignment, see above).
  Volume closes to within 1% either way.
- **Low slope.** C stays below 1 up to dt = 1200 s (s0 = 1e-4) and 1800 s (1e-5); at
  3600 s it is 2.4 and 1.3, so Km is clamped there too. Below C = 1, results are again
  insensitive to dt (peak within 2.5%, timing within 0.35 h). Here the X floor binds
  everywhere, C2 < 0 whenever C < 0.5 (= 2X), and the volume balance moves by
  −1.5% to +1.0% with dt (variable-parameter MC; compare ../short_ts_switch, "Where the volume loss arises"). The pulse is
  already attenuated by 53% (1e-4) and 73% (1e-5) at dt = 30 s, so the extra attenuation
  from the clamp is a larger share of a smaller wave. Once clamped, both slopes become
  the same fixed cascade (above).

### Caveats
- Synthetic, steep (s0 = 0.008), uniform channel; a single reach of ten 2000 m segments
  with lateral inflow only on the first; not the NWM network. Network behavior at large
  dt is in `repro/short_ts_switch/`.
- With 10 segments, the delay is 10 × (dt − dx/Ck) at most. A network path with hundreds
  of segments accumulates proportionally more.
- The low-slope runs change only s0. They keep the steep channel's discharge
  (2000 m³/s), so depths are 13.8–18.7 m and the flow is in the floodplain; real
  slope-floor NWM segments have their own geometry and flows.
- The point-forcing variant reproduces the notebook's formula, including its
  `np.linspace` time axis (sample spacing duration/(n−1), slightly more than dt). It is
  the faithful extension but confounds dt with forcing aliasing at dt ≥ 1800 s.
- Peak values at dt ≥ 3600 s are samples of a hydrograph that spans two or three output
  steps.
- The expected values for dt > 600 s are a regression baseline from this extension's own
  run (`expected/extended.json`, macOS arm64, gfortran 15.2.0); no 2020 values exist.
  Docker was not rerun for the extension.

## Fidelity of the ports
- `run_experiment.py`: notebook cells 5 and 7, with identical parameters, forcing
  (`np.linspace(0, duration, int(duration/dt))` time axis, as in the notebook), loop
  order, and upstream/downstream bookkeeping (`qup` = upstream flow at t−1, `quc` =
  upstream flow at t, `qdp` = own flow at t−1, segment 0 gets zero upstream inflow).
  numpy arrays replace object-dtype DataFrames; the values are the same floats.
- f2py initializes scalar `intent(out)` arguments to 0 in its generated C wrapper. The
  primary kernel reads `qdc` (an `intent(out)` argument) in its "water to route?" test
  before assigning it, so this initialization matters; it is the same in 2020 and now.
- `run_dispersion.py`: `compute_network` / `compute_reach_kernel` ported line by line
  from `mc_reach.pyx`, keeping float32 throughout as the Cython does; network
  decomposition uses the original `nhd_network.py`; `replace_downstreams` is copied
  verbatim; the ql frame is filled through numpy because pandas 3 refuses the 2020-style
  float64 assignment into a float32 frame (same float32 values result).

## Known caveats
- Python 3.12 / numpy 2.5 / meson replace the notebooks' Python 3.6 / numpy.distutils
  toolchain. Kernel precision is set by `varPrecision.f90` (`prec = kind(1.0)`, i.e.
  float32), so results match to float32 rounding, not bit-for-bit across platforms.
- The primary kernel's f2py build uses meson `buildtype=release`. The exact compile
  lines are in `build/build_info.json` and `results/provenance.json`.
- Docker was tested on linux/arm64 only. The 2020 runs were on x86_64 (WSL and Colab);
  `docker build --platform linux/amd64` should work under emulation but is untested.
