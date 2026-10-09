#!/usr/bin/env bash
# One command: install the locked environment, fetch + verify inputs, run, check.
# Set REQUIRED_ONLY=1 to skip the optional NWM v2.1 RouteLink (269 MB) comparison.
# river_names.py, `subrivers.py --refresh` and `domains.py --refresh` (live USGS/EPA queries) are
# NOT run here; their snapshots river_names.json, subriver_gnis.json (committed) and
# domains_snapshot.json (release asset, downloaded below) are inputs. See README.md.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "ERROR: uv is required (https://docs.astral.sh/uv/)"; exit 1; }
uv sync --locked
if [[ "${REQUIRED_ONLY:-0}" == "1" ]]; then
  uv run --locked python fetch_data.py --required-only
else
  uv run --locked python fetch_data.py
fi
uv run --locked python ../../tools/fetch_bundle.py network-stats   # domains_snapshot.json
uv run --locked python analyze.py
uv run --locked python table_md.py
uv run --locked python subrivers.py
uv run --locked python domains.py
uv run --locked python check.py
