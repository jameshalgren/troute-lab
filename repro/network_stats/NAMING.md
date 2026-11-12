# How NWM channel networks and rivers are named

*AI-assembled (Claude, 2026-10-22) from `river_names.py`, `subrivers.py`, `domains.py`, their
results, and the author's notes in `~/git/troute_paper/notes/`. The author has not reviewed it.
Where this file and the code disagree, the code is right; constants are quoted with their names
so they can be checked.*

## Contents
1. [Why names are needed, and what goes wrong](#1-why-names-are-needed-and-what-goes-wrong)
2. [Overview: three layers](#2-overview-three-layers)
3. [Data sources](#3-data-sources)
4. [Layer 1: network names (level-path GNIS rule)](#4-layer-1-network-names-level-path-gnis-rule)
5. [Layer 2: sub-rivers (tributary mouths)](#5-layer-2-sub-rivers-tributary-mouths)
6. [Layer 3: lake-outlet and outlet-confluence renames](#6-layer-3-lake-outlet-and-outlet-confluence-renames)
7. [Splitting lake tributaries into separate rows](#7-splitting-lake-tributaries-into-separate-rows)
8. [Separate vs merged networks around bays and lakes](#8-separate-vs-merged-networks-around-bays-and-lakes)
9. [Output columns and flags](#9-output-columns-and-flags)
10. [Results](#10-results)
11. [Who uses the names](#11-who-uses-the-names)
12. [Reproducibility](#12-reproducibility)
13. [History and the author's decisions](#13-history-and-the-authors-decisions)
14. [Open items](#14-open-items)
15. [Known weaknesses](#15-known-weaknesses)
16. [Constants](#16-constants)

---

## 1. Why names are needed, and what goes wrong

The NWM RouteLink files only store numbers. Each segment has a `feature_id` (`link`), a downstream `to`, and
attributes; none of these is a river name. The network-statistics experiment splits each domain into
independent drainage networks (12,820 in CONUS) and ranks them by size. Tables, the paper and the
explorer need a name for each large network and for well-known tributaries inside them.

In CONUS, HI and PRVI the NWM `feature_id` equals an NHDPlus V2 / V2.1 COMID wherever the ID exists in
NHDPlus, so names can come from the NHDPlus `GNIS_NAME` attribute. This works for most rivers. It fails in
three known ways, and each layer below was added to fix one of them:

| Failure | Example | Fixed by |
|---|---|---|
| The outlet flowline itself has no name | Many coastal outlets; the lowest reaches of large rivers are often blank | Layer 1 walks up the NHDPlus level path to the first name |
| A tributary's name is not unique or stops before its mouth | Several "White River"s; the "Wabash River" name ends near Lafayette, IN | Layer 2 limits the search by region and box, then follows the level path to the mouth |
| The level path through a lake carries the name of **one inflow**, so a whole lake system is named after a minor tributary | The network draining Lake Pontchartrain was called "Tchefuncte River" | Layer 3: the lake-outlet rule |
| Two large rivers meet just above the outlet, and the network is named after the smaller | "Buffalo Bayou" for the San Jacinto + Buffalo Bayou network; "Neches River" for Sabine + Neches | Layer 3: the outlet-confluence rule |

## 2. Overview: three layers

```
analyze.py         networks_<DOM>.csv         every network, ranked by segment count
   │
river_names.py     river_names.json           Layer 1 (CONUS): GNIS name on the outlet's level path
   │                (live USGS queries; committed snapshot)
subrivers.py       subrivers.csv, T_subrivers  Layer 2 (CONUS): mouths of named tributaries
   │                (subriver_gnis.json snapshot)
domains.py         T_basins*.csv, lake_renames.csv, T_subrivers_ext.csv,
                   bay_networks.csv, waterbody_networks.csv, domains.json
                   Layer 1 for AK/HI/PRVI, Layer 2 for AK/HI/PRVI, Layer 3 for all domains,
                   lake-inflow sub-rivers
                   (domains_snapshot.json; release asset)
```

- **`river_name`** is the Layer 1 name. It never changes after it is assigned, so older checks still hold.
- **`display_name`** is the name to show. It equals `river_name` unless Layer 3 renamed the network.
- **`name_rule`** records which rule produced `display_name`: `levelpath_gnis`, `gnis_mouth_source` (AK),
  `lake_outlet`, `outlet_confluence` or `unverified`.

## 3. Data sources

| Domain | Feature IDs | Name source | Service |
|---|---|---|---|
| CONUS | NHDPlus V2 COMIDs, plus about 1e9+ IDs for non-NHDPlus segments (e.g. Canada/Mexico) | NHDPlus V2 `gnis_name` | USGS geoserver WFS `wmadata:nhdflowline_network` (the layer behind NLDI and nhdplusTools), `https://api.water.usgs.gov/geoserver/wmadata/ows` |
| HI (VPU 20), PRVI (VPU 21) | NHDPlus V2.1 COMIDs | NHDPlus V2.1 `gnis_name` | EPA WATERS NHDPlus MapServer (`watersgeo.epa.gov`), layer 2 = flowlines, layer 4 = waterbodies |
| AK | NHDPlus HR NHDPlusIDs (Cook Inlet), Arc-Hydro IDs `190201…` (Copper River) | USGS **GNIS Domestic Names** national text file, `Stream` features (mouth = primary point, source = source point) | `DomesticNames_National_Text.zip` from `prd-tnm.s3.amazonaws.com` (accessed 2026-10-07). NHDPlus HR was unusable that day (HTTP 502/504, more than 100 s per query) |
| All | Water body names | NHDPlus V2.1 waterbody `gnis_name`; otherwise GNIS `Lake` / `Reservoir` / `Bay` / `Swamp` points | EPA layer 4; GNIS file |

Other notes:
- **NWM Alaska coverage:** the NWM v3.1.6 Alaska RouteLink covers only Cook Inlet and the Copper River.
  The Yukon, Kuskokwim and the other large Alaska rivers are not in the NWM.
- **HI placeholder names:** NHDPlus V2.1 HI contains placeholder names such as `Ke360959` and `Hanak031`.
  Any name matching `^[A-Za-z]{2,6}\d{3,}$` is treated as blank (`valid_name()` in `domains.py`).
- **Exact GNIS spellings** are used everywhere: "Saint Lawrence River" (not "St."), "River Rouge" and
  "Río Grande de Loíza".

## 4. Layer 1: network names (level-path GNIS rule)

### CONUS (`river_names.py`), HI and PRVI (`domains.py: network_name()`)
1. Take the network's **outlet** segment, i.e. the segment whose `to` is 0.
2. If the outlet's ID is not an NHDPlus COMID, walk **up the RouteLink mainstem** until reaching a
   segment that is one. The RouteLink mainstem is defined at each junction as the upstream segment with
   the most segments above it. The walk is limited to 50 steps, and the number of steps is recorded in
   `name_steps_up` / `mainstem_steps_up`.
3. Read that COMID's NHDPlus **level path** (`levelpathi`). This is NHDPlus's own mainstem identifier.
   Fetch every flowline on that level path and sort by `hydroseq`, which increases going upstream.
4. **`name`** is the first non-blank GNIS name going upstream from the outlet.
5. **`mainstem_name`** is the most common non-blank GNIS name on the level path. It is a second
   opinion. For example, the Atchafalaya outlet's level path is mostly "Red River", and the San Joaquin
   outlet's first name is "New York Slough".
6. If there is no name, or no COMID within 50 steps, the network is `UNVERIFIED (lat, lon)` and is
   labelled by its outlet coordinates.

The same queries also record the outlet facts used to classify outlets (`terminalfl`, `dnhydroseq`, and
the FTYPE of the downstream flowline, e.g. `Coastline`). Those facts are not part of naming.

### AK (`domains.py: Hydro.gnis_name_for()`)
The AK hydrography has no level paths, so this rule uses GNIS stream points instead:
1. For each GNIS `Stream` in the AK box, find the RouteLink segment **nearest its source point** within
   `SOURCE_KM` = 25 km. The distance is large because sources are often on glaciers.
2. Keep the streams whose source segment lies **inside this network**.
3. For each stream, find its **mouth segment**:
   - Take the RouteLink segments within `MOUTH_KM` = 10 km of the GNIS mouth point that have the source
     segment upstream of them.
   - Of those, pick the one with the smallest subtree.
   - Then extend downstream through segments that have only one upstream segment.
4. The stream whose mouth segment drains the **largest share** of the network names it, provided that
   share is at least `NAME_MIN_SHARE` = 50%. Otherwise the network is `UNVERIFIED`.
   `name_rule = gnis_mouth_source`.

Result: 55 of the AK top 200 have a name. Examples are Susitna (121,538 segments), Copper (73,370) and
Matanuska (32,586).

## 5. Layer 2: sub-rivers (tributary mouths)

`subrivers.py` (CONUS) and `domains.py` (HI/PRVI with the same functions, AK with GNIS points) find the
**mouth segment** of each river on a candidate list. The statistics of the subtree above that mouth
become a "sub-river" row. The candidate list is encoded as `CANDIDATES` / `EXT_CANDIDATES`. It
combines the author's list, AI suggestions, and a section of "rivers important to major cities"; each
row records its `source`.

### Mouth rule (CONUS, HI, PRVI)
1. **Named set.** Collect the RouteLink segments whose COMID has a GNIS name in the candidate's
   `names` list. The list is a union, e.g. Neosho + Grand, Catawba + Wateree, or Green + Duwamish River +
   Duwamish Waterway. Only the candidate's NHDPlus VPUs are searched.
2. **Scope.** Search only the subtree above the **parent's** mouth, or the whole network when the parent
   is its own network. Parents are resolved first, so sub-sub-rivers nest. For example:
   Boulder Creek → Saint Vrain Creek → South Platte → Platte → Missouri → Mississippi.
3. **Box.** An optional lat/lon `box` on the mouth location encodes the list's state or city qualifiers,
   such as "Grand (MO)" or "Clear Creek (Denver)". These boxes are interpretations of the list, not data.
4. **Components.** Each named segment is joined to the next named segment downstream if there are at
   most `GAP` = 15 other segments between them. A component's root is its most-downstream segment.
5. **Follow to the mouth.** From the root, keep moving downstream while the next segment is one of:
   - named with one of the river's own names;
   - on the root's NHDPlus level path, and either blank or carrying a name that is not on the candidate
     list;
   - blank or not in NHDPlus, and with exactly one upstream segment.

   This step exists because big rivers are often blank along their polygon-mapped lower reaches. The
   "Wabash River" name ends near Lafayette, IN, but its level path (430001211) continues to the Ohio.
6. **Receiving river ("joins").** Use the name of the segment below the mouth. If that segment is blank,
   use the most common name on its level path. If neither gives a name, walk down at most `WALK` = 400
   segments to the first name; the unnamed stretch is reported as a **gap**.
7. **Choice and status.** Evaluate the `MAX_EVAL` = 8 largest components, starting with the largest.
   - Pick the largest component whose receiving river is the listed parent. If none joins the parent,
     pick the largest component in scope and report the river it actually joins (e.g. Black Warrior →
     Tombigbee).
   - Status values:
     - `confident`: no other qualifying component has at least `AMBIG` = 25% of the chosen one's segments.
     - `gap`: see step 6.
     - `not_in_parent`: nothing named lies in the parent's subtree.
     - `UNVERIFIED`: the choice is ambiguous.
8. **Primary rivers**, i.e. rivers that are their own networks: the largest named component in the VPUs.
   If nothing named lies below its mouth, the network outlet is the mouth. The row gives the network's
   rank.
9. **Special case:** the Upper Mississippi is the "Mississippi River" segment that enters the Cairo
   confluence segment where the Ohio joins. Its subtree includes the Missouri.

### AK sub-rivers (`domains.py: ak_resolve()`)
1. Candidate mouth segments lie within `SUB_MOUTH_KM` = 5 km of the GNIS mouth point, inside the
   parent's subtree.
2. A candidate is valid if a segment within 25 km of the GNIS source point lies upstream of it.
3. The valid candidate with the smallest subtree is the river's lowest segment. It is extended
   downstream through segments that have only one upstream segment. Status: `gnis_points`.

### Name-matching interpretations (CONUS)
- **Same name in different places** is resolved by VPU:
  - White: AR 11/08, IN 05, UT/CO 14
  - Green: KY 05, UT/WY 14, WA 17
  - Salt: KY 05, AZ 15
  - Grand: MO 10, MI 04, OK (as Neosho) 11
  - Cedar: IA 07, WA 17
  - James: SD 10, VA 02
  - Red River (south, 11/08) vs Red River of the North (09)
  - Bear River (UT, 16) vs Bear Creek (CO, 10)
- **Names absent from the layer:**
  - No flowline is named "American River"; only its North, Middle and South Forks are. They are
    followed down the level path to the Sacramento.
  - No flowline is named "Chicago River". The row uses the Chicago Sanitary and Ship Canal plus the
    North and South Branches.
- **Receiving river differs from the list** (this reflects the data and is not an error):
  - Monongahela → Allegheny; North Platte → South Platte
  - Black Warrior → Tombigbee; Cahaba, Coosa and Tallapoosa → Alabama
  - Flint → Chattahoochee; Yuba → Feather; Blue (MO) → "Old Channel Missouri River"
  - Virgin → a blank segment whose level path is mostly named "Pahranagat Wash" (probably the Overton
    Arm of Lake Mead; UNVERIFIED)
- **Red River (south)** flows into the Atchafalaya network (rank 5), not the Mississippi network.
- **Great Lakes:** all eight Great Lakes tributaries checked (Maumee, Saginaw, Grand (MI), Fox (WI),
  Genesee, Cuyahoga, Rouge, Milwaukee) lie inside the **Saint Lawrence** network (outlet 25293410).
  NHDPlus routes them through the lakes. In each case the segment below the mouth carries the name of
  the lake's *outflow* channel:
  - Lake Erie (Maumee, Cuyahoga): Niagara River
  - Lake Michigan (Fox, Grand) and Lake Huron (Saginaw): Saint Clair River
  - Rouge: Detroit River
  - Lake Ontario (Genesee): Saint Lawrence River

  This is the same thing that happens at Lake Pontchartrain, but at the Great Lakes the name belongs to
  the outflow and not to an inflow, so it causes no misnaming.

CONUS results (2026-10-06): 203 rows (160 sub-rivers, 43 primary).
- 199 `confident`.
- 3 `gap`: Pecos, Pend Oreille and Kootenai.
  - The Pecos ends 3 non-NHDPlus border segments above the Rio Grande.
  - The Kootenai and Pend Oreille mouths are at the Canadian border, followed by 135 and 23 unnamed
    segments respectively.
- 1 `not_in_parent`: the Santa Cruz (AZ) is its own network (rank 62) and is not connected to the Gila.

## 6. Layer 3: lake-outlet and outlet-confluence renames

`domains.py` applies these rules to the top networks of every domain: CONUS 500, AK 200, HI 100 and
PRVI 100 (`N_TOP`). For each network:

```
lake_rule(outlet)
  ├─ no lake qualifies ──────────────┐
  ├─ lake qualifies, name kept       │  (named_for_outflow)
  │    └─────────────────────────────┤
  │                                  └─▶ confluence_rule(outlet) ─▶ rename, or keep
  └─ lake qualifies, renamed (or kept only because the lake has no name: lake_unnamed)
```

### 6.1 What counts as a water body
`Hydro.water_of()` decides whether a segment lies in a water body, in this order:
1. The RouteLink **`NHDWaterbodyComID`**, if it is not −9999. The author called this field "isn't
   particularly well curated", but it is the field he suggested using.
2. Otherwise (CONUS, HI, PRVI only), the NHDPlus flowline's **`WBAreaComID`**, when that area's
   `WBArea_FType` is LakePond (390), Reservoir (436) or Estuary (493). This catches artificial paths
   through polygons that RouteLink does not mark as lakes.

`Hydro.members(start, W)` collects the segments of water body W connected to `start`, walking upstream.

### 6.2 Lake-outlet rule (`lake_rule()`)
This rule was written for the Tchefuncte case.
- **Cause:** in NHDPlus V2 the artificial paths through Lake Pontchartrain carry the GNIS name
  "Tchefuncte River", and the lake polygon (COMID 167166635) has no GNIS name.
- **Effect:** the level-path walk of Layer 1 passes through the lake and reports "Tchefuncte River"
  for a network that drains the Amite, Tickfaw, Tangipahoa, Tchefuncte and the whole lake.

Steps:
- **a. Walk.** From the outlet, walk up the RouteLink mainstem for at most `LAKE_WALK` = 50 segments.
- **b. Candidates.** Each distinct water body W met on the walk is a candidate, in walk order. Its
  drainage D is the subtree of the first walk segment that lies in W.
- **c. Capture test.** W must meet all three conditions; otherwise move to the next candidate:
  - D is at least `LAKE_MIN_DRAIN` = 50% of the network.
  - W has at least 2 **inflows** with at least `LAKE_MIN_SHARE` = 5% of D each. An inflow is a segment
    outside W that flows into a segment of W.
  - The largest inflow carries less than `LAKE_MAX_SHARE` = 75% of D. Above that, the lake is just a
    widening of one river.
- **d. Where the name came from.** The **first** W that passes c decides the result:
  - **Renamed** if the network's name is the label of one of W's inflows (i.e. the name came from
    upstream of the lake) **and** is not carried by any segment of the outflow channel between the
    outlet and W. A network that is `UNVERIFIED` is also renamed.
  - **Kept** otherwise, with flag `named_for_outflow`. This covers networks named after the lake's
    outflow, such as the Jordan River below Utah Lake, the Housatonic and the Santa Ana. AK networks are
    always kept by this test, because AK has no NHDPlus attributes to check the outflow channel.
- **e. Lake name** (`Hydro.waterbody_name()`):
  1. The NHDPlus V2.1 waterbody GNIS name (EPA layer 4), when not AK and the ID is a real COMID.
  2. Otherwise the GNIS `Lake` / `Reservoir` / `Bay` / `Swamp` points within
     max(`LAKE_GNIS_KM` = 3 km, the spread of W's segments) of the length-weighted centroid of W's
     segments. Each segment's length is a vote for its nearest point, and the point with the most length
     wins. Flag `lake_name_from_gnis_point`; `lake_name_source` records the GNIS ID and the vote share.
     Lake Pontchartrain is named this way: GNIS 1627974, nearest point to 47% of the channel length.
  3. If neither gives a name, the network keeps its name with flag `lake_unnamed`. The confluence rule
     is not tried in this case.
- **f. Inflow labels** (`inflow_label()`):
  - Each inflow with at least `LABEL_MIN_SHARE` = 5% of D is labelled with the **most frequent** GNIS
    name on its NHDPlus level path *upstream of the inflow point*. The most frequent name is used, not
    the first, because a connecting channel takes the name of the river that dominates it. The inflow
    through Pass Manchac, for example, is labelled "Amite River".
  - In AK the label comes from the GNIS stream rule instead.
  - An inflow with no name gets flag `inflow_unnamed` and is left out of the display name.
- **g. New name:** `"<lake name> (<inflow 1>, <inflow 2>, …)"`, with the largest inflow first and at
  most `LABEL_MAX` = 5 shown ("…" if more). With no named inflows, the name is just the lake name.
- **h. Tributaries below the lake.** A tributary that joins the outflow channel between W and the outlet
  and holds at least `BELOW_FLAG_SHARE` = 20% of the network gets flag `tributary_below_lake`. It is
  listed in `below_lake`. Example: the Bogue Chitto (24.5%) joins below Lake Pontchartrain at the
  Rigolets, through Pearl River distributaries.

### 6.3 Outlet-confluence rule (`confluence_rule()`)
This rule was written for the Buffalo Bayou and Neches cases. It is tried when the lake rule did not
rename the network.
1. Walk up the RouteLink mainstem from the outlet for at most `CONF_WALK` = 10 segments.
2. At each junction, list the upstream branches holding at least `CONF_MIN_SHARE` = 15% of the network.
   The **first** junction with two or more such branches decides the result.
3. Label each of those branches with the **first** GNIS name going up its level path. The rule gives up
   if any branch is unnamed or two branches have the same label.
4. Rename only if the current name belongs to a branch that is **not the largest**. AK is never renamed
   by this rule.
5. New name:
   - If a water body lies at the junction, or within `CONF_WATER_WALK` = 10 mainstem segments of the
     outlet, and it has a name: `"<water body> (<largest>, <next>, …)"`. Example: "Sabine Lake (Sabine
     River, Neches River)".
   - Otherwise: `"<largest> and <other>"`. Example: "San Jacinto River and Buffalo Bayou".

The rule is mechanical, and several of its 28 renames need review (see section 14).

## 7. Splitting lake tributaries into separate rows

Renaming a network to "Lake Pontchartrain (…)" fixes its label, but the lake's tributaries also need to
be listed separately. `lake_inflow_rows()` does that. For every **renamed** network, under either rule:
- every named inflow, i.e. every lake-rule inflow with at least 5% of D, and every confluence branch;
- every named tributary flagged `tributary_below_lake`

becomes a sub-river row in `results/T_subrivers_ext.csv`. Each row has `status = lake_inflow`, and its
**mouth is the inflow segment**, the segment entering the water body or the junction. A mouth that
another row already uses is skipped.

| Network | Rows created |
|---|---|
| Lake Pontchartrain (#33) | Amite River 4,697 segments (everything entering through Pass Manchac: Lake Maurepas, the Amite and the Tickfaw); Tangipahoa 1,208; Tchefuncte 564; Bogue Chitto 2,327 (below the lake) |
| San Jacinto River and Buffalo Bayou (#82) | San Jacinto 1,518; Buffalo Bayou 415 (now only its own channel through Houston) |
| Sabine Lake (#29) | Sabine River 5,837; Neches River 5,641 |
| Lake Washington (#212) | Cedar River 205; Sammamish River 193 |

The Tickfaw has no row of its own because it enters Lake Maurepas, not Lake Pontchartrain. The rule
only looks at the first water body on the outlet's mainstem; chained lakes upstream are not split.

Totals in `T_subrivers_ext.csv`: 95 `lake_inflow` rows (CONUS 88, HI 5, PRVI 2), alongside 35 other
AK/HI/PRVI sub-rivers.

## 8. Separate vs merged networks around bays and lakes

The author asked which estuaries are one network and which are several. Two reports answer this.

**`results/bay_networks.csv`** (`bay_report()`) covers 13 water bodies the author named (`BAYS`). For
each one it lists:
- the networks among the listed (top N) ones whose outlets lie within a radius of the water body's GNIS
  point;
- the network containing the segment nearest that point.

These lists are approximate. A river at the far end of a large water body can be missed, e.g. the
Susquehanna for Chesapeake Bay.

| Water body | Result |
|---|---|
| Galveston Bay | **Separate**: Trinity (#32), San Jacinto + Buffalo Bayou (#82), Clear Creek (#302). The bay is not routed |
| Sabine Lake | **Merged**: one network (#29) |
| Lake Pontchartrain | **Merged** (#33) |
| Mobile Bay | Separate: Mobile (#6), Tensaw (#196), Blakeley (#458) |
| Chesapeake Bay | Separate: 29 listed networks within 150 km, incl. Potomac (#16), James (#17), York (#52), Rappahannock (#59) |
| Delaware Bay | Separate: Delaware (#21) and 6 others |
| San Francisco Bay | Separate: Sacramento (#9), San Joaquin as "New York Slough" (#14), Napa, Petaluma, … |
| Puget Sound | Separate: 10 within 100 km |
| Pamlico Sound | Separate: Neuse (#34), Pamlico (#48), Alligator (#499) |
| Albemarle Sound | Separate: 4 small networks within 60 km |
| Great Salt Lake | Separate: Bear (#37), Jordan (#74), Weber (#84), … |
| Lake Okeechobee | Inside the Saint Lucie River network (#68) |
| Lake Tahoe | Inside the Truckee River network (#76) |

**`results/waterbody_networks.csv`** (`waterbody_report()`) covers every water body that lies on the
outlet path (within 10 mainstem segments) of **two or more** listed networks, or of a renamed one, in
every domain. It lists the networks and, for renamed ones, the merged inflows.

## 9. Output columns and flags

### `results/T_basins*.csv` (one row per top network)
| Column | Meaning |
|---|---|
| `river_name` | Layer 1 name (never overwritten) |
| `mainstem_name` | Most common GNIS name on the outlet's level path |
| `name_steps_up` | RouteLink mainstem steps from the outlet to the first NHDPlus COMID |
| `display_name` | Name to show (Layer 3 result) |
| `name_rule` | `levelpath_gnis` \| `gnis_mouth_source` \| `lake_outlet` \| `outlet_confluence` \| `unverified` |
| `name_note` | Plain-text explanation of a rename, with the old name and the branch shares |
| `name_source` | Service and rule that supplied the Layer 1 name |

CONUS `name_rule` counts (top 500): `levelpath_gnis` 406, `unverified` 48, `outlet_confluence` 26,
`lake_outlet` 20.

### `results/lake_renames.csv` (one row per network a Layer 3 rule fired on: 102 rows, 64 renamed)
| Column | Meaning |
|---|---|
| `domain`, `rank`, `outlet_feature_id` | Which network |
| `renamed`, `previous_name`, `display_name`, `rule` | What happened |
| `walk_step` / `junction_step`, `junction_feature_id` | Where on the mainstem the water body or junction is |
| `drain_share`, `largest_inflow_share` | D / network, and the largest inflow / D |
| `lake_id`, `lake_name`, `lake_name_source`, `lake_segments` | The water body |
| `inflows` | `Name (share%, inflow feature_id); …` |
| `below_lake` | Tributaries of at least 20% joining between the lake and the outlet |
| `n_inflows`, `n_inflows_ge_min`, `outflow_names` | Evidence for the capture test and the outflow test |
| `flags` | See below |

### Flags
| Flag | Count | Meaning |
|---|---:|---|
| `named_for_outflow` | 32 | Lake captures the network, but the name belongs to the outflow; kept |
| `inflow_unnamed` | 34 | At least one inflow of 5% or more has no GNIS name |
| `lake_name_from_gnis_point` | 23 | Lake name came from the nearest-GNIS-point vote, not NHDPlus |
| `lake_unnamed` | 6 | No lake name found; network kept its name |
| `tributary_below_lake` | 4 | A tributary of at least 20% joins below the lake |

### `results/T_subrivers_ext.csv`
Same columns as `subrivers.csv`, plus `domain`. Lake-inflow rows have `status = lake_inflow`,
`group = "Lake and bay inflows"`, `parent_label` = the renamed network, `joins` = the lake name, and
`method` = `inflow` or `joins below the water body`.

## 10. Results

### All 64 renames (`lake_renames.csv`, 2026-10-07)
CONUS 46 (20 lake-outlet, 26 confluence), AK 1, HI 6 (4 lake, 2 confluence), PRVI 11.

| Domain | # | Rule | Previous name | Display name | Inflows / branches (share) | Flags |
|---|---:|---|---|---|---|---|
| CONUS | 29 | confluence | Neches River | Sabine Lake (Sabine River, Neches River) | Sabine River (50.7%); Neches River (49.0%) |  |
| CONUS | 33 | lake | Tchefuncte River | Lake Pontchartrain (Amite River, Tangipahoa River, Tchefuncte River) | Amite River (67.2%); Tangipahoa River (17.3%); Tchefuncte River (8.1%) | lake_name_from_gnis_point, tributary_below_lake |
| CONUS | 82 | confluence | Buffalo Bayou | San Jacinto River and Buffalo Bayou | San Jacinto River (78.4%); Buffalo Bayou (21.4%) |  |
| CONUS | 85 | confluence | Tule River | Mill Creek and Tule River | Mill Creek (63.7%); Tule River (34.6%) |  |
| CONUS | 95 | confluence | Piscataqua River | Pawtuckaway River and Piscataqua River | Pawtuckaway River (51.0%); Piscataqua River (47.9%) |  |
| CONUS | 98 | confluence | San Simon Wash | Vamori Wash and San Simon Wash | Vamori Wash (76.8%); San Simon Wash (20.7%) |  |
| CONUS | 119 | lake | Thomas Creek | Goose Lake (Thomas Creek, Drews Creek, Dry Creek) | Thomas Creek (39.6%); Drews Creek (25.1%); Dry Creek (5.8%) |  |
| CONUS | 121 | lake | Biloxi River | Big Lake (Biloxi River, Tchoutacabouffa River, Bernard, Bayou) | Biloxi River (54.0%); Tchoutacabouffa River (33.3%); Bernard) | lake_name_from_gnis_point |
| CONUS | 122 | confluence | Mimbres River | Silva Creek and Mimbres River | Silva Creek (59.1%); Mimbres River (33.1%) |  |
| CONUS | 123 | confluence | Puyallup River | White River and Puyallup River | White River (54.7%); Puyallup River (43.3%) |  |
| CONUS | 135 | confluence | Lavaca River | Navidad River and Lavaca River | Navidad River (55.4%); Lavaca River (43.0%) |  |
| CONUS | 142 | lake | Deep Creek | Hart Lake (Deep Creek, Honey Creek, Fish Creek) | Deep Creek (55.9%); Honey Creek (28.8%); Fish Creek (12.3%) |  |
| CONUS | 166 | confluence | Matanzas River | Tolomato River and Matanzas River | Tolomato River (70.2%); Matanzas River (29.2%) |  |
| CONUS | 168 | confluence | San Cristobal Wash | Growler Wash and San Cristobal Wash | Growler Wash (79.6%); San Cristobal Wash (18.2%) |  |
| CONUS | 191 | lake | Mauvais Coulee | Lake Alice (Mauvais Coulee) | Mauvais Coulee (64.7%); unnamed inflow at 48.350) | inflow_unnamed |
| CONUS | 212 | confluence | Sammamish River | Lake Washington (Cedar River, Sammamish River) | Cedar River (50.0%); Sammamish River (47.1%) |  |
| CONUS | 228 | confluence | Duckwater Creek | Currant Creek and Duckwater Creek | Currant Creek (53.6%); Duckwater Creek (44.9%) |  |
| CONUS | 244 | confluence | Elkhorn Slough | Alisal Slough and Elkhorn Slough | Alisal Slough (68.5%); Elkhorn Slough (31.2%) |  |
| CONUS | 256 | confluence | Salt Creek | Nogal Arroyo and Salt Creek | Nogal Arroyo (75.1%); Salt Creek (23.0%) |  |
| CONUS | 298 | lake | Barton River | Lake Memphremagog (Clyde River, Barton River, Black River) | Clyde River (37.6%); Barton River (30.4%); Black River (20.7%) |  |
| CONUS | 309 | confluence | Wye River | Wye East River and Wye River | Wye East River (56.8%); Wye River (41.1%) |  |
| CONUS | 323 | confluence | Chechessee River | Colleton River and Chechessee River | Colleton River (51.3%); Chechessee River (47.9%) |  |
| CONUS | 355 | lake | Bayou Blue | Wax Lake (Bayou Blue, Hog Bayou, Leopard Bayou) | Bayou Blue (48.3%); Hog Bayou (31.3%); Leopard Bayou (7.0%) |  |
| CONUS | 372 | lake | Waterton River | Upper Waterton Lake (Waterton River, Boundary Creek, Street Creek) | Waterton River (57.1%); Boundary Creek (22.0%); Street Creek (6.3%) | lake_name_from_gnis_point |
| CONUS | 388 | lake | UNVERIFIED (41.281, -120.057) | Lower Lake (Bare Creek) | Bare Creek (21.9%); unnamed inflow at 41.205); unnamed inflow at 41.227); unnamed inflow at 41.208) | inflow_unnamed |
| CONUS | 393 | lake | UNVERIFIED (29.461, -89.988) | Round Lake | unnamed inflow at 29.568); unnamed inflow at 29.559); unnamed inflow at 29.557); unnamed inflow at 29.571) | inflow_unnamed, tributary_below_lake |
| CONUS | 398 | lake | UNVERIFIED (31.782, -108.532) | Playas Lake | unnamed inflow at 31.943); unnamed inflow at 31.866); unnamed inflow at 31.919) | inflow_unnamed |
| CONUS | 400 | confluence | Shrewsbury River | Navesink River and Shrewsbury River | Navesink River (74.6%); Shrewsbury River (24.9%) |  |
| CONUS | 401 | confluence | Broadkill River | Sowbridge Branch and Broadkill River | Sowbridge Branch (39.1%); Broadkill River (24.3%) |  |
| CONUS | 403 | lake | UNVERIFIED (40.803, -114.999) | Snow Water Lake (Johnson Creek) | unnamed inflow at 40.743); unnamed inflow at 40.770); unnamed inflow at 40.758); unnamed inflow at 40.808); Johnson Creek (8.9%) | inflow_unnamed |
| CONUS | 404 | confluence | Red Creek | Hay Reservoir (Bush Creek, Red Creek) | Bush Creek (79.3%); Red Creek (19.5%) |  |
| CONUS | 407 | confluence | Bush River | Otter Point Creek and Bush River | Otter Point Creek (53.9%); Bush River (32.3%) |  |
| CONUS | 409 | confluence | Belly River | Mokowanis River and Belly River | Mokowanis River (47.6%); Belly River (35.5%) |  |
| CONUS | 412 | lake | UNVERIFIED (41.749, -120.147) | Upper Lake (Bidwell Creek, Venning Creek) | unnamed inflow at 41.829); Bidwell Creek (11.5%); Venning Creek (6.7%) | inflow_unnamed |
| CONUS | 415 | lake | Rush Creek | Mono Lake (Rush Creek) | Rush Creek (74.2%); unnamed inflow at 38.085); unnamed inflow at 38.066) | inflow_unnamed |
| CONUS | 422 | confluence | Back River | Hampton Lake (Southwest Branch Back River, Back River) | Southwest Branch Back River (42.1%); Back River (31.4%) | lake_name_from_gnis_point |
| CONUS | 428 | confluence | East Carancahua Creek | West Carancahua Creek and East Carancahua Creek | West Carancahua Creek (46.4%); East Carancahua Creek (35.3%) |  |
| CONUS | 430 | lake | Walker River | Walker Lake (Walker River) | Walker River (57.2%); unnamed inflow at 38.761) | inflow_unnamed |
| CONUS | 436 | lake | UNVERIFIED (29.589, -91.804) | Lake Tom | unnamed inflow at 29.583); unnamed inflow at 29.561); unnamed inflow at 29.584) | inflow_unnamed, lake_name_from_gnis_point |
| CONUS | 438 | confluence | Guadalupe River | Vasona Reservoir (Los Gatos Creek, Guadalupe River) | Los Gatos Creek (51.0%); Guadalupe River (46.3%) |  |
| CONUS | 441 | lake | Fish Creek | Swan Lake (Fish Creek, Bald Mountain Creek) | Fish Creek (49.5%); Bald Mountain Creek (29.7%); unnamed inflow at 41.847) | inflow_unnamed, tributary_below_lake |
| CONUS | 459 | lake | UNVERIFIED (29.620, -91.870) | Bayou Platte | unnamed inflow at 29.585); unnamed inflow at 29.590) | inflow_unnamed, lake_name_from_gnis_point |
| CONUS | 463 | confluence | Garcitas Creek | Arenosa Creek and Garcitas Creek | Arenosa Creek (47.1%); Garcitas Creek (46.4%) |  |
| CONUS | 468 | lake | Bayou Magill | Bobs Lakes (Bayou Magill) | Bayou Magill (64.0%); unnamed inflow at 29.952); unnamed inflow at 29.961) | inflow_unnamed, lake_name_from_gnis_point |
| CONUS | 475 | confluence | Roberts River | Lane Bay (Lane River, Roberts River) | Lane River (81.5%); Roberts River (17.8%) | lake_name_from_gnis_point |
| CONUS | 494 | lake | Pia Oik Wash | Menagers Lake (Siovi Shuatak Wash, Pia Oik Wash, Ali Chuk Wash) | Siovi Shuatak Wash (41.7%); Pia Oik Wash (33.1%); Ali Chuk Wash (9.4%); unnamed inflow at 31.826) | inflow_unnamed |
| AK | 147 | lake | UNVERIFIED (59.416, -153.913) | Kirschner Lake | unnamed inflow at 59.429); unnamed inflow at 59.433); unnamed inflow at 59.426) | inflow_unnamed, lake_name_from_gnis_point |
| HI | 10 | confluence | Kapaa Stream | Kealia Stream and Kapaa Stream | Kealia Stream (48.7%); Kapaa Stream (35.9%) |  |
| HI | 18 | lake | Waikapu Stream | Keālia Pond (Waikapu Stream) | Waikapu Stream (73.3%); unnamed inflow at 20.801); unnamed inflow at 20.785) | inflow_unnamed, lake_name_from_gnis_point |
| HI | 31 | lake | UNVERIFIED (21.991, -159.341) | De Mello Reservoir | unnamed inflow at 21.997); unnamed inflow at 22.002) | inflow_unnamed, lake_name_from_gnis_point |
| HI | 39 | confluence | Kawiwi Stream | Kaupuni Stream and Kawiwi Stream | Kaupuni Stream (74.6%); Kawiwi Stream (23.7%) |  |
| HI | 43 | lake | UNVERIFIED (21.891, -159.489) | Aepoeha Reservoir | unnamed inflow at 21.903); unnamed inflow at 21.906); unnamed inflow at 21.896); unnamed inflow at 21.894) | inflow_unnamed |
| HI | 79 | lake | UNVERIFIED (21.954, -160.115) | Keawanui Bay | unnamed inflow at 21.951); unnamed inflow at 21.956) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 19 | lake | Río Toa Vaca | Lago Guayabal (Río Toa Vaca) | Río Toa Vaca (47.9%); unnamed inflow at 18.106) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 26 | lake | UNVERIFIED (17.982, -66.016) | Lago Patillas (Río Marín) | unnamed inflow at 18.033); Río Marín (24.2%) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 30 | lake | UNVERIFIED (17.699, -64.785) | Fredensborg Pond | unnamed inflow at 17.724); unnamed inflow at 17.723) | inflow_unnamed, lake_name_from_gnis_point, tributary_below_lake |
| PRVI | 67 | lake | UNVERIFIED (17.724, -64.653) | Great Pond | unnamed inflow at 17.727); unnamed inflow at 17.729); unnamed inflow at 17.729); unnamed inflow at 17.729) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 72 | lake | UNVERIFIED (18.127, -67.179) | Laguna Joyuda | unnamed inflow at 18.129); unnamed inflow at 18.137); unnamed inflow at 18.126) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 77 | lake | UNVERIFIED (18.090, -65.513) | Laguna Playa Grande | unnamed inflow at 18.090); unnamed inflow at 18.095) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 80 | lake | UNVERIFIED (18.434, -65.964) | Laguna de Pinoñes | unnamed inflow at 18.445); unnamed inflow at 18.439); unnamed inflow at 18.436); unnamed inflow at 18.429); unnamed inflow at 18.428) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 83 | lake | UNVERIFIED (17.708, -64.704) | Manchenil Bay | unnamed inflow at 17.712); unnamed inflow at 17.713) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 88 | lake | UNVERIFIED (17.947, -66.257) | Mar Negro | unnamed inflow at 17.948); unnamed inflow at 17.948) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 89 | lake | UNVERIFIED (18.125, -65.375) | Laguna Yanuel | unnamed inflow at 18.127); unnamed inflow at 18.130) | inflow_unnamed, lake_name_from_gnis_point |
| PRVI | 93 | lake | UNVERIFIED (18.120, -65.562) | Laguna El Pobre | unnamed inflow at 18.118); unnamed inflow at 18.117) | inflow_unnamed, lake_name_from_gnis_point |

### Lake captured the network but the name was kept (38)
These networks passed the capture test, but kept their name for one of two reasons:
- Their name is the outflow's name (`named_for_outflow`). Examples: Housatonic, Santa Ana, Salton Sea,
  Jordan, Mermentau, Presumpscot, Gunpowder, Hackensack, Elwha; AK: Beluga, Eyak, Kasilof, Eklutna,
  Bradley; PRVI: Río Grande de Arecibo, Caño de Martín Peña.
- The lake has no name (`lake_unnamed`): CONUS #277, #394 (Rock Creek), #423 (Malheur Slough); AK #107,
  #198; PRVI #66.

## 11. Who uses the names

- **Explorer** (`explorer/scripts/build_codes.py`): a network's `name` is the `display_name`. Renamed
  networks keep the old name in `level_path_name` and the rule in `name_rule` (see
  `explorer/DATA_CONTRACT.md`, "Names").
- **`repro/diffusive_mainstem`** reads names from `network_stats/results/T_basins.csv` (since
  2026-10-20; before that it read the paper repo's `notes/proposed_tables/T_basins.csv`, a
  byte-identical copy). Changing names or columns here changes that screen's network names too.
- **Paper** (`~/git/troute_paper`): the draft proposes table **T2 "NWM basins"** built from
  `T_basins`. There is no wording yet about naming, and no figure or text on splitting lake tributaries.
  Copies of the tables are in `notes/proposed_tables/`.

## 12. Reproducibility

Every web lookup is frozen in a snapshot, so `run.sh` makes no live queries.

| Snapshot | Written by | Holds | Checked by |
|---|---|---|---|
| `river_names.json` (committed) | `river_names.py` (live; not in `run.sh`) | Layer 1 CONUS names and outlet facts | `check.py` / `expected/expected.json` |
| `subriver_gnis.json` (committed) | `subrivers.py --refresh` | Every WFS name query (with its `resultType=hits` count, so truncation fails) and per-COMID name | SHA-256 in `expected/subrivers_expected.json` |
| `domains_snapshot.json` (release asset, 4.8 MB, fetched by `tools/fetch_bundle.py network-stats`) | `domains.py --refresh` | Every EPA query answer and every GNIS feature returned | SHA-256 `5af3611d…` in `expected/domains_expected.json` |

Offline runs reproduce the refresh runs byte for byte. The status on 2026-10-07 was that
`run.sh` passes 1,280 of 1,280 checks. Any refresh that changes a snapshot changes its SHA-256, and
`check.py` fails until the expected file is updated, with a reason given in the README.

## 13. History and the author's decisions

| Date | Event |
|---|---|
| 2026-10-06 | Layer 1 (`river_names.py`, CONUS top 500) and Layer 2 (`subrivers.py`, 203 rows) built and checked |
| 2026-10-06/07 | Author (troute_paper `notes/questions_batch_02_ANSWERED.md` L202): *"The Tchefuncte River flowing into Lake Ponchartrain is capturing all tributaries to that lake. We might need to fix that. The RouteLink file has lake parameter identifying portions of the network considered to be with a lake, which we might use (it isn't particularly well curated.)"* |
| same | Author (L204): *"The ability select lakes or bodies of water with all streams flowing into them (Delaware bay, Lake pontchartrain, Salt Lake, Tahoe, etc) would be an additional capability to consider in a draft form, perhaps another branch."* |
| 2026-10-07 | Author asked for the full domain; said Buffalo Bayou "has too many streams labelled to it" and that "the Sabine is lumped into the Neches". `domains.py` added: AK/HI/PRVI names, the lake-outlet and outlet-confluence rules, lake-inflow sub-rivers, and the bay reports |
| 2026-10-07 | NHDPlus HR service down, so AK names fell back to GNIS Domestic Names. Author: *"Let's do this again tomorrow and see if the service is back up"* |
| later | Author on the water-body selection feature (`questions_batch_03_ANSWERED.md` L54–58): *"Finish what you are doing first, then it doesn't need to be a branch."* It goes on main |
| 2026-10-20 | `diffusive_mainstem` switched to reading `network_stats/results/T_basins.csv` |

## 14. Open items

1. **Author review of the 64 renames** (`lake_renames.csv`; troute_paper `notes/tasks.md` L172–174,
   a JH task). This has been raised repeatedly with no answer logged. The weakest renames are the
   mechanical confluence names whose second branch is a minor creek or a misreading of the geography:
   - "Mill Creek and Tule River" (#85)
   - "Silva Creek and Mimbres River" (#122)
   - "Pawtuckaway River and Piscataqua River" (#95)
   - "Sowbridge Branch and Broadkill River" (#401)
   - "Vamori Wash and San Simon Wash" (#98)
   - "Wye East River and Wye River" (#309)

   Lake renames with no named inflow, such as "Round Lake", "Lake Tom" and "Bayou Platte", replace an
   UNVERIFIED name with a lake that may be only a local feature.
2. **AK names**: rerun `domains.py --refresh` and `explorer/scripts/build_places.py --refresh` once the
   USGS NHDPlus HR service works (`tasks.md` L175–177). Only 55 of the AK top 200 are named.
3. **Water-body selection** ("select a lake with all inflowing streams") in the explorer: planned, not
   started, to go on main.
4. **Paper wording** for naming and for the lake-tributary split: not drafted.

## 15. Known weaknesses

- **Distributaries and sloughs:** the Layer 1 name can belong to a distributary or slough at the outlet.
  Examples are "New York Slough" (San Joaquin, #14) and "South Santee River". Check `mainstem_name`.
- **Unnamed networks:** 48 of the CONUS top 500 stay `UNVERIFIED (lat, lon)`.
- **Only one water body is examined:** the lake rule looks only at the **first** qualifying water body
  within 50 mainstem segments of the outlet. Chains of lakes and lakes higher in the network are not
  examined.
- **The 75% cutoff decides the type of lake:** a lake with one dominant inflow (75% or more) is treated
  as a widening of that river and is not renamed. This is deliberate, but the cutoff is a judgement.
- **Fixed branch labels:** confluence branches are labelled with the *first* name going up, and lake
  inflows with the *most frequent* name. Either choice can pick a local name.
- **Unreliable lake flag:** `NHDWaterbodyComID` is not well curated (the author's words). The
  `WBAreaComID` fallback adds estuaries, which can name a network after a bay.
- **GNIS-point lake names:** names from the nearest-point vote (23 cases) can pick a nearby smaller
  feature. `lake_name_source` gives the vote share; Lake Pontchartrain's is 47%.
- **AK:** no outflow-name test (so lake renames are rare, 1 case) and no confluence rule.
- **Approximate bay lists:** `bay_networks.csv` uses radius lists, which can miss rivers at the far end
  of a large bay.

## 16. Constants

| Constant | Value | File | Used for |
|---|---:|---|---|
| mainstem walk for a COMID | 50 | river_names.py / domains.py | Layer 1 |
| `MOUTH_KM` | 10 km | domains.py | AK network name: GNIS mouth to segment |
| `SOURCE_KM` | 25 km | domains.py | AK: GNIS source to segment |
| `NAME_MIN_SHARE` | 0.5 | domains.py | AK: share of network the naming stream must drain |
| `SUB_MOUTH_KM` | 5 km | domains.py | AK sub-river mouths |
| `GAP` | 15 | subrivers.py | Unnamed segments bridged between named ones |
| `WALK` | 400 | subrivers.py | Walk to find the receiving river |
| `MAX_EVAL` | 8 | subrivers.py | Components evaluated |
| `AMBIG` | 0.25 | subrivers.py | Second-component ratio that makes a row ambiguous |
| `N_TOP` | 500 / 200 / 100 / 100 | domains.py | Networks examined: CONUS / AK / HI / PRVI |
| `LAKE_WALK` | 50 | domains.py | Mainstem segments searched for a lake |
| `LAKE_MIN_DRAIN` | 0.5 | domains.py | Lake must drain this share of the network |
| `LAKE_MIN_SHARE` | 0.05 | domains.py | Inflow counts toward "at least 2 inflows" |
| `LAKE_MAX_SHARE` | 0.75 | domains.py | Largest inflow must be below this share |
| `LABEL_MIN_SHARE` | 0.05 | domains.py | Inflow appears in the name and gets a row |
| `LABEL_MAX` | 5 | domains.py | Inflows shown in the name |
| `BELOW_FLAG_SHARE` | 0.20 | domains.py | Below-lake tributary flag |
| `LAKE_GNIS_KM` | 3 km | domains.py | Minimum GNIS search radius for lake names |
| `CONF_WALK` | 10 | domains.py | Junctions examined above the outlet |
| `CONF_MIN_SHARE` | 0.15 | domains.py | Branch share for the confluence rule |
| `CONF_WATER_WALK` | 10 | domains.py | Water body near the outlet names a confluence |
| `WATER_FTYPES` | LakePond 390, Reservoir 436, Estuary 493 | domains.py | NHDPlus areas counted as water bodies |
