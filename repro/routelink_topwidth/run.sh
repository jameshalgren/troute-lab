#!/usr/bin/env bash
# One command: install the locked environment, fetch + verify inputs, run, check.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
uv sync --locked
uv run --locked python fetch_data.py
uv run --locked python analyze.py
uv run --locked python check.py
