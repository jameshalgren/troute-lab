"""Clip-and-replay test of the upstream-inflow patch.

For each case (LowerColorado_TX with recorded NWM forcing; Potomac synthetic storm) and
each assume_short_ts setting:

1. Choose two boundary segments by a fixed rule (no hand picking):
   B1 = the mainstem (longest-path) segment whose upstream segment count is closest to
        half the network;
   B2 = the largest tributary (most upstream segments) entering the mainstem below B1,
        i.e. its last segment before the junction.
   The clipped domain is every segment that is neither a boundary nor upstream of one.
2. Full run: the whole network, patched T-Route, no boundaries. Records every routing
   step for the clipped domain and the two boundaries.
3. Boundary file from the full run: each boundary's routed outflow at every routing step,
   with the restart flow at t0 (CSV for lc_nwm, NetCDF for potomac_storm), and the same
   series sampled hourly (CSV) to exercise the linear interpolation.
4. Clipped runs with each boundary file. T-Route routes only the clipped domain.
5. Compare the clipped runs with the full run on every clipped-domain segment at every
   routing step.

Extra checks (lc_nwm): the clipped run with native-step input repeated with the
by-network compute method, and with `upstream_inflow_segments` naming only B1 (the file
holds both boundaries, so B2 and its basin are routed). Both cases:  the patched full run (no boundaries) against the unpatched build's
end-of-hour flows in ../short_ts_switch/results/runs/ (if that experiment has been run).

Run files (large) go to build/runs/, not results/.

    python test_clip.py --variant corrected|unpatched [--jobs 4] [--force]

Run it with the interpreter of the matching build (run.sh: .venv for corrected,
build/venv_unpatched for unpatched). Run files go to build/runs/<variant>/, results to
results/results_<variant>.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

HERE = Path(__file__).resolve().parent
SIBLING = HERE.parent / "short_ts_switch"
INPUTS = SIBLING / "build" / "inputs"
RESULTS = HERE / "results"
DT = 300
CASES = {"lc_nwm": {"hours": 28, "native_format": "csv"},
         "potomac_storm": {"hours": 480, "native_format": "nc"}}
PEAK_FLOOR = 0.01  # m3/s: relative errors only for segments whose full-run peak exceeds this


def upstream_counts(link: np.ndarray, to: np.ndarray) -> dict[int, int]:
    """Number of segments upstream of each segment, itself included."""
    ups = defaultdict(list)
    for a, b in zip(link, to):
        ups[int(b)].append(int(a))
    n = {}
    for root in link:
        stack = [(int(root), False)]
        while stack:
            s, done = stack.pop()
            if s in n:
                continue
            if done:
                n[s] = 1 + sum(n[u] for u in ups.get(s, ()))
            else:
                stack.append((s, True))
                stack.extend((u, False) for u in ups.get(s, ()) if u not in n)
    return n, ups


def choose(case: str) -> dict:
    seg = pd.read_parquet(INPUTS / case / "segments.parquet")
    link, to = seg["link"].to_numpy(), seg["to"].to_numpy()
    n_up, ups = upstream_counts(link, to)
    total = len(seg)
    main = seg[seg["mainstem"]]
    b1 = int(main.iloc[np.argmin(np.abs(main["link"].map(n_up).to_numpy() - total / 2))]["link"])
    dist = dict(zip(seg["link"], seg["dist_to_outlet_km"]))
    main_set = set(main["link"])
    to_d = dict(zip(link.tolist(), to.tolist()))
    cands = [int(s) for s in link if s not in main_set and to_d[s] in main_set
             and dist[to_d[s]] < dist[b1]]
    b2 = max(cands, key=lambda s: n_up[s])
    domain, down_mask, n_removed = clip_domain(link, ups, to_d, [b1, b2])
    bounds = np.array([b1, b2], dtype=np.int64)
    describe = []
    for b in (b1, b2):
        d = to_d[b]
        describe.append({"segment": b, "role": "mainstem" if b in main_set else "tributary mouth",
                         "upstream_segments_incl_self": n_up[b], "drains_to": d,
                         "drains_to_n_upstreams": len(ups[d]),
                         "dist_to_outlet_km": round(float(dist[b]), 3)})
    return {"boundaries": bounds, "domain": domain, "n_total": total,
            "downstream_mask": down_mask, "n_removed": n_removed, "describe": describe,
            "link": link, "ups": ups, "to_d": to_d}


def clip_domain(link, ups, to_d, bounds):
    """Segments left after clipping at bounds, and which of them lie downstream of one."""
    removed = set()
    stack = list(bounds)
    while stack:
        s = stack.pop()
        if s not in removed:
            removed.add(s)
            stack.extend(ups.get(s, ()))
    domain = np.array(sorted(set(link.tolist()) - removed), dtype=np.int64)
    down = set()  # the only segments the boundary flow can reach
    for b in bounds:
        s = to_d[b]
        while s in to_d and s not in down:
            down.add(s)
            s = to_d[s]
    return domain, np.isin(domain, list(down)), len(removed)


def run(args: list[str], log: Path) -> None:
    with open(log, "w") as fh:
        p = subprocess.run([sys.executable, str(HERE / "run_troute.py"), *args],
                           stdout=fh, stderr=subprocess.STDOUT)
    if p.returncode:
        sys.exit(f"ERROR: run failed, see {log}")
    print(log.read_text().strip().splitlines()[-1], flush=True)


def write_inflow(case: str, q_b: np.ndarray, bounds: np.ndarray, q0: np.ndarray,
                 hours: int, out_native: Path, out_hourly: Path, fmt: str) -> None:
    info = json.loads((INPUTS / case / "case.json").read_text())
    t0 = pd.Timestamp(info["t0"])
    nts = q_b.shape[1]
    times = t0 + pd.to_timedelta(np.arange(nts + 1) * DT, unit="s")
    series = np.concatenate([q0[:, None], q_b], axis=1)  # t0 value = restart qu0
    if fmt == "nc":
        xr.Dataset(
            {"flow": (("time", "feature_id"), series.T.astype(np.float32),
                      {"units": "m3 s-1", "long_name": "outflow of upstream inflow boundary segment"})},
            coords={"time": times.values, "feature_id": bounds},
        ).to_netcdf(out_native)
    else:
        pd.DataFrame(series, index=pd.Index(bounds, name="feature_id"),
                     columns=times.strftime("%Y-%m-%d %H:%M:%S")).to_csv(out_native, float_format="%.9g")
    sph = 3600 // DT
    hourly = series[:, ::sph]  # t0, t0+1h, ...
    pd.DataFrame(hourly, index=pd.Index(bounds, name="feature_id"),
                 columns=times[::sph].strftime("%Y-%m-%d %H:%M:%S")).to_csv(out_hourly, float_format="%.9g")


def compare(full: np.ndarray, clip: np.ndarray, domain: np.ndarray, outlet: int,
            down: np.ndarray) -> dict:
    d = clip.astype(np.float64) - full.astype(np.float64)
    a = np.abs(d)
    io = int(np.flatnonzero(domain == outlet)[0])
    pf, pc = float(full[io].max()), float(clip[io].max())
    seg_max = a.max(axis=1)
    seg_peak = np.abs(full).max(axis=1).astype(np.float64)
    ok = seg_peak > PEAK_FLOOR
    rel = np.where(ok, seg_max / np.where(ok, seg_peak, 1.0), 0.0)
    worst = int(np.argmax(seg_max))
    vol_f = float(full[io].astype(np.float64).sum() * DT)
    vol_c = float(clip[io].astype(np.float64).sum() * DT)
    return {
        "segments_compared": int(full.shape[0]), "steps_compared": int(full.shape[1]),
        "bitwise_identical": bool(np.array_equal(full, clip)),
        "fraction_values_identical": float((d == 0).mean()),
        "segments_differing": int((seg_max > 0).sum()),
        "max_abs_err_m3s": float(a.max()),
        "max_rel_err": float(rel.max()),
        "rel_err_definition": "max over segments of max|clipped - full| / peak full flow, "
                              f"segments with peak > {PEAK_FLOOR} m3/s",
        "worst_segment": int(domain[worst]),
        "worst_segment_peak_full_m3s": float(seg_peak[worst]),
        "segments_not_downstream_of_a_boundary": int((~down).sum()),
        "max_abs_err_not_downstream_m3s": float(seg_max[~down].max()) if (~down).any() else 0.0,
        "outlet": {"segment": int(outlet), "peak_full_m3s": pf, "peak_clipped_m3s": pc,
                   "peak_rel_err": (pc - pf) / pf if pf else 0.0,
                   "peak_step_full": int(full[io].argmax()), "peak_step_clipped": int(clip[io].argmax()),
                   "max_abs_err_m3s": float(a[io].max()),
                   "volume_rel_err": (vol_c - vol_f) / vol_f if vol_f else 0.0},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--cases", nargs="+", default=list(CASES))
    ap.add_argument("--variant", choices=["corrected", "unpatched"], required=True)
    args = ap.parse_args()
    build_info = json.loads((HERE / "build" / args.variant / "build_info.json").read_text())
    if Path(build_info["venv"]).resolve() != Path(sys.prefix).resolve():
        sys.exit(f"ERROR: build '{args.variant}' was installed into {build_info['venv']}, "
                 f"but this interpreter is {sys.prefix}")
    runs_dir = HERE / "build" / "runs" / args.variant
    for case in args.cases:
        if not (INPUTS / case / "case.json").exists():
            sys.exit(f"ERROR: {INPUTS / case} missing; run.sh prepares it via ../short_ts_switch")
    RESULTS.mkdir(exist_ok=True)
    out = {"variant": args.variant, "dt_s": DT,
           "troute_build": {k: build_info[k] for k in
                            ("troute_repo", "troute_commit", "patch", "patch_sha256", "kernel",
                             "platform", "compilers")},
           "cases": {}}

    def go(a, log):
        if args.force or not Path(a[a.index("--out") + 1]).exists() or \
                not Path(a[a.index("--out") + 1]).with_suffix(".json").exists():
            run(a, log)
        else:
            print(f"skip    {Path(a[a.index('--out') + 1]).name} (exists)")

    for case in args.cases:
        hours, fmt = CASES[case]["hours"], CASES[case]["native_format"]
        info = json.loads((INPUTS / case / "case.json").read_text())
        sel = choose(case)
        d = runs_dir / case
        d.mkdir(parents=True, exist_ok=True)
        bounds, domain = sel["boundaries"], sel["domain"]
        # lc_nwm is small: record every segment, for the subset test below
        keep_full = (np.sort(sel["link"]).astype(np.int64) if case == "lc_nwm"
                     else np.concatenate([domain, bounds]))
        pos = pd.Index(keep_full)
        np.save(d / "keep_full.npy", keep_full)
        np.save(d / "keep_domain.npy", domain)
        restart = pd.read_pickle(INPUTS / case / "restart.pkl")
        q0 = restart["qu0"].reindex(bounds).fillna(0.0).to_numpy(np.float64)
        res = {"label": info["label"], "hours": hours, "t0": info["t0"],
               "n_segments": sel["n_total"], "boundaries": sel["describe"],
               "boundary_segments": [int(b) for b in bounds],
               "n_clipped_domain": int(len(domain)),
               "n_removed_incl_boundaries": sel["n_removed"], "runs": {}}

        # 1. full runs (both settings) in parallel
        jobs = []
        for sts in ("false", "true"):
            tag = f"sts{int(sts == 'true')}"
            jobs.append(([case, str(DT), sts, "--hours", str(hours), "--keep", str(d / "keep_full.npy"),
                          "--out", str(d / f"full_{tag}.npy")], d / f"full_{tag}.log"))
        with ThreadPoolExecutor(args.jobs) as ex:
            list(ex.map(lambda j: go(*j), jobs))

        # 2. boundary files, 3. clipped runs
        dom_b1, down_b1, _ = clip_domain(sel["link"], sel["ups"], sel["to_d"], [int(bounds[0])])
        np.save(d / "keep_domain_b1.npy", dom_b1)
        jobs = []
        for sts in ("false", "true"):
            tag = f"sts{int(sts == 'true')}"
            full = np.load(d / f"full_{tag}.npy", mmap_mode="r")
            q_b = np.asarray(full[pos.get_indexer(bounds)])
            native = d / f"inflow_native_{tag}.{fmt}"
            hourly = d / f"inflow_hourly_{tag}.csv"
            write_inflow(case, q_b, bounds, q0, hours, native, hourly, fmt)
            for kind, f in (("native", native), ("hourly", hourly)):
                jobs.append(([case, str(DT), sts, "--hours", str(hours), "--keep", str(d / "keep_domain.npy"),
                              "--out", str(d / f"clip_{kind}_{tag}.npy"), "--inflow", str(f)],
                             d / f"clip_{kind}_{tag}.log"))
            if case == "lc_nwm":
                jobs.append(([case, str(DT), sts, "--hours", str(hours), "--keep", str(d / "keep_domain.npy"),
                              "--out", str(d / f"clip_native_bynetwork_{tag}.npy"), "--inflow", str(native),
                              "--method", "by-network"], d / f"clip_native_bynetwork_{tag}.log"))
                # upstream_inflow_segments: use only the first boundary of the file
                jobs.append(([case, str(DT), sts, "--hours", str(hours), "--keep", str(d / "keep_domain_b1.npy"),
                              "--out", str(d / f"clip_native_subset_{tag}.npy"), "--inflow", str(native),
                              "--segments", str(bounds[0])], d / f"clip_native_subset_{tag}.log"))
        with ThreadPoolExecutor(args.jobs) as ex:
            list(ex.map(lambda j: go(*j), jobs))

        # 4. compare
        for sts in ("false", "true"):
            tag = f"sts{int(sts == 'true')}"
            full = np.load(d / f"full_{tag}.npy", mmap_mode="r")
            f_dom = np.asarray(full[pos.get_indexer(domain)])
            kinds = ["native", "hourly"] + (["native_bynetwork", "native_subset"] if case == "lc_nwm" else [])
            r = {}
            for kind in kinds:
                clip = np.load(d / f"clip_{kind}_{tag}.npy")
                meta = json.loads((d / f"clip_{kind}_{tag}.json").read_text())
                if kind == "native_subset":
                    r[kind] = compare(np.asarray(full[pos.get_indexer(dom_b1)]), clip, dom_b1,
                                      int(info["outlet"]), down_b1)
                    r[kind]["boundary_segments"] = [int(bounds[0])]
                    r[kind]["n_clipped_domain"] = int(len(dom_b1))
                else:
                    r[kind] = compare(f_dom, clip, domain, int(info["outlet"]), sel["downstream_mask"])
                r[kind]["n_routed_segments"] = meta["n_routed_segments"]
                r[kind]["n_loops"] = meta["n_loops"]
                r[kind]["wall_s"] = meta["wall_s"]
            fm = json.loads((d / f"full_{tag}.json").read_text())
            r["full_run"] = {"n_routed_segments": fm["n_routed_segments"], "n_loops": fm["n_loops"],
                             "wall_s": fm["wall_s"]}
            # regression: patched build, no boundaries vs ../short_ts_switch's build without the
            # patch, when that build has the same kernel (its build_info.json "kernel")
            ref = SIBLING / "results" / "runs" / case / f"dt{DT}_sts{int(sts == 'true')}.npz"
            sib = SIBLING / "build" / "build_info.json"
            sib_kernel = json.loads(sib.read_text()).get("kernel", "unpatched") if sib.exists() else None
            if sib_kernel == args.variant and ref.exists():
                z = np.load(ref)
                sph = 3600 // DT
                rpos = pd.Series(np.arange(len(z["link"])), index=z["link"]).reindex(domain).to_numpy()
                ref_q = z["q_hourly"][rpos, :hours]
                mine = f_dom[:, sph - 1::sph]
                r["no_boundary_regression_vs_unpatched"] = {
                    "reference_kernel": sib_kernel,
                    "reference": str(ref.relative_to(HERE.parent)),
                    "compared": "end-of-hour flow, clipped-domain segments",
                    "bitwise_identical": bool(np.array_equal(ref_q, mine)),
                    "max_abs_diff_m3s": float(np.abs(ref_q.astype(np.float64) - mine).max()),
                }
            else:
                r["no_boundary_regression_vs_unpatched"] = None
            res["runs"][tag] = r
            n = r["native"]
            print(f"{case} {tag}: native input max|err| = {n['max_abs_err_m3s']:.3g} m3/s "
                  f"(bitwise {n['bitwise_identical']}); hourly input max|err| = "
                  f"{r['hourly']['max_abs_err_m3s']:.3g} m3/s, outlet peak rel err "
                  f"{r['hourly']['outlet']['peak_rel_err']:.2e}", flush=True)
        out["cases"][case] = res

    (RESULTS / f"results_{args.variant}.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"ok      results/results_{args.variant}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
