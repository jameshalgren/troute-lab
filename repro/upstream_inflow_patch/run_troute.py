"""Run the patched T-Route once and keep native-resolution flows of chosen segments.

T-Route does the routing through its normal V4 entry point
(`nwm_routing.__main__.main_v04(["-f", <yaml>])`). As in repro/short_ts_switch, the only
intervention is that the output writer `nwm_output_generator` is replaced by a collector.
The collector writes the flow at every routing step for the segments listed in --keep
to an .npy file, shape [len(keep), nts], float32 (step j is valid at t0 + (j+1)*dt).

The configuration is the one of repro/short_ts_switch/run_troute.py (NHDNetwork from the
case's RouteLink subset, MC V02-structured, serial compute, waterbodies not broken out,
no DA, 24-h forcing loops, lite restart), plus, with --inflow, the patch's
`forcing_parameters.upstream_inflow_file`. Inputs are read from
../short_ts_switch/build/inputs/<case>/ (made by that experiment's make_inputs.py).

    python run_troute.py <case> <dt> <true|false> --hours H --keep keep.npy --out q.npy
                         [--inflow boundary_inflow.csv|.nc] [--method serial|by-network]
                         [--segments ID ...]
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
SIBLING = HERE.parent / "short_ts_switch"
INPUTS = SIBLING / "build" / "inputs"
LOOP_HOURS = 24

COLUMNS = {"key": "link", "downstream": "to", "dx": "Length", "n": "n", "ncc": "nCC", "s0": "So",
           "bw": "BtmWdth", "waterbody": "NHDWaterbodyComID", "gages": "gages", "tw": "TopWdth",
           "twcc": "TopWdthCC", "musk": "MusK", "musx": "MusX", "cs": "ChSlp", "alt": "alt"}


def config(case: str, dt: int, short_ts: bool, hours: int, inflow: Path | None,
           method: str, segments: list[int] | None = None) -> dict:
    d = INPUTS / case
    info = json.loads((d / "case.json").read_text())
    if 3600 % dt:
        raise ValueError("dt must divide 3600 (hourly forcing)")
    forcing = {
        "qts_subdivisions": 3600 // dt,
        "dt": dt,
        "qlat_input_folder": str(SIBLING / info["forcing_dir"]),
        "qlat_file_pattern_filter": "*.CHRTOUT_DOMAIN1",
        "nts": hours * 3600 // dt,
        "max_loop_size": LOOP_HOURS,
    }
    if inflow is not None:
        forcing["upstream_inflow_file"] = str(inflow)   # the patch's new key
    if segments:
        forcing["upstream_inflow_segments"] = [int(s) for s in segments]  # optional subset
    return {
        "log_parameters": {"showtiming": False, "log_level": "WARNING"},
        "network_topology_parameters": {
            "supernetwork_parameters": {"geo_file_path": str(d / "RouteLink.nc"),
                                        "network_type": "NHDNetwork", "columns": COLUMNS},
            "waterbody_parameters": {"break_network_at_waterbodies": False},
        },
        "compute_parameters": {
            "parallel_compute_method": method,
            "compute_kernel": "V02-structured",
            "assume_short_ts": bool(short_ts),
            "subnetwork_target_size": 10000,
            "cpu_pool": 1,
            "restart_parameters": {"lite_channel_restart_file": str(d / "restart.pkl")},
            "forcing_parameters": forcing,
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("dt", type=int)
    ap.add_argument("short_ts", choices=["true", "false"])
    ap.add_argument("--hours", type=int, required=True)
    ap.add_argument("--keep", type=Path, required=True, help=".npy of segment IDs to record")
    ap.add_argument("--out", type=Path, required=True, help="output .npy [len(keep), nts]")
    ap.add_argument("--inflow", type=Path, default=None, help="upstream inflow file (patch)")
    ap.add_argument("--method", default="serial", choices=["serial", "by-network"])
    ap.add_argument("--segments", type=int, nargs="+", default=None,
                    help="upstream_inflow_segments (default: every segment in the file)")
    args = ap.parse_args()
    short_ts = args.short_ts == "true"
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg_path = out.with_suffix(".yaml")
    cfg_path.write_text(yaml.safe_dump(
        config(args.case, args.dt, short_ts, args.hours,
               args.inflow.resolve() if args.inflow else None, args.method, args.segments),
        sort_keys=False))

    import nwm_routing.__main__ as M  # patched T-Route (build_patched.py)

    keep = np.load(args.keep)
    nts = args.hours * 3600 // args.dt
    q = np.lib.format.open_memmap(out, mode="w+", dtype=np.float32, shape=(len(keep), nts))
    state = {"j": 0, "n_routed": None, "loops": 0}

    def keep_results(run, run_results, *a, **k):  # replaces T-Route's output writer
        idx = np.concatenate([np.asarray(r[0]) for r in run_results])
        fvd = np.concatenate([np.asarray(r[1]) for r in run_results])
        if len(np.unique(idx)) != len(idx):
            raise RuntimeError("duplicate segments in T-Route output")
        pos = pd.Series(np.arange(len(idx)), index=idx).reindex(keep)
        if pos.isna().any():
            raise RuntimeError(f"{int(pos.isna().sum())} kept segments missing from T-Route output")
        flow = fvd[pos.to_numpy().astype(int)][:, 0::3]
        m = flow.shape[1]
        q[:, state["j"]:state["j"] + m] = flow
        state["j"] += m
        state["n_routed"] = len(idx)
        state["loops"] += 1

    M.nwm_output_generator = keep_results
    t_start = time.perf_counter()
    M.main_v04(["-f", str(cfg_path)])
    wall = time.perf_counter() - t_start
    q.flush()
    if state["j"] != nts:
        raise RuntimeError(f"expected {nts} steps, got {state['j']}")
    meta = {"case": args.case, "dt": args.dt, "short_ts": short_ts, "hours": args.hours,
            "nts": nts, "inflow": args.inflow.name if args.inflow else None,
            "method": args.method, "segments": args.segments, "n_routed_segments": state["n_routed"],
            "n_loops": state["loops"], "wall_s": round(wall, 2)}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"ok      {args.case} dt={args.dt} short_ts={short_ts} inflow={meta['inflow']}: "
          f"{state['n_routed']} routed segments, {nts} steps, {wall:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
