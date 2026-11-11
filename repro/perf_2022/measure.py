"""Run one command and record wall time, CPU time, and memory of its whole process tree.

AI-written (Claude, 2026-11-04); not yet reviewed by the author.

  uv run --locked python measure.py --out RUN_DIR [--interval 2] -- CMD [ARGS...]

Writes into RUN_DIR:
  stdout.log    the command's stdout and stderr (t-route prints its TIMING SUMMARY here)
  samples.csv   every --interval seconds: elapsed s, number of processes in the tree,
                summed RSS, summed PSS (Linux) or USS (macOS), summed CPU percent
  metrics.json  wall_s, exit code, user/sys CPU seconds of the tree (getrusage of reaped
                children: includes joblib/loky workers), CPU utilisation (CPU s / wall s),
                peak summed RSS and PSS/USS, largest single-process max RSS, host facts
                (CPU model, physical/logical cores, RAM), and the environment variables
                that change timings (MALLOC_ARENA_MAX, *_NUM_THREADS)

Why PSS: forked loky workers share pages with their parent, so summed RSS double counts;
PSS divides shared pages among the processes that map them (Linux only; the NGWPC
benchmark makes the same point). On macOS USS is recorded instead and is a lower bound.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

import psutil

ENV_KEYS = ["MALLOC_ARENA_MAX", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "PYTHONHASHSEED"]


def host() -> dict:
    cpu = platform.processor()
    try:
        if sys.platform == "darwin":
            cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
        else:
            for ln in Path("/proc/cpuinfo").read_text().splitlines():
                if ln.startswith("model name"):
                    cpu = ln.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return {"node": platform.node(), "system": platform.platform(), "cpu": cpu,
            "cores_physical": psutil.cpu_count(logical=False), "cores_logical": psutil.cpu_count(),
            "ram_bytes": psutil.virtual_memory().total, "python_of_tool": platform.python_version()}


def tree(p: psutil.Process) -> list[psutil.Process]:
    try:
        return [p] + p.children(recursive=True)
    except psutil.Error:
        return []


def sample(procs: list[psutil.Process]) -> tuple[int, int, int, float]:
    rss = pss = 0
    cpu = 0.0
    n = 0
    for q in procs:
        try:
            if sys.platform.startswith("linux"):
                fi = q.memory_full_info()
                rss += fi.rss
                pss += fi.pss
            else:
                mi = q.memory_info()
                rss += mi.rss
                try:
                    pss += q.memory_full_info().uss
                except psutil.Error:
                    pass
            cpu += q.cpu_percent(None)
            n += 1
        except psutil.Error:
            continue
    return n, rss, pss, cpu


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        ap.error("no command given (put it after --)")
    a.out.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT")}
    ru0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    t0 = time.perf_counter()
    peak = {"rss": 0, "pss": 0, "procs": 0}
    with open(a.out / "stdout.log", "w") as log, open(a.out / "samples.csv", "w") as smp:
        smp.write("elapsed_s,n_procs,rss_sum_bytes,pss_or_uss_sum_bytes,cpu_percent_sum\n")
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=a.out, env=env)
        ps = psutil.Process(proc.pid)
        last_beat = t0
        while proc.poll() is None:
            n, rss, pss, cpu = sample(tree(ps))
            el = time.perf_counter() - t0
            smp.write(f"{el:.1f},{n},{rss},{pss},{cpu:.0f}\n")
            peak["rss"], peak["pss"], peak["procs"] = max(peak["rss"], rss), max(peak["pss"], pss), max(peak["procs"], n)
            if el - (last_beat - t0) >= 600:
                smp.flush()
                print(f"        {el / 3600:.2f} h elapsed, {n} processes, RSS {rss / 2**30:.1f} GiB", flush=True)
                last_beat = time.perf_counter()
            time.sleep(a.interval)
        rc = proc.wait()
    wall = time.perf_counter() - t0
    ru1 = resource.getrusage(resource.RUSAGE_CHILDREN)
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes on macOS, KiB on Linux
    m = {"cmd": cmd, "exit_code": rc, "wall_s": round(wall, 3),
         "cpu_user_s": round(ru1.ru_utime - ru0.ru_utime, 3), "cpu_sys_s": round(ru1.ru_stime - ru0.ru_stime, 3),
         "peak_rss_sum_bytes": peak["rss"],
         "peak_pss_sum_bytes" if sys.platform.startswith("linux") else "peak_uss_sum_bytes": peak["pss"],
         "max_single_process_maxrss_bytes": ru1.ru_maxrss * scale, "peak_processes": peak["procs"],
         "sample_interval_s": a.interval, "host": host(),
         "memory_note": ("Linux: PSS sums shared pages once" if sys.platform.startswith("linux") else
                         "macOS: no PSS; summed RSS double counts pages shared by loky workers, and "
                         "USS of child processes is usually not readable without root (then 0)"),
         "env": {k: os.environ.get(k) for k in ENV_KEYS},
         "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    m["cpu_utilisation"] = round((m["cpu_user_s"] + m["cpu_sys_s"]) / max(wall, 1e-9), 3)
    (a.out / "metrics.json").write_text(json.dumps(m, indent=1) + "\n")
    print(f"{'ok' if rc == 0 else 'FAILED'}      exit {rc}, wall {wall:.1f} s, CPU {m['cpu_user_s'] + m['cpu_sys_s']:.1f} s, "
          f"peak RSS(sum) {peak['rss'] / 2**30:.2f} GiB -> {a.out / 'metrics.json'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
