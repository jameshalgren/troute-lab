#!/usr/bin/env bash
# One command: locked env -> modified-equation derivation -> fetch WRF-Hydro file at the
# pinned SHA, apply the draft patch, build the harness -> experiments -> check.
# AI-written (Claude, 2026-10-09); not reviewed.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required"; exit 1; }
for t in "${FC:-gfortran}" patch; do command -v "$t" >/dev/null || { echo "ERROR: $t not found"; exit 1; }; done
uv sync --locked
mkdir -p results
uv run --locked python derive_modified_equation.py | tee results/derivation.txt
uv run --locked python build_harness.py > /dev/null
uv run --locked python analyze.py | tee results/table.txt
cp build/build_info.json results/build_info.json
uv run --locked python check.py
