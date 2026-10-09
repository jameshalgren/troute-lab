"""Run the full matrix: case x dt x assume_short_ts, each run in a fresh process.

    uv run python run_experiment.py              # all runs (skips runs already done)
    uv run python run_experiment.py --force      # rerun everything
    uv run python run_experiment.py --jobs 2     # parallel processes (default 4)
    uv run python run_experiment.py --rerun DIR  # repeat the check runs into DIR (check.py)

dt = 60 s is the small-dt end. Note (see README): the two settings do NOT converge to
the same solution as dt -> 0; False converges to the Muskingum ODE, True to a cascade of
linear reservoirs with constant K(1 - X).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "results" / "runs"

CASES = ["lc_nwm", "potomac_storm"]
DTS = [60, 300, 900, 3600]           # s; 300 s is the NWM / T-Route default
SETTINGS = ["true", "false"]
# Repeated by run.sh into results/rerun/ for check.py's bitwise self-consistency test.
CHECK_RUNS = [("lc_nwm", 300, "true"), ("lc_nwm", 300, "false"),
              ("potomac_storm", 300, "true"), ("potomac_storm", 300, "false")]


def one(case: str, dt: int, sts: str, out: Path) -> tuple[str, int, str]:
    log = out.with_suffix(".log")
    with open(log, "w") as f:
        p = subprocess.run([sys.executable, str(HERE / "run_troute.py"), case, str(dt), sts,
                            "--out", str(out)], stdout=f, stderr=subprocess.STDOUT, cwd=HERE)
    last = log.read_text().strip().splitlines()[-1:] or [""]
    status = last[0] if p.returncode == 0 else f"FAILED ({p.returncode}); see {log.relative_to(HERE)}"
    print(status, flush=True)
    return case, dt, sts if p.returncode == 0 else "FAILED"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--rerun", type=Path, default=None)
    args = ap.parse_args()
    todo = []
    if args.rerun:
        args.rerun = args.rerun.resolve()
        for case, dt, sts in CHECK_RUNS:
            out = args.rerun / case / f"dt{dt}_sts{int(sts == 'true')}.npz"
            out.parent.mkdir(parents=True, exist_ok=True)
            todo.append((case, dt, sts, out))
    else:
        for case in CASES:
            for dt in sorted(DTS):
                for sts in SETTINGS:
                    out = RUNS / case / f"dt{dt}_sts{int(sts == 'true')}.npz"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    if out.exists() and not args.force:
                        print(f"skip    {out.relative_to(HERE)} (exists)")
                        continue
                    todo.append((case, dt, sts, out))
    # largest runs first so the pool stays busy
    todo.sort(key=lambda t: t[1])
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        res = list(ex.map(lambda t: one(*t), todo))
    failed = [r for r in res if r[2] == "FAILED"]
    if failed:
        print(f"ERROR: {len(failed)} runs failed: {failed}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
