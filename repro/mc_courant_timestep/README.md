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
`run_dispersion.py` (three kernel builds) → `check.py`.

Platform-independent alternative (Debian 12 + gfortran 12.2.0 from a dated
snapshot.debian.org archive, base images pinned by digest):
```bash
cd repro/mc_courant_timestep
docker build -t troute-repro-mc-courant .
docker run --rm -v "$PWD/results:/work/results" troute-repro-mc-courant
```

Outputs in `results/`: `courant_test.json`, `courant_test_outlet.csv` (outlet
hydrograph, depth, and C for every dt), `courant_test_hydrographs.png`,
`dispersion_<build>.json/.png`, and `provenance.json` (platform, Python, uv, package
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
