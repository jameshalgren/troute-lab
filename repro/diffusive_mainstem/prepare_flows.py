"""Extract NHDPlusV2 EROM mean-annual flow and velocity for every CONUS flowline.

Reads the 21 CONUS `NHDPlusV21_<DA>_<VPU>_EROMExtension_<vv>.7z` archives that
fetch_data.py downloaded into data/erom/, pulls only `EROM_MA0001.DBF` (mean annual) out
of each, and writes data/erom_ma.parquet with one row per ComID:

  comid      NHDPlusV2 COMID (= NWM v3 CONUS feature_id for NHDPlus-derived segments)
  qe_ma_cms  Q0001E, gage-adjusted mean annual flow (EROM step E), converted cfs -> m3/s
  ve_ma_ms   V0001E, mean annual velocity for Q0001E (Jobson 1996 method), ft/s -> m/s
  vpu        source vector processing unit

Field meanings and units (cfs, ft/s) follow the NHDPlusV2 User Guide (McKay et al. 2012),
EROM section; see README.md "Sources". Where a ComID appears in two VPUs (none expected)
the first is kept and the duplicate count is recorded in data/erom_ma_meta.json.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import py7zr
from dbfread import DBF

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CFS_TO_CMS = 0.028316846592      # exact: (0.3048 m)^3
FPS_TO_MS = 0.3048


def main() -> int:
    out = DATA / "erom_ma.parquet"
    archives = sorted((DATA / "erom").glob("NHDPlusV21_*_EROMExtension_*.7z"))
    archives = [a for a in archives if "_HI_" not in a.name and "_CI_" not in a.name]
    if len(archives) != 21:
        raise SystemExit(f"expected 21 CONUS EROM archives in data/erom, found {len(archives)}; run fetch_data.py")
    frames = []
    for a in archives:
        vpu = a.name.split("_")[3]
        with py7zr.SevenZipFile(a) as z:
            target = [n for n in z.getnames() if n.upper().endswith("EROM_MA0001.DBF")]
            if len(target) != 1:
                raise SystemExit(f"{a.name}: expected one EROM_MA0001.DBF, found {target}")
            tmp = Path(tempfile.mkdtemp())
            try:
                z.extract(path=tmp, targets=target)
                dbf = DBF(str(tmp / target[0]), load=False)
                rows = [(r["ComID"], r["Q0001E"], r["V0001E"]) for r in dbf]
            finally:
                shutil.rmtree(tmp)
        df = pd.DataFrame(rows, columns=["comid", "q_cfs", "v_fps"])
        df["vpu"] = vpu
        frames.append(df)
        print(f"{a.name}: {len(df):,} rows")
    df = pd.concat(frames, ignore_index=True)
    n_dup = int(df["comid"].duplicated().sum())
    df = df.drop_duplicates("comid", keep="first")
    df = pd.DataFrame({"comid": df["comid"].astype(np.int64),
                       "qe_ma_cms": df["q_cfs"].astype(np.float64) * CFS_TO_CMS,
                       "ve_ma_ms": df["v_fps"].astype(np.float64) * FPS_TO_MS,
                       "vpu": df["vpu"].astype(str)})
    df.to_parquet(out, index=False)
    meta = {"rows": int(len(df)), "duplicate_comids_dropped": n_dup,
            "archives": [a.name for a in archives],
            "fields": {"qe_ma_cms": "Q0001E (cfs) x 0.028316846592", "ve_ma_ms": "V0001E (ft/s) x 0.3048"},
            "n_q_nonpositive": int((df["qe_ma_cms"] <= 0).sum()),
            "n_v_nonpositive": int((df["ve_ma_ms"] <= 0).sum())}
    (DATA / "erom_ma_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
