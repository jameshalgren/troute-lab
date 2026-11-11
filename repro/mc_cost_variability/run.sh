#!/usr/bin/env bash
# One command: locked environment -> RouteLink (shared with ../network_stats) -> Potomac case ->
# six routed scenarios with the work-counting kernel port (each verified call by call against
# ../short_ts_switch/closure_port.py) -> replay_record self-test -> timing (TIMING=0 skips it,
# about 15 min single-threaded) -> tables and cost vectors -> figures -> checks.
# JOBS=n scenarios in parallel (default 3). Needs only uv (no Fortran, no T-Route build).
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
JOBS="${JOBS:-3}"
uv sync --locked
uv run --locked python fetch_data.py
uv run --locked python make_case.py
uv run --locked python simulate.py calm            # compiles and caches the numba kernels first
printf '%s\n' s25 s100 s250 s25_f s250_f | \
  NUMBA_NUM_THREADS="$(( $(getconf _NPROCESSORS_ONLN) / JOBS > 0 ? $(getconf _NPROCESSORS_ONLN) / JOBS : 1 ))" \
  xargs -P "$JOBS" -I{} uv run --locked python simulate.py {}
uv run --locked python replay_record.py --self-test s25
if [ "${TIMING:-1}" != "0" ]; then
  uv run --locked python timing.py calm s25 s250    # alone: timing needs a quiet machine
fi
uv run --locked python analyze.py
uv run --locked python figures.py
uv run --locked python check.py
