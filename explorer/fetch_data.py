# /// script
# requires-python = ">=3.10"
# ///
"""Download the basin explorer's data into explorer/data/ (SHA-256 checked).

    uv run explorer/fetch_data.py            # web data: JSON + overview tiles (~31 MB)
    uv run explorer/fetch_data.py --full     # + full-resolution tiles flowlines.pmtiles (983 MB)
    uv run explorer/fetch_data.py --verify   # check only
    uv run explorer/fetch_data.py --source hydroshare | <base URL> | <directory>

Versions, URLs and checksums: ../data_bundles.json (bundle "explorer"). To build the same
files from the public sources instead, see README.md ("Rebuild everything").
"""
import runpy
import sys
from pathlib import Path

sys.argv[1:1] = ["explorer"]
runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools" / "fetch_bundle.py"), run_name="__main__")
