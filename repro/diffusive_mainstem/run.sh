#!/usr/bin/env bash
# One command: install the locked environment, fetch + verify inputs, run, check.
# potomac_check.py uses ../short_ts_switch outputs if that experiment has been run (else skipped).
# geometry_check.py runs only if NWM_HYDROFABRIC_GDB points at an extracted NWM v3 hydrofabric.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
uv sync --locked
uv run --locked python fetch_data.py
uv run --locked python prepare_flows.py
[ -f ../network_stats/results/T_basins.csv ] || { echo "ERROR: run ../network_stats/run.sh first (river names: results/T_basins.csv)"; exit 1; }
uv run --locked python analyze.py
uv run --locked python potomac_check.py
uv run --locked python figures.py
uv run --locked python geometry_check.py
uv run --locked python check.py
