"""Run T-Route once and keep everything needed to replay every MC kernel call.

    uv run python closure_record.py <case> <dt> <true|false> --out DIR

Same configuration and entry point as run_troute.py (T-Route's V4 `main_v04`, NHDNetwork,
MC V02-structured, serial). Two interceptions, neither of which changes the routing:
- `nwm_output_generator` (T-Route's writer) is replaced by a collector that writes the
  native-resolution flow and depth of every segment at every step into float32 arrays;
- `nwm_route` is wrapped to record the inputs T-Route passes to the MC computation in
  each forcing loop: the channel parameters (`param_df`), the upstream connections
  (`upstream_connections`, in T-Route's order, which sets the float32 summation order of
  junction inflows), the loop's initial state (`q0`: qu0, qd0, h0) and the lateral
  inflows (`qlats`).

Writes to DIR: q.npy and h.npy (nseg x nts, float32; step j is valid at t0 + (j+1) dt),
qlat.npy (nseg x hours, float32, as T-Route used it), q0.npy and h0.npy (initial state of
the first loop), params.npy (nseg x 8: dx, bw, tw, twcc, n, ncc, cs, s0, float32),
up_ptr.npy / up_idx.npy (upstream connections as CSR, positions in `link` order),
link.npy, and meta.json (including a check that each later loop started from the
previous loop's last flow and depth, which closure_replay.py relies on). Used by
closure.sh for the closure diagnostics (README "Closure diagnostics on the network").
"""
from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_troute as RT  # noqa: E402

PCOLS = ["dx", "bw", "tw", "twcc", "n", "ncc", "cs", "s0"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case")
    ap.add_argument("dt", type=int)
    ap.add_argument("short_ts", choices=["true", "false"])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    short_ts = args.short_ts == "true"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    info = json.loads((RT.INPUTS / args.case / "case.json").read_text())
    hours = int(info["hours"])
    nts = hours * 3600 // args.dt
    cfg_path = out / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(RT.config(args.case, args.dt, short_ts, hours, out), sort_keys=False))

    import nwm_routing.__main__ as M  # T-Route (installed by build_troute.py)

    seg = pd.read_parquet(RT.INPUTS / args.case / "segments.parquet")
    link = seg["link"].to_numpy()
    nseg = len(link)
    pos = pd.Series(np.arange(nseg), index=link)
    Q = np.lib.format.open_memmap(out / "q.npy", mode="w+", dtype=np.float32, shape=(nseg, nts))
    H = np.lib.format.open_memmap(out / "h.npy", mode="w+", dtype=np.float32, shape=(nseg, nts))
    st = {"j": 0, "loops": [], "qlat": [], "first": None}

    orig_route = M.nwm_route
    sig = inspect.signature(orig_route)

    def route(*a, **k):
        b = sig.bind(*a, **k)
        q0 = b.arguments["q0"].reindex(link)
        ql = b.arguments["qlats"].reindex(link)
        if q0.isna().any().any() or ql.isna().any().any():
            raise RuntimeError("q0 or qlats does not cover every segment")
        nts_loop = int(b.arguments["nts"])
        qts = int(b.arguments["qts_subdivisions"])
        st["qlat"].append(ql.to_numpy(dtype=np.float32)[:, : nts_loop // qts])
        q0v = q0[["qu0", "qd0", "h0"]].to_numpy(dtype=np.float32)
        loop = {"start_step": st["j"], "nts": nts_loop, "qts_subdivisions": qts,
                "qlat_columns_given": int(ql.shape[1])}
        if st["first"] is None:
            p = b.arguments["param_df"].reindex(link)[PCOLS].astype("float32")
            up = b.arguments["upstream_connections"]
            ptr, idx = [0], []
            for l in link:
                idx.extend(int(pos[u]) for u in up.get(l, ()))
                ptr.append(len(idx))
            np.save(out / "params.npy", p.to_numpy())
            np.save(out / "up_ptr.npy", np.array(ptr, dtype=np.int64))
            np.save(out / "up_idx.npy", np.array(idx, dtype=np.int64))
            np.save(out / "q0.npy", q0v[:, 0])
            np.save(out / "h0.npy", q0v[:, 2])
            st["first"] = {"qu0_equals_qd0": bool(np.array_equal(q0v[:, 0], q0v[:, 1]))}
        else:
            j = st["j"]
            loop["starts_from_previous_last_step"] = bool(
                np.array_equal(q0v[:, 0], Q[:, j - 1]) and np.array_equal(q0v[:, 1], Q[:, j - 1])
                and np.array_equal(q0v[:, 2], H[:, j - 1]))
        st["loops"].append(loop)
        return orig_route(*a, **k)

    def collect(run, run_results, *a, **k):  # replaces T-Route's output writer
        idx = np.concatenate([np.asarray(r[0]) for r in run_results])
        fvd = np.concatenate([np.asarray(r[1]) for r in run_results])
        order = pd.Series(np.arange(len(idx)), index=idx).reindex(link)
        if order.isna().any():
            raise RuntimeError("segments missing from T-Route output")
        fvd = fvd[order.to_numpy().astype(int)]
        m = fvd.shape[1] // 3
        j = st["j"]
        Q[:, j:j + m] = fvd[:, 0::3]
        H[:, j:j + m] = fvd[:, 2::3]
        st["j"] = j + m

    M.nwm_route = route
    M.nwm_output_generator = collect
    t0 = time.perf_counter()
    M.main_v04(["-f", str(cfg_path)])
    wall = time.perf_counter() - t0
    if st["j"] != nts:
        raise RuntimeError(f"recorded {st['j']} of {nts} steps")
    Q.flush()
    H.flush()
    qlat = np.concatenate(st["qlat"], axis=1)
    np.save(out / "qlat.npy", qlat)
    np.save(out / "link.npy", link)
    meta = {"case": args.case, "dt_s": args.dt, "assume_short_ts": short_ts, "hours": hours, "nts": nts,
            "nseg": nseg, "qts_subdivisions": 3600 // args.dt, "qlat_hours": int(qlat.shape[1]),
            "loops": st["loops"], **st["first"], "finite": bool(np.isfinite(Q).all() and np.isfinite(H).all()),
            "wall_s": round(wall, 1)}
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"ok      recorded {args.case} dt={args.dt} assume_short_ts={short_ts}: {nseg} x {nts} in {wall:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
