#!/usr/bin/env bash
# Write the configurations of one stage of the plan (README.md) and print the commands
# that run them. Runs nothing long.
#
#   make_matrix.sh smoke        Stage i  (author's laptop): CONUS one week; Potomac one year
#   make_matrix.sh ohio         Stage i, optional: Ohio one year
#   make_matrix.sh month NCPU   Stage ii (lab Mac): CONUS January 2018, NCPU workers
#   make_matrix.sh year NCPU    Stage ii (lab Mac): CONUS calendar 2018, NCPU workers
#
# Each configuration goes to results/<case>/<variant>/<era|current>/ (config.yaml,
# case.json); run_case.sh <build label> <that directory> runs it. Inputs must exist
# first (fetch_inputs.py, make_mask.py; see README.md).
#
# AI-written (Claude, 2026-11-04); not yet reviewed by the author.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=${PERF2022_DATA:-$HERE/data}
STAGE=${1:?usage: make_matrix.sh smoke|ohio|month NCPU|year NCPU}
NCPU=${2:-}
OUT=${PERF2022_RESULTS:-$HERE/results}
CMDS=()

cfg() {  # cfg CASE VARIANT HOURS FORCING_DIR [extra make_configs args...]
  local case=$1 var=$2 hours=$3 forcing=$4; shift 4
  for code in era current; do
    local d=$OUT/$case/$var/$code
    (cd "$HERE" && uv run --locked python make_configs.py --code "$code" --case "$case" \
       --start 2018-01-01_00 --hours "$hours" --forcing-dir "$forcing" --out "$d" "$@") | sed 's/^/  /'
    if [[ $code == era ]]; then
      CMDS+=("./run_case.sh era-original $d" "./run_case.sh era-corrected $d")
    else
      CMDS+=("./run_case.sh current-corrected $d" "./run_case.sh current-original $d")
    fi
  done
}

case "$STAGE" in
  smoke)
    F=$DATA/forcing/conus_slim
    # CONUS, one week: parallel method and worker count (4 = the M5's performance cores)
    cfg conus_week jitc_cpu4_loop12  168 "$F" --method by-subnetwork-jit-clustered --cpu-pool 4  --loop-hours 12
    cfg conus_week jitc_cpu10_loop12 168 "$F" --method by-subnetwork-jit-clustered --cpu-pool 10 --loop-hours 12
    cfg conus_week jit_cpu4_loop12   168 "$F" --method by-subnetwork-jit           --cpu-pool 4  --loop-hours 12
    cfg conus_week net_cpu4_loop12   168 "$F" --method by-network                  --cpu-pool 4  --loop-hours 12
    cfg conus_week jitc_cpu4_loop12_lite 168 "$F" --method by-subnetwork-jit-clustered --cpu-pool 4 --loop-hours 12 --output lite
    # Potomac (16,454 segments), one year, serial: per-segment-step cost with no parallel overhead
    cfg potomac_year serial_loop24 8760 "$DATA/forcing/potomac" --mask "$DATA/masks/potomac.csv" --method serial --cpu-pool 1 --loop-hours 24
    ;;
  ohio)
    cfg ohio_year jitc_cpu4_loop24 8760 "$DATA/forcing/ohio" --mask "$DATA/masks/ohio.csv" --method by-subnetwork-jit-clustered --cpu-pool 4 --loop-hours 24
    cfg ohio_year serial_loop24    8760 "$DATA/forcing/ohio" --mask "$DATA/masks/ohio.csv" --method serial --cpu-pool 1 --loop-hours 24
    ;;
  month|year)
    [[ -n "$NCPU" ]] || { echo "ERROR: give the number of workers (performance cores on Apple silicon, physical cores otherwise)" >&2; exit 2; }
    F=$DATA/forcing/conus_slim
    H=$([[ $STAGE == month ]] && echo 744 || echo 8760)
    cfg conus_$STAGE "jitc_cpu${NCPU}_loop24" "$H" "$F" --method by-subnetwork-jit-clustered --cpu-pool "$NCPU" --loop-hours 24
    if [[ $STAGE == month ]]; then
      cfg conus_month "jitc_cpu${NCPU}_loop12" 744 "$F" --method by-subnetwork-jit-clustered --cpu-pool "$NCPU" --loop-hours 12
      cfg conus_month "jit_cpu${NCPU}_loop24"  744 "$F" --method by-subnetwork-jit           --cpu-pool "$NCPU" --loop-hours 24
      cfg conus_month "net_cpu${NCPU}_loop24"  744 "$F" --method by-network                  --cpu-pool "$NCPU" --loop-hours 24
      CORES=$( (sysctl -n hw.physicalcpu 2>/dev/null || nproc) | head -1)
      if [[ "$NCPU" != 36 ]] && ((CORES >= 36)); then  # the Cheyenne node size of 2022 (36 cores)
        cfg conus_month jitc_cpu36_loop24 744 "$F" --method by-subnetwork-jit-clustered --cpu-pool 36 --loop-hours 24
      fi
    fi
    ;;
  *) echo "ERROR: unknown stage $STAGE" >&2; exit 2 ;;
esac

echo
echo "Configurations written. Run (one at a time; each line is one measured run):"
for c in "${CMDS[@]}"; do echo "  $c"; done
echo "Then: uv run --locked python summarize.py"
