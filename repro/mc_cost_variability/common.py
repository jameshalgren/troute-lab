"""Shared paths, scenarios and case loading for the MC cost-variability experiment.

The Potomac case is the one of ../short_ts_switch (README "Design", case potomac_storm):
all 16,454 segments upstream of NWM v3.1.7 feature 4539621, synthetic storm, 40 days,
dt = 300 s. Its inputs are rebuilt here with ../short_ts_switch/make_inputs.py, imported
read-only (its functions are called with this experiment's paths; nothing is written
into ../short_ts_switch). Only the storm depth changes between scenarios.

Import this module before numba: it points NUMBA_CACHE_DIR at build/numba_cache so that
the read-only import of ../short_ts_switch/closure_port.py (numba cache=True) does not
write a cache next to that file.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STS_DIR = HERE.parent / "short_ts_switch"
DATA = HERE / "data"
BUILD = HERE / "build"
RESULTS = HERE / "results"
TABLES = HERE / "tables"
CASE_DIR = DATA / "inputs" / "potomac"

os.environ.setdefault("NUMBA_CACHE_DIR", str(BUILD / "numba_cache"))
sys.dont_write_bytecode = True            # no __pycache__ next to the read-only imports
if str(STS_DIR) not in sys.path:
    sys.path.append(str(STS_DIR))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# NWM v3.1.7 RouteLink_CONUS.nc: URL, SHA-256 and size as pinned in
# ../short_ts_switch/fetch_data.py (ROUTELINK) and ../network_stats/fetch_data.py.
ROUTELINK_URL = "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/parm/domain/RouteLink_CONUS.nc"
ROUTELINK_SHA256 = "4957655896f4f27854f893d02fa084f9f79c1cf8e80ce77565a7356dadb6fc0e"
ROUTELINK_CANDIDATES = [DATA / "RouteLink_CONUS.nc",
                        HERE.parent / "network_stats" / "data" / "RouteLink_CONUS.nc",
                        STS_DIR / "data" / "RouteLink_CONUS.nc"]

DT = 300                                  # s, NWM channel timestep (T-Route default dt)
HOURS = 40 * 24                           # the potomac_storm run length
QTS = 3600 // DT                          # qts_subdivisions: routing steps per forcing hour
NTS = HOURS * 3600 // DT                  # 11,520 steps
T_ACC0 = QTS                              # statistics start after the first hour (as closure_replay.py:
                                          # T-Route's lite restart starts every depth at h0 = 0)

# Scenarios: storm runoff depth (mm), same gamma shape / timing / baseflow as make_inputs.py.
# "calm" is the baseflow alone (no storm): the steady state the storm runs start from.
SCENARIOS = {
    "calm":    {"storm_mm": 0.0,   "sts": True},
    "s25":     {"storm_mm": 25.0,  "sts": True},     # the existing potomac_storm forcing
    "s100":    {"storm_mm": 100.0, "sts": True},
    "s250":    {"storm_mm": 250.0, "sts": True},
    "s25_f":   {"storm_mm": 25.0,  "sts": False},    # assume_short_ts = False (check)
    "s250_f":  {"storm_mm": 250.0, "sts": False},
}
PRIMARY = ["calm", "s25", "s100", "s250"]

# T-Route chunk windows (routing steps per subnetwork call). compute_network_structured
# runs `while timestep < nsteps+1: for i in range(num_reaches)` (mc_reach.pyx L502-503 @
# d29f663), i.e. every unit is called once per forcing loop for all of the loop's steps;
# the loop is max_loop_size hours (ForcingParameters default 24 h, compute_parameters.py
# L445 @ d29f663; also the value ../short_ts_switch/run_troute.py sets).
WINDOWS = {"1h": QTS, "3h": 3 * QTS, "24h": 24 * QTS, "run": NTS}
PRIMARY_WINDOW = "24h"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def routelink_path() -> Path:
    for p in ROUTELINK_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit("RouteLink_CONUS.nc not found; run fetch_data.py")


def load_case() -> dict:
    """Arrays of the Potomac case written by make_case.py (segment order = RouteLink subset order)."""
    d = {k: np.load(CASE_DIR / f"{k}.npy") for k in
         ("link", "params", "up_ptr", "up_idx", "topo", "q0_base", "length_km")}
    d["seg"] = pd.read_parquet(CASE_DIR / "segments.parquet")
    d["info"] = json.loads((CASE_DIR / "case.json").read_text())
    return d


def storm_qlat(length_km: np.ndarray, storm_mm: float) -> np.ndarray:
    """Hour-averaged lateral inflow (float32, nseg x HOURS) from make_inputs.storm_series,
    with STORM_MM set to storm_mm for the call."""
    import make_inputs as MI                 # ../short_ts_switch, read-only
    old = MI.STORM_MM
    try:
        MI.STORM_MM = float(storm_mm)
        return MI.storm_series(np.asarray(length_km, dtype=float), HOURS)
    finally:
        MI.STORM_MM = old


def run_dir(name: str) -> Path:
    return RESULTS / "runs" / name
