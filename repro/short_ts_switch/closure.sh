#!/usr/bin/env bash
# Optional (CLOSURE=1 run.sh runs it): what the MC kernel's Cunge closure produces on the
# network (README "Closure diagnostics on the network"). Needs run.sh's runs and build.
# 1. a second T-Route build with the unpatched d29f663 kernel in build/unpatched_kernel
#    (skipped if present; since 2026-10-09 this directory's own build is the corrected
#    kernel); 2. closure_runs.py: every run of the matrix recorded with both builds at
#    native resolution, replayed through the float32 port closure_port.py (numba; the
#    corrected recording with its corrected mode), reduced, recordings deleted;
#    3. closure_analyze.py: results/closure/summary.json + figures.
# About 15 min with 4 jobs on a 16-core Apple-silicon Mac; peak disk about 35 GB under
# build/closure_runs (dt = 60 s recordings). FORCE=1 redoes everything.
set -euo pipefail
cd "$(dirname "$0")"
HERE="$PWD"
W="$HERE/build/unpatched_kernel"
if ! grep -q '"kernel": "unpatched"' "$W/build/build_info.json" 2>/dev/null; then
  mkdir -p "$W/data"
  cp "$HERE"/*.py "$HERE"/pyproject.toml "$HERE"/uv.lock "$HERE"/.python-version "$W"/
  ln -sfn "$HERE/data/t-route" "$W/data/t-route"
  ln -sfn "$HERE/data/RouteLink_CONUS.nc" "$W/data/RouteLink_CONUS.nc"
  (
    cd "$W"
    uv sync --locked --inexact
    KERNEL_FIXES="$HERE/../kernel_fixes" uv run --locked python build_troute.py --kernel unpatched ${FORCE:+--force}
  )
fi
# numba caches compiled replays per source file, not per dependency: a cached
# closure_replay.replay would keep an older closure_port inlined. Clear it (2026-10-09).
rm -rf "$HERE/__pycache__"/closure_replay*.nb* "$HERE/__pycache__"/closure_port*.nb*
uv run --locked python closure_runs.py --jobs "${JOBS:-4}" ${FORCE:+--force}
uv run --locked --with "${NUMBA_PIN:-numba==0.61.2}" python closure_analyze.py
