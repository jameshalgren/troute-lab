#!/usr/bin/env bash
# One command: inputs (from ../short_ts_switch) -> T-Route CIROH-UA d29f663 with
# troute-upstream-inflow.patch and the corrected MC kernel (../kernel_fixes/patches) ->
# full / clipped runs -> comparison -> provenance -> check.
# COMPARE_UNPATCHED=1 also builds and runs the patch with the kernel as published
# (2026-10-09: before then the default build used that kernel, and "qj" the Qj-only fix).
# JOBS=n sets parallel T-Route processes (default 4). FORCE=1 rebuilds and reruns.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
for t in "${F90:-gfortran}" make git nc-config nf-config; do
  command -v "$t" >/dev/null || { echo "ERROR: $t not found (needs a Fortran compiler, make, git, netCDF-C and netCDF-Fortran)"; exit 1; }
done

# Inputs: the two test domains prepared by the sibling experiment (same T-Route commit;
# LowerColorado_TX from t-route's test data, Potomac from NWM v3.1.7 RouteLink). Made
# there only if missing; that experiment's T-Route build is not touched.
S=../short_ts_switch
if [ ! -f "$S/build/inputs/lc_nwm/case.json" ] || [ ! -f "$S/build/inputs/potomac_storm/case.json" ]; then
  (cd "$S" && uv sync --locked --inexact && uv run --locked python fetch_data.py && uv run --locked python make_inputs.py)
fi

# --inexact: keep the t-route packages that build_patched.py installs into each venv
uv sync --locked --inexact
uv run --locked python build_patched.py --variant corrected ${FORCE:+--force}
uv run --locked python test_clip.py --variant corrected --jobs "${JOBS:-4}" ${FORCE:+--force}
VARIANTS="corrected"
if [ "${COMPARE_UNPATCHED:-0}" = "1" ]; then
  export_u() { UV_PROJECT_ENVIRONMENT=build/venv_unpatched "$@"; }
  export_u uv sync --locked --inexact
  export_u uv run --locked python build_patched.py --variant unpatched ${FORCE:+--force}
  export_u uv run --locked python test_clip.py --variant unpatched --jobs "${JOBS:-4}" ${FORCE:+--force}
  VARIANTS="corrected unpatched"
fi

VARIANTS="$VARIANTS" uv run --locked python -c "
import json, os, sys
from pathlib import Path
sys.path.insert(0, '.')
import provenance
S = Path('../short_ts_switch/build/inputs')
inputs = {'troute-upstream-inflow.patch': Path('troute-upstream-inflow.patch')}
for case in ('lc_nwm', 'potomac_storm'):
    for f in ('RouteLink.nc', 'restart.pkl', 'segments.parquet', 'case.json'):
        inputs[f'{case}/{f}'] = S / case / f
builds = {v: {k: x for k, x in json.loads(Path(f'build/{v}/build_info.json').read_text()).items() if k != 'steps'}
          for v in os.environ['VARIANTS'].split()}
provenance.write(Path('.').resolve(), Path('results'), inputs=inputs,
    sources={'t-route': {'repo': builds['corrected']['troute_repo'], 'commit': builds['corrected']['troute_commit']}},
    compilers=[['gfortran', '--version'], ['gcc', '--version'], ['nf-config', '--version'], ['nc-config', '--version']],
    extra={'troute_builds': builds})
print('ok      results/provenance.json')
"
uv run --locked python check.py
