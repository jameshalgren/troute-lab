# Basin explorer

*AI-assembled (Claude, 2026-10-06/07); not yet reviewed by the author.* File schemas:
[`DATA_CONTRACT.md`](DATA_CONTRACT.md).

The explorer shows the independent drainage networks of the NWM v3.1.6 channel network
(RouteLink) in all four NWM domains — **CONUS**, **Alaska** (Cook Inlet and the Copper
River only: that is all the NWM Alaska domain contains), **Hawaii**, **Puerto Rico and the
U.S. Virgin Islands** — with named tributaries, width functions, transboundary channel,
and places (gages, forecast points, reservoirs, dams, bridges).

## Quick start

**Just look at it**: the hosted copy is at <https://jameshalgren.github.io/troute-lab/> (GitHub Pages; every river
and waterbody, from the web tileset). Locally, download the web data bundle (about
433 MB, SHA-256 checked; release assets, not in git) and serve:

```sh
uv run explorer/fetch_data.py       # -> explorer/data/
uv run explorer/serve.py            # then open http://localhost:8765/
```

This uses the web tileset (`tiles.json` and `web_*.pmtiles`, see "Web tileset" below),
on which everything works, including "upstream of this point" (the orange highlight
after a map click) and the waterbody polygons; above zoom 10 the map enlarges the z10
tiles. `uv run explorer/fetch_data.py --full` also downloads the single full-resolution
file `flowlines.pmtiles` (983 MB, z3-12; too large for GitHub Pages, which allows at most
100 MB per file); the page uses it when `explorer/data/tiles.json` is absent. Bundle
versions, URLs and checksums are in `data_bundles.json`; `--source hydroshare` or
`--source <URL or directory>` selects a mirror.

**Rebuild everything** (full tiles, all data):

1. Prerequisites: [`uv`](https://docs.astral.sh/uv/) (Python is fetched and pinned per
   script), [tippecanoe](https://github.com/felt/tippecanoe) ≥ 2.17 on `PATH`
   (`brew install tippecanoe`; built with 2.79.0), ~13 GB of free disk.
2. Inputs (`explorer/scripts/fetch_inputs.py`; `--check` only checks URLs and local
   files):
   ```sh
   uv run explorer/scripts/fetch_inputs.py
   ```
   - NWM v3.1.6 RouteLink files (CONUS, AK, HI, PRVI; 320 MB) from NCEP, via
     `repro/network_stats/fetch_data.py` (SHA-256 pinned there), linked into `data/`.
   - NWM v3 channel hydrofabric (`NWM_v3_hydrofabric.gdb`), the "file gdb" linked on
     <https://water.noaa.gov/about/nwm> (accessed 2026-10-07):
     <https://www.nohrsc.noaa.gov/owp_files/nwm/data_tools/NWM_channel_hydrofabric.tar.gz>,
     3,250,751,657 bytes, server Last-Modified 2023-04-13, SHA-256
     `77d8975b543ff864cdac0736cc4f455fe86d77049c4d8b1fb8e458ec755dbc94`; unpacked to
     `data/NWM_v3_hydrofabric.gdb` (4.7 GB). The build scripts use that path by default
     (or `NWM_HYDROFABRIC_GDB` / `--gdb`).
   - Everything else (TIGER/Line boundary, USGS, NWPS, NID, NBI, EPA lookups) is
     downloaded and cached by the build steps into `data/explorer/cache/` (~170 MB).
3. Network statistics and names (`build_codes.py` reads the tables this step writes to
   `repro/network_stats/results/`):
   ```sh
   repro/network_stats/run.sh     # ~5 min after downloads; 1,280 checks
   ```
4. Explorer data, in this order (times: Apple M4 Max, 2026-10-07):

   | Step | Command | Time | Writes |
   |---|---|---|---|
   | 0 | `uv run explorer/scripts/build_boundary.py` | ~3 min | `data/explorer/segment_boundary.parquet` |
   | 1 | `uv run explorer/scripts/build_codes.py` | ~10 s | `rivers.json`, `data/explorer/segment_attrs.parquet` |
   | 2 | `uv run explorer/scripts/build_map_data.py` | ~2.5–3.5 min | tiles, `widths.json`, `bboxes.json`, `outlets.geojson` |
   | 2b | `uv run explorer/scripts/build_web_tiles.py` (hosted site only) | ~1.5 min | web tileset `data/explorer/web/` (see "Web tileset") |
   | 3 | `uv run explorer/scripts/build_places.py` | ~2 min cached; ~20 min first run | `places.json`, `data/explorer/T_places.csv` (gitignored) |

5. `uv run explorer/serve.py` and open <http://localhost:8765/>.

Disk after a full build: `data/` ≈ 9 GB (hydrofabric tarball 3.25 GB, which can be deleted
after unpacking; geodatabase 4.7 GB; RouteLink 0.3 GB; scratch FlatGeobuf files and
caches 2.3 GB), plus `explorer/data/flowlines.pmtiles` (983 MB, gitignored).
Web data bundle (`explorer/fetch_data.py`, not in git) ≈ 433 MB (web tileset 419.3,
places 12.8, JSON 1.2).

Known service problem: the USGS NHDPlus HR map service returned HTTP 502/504 or took
> 100 s per query on 2026-10-07. On 2026-10-08 its queries by `nhdplusid` answered (12–98 s
each, some 502/504 retries), so `build_places.py` now has the AK gage drainage-area check
and AK waterbody names (cached in `data/explorer/cache/nhdplushr/`;
`meta.method.nhdplus_hr_service` records the probe). Queries by `levelpathi` and
`where=1=0` counts still got no answer (HTTP 504 after 180 s, or nothing in 300 s), so
Alaska network names still come from USGS GNIS (see "Names").

## Methods

**Domains and sources.** NWM v3.1.6 RouteLink files (NCEP `nwm.v3.1.6/parm`, SHA-256
pinned in `repro/network_stats/fetch_data.py`): CONUS 2,776,734 segments / 12,820
networks; AK 391,528 / 4,102; HI 13,637 / 1,273; PRVI 14,017 / 747. Geometry: NWM v3
hydrofabric layers `nwm_reaches_{conus,alaska,hawaii,puertorico}` (field `ID` =
feature_id; every RouteLink segment has a line except 6 AK synthetic lake links) and
`nwm_waterbodies_{conus,alaska,hawaii}`. CRS: the gdb layers are NAD83 (EPSG:4269; CONUS
waterbodies in USA Contiguous Albers); tiles are WGS84 / Web Mercator; lengths and
distances are computed in EPSG:5070 (CONUS), EPSG:3338 (AK), ESRI:102007 (HI) and
EPSG:32161 (PRVI). No NWM reach crosses the antimeridian (checked; the AK domain spans
−154.7 to −140.1).

**Listed rivers and codes.** Top 500 CONUS, 200 AK, 100 HI and 100 PRVI networks by
segment count, plus named sub-rivers: the CONUS candidate list (`T_subrivers.csv`), AK/HI/PRVI
rivers (`T_subrivers_ext.csv`: Susitna with Yentna, Skwentna, Chulitna, Talkeetna, Deshka;
Copper with Chitina, Gulkana, Tazlina, Klutina, Tonsina; Matanuska, Knik, Kenai, Little
Susitna, Kasilof; Waimea with Makaweli, Wailua, Hanalei, Hanapepe, Wainiha, Wailuku
(Hilo), Kaukonahua; Río Grande de Loíza with Río Gurabo, Río de la Plata, Río Grande de
Arecibo with Río Caonillas, Añasco, Manatí, Culebrinas, Guanajibo, Cibuco), and the
inflows of lake-renamed networks. Codes are unique across domains (DATA_CONTRACT,
"Codes"). The Yukon, Kuskokwim, Noatak, Kobuk, Colville, Stikine, Taku and Nushagak are not
in the NWM Alaska domain.

**Names.** CONUS: NHDPlus V2 GNIS name on the outlet's level path (`river_names.json`).
HI/PRVI: the same rule on NHDPlus V2.1 (EPA WATERS). AK: USGS GNIS Domestic Names streams
(mouth and source points), because the NHDPlus HR service did not answer level-path
queries (2026-10-07 and 2026-10-08). Networks whose name
came from a river *upstream* of a lake, bay or confluence at the outlet are renamed (the
author's Tchefuncte, Buffalo Bayou and Neches examples): **Lake Pontchartrain (Amite River,
Tangipahoa River, Tchefuncte River)**, **San Jacinto River and Buffalo Bayou**, **Sabine
Lake (Sabine River, Neches River)**, and 61 others (64 in all four domains) listed in
`repro/network_stats/results/lake_renames.csv`, each with its rule and flags. The rivers entering
the water body become sub-rivers of their own (so Buffalo Bayou covers only its channel
through Houston). Rules, thresholds and the "separate vs merged" table for Galveston Bay,
Mobile Bay, Chesapeake Bay, San Francisco Bay, Puget Sound, the Pamlico/Albemarle sounds,
Great Salt Lake, Lake Okeechobee and Lake Tahoe: `repro/network_stats/README.md`, "Full
NWM domain". Galveston Bay is not routed in RouteLink: the Trinity (#32) and the San
Jacinto + Buffalo Bayou network (#82) are separate networks that end at the bay.

**Selecting a lake with all inflowing streams (not built; for a later branch).** The pieces
exist: the lake-outlet rule already finds a water body's member segments (RouteLink
waterbody or NHDPlus WBAreaComID) and its inflow segments. A lake selection would list
those inflows and highlight the union of their upstream intervals `[p, p+z)` — one range
filter per inflow — plus the lake's own segments. For terminal lakes (Great Salt Lake,
Salton Sea) the inflows are separate networks whose outlets lie in the lake polygon, so it
would also need an outlet-in-polygon test against `nwm_waterbodies_*` or NHDPlus
waterbodies.

### Transboundary

**Definition (for non-specialists).** A river is *transboundary* if its channel crosses the
U.S. international boundary, so that part of it lies in Canada or Mexico. We check every
NWM river reach against the official U.S. boundary of the Census Bureau and measure how
much channel lies outside the United States. Where a river *is* the boundary (the Rio
Grande, the St. Lawrence, the Rainy River), its channel is counted as "along the boundary"
rather than inside or outside, so its wiggles across the line are not counted as
crossings. A crossing is a place where the flow passes from clearly inside the U.S. to
clearly outside, or back.

**Method** (`explorer/scripts/build_boundary.py`, then `build_codes.py`):
- Boundary: U.S. Census Bureau TIGER/Line 2024 state polygons (union of all 56 states,
  DC and territories), <https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip>
  (9,954,307 bytes, Last-Modified 2025-06-27; SHA-256 recorded in
  `data/explorer/cache/sources.json` and `data/explorer/segment_boundary.json`). TIGER/Line
  state polygons follow the international boundary through the Great Lakes and the border
  rivers and include coastal water, so channel in a lake or an estuary is not "outside".
  (The Census *cartographic* boundary files are clipped to the shoreline and would put
  every Great Lakes flow path outside the U.S.; they are not used.)
- Per reach: `out_frac` = share of the line outside the U.S. polygon, measured in the
  domain's projected CRS (exact intersection; the polygon is split into a quadtree of
  ≤ 4,000-vertex pieces). `band_frac` = share of the line within **500 m** of the
  international boundary (the U.S. outline inside lon/lat boxes for Canada and Mexico).
  Status: **on the boundary** if `band_frac ≥ 0.5`; else **outside** if `out_frac > 0.5`
  and the reach is in a Canada/Mexico box; else **inside**. Reaches outside the polygon but
  not near Canada or Mexico (offshore) would count as inside; there are none (CONUS,
  AK, HI, PRVI all 0).
- Why 500 m: NHDPlus V2 lines come from 1:100,000 NHD (National Map Accuracy Standard,
  90% of points within ~51 m); the legal boundary in a border river is the deepest channel
  or the middle of a channel 50–1,500 m wide that has moved since it was mapped; NHDPlus
  draws the river as one center line. 500 m absorbs this on all the border rivers named
  below without reaching typical tributaries. Sensitivity: 3,854 CONUS reaches are on the
  boundary at 500 m, 2,932 at 250 m (AK 26 and 11).
- Per river (all segments upstream of its outlet or mouth): km outside (sum of RouteLink
  `Length` of outside reaches), km along the boundary, and crossings counted **with
  hysteresis**: each clearly inside / outside reach is compared with the next clearly
  inside / outside reach downstream, skipping reaches on the boundary. Outside → inside is
  an inbound crossing, inside → outside outbound. `tb` = the river has channel both
  inside and outside.
- Results (CONUS 107,612 reaches outside — 94,718 in Canada, 12,894 in Mexico — and 3,854
  on the boundary; AK 202 outside, in Canada, all in the Copper River network; HI and PRVI
  none): 27 listed networks are transboundary. Largest channel outside the U.S.: St.
  Lawrence (Great Lakes) 158,190 km; Rio Grande 55,241 km (+ 2,216 km along the boundary);
  Columbia 50,587 km; Rainy 16,892 km; Mississippi 13,017 km (Canadian Missouri tributaries,
  e.g. the Milk); Souris 9,409 km; Saint John 6,159 km; Red River of the North 3,216 km;
  Tijuana 1,832 km; an unnamed Quebec outlet (likely the Richelieu) 1,676 km; Colorado
  1,146 km; New River (Salton Sea) 1,062 km; Saint Croix 914 km; Santa Cruz 668 km;
  Copper (AK) 506 km.
- Caveats: crossings are counted at reach resolution (a reach is wholly inside, outside
  or on the boundary); border rivers with braided or relocated channels can still produce
  a few spurious crossings where the channel leaves the 500 m band (the Rio Grande's 130
  inbound crossings have not been checked one by one: Mexican tributaries such as the
  Conchos are real crossings, but some may be such artifacts);
  the Great Lakes count every Canadian tributary of the lakes as an inbound crossing; the
  boxes that tell Canada from Mexico are coarse lon/lat boxes (they only decide which
  country, not whether a reach is outside). Networks whose RouteLink outlet is cut at the
  boundary (Red River of the North, Souris, St. Lawrence at 45° N) show `tb_outlet = on`
  and outbound flow is then not counted as a crossing; the repro table's
  `international_boundary_cut` class marks them.

**Hydrography source (not transboundary).** The old "cross-boundary" column counted CONUS
segments with `feature_id ≥ 1e9`, i.e. channel added from outside NHDPlus V2. That is
where the line work came from, not which country it is in, so it is kept only as
`xb_segments` / `xb_km` ("hydrography source", shown in the Notes column) and the tile
property `h`.

**Map.** Channel outside the U.S. is drawn dashed (orange-brown), channel along the boundary
dotted; the selected river's outside channel is dashed in the highlight color.

## Building the map data (details)

`explorer/scripts/build_map_data.py` writes `widths.json`, `bboxes.json`,
`outlets.geojson` (web data bundle), `flowlines_overview.pmtiles` and
`flowlines_overview_other.pmtiles` (not published) and `flowlines.pmtiles` (gitignored) into `explorer/data/`.

```sh
uv run explorer/scripts/build_map_data.py                  # everything
uv run explorer/scripts/build_map_data.py --skip-extract   # reuse data/explorer/*.fgb
uv run explorer/scripts/build_map_data.py --skip-tiles     # JSON products only
```

The script ends with validation checks and exits non-zero if any fails: width-function
totals equal `n_segments` for all 1,168 rivers; Mississippi longest path 2,219 reaches; per
domain, the network sizes sum to the domain's segment count and the top-N sizes match
`rivers.json`; `p` is unique across all 3,195,916 segments; no reach spans the
antimeridian; tile features decoded from every PMTiles file (Missouri, Mississippi and the
largest AK, HI and PRVI networks) match `segment_attrs.parquet`.

**Tiles.** Layer `flow`, integer properties (see the contract). Small stream orders are
left out at low zooms:

| zoom | 3–4 | 5 | 6 | 7 | 8 | 9–12 |
|---|---|---|---|---|---|---|
| `flowlines.pmtiles`, CONUS and AK | o ≥ 7 | o ≥ 6 | o ≥ 5 | o ≥ 4 | o ≥ 3 | all |
| `flowlines.pmtiles`, HI and PRVI | o ≥ 4 | o ≥ 3 | o ≥ 2 | all | all | all |
| `flowlines_overview.pmtiles` (CONUS, z3–8) | o ≥ 7 | o ≥ 6 | o ≥ 6 | o ≥ 5 | o ≥ 5 | — |
| `flowlines_overview_other.pmtiles`, AK (z3–8) | o ≥ 7 | o ≥ 6 | o ≥ 6 | o ≥ 5 | o ≥ 5 | — |
| `flowlines_overview_other.pmtiles`, HI and PRVI (z3–8) | o ≥ 4 | o ≥ 3 | o ≥ 3 | all | all | — |

`flowlines.pmtiles` also carries a `waterbodies` polygon layer (`{id}`, z6–12). No tile
size or feature limit is applied, and features are never coalesced, so every feature keeps
its own properties. Thresholds are constants at the top of the script.

**Outputs** (2026-10-07): `flowlines.pmtiles` 983 MB (gitignored);
`flowlines_overview.pmtiles` 14.35 MB; `flowlines_overview_other.pmtiles` 2.74 MB;
`widths.json` 0.35 MB; `bboxes.json` 0.05 MB; `outlets.geojson` 0.19 MB; `rivers.json`
0.58 MB. Scratch FlatGeobuf files in `data/explorer/` ≈ 2.1 GB (gitignored).

**Web tileset (hosted site).** GitHub Pages serves at most 100 MB per file and about 1 GB
per site, so the hosted explorer cannot use `flowlines.pmtiles`. `build_web_tiles.py`
(after `build_map_data.py`; needs `data/explorer/flow.fgb` and `waterbodies.fgb`) makes a
tile set with the same layers and fields up to zoom 10, in files under 95 MB each:

```sh
uv run explorer/scripts/build_web_tiles.py                     # ~1.5 min -> data/explorer/web/
uv run explorer/scripts/build_web_tiles.py --skip-tippecanoe   # re-split the earlier z3-10 build
```

One tippecanoe run (the full tiles' command with `-z 10`) writes
`data/explorer/web/_z3_10.pmtiles`; its tiles are copied byte for byte into
`web_low.pmtiles` (z3–8, all domains, orders by zoom as in the table above, waterbodies
z6+) and five regional files (z9–10, every segment and waterbody). A regional file holds a
band of z9 tile columns, so each z9 and z10 tile is in exactly one file: no features are
duplicated or cut at the seams. `tiles.json` lists each file with its zoom range, bounds,
size and SHA-256; the page shows `web_low` below zoom 9 and the regional files from zoom 9
on, overzooming the z10 tiles at higher zooms. The script checks the size limit, that the
files hold every tile of the z3–10 build exactly once, and that probe tiles (St. Louis,
both sides of each seam, Anchorage, Honolulu, San Juan) are identical to the source and
carry `p` and `z`. Two runs on 2026-10-09 gave identical files (SHA-256 in `tiles.json`).

| file | zooms | z9 tile columns (west edge) | MB (2026-10-09) |
|---|---|---|---|
| `web_low.pmtiles` | 3–8 | all | 63.3 |
| `web_akhi.pmtiles` (Alaska, Hawaii) | 9–10 | 0–77 | 33.9 |
| `web_west.pmtiles` | 9–10 | 78–99 (−125.16°) | 76.4 |
| `web_plains.pmtiles` | 9–10 | 100–117 (−109.69°) | 79.9 |
| `web_central.pmtiles` | 9–10 | 118–130 (−97.03°) | 79.0 |
| `web_east.pmtiles` (incl. PRVI) | 9–10 | 131–511 (−87.89°) | 86.8 |
| total | | | 419.3 |

<!-- places:start (generated by explorer/scripts/build_places.py; edits here are overwritten) -->
## Places of interest

`data/places.json` (built 2026-10-08; 12.85 MB) lists locations keyed to NWM v3.1.6 RouteLink feature_ids. A CSV copy is at `data/explorer/T_places.csv`. Flags mark places whose link to the network may be wrong; they are not corrections.

| type | places | flagged | flags (count) |
|---|---:|---:|---|
| gage | 8,941 | 1,226 | `inactive` 742, `da_mismatch` 439, `dist_gt_2km` 73, `no_q_or_stage_series` 29, `not_found` 2, `id_needs_leading_zero` 1 |
| forecast_point | 7,893 | 998 | `no_reach_id` 598, `reach_differs_from_gage_segment` 311, `dist_gt_2km` 103, `reach_not_in_routelink` 1 |
| reservoir | 6,044 | 6 | `no_polygon` 6 |
| dam | 3,324 | 1,665 | `low_order` 1,419, `snap_gt_250m` 482 |
| bridge | 9,955 | 1,063 | `snap_gt_250m` 1,063 |

Places per domain:

| domain | gage | forecast_point | reservoir | dam | bridge |
|---|---:|---:|---:|---:|---:|
| CONUS | 8,735 | 7,726 | 5,782 | 3,286 | 9,890 |
| AK | 65 | 68 | 237 | 7 | 51 |
| HI | 58 | 25 | 9 | 7 | 0 |
| PRVI | 83 | 74 | 16 | 24 | 14 |

Sources, filters and flag definitions:

- **domains**: All four NWM v3.1.6 domains (CONUS, AK, HI, PRVI); each place carries `dom`. Distances and snapping in a projected CRS per domain: {'CONUS': 'EPSG:5070', 'AK': 'EPSG:3338', 'HI': 'ESRI:102007', 'PRVI': 'EPSG:32161'}.
- **gage**: RouteLink_{CONUS,AK,HI,PRVI}.nc `gages` (stripped). USGS ids: name, location, drainage_area from USGS Water Data API monitoring-locations; activity from time-series-metadata (00060, 00065). WSC ids: ECCC hydrometric-stations (DRAINAGE_AREA_GROSS). Model drainage area: NHDPlusV2 TotDASqKm of COMID = feature_id from the EPA WATERS NHDPlus service (CONUS, HI, PRVI; NHDPlus V2.1), or NHDPlus HR TotalDrainageAreaSqKm of NHDPlusID = feature_id from the USGS NHDPlus HR service (AK); missing where the feature_id has no NHDPlus record (e.g. AK Arc-Hydro segments), then no DA check.
- **forecast_point**: NWPS /gauges entries inside lon -126..-61, lat 23..51 with a forecast PEDTS, excluding AK, HI, PR, VI, GU, AS, MP (CONUS); AK, HI, PR+VI: NWPS gauges with a forecast PEDTS in the domain's state(s) {'AK': {'AK'}, 'HI': {'HI'}, 'PRVI': {'PR', 'VI'}} and inside the domain box {'CONUS': (-126.0, 23.0, -61.0, 54.0), 'AK': (-155.5, 58.3, -139.5, 64.0), 'HI': (-160.6, 18.7, -154.6, 22.5), 'PRVI': (-67.5, 17.5, -64.4, 18.7)} (the NWM Alaska domain covers Cook Inlet and the Copper River only); reachId and usgsId from /gauges/{lid}.
- **reservoir**: One place per RouteLink NHDWaterbodyComID; feature_id = outlet member (its `to` leaves the waterbody); lat/lon = polygon centroid (nwm_waterbodies_{conus,alaska,hawaii}; PRVI has no waterbody layer, so its places sit on the outlet segment), area from the polygon in an equal-area/projected CRS; name = NHDPlusV2 waterbody GNIS_NAME (EPA WATERS layer 4; CONUS, HI, PRVI) or NHDPlus HR NHDWaterbody GNIS_Name (layer 9; AK); res_type from reservoir_index_AnA.nc (CONUS) or reservoir_index_GDL_AK.nc (AK; HI and PRVI have no reservoir index) (codes per https://github.com/NCAR/wrf_hydro_nwm_public/blob/main/src/Routing/module_RT.F90 (reservoir_type dispatch: 1 level pool, 2 USGS persistence, 3 USACE persistence, 4/5 RFC forecast); Persistence_Level_Pool_Hybrid_Module_README.md, RFC_Forecasts_Module_README.md in the same directory).
- **dam**: NID national CSV; major = NID Height >= 50 ft OR Normal Storage >= 5,000 acre-ft OR Max Storage >= 25,000 acre-ft (the National Atlas 'major dams' definition, see http://lagic.lsu.edu/data/losco/dams00x020_usgs_2006_faq.html, accessed 2026-10-06); associated structures excluded; snapped to nearest segment of order >= 3 within 500 m (domain CRS); dams outside the domain box or farther away are omitted.
- **bridge**: NBI 2025 delimited file, record type 1, Item 42B (service under) in 5-8 (waterway, highway-waterway, railroad-waterway, highway-waterway-railroad; 9 'relief' excluded); lat/lon decoded from Items 16/17 (DDMMSSss, DDDMMSSss, west longitude; coding guide https://www.fhwa.dot.gov/bridge/mtguide.pdf); AK, HI, PR+VI: state codes {'AK': {'02'}, 'HI': {'15'}, 'PRVI': {'72', '78'}} inside the domain box; snapped to the nearest segment of any order within 500 m and kept if that segment has order >= 6.
- **segment_geometry**: NWM v3 hydrofabric nwm_reaches_* line geometry (projected per domain: {'CONUS': 'EPSG:5070', 'AK': 'EPSG:3338', 'HI': 'ESRI:102007', 'PRVI': 'EPSG:32161'})
- **nhdplus_hr_service**: USGS NHDPlus HR map service (https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer) probe on 2026-10-08: available
- **nextgen_crosscheck**: not run (set NEXTGEN_HYDROFABRIC_GPKG to a local conus_nextgen.gpkg from https://communityhydrofabric.s3.us-east-1.amazonaws.com/hydrofabrics/community/conus_nextgen.tar.gz)

Flags:

- `not_found`: gage id not found in the USGS Water Data API (or ECCC station list for WSC ids)
- `id_needs_leading_zero`: 7-digit RouteLink id matched a USGS site only after adding a leading zero
- `dist_gt_2km`: site (or forecast point) is more than 2 km from its segment
- `da_mismatch`: site drainage area / NHDPlusV2 TotDASqKm of the segment's COMID outside 0.75-1.33
- `inactive`: USGS: newest discharge (00060) or stage (00065) time series ends > 365 days before access; WSC: station status not 'Active'
- `no_q_or_stage_series`: USGS site has no discharge or stage time series in the Water Data API
- `multi_segment`: same gage id on more than one RouteLink segment
- `detail_not_found`: NWPS per-gauge endpoint returned nothing
- `no_reach_id`: NWPS gauge has no reachId
- `reach_not_in_routelink`: NWPS reachId is not a feature_id of the domain's RouteLink
- `reach_differs_from_gage_segment`: NWPS reachId differs from the RouteLink segment carrying the same USGS id
- `multiple_outlets`: more than one member segment of the waterbody drains out of it (outlet = highest order)
- `no_outlet`: no member segment drains out of the waterbody
- `not_in_reservoir_index`: waterbody missing from reservoir_index_*.nc
- `no_polygon`: waterbody id missing from the domain's nwm_waterbodies_* layer
- `snap_gt_250m`: snapped more than 250 m
- `low_order`: dam snapped to a segment of order < 4
- `nextgen_differs`: the NextGen hydrofabric puts the same gage / LID / NID id on a flowpath that neither contains nor touches this feature_id

Inputs (access date; SHA-256 of the cached copy is in `meta.sources` of `places.json`):

- `census/tl_2024_us_state.zip`: https://www2.census.gov/geo/tiger/TIGER2024/STATE/tl_2024_us_state.zip (accessed 2026-10-07)
- `eccc/hydrometric_stations.json`: https://api.weather.gc.ca/collections/hydrometric-stations/items?f=json&limit=10000 (accessed 2026-10-06)
- `epa/nhdplusv2_flowline_totdasqkm.json`: https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/2/query?where=comid IN (...)&outFields=comid,totdasqkm (accessed 2026-10-06)
- `epa/nhdplusv2_flowline_totdasqkm_HI.json`: https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/2/query?where=comid IN (...)&outFields=comid,totdasqkm (accessed 2026-10-07)
- `epa/nhdplusv2_flowline_totdasqkm_PRVI.json`: https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/2/query?where=comid IN (...)&outFields=comid,totdasqkm (accessed 2026-10-07)
- `epa/nhdplusv2_waterbody_gnis.json`: https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/4/query?where=comid IN (...)&outFields=comid,gnis_name,gnis_id,ftype (accessed 2026-10-06)
- `epa/nhdplusv2_waterbody_gnis_HI.json`: https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/4/query?where=comid IN (...)&outFields=comid,gnis_name,gnis_id,ftype (accessed 2026-10-07)
- `epa/nhdplusv2_waterbody_gnis_PRVI.json`: https://watersgeo.epa.gov/arcgis/rest/services/NHDPlus/NHDPlus/MapServer/4/query?where=comid IN (...)&outFields=comid,gnis_name,gnis_id,ftype (accessed 2026-10-07)
- `nbi/2025hwybronefiledel.zip`: https://www.fhwa.dot.gov/bridge/nbi/2025hwybronefiledel.zip (accessed 2026-10-06)
- `nhdplushr/flowline_totdasqkm_AK.json`: https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/3/query?where=nhdplusid IN (...)&outFields=nhdplusid,totdasqkm (accessed 2026-10-08)
- `nhdplushr/waterbody_gnis_AK.json`: https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer/9/query?where=nhdplusid IN (...)&outFields=nhdplusid,gnis_name,gnis_id,ftype (accessed 2026-10-08)
- `nid/nation.csv`: https://nid.sec.usace.army.mil/api/nation/csv (accessed 2026-10-06)
- `nwm_parm/reservoir_index_AnA.nc`: https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain/reservoir_index_AnA.nc (accessed 2026-10-06)
- `nwm_parm/reservoir_index_Extended_AnA.nc`: https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain/reservoir_index_Extended_AnA.nc (accessed 2026-10-06)
- `nwm_parm/reservoir_index_GDL_AK.nc`: https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain_alaska/reservoir_index_GDL_AK.nc (accessed 2026-10-07)
- `nwm_parm/reservoir_index_Medium_Range.nc`: https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain/reservoir_index_Medium_Range.nc (accessed 2026-10-06)
- `nwm_parm/reservoir_index_Short_Range.nc`: https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain/reservoir_index_Short_Range.nc (accessed 2026-10-06)
- `nwps/gauge_details.json`: https://api.water.noaa.gov/nwps/v1/gauges/{lid} (one GET per forecast gauge; fields lid, usgsId, reachId, name, county, latitude, longitude) (accessed 2026-10-06)
- `nwps/gauge_details_AK.json`: https://api.water.noaa.gov/nwps/v1/gauges/{lid} (one GET per forecast gauge; fields lid, usgsId, reachId, name, county, latitude, longitude) (accessed 2026-10-07)
- `nwps/gauge_details_HI.json`: https://api.water.noaa.gov/nwps/v1/gauges/{lid} (one GET per forecast gauge; fields lid, usgsId, reachId, name, county, latitude, longitude) (accessed 2026-10-07)
- `nwps/gauge_details_PRVI.json`: https://api.water.noaa.gov/nwps/v1/gauges/{lid} (one GET per forecast gauge; fields lid, usgsId, reachId, name, county, latitude, longitude) (accessed 2026-10-07)
- `nwps/gauges.json`: https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=..&bbox.ymin=23&bbox.xmax=..&bbox.ymax=51&srid=EPSG_4326 (5-degree longitude bands from -126 to -61) (accessed 2026-10-06)
- `nwps/gauges_AK.json`: https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-155.5&bbox.ymin=58.3&bbox.xmax=-139.5&bbox.ymax=64.0&srid=EPSG_4326 (accessed 2026-10-07)
- `nwps/gauges_HI.json`: https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-160.6&bbox.ymin=18.7&bbox.xmax=-154.6&bbox.ymax=22.5&srid=EPSG_4326 (accessed 2026-10-07)
- `nwps/gauges_PRVI.json`: https://api.water.noaa.gov/nwps/v1/gauges?bbox.xmin=-67.5&bbox.ymin=17.5&bbox.xmax=-64.4&bbox.ymax=18.7&srid=EPSG_4326 (accessed 2026-10-07)
- `usgs/monitoring_locations.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?filter=monitoring_location_number IN (...) (accessed 2026-10-06)
- `usgs/monitoring_locations_AK.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?filter=monitoring_location_number IN (...) (accessed 2026-10-07)
- `usgs/monitoring_locations_HI.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?filter=monitoring_location_number IN (...) (accessed 2026-10-07)
- `usgs/monitoring_locations_PRVI.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?filter=monitoring_location_number IN (...) (accessed 2026-10-07)
- `usgs/time_series_metadata.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/time-series-metadata/items?filter=monitoring_location_id IN (...) AND parameter_code IN ('00060','00065') (accessed 2026-10-06)
- `usgs/time_series_metadata_AK.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/time-series-metadata/items?filter=monitoring_location_id IN (...) AND parameter_code IN ('00060','00065') (accessed 2026-10-07)
- `usgs/time_series_metadata_HI.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/time-series-metadata/items?filter=monitoring_location_id IN (...) AND parameter_code IN ('00060','00065') (accessed 2026-10-07)
- `usgs/time_series_metadata_PRVI.json`: https://api.waterdata.usgs.gov/ogcapi/v0/collections/time-series-metadata/items?filter=monitoring_location_id IN (...) AND parameter_code IN ('00060','00065') (accessed 2026-10-07)

Rebuild: `NWM_HYDROFABRIC_GDB=<path to NWM_v3_hydrofabric.gdb> NEXTGEN_HYDROFABRIC_GPKG=<path to conus_nextgen.gpkg> uv run explorer/scripts/build_places.py` (both variables optional; see the script docstring).
<!-- places:end -->
