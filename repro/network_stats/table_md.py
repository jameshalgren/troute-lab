"""Render results/T_basins.csv + T_basins_summary.csv as Markdown (results/T_basins_rows.md).

The rows of the paper's basin table are this file's output, pasted below a
hand-written header. Notes in NOTES are hand-written; each states its evidence, and every
number in them comes from results/ or river_names.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

NOTES = {
    25293410: "Outlet is the St. Lawrence at the U.S.-Canada boundary; network includes the Great Lakes "
              "basin (NHDPlus TotDASqKM 776,672 km²), Canadian side included (see 'in CA/MX').",
    15183793: "Atchafalaya: separate network from the Mississippi. A RouteLink segment has one `to`, so the "
              "Mississippi-to-Atchafalaya distributary is not represented (NHDPlus TotDASqKM here, "
              "3,133,387 km², counts the Mississippi drainage through the divergence).",
    626220: "Continuous to the Colorado headwaters (37.95°N) only through 10,416 non-NHDPlus (ID ≥ 1e9) "
            "segments, mostly in Mexico / on the border reach; without them it splits at El Paso and at "
            "the Pecos confluence (see README).",
    21412883: "Outlet at the U.S.-Mexico boundary (NHDPlus also ends here).",
    23832907: "Includes the Canadian upper Columbia (24,203 non-NHDPlus segments, up to 52.9°N).",
    22811611: "Bounds by-network parallelism (40.2% of CONUS segments).",
    1020000221: "Outlet in Quebec (46.03°N, -73.12°E); likely Richelieu River from coordinates (UNVERIFIED).",
}


def fmt_int(x) -> str:
    return "" if pd.isna(x) else f"{int(x):,}"


def main() -> int:
    t = pd.read_csv(RESULTS / "T_basins.csv")
    s = pd.read_csv(RESULTS / "T_basins_summary.csv")
    lines = ["| Rank | River (outlet) | Outlet feature_id | Segments (% CONUS) | Reaches | Channel length (km) "
             "| Max order | Longest path (seg / reaches / km) | Headwaters | Gages | Waterbodies "
             "| Outlet class | Non-NHDPlus IDs / in CA-MX | Notes |",
             "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---|"]
    for r in t.itertuples():
        name = r.river_name if isinstance(r.river_name, str) else "UNVERIFIED"
        if isinstance(r.mainstem_name, str) and r.mainstem_name and r.mainstem_name != name:
            name += f" (mainstem: {r.mainstem_name})"
        if name.startswith("UNVERIFIED"):
            name = f"UNVERIFIED ({r.outlet_lat:.3f}, {r.outlet_lon:.3f})"
        notes = [NOTES.get(int(r.outlet_feature_id), "")]
        if not pd.isna(r.name_steps_up) and r.name_steps_up > 0:
            notes.append(f"name taken {int(r.name_steps_up)} segments upstream (outlet ID not in NHDPlus V2)")
        cls = r.outlet_class + (f" ({r.class_confidence})" if isinstance(r.class_confidence, str) else "")
        lines.append(
            f"| {r.rank} | {name} | {r.outlet_feature_id} | {r.n_segments:,} ({r.pct_domain_segments:.2f}%) "
            f"| {r.n_reaches:,} | {r.length_km:,.0f} | {r.max_order} "
            f"| {r.longest_path_segments:,} / {r.longest_path_reaches:,} / {r.longest_path_km:,.0f} "
            f"| {r.n_headwaters:,} | {r.n_gages:,} | {r.n_waterbodies:,} | {cls} "
            f"| {r.n_ids_ge_1e9:,} / {r.n_segments_in_canada_mexico:,} | {'; '.join(n for n in notes if n)} |")
    lines += ["", "| Group | Networks | Segments (% of domain) | Reaches | Channel length (km) | Gages "
              "| Waterbodies | Largest network (segments) | Median size | Single-segment networks |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in s.itertuples():
        lines.append(f"| {r.group} | {r.n_networks:,} | {r.n_segments:,} ({r.pct_domain_segments:.1f}%) "
                     f"| {r.n_reaches:,} | {r.length_km:,.0f} | {r.n_gages:,} | {r.n_waterbodies:,} "
                     f"| {fmt_int(r.largest_network_segments)} | "
                     f"{'' if pd.isna(r.median_network_segments) else f'{r.median_network_segments:g}'} "
                     f"| {fmt_int(r.single_segment_networks)} |")
    (RESULTS / "T_basins_rows.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {RESULTS / 'T_basins_rows.md'} ({len(t)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
