#!/usr/bin/env bash
# One command: locked environment -> fetch + verify sources -> compile the original
# Fortran -> run primary + exploratory experiments -> check against expected/.
# Set QUICK=1 to skip the exploratory sweep (primary experiment + extension, ~45 s).
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
command -v "${FC:-gfortran}" >/dev/null || { echo "ERROR: Fortran compiler ${FC:-gfortran} not found"; exit 1; }
uv sync --locked
uv run --locked python fetch_data.py
uv run --locked python build_kernels.py
uv run --locked python run_experiment.py
# Extension: same channel and forcing, dt up to 4 h, closure diagnostics (~10 s on 8+ cores)
uv run --locked python run_extended.py
uv run --locked python plot_extended.py
# Corrected 2020 kernel (../kernel_fixes/patches/anw2020/) beside the faithful one (~5 s)
uv run --locked python run_corrected.py
if [[ "${QUICK:-0}" != "1" ]]; then
  # Exploratory: deterministic build, both settings of the short-timestep assumption
  uv run --locked python run_dispersion.py --variant init_zero --short-ts both
  # Exploratory: the notebook's own compiler flags (uninitialized memory; platform-dependent)
  uv run --locked python run_dispersion.py --variant notebook_flags --short-ts false
  # Sensitivity demonstration: the same source with uninitialized reals set to NaN
  uv run --locked python run_dispersion.py --variant init_nan --short-ts false --dt 30
  uv run --locked python check.py
else
  uv run --locked python check.py --primary-only --with-extended
fi
