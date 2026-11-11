#!/usr/bin/env bash
# One command: locked environment -> fetch + verify inputs -> build T-Route at the
# pinned commit -> prepare inputs -> run the True/False x dt matrix -> analyze ->
# mechanism checks ->
# repeat four runs for the bitwise self-consistency check -> provenance -> check.
# JOBS=n sets parallel T-Route processes (default 4). FORCE=1 reruns everything.
# CLOSURE=1 also runs closure.sh (optional closure diagnostics) before check.py.
# KERNEL=unpatched builds T-Route's MC kernel as published (opt-in comparison; default
# since 2026-10-09: the corrected kernel, ../kernel_fixes; check.py then uses the
# expected/*_unpatched_kernel.json baselines).
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
for t in "${F90:-gfortran}" make git nc-config nf-config; do
  command -v "$t" >/dev/null || { echo "ERROR: $t not found (needs a Fortran compiler, make, git, netCDF-C and netCDF-Fortran)"; exit 1; }
done
# --inexact: keep the t-route packages that build_troute.py installs into this venv
uv sync --locked --inexact
uv run --locked python fetch_data.py
uv run --locked python build_troute.py ${FORCE:+--force}
uv run --locked python make_inputs.py
uv run --locked python run_experiment.py --jobs "${JOBS:-4}" ${FORCE:+--force}
uv run --locked python analyze.py
JOBS="${JOBS:-4}" uv run --locked python mechanism.py
rm -rf results/rerun
uv run --locked python run_experiment.py --jobs "${JOBS:-4}" --rerun results/rerun
uv run --locked python -c "
import json, sys
from pathlib import Path
sys.path.insert(0, '.')
import provenance
from fetch_data import TROUTE_SHA, TROUTE_REPO, ROUTELINK_DEST
info = json.loads(Path('build/build_info.json').read_text())
provenance.write(Path('.').resolve(), Path('results'),
    inputs={'RouteLink_CONUS.nc': ROUTELINK_DEST},
    sources={'t-route': {'repo': TROUTE_REPO, 'commit': TROUTE_SHA}},
    compilers=[['gfortran', '--version'], ['gcc', '--version'], ['nf-config', '--version'], ['nc-config', '--version']],
    extra={'troute_build': {k: v for k, v in info.items() if k != 'steps'}})
print('ok      results/provenance.json')
"
# Optional, about 15 min and up to ~35 GB of temporary disk: the closure diagnostics
# (README "Closure diagnostics on the network"); check.py section 6 then checks them.
if [ "${CLOSURE:-0}" = "1" ]; then
  ./closure.sh
fi
uv run --locked python check.py
