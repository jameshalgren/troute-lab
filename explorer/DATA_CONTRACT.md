# Basin explorer: data contract

The explorer (`explorer/index.html`) reads these files from `explorer/data/`.
Each file has exactly one producer. Files in the web data bundle (a release asset fetched by `explorer/fetch_data.py`; no data
is committed to git) stay small: each ≤ ~15 MB, total budget ≈ 35 MB (2026-10-07: 14.4 + 2.7 MB overview tiles, 12.8 MB places, ~1.2 MB JSON). The full
tiles are an optional separate download (`fetch_data.py --full`) or are rebuilt by script.

The explorer covers all four NWM v3.1.6 domains: **CONUS**, **AK** (Alaska: Cook Inlet and
the Copper River only; that is all the NWM Alaska domain contains), **HI** and **PRVI**
(Puerto Rico and the U.S. Virgin Islands).

| File | Producer | In web bundle? | Contents |
|---|---|---|---|
| `rivers.json` | `explorer/scripts/build_codes.py` | yes | `{meta, nodes:[…]}`. One node per selectable river. `code` (unique across domains, see **Codes**); `dom` ∈ {CONUS, AK, HI, PRVI}; `rank` (networks: rank in their domain); `kind` ∈ {network, sub}; `parent` = code of the river it flows into (network containment); `name` (networks: `display_name` of the repro table, see **Names**); stats from the repro CSVs; `p`, `z` (upstream interval of the outlet / mouth segment); transboundary fields `tb, tb_out_km, tb_out_segments, tb_on_km, tb_cross_in, tb_cross_out, tb_dir, tb_outlet, tb_countries` (see **Transboundary**); hydrography-source fields `xb_segments, xb_km`. `meta.domains[dom]` = `{code_base, label, n_segments, n_networks, bbox, p_range, …}` |
| `widths.json` | `explorer/scripts/build_map_data.py` | yes | `{code: {"bin": b, "d0": d0, "max_d": m, "counts": [...]}}`: the **width function**, i.e. segments per topological distance (in reaches) above the river's mouth, in bins of `b` reaches (≤ 300 bins; `counts[i]` covers distances `[i·b, (i+1)·b)`; `m` = largest distance, inclusive). `d0` = `d_reach` of the mouth segment (0 for networks), so bin `[lo, hi)` maps to tile features with `d ∈ [d0+lo, d0+hi)`. Also `"_networks": {"sizes": [CONUS…], "by_domain": {"CONUS": […], "AK": […], "HI": […], "PRVI": […]}}`: segment counts of every network of each domain, largest first |
| `bboxes.json` | `build_map_data.py` | yes | `{code: [west, south, east, north]}` |
| `outlets.geojson` | `build_map_data.py` | yes | Points: listed network outlets and sub-river mouths; `properties: {code, name, kind, dom}` |
| `flowlines.pmtiles` | `build_map_data.py` (tippecanoe) | **no** (optional download, `fetch_data.py --full`, ~1 GB) | Vector tiles of all four domains, layer `flow` (z3–12). Per feature (integers): `id` feature_id; `n` listed network code or 0; `r` innermost listed river code or 0; `o` Strahler order; `d` d_reach (distance from the network outlet in reaches); `p` DFS preorder index (unique across domains); `z` upstream-subtree size; `dm` domain (1 AK, 2 HI, 3 PRVI; **absent** = CONUS); `x` boundary position (1 outside the U.S., 2 on the boundary; **absent** = inside); `h` hydrography source (1 = not the domain's NHDPlus; absent = NHDPlus). Orders shown from zoom: CONUS and AK o≥7 z3, o≥6 z5, o≥5 z6, o≥4 z7, o≥3 z8, all z9+; HI and PRVI o≥4 z3, o≥3 z5, o≥2 z6, all z7+. Layer `waterbodies` (polygons, `{id}`, z6+; CONUS, AK, HI; the hydrofabric has no PRVI waterbody layer) |
| `flowlines_overview.pmtiles` | `build_map_data.py` | yes (14.4 MB) | CONUS only; `flow` with `id, n, r, o, d, x` (no `p`, `z`, `h`: upstream highlighting needs the full tiles), z3–8, o≥7 z3, o≥6 z5, o≥5 z7; no `waterbodies` |
| `flowlines_overview_other.pmtiles` | `build_map_data.py` | yes (2.7 MB) | AK, HI and PRVI, same schema plus `dm`; AK o≥7 z3, o≥6 z5, o≥5 z7; HI and PRVI o≥4 z3, o≥3 z5, all z7+ |
| `places.json` | `explorer/scripts/build_places.py` | yes | `{meta, places:[{type, dom, key, name, feature_id, lat, lon, net, river, order, p, z, flags:[…], source, extra:{…}}]}` (`p`, `z` = the upstream interval of the place's segment; absent when it has no segment); `type` ∈ {gage, forecast_point, reservoir, dam, bridge}. `extra` has every field of `data/explorer/T_places.csv` except pure duplicates (author X2, 2026-10-07) |

Segment attributes shared by the producers: `data/explorer/segment_attrs.parquet`
(gitignored), columns `feature_id, dom, net, river, order, d_seg, d_reach, p, z, xb, tb, lat, lon`,
written by `build_codes.py`; and `data/explorer/segment_boundary.parquet` (gitignored),
columns `feature_id, dom, out_frac, band_frac, status, country`, written by
`build_boundary.py`.

**Codes.** `code = base + rank` for a listed network (rank 1–999 within its domain) and
`base + 1001 + i` for the i-th listed sub-river of the domain, with base 0 (CONUS), 10000
(AK), 20000 (HI), 30000 (PRVI). CONUS codes are unchanged from the CONUS-only version
(networks 1–500, sub-rivers from 1001 in `T_subrivers.csv` order; lake/confluence inflow
sub-rivers follow). The domain of a code is `floor(code / 10000)`. Listed: CONUS top 500,
AK top 200, HI top 100, PRVI top 100 networks.

**Names.** A network's `name` is the repro `display_name`: the NHDPlus GNIS name on the
outlet's level path (`river_names.py`; HI/PRVI the same rule on NHDPlus V2.1), the GNIS
Domestic Names stream that drains most of the network (AK), or a name from the
**lake-outlet** or **outlet-confluence** rule (e.g. "Lake Pontchartrain (Amite River,
Tangipahoa River, Tchefuncte River)"; rules in `repro/network_stats/README.md`, "Full NWM
domain"). Renamed networks keep the old name in `level_path_name` and the rule in
`name_rule`.

**Upstream interval.** `build_codes.py` numbers segments in depth-first preorder, walking
upstream from each outlet (`p`), domain after domain (CONUS 0–2,776,733; AK, HI and PRVI
follow), and records each segment's upstream-subtree size (`z`, inclusive). Every segment
upstream of segment `s` (including `s`) has `p ∈ [p_s, p_s + z_s)`, one range filter on
the tiles. Because `p` is unique across domains, the same filter works in the combined
tile file. Check: the Mississippi outlet's `z` equals its network size, 1,117,312.

**Transboundary.** A river is *transboundary* if its channel crosses the U.S.
international boundary, so part of it lies in Canada or Mexico. We test every NWM reach
against the U.S. boundary of the Census Bureau (TIGER/Line 2024 state polygons, which
follow the international boundary through the Great Lakes and the border rivers). A reach
counts as *outside the U.S.* if more than half of its line is outside, and as *on the
boundary* if at least half of it is within 500 m of the international boundary (a border
river such as the Rio Grande, whose channel *is* the boundary). A *crossing* is a place
where the flow passes from a reach clearly inside the U.S. to one clearly outside (or the
reverse); reaches on the boundary are skipped, so a border river that wiggles across the
line is not counted as crossing it.

Fields (per river, over the segments upstream of its outlet or mouth): `tb` = has both
inside and outside channel; `tb_out_km`, `tb_out_segments` = channel outside the U.S.
(RouteLink `Length`); `tb_on_km` = channel on the boundary; `tb_cross_in` / `tb_cross_out`
= crossings into / out of the U.S. along the flow; `tb_dir` ∈ {inbound, outbound, both};
`tb_outlet` ∈ {in, out, on} for the outlet / mouth segment; `tb_countries`;
`tb_foreign_only` if all channel is outside. HI and PRVI have no land boundary. Method,
inputs and caveats: README, "Transboundary". The map draws outside channel dashed and
boundary channel dotted.

**Hydrography source (`xb`, `h`; not transboundary).** 1 if a segment is not from the
domain's NHDPlus: CONUS `feature_id ≥ 1e9` (segments added outside NHDPlus V2, e.g. the
Canadian Columbia and the Mexican Rio Grande tributaries); AK the Arc-Hydro segments of the
Copper River region (IDs 190201…) and the six synthetic lake links (IDs < 100). It says
where a segment's geometry came from, not which country it is in (e.g. the Canadian
Great Lakes channel is NHDPlus-derived).

**Highlighting rule.** Selecting river `c` highlights features whose `r` is `c` or any
descendant code of `c` in `rivers.json`. Selecting network code `k` highlights features
with `n == k`.

**Serving.** PMTiles needs HTTP Range requests, so open the explorer through
`uv run explorer/serve.py`, not as `file://`. Without `flowlines.pmtiles` the page
uses the two overview files.
