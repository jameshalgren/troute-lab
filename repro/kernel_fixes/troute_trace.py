"""Run T-Route once (run_troute.py) with an instrumented kernel and save the event counts.

    uv run python troute_trace.py <case> <dt> <true|false> --out RUN.npz

Runs in a working copy of ../short_ts_switch whose T-Route was built with
`build_troute.py --kernel trace-L<k>` (troute_compare.sh). The instrumented kernel keeps
cumulative counters in the Fortran module variable kernel_trace::ev(9) (int64), linked into
T-Route's reach extension; after the run they are read through ctypes and written
to RUN.events.json (meanings in harness/driver.F90; ev(8) counts Secant iterations, ev(9) collapsed-search restarts).
"""
from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path.cwd()
sys.path.insert(0, str(HERE))
import run_troute  # noqa: E402  (the working copy's)

NAMES = ["lastpass_converged", "negative_step", "degenerate_slope", "retry", "abandoned",
         "loop_skipped_after_retry", "no_flow", "iterations", "collapse_restart"]


def main() -> int:
    out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    rc = run_troute.main()
    import troute.routing.fast_reach.reach as kr   # the extension that links the kernel
    lib = ctypes.CDLL(kr.__file__)
    ev = (ctypes.c_int64 * 9).in_dll(lib, "__kernel_trace_MOD_ev")
    d = np.load(out)
    calls = int(d["link"].size) * int(d["hours"]) * 3600 // int(d["dt"])
    res = {"kernel_calls": calls, "events": {k: int(v) for k, v in zip(NAMES, ev)},
           "note": "occurrence counts over all kernel calls; calls = segments x steps "
                   "(waterbodies are routed as channels, so every segment is an MC call)"}
    out.with_suffix(".events.json").write_text(json.dumps(res, indent=1) + "\n")
    print("ok      events", res["events"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
