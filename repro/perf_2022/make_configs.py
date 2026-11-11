"""Write one t-route configuration (YAML) plus case.json for a timing run.

AI-written (Claude, 2026-11-04); not yet reviewed by the author.

The same physical setup is written in two dialects:
  --code era      NOAA-OWP/t-route a6efbf4e (2022-02-16), V3 YAML, run with
                  `python -m nwm_routing -f -V3 config.yaml`. Keys and defaults from that
                  commit's doc/v3_doc.yaml and test/LowerColorado_TX/test_AnA.yaml.
  --code current  CIROH-UA/t-route d29f663 (ngiab), V4 YAML (pydantic troute.config), run
                  with `python -m nwm_routing -f -V4 config.yaml`. Keys as in
                  ../short_ts_switch/run_troute.py, which runs this build.

Fixed for every run (the 2022 values are unknown; these follow the team's test
configuration of that month, test_AnA.yaml at a6efbf4e):
  NWM v2.1 RouteLink, Muskingum-Cunge only (compute_kernel V02-structured), dt = 300 s,
  qts_subdivisions = 12 (hourly CHRTOUT forcing), assume_short_ts = True, no data
  assimilation, no waterbodies (break_network_at_waterbodies = False: the NWM v2.1
  LAKEPARM file was not found in a public archive, see README.md), the four synthetic
  Great Lakes segments of the NWM 2.1 RouteLink renamed as v3_doc.yaml requires for
  CONUS runs.
Variable (command-line): parallel_compute_method, cpu_pool, subnetwork_target_size,
max_loop_size (hours = files, forcing is hourly), output, start, length, domain mask,
initial state.

Example:
  uv run --locked python make_configs.py --code era --case conus_week \\
      --start 2018-01-01_00 --hours 168 --forcing-dir data/forcing/conus_slim \\
      --method by-subnetwork-jit-clustered --cpu-pool 8 --loop-hours 24 \\
      --out results/conus_week/era-original/cfg
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import netCDF4
import yaml

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PERF2022_DATA", HERE / "data")).resolve()
SYNTHETIC_WB = [4800002, 4800004, 4800006, 4800007]  # doc/v3_doc.yaml at a6efbf4e
COLUMNS = {"key": "link", "downstream": "to", "dx": "Length", "n": "n", "ncc": "nCC", "s0": "So",
           "bw": "BtmWdth", "waterbody": "NHDWaterbodyComID", "gages": "gages", "tw": "TopWdth",
           "twcc": "TopWdthCC", "musk": "MusK", "musx": "MusX", "cs": "ChSlp", "alt": "alt"}
METHODS = ["serial", "by-network", "by-subnetwork-jit", "by-subnetwork-jit-clustered"]


def build(a) -> tuple[dict, dict]:
    t0 = datetime.strptime(a.start, "%Y-%m-%d_%H")
    dt = 300
    nts = a.hours * 3600 // dt
    sn = {"geo_file_path": str(a.routelink.resolve()),
          "synthetic_wb_segments": SYNTHETIC_WB, "synthetic_wb_id_offset": 9.99e11}
    if a.mask:
        sn["mask_file_path"] = str(a.mask.resolve())
    restart = {"start_datetime": t0.strftime("%Y-%m-%d_%H:%M")}
    if a.restart:
        restart = {"lite_channel_restart_file": str(a.restart.resolve())}
    forcing = {"qts_subdivisions": 3600 // dt, "dt": dt,
               "qlat_input_folder": str(a.forcing_dir.resolve()),
               "qlat_file_pattern_filter": "*.CHRTOUT_DOMAIN1",
               "nts": nts, "max_loop_size": a.loop_hours}
    compute = {"parallel_compute_method": a.method, "compute_kernel": "V02-structured",
               "assume_short_ts": a.short_ts == "true",
               "subnetwork_target_size": a.target_size, "cpu_pool": a.cpu_pool,
               "restart_parameters": restart, "forcing_parameters": forcing}
    out = {}
    if a.output == "chrtout":   # t-route appends `streamflow_troute` to the forcing files
        out["chrtout_output"] = {"wrf_hydro_channel_output_source_folder": str(a.forcing_dir.resolve())}
    elif a.output == "lite":    # one lite restart pickle per loop (end-state check across builds)
        # relative: resolved in the run directory (run_case.sh creates it there)
        out["lite_restart"] = {"lite_restart_output_directory": "restart_out"}
    cfg = {"log_parameters": {"showtiming": True, "log_level": "INFO"},
           "network_topology_parameters": {"supernetwork_parameters": sn,
                                           "waterbody_parameters": {"break_network_at_waterbodies": False}},
           "compute_parameters": compute,
           "output_parameters": out}
    if a.code == "current":
        sn["network_type"] = "NHDNetwork"
        sn["columns"] = COLUMNS
        compute["data_assimilation_parameters"] = {
            "streamflow_da": {"streamflow_nudging": False},
            "reservoir_da": {"reservoir_persistence_da": {"reservoir_persistence_usgs": False,
                                                          "reservoir_persistence_usace": False,
                                                          "reservoir_persistence_greatLake": False},
                             "reservoir_rfc_da": {"reservoir_rfc_forecasts": False}}}
    if a.mask:
        nseg = sum(1 for ln in a.mask.read_text().splitlines() if ln.strip())
    else:
        with netCDF4.Dataset(a.routelink) as ds:
            nseg = len(ds["link"])
    case = {"case": a.case, "code": a.code, "start": t0.strftime("%Y-%m-%d_%H:%M"), "hours": a.hours,
            "dt": dt, "nts": nts, "n_segments": nseg, "segment_steps": nseg * nts,
            "method": a.method, "cpu_pool": a.cpu_pool, "loop_hours": a.loop_hours,
            "n_loops": -(-a.hours // a.loop_hours), "target_size": a.target_size,
            "short_ts": a.short_ts == "true", "output": a.output,
            "mask": a.mask.name if a.mask else None, "restart": a.restart.name if a.restart else "cold",
            "forcing_dir": str(a.forcing_dir.resolve()), "routelink": a.routelink.name,
            "entry": f"python -m nwm_routing -f -V{3 if a.code == 'era' else 4} config.yaml"}
    return cfg, case


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code", choices=["era", "current"], required=True)
    ap.add_argument("--case", required=True, help="label, e.g. conus_week, potomac_year")
    ap.add_argument("--start", default="2018-01-01_00", help="t0, YYYY-MM-DD_HH")
    ap.add_argument("--hours", type=int, required=True)
    ap.add_argument("--forcing-dir", type=Path, required=True)
    ap.add_argument("--routelink", type=Path, default=DATA / "static" / "RouteLink_CONUS_v2.1.nc")
    ap.add_argument("--mask", type=Path)
    ap.add_argument("--restart", type=Path, help="lite channel restart (to_lite_restart.py); default cold start")
    ap.add_argument("--method", choices=METHODS, default="by-subnetwork-jit-clustered")
    ap.add_argument("--cpu-pool", type=int, default=8)
    ap.add_argument("--target-size", type=int, default=10000)
    ap.add_argument("--loop-hours", type=int, default=24)
    ap.add_argument("--short-ts", choices=["true", "false"], default="true")
    ap.add_argument("--output", choices=["none", "chrtout", "lite"], default="none")
    ap.add_argument("--out", type=Path, required=True, help="directory for config.yaml + case.json")
    a = ap.parse_args()
    if not a.routelink.exists():
        sys.exit(f"ERROR: {a.routelink} not found (run fetch_inputs.py routelink)")
    a.out.mkdir(parents=True, exist_ok=True)
    cfg, case = build(a)
    (a.out / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
    (a.out / "case.json").write_text(json.dumps(case, indent=1) + "\n")
    print(f"ok      {a.out / 'config.yaml'} ({case['n_segments']} segments x {case['nts']} steps, "
          f"{case['n_loops']} loops, {a.method}, cpu_pool {a.cpu_pool})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
