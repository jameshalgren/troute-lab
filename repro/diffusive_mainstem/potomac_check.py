"""Validation against the only model evidence we have: repro/short_ts_switch (Potomac).

Reads that experiment's per-segment outputs (it must have been run first; its results/ and
build/ are gitignored) and asks: of the MC misbehaviour measured there, what share falls
inside each mainstem (or alternative) configuration restricted to the Potomac?

Measured quantities (dt = 300 s, NWM default timestep):
* volume loss with assume_short_ts = False (assumption disabled; the code default, though
  every distributed configuration enables it, True, for NWM parity): per segment,
  (sum of upstream routed volumes + lateral volume) - own routed volume, as in
  short_ts_switch/mechanism.py `segment_balance`. Positive = loss.
* the same balance with True (WRF-Hydro/NWM parity setting), for reference.
* the switch's local effect: segments whose peak differs by > 5% between True and False.

The lateral inflow is rebuilt exactly as short_ts_switch/make_inputs.py `storm_series`
(constants copied below, with their source lines). Writes results/potomac_check.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import gammainc
from scipy.stats import spearmanr

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
STS = HERE.parent / "short_ts_switch"
RUNS = STS / "results" / "runs" / "potomac_storm"
SEGS = STS / "build" / "inputs" / "potomac_storm" / "segments.parquet"
CASE = STS / "build" / "inputs" / "potomac_storm" / "case.json"
# short_ts_switch/make_inputs.py L48-L51
AREA_PER_KM, BASEFLOW, STORM_MM = 1.25, 0.01, 25.0
STORM_SHAPE, STORM_SCALE_H, STORM_START_H = 3.0, 4.0, 24.0
DT = 300


def storm_series(length_km: np.ndarray, hours: int) -> np.ndarray:
    area_m2 = length_km * AREA_PER_KM * 1e6
    edges = np.arange(hours + 1, dtype=float) - STORM_START_H
    cdf = gammainc(STORM_SHAPE, np.clip(edges, 0, None) / STORM_SCALE_H)
    frac = np.diff(cdf)
    storm = np.outer(area_m2 * STORM_MM / 1000.0, frac / 3600.0)
    base = (length_km * AREA_PER_KM * BASEFLOW)[:, None]
    return (base + storm).astype(np.float32).astype(np.float64)


def main() -> int:
    if not (RUNS / f"dt{DT}_sts0.npz").exists() or not SEGS.exists():
        print("SKIP: repro/short_ts_switch has not been run (results/runs/potomac_storm missing)")
        (RESULTS / "potomac_check.json").write_text(json.dumps({"skipped": True}) + "\n")
        return 0
    seg = pd.read_parquet(SEGS)
    hours = int(json.loads(CASE.read_text())["hours"])
    link = seg["link"].to_numpy()
    pos = pd.Series(np.arange(len(seg)), index=link)
    down = pos.reindex(seg["to"].to_numpy()).fillna(-1).astype(int).to_numpy()
    ql = storm_series(seg["length_km"].to_numpy(), hours)
    vlat = ql.sum(axis=1) * 3600.0
    loss, peak = {}, {}
    for s in (0, 1):
        z = np.load(RUNS / f"dt{DT}_sts{s}.npz")
        assert np.array_equal(z["link"], link)
        v = z["volume_m3"]
        vup = np.zeros(len(seg))
        np.add.at(vup, down[down >= 0], v[down >= 0])
        loss[s] = vup + vlat - v
        peak[s] = z["peak_q"].astype(float)
    storm_total = (vlat - ql[:, 0] * hours * 3600.0).sum()

    cs = pd.read_parquet(RESULTS / "segments_conus.parquet")
    cs = cs.set_index("link").reindex(link)
    if cs["km"].isna().any():
        raise SystemExit("Potomac segments missing from segments_conus.parquet")
    km = cs["km"].to_numpy()
    lake = cs["lake"].to_numpy(bool)
    lf = loss[0]
    pos_loss = np.clip(lf, 0, None)
    rel_peak = (peak[1] - peak[0]) / np.maximum(peak[0], 1e-9)
    big = np.abs(rel_peak) > 0.05
    out = {"dt_s": DT, "segments": int(len(seg)), "lake_segments": int(lake.sum()),
           "false_total_loss_pct_of_storm": round(100 * lf.sum() / storm_total, 3),
           "false_positive_loss_m3": float(f"{pos_loss.sum():.4g}"),
           "true_total_loss_pct_of_storm": round(100 * loss[1].sum() / storm_total, 3),
           "segments_peak_diff_gt_5pct": int(big.sum()),
           "note": ("lake segments are routed as MC channels in short_ts_switch (waterbodies not broken out); "
                    "they are kept here and counted under their indicators like any segment")}
    qk = cs["q_cms"].to_numpy() * km
    flg = cs["error"].to_numpy(bool)          # known-error flag (LS or BW)
    eff = cs["effect"].to_numpy(bool)         # parameter-effect flag (XF or KC)
    rows = {}
    cfg_cols = [c for c in cs.columns if c.startswith("cfg_")]
    for c in cfg_cols + ["error_flagged", "effect_flagged"]:
        m = flg if c == "error_flagged" else eff if c == "effect_flagged" else cs[c].to_numpy(bool)
        # configurations exclude lakes by construction; in the Potomac run lakes are MC channels
        rows[c.removeprefix("cfg_")] = {
            "segments": int(m.sum()), "pct_km": round(100 * km[m].sum() / km.sum(), 2),
            "pct_false_loss": round(100 * pos_loss[m].sum() / pos_loss.sum(), 2),
            "pct_potomac_known_error_budget_predicted": round(100 * qk[m & flg].sum() / qk[flg].sum(), 2),
            "pct_potomac_parameter_effect_budget_predicted": round(100 * qk[m & eff].sum() / qk[eff].sum(), 2),
            "enrichment_loss_share_over_km_share": round((pos_loss[m].sum() / pos_loss.sum()) / max(km[m].sum() / km.sum(), 1e-9), 2),
            "pct_segments_peak_diff_gt_5pct_inside": round(100 * (big & m).sum() / max(big.sum(), 1), 2),
        }
    out["by_configuration"] = rows
    # indicators vs loss intensity (loss per unit of upstream storm water would need accumulation;
    # use loss per km as an intensity)
    inten = pos_loss / km
    for k in ("LS", "BW", "XF", "KC"):
        m = cs[k].to_numpy(bool)
        out[f"indicator_{k}"] = {"pct_km": round(100 * km[m].sum() / km.sum(), 2),
                                 "pct_false_loss": round(100 * pos_loss[m].sum() / pos_loss.sum(), 2)}
    so = cs["so"].to_numpy()
    edges = [0, 1.0001e-5, 1e-4, 2.5e-4, 1e-3, np.inf]
    labels = ["floor_1e-5", "1e-5_to_1e-4", "1e-4_to_2.5e-4", "2.5e-4_to_1e-3", "ge_1e-3"]
    out["false_loss_by_S0_class"] = {
        lab: {"pct_km": round(100 * km[(so >= a) & (so < b)].sum() / km.sum(), 2),
              "pct_false_loss": round(100 * pos_loss[(so >= a) & (so < b)].sum() / pos_loss.sum(), 2)}
        for lab, a, b in zip(labels, edges[:-1], edges[1:])}
    out["pct_false_loss_in_lake_segments"] = round(100 * pos_loss[lake].sum() / pos_loss.sum(), 2)
    out["spearman_error_score_vs_loss_per_km"] = round(float(spearmanr(cs["error_score"], inten).statistic), 3)
    out["spearman_neg_log_S0_vs_loss_per_km"] = round(float(spearmanr(-np.log10(cs["so"]), inten).statistic), 3)
    top = np.argsort(-pos_loss)[: max(1, len(seg) // 100)]
    out["top1pct_loss_segments"] = {"n": int(top.size), "pct_of_loss": round(100 * pos_loss[top].sum() / pos_loss.sum(), 2),
                                    "pct_error_flagged": round(100 * flg[top].mean(), 2),
                                    "pct_effect_flagged": round(100 * eff[top].mean(), 2),
                                    "pct_in_B": round(100 * cs["cfg_B_mainstem_fringes"].to_numpy(bool)[top].mean(), 2),
                                    "pct_in_F": round(100 * cs["cfg_F_candidate"].to_numpy(bool)[top].mean(), 2),
                                    "pct_slope_floor": round(100 * (cs["so"].to_numpy()[top] <= 1.0001e-5).mean(), 2)}
    (RESULTS / "potomac_check.json").write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
