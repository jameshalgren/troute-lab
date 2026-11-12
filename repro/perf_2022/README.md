# perf_2022: repeat the 2022 one-year CONUS t-route timing (plan and setup scripts)[^ai]

## Taking this on (handoff brief)

This is a self-contained subtask: someone other than the author can run it end to end.

- **Goal:** measure how long the 2022-era t-route and the current t-route take for one
  CONUS year on the same machine and inputs, where the time and memory go, and how that
  relates to the 22 h (t-route) and 4.5 h (WRF-Hydro) figures of 2022. The result feeds the
  paper's performance section.
- **Already decided:** the code versions and kernel arms (Builds), the inputs and the
  lateral-inflow variable (Inputs), the most likely 2022 configuration (Configuration), the
  stages and their order (Stages), what to measure (What to measure). Change them only with
  the author.
- **You need:** a Mac or Linux machine with gfortran, netCDF-Fortran and `uv`; about 200 GB
  of disk for the year; comfort with Python, a shell, and reading t-route YAML configs. No
  hydrology needed to run it; knowing what the record says about the 2022 run
  (Question, Configuration) helps to judge results.
- **Start here:** stage 0 (builds), then stage i-a (one CONUS week), on any machine. Long
  runs (ii-a, ii-b) go on the author's lab Mac or an equivalent.
- **Done when:** `summarize.py` produces the table in "What to measure" for ii-a (all four
  builds, plus the two earlier `nogil` builds) and ii-b (`era-original`, `current-corrected`),
  with three repeats of the week
  runs, and the results with their caveats (Comparability) are written into
  `results/README.md` here.
- **Ask:** James Halgren for decisions and approvals. For what the 2022 run actually
  was, start from the record: the
  [NOAA-OWP/t-route#526](https://github.com/NOAA-OWP/t-route/issues/526#issuecomment-1049031284)
  comment quoted under Question, its authors, and the PRs before it (Configuration).
- **Status (2026-11-04):** the plan and scripts exist, nothing has run. The author is
  installing the toolchain and configuring the lab Mac (Apple M4 Max, 16 cores, 64 GB,
  macOS 26.7.1, 434 GB free; checked over SSH 2026-11-04).

## Question

In February 2022 Adam Wlostowski wrote in
[NOAA-OWP/t-route#526](https://github.com/NOAA-OWP/t-route/issues/526#issuecomment-1049031284):

> A 1-year CONUS channel-only WRF run takes  4.5 hours. A 1-year CONUS channel-only t-route simulation takes 22 hours.

The configuration behind both numbers was never written down: #526 gives no hardware,
core count, parallel method, loop length, data-assimilation or output settings, nor how
the run was forced. This experiment

1. rebuilds the t-route code of that week and the current code,
2. runs both on the same inputs and machine, with the configuration that the record makes
   most likely (see Configuration), and
3. reports where the time goes (input read, routing, output, per-loop overhead), how much
   memory it takes, and how both compare with the 22 h / 4.5 h figures.

## Builds (2 code versions × 2 kernels)

| Label | Code | Python / key packages | Why |
|---|---|---|---|
| `era-original` | NOAA-OWP/t-route [`a6efbf4e`](https://github.com/NOAA-OWP/t-route/commit/a6efbf4e58f86c7bab73735ad021c628f69329b8) (2022-02-16, the master commit #526 links) | 3.9.25; numpy 1.22.2, pandas 1.4.1, Cython 0.29.27, joblib 1.1.0, xarray 0.21.1, netCDF4 1.5.8 (Linux, Intel Mac) / 1.6.2 (Apple silicon) | the faithful 2022 build |
| `era-corrected` | a6efbf4e + `../kernel_fixes` patches 0001–0008 | same | isolates the kernel fixes on the old framework |
| `current-original` | CIROH-UA/t-route [`d29f663`](https://github.com/CIROH-UA/t-route/commit/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6) (`ngiab` HEAD, unchanged on 2026-11-04) | 3.12.13; numpy 1.26.4, pandas 2.2.0, Cython 3.0.12 (pins of `../short_ts_switch`) | isolates the framework change (same kernel arithmetic as a6efbf4e except the #556 guards for zero floodplain width) |
| `current-corrected` | d29f663 + patches 0001–0008 | same | the repro/ default since 2026-10-09 |

Why a6efbf4e and not tag v2.2.0 (49d05633, 2022-02-12): the four commits between them are
#519 (repackaging: removed the unused kernels `V02-caching`/`V02-structured-obj` and the old
test YAMLs), #523, #524 (docstrings) and #525. Only #525 changes behaviour: it makes
qSfcLatRunoff + qBucket the preferred lateral inflow over `q_lateral` and fixes a lake-index
mapping in output. Computationally a6efbf4e = v2.2.0 for these runs, and a6efbf4e has the
directory layout `build_troute.sh` expects.

The kernel patches touch only `src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90`, and
all eight apply cleanly to a6efbf4e as well (checked 2026-11-04).

Optional later arm: NGWPC/t-route `development` (HEAD `9a3c303e`, 2026-09-29), which keeps
the NWM RouteLink path (`NHDNetwork.py`) and NGWPC's 2026 optimizations
([benchmark/RESULTS.md](https://github.com/NGWPC/t-route/blob/development/benchmark/RESULTS.md)). It reads
netCDF lateral inflow with `xr.open_mfdataset` (its requirements.txt comment), not tested here.

### Earlier `nogil` builds: was the 2022 code a regression? (author, 2026-11-04)

The author asks that the test check whether the earlier, GIL-releasing code ran better. Two
of Adam Wlostowski's PRs changed the parallel model in the three months before #526: #501
switched joblib from threads to processes, and #509 removed the `with nogil:` blocks. The
author's three possibilities:

1. **Regression.** Adam was focused on drop-in compatibility with the NWM inputs, and some
   of that work (possibly date arithmetic) was hard to do inside `nogil` blocks, so
   removing them cost speed.
2. **No change.** The blocks were dropped with no change in performance, and the code was
   simply slow.
3. **Hardware.** A current Mac may run much faster than a 2016 Cheyenne node, especially
   with parallel threads.

| Label | Commit (NOAA-OWP/t-route) | Parallel model | What it isolates |
|---|---|---|---|
| `nogil-threads` | [`7807bd4f`](https://github.com/NOAA-OWP/t-route/commit/7807bd4f7f9e232f4bf32cd2fd92ea87b39a50d7) (2021-11-15, #500; the commit before #501) | joblib `threading` (4 calls) + 3 `with nogil:` loops | threads sharing memory, no pickling |
| `nogil-procs` | [`371a2c12`](https://github.com/NOAA-OWP/t-route/commit/371a2c12ccd952f99efa76200d267dcc6d22b9da) (2022-01-03, #508; the commit before #509) | joblib `loky` (3 calls) + 3 `with nogil:` loops | #509 alone, when compared with `era` |
| `era` (above) | `a6efbf4e` (2022-02-16) | `loky`, no `nogil` | the #526 code |

Checked 2026-11-04 from the raw files at each commit (`grep -c "with nogil"` on
`mc_reach.pyx`, `grep 'backend='` on `compute.py`). #501's merge is `4fd9055e`
(2021-11-23) and #509's is `db58b14b` (2022-01-29), both by `awlostowski-noaa`. Tag
v2.1.0 (`51dc6871`, 2021-12-09) is also loky + `nogil` and could stand in for
`nogil-procs`.

What the record already says (AI reading): with DA off, #509's removal of `nogil` should
matter little under processes, because each worker has its own GIL. Any difference
between `nogil-procs` and `era` is therefore Python overhead added inside the time loop.
#509's stated reason was that the loop now calls the Python function
`reservoir_hybrid_da` ([#509](https://github.com/NOAA-OWP/t-route/pull/509) removes all
three `with nogil:` blocks of `mc_reach.pyx`). Whether date arithmetic was also involved is
not checked yet; read #509's diff and the review comments. #501's own CONUS 28-h test
had routing go from 313.76 s with threads to 184.17 s with loky
([comment](https://github.com/NOAA-OWP/t-route/pull/501#issuecomment-976502214)). On
that machine, then, processes beat `nogil` threads by 1.7×. On a Mac, with unified memory
and no pickling, threads may compare differently. That is possibility 3, and this test
measures it.

Not done yet (for whoever takes this on):
- `build_troute.sh` handles only the `src/troute-*` layout of a6efbf4e. Both commits above
  use `src/python_routing_v02/` and need a build branch; find each commit's own
  compile script.
- The YAML configs need a check against each commit's schema.
- Before #525 (2022-02-16) the code prefers the packed `q_lateral` (29% of the volume lost
  to rounding; see Inputs), so it routes slightly different flows. That is acceptable for
  timing, but say so in the results.
- #501 also rewrote file I/O (Cape Fear output 2,070.96 s → 2.35 s), so compare the
  **routing phase** (`measure.py` split), not wall time, for `nogil-threads`.
- Suggested runs: ii-a (CONUS January) for all three, at the same `cpu_pool` and loop
  length; also sweep `cpu_pool` (1, 4, 8, 12) for `nogil-threads` vs `nogil-procs` to see
  how threads scale on the Mac.

## Inputs (all public)

| Input | Source | Size | Notes |
|---|---|---|---|
| NWM v2.1 RouteLink_CONUS.nc (2,776,738 links) | [HydroShare 0a596929…](https://www.hydroshare.org/resource/0a596929a3e5411bb0032a8de35e5089/) (copy of `nwm.v2.2.0/parm/domain/`) | 269 MB, SHA-256 `1b95f69a…` | same file and hash as `../network_stats` |
| Hourly lateral inflow, NWM v2.1 retrospective CHRTOUT | `s3://noaa-nwm-retrospective-2-1-pds/model_output/YYYY/YYYYMMDDHHMM.CHRTOUT_DOMAIN1.comp` (anonymous HTTPS: `https://noaa-nwm-retrospective-2-1-pds.s3.amazonaws.com/...`); Feb 1979 – Dec 2020, no DA ([AWS registry](https://registry.opendata.aws/nwm-archive/)) | full files: mean 47.65 MB/h; **1.14 GB/day, ~35 GB/month, 417.4 GB for calendar 2018** (8,760 files, S3 listing 2026-11-04) | see "Slim forcing" |
| Initial state (optional) | `streamflow` of the CHRTOUT valid at t0 | one range read | the v2.1 bucket has no HYDRO_RST files; default is a cold start |

**Which lateral-inflow variable.** The v2.1 retrospective CHRTOUT has `q_lateral` packed
with scale_factor 0.1 m³/s, and `qSfcLatRunoff` and `qBucket` packed at 1e-5 m³/s. At
2018-01-01 12:00 the CONUS sum of `q_lateral` is 25,223 m³/s against 35,423 m³/s for
qSfcLatRunoff + qBucket: 29% of the volume is lost to rounding (AI check of one file,
2026-11-04). a6efbf4e (#525, 2022-02-16) uses qSfcLatRunoff + qBucket when both are present,
and so does WRF-Hydro's channel-only mode (`read_channel_only` in
`trunk/NDHMS/Routing/module_HYDRO_io.F`, v5.2.0: `QLateral = qBucket_in + qSfcLatRunoff_in`).
Both t-route builds here therefore get the same forcing WRF-Hydro channel-only would get.

**Slim forcing.** t-route reads only `feature_id`, `qSfcLatRunoff`, `qBucket` and the
global attribute `model_output_valid_time`. `fetch_inputs.py` range-reads just those
(about 7–10 MiB per hour instead of 47 MB) and writes `YYYYMMDDHHMM.CHRTOUT_DOMAIN1` files
(no `.comp`, the name both builds construct) with the packed integers and attributes
unchanged: **4.84 MB per hour on disk, ~42 GB for a year** (measured on two files).
a6efbf4e's own `nhd_io.get_ql_from_chrtout` returns bit-identical lateral inflow from a slim
file and from the original (checked 2026-11-04, see "What was tested"). Measured fetch rate
on the author's connection: 24 hourly files in 11.5 s with 16 worker processes, so one year
in roughly 1–1.5 h.

## Configuration (what the 2022 run most likely used)

Fixed in `make_configs.py`: Muskingum-Cunge only (`compute_kernel: V02-structured`, the
only MC kernel left at a6efbf4e), dt = 300 s, `qts_subdivisions: 12`, `assume_short_ts:
True` (as in the team's test_AnA.yaml of that week), no data assimilation, no output
(timing of routing + input), synthetic Great Lakes segments renamed as v3_doc.yaml requires
for CONUS, entry point `-V3` (era; synchronous looping `main_v03`) or `-V4` (current).

Varied: `parallel_compute_method` (by-subnetwork-jit-clustered is the leading candidate for
2022 by AI arithmetic, not by record: at #526's 2.9 µs per segment-step, read as serial, a
CONUS year is about 233 h serial; `by-network` cannot beat the Mississippi's 40% of the
segments (`../network_stats`), at least ~94 h; so 22 h needs the ~10× speed-up that
only the subnetwork (JIT) methods could give on 36 cores), `cpu_pool` (36 = one Cheyenne node), `max_loop_size` (12 h default
at a6efbf4e; 24 h current default), `subnetwork_target_size` (10,000), output (none /
CHRTOUT append / lite restart), start 2018-01-01 00 UTC.

**Deviation: no reservoirs.** WRF-Hydro "channel-only" still routes lakes, and the 2022
t-route run may have too. With `break_network_at_waterbodies: False` lake segments are
routed as channels. The first January queue keeps that baseline; a waterbody arm comes
next.

**Where the v2.1 LAKEPARM is**:
NOHRSC's
[`NWM_parameter_files_v2.1.tar.gz`](https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/NWM_parameter_files_v2.1.tar.gz)
(4,485,467,589 bytes, Last-Modified 2023-09-20, SHA-256 `911fe35d…`; linked from
[water.noaa.gov/about/nwm](https://water.noaa.gov/about/nwm); a v3.0 tarball sits beside
it). It holds `NWM_parameters_v2.1/` with RouteLink, LAKEPARM, nudgingParams, Fulldom and
spatial weights for CONUS, HI and PRVI, plus `md5sum.txt` (files dated 2021-03-08). Checked
on the lab Mac 2026-11-10:
- its `RouteLink_CONUS.nc` is byte-identical to the HydroShare copy (SHA-256 `1b95f69a…`);
- `LAKEPARM_CONUS.nc` (SHA-256 `fc74940d…`, MD5 as in `md5sum.txt`) has 5,783 `lake_id`s,
  exactly the RouteLink's 5,783 nonzero `NHDWaterbodyComID`s;
- the four Great Lakes link IDs (4800002/4/6/7) are also lake IDs, which is why
  `synthetic_wb_segments` exists (rename the links when waterbodies are on).

Not in the tarball: geo_em, wrfinput, GWBUCKPARM, the hydro tables, needed for the
WRF-Hydro reference below.

## Stages, cost estimates

All runtime and memory figures below are **estimates (AI arithmetic)** from these anchors:
#501's CONUS 28-h run (routing 184.17 s; everything except the one-time network build 203.9
s, i.e. 7.28 s per simulated hour; hardware not stated), which extrapolates to **17.7 h per
simulated year**; #526's 11,141-segment run (32 s for 1,000 steps, read here as serial:
2.9 µs per segment-step); the M5 measurements in "What was tested". Treat them as order of
magnitude.

| Stage | Where | Data (transfer / disk) | Peak memory | Wall per run | Runs |
|---|---|---|---|---|---|
| 0. Builds | both Macs | ~0.4 GB per build dir (measured for source + env) | – | minutes | 2–4 |
| i-a. CONUS, 1 week | author's laptop (M5: 4 performance + 6 efficiency cores, 32 GiB) | ~1.2 GB / 0.8 GB | 10–20 GB with 12-h loops | 20 min – 2 h | 5 variants × 2–4 builds |
| i-b. Potomac (16,454 segments), 1 year, serial | Mac | the yearly pass: ~60–90 GB transferred; subset 0.5 GB (+42 GB if the CONUS slim files are kept for stage ii) | < 2 GB | 0.5–1.5 h | 4 (2 × 2) |
| i-c. Ohio (230,729 segments), 1 year (optional) | Mac | subset ~5.3 GB, same pass | 3–6 GB | serial 7–20 h; 4 workers 2–6 h | 2–4 |
| ii-a. CONUS, January 2018 | lab Mac | 3.6 GB (or the year) | 20–40 GB (24-h loops) | ~1.5 h if #501's throughput holds | ~10–14 |
| ii-b. CONUS, calendar 2018 | lab Mac | 42 GB slim (+97 GB for CHRTOUT output) | 20–40 GB | era: 17.7–22 h on 2021-class hardware; current: unknown (measure ii-a first) | 2 (+2 kernel arms) |
| ii-c. WRF-Hydro channel-only reference (optional) | lab Mac or a Linux machine | 417 GB full CHRTOUT or the slim files; NWM v2.1 domain files (not found publicly) | ? | 4.5 h reported | 1 |

Memory reasoning: per loop, era code holds the result array of every segment
(2.78 M × (steps + 1) × 3 × float32 = 4.8 GB for 12-h loops, 9.6 GB for 24-h loops), the
lateral inflow block, the network dictionaries (1.8–2.3 GB RSS measured on the M5 for the
graph alone), and loky workers' pickled copies. In February 2021 a 5-day (1,440-step) CONUS
run hit a bus error on Cheyenne while 864 steps fit
([#223](https://github.com/NOAA-OWP/t-route/pull/223#issuecomment-780832517)), so loop length
mattered then and will here. Watch `peak_pss_gib`.

### Stage i (author's laptop)

**Needs approval: Homebrew install of the Fortran/netCDF toolchain** (none of it is on the
machine as of 2026-11-04; the earlier repro/ builds evidently had it):

```bash
brew install gcc netcdf netcdf-fortran     # gcc 16.2.0 provides gfortran; netcdf 4.10.1; netcdf-fortran 4.6.4 (arm64 bottles, 2026-11-04)
```

Then (data go to `data/`, gitignored; set `PERF2022_DATA=/some/big/disk` to move them):

```bash
cd repro/perf_2022
uv sync --locked
./build_troute.sh era original && ./build_troute.sh current corrected      # + era corrected, current original
uv run --locked python fetch_inputs.py routelink
uv run --locked python make_mask.py potomac && uv run --locked python make_mask.py ohio
# one week of CONUS forcing (stage i-a)
uv run --locked python fetch_inputs.py forcing 2018-01-01_00 2018-01-08_00
# the whole year once: CONUS slim files (for stage ii) plus the two subdomains (needs author approval: ~60-90 GB transfer)
uv run --locked python fetch_inputs.py forcing 2018-01-01_00 2019-01-01_00 --mask data/masks/potomac.csv --mask data/masks/ohio.csv --workers 16
./make_matrix.sh smoke          # writes configs, prints the run_case.sh commands
./run_case.sh era-original results/conus_week/jitc_cpu4_loop12/era      # etc.
uv run --locked python summarize.py
```

### Stage ii (lab Mac)

The long runs are on a lab computer via remote access. Spec: Apple M4 Max (arm64), 16 cores, 64 GB,
macOS 26.7.1, 434 GB free; Homebrew present; no gfortran, netCDF-Fortran or uv. The 16-core
M4 Max is 12 performance + 4 efficiency cores by Apple's specification (not yet read from
`hw.perflevel0.physicalcpu`). `remote_check.sh` reports these (`sysctl hw.ncpu hw.physicalcpu hw.perflevel0.physicalcpu
hw.memsize machdep.cpu.brand_string`, `sw_vers`, `uname -m`, Rosetta, Homebrew, sleep
settings, disk). **Needs configuration**: the key, the toolchain install, and the data download.

What the CPU type changes:

| | Apple silicon (arm64) | Intel (x86_64) |
|---|---|---|
| era Python packages | `envs/era-macos-arm64.txt`: 2022 set except netCDF4 1.6.2, cftime 1.6.2, pyproj 3.6.0, fiona 1.9.4.post1, shapely 2.0.1 (no 2022 arm64 wheels) | `envs/era-macos-x86_64.txt`: the **exact** 2022 set, identical to Linux (netCDF4 1.5.8, fiona 1.8.21, pyproj 3.3.0, shapely 1.8.1) |
| current Python packages | `envs/current-macos-arm64.txt`, needs macOS 14 or later (netCDF4 1.7.4 wheels) | `envs/current-macos-x86_64.txt`, needs macOS 13 or later |
| gfortran + netCDF | `brew install gcc netcdf netcdf-fortran`: arm64 bottles for macOS 14 (sonoma) and later ([formulae.brew.sh API](https://formulae.brew.sh/api/formula/gcc.json), 2026-11-04) | Homebrew has **no Intel-macOS bottles** of gcc 16.2.0 or netcdf 4.10.1 (only netcdf-fortran has a `sonoma` Intel bottle), so brew would compile gcc from source. conda-forge has osx-64 gfortran 16.2.0, libnetcdf 4.10.1, netcdf-fortran 4.6.4 (anaconda.org API, 2026-11-04): e.g. `micromamba create -p ~/perf2022-tc -c conda-forge gfortran netcdf-fortran`, then `export F90=~/perf2022-tc/bin/gfortran` and put that `bin` on PATH (untested) |
| C compiler | Apple clang (needs `-Wno-error=implicit-int`, set by the script) | same |
| Rosetta | `build_troute.sh` refuses to run in a Rosetta (x86_64-translated) shell | – |
| `cpu_pool` | the performance-core count (`hw.perflevel0.physicalcpu`); efficiency cores are much slower and make the JIT barrier wait | physical cores (`hw.physicalcpu`), not hyperthreads |

On the lab Mac:

```bash
git clone <this repository> && cd <clone>/repro/perf_2022     # or copy repro/perf_2022 + repro/kernel_fixes
./remote_check.sh --data-dir /path/with/200GB                    # report only; installs nothing
# toolchain per the table above (author approval), then:
./remote_check.sh --data-dir /path/with/200GB --build-all        # builds the 2 x 2 if every tool is present
export PERF2022_DATA=/path/with/200GB/data
uv run --locked python fetch_inputs.py routelink
uv run --locked python fetch_inputs.py forcing 2018-01-01_00 2019-01-01_00 --workers 16   # or copy the laptop's conus_slim/
./make_matrix.sh month NPERF    # NPERF = performance (or physical) cores; + a 36-worker arm if the Mac has >= 36 cores
./make_matrix.sh year NPERF
```

Order: run ii-a (month) for all four builds and the method sweep first; extrapolate with
`summarize.py`; then run ii-b (year) for `era-original` and `current-corrected`. Keep the
Mac otherwise idle, on power and awake (`run_case.sh` wraps each run in `caffeinate -i`);
consider excluding the data directory from Spotlight indexing. Physical memory matters
more than on Cheyenne: with less than 64 GB use 12-h (or 6-h) loops. A Linux container
(Docker/Colima, linux/arm64) would bring the setup closer to Linux but adds virtualised I/O
and was not prepared here.

**Comparability.** Results on a Mac are not directly comparable with the 2022 Linux/HPC
figures: different CPU microarchitecture (Apple M-series or a recent Intel vs 2016 Broadwell
Xeons), OS and memory system (unified memory, macOS scheduler with performance/efficiency
cores), compiler (gfortran 16 vs whatever Cheyenne had), file system (local APFS SSD vs
GLADE/GPFS), and process start method (Python on macOS starts worker processes by spawning,
Linux by forking; loky manages its own workers on both, but start-up and memory sharing
differ). No PSS on macOS: memory is reported as summed RSS (over-counts pages shared by the
workers) and the largest single process. Within-Mac comparisons (era vs current, kernel
original vs corrected, method and loop sweeps) are sound; the link to 22 h / 4.5 h is only
through the era-original anchor below.

### WRF-Hydro reference (optional, ii-c)

The 4.5 h figure was probably NCAR's (the same comment says "I'll need to check with NCAR").
Reproducing it needs: WRF-Hydro v5.2.0 (the retrospective files say "OUTPUT FROM WRF-Hydro
v5.2.0-beta2") built with MPI, CMake and netCDF-Fortran; the **NWM v2.1 CONUS domain and
parameter files** (Fulldom_hires, geo_em, wrfinput, RouteLink, LAKEPARM, GWBUCKPARM,
spatial weights, tables; RouteLink, LAKEPARM, Fulldom and spatial weights are in the NOHRSC
v2.1 tarball above, the others were not found); `namelist.hrldas` with `FORC_TYP = 9`
("Channel-only forcing", v5.2.0 template) and a `hydro.namelist` for reach-based MC
(`channel_option = 2`, `UDMP_OPT = 1`, `DTRT_CH = 300`). WRF-Hydro reads
`YYYYMMDDHHMM.CHRTOUT_DOMAIN1` from the forcing directory and checks the global attributes
`dev_OVRTSWCRT`, `dev_NOAH_TIMESTEP`, `dev_channel_only`, `dev_channelBucket_only`, which the
retrospective (and slim) files carry. The namelist settings are an AI reading of the v5.2.0
templates and source, untested. A public alternative is a *modern* reference: the
`nwm.v3.1.7/parm/domain/` files at NCEP plus the NWM v3.0 retrospective CHRTOUT
(`s3://noaa-nwm-retrospective-3-0-pds/CONUS/netcdf/CHRTOUT/YYYY/YYYYMMDDHHMM.CHRTOUT_DOMAIN1`,
46.3 MB/h; variables not checked). That is not the 2022 comparison.

## What to measure and how to compare

Per run (`measure.py`, `summarize.py`): wall time; t-route's own split (network graph,
initial conditions [era], forcing read, routing, output); per-loop overhead = wall − phases,
divided by the number of loops; CPU seconds and CPU utilisation (CPU/wall, the NGWPC
"1.40x of 8 cores" metric in
[benchmark/RESULTS.md](https://github.com/NGWPC/t-route/blob/development/benchmark/RESULTS.md)); peak summed RSS, PSS on Linux only; segment-steps per second in the
routing phase; extrapolated hours per simulated CONUS year.

Comparison with 2022:
- **Hardware.** Cheyenne (retired 2023-12-31) cannot be rerun. Use `era-original` on the
  lab Mac as the anchor: hardware factor h = 22 h / (era-original year hours), and
  report current builds both as measured and scaled by h. If era-original lands far from
  17.7–22 h × (expected per-core speed ratio), the configuration guess is wrong; run the
  method/loop sweep to find which setting reproduces it.
- **Framework vs kernel.** era-original → current-original is the framework change;
  original → corrected is the kernel fix (secant iteration counts).
- **WRF-Hydro.** Only a WRF-Hydro run on the same machine gives a clean ratio. Without it,
  4.5 h × (1/h) is a weak proxy (assumes WRF-Hydro gained as much from the hardware).
- **Correctness.** The `_lite` week runs write one lite restart per loop; the end states of
  era-original and current-original should agree to round-off (same kernel arithmetic;
  [#504](https://github.com/NOAA-OWP/t-route/issues/504) documents small differences across
  parallel settings).
- Repeat the week runs 3 times (median and spread); one year run per arm is enough.

## Era-build risks and fixes (found 2026-11-04)

- **Python and wheels.** a6efbf4e pins nothing (`requirements.txt`: numpy, Cython,
  pandas>=1.1.5, geopandas, xarray, netcdf4, pyyaml, toolz, joblib). `envs/era-*.txt` are
  resolved with `uv pip compile --exclude-newer 2022-02-17` (the packages as of #526). On
  Linux x86_64 and Intel macOS every package has a 2022 wheel. On macOS arm64, netCDF4 1.5.8, pyproj 3.3.0
  and fiona 1.8.21 have no arm64 wheels, so those (and cftime, shapely) are allowed newer
  versions (netCDF4 1.6.2, pyproj 3.6.0, fiona 1.9.4.post1, shapely 2.0.1); geopandas is only
  imported by a6efbf4e's `nhd_io`, not used for NetCDF RouteLinks.
- **Cython 0.29.27** translates all four extension modules a6efbf4e builds (checked; the two
  .pyx files it does not build, `diffusive_hybrid.pyx` and `reservoir.pyx`, do not
  translate, as at the time).
- **Implicit int.** `levelpool_structs.c` and `rfc_structs.c` at a6efbf4e declare
  `init_*_reach(...)` with no return type; Apple clang 21 refuses (error since clang 16;
  GCC 14 likewise). `build_troute.sh` sets `CFLAGS=-Wno-error=implicit-int` for era builds
  (checked: both then compile).
- **setuptools 60** predates PEP 660, so era packages are installed with `setup.py develop`.
- **NETCDFINC** is hard-coded to an openmpi path in a6efbf4e's `compiler.sh`; the build takes
  it from `nf-config`.
- numpy ≥ 1.24 removed aliases that era code might use: none found (`np.float`, `np.int`
  grep, 2026-11-04), but stay on the pinned numpy 1.22.2 anyway.
- `-V4` (async) at a6efbf4e calls `nwm_route` with an outdated argument list and #494 said
  the async path "appears broken"; use `-V3`.

## Environments

- `pyproject.toml` / `uv.lock` / `.python-version`: the helper scripts (Python 3.12.13).
- `envs/era.in`, `envs/current.in`: direct requirements of the two builds.
  `envs/{era,current}-{linux-x86_64,macos-arm64,macos-x86_64}.txt`: fully resolved,
  hash-pinned (`uv pip sync` checks the hashes; `build_troute.sh` picks the file for the
  machine). Regenerate with
  `uv pip compile envs/era.in --python-version 3.9 --python-platform x86_64-manylinux_2_28 --exclude-newer 2022-02-17T00:00:00Z --only-binary :all: --generate-hashes`
  (platforms `aarch64-apple-darwin`, `x86_64-apple-darwin`; macOS arm64 adds
  `--exclude-newer-package` for netcdf4, cftime ≤ 2022-12-31 and pyproj, fiona, shapely
  ≤ 2023-06-30; the current-code files need `MACOSX_DEPLOYMENT_TARGET=14.0` (arm64) or
  `13.0` (x86_64), which are also the oldest macOS versions they install on).

## Files

| File | Does |
|---|---|
| `fetch_inputs.py` | RouteLink v2.1 (SHA-256 checked); slim / full / subdomain CHRTOUT forcing for a date range (S3 listing and ETags recorded, full files MD5-checked against the ETag); warm-start CSV |
| `make_mask.py` | segments upstream of an outlet → mask CSV (presets potomac, ohio) |
| `make_configs.py` | one era (V3) or current (V4) YAML + `case.json` |
| `make_matrix.sh` | all configs of a stage; prints the run commands |
| `to_lite_restart.py` | warm-start CSV → lite restart pickle (run with the build's own Python) |
| `build_troute.sh` | one build into `build/<code>-<kernel>/` (`ONLY_ENV=1`: source, patches, env only) |
| `run_case.sh` | one measured run |
| `measure.py` | wall, CPU, process-tree memory sampling |
| `summarize.py` | `results/summary.{csv,md}` with the derived columns |
| `remote_check.sh` | environment report for the lab Mac (macOS; a Linux branch is kept); optional builds |
| `reference_2022.json` | the 2022 reference numbers with sources |

Generated, gitignored: `data/`, `build/`, `results/`, `.venv/`.

## What was tested (2026-11-04, macOS 26.7.1, Apple M5)

- `fetch_inputs.py forcing` (slim, full, two masks), `warmstart`, `routelink` not run (the
  file is the one `../network_stats` already verifies). Slim and subset files checked with
  a6efbf4e's own `nhd_io.get_ql_from_chrtout` and `get_attribute` (era Python environment):
  identical values to the original files; all 16,454 Potomac ids present.
- `make_mask.py` on the local NWM v3.1.7 RouteLink: Potomac 16,454 and Ohio 230,729
  segments, matching `../short_ts_switch` and `../network_stats`.
- `make_configs.py`: era YAML read by a6efbf4e's `read_config_file`, `build_forcing_sets`,
  `build_connections` (mask applied) and `build_qlateral_array` (no missing segments);
  current YAML accepted by d29f663's `troute.config.Config.with_strict_mode`.
- a6efbf4e pure-Python setup at CONUS scale (v3.1.7 RouteLink) on the M5: build_connections
  1.4 s, organize_independent_networks 3.0 s, by-subnetwork-jit-clustered preamble
  (build_subnetworks + reach decomposition, target 10,000: 17,428 subnetworks in 15
  orders) 3.3 s, which a6efbf4e repeats on every loop (#557 removed that in April 2022);
  peak RSS 2.3 GB.
- `build_troute.sh` with `ONLY_ENV=1` for era and current (source fetch by SHA, 8 patches,
  hashed envs); the compile steps, `run_case.sh` with t-route, and every runtime estimate
  above are **untested**.
- `measure.py`, `summarize.py` (on a synthetic log carrying #501's numbers: 17.7 h per
  year), `remote_check.sh` (on the Apple-silicon laptop only; the Intel-Mac branch is untested).

[^ai]: HEAVILY AI-assisted with author review.
