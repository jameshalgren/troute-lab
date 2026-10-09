"""Run T-Route once (one case, one dt, one assume_short_ts setting).

T-Route itself does the routing: this script writes a V4 YAML configuration and calls
`nwm_routing.__main__.main_v04(["-f", <yaml>])`, T-Route's normal entry point
(`python -m nwm_routing -f -V4 <yaml>`). The only intervention is that T-Route's output
writer `nwm_output_generator` is replaced by a function that keeps the in-memory
flow/velocity/depth results, so no output files need to be parsed.

Configuration held fixed across runs: NHDNetwork (RouteLink), Muskingum-Cunge
V02-structured kernel, serial compute, waterbodies NOT broken out (lake segments are
routed as channels; see README), no data assimilation, 24-h forcing loops (LOOP_HOURS).

Writes results/runs/<case>/dt<dt>_sts<0|1>.npz with: link order, end-of-hour flow for all
segments, per-segment peak flow / peak time / volume / depth at peak, native-resolution
flow and depth on the mainstem (longest flow path), and timing.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "build" / "inputs"
RUNS = HERE / "results" / "runs"

# T-Route forcing-loop length (hours). Loops bound memory for long, small-dt runs. A
# loop restart changes flows only at float32-noise level (max 1.2e-5 m3/s on lc_nwm,
# 7-h vs 28-h loops); every run uses the same loop length, so True/False comparisons
# are unaffected.
LOOP_HOURS = 24

COLUMNS = {"key": "link", "downstream": "to", "dx": "Length", "n": "n", "ncc": "nCC", "s0": "So",
           "bw": "BtmWdth", "waterbody": "NHDWaterbodyComID", "gages": "gages", "tw": "TopWdth",
           "twcc": "TopWdthCC", "musk": "MusK", "musx": "MusX", "cs": "ChSlp", "alt": "alt"}


def config(case: str, dt: int, short_ts: bool, hours: int, workdir: Path) -> dict:
    d = INPUTS / case
    info = json.loads((d / "case.json").read_text())
    if 3600 % dt:
        raise ValueError("dt must divide 3600 (hourly forcing)")
    return {
        "log_parameters": {"showtiming": False, "log_level": "WARNING"},
        "network_topology_parameters": {
            "supernetwork_parameters": {"geo_file_path": str(d / "RouteLink.nc"),
                                        "network_type": "NHDNetwork", "columns": COLUMNS},
            "waterbody_parameters": {"break_network_at_waterbodies": False},
        },
        "compute_parameters": {
            "parallel_compute_method": "serial",
            "compute_kernel": "V02-structured",
            "assume_short_ts": bool(short_ts),
            "subnetwork_target_size": 10000,
            "cpu_pool": 1,
            "restart_parameters": {"lite_channel_restart_file": str(d / "restart.pkl")},
            "forcing_parameters": {
                "qts_subdivisions": 3600 // dt,
                "dt": dt,
                "qlat_input_folder": str(HERE / info["forcing_dir"]),
                "qlat_file_pattern_filter": "*.CHRTOUT_DOMAIN1",
                "nts": hours * 3600 // dt,
                "max_loop_size": LOOP_HOURS,
            },
            "data_assimilation_parameters": {
                "streamflow_da": {"streamflow_nudging": False},
                "reservoir_da": {
                    "reservoir_persistence_da": {"reservoir_persistence_usgs": False,
                                                 "reservoir_persistence_usace": False,
                                                 "reservoir_persistence_greatLake": False},
                    "reservoir_rfc_da": {"reservoir_rfc_forecasts": False},
                },
            },
        },
    }


class Reducer:
    """Per-loop reduction of T-Route's flow/velocity/depth so memory stays bounded.

    Output step j (0-based, global) is valid at t0 + (j+1)*dt. Peak time is refined by a
    parabola through the peak step and its two neighbours (neighbours across loop
    boundaries are handled).
    """

    def __init__(self, link: np.ndarray, main: np.ndarray, dt: int):
        self.link, self.main, self.dt = link, main, dt
        self.sph = 3600 // dt
        n = len(link)
        self.n_steps = 0
        self.best_q = np.full(n, -np.inf, dtype=np.float32)
        self.best_j = np.zeros(n, dtype=np.int64)
        self.left = np.full(n, np.nan, dtype=np.float32)
        self.right = np.full(n, np.nan, dtype=np.float32)
        self.depth_pk = np.zeros(n, dtype=np.float32)
        self.vol = np.zeros(n)
        self.qmin = np.full(n, np.inf, dtype=np.float32)
        self.dmax = np.full(n, -np.inf, dtype=np.float32)
        self.prev_last = None
        self.hourly, self.main_q, self.main_d = [], [], []
        self.finite = True

    def add(self, run_results) -> None:
        idx = np.concatenate([np.asarray(r[0]) for r in run_results])
        fvd = np.concatenate([np.asarray(r[1]) for r in run_results])
        order = pd.Series(np.arange(len(idx)), index=idx).reindex(self.link)
        if order.isna().any():
            raise RuntimeError(f"{int(order.isna().sum())} segments missing from T-Route output")
        fvd = fvd[order.to_numpy().astype(int)]
        self.finite &= bool(np.isfinite(fvd).all())
        q, dep = fvd[:, 0::3], fvd[:, 2::3]
        m = q.shape[1]
        if m % self.sph:
            raise RuntimeError("loop length is not a whole number of hours")
        rows = np.arange(q.shape[0])
        pending = np.isnan(self.right) & np.isfinite(self.best_q)
        self.right[pending] = q[pending, 0]
        j = np.argmax(q, axis=1)
        qj = q[rows, j]
        upd = qj > self.best_q
        jg = self.n_steps + j
        left = np.where(j > 0, q[rows, np.maximum(j - 1, 0)],
                        self.prev_last if self.prev_last is not None else np.nan)
        right = np.where(j < m - 1, q[rows, np.minimum(j + 1, m - 1)], np.nan)
        self.best_q[upd], self.best_j[upd] = qj[upd], jg[upd]
        self.left[upd], self.right[upd] = left[upd], right[upd]
        self.depth_pk[upd] = dep[rows, j][upd]
        self.vol += q.astype(np.float64).sum(axis=1) * self.dt
        self.qmin = np.minimum(self.qmin, q.min(axis=1))
        self.dmax = np.maximum(self.dmax, dep.max(axis=1))
        self.hourly.append(q[:, self.sph - 1::self.sph].astype(np.float32))
        self.main_q.append(q[self.main].astype(np.float32))
        self.main_d.append(dep[self.main].astype(np.float32))
        self.prev_last = q[:, -1].copy()
        self.n_steps += m

    def peak_time_s(self) -> np.ndarray:
        t = (self.best_j + 1).astype(float) * self.dt
        a, b, c = self.left.astype(float), self.best_q.astype(float), self.right.astype(float)
        ok = np.isfinite(a) & np.isfinite(c)
        den = np.where(ok, a - 2 * b + c, 0.0)
        good = ok & (den < 0)
        off = np.zeros_like(t)
        off[good] = 0.5 * (a[good] - c[good]) / den[good]
        return t + np.clip(off, -0.5, 0.5) * self.dt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("dt", type=int)
    ap.add_argument("short_ts", choices=["true", "false"])
    ap.add_argument("--out", type=Path, default=None, help="output .npz (default results/runs/...)")
    args = ap.parse_args()
    short_ts = args.short_ts == "true"
    info = json.loads((INPUTS / args.case / "case.json").read_text())
    hours = int(info["hours"])
    out = (args.out or RUNS / args.case / f"dt{args.dt}_sts{int(short_ts)}.npz").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg_path = out.with_suffix(".yaml")
    cfg_path.write_text(yaml.safe_dump(config(args.case, args.dt, short_ts, hours, out.parent),
                                       sort_keys=False))

    import nwm_routing.__main__ as M  # T-Route (installed by build_troute.py)

    seg = pd.read_parquet(INPUTS / args.case / "segments.parquet")
    red = Reducer(seg["link"].to_numpy(), seg["mainstem"].to_numpy(), args.dt)
    n_loops = [0]

    def keep_results(run, run_results, *a, **k):  # replaces T-Route's output writer
        red.add(run_results)
        n_loops[0] += 1

    M.nwm_output_generator = keep_results
    t_start = time.perf_counter()
    M.main_v04(["-f", str(cfg_path)])
    wall = time.perf_counter() - t_start
    nts = red.n_steps
    if nts != hours * 3600 // args.dt:
        raise RuntimeError(f"unexpected number of timesteps {nts}")
    np.savez_compressed(
        out,
        link=red.link, dt=args.dt, short_ts=short_ts, hours=hours, n_loops=n_loops[0],
        q_hourly=np.concatenate(red.hourly, axis=1),                 # end of each hour
        peak_q=red.best_q, peak_t_s=red.peak_time_s(), peak_step=red.best_j,
        depth_at_peak=red.depth_pk, volume_m3=red.vol, q_min=red.qmin, depth_max=red.dmax,
        main_idx=np.flatnonzero(red.main),
        main_q=np.concatenate(red.main_q, axis=1), main_depth=np.concatenate(red.main_d, axis=1),
        finite=red.finite, wall_s=wall,
    )
    print(f"ok      {args.case} dt={args.dt} assume_short_ts={short_ts}: {len(red.link)} segments x "
          f"{nts} steps in {wall:.1f} s -> {out.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
