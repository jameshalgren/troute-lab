#!/usr/bin/env bash
# One command: locked environment -> fetch + verify sources -> compile the original
# Fortran -> run primary + exploratory experiments -> check against expected/.
# Set QUICK=1 to skip the exploratory sweep (primary experiment only, ~30 s).
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
command -v "${FC:-gfortran}" >/dev/null || { echo "ERROR: Fortran compiler ${FC:-gfortran} not found"; exit 1; }
uv sync --locked
uv run --locked python fetch_data.py
uv run --locked python build_kernels.py
uv run --locked python run_experiment.py
if [[ "${QUICK:-0}" != "1" ]]; then
  # Exploratory: deterministic build, both settings of the short-timestep assumption
  uv run --locked python run_dispersion.py --variant init_zero --short-ts both
  # Exploratory: the notebook's own compiler flags (uninitialized memory; platform-dependent)
  uv run --locked python run_dispersion.py --variant notebook_flags --short-ts false
  # Sensitivity demonstration: the same source with uninitialized reals set to NaN
  uv run --locked python run_dispersion.py --variant init_nan --short-ts false --dt 30
  uv run --locked python check.py
else
  uv run --locked python check.py --primary-only
fi
