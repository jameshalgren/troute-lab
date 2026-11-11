#!/usr/bin/env bash
# Part 3: T-Route on the same Potomac storm, current X vs patched X.
# AI-written (Claude, 2026-10-28). Mirrors ../kernel_fixes/troute_compare.sh, for two kernels only:
#   corrected    = T-Route's MC kernel with ../kernel_fixes patches 0001-0008 (the current X)
#   corrected+x  = the same plus ../kernel_fixes/patches/optional/x-cunge-factor2.patch
# Each is built from CIROH-UA/t-route d29f663 in its own working copy under build/troute/<kernel>/
# and run on ../short_ts_switch's potomac_storm case at dt = 300 s, assume_short_ts True (the
# NWM-parity setting, like WRF-Hydro's driver in part 2) and False (current-step upstream inflow,
# like part 2's sequential mode; added 2026-11-02). Needs ../short_ts_switch/run.sh to have
# been run first (its data/ and build/inputs/ are reused). Wall-clock times go to
# build/troute/timing.txt. FORCE=1 rebuilds T-Route; JOBS (default 4) runs at once.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
STS="$(cd ../short_ts_switch && pwd)"
KF="$(cd ../kernel_fixes && pwd)"
[ -d "$STS/build/inputs/potomac_storm" ] || { echo "ERROR: run ../short_ts_switch/run.sh first"; exit 1; }
export KERNEL_FIXES="$KF"
mkdir -p build/troute
T="$HERE/build/troute/timing.txt"
echo "# T-Route part 3, $(date -u +%Y-%m-%dT%H:%M:%SZ), $(uname -sm), $(sysctl -n machdep.cpu.brand_string 2>/dev/null || true)" > "$T"
t0=$(date +%s)
for k in corrected corrected+x; do
  W="$HERE/build/troute/$k"
  mkdir -p "$W/data" "$W/build"
  cp "$STS"/*.py "$STS"/pyproject.toml "$STS"/uv.lock "$STS"/.python-version "$W"/
  ln -sfn "$STS/data/t-route" "$W/data/t-route"
  ln -sfn "$STS/data/RouteLink_CONUS.nc" "$W/data/RouteLink_CONUS.nc"
  ln -sfn "$STS/build/inputs" "$W/build/inputs"
  s=$(date +%s)
  ( cd "$W" && uv sync -q --locked --inexact && uv run --locked python build_troute.py --kernel "$k" ${FORCE:+--force} | tail -1 )
  echo "build $k: $(( $(date +%s) - s )) s" >> "$T"
done
run_one() {
  set -euo pipefail
  k=$1; sts=$2; W="$HERE/build/troute/$k"; s=$(date +%s)
  n=1; [ "$sts" = false ] && n=0
  ( cd "$W" && uv run --locked python run_troute.py potomac_storm 300 "$sts" > "$W/run_potomac_$sts.log" 2>&1 )
  echo "run $k potomac_storm dt300 sts$n: $(( $(date +%s) - s )) s" >> "$T"
  echo "ok      $k assume_short_ts=$sts"
}
export -f run_one
export HERE T
printf '%s\n' "corrected true" "corrected+x true" "corrected false" "corrected+x false" \
  | xargs -P "${JOBS:-4}" -L 1 bash -c 'run_one $0 $1'
echo "total: $(( $(date +%s) - t0 )) s" >> "$T"
cat "$T"
