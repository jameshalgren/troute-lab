# Public NWM parameter archives: NOHRSC `owp_files` and NCEP `nwm.v3.1.7`

*AI-assembled (Claude, 2026-11-10) for James Halgren at the request of the troute-paper
session; not yet reviewed. Every listing, size, date, checksum and netCDF
header below was read from the live servers (or, for one tarball, from a local copy with
the published SHA-256) on **2026-11-10** unless another date is given. Quotes are
verbatim. My own interpretation is marked "Note (AI):". Where the purpose of a file is not
documented anywhere I found, it says "undocumented" and gives only what the file shows.*

Companion files in this folder:
- `headers/`: `ncdump -h` output for every netCDF file that could be read (261 files):
  `headers/v2.1/`, `headers/v3.0/`, `headers/coastal_v3.0/` (from the tarballs),
  `headers/ncep_v3.1.7/` (read by HTTP byte-range from NCEP, no full download),
  `headers/hydrofabric_*/gdb_layers.txt` (File Geodatabase layer schemas).
- `listings/`: machine-readable listings. `nohrsc_owp_files.tsv` (every NOHRSC
  file, HTTP size and Last-Modified), `ncep_nwm.v3.1.7_tree.tsv` (all 27,301
  NCEP files), `members_*.json` (every tarball member with size, tar date, MD5, SHA-256),
  `ncep_parm_hashes.txt` (SHA-256 and MD5 of the 17 small routing files in NCEP
  `parm/domain*/`).
- `raw/nohrsc_text/` (NOHRSC READMEs and the small text members of each tarball) and
  `raw/ncep_text/` (NCEP namelists and other small text files).
- `build/main_template.md` (the hand-written text of this catalog), `scripts/`, and
  `rebuild.sh`, which regenerates the tables and this file (see `README.md`).

## Contents
1. [Key findings](#1-key-findings)
2. [Overview of the archives](#2-overview-of-the-archives)
3. [NOHRSC `owp_files`](#3-nohrsc-owp_files)
4. [Descriptions of each file type](#4-descriptions-of-each-file-type)
5. [NCEP `nwm.v3.1.7`](#5-ncep-nwmv317)
6. [Namelists: routing-relevant options by configuration](#ncep-namelists)
7. [Cross-walk: which file is where](#7-cross-walk-which-file-is-where)
8. [Open questions](#8-open-questions)
9. [Method, downloads, and contributions from other sessions](#9-method-downloads-and-contributions-from-other-sessions)
10. [Sources](#10-sources)

## 1. Key findings

1. **The CONUS `LAKEPARM` file is published only in the NOHRSC v3.0 tarball.** All 10
   CONUS `hydro.namelist` files in NCEP `nwm.v3.1.7/parm/` read
   `route_lake_f = './DOMAIN/LAKEPARM_CONUS.nc'`. The 4 Hawaii ones read
   `LAKEPARM_HI.nc` and the 4 Puerto Rico ones `LAKEPARM_PRVI.nc`. None of these three
   files is in `parm/domain*/`; only `domain_alaska/LAKEPARM_AK.nc` is
   ([§6](#ncep-namelists), [S11]). The NCEP workflow script
   `ush/wrf_hydro_workflow_dev/ecflow_build/build_defs_operational.py` also names
   `'lakeparm_file': "LAKEPARM_CONUS.nc"`, `"LAKEPARM_HI.nc"` and `"LAKEPARM_PRVI.nc"` [S12].
   - The v3.0 tarball's `LAKEPARM_CONUS.nc` has 5,782 `lake_id`s. These are exactly the
     5,782 distinct non-zero `NHDWaterbodyComID`s of both the v3.0 RouteLink and the
     v3.1.6 = v3.1.7 RouteLink (none missing either way; computed 2026-11-10).
   - The NCEP `reservoir_index_*.nc` files also have `feature_id = 5782`.
   - Note (AI): this makes the v3.0 tarball's LAKEPARM the best public candidate for the
     operational v3.1 lake file. Byte identity cannot be checked, because no v3.1 copy is
     public.
2. **No file in the v3.0 tarball is byte-identical to its v2.1 counterpart.** Eight
   members have exactly the same size in both. Their headers differ only in the global
   `version` attribute ("NWM v2.1" → "NWM v3.0"):
   `Fulldom_HI_FullRouting`, `LAKEPARM_HI`, `nudgingParams_HI`, `RouteLink_HI`, and the
   four `spatialweights_*`. Their data values were not compared.
3. **The NCEP v3.1.7 RouteLinks are byte-identical to the v3.1.6 ones.** CONUS, AK, HI and
   PRVI all have the same SHA-256 as the copies pinned from `nwm.v3.1.6` (2026-09-30) in
   [`repro/routelink_topwidth/fetch_data.py`](../routelink_topwidth/fetch_data.py). The CONUS file is the Lynker "Tue Aug 5 16:57:23 2025"
   build. It differs from the v3.0 tarball's RouteLink in `to` (9 links), `order` (36
   links) and `gages` (1,057 links) only; all other variables are equal, link order
   included.
4. **NCEP `parm/domain/` holds two more CONUS RouteLinks that nothing documents:**
   `RouteLink_CONUS.nc_TxDOTstream` and `RouteLink_CONUS.nc_turnoffTxDOTstream`
   (269,363,375 bytes each, the size of the v3.0 file).
   - Their headers are identical to the v3.0 tarball RouteLink, including
     "produced Thu Sep 9 16:16:38 2021 by Kevin Sampson (NCAR)".
   - Their data differ from it in the same 9 `to` and 36 `order` values as v3.1.7, and in
     `gages` (90 and 13 links respectively).
   - `_TxDOTstream` tags 77 more links with 8-digit USGS Texas gage IDs (`08…`) than
     `_turnoffTxDOTstream`.
   - No `hydro.namelist` or script fetched from `nwm.v3.1.7` refers to either file.
5. **Several pairs of public tarball URLs are the same file.**
   `NWM_parameter_files.tar.gz` = `NWM_parameter_files_v3.0.tar.gz`,
   `NWM_coastal_parameters.tar.gz` = `NWM_coastal_parameters_v3.0.tar.gz`, and
   `data_tools/NWM_channel_hydrofabric.tar.gz` = `NWM_v3.0_channel_hydrofabric.tar.gz`.
   Each pair has the same ETag, size and Last-Modified [S1].
6. **The outer NOHRSC `README.txt` describes neither tarball.** It says "Applies to NWM
   v2.0, starting 2019-06-19" and lists `.nc.gz` files (`RouteLink_NHDPLUS.nc.gz`,
   `Fulldom_hires_netcdf_250m.nc.gz`, …) that are in no tarball now served. The v2.1
   tarball contains its own `README.txt` ("Applies to NWM v2.1, starting early 2021") with
   the current names.
   - Note (AI): [`repro/network_stats/README.md`](../network_stats/README.md) said the v2.1 tarball
     "contains `RouteLink_NHDPLUS.nc.gz`". That is the outer README's v2.0 list. The
     tarball actually contains `NWM_parameters_v2.1/RouteLink_CONUS.nc` (corrected there
     2026-11-12).
7. **v2.1 tarball contents.** It has no Alaska files and no `geo_em`, `wrfinput`,
   `GWBUCKPARM`, `hydro2dtbl`, `soilproperties`, `GEOGRID_LDASOUT`, `reservoir_index`
   or `Diversion` files. The v3.0 tarball lacks the same classes; it adds Alaska but
   still has no `reservoir_index_GDL_AK`. All of these are only at NCEP
   ([cross-walk](#7-cross-walk-which-file-is-where)).
8. **The v2.1 channel-hydrofabric tarball has no CONUS catchment layer.** Its
   geodatabase lists 8 layers and no `nwm_catchments_conus`. Table `a0000002c` has its
   `.gdbtablx` (13,624,352 bytes, the same size as the v3.0 CONUS-catchment table's
   index) and `.spx`, but no `.gdbtable` data file.
   - Note (AI): the CONUS catchment table was apparently left out when the tarball was
     made.
9. **Coastal files differ between NOHRSC and NCEP.** 11 of the 78 NOHRSC coastal files
   differ in size from NCEP `parm/coastal/`. NCEP's `correctMeshfile.sh` re-indexes
   `elementConn` (+1) in `hgrid.nc` and `open_bnds_hgrid.nc` and keeps the old files as
   `*-prev.nc`. NCEP also has 26 files the tarball lacks, e.g. `2m_sink_elements.txt`
   and `*OldESMFversion` copies.
10. **NCEP serves only `nwm.v3.1.7`.** `nwm.v3.1.6`, `nwm.v3.0.12` and `nwm.v2.2.0` all
    return 404, and the nwprod index lists only `nwm.v3.1.7/` [S10].
    - Note (AI): the published `parm/` is a copy of NCO's WCOSS2 directory
      `/lfs/h1/owp/nwm/save/nwm_parm.v3.1_to_NCO`, per the release's
      `doc/NWMImplementationInstructions.pdf`: "Copy the parameter files, or create
      symbolic links to them (these files are too large to store in the SVN repository)"
      [S13].
    - Note (AI): whatever is missing from it (the LAKEPARMs above) is missing from the
      public copy, not necessarily from operations.

## 2. Overview of the archives

| Archive | URL | Bytes | Last-Modified (HTTP) | Unpacked | What it is |
|---|---|---:|---|---:|---|
| NWM v2.1 parameters | [NWM_parameter_files_v2.1.tar.gz](https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/NWM_parameter_files_v2.1.tar.gz) | 4,485,467,589 | Wed, 20 Sep 2023 16:10:28 GMT | 21,302,335,228 (19 files) | CONUS/HI/PRVI Fulldom, RouteLink, LAKEPARM, nudgingParams, spatialweights; README, md5sum. Data files dated 2021-03-08 (md5sum 2021-04-13, README 2021-04-14). |
| NWM v3.0 parameters | [NWM_parameter_files_v3.0.tar.gz](https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/NWM_parameter_files_v3.0.tar.gz) (= `NWM_parameter_files.tar.gz`) | 4,678,832,855 | Wed, 20 Sep 2023 16:10:28 GMT | 20,749,613,374 (23 files) | Same five classes for CONUS/AK/HI/PRVI; md5sum; no README. Files dated 2023-07-10. Linked from water.noaa.gov [S5]. |
| NWM v3.0 coastal (SCHISM) parameters | [NWM_coastal_parameters_v3.0.tar.gz](https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/NWM_coastal_parameters_v3.0.tar.gz) (= `NWM_coastal_parameters.tar.gz`) | 6,195,378,227 | Wed, 20 Sep 2023 16:10:28 GMT | 19,014,618,753 (78 files) | SCHISM grids/inputs for atlgulf, pacific, hawaii, prvi; FES2014 tide grids; land-ocean masks. |
| NWM v2.0 channel hydrofabric | [NWM_v2.0_channel_hydrofabric.tar.gz](https://www.nohrsc.noaa.gov/owp_files/nwm/data_tools/NWM_v2.0_channel_hydrofabric.tar.gz) | 1,133,451,424 | Mon, 10 Apr 2023 20:15:53 GMT | 3,075,092,900 (69 files) | ESRI File Geodatabase (reaches, catchments, waterbodies; CONUS + HI) + ArcMap `.mxd`. |
| NWM v2.1 channel hydrofabric | [NWM_v2.1_channel_hydrofabric.tar.gz](https://www.nohrsc.noaa.gov/owp_files/nwm/data_tools/NWM_v2.1_channel_hydrofabric.tar.gz) | 646,132,558 | Mon, 10 Apr 2023 20:15:29 GMT | 939,825,532 (87 files) | FileGDB (CONUS/HI/PRVI, **no CONUS catchments**, see finding 8) + `.mxd`. |
| NWM v3.0 channel hydrofabric | [NWM_v3.0_channel_hydrofabric.tar.gz](https://www.nohrsc.noaa.gov/owp_files/nwm/data_tools/NWM_v3.0_channel_hydrofabric.tar.gz) (= `NWM_channel_hydrofabric.tar.gz`) | 3,250,751,657 | Thu, 13 Apr 2023 14:58:23 GMT | 5,067,922,143 (97 files) | FileGDB, CONUS/AK/HI/PRVI reaches + catchments, waterbodies (no PRVI waterbody layer). |
| NCEP operational package | [nwm.v3.1.7/](https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/) | `parm/`: 93,158,754,849 exact for 742 files + ≈ 114 GB (listing sizes) for 21,681 climatology/restart files | dirs 2026-11-02 | 27,301 files (22,423 in `parm/`) | Full operational source + `parm/` (25 configuration folders, 4 domain folders, coastal, forcing parameters, post-processing). |

Also in `owp_files` but not NWM parameters: `docs/OWP_Strategic_Plan_FY2021-FY2026_FINAL.pdf`
and 107 `github_repos/*_github_archive.tar.gz` snapshots of OWP GitHub repositories (list
in [§3.1](#31-every-file-in-owp_files)).

## 3. NOHRSC `owp_files`

Tree (crawled recursively 2026-11-10; Apache index pages show names only, so sizes and
dates are from HTTP `HEAD`) [S1]:

```
owp_files/
├── docs/                     1 file  (OWP strategic plan PDF)
├── github_repos/             107 *_github_archive.tar.gz (dated 2026-04-07 … 2026-10-07)
│   └── old/                  listed in the index, but returns HTTP 404
└── nwm/
    ├── data_tools/           4 channel-hydrofabric tarballs (v2.0, v2.1, v3.0, unversioned = v3.0)
    └── nwm_parameters/       5 tarballs + README.txt + README.v3.0.txt
```

No `README` exists in `docs/`, `github_repos/`, `nwm/` or `nwm/data_tools/`.

### 3.1 Every file in `owp_files`

<details><summary>All 119 files with size and Last-Modified (click to expand)</summary>

<<INCLUDE build/nohrsc_all_files.md>>

</details>

Note (AI): the `github_repos/` tarballs are OWP source-code snapshots (t-route, ngen,
hydrofabric, inundation-mapping, …), not model parameters. Their members were not
cataloged.

### 3.2 `nwm_parameters/README.txt` (verbatim, 1,900 bytes) [S2]

```
<<VERBATIM raw/nohrsc_text/README.txt>>
```

Note (AI): none of the seven files named here (`Fulldom_hires_netcdf_1km.nc.gz`,
`RouteLink_NHDPLUS.nc.gz`, …) is in any tarball now on the server. They are the
names of the NWM v2.0-era individual downloads.

### 3.3 `nwm_parameters/README.v3.0.txt` (verbatim, 3,851 bytes) [S3]

```
<<VERBATIM raw/nohrsc_text/README.v3.0.txt>>
```

### 3.4 `NWM_parameter_files_v2.1.tar.gz`

The tarball was read from an existing local copy (downloaded 2026-11-09). Its
SHA-256 `911fe35d9a6761183a3c9957794b5631fe013bde408edc38048c5b7808e679ea` and length
match the published file. Every member's MD5 matches the tarball's own `md5sum.txt`.
Member dates are tar mtimes in UTC.

<<INCLUDE build/table_v2.1.md>>

The tarball's own `README.txt` (verbatim, 2,003 bytes):

```
<<VERBATIM raw/nohrsc_text/v2.1/NWM_parameters_v2.1__README.txt>>
```

### 3.5 `NWM_parameter_files_v3.0.tar.gz`

Streamed from NOHRSC 2026-11-10, 16:38–16:56 UTC. Every member's MD5 matches the
tarball's `md5sum.txt`. There is no README inside; the description is `README.v3.0.txt`
(§3.3).

<<INCLUDE build/table_v3.0.md>>

### 3.6 `NWM_coastal_parameters_v3.0.tar.gz`

Streamed 2026-11-10, 16:56–17:28 UTC. Member paths start with `./coastal/`. The
descriptions are in `README.v3.0.txt` part 2 (§3.3) and in [§4](#desc-coastal).

<<INCLUDE build/table_coastal_v3.0.md>>

### 3.7 Channel hydrofabric tarballs (`data_tools/`)

These have no README. water.noaa.gov says of the unversioned file: "the latitude and
longitude coordinates of the centroid of each reach are made available in a separate
ESRI file geo-database (gdb), outside of the NWM outputs. The file gdb can be used in many
common GIS software utilities to attach coordinates to the data." [S5]. Layer schemas were
read with pyogrio/GDAL 3.12.4 from a scratch extraction that was deleted afterwards.

**NWM_v2.0_channel_hydrofabric.tar.gz**: <<INCLUDE build/table_hydrofabric_v2.0.md>>

| Layer (`nwm_v2_0_hydrofabric.gdb`) | Geometry | Features | CRS | Fields |
|---|---|---:|---|---|
| nwm_reaches_conus | MultiLineString | 2,729,077 | EPSG:4269 | feature_id, source, lat, lon, gnis_name, stream_order, Shape_Length |
| nwm_reaches_hawaii | MultiLineString | 13,637 | EPSG:4269 | (same as conus) |
| nwm_catchments_conus | MultiPolygon | 2,677,135 | USA_Contiguous_Albers_Equal_Area_Conic | feature_id, source, Shape_Length, Shape_Area |
| nwm_catchments_hawaii | MultiPolygon | 13,296 | USA_Contiguous_Albers | (same) |
| nwm_waterbodies_conus | MultiPolygon Z | 5,459 | USA_Contiguous_Albers | feature_id, source, gnis_name, Shape_Length, Shape_Area |
| nwm_waterbodies_hawaii | MultiPolygon Z | 9 | USA_Contiguous_Albers | (same) |

**NWM_v2.1_channel_hydrofabric.tar.gz**: <<INCLUDE build/table_hydrofabric_v2.1.md>>

| Layer (`nwm_v2_1_hydrofabric.gdb`) | Geometry | Features | CRS |
|---|---|---:|---|
| nwm_reaches_conus | MultiLineString | 2,776,738 | EPSG:4269 |
| nwm_reaches_hawaii | MultiLineString | 13,637 | EPSG:4269 |
| nwm_reaches_puertorico | MultiLineString | 14,017 | EPSG:4269 |
| nwm_catchments_hawaii | MultiPolygon | 13,296 | EPSG:4269 |
| nwm_catchments_puertorico | MultiPolygon | 13,692 | EPSG:4269 |
| nwm_waterbodies_conus | MultiPolygon | 5,783 | USA_Contiguous_Albers |
| nwm_waterbodies_hawaii | MultiPolygon Z | 9 | USA_Contiguous_Albers |
| nwm_waterbodies_puertorico | MultiPolygon | 15 | EPSG:4269 |
| *(no `nwm_catchments_conus`; see key finding 8)* | | | |

Fields are in `headers/hydrofabric_v2.1/gdb_layers.txt`. The reaches layers have
feature_id, stream_order, source, lat, lon, gnis_name and Shape_Length.

**NWM_v3.0_channel_hydrofabric.tar.gz** (= `NWM_channel_hydrofabric.tar.gz`): <<INCLUDE build/table_hydrofabric_v3.0.md>>

| Layer (`NWM_v3_hydrofabric.gdb`) | Geometry | Features | Fields |
|---|---|---:|---|
| nwm_reaches_conus | MultiLineString | 2,776,734 | ID, Shape_Length |
| nwm_reaches_alaska | MultiLineString | 391,522 | ID, Shape_Length |
| nwm_reaches_hawaii | MultiLineString | 13,637 | ID, Shape_Length |
| nwm_reaches_puertorico | MultiLineString | 14,017 | ID, Shape_Length |
| nwm_catchments_conus | MultiPolygon | 2,724,837 | ID, Shape_Length, Shape_Area |
| nwm_catchments_alaska | MultiPolygon | 390,548 | ID, Shape_Length, Shape_Area |
| nwm_catchments_hawaii | MultiPolygon | 13,296 | ID, Shape_Length, Shape_Area |
| nwm_catchments_puertorico | MultiPolygon | 13,692 | ID, Shape_Length, Shape_Area |
| nwm_waterbodies_conus | MultiPolygon Z | 5,782 | ID, Shape_Length, Shape_Area |
| nwm_waterbodies_alaska | MultiPolygon Z | 231 | ID, Shape_Length, Shape_Area |
| nwm_waterbodies_hawaii | MultiPolygon Z | 9 | ID, Shape_Length, Shape_Area |

Note (AI): these counts fit the parameter files.
- Reaches match the RouteLink `feature_id` counts (2,776,734 / 13,637 / 14,017).
- Catchments match the `spatialweights` / `GWBUCKPARM` `polyid` / `BasinDim` counts
  (2,724,837 / 390,548 / 13,296 / 13,692).
- CONUS waterbodies match LAKEPARM_CONUS v3.0 (5,782).
- Alaska is 6 short of the RouteLink (391,528) and LAKEPARM (237). That fits the
  RouteLink_AK attribute `processing_notes_20210629 = "2021_06_29: Added 6 synthetic lake
  objects and associated flowlines to support GDL forecast assimilation. Fixed ascending
  index issue."`.
- The v3.0 hydrofabric has dropped the `gnis_name`, `lat`/`lon` and `stream_order` fields.

## 4. Descriptions of each file type

Each entry gives the documented description (verbatim), the namelist key that reads it,
the WRF-Hydro routine that reads it, which configurations use it, and what the headers
show. The source code citations are to tag `nwm-v3.0-final` of
[NCAR/wrf_hydro_nwm_public](https://github.com/NCAR/wrf_hydro_nwm_public) (commit
e7185cbd, 2022-12-12) unless noted. The variable tables quoted as "WRF-Hydro docs" come
from the current WRF-Hydro v5.4 technical description appendices [S6].

<a id="desc-fulldom"></a>
### Fulldom (`Fulldom_<DOMAIN>_FullRouting.nc`, `Fulldom_CONUS_LongRange.nc`)
- **Documented as:** "This file contains gridded physiographic and model parameter data for
  the 'Analysis and Assimilation', 'Short Range' and 'Medium Range' configurations of the
  National Water Model." (FullRouting); "…for the 'Long-range' and 'Long-Range
  Analysis', configurations of the National Water Model (only for CONUS)." (LongRange)
  [S3]. WRF-Hydro calls it `Fulldom_hires.nc`, the "routing domain file" [S6 A7].
- **Read by:** `GEO_FINEGRID_FLNM` in `hydro.namelist`; template comment: "Specify the
  high-resolution routing terrain input data file (e.g.: "Fulldom_hires.nc")" [S7].
- **Variables (WRF-Hydro docs, A7, verbatim):** TOPOGRAPHY "Terrain grid or Digital
  Elevation Model (DEM)." m; FLOWDIRECTION "Flow direction grid, which explicitly defines
  flow directions along the channel network in gridded routing. This variable dictates
  where water flows into channels from the land surface as well as in the channel.";
  FLOWACC "Number of upstream cells that drain into each cell."; CHANNELGRID "Channel
  network grid identifying the location of stream channel grid cells (-9999=no channel,
  -1=deactivated channel, 0=active channel)"; STREAMORDER "Strahler stream order grid
  identifying the stream order for all channel pixels within the channel network.";
  LKSATFAC "Multiplier on saturated hydraulic conductivity in lateral flow direction.";
  RETDEPRTFAC "Multiplier on maximum retention depth before flow is routed as overland
  flow."; OVROUGHRTFAC "Multiplier on Manning's roughness for overland flow."; frxst_pts
  "Prescribed forecast points"; basn_msk "Prescribed basin masks"; LAKEGRID "Prescribed
  lakes"; landuse "Land use from geogrid regridded to the high-res routing grid" [S6].
  - CONUS and PRVI v3.0 add `IMPERVFRAC`; the docs do not list it.
  - Note (AI): it pairs with `imperv_adj = 1` (CONUS and PRVI namelists), "Specify
    whether to adjust overland flow parameters based on imperviousness".
- **Grids (headers):** CONUS FullRouting 18432×15360 (250 m), CONUS LongRange 4608×3840
  (1 km), HI 5900×3900 and PRVI 3000×1100 (100 m), AK 3516×1836 (250 m).
  - `DXRT`/`AGGFACTRT` in the namelists match: 250/4 (CONUS, AK), 100/10 (HI, PRVI),
    1000/1 (LongRange).
  - Lambert conformal; e.g. HI `proj4 = "+proj=lcc … +lat_1=10.0 +lat_2=30.0 +lat_0=20.6 +lon_0=-157.42 …"`.
- **Provenance (headers):** `Source_Software = "WRF-Hydro GIS Pre-processor v5 (03/2018)"`
  (v5.2 for AK).
  - The CONUS history goes back to 2014–2016 NWM v1.1 grids, e.g. "ncrename -v
    Band1,TOPOGRAPHY Fulldom_hires_netcdf_file_250m_NWMv1.1_calib1_newdem.nc".
  - In v2.1 the CONUS FullRouting file is 13,589,932,407 bytes; in v3.0 and at NCEP it is
    12,460,271,263 bytes (netCDF-4 rather than classic, plus `IMPERVFRAC`).

<a id="desc-routelink"></a>
### RouteLink (`RouteLink_<DOMAIN>.nc`)
- **Documented as:** "This file contains river channel definition and parameter data, and
  USGS stream gauge river reach definitions used in all configurations of the National
  Water Model." [S3]. The v2.1 README adds "Based on NHDPlus v2." [S4].
- **Read by:** `route_link_f` (template: "Specify the reach file for reach-based routing
  options (e.g.: "Route_Link.nc")"). Reader: `read_route_link_netcdf` in
  `Routing/module_HYDRO_io.F` (lines 8973–9068). It reads `link`, `NHDWaterbodyComID`,
  `to`, `lon`, `lat`, `alt`, `type`, `order`, `Qi`, `MusK`, `MusX`, `Length`, `n`, `So`,
  `ChSlp`, `BtmWdth`, `Kchan`, `TopWdth`, `TopWdthCC`, `nCC` and `gages` [S7].
- **Variables (WRF-Hydro docs, A11, verbatim):** BtmWdth "Channel bottom width [m]";
  ChSlp "Channel side slope [m/m]"; Kchan "Channel conductivity [mm/hr]"; Length "Stream
  segment length [m]"; MusK "Muskingum routing time [s]"; MusX "Muskingum weighting
  coefficient"; NHDWaterbodyComID "ComID of an associated water body if any"; Qi "Initial
  flow in link [m^3/s]"; So "Slope [m/m]"; alt "Elevation from the NAD88 datum at start
  node [m]"; ascendingIndex "Index to user for sorting IDs - only in NWM files"; from "From
  Link ID"; gages "Identifier for stream gage at this location"; lat "Latitude of the
  segment midpoint [degrees north]"; link "Link ID"; lon "Longitude of the segment midpoint
  [degrees east]"; n "Manning's roughness"; nCC "Compound Channel Manning's roughness";
  order "Strahler stream order"; to "To Link ID"; time "Time of measurement"; TopWdth "Top
  Width [m]"; TopWdthCC "Compound Channel Top Width [m]" [S6].
- **Versions (headers):**

  | Copy | features | built (`processing_notes`) | SHA-256 |
  |---|---:|---|---|
  | v2.1 tarball CONUS | 2,776,738 | "produced Fri Apr 12 07:16:15 2019 by Kevin Sampson (NCAR)" | `1b95f69a…1d193` (= HydroShare 0a596929…, per [`repro/network_stats`](../network_stats/README.md)) |
  | v3.0 tarball CONUS | 2,776,734 | "produced Thu Sep  9 16:16:38 2021 by Kevin Sampson (NCAR)"; "Waterbody feature class used: Input_Waterbodies_NWM_v3_0_Edit.shp" | `e34e58c8…ccb5f4` |
  | NCEP v3.1.7 CONUS (= v3.1.6) | 2,776,734 | "produced on Tue Aug  5 16:57:23 2025 by Lynker. This update builds upon the previous version of the routelink released with NWM 3.1." | `49576558…6fc0e` |
  | NCEP `…_TxDOTstream` / `…_turnoffTxDOTstream` | 2,776,734 | header = v3.0 (Sampson 2021) | `4c8cccb2…b531` / `307a8757…a058` |
  | v3.0 tarball AK | 391,528 | "produced Fri Mar 26 19:47:21 2021 by Kevin Sampson (NCAR) … combined NHDPlus HR Cook Inlet (Alaska) geodatabase" | `a1a7ee2a…a2880` (NCEP v3.1.7: `d27384e7…c793`) |
  | HI (v2.1, v3.0, NCEP) | 13,637 | "produced Fri Jan 12 11:41:28 2018" | all differ only by `version` attr in header |
  | PRVI v2.1 / v3.0+NCEP | 14,017 | "produced Wed Mar 27 20:36:25 2019" / "Thu May 27 12:47:27 2021" | |

  - The Lynker 2025 notes continue (verbatim): "Source Data: This file uses the Lynker
    Reference Fabric geopackage (Reference Fabric 3.0; https://www.lynker-spatial.com/).
    … Removed Gages: Four gages were removed from the dataset. Gage IDs: `11277100`,
    `02266291`, `382629104493000`, `06711570`."
  - The v3.1.7 CONUS file moves `lon`/`lat` to the end of the variable list and adds
    `_FillValue`s. Its link order equals v3.0.
  - Gage-tagged links: v3.0 8,660; v3.1.7 8,735; `_turnoffTxDOTstream` 8,662;
    `_TxDOTstream` 8,739.
  - The NCEP `nudgingParams_CONUS.nc` has 8,739 stations.
  - Note (AI): 8,739 is the `_TxDOTstream` count, which suggests the nudging file was
    built against that variant (UNVERIFIED: station lists not compared).

<a id="desc-lakeparm"></a>
### LAKEPARM (`LAKEPARM_<DOMAIN>.nc`)
- **Documented as:** "Provides the static parameters that describe the initial fullness,
  size (in terms of surface area and maximum elevation), and discharge mechanisms
  (orifice and weir) for each NWM waterbody. The lake_id corresponds with the
  NHD+WaterbodyComID" [S3].
- **Read by:** `route_lake_f` (template: "Specify the lake parameter file (e.g.:
  "LAKEPARM.nc"). Note REQUIRED if lakes are on."). Readers:
  - `read_route_lake_netcdf` in `module_HYDRO_io.F` (9082–9151) reads `lake_id`,
    `LkArea`, `LkMxE`, `WeirE`, `WeirC`, `WeirL`, `Dam_Length`, `OrificeC`, `OrificeA`,
    `OrificeE`, `lat`, `lon` and `ifd`;
  - `module_reservoir_routing.F` also reads `ascendingIndex` [S7].
- **Variables (WRF-Hydro docs, A14, verbatim):** lake_id "Lake index (consecutively from 1
  to n # of lakes)"; LkArea "Area [m^2]"; LkMxE "Elevation of maximum lake height [m,
  AMSL]"; WeirC "Weir coefficient (ranges from zero to one)"; WeirL "Weir length [m]";
  WeirE "Weir elevation [m, AMSL]"; OrificeC "Orifice coefficient (ranges from zero to
  one)"; OrificeA "Orifice area [m^2]"; OrificeE "Orifice elevation [m, AMSL]";
  Dam_Length "Dam length as a multiplier on WeirL [multiplier]"; ifd "Initial fraction
  water depth" [S6].
  - **`LkArea` is in km², not m².** The docs' "Area [m^2]" is an error. In every NWM
    LAKEPARM the `LkArea:long_name` is "Lake area (sq. km)" ("Gridded lake area (sq. km)"
    in the HI files), and the level-pool code converts km² to m² (§8, question 7). The
    error is reported upstream as NCAR/wrf_hydro_nwm_public issue #933, and the fix was
    merged in PR #934 on 2026-11-12 [S6b].
  - Note (AI): the docs also disagree with the files on `lake_id`. The NWM files use the
    NHDPlus waterbody ComID, not "consecutively from 1 to n".
- **Counts:** CONUS v2.1 5,783; CONUS v3.0 5,782; HI 9 (both); PRVI 15 (v2.1) / 16
  (v3.0); AK 237 (v3.0, NCEP).
  - CONUS v2.1 → v3.0: `lake_id` 397132 and 20774440 removed, 17905681 added.
  - In v2.1, four lake IDs are also RouteLink link IDs; in v3.0 and v3.1.6, none is
    (computed 2026-11-10).
  - Note (AI): the four are probably the Great Lakes IDs 4800002/4/6/7, which v3.x
    RouteLinks no longer contain [S9].

<a id="desc-nudgingparams"></a>
### nudgingParams (`nudgingParams_<DOMAIN>.nc`)
- **Documented as:** "Channel_rt nudge parameters. Supplies the parameters for the
  application of streamflow nudging data assimilation within the model" [S3].
- **Read by:** `nudgingParamFile` in `&NUDGING_nlist`. Reader: `read_nudging_param_file`
  in `nudging/module_nudging_io.F` (`stationId`, `R`, `G`, `tau`, `qThresh`,
  `expCoeff`) [S7].
- **Variables (WRF-Hydro docs, A16):** G "Amplitude of nudging"; R "Radius of influence in
  meters"; expCoeff "Coefficient b in denominator e^(-dt/b)"; qThresh "Discharge threshold
  category"; stationId "USGS station identifer"; tau "Time tapering parameter half window
  size in minutes" [S6].
- **Stations:** CONUS 7,994 (v2.1), 8,660 (v3.0), 8,739 (NCEP); HI 58; PRVI 83; AK 65.

<a id="desc-spatialweights"></a>
### spatialweights (`spatialweights_<DOMAIN>_FullRouting.nc`, `spatialweights_CONUS_LongRange.nc`)
- **Documented as:** "This file contains the spatial regridding weights, used to map
  variables from the 100m/250m WRF-Hydro model grids to the NHDPlusv2 catchment objects
  used in the 'Analysis and Assimilation', 'Short Range' and 'Medium Range'
  configurations" (FullRouting); "…from the 1km WRF-Hydro model grid … used in the 'Long
  Range' and 'Long Range Analysis' configurations" (LongRange) [S3].
- **Read by:** `udmap_file` when `UDMP_OPT = 1` (template: "User defined mapping, such as
  NHDPlus: 0=no (default), 1=yes"). Reader: `readUDMP` in `Routing/module_UDMAP.F`
  (`polyid`, `overlaps`, `regridweight`, `i_index`, `j_index`, `link`) [S7].
- **Variables (WRF-Hydro docs, A13):** polyid "ID of polygon"; IDmask "Polygon ID (polyid)
  associated with each record)"; overlaps "Number of intersecting polygons"; weight
  "Fraction of intersecting polygon(polyid) intersected by poly2"; regridweight "Fraction
  of intersecting polyid(overlapper) intersected by polygon(polyid)"; i_index/j_index
  "Index in the x/y dimension of the raster grid (starting with 1,1 in the LL corner)" [S6].
- **Headers:** CONUS `polyid` 2,724,837 (FullRouting `data` 176,453,744; LongRange
  22,067,991), "Created Sat May 11 01:00:36 2019" / "Fri May 10 16:41:55 2019". The CONUS,
  HI and PRVI files are the same size in v2.1, v3.0 and NCEP; only the `version`
  attribute changes.

<a id="desc-gwbuckparm"></a>
### GWBUCKPARM (`GWBUCKPARM_<DOMAIN>_FullRouting.nc`, `GWBUCKPARM_CONUS_LongRange.nc`): NCEP only
- **Read by:** `GWBUCKPARM_file` (template: "Groundwater bucket parameter file (e.g.:
  "GWBUCKPARM.nc")"). Reader: `read_GWBUCKPARM` in `module_HYDRO_io.F` (1513–1613):
  `Basin`, `Coeff`, `Expon`, `Zmax`, `Zinit`, `Area_sqkm`, `Loss` [S7].
- **WRF-Hydro docs (A12):** Basin "Basin monotonic ID (1…n)"; Coeff "Coefficient"; Expon
  "Exponent"; Zmax "Zmax"; Zinit "Zinit"; Area_sqkm "Basin area [km^2]"; ComID
  "NHDCatchment FEATUREID (NHDFlowline ComID)"; Loss "Fraction of bucket output lost" [S6].
- **Headers:** `BasinDim` CONUS 2,724,837 (both), AK 390,548, HI 13,296, PRVI 13,692.
  - All namelists use `GWBASESWCRT = 4` ("exp. bucket with area normalized parameters").
  - HI and PRVI set `bucket_loss = 1`.
  - Note (AI): per the template, `gwbasmskfil` is only needed when `UDMP_OPT=0`, so there
    is no GWBASINS file.

<a id="desc-hydro2dtbl"></a>
### hydro2dtbl (`hydro2dtbl_<DOMAIN>_*.nc`): NCEP only
- **Read by:** `HYDROTBL_F` (template: "Specify the spatial hydro parameters file (e.g.:
  "hydro2dtbl.nc") If you specify a filename and the file does not exist, it will be
  created for you."). Reader/writer: `hdtbl_in_nc` / `hdtbl_out` in `module_HYDRO_io.F`
  [S7].
- **WRF-Hydro docs (A10):** SMCMAX1 "Maximum volumetric soil moisture [m^3/m^3]"; SMCREF1
  "Reference volumetric soil moisture"; SMCWLT1 "Wilting point volumetric soil moisture";
  OV_ROUGH2D "Overland flow roughness coefficient"; LKSAT "Lateral saturated soil
  hydraulic conductivity [m/s]"; NEXP "Exponent in the decay function for lateral Ksat over
  depth" [S6].
- **Headers:** on the LSM grid (CONUS 4608×3840 = 1 km; AK 879×459; HI 590×390; PRVI
  300×110). The CONUS FullRouting and LongRange files are the same size (424,730,323 bytes).

<a id="desc-soilproperties"></a>
### soilproperties (`soilproperties_<DOMAIN>_*.nc`): NCEP only
- **Read by:** `SPATIAL_FILENAME` in `namelist.hrldas`. WRF-Hydro docs: "This is done
  through the use of the compile time option SPATIAL_SOIL and the specification of a
  netCDF format parameter file with the default filename soil_properties.nc." [S6 A8/A9].
- **Variables (header):** scamax, rsurfsnow, tau0, snowretfac, ssi, refkdt, slope, bexp,
  cwpvt, dksat, dwsat, hvt, mfsno, mp, psisat, quartz, refdk, rsurfexp, smcdry, smcmax,
  smcref, smcwlt, vcmx25, AXAJ, BXAJ, XXAJ, plus `imperv` (CONUS, PRVI).
  - Note (AI): AXAJ/BXAJ/XXAJ are Xinanjiang runoff parameters. That fits
    `RUNOFF_OPTION = 7` in all namelists and the release-note line "Implementation of a
    new surface runoff scheme (Xinanjiang) within the NWM" [S13].

<a id="desc-wrfinput"></a>
### wrfinput (`wrfinput_<DOMAIN>.nc`): NCEP only
- **Read by:** `HRLDAS_SETUP_FILE` in `namelist.hrldas`. WRF-Hydro docs (A7) list SMOIS,
  TSLB, SNOW, CANWAT, TSK, LAI, IVGTYP, ISLTYP, TMN, SHDMAX, SHDMIN, SEAICE, XLAND, HGT,
  e.g. "SMOIS LSM grid, soil layers Initial volumetric soil moisture content m3/m3" [S6].
- **Headers:** CONUS 4608×3840, "ncks -A -v ISLTYP,IVGTYP,XLAND
  wrfinput.d01.conus_1km_NWMv2.1_NLCD2016_RAW.nc …" (2019-07-17). AK adds `glacier` and
  `glacier_thickness`.

<a id="desc-geo-em"></a>
### geo_em (`geo_em_<DOMAIN>.nc`): NCEP only
- **Read by:** `GEO_STATIC_FLNM` (template: "Specify land surface model gridded input data
  file (e.g.: "geo_em.d01.nc")"). The routing code reads `HGT`, `XLAT`, `XLONG`
  (`HYDRO_drv/module_HYDRO_drv.F` 1671–1674), plus `LU_INDEX`/`LANDUSEF` and the soil
  category [S7].
- **WRF-Hydro docs (A7):** LU_INDEX "Land cover type"; SCT_DOM "Dominant top layer soil
  texture class"; HGT_M "Elevation … Not used by the model but useful for reference." [S6].
- **Headers:** this is the largest NCEP domain file (CONUS 9,555,402,732 bytes; 24 land
  categories, 16 soil categories). The AK file has 95 land categories.

<a id="desc-geogrid-ldasout"></a>
### GEOGRID_LDASOUT_Spatial_Metadata (`GEOGRID_LDASOUT_Spatial_Metadata_<DOMAIN>.nc`): NCEP only
- **Read by:** `LAND_SPATIAL_META_FLNM` (template: "Specify spatial metadata file for land
  surface grid. (e.g.: "GEOGRID_LDASOUT_Spatial_Metadata.nc")"). WRF-Hydro docs: the file
  "is required if using any of the io_form_outputs options" [S6 A6].
- **Headers:** only `x`, `y` and `crs` on the LSM grid. Note (AI): it supplies coordinates
  for the gridded LDASOUT/RTOUT output.

<a id="desc-reservoir-index"></a>
### reservoir_index (`reservoir_index_{AnA,Extended_AnA,Short_Range,Medium_Range}.nc`, `reservoir_index_GDL_AK.nc`): NCEP only
- **Read by:** `reservoir_parameter_file` in `&reservoir_nlist` (nwm-v3.1/v5.4 template;
  in `&HYDRO_nlist` in nwm-v3.0-final). The comment in the template: "Specify the reservoir
  parameter file". The README files do not describe it.
- **Header (verbatim attributes):** `reservoir_type` "Classification of reservoir release
  data type; Level pool = 1, USGS-persistence = 2, USACE-persistence = 3, RFC-forecasts =
  4"; `usgs_persistence_coefficients` "Persistence coefficients which are set to 1.0 for
  USGS sites"; `rfc_forecast_persist` "Maximum number of days to persist on the last value
  of RFC forecast"; `rfc_timeslice_offset` "Offset time in hours for the model to search
  forward in time from the model start time for a given RFC Timeslice file."
- **Counts:** CONUS `feature_id` 5,782 in all four.
  - AnA, Extended_AnA and Short_Range: USGS 76, USACE 70, RFC 397.
  - Medium_Range: USGS 47, USACE 52, RFC 389.
  - AK GDL: 237 lakes, 6 RFC.
- **Which file each configuration uses (namelists):**
  - AnA → `_AnA`; extended AnA → `_Extended_AnA`; short_range → `_Short_Range`;
    medium_range and medium_range_no_da → `_Medium_Range`.
  - All Alaska configurations → `_GDL_AK`.
  - The HI, PRVI and long-range configurations have no `&reservoir_nlist` file and run
    `lake_option = 1` (level pool).

<a id="desc-diversion"></a>
### Diversion (`Diversion_CONUS.nc`): NCEP only, new in v3.1
- **Read by:** `diversions_file` (`hydro.namelist` comment: "Specifiy a diversions
  parameter file if available"). Reader: `init_diversions` in
  `src/Routing/Diversions/module_diversions.F90` (tags `nwm-v3.1-beta4`, `v5.4.0`; absent
  in `nwm-v3.0-final`). It reads `Diversion_Name`, `DivType`, `FromType`, `ToType`,
  `DA_Src`, `DA_Dest`, `DivFrom`, `DivTo`, `DivCap`, `DivFrac`, `Lookback`. Only
  `DivType = 3` is handled: other types print "!!! UNSUPPORTED DIVERSION TYPE" [S7b].
- **Content (read 2026-11-10):** one diversion.
  - `Diversion_Name = "Old River Control Structure"`, `DivFrom = 19269940`,
    `DivTo = 19406874`, `DivType = 3`, `FromType = ToType = 1` ("1=reach").
  - `DivCap = 19822` m³/s, `DivFrac = 0.3`, `DA_Src = "None"`,
    `DA_Dest = "07381482"`, `Lookback = 24` h.
  - Global `:Creation_Date = "Tue Jun 18 13:07:00 2024"`.
  - Note (AI): the `DivFrac` long_name says "DivType must be 1", but the file uses type 3
    and the code supports only 3.
- **Used by:** analysis_assim, analysis_assim_extended, analysis_assim_longrange,
  short_range, medium_range, long_range. It is not used by the `*_no_da` configurations.

<a id="desc-tbl"></a>
### Parameter tables (`parm/constants{,_alaska}/*.TBL`): NCEP only
`CHANPARM.TBL` (471 B), `GENPARM.TBL` (261 B), `HYDRO.TBL` (2,199 B), `MPTABLE.TBL`
(47,966/47,969 B), `SOILPARM.TBL` (5,275 B). These are the WRF-Hydro/Noah-MP ASCII lookup
tables described in WRF-Hydro docs A8–A11 [S6]. Note (AI): with the 2-D `hydro2dtbl`,
`soilproperties` and `RouteLink` files in use, most of their entries are superseded.
`CHANPARM.TBL` applies only to gridded channel routing.

<a id="desc-forcingconfigs"></a>
### Forcing-engine configs and parameters (`parm/forcingConfigs`, `parm/forcingParam`, `parm/mpe`): NCEP only, not routing
These are 19 `template_forcing_engine_*.config` files and forcing-side parameter grids:
- `lapse_param.nc`;
- PRISM monthly climatologies for Mountain Mapper (`PRISM_Precip_Clim_<Mon>_*`);
- ESMF regridding weights;
- `Long_Range/CFSv2_Climo` (11,712 `cfs_<var>_<MMDD>_<HH>_dist_params.nc`) and
  `Long_Range/NLDAS_Climo` (8,784 `nldas<…>_dist_params.nc`);
- MRMS RQI weights;
- MPE HRAP regridding weights.

Headers of a sample are in `headers/ncep_v3.1.7/`. Note (AI): these are inputs to the NWM
forcing engine, not to WRF-Hydro routing; their purposes are not described here beyond
their names.

<a id="desc-coastal"></a>
### Coastal (SCHISM) files (`coastal/<atlgulf|pacific|hawaii|prvi>/…`)
The descriptions in `README.v3.0.txt` part 2 are quoted in full in §3.3. Header facts:
- **`hgrid.nc`:** `nodeCount`/`elementCount`: atlgulf 10,537,609 / 20,967,960; pacific
  3,138,490 / 6,050,741; hawaii 878,770 / 1,703,252; prvi 3,705,642 / 7,371,800. Global
  `gridType = "unstructured"`, `version = "0.9"`.
- **`hgrid.gr3` header lines (NCEP):** atlgulf "NWM v3.1" / "20967960 10537609".
- **`hgrid.utm`:** the atlgulf file starts
  "/scratch2/NCEPDEV/ohd/Camaron.George/schismRuns/Florence/atl/hgrid.utm" / "16140153
  8135787". Note (AI): that is a different, smaller mesh than `hgrid.gr3` (same in the
  NOHRSC tarball, same size).
- **`nwmReaches.csv`:** two blocks, each a count line followed by pairs of
  `<NWM feature_id> <integer>`. Counts: atlgulf 5,587 + 614; pacific 3,395 + 1,173;
  hawaii 731 + 149; prvi 767 + 122.
  - README: "List of the National Water Model Reach IDs which intersect the SCHISM model
    domain".
  - Note (AI): the two blocks look like SCHISM source and sink element lists; the meaning
    of the second column is undocumented.
- **`bctides.in`, `vgrid.in`, `sflux_inputs.txt`:** tiny text files. `vgrid.in` has
  "2 !ivcor" and 2 levels (2-D barotropic); `sflux_inputs.txt` is an empty namelist
  `&sflux_inputs /`.
- **`param.nml`:** about 49.5 kB SCHISM namelists.
  - NCEP pacific `param.nml` differs from the tarball copy in `s1_mxnbt`/`s2_mxnbt`
    (1.0/4.0 vs 0.5/3.5). The tarball values equal NCEP's `param.nmlORIG`.
- **`elevation_correction.csv`:** "conversion from MSL to NAVD88 for the open boundary
  nodes"; header `OID_,Field1,Field2,Field3,msl,conversion_factor`.
- **NCEP-only files:** `2m_sink_elements.txt` (undocumented; one integer per line),
  `correctMeshfile.sh` (shown in key finding 9), `*-prev.nc`, `*OldESMFversion`,
  `*NewESMFversion`, `param.nmlORIG`.

<a id="desc-tides"></a>
**Tides (`coastal/Tides/TidalConst/{k1,k2,m2,n2,o1,p1,q1,s2}.nc`).** Global grids
5760×2881 (1/16°), variables `amplitude` (cm) and `phase` (degrees). Header:
`title = "FES2014b tide elevations"`, `credits = "LEGOS, NOVELTIS, CLS, CNES"`, `license =
"http://www.aviso.oceanobs.com/fileadmin/documents/data/License_Aviso.pdf"`.

<a id="desc-mask"></a>
**Land-ocean masks (`coastal/maskFiles/Ocean_Land_Mask_*_5m.nc`).** One record per SCHISM
node (`index` = node count of the matching mesh). Variables `OID_`, `Node`, `Longitude`,
`Latitude`, `Mask`. Undocumented beyond the README's "Land-ocean mask files".

<a id="desc-md5sum"></a><a id="desc-readme"></a>
**`md5sum.txt` / `README.txt` (inside the tarballs).** These are checksums of the other
members (verified) and the README quoted in §3.4.

## 5. NCEP `nwm.v3.1.7`

The whole tree was crawled 2026-11-10 with Apache's fancy index (`?F=1`). That gives a
listing date and a rounded size for each file in one request per folder. Exact
`Content-Length`/`Last-Modified` were read by HTTP `HEAD` for every file in folders with at
most 1,000 entries (the largest has 133), and for the first 353 files of
`Long_Range/CFSv2_Climo` (5,607 files in all). Folder dates are all 2026-11-02 [S10].

### 5.1 Folder summary (whole package)

<details><summary>Files and bytes per folder (click to expand)</summary>

<<INCLUDE build/ncep_tree_summary.md>>

</details>

The non-`parm/` folders are code, not parameters:
- `sorc/nwm_wrfhydro` (771 files): the WRF-Hydro build used by NWM;
- `sorc/schism` (2,568);
- `ush/` (Python/shell workflow), `jobs/`, `scripts/`, `ecf*/`, `ecflow/` (job
  definitions), `modulefiles/`, `versions/`;
- `doc/`: `NationalWaterModelReleaseNotes.pdf` (release notes up to "Version 3.1.0"),
  `NWMImplementationInstructions.pdf`, `crontab.v2.0`…`v3.1`, install scripts.

### 5.2 `parm/` file by file

Per-file tables for every `parm/` folder follow. Folders with more than 300 files are
summarized by name pattern. Links go to the saved header.

<<INCLUDE build/ncep_parm_tables.md>>

<a id="ncep-namelists"></a>
## 6. Namelists: routing-relevant options by configuration

There are 25 configuration folders in `parm/`, each with one `hydro.namelist` and one
`namelist.hrldas`. The full side-by-side tables are generated by
`scripts/nml_table.py` into `build/hydro_namelist_table.txt` and
`build/hrldas_namelist_table.txt`. Options identical in **all 25**
`hydro.namelist`s are below; the operational file's own comment is quoted for each.

| Option | Value (all 25) | Comment in the NCEP file (verbatim) |
|---|---|---|
| `channel_option` | 2 | "Specify channel routing option: 1=Muskingam-reach, 2=Musk.-Cunge-reach, 3=Diff.Wave-gridded" |
| `compound_channel` | .TRUE. | "If using channel_option=2, activate the compound channel formulation? (Default=.FALSE.) This option is currently only supported if using reach-based routing with UDMP=1." |
| `DTRT_CH` | 300 | "Specify the channel routing model timestep...(seconds)" |
| `CHANRTSWCRT` | 1 | "Switch to activate channel routing...(0=no, 1=yes)" |
| `UDMP_OPT` | 1 | "User defined mapping, such as NHDPlus: 0=no (default), 1=yes" |
| `GWBASESWCRT` | 4 | "Switch to activate baseflow bucket model...(0=none, 1=exp. bucket, 2=pass-through, 4=exp. bucket with area normalized parameters)" |
| `rt_option` | 1 | "Specify overland flow routing option: 1=Seepest Descent (D8) 2=CASC2D (not active)" (template) |
| `output_channelBucket_influx` | 2 | "2=channel+bucket fluxes    (qSfcLatRunoff, qBucket, qBtmVertRunoff_toBucket)" |
| `temporalPersistence` | .TRUE. | "temporalPersistence defaults to true, only runs if necessary params present." |
| `nLastObs` | 480 | "The total number of last (obs, modeled) pairs to save in nudgingLastObs for removal of bias. … (Default=960=10days @15min obs resolution…)" |
| `minNumPairsBiasPersist` / `invDistTimeWeightBias` / `noConstInterfBias` | 1 / .TRUE. / .TRUE. | |
| `order_to_write`, `io_form_outputs`, `CHRTOUT_DOMAIN`, `outlake` | 1, 2, 1, 1 | |

Note (AI): `DTRT_CH = 300` s. The WRF-Hydro "short timestep switch" and its dependence on
the time step are studied in [`repro/short_ts_switch`](../short_ts_switch/README.md); that
question is not covered here.

Options that **vary** by configuration (abridged; `_no_da` = the open-loop twin):

| Configuration(s) | Fulldom / grid (`DXRT`, `AGGFACTRT`) | `lake_option` | reservoir file | `diversions_file` | Nudging `timeSlicePath` | `persistBias` / `biasWindowBeforeT0` / `maxAgePairsBiasPersist` | other |
|---|---|---|---|---|---|---|---|
| analysis_assim | CONUS FullRouting (250, 4) | 3 | `reservoir_index_AnA` | Diversion_CONUS | `./nudgingTimeSliceObs/` | T / F / 3 | `imperv_adj=1`; USGS, USACE persistence and RFC forecasts on |
| analysis_assim_no_da | same | 3 | `reservoir_index_AnA` | — | `./doesNotExistPath/` | T / F / 3 | |
| analysis_assim_extended / extend_no_da | same | 3 | `…_Extended_AnA` | yes / — | obs / doesNotExist | T / F / 3 | `rst_dt=240` |
| short_range | same | 3 | `…_Short_Range` | yes | obs | F / T / 24 | |
| medium_range / medium_range_no_da | same | 3 / 1 | `…_Medium_Range` | yes / — | obs / doesNotExist | F / T / 24 | |
| analysis_assim_longrange / long_no_da | CONUS LongRange (1000, 1) | 1 | none | yes / — | obs / doesNotExist | T / F / 3 | `SUBRTSWCRT=OVRTSWCRT=0` (no terrain routing) |
| long_range | CONUS LongRange | 1 | none | yes | obs | F / T / 24 | `out_dt=360`, `FORCING_TIMESTEP=10800` |
| ak_* (4), *_alaska_no_da (3) | AK FullRouting (250, 4) | 3 | `reservoir_index_GDL_AK` | — | obs / doesNotExist | AnA: T/F/3; fcst: F/T/24 | RFC forecasts on for short/medium; AnA reads `./gdl_files/` |
| hi_analysis_assim, hi_short_range, *_hawaii_no_da | HI FullRouting (100, 10) | 1 | none | — | obs / doesNotExist | | `bucket_loss=1`, `DTRT_TER=6`, `out_dt=15`, `NOAH_TIMESTEP=900` (all four HI configurations) |
| pr_analysis_assim, pr_short_range, *_puertorico_no_da | PRVI FullRouting (100, 10) | 1 | none | — | obs / doesNotExist | | `bucket_loss=1`, `DTRT_TER=6`, `imperv_adj=1` |

- `lake_option`: "Lake / Reservoir options (0=lakes off, 1=level pool (typical default),
  2=passthrough, 3=reservoir DA [see &reservoir_nlist below])".
- `reservoir_observation_lookback_hours = 48`, `reservoir_observation_update_time_interval_seconds = 3600`
  and `reservoir_rfc_forecasts_lookback_hours = 28` wherever a `&reservoir_nlist` exists.
- Restart files named in the namelists, e.g. CONUS `HYDRO_RST.2021-10-24_00:00_DOMAIN1`,
  are not in `parm/`. Only `parm/manualclimateRestart/` (1,536 split restart files
  `HYDRO_RST.2016-04-24_12:00_DOMAIN1.N` and `RESTART.*_DOMAIN1.N`) is published.
  - These are binary, not netCDF; the first bytes are `00000004 0000000f`.
  - Note (AI): that looks like Fortran unformatted per-process restarts, cf.
    `rst_bi_in`/`rst_bi_out` "1: use parallel io for reading multiple restart files, 1
    per core" in the template; undocumented.

**`namelist.hrldas`** (Noah-MP), all 25:
- the same in every file: `DYNAMIC_VEG_OPTION = 4`, `RUNOFF_OPTION = 7`,
  `FROZEN_SOIL_OPTION = 1`, `GLACIER_OPTION = 2`, `SURFACE_RESISTANCE_OPTION = 4`,
  `NSOIL = 4` (0.10/0.30/0.60/1.00 m);
- `PCP_PARTITION_OPTION`: 4 for CONUS, 1 for AK, HI and PRVI;
- `IMPERV_OPTION`: 2 for CONUS and PRVI, 9 for AK and HI;
- AK: `crocus_opt = 1` (glacier model);
- `HRLDAS_SETUP_FILE` → `wrfinput_<DOMAIN>.nc` and `SPATIAL_FILENAME` →
  `soilproperties_<DOMAIN>_*.nc`;
- `KHOUR`: AnA 3, extended 28 (CONUS) / 32 (AK), long-range AnA 12, AK short 15, AK
  medium 240.

**How the operational options changed across WRF-Hydro releases (template
`hydro.namelist`, NCAR repo [S7]).**
- `nwm-v2.0` (2019-03-21): no reservoir options; `GWBASESWCRT` "(0=none, 1=exp. bucket,
  2=pass-through)" only.
- `nwm-v2.1-beta3` (2021-01-25) and `nwm-v3.0-final` (2022-12-12) add the reservoir
  persistence/RFC options and `bucket_loss`.
- `nwm-v3.0-final` adds `imperv_adj` and "5=Bypass channel routing" to `channel_option`.
- `nwm-v3.1-beta4` (2025-10-01) and `v5.4.0` (2025-03-14) add `lake_option`, move the
  reservoir options to a separate `&reservoir_nlist`, and add `diversions_file` to the
  code. The template does not include it.

## 7. Cross-walk: which file is where

Legend: ● present; ○ absent; "=" byte-identical (SHA-256); "≈hdr" header identical except
the global `version` attribute (data not compared). NCEP column = `nwm.v3.1.7/parm/`.
"v2.0 README" = files named in the outer NOHRSC README (no longer downloadable).

| File class | v2.0 README | v2.1 tarball | v3.0 tarball | NCEP v3.1.7 | Notes |
|---|---|---|---|---|---|
| Fulldom CONUS FullRouting (250 m) | `Fulldom_hires_netcdf_250m.nc.gz` | ● 13.59 GB | ● 12.46 GB | ● ≈hdr v3.0 | v3.0 adds IMPERVFRAC |
| Fulldom CONUS LongRange (1 km) | `Fulldom_hires_netcdf_1km.nc.gz` | ● | ● | ● ≈hdr v3.0 | |
| Fulldom HI / PRVI | ○ | ● / ● | ● (HI ≈hdr v2.1) / ● | ● ≈hdr v3.0 | |
| Fulldom AK | ○ | ○ | ● | ● (adds `version`) | |
| RouteLink CONUS | `RouteLink_NHDPLUS.nc.gz` | ● 2019-04 build | ● 2021-09 build | ● 2025-08 Lynker (= v3.1.6) + 2 TxDOT variants | see §4 table |
| RouteLink HI / PRVI / AK | ○ | ● / ● / ○ | ● / ● / ● | ● (= v3.1.6) | HI ≈hdr across all three |
| LAKEPARM CONUS | `LAKEPARM_NHDPLUS.nc` | ● 5,783 | ● 5,782 | **○ (namelists need it)** | |
| LAKEPARM HI / PRVI | ○ | ● / ● | ● / ● | **○ / ○ (namelists need them)** | |
| LAKEPARM AK | ○ | ○ | ● | ● ≈hdr | |
| nudgingParams CONUS / HI / PRVI / AK | `nudgingParams.nc` | ● 7,994 / ● / ● / ○ | ● 8,660 / ● / ● / ● | ● 8,739 / ● / ● / ● | |
| spatialweights CONUS FR / LR / HI / PRVI | `spatialweights_{250m,1km}_all_basins.nc.gz` | ● | ● ≈hdr v2.1 | ● ≈hdr v3.0 | same since 2019 |
| spatialweights AK | ○ | ○ | ● | ● ≈hdr | |
| GWBUCKPARM (all domains) | ○ | ○ | ○ | ● | |
| hydro2dtbl, soilproperties, wrfinput, geo_em, GEOGRID_LDASOUT | ○ | ○ | ○ | ● | land-surface side |
| reservoir_index (AnA, Ext_AnA, SR, MR, GDL_AK) | ○ | ○ | ○ | ● | |
| Diversion_CONUS | ○ | ○ | ○ | ● | v3.1+ code only |
| CHANPARM/GENPARM/HYDRO/MPTABLE/SOILPARM.TBL | ○ | ○ | ○ | ● | |
| hydro.namelist / namelist.hrldas | ○ | ○ | ○ | ● ×25 | |
| SCHISM coastal | ○ | ○ | coastal tarball (78 files) | ● 104 files | 11 size differences, 26 NCEP-only |
| Channel hydrofabric (FileGDB) | ○ | `data_tools` v2.1 (no CONUS catchments) | `data_tools` v3.0 | ○ | v2.0 also in `data_tools` |

**Other copies (identity checked by SHA-256, 2026-11-10):**
- **v3.0 tarball RouteLink_CONUS** (`e34e58c8…`) = a local archive copy named
  `RouteLink_CONUS_3.0.11.nc` = t-route `test/input/geo/Channels/RouteLink_CONUS.nwm.v3.0.20.nc`
  = another local copy.
  - Note (AI): the file names suggest NWM v3.0.11 and v3.0.20 shipped the same RouteLink
    as the tarball.
- **v2.1 tarball RouteLink_CONUS** (`1b95f69a…`) = HydroShare resource 0a596929… (copied
  from `nwm.v2.2.0/parm/domain/`, per [`repro/network_stats`](../network_stats/README.md))
  = a local archive copy of `RouteLink_CONUS.nc`.
- **NCEP v3.1.7 RouteLinks** = the files pinned in
  [`repro/routelink_topwidth/fetch_data.py`](../routelink_topwidth/fetch_data.py) (from v3.1.6) =
  a local copy named `RouteLink_CONUS_3.1.nc`.
- **v3.0 tarball LAKEPARM_CONUS** = a local archive copy of the extracted tarball
  (`v3.0_par/LAKEPARM_CONUS.nc`, MD5 `97db3d8f…`).

## 8. Open questions

1. **Where is the operational v3.1 `LAKEPARM_CONUS.nc`?** And `LAKEPARM_HI.nc` and
   `LAKEPARM_PRVI.nc`? Is it identical to the v3.0 tarball's file? Only NWC/OWP can
   answer. The fit with the RouteLink waterbody set and the reservoir_index `feature_id`
   (5,782) is consistent with "yes".
2. **What are `RouteLink_CONUS.nc_TxDOTstream` and `_turnoffTxDOTstream` for?** They are
   undocumented, unreferenced by the namelists, and built from the 2021 v3.0 file. Is the
   nudgingParams station count (8,739 = TxDOT-variant gage count) a coincidence?
3. **Is the v2.1 hydrofabric tarball's missing CONUS catchment table intentional?**
4. **Do the "≈hdr" pairs have identical data?** For example, is v2.1 vs v3.0
   `spatialweights_CONUS_FullRouting`, which differs only in `version`, the same data?
   Answering needs both files; a data comparison of the 5 GB pair was not done.
5. **What is the second column of the SCHISM `nwmReaches.csv`, and what is
   `2m_sink_elements.txt`?** Both are undocumented.
6. **Which WRF-Hydro tag is `sorc/nwm_wrfhydro` in v3.1.7?** It was not inspected.
   [`repro/nwm_scale`](../nwm_scale/README.md) reports `code_version = v5.4.0` in v3.1
   output files.
7. **Closed (2026-11-11): LAKEPARM `LkArea` is in km².** The WRF-Hydro docs say "Area
   [m^2]", but the NWM files' `long_name` says "Lake area (sq. km)", and both the code
   and the values agree with the files.
   - The level-pool code takes km². WRF-Hydro `module_levelpool.F90` declares
     `ar ! area of reservoir (km^2)` and converts with `sap = ar * 1.0E6` [S7c]. t-route's
     `src/kernel/reservoir/Level_Pool/module_levelpool.F` has the same two lines [S7d].
   - The values fit km². v2.1 `LAKEPARM_CONUS` `LkArea` vs published full-pool surface
     areas (km²): Lake Mead 585.4 vs 640; Lake Powell 620.7 vs 653; Lake Tahoe 469.0 vs
     496; Lake Okeechobee 1,726.6 vs 1,891; Fort Peck Lake 912.7 vs 1,010; Lake
     Sakakawea 1,166.0 vs 1,550; Lake Oahe 1,169.1 vs 1,500. Computed with
     `scripts/analysis/lakearea_check.py`; the reference areas are the ones written in
     that script, and their sources are not recorded.
     - Note (AI): 75–95 % of full pool is what NHD waterbody polygons mapped at a
       typical stage would give. In m² the values would be lakes of under 0.002 km².
   - The documentation error (`appendices.rest`, "Area [m^2]") is reported as
     NCAR/wrf_hydro_nwm_public issue #933; the fix was merged in PR #934 on 2026-11-12
     [S6b].
8. NWM **v2.0** parameter files are no longer downloadable anywhere checked:
   - NOHRSC: `NWM_parameter_files_v2.0.tar.gz` and `_v2.2.tar.gz` return 404 (troute-paper
     session, 2026-11-04..10);
   - NCEP `nwm.v2.x` folders also return 404.

## 9. Method, downloads, and contributions from other sessions

- **Downloads (all streamed; nothing kept but headers and small text members):**
  - NOHRSC v3.0 parameters (4.68 GB), coastal (6.20 GB);
  - hydrofabric v3.0/v2.1/v2.0 (3.25/0.65/1.13 GB, twice: once for member lists, once for
    GDB schemas);
  - 17 small NCEP domain files (≈ 0.9 GB, hashed in scratch);
  - 327 small NCEP scripts;
  - NCEP doc PDFs;
  - **Total about 22 GB transferred** (under the 30 GB limit). The v2.1 tarball was read from an existing local
    copy with the same SHA-256; it was not downloaded again.
- **Header reads at NCEP:** `ncdump -h "<url>#mode=bytes"` (netCDF-C byte-range), so no
  multi-GB file was downloaded to read a header.
- **Scripts:** in `scripts/`, run by `rebuild.sh`: `crawl_nohrsc.py`, `crawl_ncep.py`,
  `scan_tar.py`, `gdb_schema.py`, `ncep_headers.py`, `ncep_hashes.py`, `find_cached.py`,
  `nml_table.py`, and the table and assembly scripts. One-off checks quoted in this
  catalog are in `scripts/analysis/`: `hdrdiff.py`, `rl_diff.py`, `lake_check.py`,
  `lakearea_check.py`. Python ran through `uv`.

## 10. Sources

All accessed 2026-11-10 unless stated.

- [S1] NOHRSC `owp_files` index and HTTP HEADs: https://www.nohrsc.noaa.gov/owp_files/ (and every subfolder; listing in `listings/nohrsc_owp_files.tsv`).
- [S2] https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/README.txt
- [S3] https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/README.v3.0.txt
- [S4] `NWM_parameters_v2.1/README.txt` inside https://www.nohrsc.noaa.gov/owp_files/nwm/nwm_parameters/NWM_parameter_files_v2.1.tar.gz
- [S5] NOAA OWP, "National Water Model", https://water.noaa.gov/about/nwm (links to the v3.0 parameter, coastal, README.v3.0 and channel-hydrofabric files).
- [S6] WRF-Hydro v5.4 Technical Description, Appendices (A6, A7, A8–A14, A16, A17): https://wrf-hydro.readthedocs.io/en/latest/appendices.html. Version-matched PDFs: v5.2 https://ral.ucar.edu/sites/default/files/public/projects/wrf-hydro/technical-description-user-guide/wrf-hydrov5.2technicaldescription.pdf; index of v5.1.1/v5.0 docs: https://ral.ucar.edu/projects/wrf_hydro/documentation
- [S6b] NCAR/wrf_hydro_nwm_public issue #933, "Docs: LAKEPARM LkArea unit is km^2, not m^2": https://github.com/NCAR/wrf_hydro_nwm_public/issues/933 ; PR #934, "change m^2 --> km^2 for LAKEPARM.LkArea appendix entry": https://github.com/NCAR/wrf_hydro_nwm_public/pull/934 (issue open; PR merged 2026-11-12; checked 2026-11-13).
- [S7] NCAR/wrf_hydro_nwm_public, tag `nwm-v3.0-final`: `trunk/NDHMS/template/HYDRO/hydro.namelist`, `trunk/NDHMS/Routing/module_HYDRO_io.F`, `trunk/NDHMS/Routing/module_UDMAP.F`, `trunk/NDHMS/Routing/module_reservoir_routing.F`, `trunk/NDHMS/nudging/module_nudging_io.F`, `trunk/NDHMS/HYDRO_drv/module_HYDRO_drv.F`, `trunk/NDHMS/Data_Rec/module_namelist.F`: https://github.com/NCAR/wrf_hydro_nwm_public/tree/nwm-v3.0-final ; template diffs against tags `nwm-v2.0`, `nwm-v2.1-beta3`, `nwm-v3.1-beta4`, `v5.4.0`.
- [S7b] NCAR/wrf_hydro_nwm_public, tag `v5.4.0`: `src/Routing/Diversions/module_diversions.F90`, `src/template/HYDRO/hydro.namelist`: https://github.com/NCAR/wrf_hydro_nwm_public/tree/v5.4.0
- [S7c] NCAR/wrf_hydro_nwm_public, tag `v5.4.0`, `src/Routing/Reservoirs/Level_Pool/module_levelpool.F90` lines 235 and 282: https://github.com/NCAR/wrf_hydro_nwm_public/blob/v5.4.0/src/Routing/Reservoirs/Level_Pool/module_levelpool.F90#L235 (accessed 2026-11-11).
- [S7d] NOAA-OWP/t-route, branch `master`, `src/kernel/reservoir/Level_Pool/module_levelpool.F` lines 244 and 294: https://github.com/NOAA-OWP/t-route/blob/master/src/kernel/reservoir/Level_Pool/module_levelpool.F#L244 (accessed 2026-11-11).
- [S8] HydroShare resource 0a596929a3e5411bb0032a8de35e5089 (v2.1 RouteLink from `nwm.v2.2.0/parm/domain/`), as documented in [`repro/network_stats/README.md`](../network_stats/README.md) (not re-accessed).
- [S9] The project's unpublished RouteLink version comparison (2026-10-06/28; v2.0, v2.1 and v3.1.6 RouteLinks) and [`repro/routelink_topwidth/fetch_data.py`](../routelink_topwidth/fetch_data.py) (v3.1.6 SHA-256 list, downloaded 2026-09-30).
- [S10] NCEP nwprod: https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/ and https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/ (full tree in `listings/ncep_nwm.v3.1.7_tree.tsv`; headers in `headers/ncep_v3.1.7/`).
- [S11] NCEP namelists: https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/parm/<configuration>/hydro.namelist and `namelist.hrldas` (25 configurations).
- [S12] https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/ush/wrf_hydro_workflow_dev/ecflow_build/build_defs_operational.py
- [S13] https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/doc/NationalWaterModelReleaseNotes.pdf and https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/doc/NWMImplementationInstructions.pdf
