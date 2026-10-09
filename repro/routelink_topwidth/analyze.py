"""Check how TopWdthCC (compound-channel top width) relates to TopWdth and
other channel parameters in the NWM v3.1.6 RouteLink files.

First run 2026-10-01/02 as a standalone script, moved here 2026-10-05 with the printed
report unchanged; in addition the key numbers are
written to results/results.json for check.py, plus results/report.txt and
results/provenance.json.

Usage (from this directory; run.sh does all of this):
    uv run python analyze.py                      # all four domains in data/
    uv run python analyze.py data/RouteLink_HI.nc # selected files
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)
RTOL = 1e-4
VARS = ["TopWdth", "TopWdthCC", "BtmWdth", "ChSlp", "n", "nCC", "order"]


def hdr(s):
    print(f"\n### {s}")


HERE = Path(__file__).resolve().parent
DOMAINS = ["CONUS", "AK", "HI", "PRVI"]
# The CONUS floors reported by the first analysis (2026-10-01/02); tested explicitly below
# (in addition to the floors inferred from the data).
REPORTED_FLOORS = {2: 10.0, 3: 30.0, 4: 50.0, 5: 70.0, 6: 80.0, 8: 150.0}


def analyze(path):
    R = {}  # machine-readable results
    ds = xr.open_dataset(path)
    df = pd.DataFrame({k: ds[k].values for k in VARS if k in ds})
    N = len(df)
    print(f"\n{'=' * 70}\n{path}: {N:,} reaches")
    tw, cc = df.TopWdth.astype("f8"), df.TopWdthCC.astype("f8")
    tw3 = 3 * tw
    is3 = np.isclose(cc, tw3, rtol=RTOL)
    R["n_reaches"] = int(N)
    R["n_TopWdthCC_eq_3TopWdth"] = int(is3.sum())
    R["pct_TopWdthCC_eq_3TopWdth"] = float(100 * is3.mean())

    hdr("TopWdthCC == 3*TopWdth (rtol 1e-4)")
    print(f"match: {is3.sum():,} ({100 * is3.mean():.3f}%)   mismatch: {(~is3).sum():,}")

    hdr("Most common TopWdthCC values (all / among mismatches)")
    print(cc.round(3).value_counts().head(10).to_string())
    print("-- mismatches:")
    print(cc[~is3].round(3).value_counts().head(15).to_string())

    hdr("Ratio TopWdthCC/TopWdth quantiles")
    q = [0, 0.001, 0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 0.999, 1]
    print((cc / tw).quantile(q).to_string())

    hdr("Rule: TopWdthCC = max(3*TW, c) for a single constant c")
    for c in [0, 5, 10, 20, 30, 50]:
        ok = np.isclose(cc, np.maximum(tw3, c), rtol=RTOL)
        print(f"c={c:>3}: match {ok.sum():,} ({100 * ok.mean():.3f}%)")

    if "order" in df:
        hdr("Mismatch constant values by stream order (crosstab)")
        print(pd.crosstab(cc[~is3].round(3), df.order[~is3]).to_string())

        hdr("Per-order summary: n, share == 3TW, min/median 3TW among 3TW matches")
        g = pd.DataFrame({"order": df.order, "is3": is3, "tw3": tw3, "cc": cc})
        summ = g.groupby("order").agg(
            n=("is3", "size"),
            pct_3TW=("is3", lambda s: 100 * s.mean()),
            min_cc=("cc", "min"),
        )
        summ["min_3TW_when_match"] = g[g.is3].groupby("order").tw3.min()
        summ["floor_const"] = g[~g.is3].groupby("order").cc.agg(
            lambda s: ",".join(f"{v:g}" for v in sorted(s.round(3).unique())))
        print(summ.to_string())

        # Infer per-order floor = most common non-3TW value where that value exceeds 3TW
        # (orders >= 2; order 1 has only 2 stray non-3TW reaches).
        low = (~g.is3) & (g.cc > g.tw3) & (g.order >= 2)
        floors = g[low].groupby("order").cc.agg(lambda s: float(s.round(3).mode().iloc[0])).to_dict()
        hdr(f"Rule: TopWdthCC = max(3*TW, floor[order]); floors={floors}")
        fl = df.order.map(floors).fillna(0).astype("f8")
        pred = np.maximum(tw3, fl)
        ok = np.isclose(cc, pred, rtol=RTOL)
        R["inferred_floors_by_order"] = {str(int(k)): float(v) for k, v in floors.items()}
        R["n_match_max_3TW_inferred_floor"] = int(ok.sum())
        R["n_residual_max_3TW_inferred_floor"] = int((~ok).sum())
        fl_rep = df.order.map(REPORTED_FLOORS).fillna(0).astype("f8")
        ok_rep = np.isclose(cc, np.maximum(tw3, fl_rep), rtol=RTOL)
        R["n_match_max_3TW_CONUS_floors"] = int(ok_rep.sum())
        R["n_residual_max_3TW_CONUS_floors"] = int((~ok_rep).sum())
        print(f"match: {ok.sum():,} ({100 * ok.mean():.4f}%)   residual: {(~ok).sum():,}")
        if (~ok).sum():
            r = pd.DataFrame({"order": df.order, "TopWdth": tw, "tw3": tw3, "pred": pred,
                              "TopWdthCC": cc})[~ok]
            r["kind"] = np.where(np.isclose(r.TopWdthCC, r.tw3, rtol=RTOL),
                                 "==3TW although 3TW<floor",
                                 np.where(r.TopWdthCC < r.tw3, "CC<3TW (below 3TW)", "other const"))
            print(r.groupby(["order", "kind"]).size().rename("count").to_string())
            print(r.head(15).to_string())
        eligible = fl > tw3
        print(f"reaches where 3TW < floor[order]: {eligible.sum():,}; of these set to floor: "
              f"{(eligible & np.isclose(cc, fl)).sum():,}; left at 3TW: {(eligible & is3).sum():,}")
        above = (~is3) & (cc < tw3 * (1 - RTOL))
        print(f"reaches where TopWdthCC < 3*TW: {above.sum():,}")

    hdr("BtmWdth / TopWdth")
    bw_ratio = df.BtmWdth / tw
    print(bw_ratio.describe().to_string())
    R["BtmWdth_over_TopWdth"] = {"min": float(bw_ratio.min()), "max": float(bw_ratio.max()),
                                 "mean": float(bw_ratio.mean())}
    ncc_ratio = (df.nCC / df.n).round(4)
    R["nCC_over_n_value_counts"] = {f"{k:g}": int(v) for k, v in ncc_ratio.value_counts().items()}

    hdr("nCC / n (value counts) and n values")
    print((df.nCC / df.n).round(4).value_counts().head().to_string())
    print(pd.crosstab(df.n.round(4), df.nCC.round(4)).to_string())

    hdr("Trapezoid consistency: implied bankfull depth")
    # WRF-Hydro/t-route MC: z = 1/ChSlp (horizontal per unit vertical), bfd = (Tw - Bw)/(2*z)
    #   => bfd = (Tw - Bw) * ChSlp / 2   (ChSlp is rise/run, V:H)
    z = df.ChSlp.astype("f8")
    bfd = (tw - df.BtmWdth) * z / 2
    print("model bankfull depth bfd = (TW-BW)*ChSlp/2 quantiles [m]:")
    print(bfd.quantile([0, 0.01, 0.5, 0.99, 1]).to_string())
    p = np.polyfit(np.log(tw), np.log(bfd), 1)
    res = np.log(bfd) - np.polyval(p, np.log(tw))
    print(f"log-fit bfd = {np.exp(p[1]):.4f} * TW^{p[0]:.4f}, resid std(log) = {res.std():.4f}")
    p2 = np.polyfit(np.log(tw), np.log(z), 1)
    res2 = np.log(z) - np.polyval(p2, np.log(tw))
    print(f"log-fit ChSlp = {np.exp(p2[1]):.4f} * TW^{p2[0]:.4f}, resid std(log) = {res2.std():.4f}")
    dflt = np.isclose(tw, 2.44, atol=1e-3)
    print(f"reaches with TW == 2.44 (DA=1 km2 default of 2.44*DA^0.34): {dflt.sum():,}; "
          f"ChSlp values there: {z[dflt].round(4).value_counts().head(3).to_dict()}")
    # NWM bankfull regressions (Blackburn-Lynch et al. 2017 style): TW = 2.44 DA^0.34, A = 0.75 DA^0.53
    # Infer DA from TW, then depth from area of trapezoid with BW = 0.6 TW: A = 0.8 TW d.
    da = (tw / 2.44) ** (1 / 0.34)
    d = 0.75 * da ** 0.53 / (0.8 * tw)
    slope_rise_run = d / (0.2 * tw)  # vertical/horizontal
    ok = np.isclose(z, slope_rise_run, rtol=1e-3)
    print(f"ChSlp == d/((TW-BW)/2) with d = 0.75*DA^0.53/(0.8*TW), DA=(TW/2.44)^(1/0.34): "
          f"{ok.sum():,} ({100 * ok.mean():.3f}%)  -> ChSlp is rise/run (V:H); depth = 0.2*TW*ChSlp")
    R["n_ChSlp_consistent_with_bankfull_regressions"] = int(ok.sum())
    ds.close()
    return R


class Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)


def main(argv):
    import provenance  # local module (same directory)

    files = argv or [f"data/RouteLink_{d}.nc" for d in DOMAINS]
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    results = {}
    with open(out / "report.txt", "w") as rep, contextlib.redirect_stdout(Tee(sys.stdout, rep)):
        for f in files:
            name = Path(f).stem.removeprefix("RouteLink_")
            results[name] = analyze(f)
    (out / "results.json").write_text(json.dumps(
        {"rtol": RTOL, "reported_floors": {str(k): v for k, v in REPORTED_FLOORS.items()},
         "domains": results}, indent=2) + "\n")
    provenance.write(HERE, out,
                     inputs={Path(f).name: HERE / f if not Path(f).is_absolute() else Path(f) for f in files},
                     sources={"routelink_base_url": "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/"})
    print(f"\nwrote {out / 'results.json'}, report.txt, provenance.json")


if __name__ == "__main__":
    main(sys.argv[1:])
