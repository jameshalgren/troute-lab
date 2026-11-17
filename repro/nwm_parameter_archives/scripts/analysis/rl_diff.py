# /// script
# requires-python = ">=3.9"
# dependencies = ["numpy", "netCDF4"]
# ///
"""Variable-by-variable comparison of RouteLink files against the first one given.
Supports key findings 3-4 and §4 RouteLink (v3.1.7 vs v3.0 differ only in `to` 9,
`order` 36, `gages` 1,057 links; TxDOT variants: `gages` 90 / 13 links).
Needs the full RouteLink files (not in this folder).
Usage: uv run scripts/analysis/rl_diff.py NAME1 RouteLink_a.nc NAME2 RouteLink_b.nc [NAME3 c.nc ...]
"""
import sys, numpy as np, netCDF4 as nc
names = sys.argv[1::2]; paths = sys.argv[2::2]
ds = [nc.Dataset(p) for p in paths]
ref = ds[0]; link0 = ref["link"][:]
for n, d in zip(names[1:], ds[1:]):
    link = d["link"][:]
    same_order = np.array_equal(link0, link)
    print(f"== {names[0]} vs {n}: same link order={same_order}")
    idx = None
    if not same_order:
        o0 = np.argsort(link0); o1 = np.argsort(link); assert np.array_equal(link0[o0], link[o1])
    for v in ref.variables:
        if v not in d.variables: print("   missing", v); continue
        a = ref[v][:]; b = d[v][:]
        if not same_order and a.shape and a.shape[0] == len(link0): a = a[o0]; b = b[o1]
        a = np.ma.filled(a, -9.99e9) if np.ma.isMaskedArray(a) else a
        b = np.ma.filled(b, -9.99e9) if np.ma.isMaskedArray(b) else b
        if a.dtype.kind in "fc": neq = ~((a == b) | (np.isnan(a) & np.isnan(b)))
        else: neq = a != b
        if neq.ndim > 1: neq = neq.any(axis=tuple(range(1, neq.ndim)))
        k = int(np.sum(neq))
        if k:
            ids = (link0[o0] if not same_order else link0)[neq][:8] if neq.shape and neq.shape[0] == len(link0) else ""
            print(f"   {v}: {k} differ; e.g. links {list(ids)}")
