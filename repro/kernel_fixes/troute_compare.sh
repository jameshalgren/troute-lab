#!/usr/bin/env bash
# T-Route network comparison of kernel variants (README "Network results").
# Needs ../short_ts_switch to have run (its data/ and build/inputs/ are reused).
# For each kernel variant: a working copy of ../short_ts_switch in build/troute/<variant>/
# (own locked .venv, T-Route built by build_troute.py --kernel <variant>), then the
# Potomac storm and LowerColorado runs at dt = 300 s with assume_short_ts True and False.
# (corrected = patches 0001-0008, the default; L5 = without the Secant package 0006-0008;
#  L7 = 0006-0007 without 0008, diagnostic: shows the volume loss 0008 prevents)
# trace-* variants also count how often each corrected code path is taken (troute_trace.py).
# Then troute_compare.py -> results/troute_compare.json, and the cross-process kernel test
# through ../short_ts_switch's qj_patch_compare.py --kernel-batch.
# JOBS=n parallel runs (default 4). FORCE=1 rebuilds. About 25 min on a 16-core Mac.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
STS="$(cd ../short_ts_switch && pwd)"
[ -d "$STS/build/inputs/potomac_storm" ] && [ -d "$STS/build/inputs/lc_nwm" ] || {
  echo "ERROR: run ../short_ts_switch/run.sh first (its inputs are reused)"; exit 1; }
VARIANTS="${VARIANTS:-unpatched L1 L5 L7 corrected corrected+x trace-L1 trace-L8}"
export KERNEL_FIXES="$HERE"
for v in $VARIANTS; do
  W="$HERE/build/troute/$v"
  mkdir -p "$W/data" "$W/build"
  cp "$STS"/*.py "$STS"/pyproject.toml "$STS"/uv.lock "$STS"/.python-version "$W"/
  cp "$HERE/troute_trace.py" "$W"/
  ln -sfn "$STS/data/t-route" "$W/data/t-route"
  ln -sfn "$STS/data/RouteLink_CONUS.nc" "$W/data/RouteLink_CONUS.nc"
  ln -sfn "$STS/build/inputs" "$W/build/inputs"
  (
    cd "$W"
    uv sync -q --locked --inexact
    uv run --locked python build_troute.py --kernel "$v" ${FORCE:+--force} | tail -1
  )
done
jobs_list=()
for v in $VARIANTS; do
  for c in potomac_storm lc_nwm; do
    for s in true false; do
      jobs_list+=("$v $c $s")
    done
  done
done
run_one() {
  set -euo pipefail
  v=$1; c=$2; s=$3
  W="$HERE/build/troute/$v"
  out="$W/results/runs/$c/dt300_sts$([ "$s" = true ] && echo 1 || echo 0).npz"
  [ -z "${FORCE:-}" ] && [ -f "$out" ] && { [[ "$v" != trace-* ]] || [ -f "${out%.npz}.events.json" ]; } && return 0
  cd "$W"
  mkdir -p "$(dirname "$out")"
  if [[ "$v" == trace-* ]]; then
    uv run --locked python troute_trace.py "$c" 300 "$s" --out "$out" > "${out%.npz}.log" 2>&1
  else
    uv run --locked python run_troute.py "$c" 300 "$s" > "$W/run_${c}_${s}.log" 2>&1
  fi
  echo "ok      $v $c $s"
}
export -f run_one
export HERE
printf '%s\n' "${jobs_list[@]}" | xargs -P "${JOBS:-4}" -L 1 bash -c 'run_one $0 $1 $2'
uv run --locked python troute_compare.py
# Cross-process determinism of the compiled kernel (the determinism test): the same 6,000
# Potomac-like calls through ctypes in two fresh processes, per build.
mkdir -p results/xproc
for v in unpatched corrected; do
  W="$HERE/build/troute/$v"
  for k in 1 2; do
    (cd "$W" && uv run --locked python qj_patch_compare.py --kernel-batch build/libmc_kernel.* \
       "$HERE/results/xproc/${v}_$k.npy")
  done
done
uv run --locked python troute_compare.py --xproc-only
