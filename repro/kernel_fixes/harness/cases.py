"""Deterministic input sweep for the MC kernel test driver (driver.f90).

    python harness/cases.py OUT.bin [--random N] [--seed S]

Writes int32 n, then n float32 records in the kernel's argument order
(dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, velp, depthp) and, beside it,
OUT.json with the column names and the counts of each part.

Part A, structured (16,128 cases): 9 channels (NWM-like headwater, mid-size, large
slope-floor, Potomac-estuary-like, steep, TwCC = 0 (the NWM 3.0 exception), Bw > Tw,
cs = 0, and Wlostowski's 2020 courant_test channel) x dt in {60, 300, 900, 3600} s x
8 flow scales x 8 flow patterns (steady, sharp rise, fall, lateral only, headwater with
previous outflow, recession, negative lateral inflow, no flow) x 7 antecedent depths
(0 to 20 x bankfull). Part B, random (default 30,000): channel parameters log-uniform over
NWM-like ranges, flows log-uniform with random zeros, antecedent depth 0-10 x bankfull.
velp is always 0, as T-Route passes it (mc_reach.pyx, buf_view[:, 11] = 0.0).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

COLS = ["dt", "qup", "quc", "qdp", "ql", "dx", "bw", "tw", "twcc", "n", "ncc", "cs", "s0",
        "velp", "depthp"]

# dx, bw, tw, twcc, n, ncc, cs, s0
CHANNELS = {
    "headwater":        (1500.0, 2.0, 3.3, 9.9, 0.06, 0.12, 0.6, 5e-3),
    "midsize":          (3000.0, 15.0, 25.0, 75.0, 0.05, 0.10, 0.4, 8e-4),
    "large_slopefloor": (4000.0, 60.0, 100.0, 300.0, 0.04, 0.08, 0.3, 1e-5),
    "estuary_like":     (3300.0, 120.0, 264.0, 792.0, 0.035, 0.07, 0.2, 1e-5),
    "steep":            (500.0, 5.0, 8.0, 24.0, 0.07, 0.14, 0.8, 5e-2),
    "twcc_zero":        (2000.0, 10.0, 16.0, 0.0, 0.05, 0.10, 0.5, 1e-3),
    "bw_gt_tw":         (2000.0, 20.0, 15.0, 45.0, 0.05, 0.10, 0.5, 1e-3),
    "cs_zero":          (1000.0, 8.0, 12.0, 36.0, 0.05, 0.10, 0.0, 2e-3),
    "wlostowski2020":   (2000.0, 50.0, 100.0, 500.6, 0.028, 0.03136, 0.42, 8e-3),
}
DTS = (60.0, 300.0, 900.0, 3600.0)
QSCALES = (0.0, 1e-3, 0.1, 1.0, 10.0, 100.0, 1000.0, 5000.0)
# multipliers of the flow scale: qup, quc, qdp, ql
PATTERNS = {
    "steady": (1.0, 1.0, 1.0, 0.0),
    "rise_sharp": (0.1, 1.0, 0.1, 0.0),
    "fall": (1.0, 0.1, 1.0, 0.0),
    "lateral_only": (0.0, 0.0, 0.0, 1.0),
    "headwater_prev": (0.0, 0.0, 1.0, 0.1),
    "recession": (0.5, 0.4, 1.0, 0.01),
    "negative_ql": (1.0, 1.0, 1.0, -0.5),
    "no_flow": (0.0, 0.0, 0.0, 0.0),
}
DEPTH_X_BANKFULL = (0.0, 0.01, 0.3, 1.0, 1.5, 5.0, 20.0)


def bankfull(bw: float, tw: float, cs: float) -> float:
    z = 1.0 if cs == 0.0 else 1.0 / cs
    if bw > tw:
        return min(bw / 1e-5, 50.0)  # the kernel's "infinitely deep" case; cap the seed depth
    if bw == tw:
        return bw / (2.0 * z)
    return (tw - bw) / (2.0 * z)


def structured() -> np.ndarray:
    rows = []
    for (dx, bw, tw, twcc, n, ncc, cs, s0) in CHANNELS.values():
        bfd = bankfull(bw, tw, cs)
        for dt in DTS:
            for q in QSCALES:
                for (a, b, c, d) in PATTERNS.values():
                    for m in DEPTH_X_BANKFULL:
                        rows.append([dt, a * q, b * q, c * q, d * q, dx, bw, tw, twcc, n, ncc,
                                     cs, s0, 0.0, m * bfd])
    return np.asarray(rows, dtype=np.float64)


def random_part(n: int, seed: int) -> np.ndarray:
    r = np.random.default_rng(seed)

    def logu(lo, hi, size):
        return np.exp(r.uniform(np.log(lo), np.log(hi), size))

    dt = r.choice(DTS, n)
    dx = logu(50.0, 20000.0, n)
    bw = logu(0.5, 300.0, n)
    tw = bw * r.uniform(1.05, 2.5, n)
    twcc = tw * r.choice([0.0, 2.0, 3.0, 5.0], n, p=[0.05, 0.15, 0.7, 0.1])
    nman = logu(0.02, 0.15, n)
    ncc = nman * r.choice([1.0, 2.0, 3.0], n, p=[0.1, 0.8, 0.1])
    cs = logu(0.05, 2.0, n)
    s0 = logu(1e-5, 0.1, n)
    s0[r.random(n) < 0.1] = 1e-5  # RouteLink's slope floor
    qs = logu(1e-4, 2e4, n)
    qup = qs * logu(0.05, 20.0, n) * (r.random(n) > 0.2)
    quc = qs * logu(0.05, 20.0, n) * (r.random(n) > 0.2)
    qdp = qs * logu(0.05, 20.0, n) * (r.random(n) > 0.1)
    ql = qs * logu(1e-4, 1.0, n) * (r.random(n) > 0.3)
    ql[r.random(n) < 0.02] *= -1.0
    z = 1.0 / cs
    bfd = (tw - bw) / (2.0 * z)
    depthp = bfd * r.uniform(0.0, 10.0, n) * (r.random(n) > 0.05)
    out = np.column_stack([dt, qup, quc, qdp, ql, dx, bw, tw, twcc, nman, ncc, cs, s0,
                           np.zeros(n), depthp])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--random", type=int, default=30000)
    ap.add_argument("--seed", type=int, default=20261009)
    args = ap.parse_args()
    a = structured()
    b = random_part(args.random, args.seed)
    allc = np.vstack([a, b]).astype(np.float32)
    assert np.all(np.isfinite(allc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "wb") as f:
        np.asarray([allc.shape[0]], dtype=np.int32).tofile(f)
        allc.tofile(f)
    meta = {"columns": COLS, "n": int(allc.shape[0]), "n_structured": int(a.shape[0]),
            "n_random": int(b.shape[0]), "seed": args.seed,
            "channels": list(CHANNELS), "patterns": list(PATTERNS), "dts": list(DTS),
            "qscales": list(QSCALES), "depth_x_bankfull": list(DEPTH_X_BANKFULL)}
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"ok      {allc.shape[0]} cases -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
