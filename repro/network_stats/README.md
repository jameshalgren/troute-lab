# NWM channel network as independent drainage networks

*AI-assembled (Claude, 2026-10-06); not yet reviewed by the author.*

## Question
Independent drainage networks never affect each other's computation, so they can be
routed in parallel with no communication. How many independent networks does the
operational NWM channel network (RouteLink) have? How large are they? How far does
by-network parallelism go before the largest network (the Mississippi) caps it? The
author recalls that with 3 processors, one took the Mississippi and two took the rest.
Related checks:
- Are the big transboundary rivers continuous or cut at the border? The author recalls
  that early RouteLink versions broke the Rio Grande into separate networks.
- How do these numbers compare with the 2020 numbers (AGU 2020 poster, 2020-01-30
  notebook, Technical-QA wiki)?

The basin table built from this experiment is `results/T_basins.csv` (Markdown rows:
`results/T_basins_rows.md`, written by `table_md.py`).

## Definitions
| Term | Definition |
|---|---|
| segment | One RouteLink row: an NHDPlus V2 flowline or other NWM `feature_id` |
| outlet | A segment whose `to` is 0 or is not a `link` in the same file. In all four v3.1.6 files and in v2.1, every outlet has `to == 0`, so every network is "primary" (it ends at a true terminal segment) |
| network | All segments that drain to one outlet. Each segment has one `to`, so each network is a tree; the code also checks that there are no cycles (0 segments on cycles) |
| headwater | A segment with no upstream segment |
| junction | A segment with ≥ 2 upstream segments |
| **reach** | A maximal run of consecutive segments with no tributary inflow between them. A segment **starts a new reach unless it has exactly one upstream segment**, so #reaches = #headwaters + #junctions |
| longest path (segments) | The maximum number of segments from a headwater to the outlet, counting both ends (= max depth + 1) |
| longest path (reaches) | The maximum over headwaters of the number of reaches crossed on the way to the outlet, counting both the headwater's reach and the outlet's reach |
| longest path (km) | The maximum summed `Length` from a segment's upstream end to the outlet. It can be a different path from the one with the most segments |
| gages | Segments whose `gages` string is non-blank |
| waterbodies | Distinct `NHDWaterbodyComID` values other than −9999 (−9999 is the only non-positive value in the files). `n_waterbody_segments` counts the segments that carry one |
| non-NHDPlus IDs | CONUS `feature_id` ≥ 1e9. The largest NHDPlus-range ID in the file is 948,100,740. These IDs come in 8 prefixes (101, 102, 109, 110, 113, 115, 117, 118). The v2.1 `processing_notes` list the regions routed with "Arc-Hydro derived segments" as 01a, 02b, 09a, 10i, 10h, 13a, 13b, 13d, 15a, 15b, 17b, 18a. The prefixes match those region numbers, but that mapping is our inference |
| in CA/MX | Segment midpoint (`lat`, `lon`) inside the Canada or Mexico polygon of Natural Earth 1:50m admin-0 countries. Approximate within a few km of the border; segments on border rivers (Rio Grande, Rainy, St. Lawrence) fall on either side arbitrarily |

## Method
- `analyze.py` builds the graph from `link` and `to` and walks breadth-first upstream
  from every outlet. It writes per-network statistics for every network
  (`results/networks_<DOMAIN>.csv`), domain summaries (`results/results.json`), figures,
  and the basin table (`results/T_basins.csv`, top 500 CONUS networks;
  `results/T_basins_summary.csv`).
- **Scheduling.** Work per network is its segment count; channel length is also tried.
  - *Bin packing:* the minimum number of equal processors such that no processor
    carries more work than the largest network, by first-fit decreasing (FFD), with
    the lower bound ⌈total/largest⌉.
  - *Makespan vs. P = 1–16:* LPT (longest-processing-time-first) list scheduling of
    whole networks.
- **Outlet class** (top 500 CONUS networks only; method and confidence are given per
  row):
  1. `coastal` (high): the NHDPlus V2 `dnhydroseq` of the outlet COMID is a
     `Coastline` feature.
  2. `international_boundary_cut`: the outlet lies within 10 km of the U.S.
     international land boundary (Natural Earth 1:10m boundary lines). Confidence is
     high if the outlet is in NHDPlus V2, medium otherwise.
  3. `inland_terminal` (medium): an NHDPlus terminal flowline with `dnhydroseq = 0`,
     more than 10 km from the border. This is a closed (endorheic) basin, *or* a
     stream that NHDPlus leaves disconnected (a losing or dry channel, e.g. the Santa
     Cruz River in Arizona, rank 62). The class does not separate the two.
  4. `undetermined`: the outlet is not in NHDPlus V2.

  Great Lakes tributaries are not separate networks. NHDPlus routes them through the
  lakes, so they belong to the St. Lawrence network (rank 4). The sub-river step
  confirms this for eight of them (see "Sub-rivers").
- **River names** (`river_names.py` writes the snapshot `river_names.json`; see below).
- **Continuity and splits.**
  - `analyze.py` locates the NLDI upstream-mainstem flowlines of the Rio Grande,
    Colorado, Mississippi, and Columbia, and named tributaries (Pecos River, Rio Chama),
    in the RouteLink networks.
  - It recomputes all networks with (a) the non-NHDPlus (ID ≥ 1e9) segments removed
    and (b) the CA/MX segments removed.

## Provenance of inputs (`fetch_data.py`, SHA-256 verified)
- **NWM v3.1.6 `RouteLink_{CONUS,AK,HI,PRVI}.nc`**: the same URLs and hashes as
  [`../routelink_topwidth/`](../routelink_topwidth/), from
  <https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/>.
- **NWM v2.1 `RouteLink_CONUS.nc` (optional, 269 MB)**: HydroShare resource
  [0a596929a3e5411bb0032a8de35e5089](https://www.hydroshare.org/resource/0a596929a3e5411bb0032a8de35e5089/),
  created 2022-09-23 by Austin Raney. Its abstract says the file was pulled from
  `nwm.v2.2.0/parm/domain/` on NCO on 2022-09-23. Its global attributes include
  `version = "NWM v2.1"` and "produced Fri Apr 12 2019 by Kevin Sampson (NCAR)". It
  has 2,776,738 segments. Skip it with `REQUIRED_ONLY=1`.
- **Natural Earth** (public domain), pinned to commit `117488dc` of
  [nvkelso/natural-earth-vector](https://github.com/nvkelso/natural-earth-vector):
  1:10m land boundary lines and 1:50m admin-0 countries.
- **`river_names.json`** (committed snapshot, generated 2026-10-06 by
  `river_names.py`): NHDPlus V2 attributes and NLDI navigation results, from live USGS
  services. `run.sh` does not query the web for these. To refresh, run
  `uv run --locked python river_names.py` after `analyze.py`. The refreshed snapshot
  can change names or classes only if USGS changes the services.
- **`subriver_gnis.json`** (committed snapshot, generated 2026-10-06 by
  `subrivers.py --refresh`; SHA-256 `9bbe72a13c1eb445831fd31a37e083c8f0f2afaf384654712ad18901efae5352`,
  recorded in `expected/subrivers_expected.json` and verified by `check.py`):
  NHDPlus V2 COMIDs by exact GNIS name, and name / level path / drainage area for the
  COMIDs that the sub-river step looks at. See "Sub-rivers".

### Getting NHDPlus GNIS names by COMID (for follow-up work)
NWM `feature_id` = NHDPlus V2 COMID wherever the ID exists in NHDPlus V2. The USGS
geoserver layer behind NLDI returns any NHDPlus V2 attribute (e.g. `gnis_name`,
`levelpathi`, `hydroseq`, `terminalfl`, `dnhydroseq`, `totdasqkm`, `ftype`), with
no key:

```
https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.0.0&request=GetFeature
  &typeName=wmadata:nhdflowline_network&outputFormat=application/json
  &propertyName=comid,gnis_name,levelpathi&CQL_FILTER=comid IN (22811611,626220)
```

Notes on using it (2026-10-06):
- `IN (...)` lists of 100 COMIDs work, and so do `levelpathi IN (...)` and
  `gnis_name='Rio Chama'`.
- A CQL `AND` is refused with HTTP 403. Filter further in code instead.
- Leave `'(),=` unencoded in the filter.
- The old host `labs.waterdata.usgs.gov` returns 403.
- The outlet flowline's own `gnis_name` is often blank. Walk its level path upstream,
  as `river_names.py` does.

## How to run
```bash
repro/network_stats/run.sh                 # ~590 MB of downloads (v3.1.6 + v2.1); ~1 min after download
REQUIRED_ONLY=1 repro/network_stats/run.sh  # skip the optional v2.1 file
```
Steps: `uv sync --locked` (Python 3.12.13, numpy 2.5.3, pandas 3.0.6, xarray 2026.9.0,
netCDF4 1.7.4, matplotlib 3.11.2), then `fetch_data.py` → `analyze.py` →
`table_md.py` → `subrivers.py` → `domains.py` → `check.py`.

Outputs in `results/`:
- `networks_{CONUS,AK,HI,PRVI,CONUS_v2.1}.csv`: every network.
- `results.json`
- `T_basins.csv`, `T_basins_summary.csv`, `T_basins_rows.md`
- `fig_network_sizes.{png,pdf}`, `fig_makespan.{png,pdf}`
- `subrivers.csv` (all columns), `subrivers.json`, `T_subrivers.csv`,
  `T_subrivers_rows.md`
- `domains.py` (see "Full NWM domain"): `T_basins_{AK,HI,PRVI}.csv`, new columns
  `display_name, name_rule, name_note, name_source` in `T_basins.csv`, `lake_renames.csv`,
  `T_subrivers_ext.csv`, `waterbody_networks.csv`, `bay_networks.csv`, `domains.json`
- `provenance.json`

## Results (NWM v3.1.6, `expected/expected.json`)
| | CONUS | AK | HI | PRVI |
|---|---:|---:|---:|---:|
| Segments | 2,776,734 | 391,528 | 13,637 | 14,017 |
| Networks | 12,820 | 4,102 | 1,273 | 747 |
| Reaches | 2,114,380 | 336,536 | 8,331 | 10,610 |
| Junctions / headwaters | 1,046,104 / 1,068,276 | 165,379 / 171,157 | 3,508 / 4,823 | 4,906 / 5,704 |
| Median network size (segments) | 4 | 1 | 3 | 2 |
| Single-segment networks | 2,592 | 2,171 | 512 | 330 |
| Largest network: segments (share) | 1,117,312 (40.2%) | 121,538 (31.0%) | 723 (5.3%) | 1,541 (11.0%) |
| Share in largest 3 / 10 networks | 53.6% / 69.7% | 58.1% / 71.5% | 13.3% / 26.1% | 25.9% / 54.6% |
| FFD processors at capacity = largest network (segments / length) | 3 / 3 | 4 / 4 | 19 / 30 | 10 / 10 |
| Max by-network speedup (total / largest) | 2.49 | 3.22 | 18.9 | 9.10 |

- **CONUS largest network.** The Mississippi (outlet 22811611, 29.135 N, −89.039 E)
  has 868,651 reaches and max Strahler order 10. Its longest path is **3,174 segments
  = 2,219 reaches = 6,041 km**.
- **CONUS network sizes.** 30 networks have ≥ 10,000 segments, and 4 have ≥ 100,000.
- **The "3 processors" statement.** With work = segments, the lower bound
  ⌈2,776,734 / 1,117,312⌉ = ⌈2.49⌉ = 3, FFD packs CONUS into **3** processors, and
  LPT with P = 3 reaches makespan = the Mississippi alone (40.2% of total). One
  processor takes the Mississippi and the other two share the remaining 59.8% (about
  29.9% each). This matches the author's recollection. Channel length as work gives
  the same result (largest 39.3%, 3 processors). From P = 3 to 16 the makespan stays
  at 40.2%: by-network parallelism alone cannot exceed a 2.49× speedup on CONUS.
- **Largest networks in the other domains.** AK: outlet 75000200000234 at 61.30 N,
  −150.58 E, which by coordinates is likely the Susitna River at Cook Inlet
  (UNVERIFIED; AK IDs are not NHDPlus V2 COMIDs). HI: 800013609 (21.96 N, −159.66 E).
  PRVI: 800040713 (18.44 N, −65.88 E). None of these is named here.

### Transboundary findings (v3.1.6)
Among the top 500 CONUS networks:
- 284 outlets are `coastal`.
- 24 are `international_boundary_cut`: the Colorado at the Mexico boundary, the
  St. Lawrence at 45° N, and the Rainy, Red River of the North, Souris, Roseau, Saint
  Mary, Belly, Waterton, Saint John, Aroostook, Meduxnekeag, Saint Regis and Salmon
  rivers, and several Arizona washes.
- 191 are `inland_terminal`.
- 1 is `undetermined`: an outlet in Quebec at 46.03 N, −73.12 E, likely the Richelieu
  (UNVERIFIED).

For the Colorado, St. Lawrence, Rainy, Red River of the North and Souris, NHDPlus V2
also ends at the border (`terminalfl = 1`, `dnhydroseq = 0`), so those cuts come from
NHDPlus. For the Belly and Meduxnekeag, NHDPlus continues downstream but RouteLink
stops at the border.

The CONUS RouteLink also reaches across the border. 62,215 segments have non-NHDPlus
IDs (35,393 north of 49.05 N, 10,912 south of 31.3 N). 110,327 segment midpoints lie
in Canada or Mexico. The difference is mostly NHDPlus V2's own Canadian coverage,
e.g. 47,584 Canadian segments in the Great Lakes (St. Lawrence) network.

**Rio Grande (outlet 626220, at the Gulf of Mexico)**
- **v3.1.6, as distributed:** one network of 54,182 segments, spanning 24.88–37.95 N
  and −108.37 to −97.15 E. Longest path 1,739 segments / 1,032 reaches / 3,120 km.
  - All 1,409 of the 1,550 NLDI upstream-mainstem flowlines that are present in
    RouteLink lie in this one network, up to the Colorado headwaters (37.85 N). The
    141 absent mainstem flowlines all lie on the border reach (25.96–31.81 N).
  - The **Rio Chama** (224/224 named flowlines) and the **Pecos River** (697/698) are
    inside the network.
    - The Rio Chama joins NHDPlus mainstem segment 17870388 (36.03 N, −106.08 E).
    - The Pecos's downstream-most segment (335000) flows to 1131000531 (29.69 N,
      −101.37 E), a non-NHDPlus segment on the border reach.
- **Without the 10,416 non-NHDPlus segments** (method a), the Rio Grande falls into
  200 pieces:
  - 21,829 segments ending at El Paso (2539831, 31.82 N, −106.59 E; longest path
    1,059 km);
  - 12,179 segments ending at the Pecos confluence (335000, 29.70 N, −101.37 E;
    1,511 km);
  - then 1,163 segments (317255, 29.42 N, −101.04 E), and smaller pieces.

  Method (b), removing CA/MX segments, gives 346 pieces with the same two largest.
  **So the Rio Grande is continuous in v3.1.6 (and in v2.1) only through the
  cross-border segments.** This is consistent with the author's recollection that
  earlier versions split it, though no such earlier file was available to test
  directly.
- **The Colorado** keeps its whole mainstem in one network (1,871/1,874 flowlines).
  Without non-NHDPlus segments it splits into 18 pieces; the largest (164,476
  segments) ends near Yuma.

### Cross-version comparison and the 2020 numbers
| Source | Segments | Reaches | Junctions | Networks | Longest path |
|---|---:|---:|---:|---:|---|
| AGU 2020 poster ([T-Route wiki](https://github.com/NOAA-OWP/t-route/wiki/Home:-Welcome-to-TRoute)) | 2,729,077 | 2,102,010 | 1,029,217 | 14,713 | 2,218 reaches |
| 2020-01-30 notebook ([`Network_Analysis_via_Parallelization_Demo.ipynb`](https://github.com/jameshalgren/wrf_hydro_nwm_public/blob/dynamic_channel_routing/trunk/NDHMS/dynamic_channel_routing/notebooks/Network_Analysis_via_Parallelization_Demo.ipynb)) | "2.7M" | | | 14,351 | |
| [Technical-QA wiki](https://github.com/NOAA-OWP/t-route/wiki/Technical-QA) | | | | | 2,219 "segments" |
| NWM v2.1 RouteLink (this run) | 2,776,738 | 2,114,381 | 1,046,102 | 12,822 | 3,174 seg / 2,219 reaches |
| NWM v3.1.6 RouteLink (this run) | 2,776,734 | 2,114,380 | 1,046,104 | 12,820 | 3,174 seg / 2,219 reaches |
| v3.1.6 without non-NHDPlus segments | 2,714,519 | | | 13,268 | |
| v3.1.6 without CA/MX segments | 2,666,407 | | | 14,341 | |

- **v2.1 vs. v3.1.6 are almost identical.** There are 2 extra outlets in v2.1 (1319262,
  24604493) and 3 networks whose sizes differ (Rio Grande 54,176 vs. 54,182; Colorado
  ±1; St. Lawrence ±4).
- **Neither file reproduces the 2020 counts.** The poster has 47,657 fewer segments and
  1,893 more networks than v3.1.6, so it used a different RouteLink. That was probably
  an NWM v2.0 or earlier file (UNVERIFIED), perhaps one without some of the
  cross-border segments.
  - Removing segments does not match the 2020 numbers either. Removing the
    non-NHDPlus segments gives 13,268 networks; removing CA/MX segments gives 14,341.
    The 14,341 is close to the notebook's 14,351 but should not be read as a match:
    the segment totals differ.
- **2,218 vs. 2,219 reaches.** Under our definition the Mississippi's longest path
  crosses 2,219 reaches, which means 2,218 reach-to-reach transitions (junctions
  crossed). The poster's 2,218 is most likely the same path counted exclusively
  (transitions, or omitting one end reach), and the wiki's 2,219 counted inclusively.
  UNVERIFIED: the 2020 code was not rerun. The path itself is the same in v2.1 and
  v3.1.6.
- **2.10M vs. 2.11M reaches.** The poster's 2,102,010 vs. our 2,114,380 (+12,370) goes
  with its smaller segment count, i.e. a different RouteLink version. v2.1 → v3.1.6
  changes the count by only 1. Both round to "2.1M reaches".

### Older RouteLink availability (searched 2026-10-06)
- **Found:** v2.1 (as deployed in nwm.v2.2.0) on HydroShare (above). A second copy of
  the same size is in a HydroShare resource of James Halgren's
  (b9d3bd7091244e8d99cbb8d6a8e1ae80, from `nwm.v2.2.0/parm/DOMAIN_WCOSS_Names/`).
- **Not obtainable:**
  - NCO nwprod serves only `nwm.v3.1.6`. Every older directory returns 404 (v1.2.0,
    v2.0.x, v2.1.x, v2.2.x, v3.0.x, v3.1.0), and the Wayback Machine has no RouteLink
    captures.
  - NOHRSC's `NWM_parameter_files_v2.1.tar.gz` (README: "applies to NWM v2.0")
    contains `RouteLink_NHDPLUS.nc.gz` but is 4.49 GB, above the 600 MB limit. It was
    not downloaded.
  - AWS `noaa-nwm-pds`, `noaa-nwm-retrospective-2-1-pds`, `noaa-nwm-retro-v2-0-pds`
    and `noaa-nwm-retrospective-3-0-pds`, and the GCS `national-water-model` bucket,
    have no parameter or domain files.
  - The t-route repository has only small test subsets.
  - Zenodo was not searched.

## Sub-rivers (`subrivers.py`)
*Added 2026-10-06 (AI-assembled, not yet reviewed by the author).* For each river in
the candidate list
(the author's list, the AI suggestions, and the city-rivers section; encoded in
`CANDIDATES` in `subrivers.py`), find the river's **mouth** segment in the v3.1.6 CONUS
RouteLink and compute the statistics of the subtree upstream of it, with the same
definitions as above. Table: `results/T_subrivers.csv` (Markdown rows: `results/T_subrivers_rows.md`).

### Method
1. **Named set.** The RouteLink segments whose NHDPlus V2 COMID has a GNIS name in the
   candidate's name list, restricted to the candidate's NHDPlus VPUs (e.g. `05` for the
   Ohio basin, `14` for the Upper Colorado). Several names form a union (Neosho + Grand;
   Catawba + Wateree; Green + Duwamish River + Duwamish Waterway).
2. **Scope.** The subtree of the parent's mouth, or the whole network for a parent that
   is its own network. Parents are resolved first, so a sub-sub-river (e.g. Boulder
   Creek → St. Vrain Creek → South Platte → Platte → Missouri) is searched only inside
   its parent.
3. **Components.** Named segments are joined to the next named segment downstream,
   across at most 15 other segments. Each component's root is its most-downstream
   segment.
4. **Mouth.** From the root, the mouth moves downstream while the next segment is (a)
   named with one of the river's own names, (b) on the root's NHDPlus level path
   (`levelpathi`, the NHDPlus mainstem) and blank-named or named with a name that is
   not in the candidate list, or (c) blank-named or not in NHDPlus V2 and with exactly
   one upstream segment. Rule (b) is needed because many large rivers are blank along
   their lower, polygon-mapped reaches: for example, the 196 flowlines named
   "Wabash River" end near Lafayette, Indiana (40.48 N). The ~200 segments below are
   blank or named "Big Bayou", but they stay on the Wabash level path (430001211) down
   to the Ohio.
5. **Receiving river ("joins").** The GNIS name of the segment below the mouth or, if
   that segment is blank, the most frequent name on its NHDPlus level path. If that
   segment is not in NHDPlus or its level path has no name, the first name met walking
   down is used, and the segments in between are reported as a **gap**.
6. **Choice and status.**
   - The largest component in scope (8 evaluated, largest first) whose receiving river
     is the listed parent is chosen. If none flows directly into the parent, the
     largest component in scope is chosen, and the river it actually joins is reported
     (e.g. Black Warrior → Tombigbee → Mobile).
   - `confident`: no other qualifying component has ≥ 25% of the chosen one's
     segments.
   - `UNVERIFIED`: ambiguous, or the mouth falls outside the parent.
   - `gap`: unnamed segments with tributary junctions separate the mouth from the
     receiving river; their inflows are not counted.
   - `not_in_parent`: no named segment lies inside the parent; the largest named
     component in the VPUs is reported with its own network.
7. **Primary rivers** (own networks: parents and the "primary" city rivers): the
   largest named component in the VPUs. If nothing named lies below its mouth, the
   river is its network's mainstem and the network outlet is used. Otherwise the row
   reports the network it drains into. The row gives the network's rank in
   `results/networks_CONUS.csv`.
8. **Upper Mississippi**: the "Mississippi River" segment that enters the confluence
   segment where the Ohio joins (Cairo). Its subtree includes the Missouri.

### Name-matching rules and interpretations
- Exact GNIS names. "Saint", not "St." (Saint Francis, Saint Croix, Saint Vrain Creek,
  Saint Lawrence). "Maria" was read as the Marias River, as in the candidates file.
- **Same names in different places.** VPUs separate most of them: White (AR: VPU
  11/08; IN: 05; UT/CO: 14), Green (KY: 05; UT/WY: 14; WA: 17), Salt (KY: 05; AZ: 15),
  Grand (MO: 10; MI: 04; OK, as Neosho: 11), Bear River (UT, VPU 16) vs. Bear Creek
  (CO, 10), Red River (south: 11/08) vs. Red River of the North (09), Cedar (IA: 07;
  WA: 17), James (SD: 10; VA: 02), Colorado (TX: 12).
- **Location boxes** (lat/lon ranges on the mouth, in `BOX`) encode the list's
  qualifiers where one VPU has several candidates: Chippewa (WI), Wolf (TN, Memphis),
  Green, Licking and Salt (KY), White (IN), Platte (NE), Grand (MO), Blue (MO, Kansas
  City), Clear, Cherry and Bear Creeks (Denver), Genesee (NY), Fox (WI), Grand (MI),
  Rouge (Detroit), Milwaukee, Cedar and Green–Duwamish (Seattle), Guadalupe and James
  (VA). They are interpretations of the list, not data. About 30 resolved mouths, including
  every boxed one, were compared by eye with their coordinates (e.g. Clear Creek at
  39.82 N, −104.98 E, near Commerce City; Grand (MO) at 39.38 N, −93.11 E, near
  Brunswick).
- **Names absent from the layer.** No VPU-18 flowline is named "American River". Only
  the North, Middle and South Forks are, so the American is found through its forks
  and followed down its level path to the Sacramento. No flowline is named "Chicago
  River"; the row uses the Chicago Sanitary and Ship Canal and the North/South
  Branches. "River Rouge" is the GNIS form in Michigan.
- **Platte**: the Platte is formed at North Platte, Nebraska. The North Platte's mouth
  segment flows into a segment named South Platte River, which joins the Platte.
- **Red River (south)**: listed under the Mississippi, but in RouteLink it flows into
  the Atchafalaya, a separate network (rank 5; see the basin table). Its share is
  given against that network. The Washita, Sulphur and Ouachita/Black are searched
  inside the Red.
- **Tennessee**: listed under both the Mississippi and the Ohio. It joins the Ohio
  (Paducah), and is listed once, under the Ohio.

### Results (`results/subrivers.csv`, 2026-10-06)
203 rows: 160 sub-rivers (the candidates plus two intermediate parents added for
searching, St. Vrain Creek and Cedar (IA)) and 43 primary rivers (16 parents, the
Atchafalaya, and 26 primary city rivers or "check alongside" networks).

| Status | Sub-rivers | Primary |
|---|---:|---:|
| confident | 156 | 43 |
| gap | 3 (Pecos, Pend Oreille, Kootenai) | |
| not_in_parent | 1 (Santa Cruz, AZ) | |
| UNVERIFIED | 0 | 0 |

- **Ohio vs. Upper Mississippi at Cairo.** The Ohio (mouth 1844789) has **230,729**
  segments (20.7% of the Mississippi network, 8.3% of CONUS); its longest path is
  1,140 reaches / 2,100 km. The Mississippi above the confluence (mouth 5093446) has
  **648,894** (58.1%), but that includes the Missouri (462,963; 41.4%). The Upper
  Mississippi minus the Missouri is 185,931 segments, and that figure also contains
  everything between St. Louis and Cairo. So by segments, the Ohio is larger than the
  Mississippi above the Missouri, and smaller than the Mississippi at Cairo.
- **Great Lakes.** All eight Great Lakes tributaries checked (Maumee, Saginaw,
  Grand (MI), Fox (WI), Genesee, Cuyahoga, Rouge, Milwaukee) are inside the St.
  Lawrence network (outlet 25293410). The segment below each mouth, presumably the flow
  path through the lake, carries the name of the lake's outflow channel: Niagara River
  (Maumee, Cuyahoga: Lake Erie), Saint Clair River (Fox, Grand: Lake Michigan; Saginaw:
  Lake Huron), Detroit River (Rouge), Saint Lawrence River (Genesee: Lake Ontario). The
  Milwaukee joins the Kinnickinnic River first.
- **Santa Cruz (AZ)** is not connected to the Gila in RouteLink. It is its own network
  (rank 62, outlet 15888878, `inland_terminal`).
- **Gaps.**
  - The Pecos ends 3 non-NHDPlus segments above the Rio Grande (border reach).
  - The Kootenai and Pend Oreille mouths found are at the Canadian border (49.00 N).
    135 and 23 unnamed segments follow before the Columbia River name resumes.
- **Different receiving river than listed** (data, not an error):
  - Monongahela → Allegheny (at Pittsburgh) → Ohio; North Platte → South Platte →
    Platte
  - Black Warrior → Tombigbee; Cahaba, Coosa and Tallapoosa → Alabama
  - Flint → Chattahoochee; Yuba → Feather; McCloud → Pit; New (AZ) → Agua Fria
  - DuPage and the Chicago canal → Des Plaines; Blue (MO) → "Old Channel Missouri
    River"; Catawba/Wateree → Congaree
  - Virgin → a blank segment whose NHDPlus level path is mostly named "Pahranagat
    Wash" → Colorado. This is probably the Overton Arm of Lake Mead (UNVERIFIED).
- **Primary city rivers.** San Jacinto drains into the Buffalo Bayou network (rank
  82): its mouth segment flows into a segment named Buffalo Bayou. The Cedar (WA) drains
  into Lake Washington, in a network named "Sammamish River" (rank 212). Ranks of the
  others are in the table.

### Caching the GNIS lookups (`subriver_gnis.json`)
`subrivers.py --refresh` runs the same resolution with live WFS queries and records
every answer. Each name query stores the WFS 1.1.0 `resultType=hits` count, and the
run fails if fewer features come back (no silent truncation). The plain `subrivers.py`
in `run.sh` reads only the snapshot, and stops if a lookup is missing. The offline
run reproduced the live run's `results/subrivers.csv` byte for byte. A refresh that
changes the snapshot changes its SHA-256, so `check.py` fails until
`expected/subrivers_expected.json` is updated with a reason here.

### Caveats
- NHDPlus `TotDASqKM` at the mouth COMID (column `nhdplus_totdasqkm_at_mouth`) is a
  sanity check only. At some mouths it counts flow through divergences, e.g. 444,024
  km² at the Illinois mouth and 255,657 km² at the Rock. RouteLink keeps one `to` per
  segment, so the subtree counts are not affected.
- "confident" means the rule picked one unambiguous mouth that flows into the expected
  river. It does not mean the author has checked the row.

## Full NWM domain, lake-outlet and confluence names (`domains.py`)
*Added 2026-10-07 (AI-assembled, not yet reviewed by the author).* The author asked for
"the full domain" and noted that the network named "Tchefuncte River" captures all of
Lake Pontchartrain's tributaries, that Buffalo Bayou "has too many streams labelled to
it", and that "the Sabine is lumped into the Neches" (2026-10-07).
The rules are in the docstring of `domains.py`; constants are at its top.

**Coverage.** The NWM v3.1.6 Alaska RouteLink covers **Cook Inlet and the Copper River
only** (lon −154.7 to −140.1, lat 58.6–63.6; `processing_notes`: "combined NHDPlus HR
Cook Inlet (Alaska) geodatabase … Arc-Hydro derived segments for Regions 190201 (Copper
River)"). The Yukon, Tanana, Koyukuk, Porcupine, Kuskokwim, Noatak, Kobuk, Colville,
Stikine, Taku and Nushagak are **not in the NWM**. HI and PRVI feature_ids are NHDPlus
V2.1 COMIDs (VPUs 20 and 21).

**Names of the top networks** (AK 200, HI 100, PRVI 100; CONUS 500 as before):
- HI, PRVI: the `river_names.py` rule (GNIS name on the outlet's NHDPlus level path), from
  the EPA WATERS NHDPlus V2.1 map service. NHDPlus V2.1 HI contains placeholder names such
  as "Ke360959" and "Hanak031"; names matching `^[A-Za-z]{2,6}\d{3,}$` are ignored.
- AK: the USGS NHDPlus HR map service was unusable on 2026-10-07 (HTTP 502/504 and more
  than 100 s per attribute query), so AK names come from the **USGS GNIS Domestic Names**
  national file (`Stream` features; mouth = primary point, source = source point). A GNIS
  stream names a network if the segment nearest its source (within 25 km; sources are often
  on glaciers) drains to the outlet and its lowest segment (within 10 km of the mouth
  point, inside the network) drains ≥ 50% of the network. 55 of the AK top 200 get a name
  this way; the rest are UNVERIFIED with coordinates. AK outlet classes are not computed
  (border test only).
- Results: AK Susitna River (121,538 segments), Copper River (73,370; Arc-Hydro
  segments), Matanuska River (32,586), an unnamed Copper delta channel (10,411),
  Chakachatna River (9,014); HI Waimea River (Kauaʻi, 723), Wailua River (571), Wailuku
  River (Hilo, 515); PRVI Río Grande de Loíza (1,541), Río de la Plata (1,086), Río Grande
  de Añasco (1,000), Río Grande de Arecibo (919).

**Lake-outlet rule** (all domains). Cause of the Tchefuncte case: in NHDPlus V2 the
artificial paths through Lake Pontchartrain carry the GNIS name "Tchefuncte River", and
the lake polygon (COMID 167166635) has no GNIS name. A network is renamed for a water
body W on its outlet mainstem (≤ 50 segments up) when W drains ≥ 50% of the network, has
≥ 2 inflows with ≥ 5% of W's drainage each and none with ≥ 75%, **and** the network's
level-path name is one of W's inflows and is not carried by the channel below W (the
Tchefuncte case; a network named for W's outflow, e.g. Jordan River below Utah Lake,
keeps its name). W is a RouteLink waterbody (`NHDWaterbodyComID`) or, for CONUS/HI/PRVI,
the NHDPlus `WBAreaComID` of a flowline whose `WBArea_FType` is LakePond, Reservoir or
Estuary. W's name: the NHDPlus V2.1 waterbody GNIS name, else the GNIS Lake / Reservoir
/ Bay / Swamp point nearest to most of W's channel length (flag
`lake_name_from_gnis_point`).

**Outlet-confluence rule** (all domains). If two or more branches with ≥ 15% of the
network each meet within 10 segments of the outlet and the network is named for a branch
that is not the largest, it is renamed "<largest> and <other>", or "<water body>
(<branches>)" when the junction or the outlet lies in a water body. Branches are labeled
by the first GNIS name going up their level path.

**Renamed networks** (`results/lake_renames.csv`, rule and flags per row): CONUS 46
(20 lake-outlet, 26 confluence), AK 1, HI 6, PRVI 11. The author's examples:
- #33 Tchefuncte River → **Lake Pontchartrain (Amite River, Tangipahoa River, Tchefuncte
  River)**. Flag `tributary_below_lake`: the Bogue Chitto (2,327 segments, 24.5% of the
  network) joins at the Rigolets, below the lake, through Pearl River distributaries.
- #82 Buffalo Bayou → **San Jacinto River and Buffalo Bayou**: the network ends at
  Lynchburg, where the San Jacinto (1,518 segments, 78%) and Buffalo Bayou (415, 21%)
  meet. Galveston Bay itself is not routed in RouteLink.
- #29 Neches River → **Sabine Lake (Sabine River, Neches River)**: the Sabine (5,837) and
  the Neches (5,641) meet at Sabine Lake / Sabine Pass.
- #212 Sammamish River → Lake Washington (Cedar River, Sammamish River).
- Others are listed in `lake_renames.csv`. Several confluence renames are mechanical and
  need the author's review (e.g. #85 "Mill Creek and Tule River", #122 "Silva Creek and
  Mimbres River", #95 "Pawtuckaway River and Piscataqua River").

**Inflow sub-rivers.** Every named inflow (≥ 5% of the water body's drainage) or branch of
a renamed network, and every named tributary flagged below the water body, becomes a
listed sub-river with its mouth at the water body or junction (95 rows, status
`lake_inflow`, in `T_subrivers_ext.csv`). So Buffalo Bayou now covers only its own
channel through Houston (415 segments). Under Lake Pontchartrain the rows are "Amite
River" (4,697 segments: everything entering through Pass Manchac, i.e. Lake Maurepas with
the Amite and Tickfaw; labeled by the dominant name on that level path), Tangipahoa
(1,208), Tchefuncte (564) and Bogue Chitto (2,327, below the lake). The Tickfaw is not a
separate row because it enters Lake Maurepas, not Lake Pontchartrain.

**Separate networks vs merged** (`results/bay_networks.csv`; networks among the listed
ones ending within a radius of the water body's GNIS point, and the network containing
the segment nearest that point; approximate, rivers at the far end of a large water body
can be missed, e.g. the Susquehanna for Chesapeake Bay):
- Galveston Bay: **separate** — Trinity River (#32, 9,616 segments), San Jacinto + Buffalo
  Bayou (#82), Clear Creek (#302); the bay is not routed.
- Sabine Lake: **merged** — one network (#29). Lake Pontchartrain: **merged** (#33).
- Mobile Bay: separate — Mobile (#6), Tensaw (#196), Blakeley (#458).
- Chesapeake Bay: separate — 29 listed networks within 150 km, incl. Potomac (#16), James
  (#17), York (#52), Rappahannock (#59). Delaware Bay: separate (Delaware #21 and 6 others).
- San Francisco Bay: separate (Sacramento #9, San Joaquin as "New York Slough" #14, Napa,
  Petaluma, …). Puget Sound: separate (10 within 100 km). Pamlico Sound: Neuse (#34),
  Pamlico (#48), Alligator (#499). Albemarle Sound: 4 small networks within 60 km.
- Great Salt Lake: separate — Bear (#37), Jordan (#74), Weber (#84), …
- Lake Okeechobee lies inside the Saint Lucie River network (#68); Lake Tahoe inside the
  Truckee River network (#76).

**Snapshot.** `domains_snapshot.json` (not in git: `run.sh` downloads it, SHA-256 checked,
with `../../tools/fetch_bundle.py network-stats` from the release asset listed in
`../../data_bundles.json`; 4.8 MB, generated 2026-10-07 by `domains.py
--refresh`, SHA-256 `5af3611de8937d314d0e50d84ffbd19f04b317c5dfd2312baab976eb3b9f026f`)
holds every EPA answer used and every GNIS feature a lookup returned. The GNIS file is
`DomesticNames_National_Text.zip` (accessed 2026-10-07, SHA-256
`180651b9fba01e65fc65182fb61de5be73bf6f42082a1b9b82cca2f74d3c16e9`; downloaded into
`data/gnis/` by `--refresh` only). The offline run reproduces the refresh run's
`results/domains.json`. Not done: a "select a lake with all inflowing streams" feature
(see `explorer/README.md`).

## Expected results and check
`expected/expected.json` holds the values from the first run, 2026-10-06 (macOS arm64):
domain counts, scheduling, the top 7 CONUS networks with names and classes, Rio Grande
continuity and splits, and v2.1. The CONUS counts also match an independent quick
script run by the coordinating session (see `_source`). `check.py` requires exact
integers and strings and floats within relative 1e-6. It skips v2.1 when that file
is absent.

`expected/subrivers_expected.json` (added 2026-10-06) holds the sub-river values of the
first run: the snapshot SHA-256, the status counts, the Great Lakes membership, and full
statistics for the Ohio, Missouri, Upper Mississippi, Arkansas, Yellowstone, Snake, Green
(UT/WY), Tennessee and Platte, plus a cross-check that the Mississippi found by name
reproduces the whole network (1,117,312 segments).

`expected/domains_expected.json` (added 2026-10-07) holds the `domains.py` values of the
first run: the snapshot SHA-256, the top 5 networks of each domain with names and classes,
name-rule counts, every renamed network (lake-outlet and confluence rules), the AK/HI/PRVI
sub-rivers, the 95 inflow sub-rivers and the bay table.

**Status (2026-10-07, macOS arm64):** `run.sh` passes 1,280/1,280 checks (241 earlier
checks, 157 sub-river checks, 882 full-domain checks), with and without `REQUIRED_ONLY=1`
(v2.1 present). Earlier: 398/398 (2026-10-06).

## Known caveats
- **River names.** Names are NHDPlus V2 GNIS names on the outlet's level path.
  - The outlet name can be a distributary or slough, e.g. "New York Slough"
    (San Joaquin) and "South Santee River" (Broad/Santee). The `mainstem_name` column
    gives the most frequent name on the level path.
  - 55 of the top 500 have no GNIS name and are marked UNVERIFIED with coordinates.
- **`inland_terminal` and `international_boundary_cut` are heuristics.** The CA/MX
  polygon test is approximate at 1:50m and unreliable for segments on border rivers.
- **`n_ids_ge_1e9`** applies to CONUS only; all AK IDs are large.
- **v2.1 file.** Only the HydroShare copy was used; we have not confirmed it is
  byte-identical to NCO's original.
