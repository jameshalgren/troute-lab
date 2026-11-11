#!/usr/bin/env bash
# One command: locked environment -> fetch + verify sources -> kernel harness (sweep.py:
# every patch level, NGWPC's kernels, diagnostic builds) -> T-Route network comparison
# (troute_compare.sh; needs ../short_ts_switch's inputs, made here if missing) -> check.
# JOBS=n parallel T-Route runs (default 4). FORCE=1 rebuilds. SKIP_TROUTE=1 runs only the
# kernel harness (about 1 min); the full run takes about 30 min on a 16-core Mac.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
for t in "${FC:-gfortran}" git; do
  command -v "$t" >/dev/null || { echo "ERROR: $t not found"; exit 1; }
done
uv sync --locked
uv run --locked python fetch_data.py
uv run --locked python sweep.py
if [ "${SKIP_TROUTE:-0}" != "1" ]; then
  S=../short_ts_switch
  if [ ! -f "$S/build/inputs/lc_nwm/case.json" ] || [ ! -f "$S/build/inputs/potomac_storm/case.json" ]; then
    (cd "$S" && uv sync --locked --inexact && uv run --locked python fetch_data.py && uv run --locked python make_inputs.py)
  fi
  ./troute_compare.sh
fi
uv run --locked python check.py
