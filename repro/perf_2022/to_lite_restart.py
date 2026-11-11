"""Convert a warm-start CSV (fetch_inputs.py warmstart) into a t-route "lite" channel restart.

AI-written (Claude, 2026-11-04); not yet reviewed by the author.

Run it with the Python of the t-route build that will read the file, because the restart
is a pandas pickle (a6efbf4e nhd_io.read_lite_restart / write_lite_restart: a DataFrame
indexed by segment id with columns qu0, qd0, h0 and a `time` column):

  build/era/.venv/bin/python to_lite_restart.py data/warmstart/201801010000.csv build/era/restart_201801010000.pkl
  build/current/.venv/bin/python to_lite_restart.py data/warmstart/201801010000.csv build/current/restart_201801010000.pkl

The four synthetic Great Lakes segments of the NWM 2.1 RouteLink are renamed by t-route
(id + 9.99e11, `synthetic_wb_segments` in the configs); their rows are duplicated under
the renamed id so both spellings are covered. Extra rows are harmless (t-route selects
the rows it needs with .loc).
"""
import sys
from datetime import datetime

import pandas as pd

SYNTHETIC_WB = [4800002, 4800004, 4800006, 4800007]
OFFSET = 999000000000


def main() -> int:
    src, dst = sys.argv[1], sys.argv[2]
    with open(src) as f:
        first = f.readline()
    t0 = datetime.strptime(first.split("valid ")[1].split()[0], "%Y-%m-%d_%H:%M")
    df = pd.read_csv(src, comment="#").set_index("feature_id")
    syn = df.loc[df.index.intersection(SYNTHETIC_WB)].copy()
    syn.index = syn.index + OFFSET
    df = pd.concat([df, syn]).astype("float32")
    df.index = df.index.astype("int64")
    df.index.name = None
    df["time"] = pd.Timestamp(t0)
    df.to_pickle(dst)
    print(f"ok      {dst}: {len(df)} rows, t0 {t0:%Y-%m-%d %H:%M}, pandas {pd.__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
