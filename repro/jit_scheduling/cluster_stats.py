# /// script
# requires-python = "==3.12.*"
# dependencies = ["numpy==2.5.4", "numba==0.68.1", "netCDF4==1.7.5.1.post1", "pandas==3.0.6"]
# ///
"""Cluster-size statistics for the old (0.65 rule) and bin-packing (PR #26) clustering.
    uv run cluster_stats.py -> results/cluster_stats.csv
The PR reports a cluster-size standard deviation of 318.13 -> 88.74 segments without
stating the domain or target size; the Mississippi at T = 1000 gives similar values, which
is suggestive but not a confirmation (README, "Balancing")."""
from pathlib import Path
import numpy as np
import pandas as pd
import jitsched as J
from run_experiments import Scopes, SCOPE_OUTLETS, RL, THRESHOLDS

HERE = Path(__file__).resolve().parent
D, S = J.load_cached(HERE / "data", RL, THRESHOLDS)
rows = []
for sn in ("Mississippi", "CONUS", "RioGrande"):
    sc = Scopes(D, S, sn, None if sn == "CONUS" else SCOPE_OUTLETS[sn])
    for T in (100, 1000, 10000):
        for mode in ("subnet", "cluster_old", "cluster_bin"):
            G = sc.graph(mode, T)
            # per-order statistics (clusters in an order run concurrently), then pooled
            c = G.cost
            rows.append(dict(scope=sn, T=T, mode=mode, n_clusters=G.n, mean=c.mean(), std=c.std(), min=c.min(), max=c.max(),
                             share_over_1p1T=float((c > 1.1 * T).mean())))
out = pd.DataFrame(rows).round(2)
out.to_csv(HERE / "results" / "cluster_stats.csv", index=False)
print(out.to_string(index=False))
