#!/usr/bin/env bash
# Reproduce everything. Needs uv. The RouteLink download (~270 MB) is shared with ../network_stats.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
RL=../network_stats/data/RouteLink_CONUS.nc
if [[ ! -f "$RL" ]]; then
  (cd ../network_stats && uv run --locked python fetch_data.py --required-only)   # SHA-256 verified there
fi
uv run fetch_testcase.py        # t-route test case RouteLink (1 MB), used by check.py test 7
uv run worked_example.py        # 15-segment schematic
uv run run_experiments.py       # main grid + sensitivities (about 8 min of CPU time; see README)
uv run cluster_stats.py
uv run make_figures.py
# measured-cost schedules (needs ../mc_cost_variability/results/cost/, from `bash ../mc_cost_variability/run.sh`)
if [[ -f ../mc_cost_variability/results/cost/segment_cost.csv ]]; then uv run cost_scheduling.py; fi
uv run check.py
