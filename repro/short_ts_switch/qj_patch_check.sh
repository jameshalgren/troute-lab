#!/usr/bin/env bash
# Optional diagnostic (not part of run.sh): how much of the True/False comparison depends on
# the MC kernel's uninitialized secant variable (README "Mechanism checks", E).
# Builds a second, patched T-Route (build_troute.py --patch-qj) in a separate copy of this
# directory (build/qj_patch/, own .venv), reruns the Potomac storm at dt = 300 and 3600 s with
# both settings, and compares with results/runs/ -> results/qj_patch_check.json.
# Needs run.sh to have completed. About 5 minutes on a 16-core Apple-silicon Mac.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
W="$HERE/build/qj_patch"
mkdir -p "$W/data"
cp "$HERE"/*.py "$HERE"/pyproject.toml "$HERE"/uv.lock "$HERE"/.python-version "$W"/
ln -sfn "$HERE/data/t-route" "$W/data/t-route"
ln -sfn "$HERE/data/RouteLink_CONUS.nc" "$W/data/RouteLink_CONUS.nc"
(
  cd "$W"
  uv sync --locked --inexact
  uv run --locked python build_troute.py --patch-qj ${FORCE:+--force}
  uv run --locked python make_inputs.py potomac_storm
  for dt in 300 3600; do
    for s in true false; do
      uv run --locked python run_troute.py potomac_storm "$dt" "$s"
    done
  done
)
uv run --locked python qj_patch_compare.py "$W/results/runs/potomac_storm"
