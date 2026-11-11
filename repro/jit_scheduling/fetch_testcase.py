# /// script
# requires-python = "==3.12.*"
# dependencies = []
# ///
"""Download the t-route test case RouteLink (test/LowerColorado_TX/domain/RouteLink.nc) to
data/lc_test/ and print its SHA-256. Used by check.py test 7 (optional).

Source: https://github.com/NOAA-OWP/t-route/blob/12a8eae0cdfed437143c590659fa7077605a5e70/test/LowerColorado_TX/domain/RouteLink.nc
(file fetched 2026-10-29; 1,117,660 bytes)."""
import hashlib
import urllib.request
from pathlib import Path

COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"   # NOAA-OWP/t-route master on 2026-10-29
URL = f"https://raw.githubusercontent.com/NOAA-OWP/t-route/{COMMIT}/test/LowerColorado_TX/domain/RouteLink.nc"
SHA256 = "e7ab06e5a93c664a91b10650063e0994279ef5ecc355024a780594d44e1aab47"
dest = Path(__file__).resolve().parent / "data" / "lc_test" / "RouteLink.nc"
dest.parent.mkdir(parents=True, exist_ok=True)
if not dest.exists():
    urllib.request.urlretrieve(URL, dest)
h = hashlib.sha256(dest.read_bytes()).hexdigest()
if h != SHA256:
    raise SystemExit(f"SHA-256 mismatch for {dest}: {h} != {SHA256}")
print(dest.name, dest.stat().st_size, "bytes, sha256 OK", h)
