#!/usr/bin/env bash
# Run one configured case with one build, under measure.py.
#
#   run_case.sh BUILD_LABEL RUN_DIR [REPEAT]
#
#   BUILD_LABEL  a directory under build/ made by build_troute.sh, e.g. era-original,
#                current-corrected
#   RUN_DIR      holds config.yaml + case.json from make_configs.py (written with the
#                matching --code); results go to RUN_DIR/<BUILD_LABEL>/r<REPEAT>/
#   REPEAT       repetition number (default 1)
#
# The t-route command is the one each commit documents: `python -m nwm_routing -f -V3
# config.yaml` (a6efbf4e: synchronous looping, main_v03) or `-V4` (d29f663: main_v04).
# Nothing in the environment is tuned by default (the 2022 run is not known to have set
# anything); export MALLOC_ARENA_MAX / OMP_NUM_THREADS yourself for a tuning arm, and
# measure.py records them.
#
# AI-written (Claude, 2026-11-04); not yet reviewed by the author. NOT YET RUN against a
# t-route build (no Fortran compiler on the machine where it was written).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
LABEL=${1:?usage: run_case.sh BUILD_LABEL RUN_DIR [REPEAT]}
RUN=$(cd "${2:?usage: run_case.sh BUILD_LABEL RUN_DIR [REPEAT]}" && pwd)
REP=${3:-1}
B=$HERE/build/$LABEL
PY=$B/.venv/bin/python
[[ -x "$PY" && -f "$B/build_info.json" ]] || { echo "ERROR: build $LABEL not found; run build_troute.sh first" >&2; exit 1; }
[[ -f "$RUN/config.yaml" && -f "$RUN/case.json" ]] || { echo "ERROR: $RUN lacks config.yaml/case.json (make_configs.py)" >&2; exit 1; }
CODE=${LABEL%%-*}
grep -q "\"code\": \"$CODE\"" "$RUN/case.json" || { echo "ERROR: $RUN was written for another --code than $CODE" >&2; exit 1; }
V=$([[ "$CODE" == era ]] && echo 3 || echo 4)
OUT=$RUN/$LABEL/r$REP
mkdir -p "$OUT"
cp "$RUN/config.yaml" "$RUN/case.json" "$B/build_info.json" "$OUT/"
# A CHRTOUT-output run appends `streamflow_troute` to the forcing files; a second run on
# the same files would find the variable already there, so warn.
if grep -q chrtout_output "$OUT/config.yaml"; then
  echo "NOTE: chrtout output writes into the forcing files; use a fresh copy of the forcing directory per run." >&2
fi
# lite restart output is configured as the relative directory restart_out (cwd = $OUT)
if grep -q lite_restart_output_directory "$OUT/config.yaml"; then mkdir -p "$OUT/restart_out"; fi
# macOS: keep the machine awake for as long as this script runs (no effect elsewhere)
if command -v caffeinate >/dev/null; then caffeinate -i -w $$ & fi
cd "$HERE"
uv run --locked python measure.py --out "$OUT" -- "$PY" -m nwm_routing -f -V$V "$OUT/config.yaml"
