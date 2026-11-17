# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Compare saved netCDF headers: v3.0 tarball vs NCEP v3.1.7 parm/domain*, and the two TxDOT
RouteLink variants. Supports the "≈hdr" (header identical except `version`) marks in the
§7 cross-walk and key finding 4 (TxDOT headers = v3.0 header). Offline; reads headers/.
Usage (from the catalog folder): uv run python -I scripts/analysis/hdrdiff.py
"""
import glob, os, difflib
def body(p): return open(p).read().splitlines()[2:]  # drop source line and 'netcdf name {' line
pairs = []
for f in sorted(glob.glob("headers/v3.0/*.cdl")):
    b = os.path.basename(f)[len("v3.0_par__"):]
    m = glob.glob(f"headers/ncep_v3.1.7/parm__domain*__{b}")
    pairs.append((f, m[0] if m else None, b))
pairs += [("headers/v3.0/v3.0_par__RouteLink_CONUS.nc.cdl", f"headers/ncep_v3.1.7/parm__domain__RouteLink_CONUS.nc_{t}.cdl", f"RouteLink_CONUS vs _{t}") for t in ("TxDOTstream", "turnoffTxDOTstream")]
pairs += [("headers/ncep_v3.1.7/parm__domain__RouteLink_CONUS.nc_TxDOTstream.cdl", "headers/ncep_v3.1.7/parm__domain__RouteLink_CONUS.nc_turnoffTxDOTstream.cdl", "TxDOT vs turnoffTxDOT")]
for a, b, name in pairs:
    if not b: print(f"== {name}: NOT in NCEP v3.1.7 parm/domain*"); continue
    d = [l for l in difflib.unified_diff(body(a), body(b), lineterm="", n=0) if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    print(f"== {name}: {len(d)} differing header lines")
    for l in d[:6]: print("     " + l[:170])
