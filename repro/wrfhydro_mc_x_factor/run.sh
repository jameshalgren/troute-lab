#!/usr/bin/env bash
# One command, three parts (AI-written, Claude, 2026-10-09; parts 2-3 added 2026-10-31; not reviewed):
#   1. prismatic channel: modified-equation derivation, then WRF-Hydro's SUBMUSKINGCUNGE (fetched at
#      a pinned SHA, original and patched) against the analytical convection-diffusion solution
#   2. Potomac network: the same routine, driven like WRF-Hydro's channel driver, on the NWM v3.1.7
#      Potomac network (RouteLink fetched and SHA-256 checked) with a synthetic storm; run with the
#      short-time-step assumption (lagged upstream inflow, WRF-Hydro's own way) and without it
#      (sequential, current-step upstream inflow; added 2026-11-02)
#   3. T-Route on the same storm, current vs patched kernel, assume_short_ts True and False
#      (troute_part3.sh); needs
#      ../short_ts_switch/run.sh to have been run first (its inputs are reused), else skipped
#   1b. (after part 2) part 1 under NWM conditions: reaches.py, single reaches with NWM v3.1.7 link
#      lengths, slopes and channel geometry, inflow = part 2's storm hydrograph at a gauge (added 2026-11-02)
# QUICK=1 runs part 1 only; SKIP_TROUTE=1 skips part 3. Wall-clock times go to the timing files.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required"; exit 1; }
for t in "${FC:-gfortran}" patch; do command -v "$t" >/dev/null || { echo "ERROR: $t not found"; exit 1; }; done
uv sync --locked
mkdir -p results

# ---- part 1: prismatic channel
uv run --locked python derive_modified_equation.py | tee results/derivation.txt
uv run --locked python build_harness.py > /dev/null
uv run --locked python analyze.py | tee results/table.txt
cp build/build_info.json results/build_info.json

if [ -z "${QUICK:-}" ]; then
  # ---- part 2: Potomac network, WRF-Hydro's routine
  uv run --locked python fetch_data.py
  uv run --locked python potomac_inputs.py
  mkdir -p build/potomac/out
  T=build/potomac/timing.txt
  echo "# WRF-Hydro part 2, $(date -u +%Y-%m-%dT%H:%M:%SZ), $(uname -sm), $(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)" > "$T"
  # lagged (WRF-Hydro's way, the default) -> out/<v>_*; sequential -> out/<v>_seq_*
  for v in orig patched; do
    for m in lagged sequential; do
      o=$v; [ "$m" = sequential ] && o=${v}_seq
      ( s=$(date +%s)
        build/network_driver "$v" build/potomac/inputs.bin "build/potomac/out/$o" "$m" > "build/potomac/out/${o}_stdout.txt"
        echo "run $o: $(( $(date +%s) - s )) s" >> "$T" ) &
    done
  done
  wait
  # ---- part 1, NWM conditions: single reaches built from NWM links, inflow from part 2
  uv run --locked python reaches.py | tee results/reaches_table.txt
  # ---- part 3: T-Route on the same storm (optional)
  if [ -z "${SKIP_TROUTE:-}" ] && [ -d ../short_ts_switch/build/inputs/potomac_storm ]; then
    ./troute_part3.sh
  else
    echo "skip    part 3 (T-Route): set up ../short_ts_switch first, or unset SKIP_TROUTE"
  fi
  uv run --locked python potomac_analyze.py | tee results/potomac_table.txt
fi

uv run --locked python check.py
