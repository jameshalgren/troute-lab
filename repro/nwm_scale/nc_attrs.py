# /// script
# requires-python = ">=3.9"
# dependencies = ["netCDF4", "numpy"]
# ///
"""Print the timing attributes and feature_id count of NWM channel_rt files.

model_initialization_time shows where each run starts, so (valid time - initialization
time) gives the hours a cycle integrates; model_total_valid_times is the number of output
times in the run; feature_id is the number of reaches written.
Files are downloads: keep them in their own directory and run with -I, e.g.
    uv run --no-project --with netCDF4 --with numpy python -I nc_attrs.py DIR/*.nc
"""
import os, sys
import numpy as np
import netCDF4

KEYS = ["model_initialization_time", "model_output_valid_time", "model_total_valid_times",
        "NWM_version_number", "code_version", "model_configuration", "dev_channel_only"]
flows = {}
for p in sys.argv[1:]:
    with netCDF4.Dataset(p) as ds:
        a = {k: ds.getncattr(k) for k in ds.ncattrs()}
        nf = len(ds.dimensions["feature_id"]) if "feature_id" in ds.dimensions else None
        flows[os.path.basename(p)] = (a.get("model_output_valid_time"),
                                      np.asarray(ds.variables["streamflow"][:], dtype=float))
    print(f"{os.path.basename(p)}\tfeature_id={nf}\t" + "\t".join(f"{k}={a.get(k, '')}" for k in KEYS))

# Same valid time from different cycles: are the overlapping hours recomputed?
names = sorted(flows)
for i, a in enumerate(names):
    for b in names[i + 1:]:
        (va, qa), (vb, qb) = flows[a], flows[b]
        same_run = a.split(".")[2] == b.split(".")[2] and a.split(".")[-2] == b.split(".")[-2]
        if va == vb and same_run and qa.shape == qb.shape:
            d = np.abs(qa - qb)
            print(f"streamflow {a} vs {b}: max |diff| {np.nanmax(d):.4g} m3/s, reaches differing {np.mean(d > 1e-6):.3%}")
