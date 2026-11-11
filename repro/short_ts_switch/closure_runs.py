"""Driver for the closure diagnostics: record, compare, replay, clean up (closure.sh).

    uv run python closure_runs.py [--jobs N] [--force] [--keep]

For every case x dt x assume_short_ts (the run matrix of run_experiment.py) one job:
1. records the run twice with closure_record.py: with this directory's T-Route build
   ("patched": the corrected kernel, the build behind results/runs/ since 2026-10-09) and
   with the unpatched d29f663 kernel in build/unpatched_kernel (build_troute.py
   --kernel unpatched);
2. checks the recordings against run_troute.py's outputs (hourly flows bitwise) where
   those exist, and compares the two trajectories segment-step by segment-step;
3. replays both with closure_replay.py: the patched recording with the port's corrected
   mode (fidelity and closure diagnostics), the unpatched one with Qj_0 = 0 on entry (it
   counts the kernel calls whose outflow the unpatched kernel computed differently);
4. deletes the recordings (several GB at dt = 60 s), except the patched Potomac
   dt = 300 s pair, which closure_analyze.py uses for a float64 check; --keep keeps all.
Outputs: results/closure/<patched|unpatched>/<case>/dt<dt>_sts<0|1>.npz and
results/closure/jobs/<case>_dt<dt>_sts<0|1>.json.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_experiment import CASES, DTS, SETTINGS  # noqa: E402

UNPATCHED = HERE / "build" / "unpatched_kernel"
REC = HERE / "build" / "closure_runs"
OUT = HERE / "results" / "closure"
NUMBA = os.environ.get("NUMBA_PIN", "numba==0.61.2")
KEEP_ALWAYS = {("potomac_storm", 300, 0), ("potomac_storm", 300, 1)}


def sh(cmd: list[str], cwd: Path, log: Path, env: dict | None = None) -> None:
    with open(log, "a") as f:
        f.write("$ " + " ".join(cmd) + f"   (cwd {cwd.relative_to(HERE) if cwd != HERE else '.'})\n")
        f.flush()
        p = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env)
    if p.returncode:
        raise RuntimeError(f"failed: {' '.join(cmd)} (see {log.relative_to(HERE)})")


def compare(a: Path, b: Path, chunk: int = 2000) -> dict:
    """Patched (a) vs unpatched (b) T-Route trajectories, every segment-step."""
    qa, qb = np.load(a / "q.npy", mmap_mode="r"), np.load(b / "q.npy", mmap_mode="r")
    n1 = n3 = 0
    worst = np.zeros(qa.shape[0])
    for i in range(0, qa.shape[0], chunk):
        x, y = np.asarray(qa[i:i + chunk], dtype=np.float64), np.asarray(qb[i:i + chunk], dtype=np.float64)
        d = np.abs(x - y)
        rel = d / np.maximum(np.abs(y), 1e-3)
        n1 += int((rel > 1e-6).sum())
        n3 += int((rel > 1e-3).sum())
        worst[i:i + chunk] = d.max(axis=1) / np.maximum(y.max(axis=1), 1e-6)
    return {"segment_steps": int(qa.size), "n_rel_diff_gt_1e-6": n1, "n_rel_diff_gt_1e-3": n3,
            "max_diff_pct_of_own_peak": float(f"{100 * worst.max():.4g}"),
            "segments_diff_gt_1pct_of_peak": int((worst > 0.01).sum())}


def job(case: str, dt: int, sts: int, force: bool, keep: bool, threads: int) -> dict:
    name = f"dt{dt}_sts{sts}"
    meta_out = OUT / "jobs" / f"{case}_{name}.json"
    outs = {b: OUT / b / case / f"{name}.npz" for b in ("patched", "unpatched")}
    if meta_out.exists() and all(o.exists() for o in outs.values()) and not force:
        print(f"skip    {case} {name} (done)", flush=True)
        return json.loads(meta_out.read_text())
    log = OUT / "logs" / f"{case}_{name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")
    rec = {b: REC / b / case / name for b in ("patched", "unpatched")}
    s = "true" if sts else "false"
    sh(["uv", "run", "--locked", "python", str(HERE / "closure_record.py"), case, str(dt), s, "--out",
        str(rec["unpatched"])], UNPATCHED, log)
    sh(["uv", "run", "--locked", "python", str(HERE / "closure_record.py"), case, str(dt), s, "--out",
        str(rec["patched"])], HERE, log)
    info = {"case": case, "dt_s": dt, "assume_short_ts": bool(sts),
            "trajectory_patched_vs_unpatched": compare(rec["patched"], rec["unpatched"])}
    env = {**os.environ, "NUMBA_NUM_THREADS": str(threads)}
    refs = {"unpatched": UNPATCHED / "results" / "runs" / case / f"{name}.npz",
            "patched": HERE / "results" / "runs" / case / f"{name}.npz"}
    for b in ("patched", "unpatched"):
        cmd = ["uv", "run", "--locked", "--with", NUMBA, "python", str(HERE / "closure_replay.py"),
               str(rec[b]), str(outs[b]), "--qj0", "0"] + (["--corrected"] if b == "patched" else [])
        if refs[b].exists():
            cmd += ["--compare-npz", str(refs[b])]
        sh(cmd, HERE, log, env)
        info[f"record_meta_{b}"] = json.loads((rec[b] / "meta.json").read_text())
    if not keep:
        for b in ("unpatched", "patched"):
            if not (b == "patched" and (case, dt, sts) in KEEP_ALWAYS):
                shutil.rmtree(rec[b])
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    meta_out.write_text(json.dumps(info, indent=1) + "\n")
    print(f"ok      {case} {name}: trajectories patched vs unpatched differ (rel > 1e-3) in "
          f"{info['trajectory_patched_vs_unpatched']['n_rel_diff_gt_1e-3']} segment-steps", flush=True)
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep every recording (about 60 GB)")
    args = ap.parse_args()
    for d, want in ((HERE, "corrected"), (UNPATCHED, "unpatched")):
        info = d / "build" / "build_info.json"
        if not info.exists() or json.loads(info.read_text()).get("kernel") != want:
            sys.exit(f"ERROR: {d / 'build'} is not a '{want}'-kernel T-Route build (closure.sh builds both)")
    todo = [(c, dt, int(s == "true")) for dt in sorted(DTS) for c in CASES for s in SETTINGS]
    threads = max(1, (os.cpu_count() or 4) // args.jobs)
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        list(ex.map(lambda t: job(*t, args.force, args.keep, threads), todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
