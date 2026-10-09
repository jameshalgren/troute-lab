# repro/: reproducible experiments

Each subdirectory is one **self-contained, deeply reproducible experiment** behind a
claim or figure in the paper. Author's requirement (James Halgren, 2026-10-05):

> We would want such scripts to be deep -- specifying library versions, including data
> download automation, and otherwise ensuring reproducibility.

*This folder and its scripts were AI-assembled (Claude, 2026-10-05) and have not yet
been reviewed by the author.*

| Experiment | Question | Inputs | Runtime | Status (2026-10-05) |
|---|---|---|---|---|
| [`routelink_topwidth/`](routelink_topwidth/) | How is `TopWdthCC` (compound-channel top width) derived from `TopWdth` in the NWM v3 RouteLink files? | NWM v3.1.6 RouteLink_{CONUS,AK,HI,PRVI}.nc from NCEP (~320 MB) | < 1 min after download | `check.py` passes (23/23), macOS arm64 |
| [`network_stats/`](network_stats/) | How many independent drainage networks does the NWM RouteLink have, and how large are they? Does the largest (Mississippi, 40.2% of CONUS) cap by-network parallelism at 3 processors? Transboundary cuts; Rio Grande continuity; comparison with NWM v2.1 and the 2020 counts; sizes of ~160 named sub-rivers (Ohio, Missouri, ...) found by their mouth segments | NWM v3.1.6 RouteLink_{CONUS,AK,HI,PRVI}.nc (NCEP, ~320 MB), optional NWM v2.1 CONUS RouteLink (HydroShare, 269 MB), Natural Earth borders (pinned commit), committed USGS NHDPlus/NLDI snapshots `river_names.json` and `subriver_gnis.json` (SHA-256 checked) | ~1 min after download | `check.py` passes (398/398, of which 157 are sub-river checks), macOS arm64, 2026-10-06 |
| [`mc_courant_timestep/`](mc_courant_timestep/) | Reproduce Wlostowski's 2020 synthetic-channel experiment: Muskingum-Cunge with C > 1 delays and attenuates waves | Fortran MC kernels, notebooks, helpers pinned by commit SHA on GitHub | ~3 min | Primary reproduced exactly (macOS arm64 and Docker linux/arm64). Exploratory notebook: 4 of 7 runs reproduced; its 2020 kernel reads uninitialized memory (see its README) |
| [`short_ts_switch/`](short_ts_switch/) | What does T-Route's `assume_short_ts` (WRF-Hydro's one-step upstream-inflow lag) do to routed flows, how does it build up through a network, and how does it depend on dt? T-Route itself (CIROH-UA `d29f663`, built from source), True/False × dt 60/300/900/3600 s | t-route source and its `test/LowerColorado_TX` (recorded NWM forcing) fetched by commit SHA; NWM v3.1.6 RouteLink_CONUS.nc (Potomac extracted, synthetic storm) | ~7.5 min (clean, 4 jobs) | `check.py` passes (122/122), macOS arm64, 2026-10-07; clean rerun identical. Not yet reviewed by the author |

## Running an experiment

Prerequisites: [`uv`](https://docs.astral.sh/uv/) (it installs the pinned Python
itself), network access to the input URLs, and for `mc_courant_timestep/` a
Fortran compiler (`gfortran`) plus a C compiler. `short_ts_switch/` also needs `make`,
`git`, and netCDF-C/netCDF-Fortran (`nc-config`, `nf-config`) to build T-Route. Then:

```bash
repro/<experiment>/run.sh          # fetch -> run -> check; exit status 0 = reproduced
```

`mc_courant_timestep/` also ships a `Dockerfile` (base image pinned by digest) for a
platform-independent run. Docker images must build from lean, pinned base images
(e.g. Debian slim by digest, as here), with everything else installed explicitly and
pinned, rather than from large prebuilt science images (author direction,
2026-10-05).

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

### Pinning rules
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
[Zenodo](https://zenodo.org/) (GitHub integration gives a DOI per release) and cite the
DOI in the paper's data/code availability statement. Large public inputs (RouteLink
files) are not redistributed; they are cited by URL plus SHA-256. If NCEP removes them,
a deposit of the exact files (with NOAA's public-domain status noted) would be needed.
No deposit has been made yet.
