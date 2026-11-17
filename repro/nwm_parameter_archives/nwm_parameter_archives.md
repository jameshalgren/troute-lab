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

| Path | Bytes | Last-Modified (HTTP) |
|---|---:|---|
| `docs/OWP_Strategic_Plan_FY2021-FY2026_FINAL.pdf` | 3,478,463 | 01 Sep 2021 15:05:40 |
| `github_repos/ADHydro_github_archive.tar.gz` | 36,687,084 | 07 Oct 2026 16:19:25 |
| `github_repos/AORC-jupyter-notebooks_github_archive.tar.gz` | 876,525 | 07 Oct 2026 16:19:25 |
| `github_repos/DMOD_github_archive.tar.gz` | 21,830,505 | 07 Oct 2026 16:19:29 |
| `github_repos/LGAR-C_github_archive.tar.gz` | 86,123,322 | 07 Oct 2026 16:19:37 |
| `github_repos/LGAR-Py_github_archive.tar.gz` | 43,520,300 | 07 Oct 2026 16:19:37 |
| `github_repos/NextGen-Info_github_archive.tar.gz` | 1,552,109 | 07 Oct 2026 16:19:38 |
| `github_repos/NextGen-Water-Prediction-Capability_github_archive.tar.gz` | 1,507,427 | 07 Oct 2026 16:19:39 |
| `github_repos/NextGen_Regionalization_github_archive.tar.gz` | 171,087,602 | 07 Oct 2026 16:19:39 |
| `github_repos/OWP-Presentations_github_archive.tar.gz` | 1,250,916,855 | 07 Oct 2026 16:19:49 |
| `github_repos/RRASSLER_github_archive.tar.gz` | 309,315,630 | 07 Oct 2026 16:20:00 |
| `github_repos/SLoTH_github_archive.tar.gz` | 1,576,668 | 07 Oct 2026 16:20:00 |
| `github_repos/SoilFreezeThaw_github_archive.tar.gz` | 99,158,132 | 07 Oct 2026 16:20:01 |
| `github_repos/SoilMoistureProfiles_github_archive.tar.gz` | 4,521,605 | 07 Oct 2026 16:20:01 |
| `github_repos/aorc_bmi_github_archive.tar.gz` | 1,605,492 | 07 Oct 2026 16:19:25 |
| `github_repos/auto-eval-coordinator_github_archive.tar.gz` | 110,567,543 | 07 Oct 2026 16:19:26 |
| `github_repos/auto-eval-jobs_github_archive.tar.gz` | 8,925,169 | 07 Oct 2026 16:19:26 |
| `github_repos/benchmarkcat_github_archive.tar.gz` | 26,335,731 | 07 Oct 2026 16:19:26 |
| `github_repos/bmi-cxx_github_archive.tar.gz` | 86,145 | 07 Oct 2026 16:19:26 |
| `github_repos/bridge-classification_github_archive.tar.gz` | 6,009,322 | 07 Oct 2026 16:19:26 |
| `github_repos/cfe_github_archive.tar.gz` | 96,080,801 | 07 Oct 2026 16:19:27 |
| `github_repos/channel-shape-ML_github_archive.tar.gz` | 599,611,268 | 07 Oct 2026 16:19:28 |
| `github_repos/data-service-notebooks_github_archive.tar.gz` | 1,942,068 | 07 Oct 2026 16:19:28 |
| `github_repos/datum-sync_github_archive.tar.gz` | 4,099,001 | 07 Oct 2026 16:19:28 |
| `github_repos/eval-panel_github_archive.tar.gz` | 1,509,248 | 07 Oct 2026 16:19:29 |
| `github_repos/evapotranspiration_github_archive.tar.gz` | 2,381,348 | 07 Oct 2026 16:19:29 |
| `github_repos/fim-misc_github_archive.tar.gz` | 1,954,953 | 07 Oct 2026 16:19:29 |
| `github_repos/flow-dispersal_github_archive.tar.gz` | 328,602,236 | 07 Oct 2026 16:19:30 |
| `github_repos/flows2fim_github_archive.tar.gz` | 113,002,706 | 07 Oct 2026 16:19:30 |
| `github_repos/formulation-selector_github_archive.tar.gz` | 7,016,216 | 13 Jul 2026 18:21:07 |
| `github_repos/geogrids_github_archive.tar.gz` | 154,598,007 | 07 Oct 2026 16:19:31 |
| `github_repos/gfm-puller_github_archive.tar.gz` | 109,904 | 07 Oct 2026 16:19:31 |
| `github_repos/gh-train_github_archive.tar.gz` | 5,395,568 | 07 Oct 2026 16:19:31 |
| `github_repos/github_archive_github_archive.tar.gz` | 50,021 | 07 Oct 2026 16:19:31 |
| `github_repos/gval_github_archive.tar.gz` | 54,283,535 | 07 Oct 2026 16:19:31 |
| `github_repos/hand-index_github_archive.tar.gz` | 3,247,912 | 07 Oct 2026 16:19:31 |
| `github_repos/hec-ras-stac_github_archive.tar.gz` | 1,958,665 | 07 Oct 2026 16:19:31 |
| `github_repos/hfaggregate_github_archive.tar.gz` | 1,198,765 | 07 Oct 2026 16:19:31 |
| `github_repos/hfngen_github_archive.tar.gz` | 2,981,976 | 07 Oct 2026 16:19:32 |
| `github_repos/hfrefactor_github_archive.tar.gz` | 121,485 | 07 Oct 2026 16:19:32 |
| `github_repos/hfsubset_github_archive.tar.gz` | 20,128,648 | 07 Oct 2026 16:19:32 |
| `github_repos/hfutils_github_archive.tar.gz` | 3,719,875 | 07 Oct 2026 16:19:32 |
| `github_repos/hyAggregate_github_archive.tar.gz` | 57,502,401 | 07 Oct 2026 16:19:32 |
| `github_repos/hyRelease_github_archive.tar.gz` | 1,500,467 | 07 Oct 2026 16:19:35 |
| `github_repos/hydrofab_github_archive.tar.gz` | 248,385,225 | 07 Oct 2026 16:19:33 |
| `github_repos/hydrofabric-builds_github_archive.tar.gz` | 209,875,325 | 07 Oct 2026 16:19:34 |
| `github_repos/hydrofabric_github_archive.tar.gz` | 451,433,054 | 13 Jul 2026 18:21:11 |
| `github_repos/hydrofabric_v2.2_github_archive.tar.gz` | 451,437,253 | 07 Oct 2026 16:19:35 |
| `github_repos/hydrotools_github_archive.tar.gz` | 33,774,927 | 07 Oct 2026 16:19:35 |
| `github_repos/hydrovis-notifications_github_archive.tar.gz` | 810,972 | 07 Apr 2026 21:08:11 |
| `github_repos/hydrovis-nwps-core_github_archive.tar.gz` | 41,824,718 | 07 Apr 2026 21:08:12 |
| `github_repos/hydrovis-nwps-hydrogen_github_archive.tar.gz` | 38,727,286 | 07 Apr 2026 21:08:12 |
| `github_repos/hydrovis-nwps-qpe-accumulator_github_archive.tar.gz` | 45,620,416 | 07 Apr 2026 21:08:13 |
| `github_repos/hydrovis-nwps-terraform_github_archive.tar.gz` | 86,815 | 07 Apr 2026 21:08:13 |
| `github_repos/hydrovis_github_archive.tar.gz` | 849,933,370 | 07 Apr 2026 21:08:11 |
| `github_repos/hypy_github_archive.tar.gz` | 934,932 | 07 Oct 2026 16:19:35 |
| `github_repos/icefabric_github_archive.tar.gz` | 210,373,242 | 07 Oct 2026 16:19:36 |
| `github_repos/inundation-mapping-lidar_github_archive.tar.gz` | 1,509,252 | 07 Oct 2026 16:19:36 |
| `github_repos/inundation-mapping_github_archive.tar.gz` | 40,714,665 | 07 Oct 2026 16:19:36 |
| `github_repos/iso_c_fortran_bmi_github_archive.tar.gz` | 1,912,475 | 07 Oct 2026 16:19:36 |
| `github_repos/lstm_github_archive.tar.gz` | 148,343,107 | 07 Oct 2026 16:19:38 |
| `github_repos/near_real-time_sfincs_github_archive.tar.gz` | 5,834,819 | 07 Oct 2026 16:19:38 |
| `github_repos/nextgen-support-scripts_github_archive.tar.gz` | 2,505,287 | 07 Oct 2026 16:19:39 |
| `github_repos/ngen-cal_github_archive.tar.gz` | 2,585,764 | 07 Oct 2026 16:19:39 |
| `github_repos/ngen-forcing_github_archive.tar.gz` | 140,490,137 | 07 Oct 2026 16:19:40 |
| `github_repos/ngen.hydrofab_github_archive.tar.gz` | 1,923,728 | 07 Oct 2026 16:19:41 |
| `github_repos/ngen_github_archive.tar.gz` | 348,175,072 | 07 Oct 2026 16:19:41 |
| `github_repos/ngencerf-docker_github_archive.tar.gz` | 34,894 | 07 Oct 2026 16:19:39 |
| `github_repos/ngencerf-server_github_archive.tar.gz` | 23,906,207 | 07 Oct 2026 16:19:39 |
| `github_repos/ngencerf-ui_github_archive.tar.gz` | 28,903,571 | 07 Oct 2026 16:19:39 |
| `github_repos/ngwpc-cookbooks_github_archive.tar.gz` | 11,646,527 | 07 Oct 2026 16:19:41 |
| `github_repos/noah-owp-modular_github_archive.tar.gz` | 9,676,242 | 07 Oct 2026 16:19:42 |
| `github_repos/nomad-runner_github_archive.tar.gz` | 69,619 | 07 Oct 2026 16:19:42 |
| `github_repos/nrt-fim_github_archive.tar.gz` | 4,823,661 | 07 Oct 2026 16:19:42 |
| `github_repos/nwm-cal-mgr_github_archive.tar.gz` | 26,868,083 | 07 Oct 2026 16:19:42 |
| `github_repos/nwm-coastal_github_archive.tar.gz` | 184,998,137 | 07 Oct 2026 16:19:42 |
| `github_repos/nwm-data-assimilation_github_archive.tar.gz` | 2,391,976 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-eval-mgr_github_archive.tar.gz` | 9,803,117 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-ewts_github_archive.tar.gz` | 1,368,974 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-fcst-mgr_github_archive.tar.gz` | 403,408 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-gdrom_github_archive.tar.gz` | 1,513,380 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-msw-mgr_github_archive.tar.gz` | 11,933,676 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-ngencerf-infra_github_archive.tar.gz` | 1,747,216 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-post-processing_github_archive.tar.gz` | 2,795,239 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-region-mgr_github_archive.tar.gz` | 36,803,525 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-rte_github_archive.tar.gz` | 2,655,676 | 07 Oct 2026 16:19:43 |
| `github_repos/nwm-verf_github_archive.tar.gz` | 6,054,044 | 07 Oct 2026 16:19:43 |
| `github_repos/old/` | — | listed in parent index, but HTTP 404 |
| `github_repos/owp-open-source-project-template_github_archive.tar.gz` | 1,518,540 | 07 Oct 2026 16:19:43 |
| `github_repos/pfds-web_github_archive.tar.gz` | 1,723,949,450 | 07 Apr 2026 21:08:41 |
| `github_repos/predict-riverML_github_archive.tar.gz` | 2,915,647,179 | 07 Oct 2026 16:19:58 |
| `github_repos/rafts_github_archive.tar.gz` | 18,378,384 | 07 Oct 2026 16:19:58 |
| `github_repos/ras2fim_github_archive.tar.gz` | 10,260,066 | 07 Oct 2026 16:19:58 |
| `github_repos/reference-builds_github_archive.tar.gz` | 1,199,979 | 07 Oct 2026 16:19:58 |
| `github_repos/ripple1d-pipeline_github_archive.tar.gz` | 2,258,874 | 07 Oct 2026 16:19:59 |
| `github_repos/ripple1d_github_archive.tar.gz` | 58,400,904 | 07 Oct 2026 16:19:59 |
| `github_repos/sac-sma_github_archive.tar.gz` | 32,598,457 | 07 Oct 2026 16:20:00 |
| `github_repos/snow17_github_archive.tar.gz` | 47,192,163 | 07 Oct 2026 16:20:01 |
| `github_repos/t-route_github_archive.tar.gz` | 177,090,942 | 07 Oct 2026 16:20:05 |
| `github_repos/topmodel_github_archive.tar.gz` | 282,053,192 | 07 Oct 2026 16:20:02 |
| `github_repos/topoflow-glacier_github_archive.tar.gz` | 40,595,258 | 07 Oct 2026 16:20:04 |
| `github_repos/topoflow_github_archive.tar.gz` | 362,022,648 | 07 Oct 2026 16:20:04 |
| `github_repos/twod-fim-deployment_github_archive.tar.gz` | 681,802 | 07 Oct 2026 16:20:05 |
| `github_repos/twod-fim-jobs_github_archive.tar.gz` | 224,865 | 07 Oct 2026 16:20:05 |
| `github_repos/twod-fim-knowledge-base_github_archive.tar.gz` | 355,546,526 | 07 Oct 2026 16:20:06 |
| `github_repos/ueb_bmi_github_archive.tar.gz` | 5,871,045 | 07 Oct 2026 16:20:06 |
| `github_repos/wres-explorer_github_archive.tar.gz` | 2,985,851 | 07 Oct 2026 16:20:06 |
| `github_repos/wres_github_archive.tar.gz` | 696,661,929 | 07 Oct 2026 16:20:09 |
| `github_repos/zonal_github_archive.tar.gz` | 45,097,318 | 07 Oct 2026 16:20:09 |
| `nwm/data_tools/NWM_channel_hydrofabric.tar.gz` | 3,250,751,657 | 13 Apr 2023 14:58:23 |
| `nwm/data_tools/NWM_v2.0_channel_hydrofabric.tar.gz` | 1,133,451,424 | 10 Apr 2023 20:15:53 |
| `nwm/data_tools/NWM_v2.1_channel_hydrofabric.tar.gz` | 646,132,558 | 10 Apr 2023 20:15:29 |
| `nwm/data_tools/NWM_v3.0_channel_hydrofabric.tar.gz` | 3,250,751,657 | 13 Apr 2023 14:58:23 |
| `nwm/nwm_parameters/NWM_coastal_parameters.tar.gz` | 6,195,378,227 | 20 Sep 2023 16:10:28 |
| `nwm/nwm_parameters/NWM_coastal_parameters_v3.0.tar.gz` | 6,195,378,227 | 20 Sep 2023 16:10:28 |
| `nwm/nwm_parameters/NWM_parameter_files.tar.gz` | 4,678,832,855 | 20 Sep 2023 16:10:28 |
| `nwm/nwm_parameters/NWM_parameter_files_v2.1.tar.gz` | 4,485,467,589 | 20 Sep 2023 16:10:28 |
| `nwm/nwm_parameters/NWM_parameter_files_v3.0.tar.gz` | 4,678,832,855 | 20 Sep 2023 16:10:28 |
| `nwm/nwm_parameters/README.txt` | 1,900 | 20 Sep 2023 16:10:28 |
| `nwm/nwm_parameters/README.v3.0.txt` | 3,851 | 20 Sep 2023 16:10:28 |

</details>

Note (AI): the `github_repos/` tarballs are OWP source-code snapshots (t-route, ngen,
hydrofabric, inundation-mapping, …), not model parameters. Their members were not
cataloged.

### 3.2 `nwm_parameters/README.txt` (verbatim, 1,900 bytes) [S2]

```
Current NWM parameter files
---------------------------
 * Applies to NWM v2.0, starting 2019-06-19.
 * This file list and description also applies to previous versions of the
   NWM, but file contents may differ between versions.

* Fulldom_hires_netcdf_1km.nc.gz
File description:  This file contains gridded physiographic and model parameter
data for the 'Long-range' configuration of the National Water Model.

* Fulldom_hires_netcdf_250m.nc.gz
File description:  This file contains gridded physiographic and model parameter
data for the 'Analysis and Assimilation', 'Short Range' and 'Medium Range'
configurations of the National Water Model.

* RouteLink_NHDPLUS.nc.gz
File description:  This file contains river channel definition and parameter
data, and USGS stream gauge river reach definitions used in all configurations
of the National Water Model.

* spatialweights_1km_all_basins.nc.gz
File description:  This file contains the spatial regridding weights, used to
map variables from the 1km WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in the 'Long Range' configuration of the National Water Model.

* spatialweights_250m_all_basins.nc.gz
File description:  This file contains the spatial regridding weights, used to
map variables from the 250m WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in the 'Analysis and Assimilation', 'Short Range' and 'Medium
Range' configurations of the National Water Model.

* LAKEPARM_NHDPLUS.nc
File description: Provides the static parameters that describe the initial
fullness, size (in terms of surface area and maximum elevation), and discharge
mechanisms (orifice and weir) for each NWM waterbody. The lake_id corresponds
with the NHD+WaterbodyComID

* nudgingParams.nc 
File description: Channel_rt nudge parameters. Supplies the parameters for the
application of streamflow nudging data assimilation within the model
```

Note (AI): none of the seven files named here (`Fulldom_hires_netcdf_1km.nc.gz`,
`RouteLink_NHDPLUS.nc.gz`, …) is in any tarball now on the server. They are the
names of the NWM v2.0-era individual downloads.

### 3.3 `nwm_parameters/README.v3.0.txt` (verbatim, 3,851 bytes) [S3]

```
Parameter Description Document for 1) NWM Model and 2) NWM Coastal Module Parameters


1) Current NWM v3.0 parameter files
---------------------------
 * "DOMAIN" below can be:  
 *   CONUS, AK, PRVI or HI for Continental United States, 
 *   Alaska, Puerto Rico / US Virgin ISlands, and Hawaii domains


* Fulldom_CONUS_LongRange.nc
File description:  This file contains gridded physiographic and model parameter
data for the 'Long-range' and 'Long-Range Analysis', configurations of the National Water Model (only for CONUS).


* Fulldom_DOMAIN_FullRouting.nc
File description:  This file contains gridded physiographic and model parameter
data for the 'Analysis and Assimilation', 'Short Range' and 'Medium Range'
configurations of the National Water Model.


* LAKEPARM_DOMAIN.nc
File description: Provides the static parameters that describe the initial
fullness, size (in terms of surface area and maximum elevation), and discharge
mechanisms (orifice and weir) for each NWM waterbody. The lake_id corresponds
with the NHD+WaterbodyComID


* nudgingParams_DOMAIN.nc 
File description: Channel_rt nudge parameters. Supplies the parameters for the
application of streamflow nudging data assimilation within the model


* RouteLink_DOMAIN.nc
File description:  This file contains river channel definition and parameter
data, and USGS stream gauge river reach definitions used in all configurations
of the National Water Model.


* spatialweights_CONUS_LongRange.nc
File description:  This file contains the spatial regridding weights, used to
map variables from the 1km WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in the 'Long Range' and 'Long Range Analysis' configurations of the National Water Model.


* spatialweights_DOMAIN_FullRouting.nc
File description:  This file contains the spatial regridding weights, used to
map variables from the 100m/250m WRF-Hydro model grids to the NHDPlusv2 catchment
objects used in the 'Analysis and Assimilation', 'Short Range' and 'Medium
Range' configurations of the National Water Model.


 


2) Current NWM v3.0 Coastal Module (SCHISM) parameter files
---------------------------
* All files are available for the Atlantic Gulf, Pacific, Hawaii and Puerto Rico / US VI domains.


Files:


* bctides.in: Boundary condition input file with horizontal boundary condition and nudging options.
* element_areas.txt:  list of the elements on the SCHISM grids and their corresponding areas in m^2
* elev.ic: A .gr3 format file that specifies the initial elevation at each node.
* elevation_correction.csv: conversion from MSL to NAVD88 for the open boundary nodes on the Pacific and Atlantic domain SCHISM grids
* hgrid.gr3 and hgrid.ll:  Horizontal grid file with node centered spatial data and mesh connectivity
* hgrid.cpp and hgrid.utm: Horizontal grid files in cartesian and UTM coordinates for generating discharge files.
* hgrid.nc: grid file in netcdf format, containing a list of nodes with their locations and elevations along with a list of elements
* hgrid.vtk:  ASCII version of the grid file containing element number, element coordinates, and element original coordinates
* manning.gr3: Bottom friction input file
* nwmReaches.csv: List of the National Water Model Reach IDs which intersect the SCHISM model domain
* open_bnds_hgrid.nc: list of the open boundary nodes and their locations in netcdf format
* param.nml : Main parameter input file 
* vgrid.in: Vertical grid input file
* windrot_geo2proj.gr3: A .gr3 format file contains map projection information for atmospheric forcing files
* Ocean_Land_Mask*.nc: Land-ocean mask files
* k1.nc, k2.nc, m2.nc, n2.nc, o1.nc, p1.nc, q1.nc and S2.nc: Tidal constituents
* sflux_inputs.txt: ASCII file that contains a namelist for atmospheric forcing
```

### 3.4 `NWM_parameter_files_v2.1.tar.gz`

The tarball was read from an existing local copy (downloaded 2026-11-09). Its
SHA-256 `911fe35d9a6761183a3c9957794b5631fe013bde408edc38048c5b7808e679ea` and length
match the published file. Every member's MD5 matches the tarball's own `md5sum.txt`.
Member dates are tar mtimes in UTC.

Compressed: 4,485,467,589 bytes, SHA-256 `911fe35d9a6761183a3c9957794b5631fe013bde408edc38048c5b7808e679ea` (computed on the stream, 2026-11-10).

| Member | Bytes | Date in tar (UTC) | MD5 | Format | Dimensions | `version` attr | Description key |
|---|---:|---|---|---|---|---|---|
| [NWM_parameters_v2.1/RouteLink_CONUS.nc](headers/v2.1/NWM_parameters_v2.1__RouteLink_CONUS.nc.cdl) | 269,366,417 | 2021-03-08 22:54 | `7c6d36554c39df06693a7589597ab484` | netCDF-4 classic model | feature_id=2776738, IDLength=15 | NWM v2.1 | [RouteLink](#desc-routelink) |
| [NWM_parameters_v2.1/LAKEPARM_CONUS.nc](headers/v2.1/NWM_parameters_v2.1__LAKEPARM_CONUS.nc.cdl) | 583,546 | 2021-03-08 23:39 | `a895833399efffa4a682791d83a9ed60` | netCDF-4 classic model | feature_id=5783 | NWM v2.1 | [LAKEPARM](#desc-lakeparm) |
| [NWM_parameters_v2.1/nudgingParams_CONUS.nc](headers/v2.1/NWM_parameters_v2.1__nudgingParams_CONUS.nc.cdl) | 2,677,812 | 2021-03-08 23:39 | `576a977eea18cfd7c99bf2657b688f19` | netCDF-4 | stationIdStrLen=15, stationIdInd=UNLIMITED(7994), threshInd=1, monthInd=12, threshCatInd=2 | NWM v2.1 | [nudgingParams](#desc-nudgingparams) |
| [NWM_parameters_v2.1/Fulldom_CONUS_LongRange.nc](headers/v2.1/NWM_parameters_v2.1__Fulldom_CONUS_LongRange.nc.cdl) | 760,985,740 | 2021-03-08 22:54 | `7db92aef6837acd9f5dc2a76b149a06f` | netCDF-4 classic model | y=3840, x=4608 | NWM v2.1 | [Fulldom](#desc-fulldom) |
| [NWM_parameters_v2.1/Fulldom_CONUS_FullRouting.nc](headers/v2.1/NWM_parameters_v2.1__Fulldom_CONUS_FullRouting.nc.cdl) | 13,589,932,407 | 2021-03-08 23:00 | `dae0768e6a2977c8de1c57620c4be4aa` | netCDF-4 classic model | y=15360, x=18432 | NWM v2.1 | [Fulldom](#desc-fulldom) |
| [NWM_parameters_v2.1/Fulldom_HI_FullRouting.nc](headers/v2.1/NWM_parameters_v2.1__Fulldom_HI_FullRouting.nc.cdl) | 828,475,389 | 2021-03-08 23:00 | `ccd03b89b3801c987f2072d3e15fda3e` | netCDF-4 classic model | y=3900, x=5900 | NWM v2.1 | [Fulldom](#desc-fulldom) |
| [NWM_parameters_v2.1/Fulldom_PRVI_FullRouting.nc](headers/v2.1/NWM_parameters_v2.1__Fulldom_PRVI_FullRouting.nc.cdl) | 168,366,969 | 2021-03-08 22:59 | `0ed45272d739ae609ef5dd4410d1b7ef` | netCDF-4 classic model | y=1100, x=3000 | NWM v2.1 | [Fulldom](#desc-fulldom) |
| [NWM_parameters_v2.1/LAKEPARM_HI.nc](headers/v2.1/NWM_parameters_v2.1__LAKEPARM_HI.nc.cdl) | 22,950 | 2021-03-08 23:39 | `250675556ed6bee727168e379c4e174e` | netCDF-4 | feature_id=9, string1=1 | NWM v2.1 | [LAKEPARM](#desc-lakeparm) |
| [NWM_parameters_v2.1/LAKEPARM_PRVI.nc](headers/v2.1/NWM_parameters_v2.1__LAKEPARM_PRVI.nc.cdl) | 23,095 | 2021-03-08 23:38 | `c8e3fe28bd1916a9eeddbd3f5e15112f` | netCDF-4 classic model | feature_id=15 | NWM v2.1 | [LAKEPARM](#desc-lakeparm) |
| [NWM_parameters_v2.1/RouteLink_HI.nc](headers/v2.1/NWM_parameters_v2.1__RouteLink_HI.nc.cdl) | 1,346,576 | 2021-03-08 22:58 | `08d48fde4c00cecc3be05beb6f411ca0` | netCDF-4 classic model | feature_id=13637, IDLength=15 | NWM v2.1 | [RouteLink](#desc-routelink) |
| [NWM_parameters_v2.1/RouteLink_PRVI.nc](headers/v2.1/NWM_parameters_v2.1__RouteLink_PRVI.nc.cdl) | 1,380,521 | 2021-03-08 22:59 | `b3dc9745ebb428b52c7cf30ff22d12db` | netCDF-4 classic model | feature_id=14017, IDLength=15 | NWM v2.1 | [RouteLink](#desc-routelink) |
| [NWM_parameters_v2.1/nudgingParams_HI.nc](headers/v2.1/NWM_parameters_v2.1__nudgingParams_HI.nc.cdl) | 49,188 | 2021-03-08 23:39 | `4deb94c0f30df0a04ecb2665575f6d1e` | netCDF-4 | stationIdStrLen=15, stationIdInd=UNLIMITED(58), threshInd=1, monthInd=12, threshCatInd=2 | NWM v2.1 | [nudgingParams](#desc-nudgingparams) |
| [NWM_parameters_v2.1/nudgingParams_PRVI.nc](headers/v2.1/NWM_parameters_v2.1__nudgingParams_PRVI.nc.cdl) | 71,132 | 2021-03-08 23:38 | `7233c93822a9db1ef309ae4bde8ffe6e` | netCDF-4 | stationIdStrLen=15, stationIdInd=UNLIMITED(83), threshInd=1, monthInd=12, threshCatInd=2 | NWM v2.1 | [nudgingParams](#desc-nudgingparams) |
| [NWM_parameters_v2.1/spatialweights_CONUS_LongRange.nc](headers/v2.1/NWM_parameters_v2.1__spatialweights_CONUS_LongRange.nc.cdl) | 639,711,046 | 2021-03-08 22:59 | `68346d781274009a4d17045a926f534e` | netCDF-4 | polyid=2724837, data=22067991 | NWM v2.1 | [spatialweights](#desc-spatialweights) |
| [NWM_parameters_v2.1/spatialweights_CONUS_FullRouting.nc](headers/v2.1/NWM_parameters_v2.1__spatialweights_CONUS_FullRouting.nc.cdl) | 4,962,512,130 | 2021-03-08 23:01 | `057c41bbdfec4af462f0ae7eb0e15c00` | netCDF-4 | polyid=2724837, data=176453744 | NWM v2.1 | [spatialweights](#desc-spatialweights) |
| [NWM_parameters_v2.1/spatialweights_HI_FullRouting.nc](headers/v2.1/NWM_parameters_v2.1__spatialweights_HI_FullRouting.nc.cdl) | 40,222,955 | 2021-03-08 22:58 | `2701bf4e333d2f2ef526cb22e9d24a50` | netCDF-4 | polyid=13296, data=1432428 | NWM v2.1 | [spatialweights](#desc-spatialweights) |
| [NWM_parameters_v2.1/spatialweights_PRVI_FullRouting.nc](headers/v2.1/NWM_parameters_v2.1__spatialweights_PRVI_FullRouting.nc.cdl) | 36,604,358 | 2021-03-08 22:59 | `695a1d6b0a8ee3732342e8ceea5b0d07` | netCDF-4 | polyid=13692, data=1138467 | NWM v2.1 | [spatialweights](#desc-spatialweights) |
| `NWM_parameters_v2.1/md5sum.txt` | 994 | 2021-04-13 22:29 | `23dc748e58e33a5739e2bed326accdf6` | text |  |  | [md5sum](#desc-md5sum) |
| `NWM_parameters_v2.1/README.txt` | 2,003 | 2021-04-14 19:29 | `c682ce9fe37be8181e7f3dba876b2f1d` | text |  |  | [README](#desc-readme) |

The tarball's own `README.txt` (verbatim, 2,003 bytes):

```
Current NWM parameter files
---------------------------
 * Applies to NWM v2.1, starting early 2021. Files included for CONUS, Hawaii (HI),
   and Puerto Rico/US Virgin Islands (PRVI) modeling domains.
 * This file list and description generally applies to previous versions of the
   NWM, but file contents may differ between versions.

* Fulldom_CONUS_LongRange
File description:  This file contains gridded physiographic and model parameter
data for the 'Long-range' CONUS configuration of the National Water Model.

* Fulldom_*_FullRouting
File description:  This file contains gridded physiographic and model parameter
data for all 'Analysis and Assimilation', 'Short Range' and 'Medium Range'
configurations of the National Water Model.

* RouteLink
File description:  This file contains river channel definition and parameter
data, and USGS stream gauge river reach definitions used in all configurations
of the National Water Model. Based on NHDPlus v2.

* spatialweights_CONUS_LongRange
File description:  This file contains the spatial regridding weights, used to
map variables from the 1km WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in the 'Long Range' CONUS configuration of the National Water Model.

* spatialweights_*_FullRouting
File description:  This file contains the spatial regridding weights, used to
map variables from the 250m WRF-Hydro model grid to the NHDPlusv2 catchment
objects used in all 'Analysis and Assimilation', 'Short Range' and 'Medium
Range' configurations of the National Water Model.

* LAKEPARM
File description: Provides the static parameters that describe the initial
fullness, size (in terms of surface area and maximum elevation), and discharge
mechanisms (orifice and weir) for each NWM waterbody. The lake_id corresponds
with the NHD+WaterbodyComID. Based on NHDPlus v2.

* nudgingParams 
File description: Channel_rt nudge parameters. Supplies the parameters for the
application of streamflow nudging data assimilation within the model
```

### 3.5 `NWM_parameter_files_v3.0.tar.gz`

Streamed from NOHRSC 2026-11-10, 16:38–16:56 UTC. Every member's MD5 matches the
tarball's `md5sum.txt`. There is no README inside; the description is `README.v3.0.txt`
(§3.3).

Compressed: 4,678,832,855 bytes, SHA-256 `1d8a7e1eb506ec38a2ff0de64b1b5ebc7472205e0d660ee28080a9e15b6ce38c` (computed on the stream, 2026-11-10).

| Member | Bytes | Date in tar (UTC) | MD5 | Format | Dimensions | `version` attr | Description key |
|---|---:|---|---|---|---|---|---|
| [v3.0_par/nudgingParams_AK.nc](headers/v3.0/v3.0_par__nudgingParams_AK.nc.cdl) | 68,158 | 2023-07-10 15:10 | `ab53781d4d759365ff6af69f5912e4f3` | netCDF-4 | stationIdStrLen=15, stationIdInd=UNLIMITED(65), threshInd=1, monthInd=12, threshCatInd=2 | NWM v3.0 | [nudgingParams](#desc-nudgingparams) |
| [v3.0_par/Fulldom_AK_FullRouting.nc](headers/v3.0/v3.0_par__Fulldom_AK_FullRouting.nc.cdl) | 329,305,930 | 2023-07-10 15:09 | `7ac9df1356f7abfcce139f0c81eac775` | netCDF-4 classic model | y=1836, x=3516, string1=1 | — | [Fulldom](#desc-fulldom) |
| [v3.0_par/spatialweights_HI_FullRouting.nc](headers/v3.0/v3.0_par__spatialweights_HI_FullRouting.nc.cdl) | 40,222,955 | 2023-07-10 15:00 | `a3ab8ea2c6ee4f6517456b171ee1a3a3` | netCDF-4 | polyid=13296, data=1432428 | NWM v3.0 | [spatialweights](#desc-spatialweights) |
| [v3.0_par/LAKEPARM_HI.nc](headers/v3.0/v3.0_par__LAKEPARM_HI.nc.cdl) | 22,950 | 2023-07-10 14:57 | `920d519100533a59b6618b5c3c48834d` | netCDF-4 | feature_id=9, string1=1 | NWM v3.0 | [LAKEPARM](#desc-lakeparm) |
| [v3.0_par/Fulldom_PRVI_FullRouting.nc](headers/v3.0/v3.0_par__Fulldom_PRVI_FullRouting.nc.cdl) | 181,574,634 | 2023-07-10 14:56 | `31e0edfe203d144f5f4ba7a3d14fb2a7` | netCDF-4 classic model | y=1100, x=3000 | NWM v3.0 | [Fulldom](#desc-fulldom) |
| [v3.0_par/spatialweights_CONUS_FullRouting.nc](headers/v3.0/v3.0_par__spatialweights_CONUS_FullRouting.nc.cdl) | 4,962,512,130 | 2023-07-10 15:00 | `cdc8803a84e832bab6d22935b448c97c` | netCDF-4 | polyid=2724837, data=176453744 | NWM v3.0 | [spatialweights](#desc-spatialweights) |
| [v3.0_par/Fulldom_CONUS_LongRange.nc](headers/v3.0/v3.0_par__Fulldom_CONUS_LongRange.nc.cdl) | 760,987,866 | 2023-07-10 14:55 | `1d0c852ff6d2328090ca560277753e12` | netCDF-4 classic model | y=3840, x=4608 | NWM v3.0 | [Fulldom](#desc-fulldom) |
| [v3.0_par/nudgingParams_CONUS.nc](headers/v3.0/v3.0_par__nudgingParams_CONUS.nc.cdl) | 2,893,494 | 2023-07-10 14:58 | `87b58468772b69b6a2f65f5f57640d9b` | netCDF-4 | stationIdStrLen=15, stationIdInd=UNLIMITED(8660), threshInd=1, monthInd=12, threshCatInd=2 | — | [nudgingParams](#desc-nudgingparams) |
| [v3.0_par/RouteLink_CONUS.nc](headers/v3.0/v3.0_par__RouteLink_CONUS.nc.cdl) | 269,363,375 | 2023-07-10 14:59 | `67728d130b85793e327aa4b7069a35d1` | netCDF-4 classic model | feature_id=2776734, IDLength=15 | — | [RouteLink](#desc-routelink) |
| [v3.0_par/Fulldom_CONUS_FullRouting.nc](headers/v3.0/v3.0_par__Fulldom_CONUS_FullRouting.nc.cdl) | 12,460,271,263 | 2023-07-10 14:53 | `5fc08a16f0826afb34313f7f403903a1` | netCDF-4 | y=15360, x=18432, string1=1 | NWM v3.0 | [Fulldom](#desc-fulldom) |
| [v3.0_par/spatialweights_PRVI_FullRouting.nc](headers/v3.0/v3.0_par__spatialweights_PRVI_FullRouting.nc.cdl) | 36,604,358 | 2023-07-10 15:00 | `6adb4efb972175f923d0f68dbdc56b8b` | netCDF-4 | polyid=13692, data=1138467 | NWM v3.0 | [spatialweights](#desc-spatialweights) |
| [v3.0_par/spatialweights_AK_FullRouting.nc](headers/v3.0/v3.0_par__spatialweights_AK_FullRouting.nc.cdl) | 186,703,565 | 2023-07-10 15:10 | `f6a1358911c3996196e2b8b6aca438f5` | netCDF-4 | polyid=390548, data=5687748 | NWM v3.0 | [spatialweights](#desc-spatialweights) |
| [v3.0_par/spatialweights_CONUS_LongRange.nc](headers/v3.0/v3.0_par__spatialweights_CONUS_LongRange.nc.cdl) | 639,711,046 | 2023-07-10 15:00 | `70c4369086317a81d30374f502f566fd` | netCDF-4 | polyid=2724837, data=22067991 | NWM v3.0 | [spatialweights](#desc-spatialweights) |
| [v3.0_par/nudgingParams_PRVI.nc](headers/v3.0/v3.0_par__nudgingParams_PRVI.nc.cdl) | 71,038 | 2023-07-10 14:58 | `5255ecff1dd502c6838f2c7d299ca267` | netCDF-4 | stationIdStrLen=15, stationIdInd=UNLIMITED(83), threshInd=1, monthInd=12, threshCatInd=2 | NWM v3.0 | [nudgingParams](#desc-nudgingparams) |
| [v3.0_par/RouteLink_AK.nc](headers/v3.0/v3.0_par__RouteLink_AK.nc.cdl) | 47,399,233 | 2023-07-10 15:10 | `f6e607e92c3ad4d60bd7f7824ff57efd` | netCDF-4 | feature_id=391528, IDLength=15 | NWM v3.0 | [RouteLink](#desc-routelink) |
| `v3.0_par/md5sum.txt` | 1,318 | 2023-07-10 15:12 | `5cf24f35d6beaed010540db2f8410d31` | text |  |  | [md5sum](#desc-md5sum) |
| [v3.0_par/nudgingParams_HI.nc](headers/v3.0/v3.0_par__nudgingParams_HI.nc.cdl) | 49,188 | 2023-07-10 14:58 | `df5f734451061987ebc159abf80090d3` | netCDF-4 | stationIdStrLen=15, stationIdInd=UNLIMITED(58), threshInd=1, monthInd=12, threshCatInd=2 | NWM v3.0 | [nudgingParams](#desc-nudgingparams) |
| [v3.0_par/LAKEPARM_AK.nc](headers/v3.0/v3.0_par__LAKEPARM_AK.nc.cdl) | 45,788 | 2023-07-10 15:10 | `f9f95eeda7ec8c2b08d66fee785f8676` | netCDF-4 | feature_id=237 | NWM v3.0 | [LAKEPARM](#desc-lakeparm) |
| [v3.0_par/LAKEPARM_PRVI.nc](headers/v3.0/v3.0_par__LAKEPARM_PRVI.nc.cdl) | 20,704 | 2023-07-10 14:57 | `cd7a173635458a08f9b51ef471a46c84` | netCDF-4 classic model | feature_id=16 | NWM v3.0 | [LAKEPARM](#desc-lakeparm) |
| [v3.0_par/RouteLink_HI.nc](headers/v3.0/v3.0_par__RouteLink_HI.nc.cdl) | 1,346,576 | 2023-07-10 14:59 | `5c1e48939ced20054d98c5842c784496` | netCDF-4 classic model | feature_id=13637, IDLength=15 | NWM v3.0 | [RouteLink](#desc-routelink) |
| [v3.0_par/RouteLink_PRVI.nc](headers/v3.0/v3.0_par__RouteLink_PRVI.nc.cdl) | 1,380,709 | 2023-07-10 14:59 | `d4089177eb1bba4f2df8e68492d8a83c` | netCDF-4 classic model | feature_id=14017, IDLength=15 | NWM v3.0 | [RouteLink](#desc-routelink) |
| [v3.0_par/Fulldom_HI_FullRouting.nc](headers/v3.0/v3.0_par__Fulldom_HI_FullRouting.nc.cdl) | 828,475,389 | 2023-07-10 14:56 | `98809352c15553eef895d5626fb6bd75` | netCDF-4 classic model | y=3900, x=5900 | NWM v3.0 | [Fulldom](#desc-fulldom) |
| [v3.0_par/LAKEPARM_CONUS.nc](headers/v3.0/v3.0_par__LAKEPARM_CONUS.nc.cdl) | 581,707 | 2023-07-10 14:56 | `97db3d8f22ceb8a478360b3b8e212cbc` | netCDF-4 | feature_id=5782, string1=1 | — | [LAKEPARM](#desc-lakeparm) |

### 3.6 `NWM_coastal_parameters_v3.0.tar.gz`

Streamed 2026-11-10, 16:56–17:28 UTC. Member paths start with `./coastal/`. The
descriptions are in `README.v3.0.txt` part 2 (§3.3) and in [§4](#desc-coastal).

Compressed: 6,195,378,227 bytes, SHA-256 `6b73c2b7e57fe4903ac46aa0781f2226da8bf81b85c39cc9b99c0a18b53cc431` (computed on the stream, 2026-11-10).

| Member | Bytes | Date in tar (UTC) | MD5 | Format | Dimensions | `version` attr | Description key |
|---|---:|---|---|---|---|---|---|
| [coastal/Tides/TidalConst/n2.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__n2.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `f05014b2c0fb3b2ffe723a79dda21ed3` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| [coastal/Tides/TidalConst/m2.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__m2.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `ba25f413b336dcb8b50ee4b83e83e275` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| [coastal/Tides/TidalConst/o1.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__o1.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `34ea85df99d7b81bf2dfa1ff88a8ad62` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| [coastal/Tides/TidalConst/q1.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__q1.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `c22ae8b6cdfe82b0e9e59c238d6ee28c` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| [coastal/Tides/TidalConst/k1.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__k1.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `314a49d3eb3cbd1175c4ad6dad7a7864` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| [coastal/Tides/TidalConst/k2.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__k2.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `dfaf5ecee6176a79efcbd5b5b5620896` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| [coastal/Tides/TidalConst/p1.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__p1.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `1bc049bcc0f51e6cf94901d70e94f8bd` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| [coastal/Tides/TidalConst/s2.nc](headers/coastal_v3.0/coastal__Tides__TidalConst__s2.nc.cdl) | 132,879,586 | 2022-12-02 19:10 | `3e1efb98c7f2280dd7fd99e5b98b5d24` | netCDF-4 | lat=2881, lon=5760, nv=2 | — | [tides](#desc-tides) |
| `coastal/hawaii/windrot_geo2proj.gr3` | 80,636,157 | 2023-01-27 14:23 | `c7b7ba35a794268ca4dd92db75ed4084` | text |  |  | [windrot_geo2proj.gr3](#desc-coastal) |
| `coastal/hawaii/vgrid.in` | 172 | 2022-10-26 18:00 | `13af415067a30369603a4002db7d695b` | text |  |  | [vgrid.in](#desc-coastal) |
| [coastal/hawaii/open_bnds_hgrid.nc](headers/coastal_v3.0/coastal__hawaii__open_bnds_hgrid.nc.cdl) | 422,410 | 2023-01-27 14:27 | `31c845baea78a85cac53a0bd98101d23` | netCDF-4 | nodeCount=8695, openBndNodeCount=4350, elementCount=8695, maxNodePElement=3, coordDim=2 | 0.9 | [open_bnds_hgrid.nc](#desc-coastal) |
| `coastal/hawaii/hgrid.utm` | 39,114,789 | 2022-10-26 18:00 | `fe95f78302d716ceabdc719cb16bec5c` | text |  |  | [hgrid.utm](#desc-coastal) |
| [coastal/hawaii/hgrid.nc](headers/coastal_v3.0/coastal__hawaii__hgrid.nc.cdl) | 63,464,378 | 2023-01-27 14:26 | `2ef444aa432c2eabf47332d9e191d607` | netCDF-4 | nodeCount=878770, elementCount=1703252, maxNodePElement=3, coordDim=2 | 0.9 | [hgrid.nc](#desc-coastal) |
| `coastal/hawaii/elev.ic` | 84,855,138 | 2023-03-12 02:12 | `010c316eed038a2991407842c9c5e0e7` | text |  |  | [elev.ic](#desc-coastal) |
| `coastal/hawaii/element_areas.txt` | 13,426,191 | 2023-01-27 14:27 | `f8a610a17552cdbbfcc1eb7e82527e49` | text |  |  | [element_areas.txt](#desc-coastal) |
| `coastal/hawaii/hgrid.gr3` | 86,109,350 | 2023-03-12 02:13 | `30cd27afb9f83770a7ede777f8a25bed` | text |  |  | [hgrid.gr3](#desc-coastal) |
| `coastal/hawaii/nwmReaches.csv` | 15,251 | 2023-01-27 14:23 | `980b342d4e0f487080ccb4367e8113a7` | text |  |  | [nwmReaches.csv](#desc-coastal) |
| `coastal/hawaii/manning.gr3` | 81,876,381 | 2023-01-27 14:23 | `f7607abc24b277dcf44617bcb10b1ad6` | text |  |  | [manning.gr3](#desc-coastal) |
| `coastal/hawaii/hgrid.ll` | 86,109,350 | 2023-03-12 02:13 | `30cd27afb9f83770a7ede777f8a25bed` | text |  |  | [hgrid.ll](#desc-coastal) |
| `coastal/hawaii/sflux/sflux_inputs.txt` | 16 | 2022-10-26 18:00 | `4b15331d78774cf49ae8a9701c481afc` | text |  |  | [sflux_inputs.txt](#desc-coastal) |
| `coastal/hawaii/hgrid.cpp` | 99,729,099 | 2023-02-15 19:24 | `e558bec8e82f7e6756d7dc5ea420f511` | text |  |  | [hgrid.cpp](#desc-coastal) |
| `coastal/hawaii/hgrid.vtk` | 48,836,839 | 2022-10-26 18:00 | `1885d6035a39b7d58dee1cee756acb64` | text |  |  | [hgrid.vtk](#desc-coastal) |
| `coastal/hawaii/param.nml` | 49,519 | 2023-04-14 15:19 | `72717386229ab8273279daf12d942c87` | text |  |  | [param.nml](#desc-coastal) |
| `coastal/hawaii/bctides.in` | 82 | 2023-01-27 14:22 | `b793281842a8e30ee46d89440396c93c` | text |  |  | [bctides.in](#desc-coastal) |
| `coastal/atlgulf/windrot_geo2proj.gr3` | 1,085,234,838 | 2023-04-28 17:44 | `90780bc1774c6bdcb9e2e608e6e5f27f` | text |  |  | [windrot_geo2proj.gr3](#desc-coastal) |
| `coastal/atlgulf/vgrid.in` | 172 | 2023-04-28 17:44 | `13af415067a30369603a4002db7d695b` | text |  |  | [vgrid.in](#desc-coastal) |
| [coastal/atlgulf/open_bnds_hgrid.nc](headers/coastal_v3.0/coastal__atlgulf__open_bnds_hgrid.nc.cdl) | 999,841 | 2023-04-28 17:44 | `8ea16365acb4488f6d89413300fd5305` | netCDF-4 | nodeCount=21096, openBndNodeCount=9211, elementCount=21094, maxNodePElement=3, coordDim=2 | 0.9 | [open_bnds_hgrid.nc](#desc-coastal) |
| `coastal/atlgulf/hgrid.utm` | 1,060,814,755 | 2023-05-01 13:41 | `e1e9fbafcd90cfa8d324ddd6763ca872` | text |  |  | [hgrid.utm](#desc-coastal) |
| [coastal/atlgulf/hgrid.nc](headers/coastal_v3.0/coastal__atlgulf__hgrid.nc.cdl) | 776,682,334 | 2023-04-28 17:43 | `412e388318798812bb5140c8e486ee6c` | netCDF-4 | nodeCount=10537609, elementCount=20967960, maxNodePElement=3, coordDim=2 | 0.9 | [hgrid.nc](#desc-coastal) |
| `coastal/atlgulf/elev.ic` | 1,141,687,052 | 2023-04-28 17:43 | `c504887613fadd455dfbc212171c7a2b` | text |  |  | [elev.ic](#desc-coastal) |
| `coastal/atlgulf/element_areas.txt` | 164,656,091 | 2023-04-28 17:43 | `31ccb0adb3b49f5c5cd475621753d6ca` | text |  |  | [element_areas.txt](#desc-coastal) |
| `coastal/atlgulf/hgrid.gr3` | 1,145,865,241 | 2023-04-28 17:43 | `7e230445295c28a98e14758d3f0d2865` | text |  |  | [hgrid.gr3](#desc-coastal) |
| `coastal/atlgulf/nwmReaches.csv` | 106,799 | 2023-04-28 17:44 | `53df181b1fec66daf97269fe16ae75d4` | text |  |  | [nwmReaches.csv](#desc-coastal) |
| `coastal/atlgulf/manning.gr3` | 1,098,881,790 | 2023-04-28 17:44 | `febbbe564f8c35c4c5754f3e63b483ae` | text |  |  | [manning.gr3](#desc-coastal) |
| `coastal/atlgulf/hgrid.ll` | 1,145,865,241 | 2023-04-28 17:43 | `7e230445295c28a98e14758d3f0d2865` | text |  |  | [hgrid.ll](#desc-coastal) |
| `coastal/atlgulf/sflux/sflux_inputs.txt` | 16 | 2023-04-26 19:43 | `4b15331d78774cf49ae8a9701c481afc` | text |  |  | [sflux_inputs.txt](#desc-coastal) |
| `coastal/atlgulf/hgrid.cpp` | 1,297,667,657 | 2023-04-28 17:43 | `710fa27115d4902a51e146922e218dfc` | text |  |  | [hgrid.cpp](#desc-coastal) |
| `coastal/atlgulf/hgrid.vtk` | 1,406,890,042 | 2023-04-28 17:44 | `6eaad434f0095606a2eca0de1edb2309` | text |  |  | [hgrid.vtk](#desc-coastal) |
| `coastal/atlgulf/param.nml` | 49,518 | 2023-04-14 15:19 | `bb3a1eadd489318d40aa89052fdbcd79` | text |  |  | [param.nml](#desc-coastal) |
| `coastal/atlgulf/elevation_correction.csv` | 938,281 | 2023-04-28 17:43 | `bd5da6a1e4efcb88ff0ed45c40568321` | text |  |  | [elevation_correction.csv](#desc-coastal) |
| `coastal/atlgulf/bctides.in` | 71 | 2023-04-28 17:43 | `344115e7aae2ad1ce9fdec459f2a4ec3` | text |  |  | [bctides.in](#desc-coastal) |
| [coastal/maskFiles/Ocean_Land_Mask_PR_USVI_5m.nc](headers/coastal_v3.0/coastal__maskFiles__Ocean_Land_Mask_PR_USVI_5m.nc.cdl) | 118,580,912 | 2023-01-27 19:23 | `92d408ca150e34bbeefaea5e4d4be3ee` | 64-bit offset | index=3705642 | — | [mask](#desc-mask) |
| [coastal/maskFiles/Ocean_Land_Mask_Hawaii_5m.nc](headers/coastal_v3.0/coastal__maskFiles__Ocean_Land_Mask_Hawaii_5m.nc.cdl) | 28,121,008 | 2023-01-27 19:23 | `008d1cfcf34ddac15c8f0bc291dabf6a` | 64-bit offset | index=878770 | — | [mask](#desc-mask) |
| [coastal/maskFiles/Ocean_Land_Mask_5m_Pacific_Coast_V2.nc](headers/coastal_v3.0/coastal__maskFiles__Ocean_Land_Mask_5m_Pacific_Coast_V2.nc.cdl) | 100,432,048 | 2022-11-29 14:57 | `7f5f550c249c53210119dc012d4c8cb0` | 64-bit offset | index=3138490 | — | [mask](#desc-mask) |
| [coastal/maskFiles/Ocean_Land_Mask_AtlanticGulf_5m.nc](headers/coastal_v3.0/coastal__maskFiles__Ocean_Land_Mask_AtlanticGulf_5m.nc.cdl) | 505,812,812 | 2023-04-28 17:49 | `72d685d639b97eb7b78b9cb8b60e0a74` | netCDF-4 | index=10537609 | — | [mask](#desc-mask) |
| `coastal/pacific/windrot_geo2proj.gr3` | 328,965,912 | 2023-01-27 14:34 | `ab4f1851f39b92319b2387d4e7b6b620` | text |  |  | [windrot_geo2proj.gr3](#desc-coastal) |
| `coastal/pacific/vgrid.in` | 172 | 2022-10-26 18:01 | `13af415067a30369603a4002db7d695b` | text |  |  | [vgrid.in](#desc-coastal) |
| [coastal/pacific/open_bnds_hgrid.nc](headers/coastal_v3.0/coastal__pacific__open_bnds_hgrid.nc.cdl) | 2,201,562 | 2023-01-27 14:39 | `e45783c5168d52f9d015912fa067f46c` | netCDF-4 | nodeCount=46507, openBndNodeCount=23753, elementCount=46507, maxNodePElement=3, coordDim=2 | 0.9 | [open_bnds_hgrid.nc](#desc-coastal) |
| `coastal/pacific/hgrid.utm` | 381,095,165 | 2022-10-26 18:01 | `9884436f3f31f1343163ffa9469ac323` | text |  |  | [hgrid.utm](#desc-coastal) |
| [coastal/pacific/hgrid.nc](headers/coastal_v3.0/coastal__pacific__hgrid.nc.cdl) | 225,697,079 | 2023-01-27 14:38 | `59d8f90d8a1f1bb67fc9b0e300cfb115` | netCDF-4 | nodeCount=3138490, elementCount=6050741, maxNodePElement=3, coordDim=2 | 0.9 | [hgrid.nc](#desc-coastal) |
| `coastal/pacific/elev.ic` | 340,818,673 | 2023-03-10 22:32 | `a2aa9681534f38c2ad29268c20feaf1c` | text |  |  | [elev.ic](#desc-coastal) |
| `coastal/pacific/element_areas.txt` | 47,622,735 | 2023-01-27 14:40 | `5faddb43699d17513e173f98d99c1396` | text |  |  | [element_areas.txt](#desc-coastal) |
| `coastal/pacific/hgrid.gr3` | 346,251,903 | 2023-03-10 22:32 | `cae1d33654af96c21edc063cf080b97f` | text |  |  | [hgrid.gr3](#desc-coastal) |
| `coastal/pacific/nwmReaches.csv` | 74,848 | 2023-01-27 14:33 | `549b0a45de58489afb792eff1a590cda` | text |  |  | [nwmReaches.csv](#desc-coastal) |
| `coastal/pacific/manning.gr3` | 333,673,353 | 2023-01-27 14:33 | `9f0c699e0ce39a87b49c8bf83437b8bd` | text |  |  | [manning.gr3](#desc-coastal) |
| `coastal/pacific/hgrid.ll` | 346,251,903 | 2023-03-10 22:32 | `cae1d33654af96c21edc063cf080b97f` | text |  |  | [hgrid.ll](#desc-coastal) |
| `coastal/pacific/sflux/sflux_inputs.txt` | 16 | 2022-10-26 18:01 | `4b15331d78774cf49ae8a9701c481afc` | text |  |  | [sflux_inputs.txt](#desc-coastal) |
| `coastal/pacific/hgrid.cpp` | 370,454,132 | 2023-02-15 19:23 | `41cad83f41f27773f0437fbd839056cc` | text |  |  | [hgrid.cpp](#desc-coastal) |
| `coastal/pacific/hgrid.vtk` | 492,442,828 | 2022-10-26 18:00 | `3ad68e4898de3171cf30bd0dc97a1bdf` | text |  |  | [hgrid.vtk](#desc-coastal) |
| `coastal/pacific/param.nml` | 49,519 | 2023-04-14 15:19 | `a488d2f7b3e6bb42bb0285a188af4f6f` | text |  |  | [param.nml](#desc-coastal) |
| `coastal/pacific/elevation_correction.csv` | 2,506,640 | 2023-03-07 19:48 | `7b9090e212f21b521fac8f8bf2ce5d90` | text |  |  | [elevation_correction.csv](#desc-coastal) |
| `coastal/pacific/bctides.in` | 72 | 2023-01-27 14:32 | `2915e83a3cbc087a830fe73405258f17` | text |  |  | [bctides.in](#desc-coastal) |
| `coastal/prvi/windrot_geo2proj.gr3` | 370,667,778 | 2023-01-24 16:58 | `f9b0269fe3769bb333bff13afaaa265f` | text |  |  | [windrot_geo2proj.gr3](#desc-coastal) |
| `coastal/prvi/vgrid.in` | 172 | 2022-10-26 18:01 | `13af415067a30369603a4002db7d695b` | text |  |  | [vgrid.in](#desc-coastal) |
| [coastal/prvi/open_bnds_hgrid.nc](headers/coastal_v3.0/coastal__prvi__open_bnds_hgrid.nc.cdl) | 606,286 | 2023-01-24 20:36 | `29c218ad655d99762f8946c62840ee1f` | netCDF-4 | nodeCount=12783, openBndNodeCount=4329, elementCount=12783, maxNodePElement=3, coordDim=2 | 0.9 | [open_bnds_hgrid.nc](#desc-coastal) |
| `coastal/prvi/hgrid.utm` | 112,977,344 | 2022-10-26 18:01 | `bcf4533617e4918b81da8a54a138d0b8` | text |  |  | [hgrid.utm](#desc-coastal) |
| [coastal/prvi/hgrid.nc](headers/coastal_v3.0/coastal__prvi__hgrid.nc.cdl) | 273,082,222 | 2023-01-24 20:35 | `c2ce0aa37e3a8156dba96f36ad67d00a` | netCDF-4 | nodeCount=3705642, elementCount=7371800, maxNodePElement=3, coordDim=2 | 0.9 | [hgrid.nc](#desc-coastal) |
| `coastal/prvi/elev.ic` | 384,843,729 | 2023-03-10 22:27 | `c956de3f193aae1ae1fcddfece433682` | text |  |  | [elev.ic](#desc-coastal) |
| `coastal/prvi/element_areas.txt` | 58,123,395 | 2023-01-24 22:11 | `fa88a70128fd93671810a45d4c75d2c1` | text |  |  | [element_areas.txt](#desc-coastal) |
| `coastal/prvi/hgrid.gr3` | 391,844,826 | 2023-03-10 22:27 | `9332f5a56be5833393278284c26ef0ca` | text |  |  | [hgrid.gr3](#desc-coastal) |
| `coastal/prvi/nwmReaches.csv` | 15,821 | 2023-01-24 16:57 | `24b260d41eed9323b7461c69f7f9f923` | text |  |  | [nwmReaches.csv](#desc-coastal) |
| `coastal/prvi/manning.gr3` | 376,216,253 | 2023-01-24 16:57 | `6b7d656a9e5d092a905011cf3f97b78c` | text |  |  | [manning.gr3](#desc-coastal) |
| `coastal/prvi/hgrid.ll` | 391,844,826 | 2023-03-10 22:27 | `9332f5a56be5833393278284c26ef0ca` | text |  |  | [hgrid.ll](#desc-coastal) |
| `coastal/prvi/sflux/sflux_inputs.txt` | 16 | 2022-10-26 18:01 | `4b15331d78774cf49ae8a9701c481afc` | text |  |  | [sflux_inputs.txt](#desc-coastal) |
| `coastal/prvi/hgrid.cpp` | 446,212,653 | 2023-02-15 21:53 | `38ab7143cd9fb98eb1152d84f4bf1ae3` | text |  |  | [hgrid.cpp](#desc-coastal) |
| `coastal/prvi/hgrid.vtk` | 163,058,989 | 2022-10-26 18:01 | `f23a25df94acde86de639b2355f976c2` | text |  |  | [hgrid.vtk](#desc-coastal) |
| `coastal/prvi/param.nml` | 49,519 | 2023-04-14 15:20 | `72717386229ab8273279daf12d942c87` | text |  |  | [param.nml](#desc-coastal) |
| `coastal/prvi/bctides.in` | 83 | 2023-01-24 16:56 | `206a03ead11a1aeafb2d45a22ba36b05` | text |  |  | [bctides.in](#desc-coastal) |

### 3.7 Channel hydrofabric tarballs (`data_tools/`)

These have no README. water.noaa.gov says of the unversioned file: "the latitude and
longitude coordinates of the centroid of each reach are made available in a separate
ESRI file geo-database (gdb), outside of the NWM outputs. The file gdb can be used in many
common GIS software utilities to attach coordinates to the data." [S5]. Layer schemas were
read with pyogrio/GDAL 3.12.4 from a scratch extraction that was deleted afterwards.

**NWM_v2.0_channel_hydrofabric.tar.gz**: Compressed: 1,133,451,424 bytes, SHA-256 `3c8316813b4020142553b229f9570f47bf63e6d2a2e7b984f3a4890895b0f30b`. 69 files, 3,075,092,900 bytes uncompressed.
- 68 ESRI File Geodatabase internal files (`a0000000NN.gdbtable/.gdbtablx/.spx/.atx/.gdbindexes/.freelist/.horizon`, plus `gdb`, `timestamps`), 3,074,032,548 bytes, dated 2019-02-06 to 2019-02-28. Full per-file list with MD5: [listings/members_hydrofabric_v2.0.json](listings/members_hydrofabric_v2.0.json).
- `NWM_v2.0_channel_hydrofabric/nwm_v2_0_hydrofabric.mxd` (1,060,352 bytes, 2019-02-28, MD5 `0b0fd0a71bb7c7eddda5c62e51d3bba5`)

| Layer (`nwm_v2_0_hydrofabric.gdb`) | Geometry | Features | CRS | Fields |
|---|---|---:|---|---|
| nwm_reaches_conus | MultiLineString | 2,729,077 | EPSG:4269 | feature_id, source, lat, lon, gnis_name, stream_order, Shape_Length |
| nwm_reaches_hawaii | MultiLineString | 13,637 | EPSG:4269 | (same as conus) |
| nwm_catchments_conus | MultiPolygon | 2,677,135 | USA_Contiguous_Albers_Equal_Area_Conic | feature_id, source, Shape_Length, Shape_Area |
| nwm_catchments_hawaii | MultiPolygon | 13,296 | USA_Contiguous_Albers | (same) |
| nwm_waterbodies_conus | MultiPolygon Z | 5,459 | USA_Contiguous_Albers | feature_id, source, gnis_name, Shape_Length, Shape_Area |
| nwm_waterbodies_hawaii | MultiPolygon Z | 9 | USA_Contiguous_Albers | (same) |

**NWM_v2.1_channel_hydrofabric.tar.gz**: Compressed: 646,132,558 bytes, SHA-256 `7e20135bb54954a04ece50e3ed8c304cb765fbb565cd7f0b35813ccdb1d050ff`. 87 files, 939,825,532 bytes uncompressed.
- 86 ESRI File Geodatabase internal files (`a0000000NN.gdbtable/.gdbtablx/.spx/.atx/.gdbindexes/.freelist/.horizon`, plus `gdb`, `timestamps`), 939,216,252 bytes, dated 2020-01-29 to 2020-10-26. Full per-file list with MD5: [listings/members_hydrofabric_v2.1.json](listings/members_hydrofabric_v2.1.json).
- `NWM_v2.1_channel_hydrofabric_10262020/NWM_v2.1_channel_hydrofabric_10262020.mxd` (609,280 bytes, 2020-10-26, MD5 `924b691a79d63f421b4574a676273c04`)

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

**NWM_v3.0_channel_hydrofabric.tar.gz** (= `NWM_channel_hydrofabric.tar.gz`): Compressed: 3,250,751,657 bytes, SHA-256 `77d8975b543ff864cdac0736cc4f455fe86d77049c4d8b1fb8e458ec755dbc94`. 97 files, 5,067,922,143 bytes uncompressed.
- 97 ESRI File Geodatabase internal files (`a0000000NN.gdbtable/.gdbtablx/.spx/.atx/.gdbindexes/.freelist/.horizon`, plus `gdb`, `timestamps`), 5,067,922,143 bytes, dated 2022-06-08 to 2023-04-12. Full per-file list with MD5: [listings/members_hydrofabric_v3.0.json](listings/members_hydrofabric_v3.0.json).

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

| Folder | Files | Bytes (exact, HEAD) | Files without exact size |
|---|---:|---:|---:|
| `doc/` | 23 | 1,922,502 | 0 |
| `ecf.20260518/` | 177 | 268,596 | 0 |
| `ecf.20260520/` | 177 | 269,076 | 0 |
| `ecf/` | 183 | 278,246 | 0 |
| `ecflow/` | 26 | 96,802 | 0 |
| `jobs/` | 28 | 91,005 | 0 |
| `modulefiles/` | 4 | 4,389 | 0 |
| `notUsedOps/` | 17 | 30,974 | 0 |
| `parm/ak_analysis_assim` | 2 | 14,102 | 0 |
| `parm/ak_analysis_assim_extended` | 2 | 14,104 | 0 |
| `parm/ak_medium_range` | 2 | 14,115 | 0 |
| `parm/ak_short_range` | 2 | 14,112 | 0 |
| `parm/analysis_assim` | 2 | 14,513 | 0 |
| `parm/analysis_assim_alaska_no_da` | 2 | 14,096 | 0 |
| `parm/analysis_assim_extend_alaska_no_da` | 2 | 14,098 | 0 |
| `parm/analysis_assim_extend_no_da` | 2 | 14,419 | 0 |
| `parm/analysis_assim_extended` | 2 | 14,524 | 0 |
| `parm/analysis_assim_hawaii_no_da` | 2 | 12,754 | 0 |
| `parm/analysis_assim_long_no_da` | 2 | 13,069 | 0 |
| `parm/analysis_assim_longrange` | 2 | 13,174 | 0 |
| `parm/analysis_assim_no_da` | 2 | 14,510 | 0 |
| `parm/analysis_assim_puertorico_no_da` | 2 | 12,779 | 0 |
| `parm/coastal` | 104 | 22,333,929,988 | 0 |
| `parm/constants` | 5 | 56,172 | 0 |
| `parm/constants_alaska` | 5 | 56,175 | 0 |
| `parm/domain` | 22 | 40,048,621,329 | 0 |
| `parm/domain_alaska` | 12 | 767,943,543 | 0 |
| `parm/domain_hawaii` | 10 | 1,268,082,639 | 0 |
| `parm/domain_puertorico` | 10 | 234,299,090 | 0 |
| `parm/forcingConfigs` | 19 | 277,230 | 0 |
| `parm/forcingParam` | 20,577 | 17,097,135,478 | 20,145 |
| `parm/hi_analysis_assim` | 2 | 12,759 | 0 |
| `parm/hi_short_range` | 2 | 12,767 | 0 |
| `parm/long_range` | 2 | 12,907 | 0 |
| `parm/manualclimateRestart` | 1,536 | 0 | 1,536 |
| `parm/medium_range` | 2 | 14,539 | 0 |
| `parm/medium_range_alaska_no_da` | 2 | 14,108 | 0 |
| `parm/medium_range_no_da` | 2 | 14,435 | 0 |
| `parm/mpe` | 6 | 6,408,435,615 | 0 |
| `parm/post_processing` | 37 | 4,999,515,073 | 0 |
| `parm/pr_analysis_assim` | 2 | 12,782 | 0 |
| `parm/pr_short_range` | 2 | 12,790 | 0 |
| `parm/short_range` | 2 | 14,535 | 0 |
| `parm/short_range_hawaii_no_da` | 2 | 12,762 | 0 |
| `parm/short_range_puertorico_no_da` | 2 | 12,786 | 0 |
| `parm/transfer` | 30 | 60,978 | 0 |
| `scripts/` | 27 | 311,308 | 0 |
| `sorc/` | 1 | 1,961 | 0 |
| `sorc/combine_hotstart7` | 3 | 2,172 | 0 |
| `sorc/combine_sink_source` | 3 | 1,459 | 0 |
| `sorc/metis_prep` | 3 | 1,534 | 0 |
| `sorc/nwm_wrfhydro` | 771 | 14,821,549 | 1 |
| `sorc/schism` | 2,568 | 539,390,380 | 6 |
| `ush/WrfHydroForcing` | 107 | 1,840,740 | 1 |
| `ush/ace_download` | 43 | 631,803 | 3 |
| `ush/batch` | 26 | 108,354 | 0 |
| `ush/canada_download` | 11 | 101,544 | 0 |
| `ush/cfs2hydroa` | 7 | 95,874 | 0 |
| `ush/combine` | 14 | 74,306 | 0 |
| `ush/down` | 24 | 145,567 | 0 |
| `ush/gfs2hydro1km` | 17 | 226,683 | 0 |
| `ush/grib2netcdf` | 34 | 14,473,914 | 0 |
| `ush/hrrr2hydro1km` | 5 | 38,778 | 0 |
| `ush/hydro_model` | 22 | 175,257 | 0 |
| `ush/merge_timeslices` | 4 | 8,854 | 1 |
| `ush/mountain_mapper_gfs` | 1 | 10,666 | 0 |
| `ush/mpe_refine` | 15 | 202,377 | 0 |
| `ush/nam2hydro` | 7 | 67,499 | 0 |
| `ush/nc2shef` | 14 | 208,480,711 | 0 |
| `ush/nwm-post-processing` | 233 | 1,839,564 | 0 |
| `ush/production_switch` | 12 | 20,860 | 0 |
| `ush/radar2hydro1km` | 5 | 23,633 | 0 |
| `ush/rap2hydro` | 9 | 73,662 | 0 |
| `ush/reforecast` | 7 | 29,900 | 0 |
| `ush/resume_forecast` | 17 | 145,234 | 0 |
| `ush/rfc_ingestion` | 56 | 9,127,945 | 0 |
| `ush/scale` | 1 | 2,276 | 0 |
| `ush/thinning_and_compression` | 7 | 82,758 | 0 |
| `ush/usgs_download` | 39 | 442,164 | 0 |
| `ush/utils` | 47 | 80,901 | 0 |
| `ush/wrf_hydro_workflow_dev` | 81 | 671,798,097 | 1 |
| `versions/` | 2 | 3,716 | 0 |

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


#### `parm/ak_analysis_assim/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,633 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,469 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/ak_analysis_assim_extended/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,634 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,470 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/ak_medium_range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,640 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,475 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/ak_short_range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,640 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,472 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,759 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,754 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_alaska_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,627 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,469 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_extend_alaska_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,628 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,470 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_extend_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,664 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,755 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_extended/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,769 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,755 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_hawaii_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,287 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,467 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_long_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,313 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,756 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_longrange/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,418 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,756 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,756 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,754 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/analysis_assim_puertorico_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,306 | 02 Nov 2026 16:22 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,473 | 02 Nov 2026 16:22 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/coastal/Tides/TidalConst/` (8 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [k1.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__k1.nc.cdl) | 132,879,586 | 02 Nov 2026 16:22 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |
| [k2.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__k2.nc.cdl) | 132,879,586 | 02 Nov 2026 16:22 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |
| [m2.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__m2.nc.cdl) | 132,879,586 | 02 Nov 2026 16:22 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |
| [n2.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__n2.nc.cdl) | 132,879,586 | 02 Nov 2026 16:22 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |
| [o1.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__o1.nc.cdl) | 132,879,586 | 02 Nov 2026 16:22 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |
| [p1.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__p1.nc.cdl) | 132,879,586 | 02 Nov 2026 16:22 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |
| [q1.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__q1.nc.cdl) | 132,879,586 | 02 Nov 2026 16:22 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |
| [s2.nc](headers/ncep_v3.1.7/parm__coastal__Tides__TidalConst__s2.nc.cdl) | 132,879,586 | 02 Nov 2026 16:23 | lat=2881, lon=5760, nv=2 | — | [coastal](#desc-coastal) |

#### `parm/coastal/atlgulf/` (21 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `2m_sink_elements.txt` | 107,066,328 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `bctides.in` | 71 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `correctMeshfile.sh` | 250 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `element_areas.txt` | 164,656,091 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `elev.ic` | 1,186,861,209 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `elevation_correction.csv` | 938,281 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__atlgulf__hgrid-prev.nc.cdl) | 776,682,334 | 02 Nov 2026 16:23 | nodeCount=10537609, elementCount=20967960, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.cpp` | 1,297,667,657 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.gr3` | 1,241,201,443 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.ll` | 1,241,201,443 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [hgrid.nc](headers/ncep_v3.1.7/parm__coastal__atlgulf__hgrid.nc.cdl) | 776,687,064 | 02 Nov 2026 16:23 | elementCount=20967960, maxNodePElement=3, nodeCount=10537609, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [hgrid.ncOldESMFversion](headers/ncep_v3.1.7/parm__coastal__atlgulf__hgrid.ncOldESMFversion.cdl) | 776,682,334 | 02 Nov 2026 16:23 | nodeCount=10537609, elementCount=20967960, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.utm` | 1,060,814,755 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.vtk` | 1,406,890,042 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `manning.gr3` | 1,098,881,790 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `nwmReaches.csv` | 106,799 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [open_bnds_hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__atlgulf__open_bnds_hgrid-prev.nc.cdl) | 999,841 | 02 Nov 2026 16:23 | nodeCount=21096, openBndNodeCount=9211, elementCount=21094, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.nc](headers/ncep_v3.1.7/parm__coastal__atlgulf__open_bnds_hgrid.nc.cdl) | 1,002,504 | 02 Nov 2026 16:23 | elementCount=21094, maxNodePElement=3, nodeCount=21096, openBndNodeCount=9211, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `param.nml` | 49,518 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `vgrid.in` | 172 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `windrot_geo2proj.gr3` | 1,085,234,838 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |

#### `parm/coastal/atlgulf/sflux/` (1 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `sflux_inputs.txt` | 16 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |

#### `parm/coastal/hawaii/` (21 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `2m_sink_elements.txt` | 8,189,324 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `bctides.in` | 82 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `correctMeshfile.sh` | 250 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `element_areas.txt` | 13,426,191 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `elev.ic` | 84,855,138 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__hawaii__hgrid-prev.nc.cdl) | 63,464,378 | 02 Nov 2026 16:23 | nodeCount=878770, elementCount=1703252, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.cpp` | 99,729,099 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.gr3` | 86,109,350 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.ll` | 86,109,350 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [hgrid.nc](headers/ncep_v3.1.7/parm__coastal__hawaii__hgrid.nc.cdl) | 63,469,120 | 02 Nov 2026 16:23 | elementCount=1703252, maxNodePElement=3, nodeCount=878770, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [hgrid.ncOldESMFversion](headers/ncep_v3.1.7/parm__coastal__hawaii__hgrid.ncOldESMFversion.cdl) | 63,464,378 | 02 Nov 2026 16:23 | nodeCount=878770, elementCount=1703252, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.utm` | 39,114,789 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.vtk` | 48,836,839 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `manning.gr3` | 81,876,381 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `nwmReaches.csv` | 15,251 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [open_bnds_hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__hawaii__open_bnds_hgrid-prev.nc.cdl) | 422,410 | 02 Nov 2026 16:23 | nodeCount=8695, openBndNodeCount=4350, elementCount=8695, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.nc](headers/ncep_v3.1.7/parm__coastal__hawaii__open_bnds_hgrid.nc.cdl) | 425,073 | 02 Nov 2026 16:23 | elementCount=8695, maxNodePElement=3, nodeCount=8695, openBndNodeCount=4350, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.ncOldESMFversion](headers/ncep_v3.1.7/parm__coastal__hawaii__open_bnds_hgrid.ncOldESMFversion.cdl) | 422,410 | 02 Nov 2026 16:23 | nodeCount=8695, openBndNodeCount=4350, elementCount=8695, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `param.nml` | 49,519 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `vgrid.in` | 172 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `windrot_geo2proj.gr3` | 80,636,157 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |

#### `parm/coastal/hawaii/sflux/` (1 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `sflux_inputs.txt` | 16 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |

#### `parm/coastal/maskFiles/` (4 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [Ocean_Land_Mask_5m_Pacific_Coast_V2.nc](headers/ncep_v3.1.7/parm__coastal__maskFiles__Ocean_Land_Mask_5m_Pacific_Coast_V2.nc.cdl) | 100,432,048 | 02 Nov 2026 16:23 | index=3138490 | — | [coastal](#desc-coastal) |
| [Ocean_Land_Mask_AtlanticGulf_5m.nc](headers/ncep_v3.1.7/parm__coastal__maskFiles__Ocean_Land_Mask_AtlanticGulf_5m.nc.cdl) | 505,812,812 | 02 Nov 2026 16:23 | index=10537609 | — | [coastal](#desc-coastal) |
| [Ocean_Land_Mask_Hawaii_5m.nc](headers/ncep_v3.1.7/parm__coastal__maskFiles__Ocean_Land_Mask_Hawaii_5m.nc.cdl) | 28,121,008 | 02 Nov 2026 16:23 | index=878770 | — | [coastal](#desc-coastal) |
| [Ocean_Land_Mask_PR_USVI_5m.nc](headers/ncep_v3.1.7/parm__coastal__maskFiles__Ocean_Land_Mask_PR_USVI_5m.nc.cdl) | 118,580,912 | 02 Nov 2026 16:23 | index=3705642 | — | [coastal](#desc-coastal) |

#### `parm/coastal/pacific/` (25 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `2m_sink_elements.txt` | 27,033,739 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `bctides.in` | 72 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `correctMeshfile.sh` | 250 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `element_areas.txt` | 47,622,735 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `elev.ic` | 340,818,673 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `elevation_correction.csv` | 2,506,640 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__pacific__hgrid-prev.nc.cdl) | 225,697,079 | 02 Nov 2026 16:23 | nodeCount=3138490, elementCount=6050741, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.cpp` | 370,454,132 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.gr3` | 346,251,903 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.ll` | 346,251,903 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [hgrid.nc](headers/ncep_v3.1.7/parm__coastal__pacific__hgrid.nc.cdl) | 225,701,857 | 02 Nov 2026 16:23 | elementCount=6050741, maxNodePElement=3, nodeCount=3138490, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [hgrid.ncNewESMFversion](headers/ncep_v3.1.7/parm__coastal__pacific__hgrid.ncNewESMFversion.cdl) | 225,701,857 | 02 Nov 2026 16:23 | elementCount=6050741, maxNodePElement=3, nodeCount=3138490, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [hgrid.ncOldESMFversion](headers/ncep_v3.1.7/parm__coastal__pacific__hgrid.ncOldESMFversion.cdl) | 225,697,079 | 02 Nov 2026 16:23 | nodeCount=3138490, elementCount=6050741, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.utm` | 381,095,165 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `hgrid.vtk` | 492,442,828 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `manning.gr3` | 333,673,353 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `nwmReaches.csv` | 74,848 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| [open_bnds_hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__pacific__open_bnds_hgrid-prev.nc.cdl) | 2,201,562 | 02 Nov 2026 16:23 | nodeCount=46507, openBndNodeCount=23753, elementCount=46507, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.nc](headers/ncep_v3.1.7/parm__coastal__pacific__open_bnds_hgrid.nc.cdl) | 2,204,225 | 02 Nov 2026 16:23 | elementCount=46507, maxNodePElement=3, nodeCount=46507, openBndNodeCount=23753, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.ncNewESMFversion](headers/ncep_v3.1.7/parm__coastal__pacific__open_bnds_hgrid.ncNewESMFversion.cdl) | 2,204,225 | 02 Nov 2026 16:23 | elementCount=46507, maxNodePElement=3, nodeCount=46507, openBndNodeCount=23753, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.ncOldESMFversion](headers/ncep_v3.1.7/parm__coastal__pacific__open_bnds_hgrid.ncOldESMFversion.cdl) | 2,201,562 | 02 Nov 2026 16:23 | nodeCount=46507, openBndNodeCount=23753, elementCount=46507, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `param.nml` | 49,519 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `param.nmlORIG` | 49,519 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `vgrid.in` | 172 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `windrot_geo2proj.gr3` | 328,965,912 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |

#### `parm/coastal/pacific/sflux/` (1 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `sflux_inputs.txt` | 16 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |

#### `parm/coastal/prvi/` (21 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `2m_sink_elements.txt` | 27,876,667 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `bctides.in` | 83 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `correctMeshfile.sh` | 250 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `element_areas.txt` | 58,123,395 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |
| `elev.ic` | 384,843,729 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| [hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__prvi__hgrid-prev.nc.cdl) | 273,082,222 | 02 Nov 2026 16:24 | nodeCount=3705642, elementCount=7371800, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.cpp` | 446,212,653 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| `hgrid.gr3` | 391,844,826 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| `hgrid.ll` | 391,844,826 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| [hgrid.nc](headers/ncep_v3.1.7/parm__coastal__prvi__hgrid.nc.cdl) | 273,086,952 | 02 Nov 2026 16:24 | elementCount=7371800, maxNodePElement=3, nodeCount=3705642, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [hgrid.ncOldESMFversion](headers/ncep_v3.1.7/parm__coastal__prvi__hgrid.ncOldESMFversion.cdl) | 273,082,222 | 02 Nov 2026 16:24 | nodeCount=3705642, elementCount=7371800, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `hgrid.utm` | 112,977,344 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| `hgrid.vtk` | 163,058,989 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| `manning.gr3` | 376,216,253 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| `nwmReaches.csv` | 15,821 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| [open_bnds_hgrid-prev.nc](headers/ncep_v3.1.7/parm__coastal__prvi__open_bnds_hgrid-prev.nc.cdl) | 606,286 | 02 Nov 2026 16:24 | nodeCount=12783, openBndNodeCount=4329, elementCount=12783, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.nc](headers/ncep_v3.1.7/parm__coastal__prvi__open_bnds_hgrid.nc.cdl) | 608,949 | 02 Nov 2026 16:24 | elementCount=12783, maxNodePElement=3, nodeCount=12783, openBndNodeCount=4329, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| [open_bnds_hgrid.ncOldESMFversion](headers/ncep_v3.1.7/parm__coastal__prvi__open_bnds_hgrid.ncOldESMFversion.cdl) | 606,286 | 02 Nov 2026 16:24 | nodeCount=12783, openBndNodeCount=4329, elementCount=12783, maxNodePElement=3, coordDim=2 | 0.9 | [coastal](#desc-coastal) |
| `param.nml` | 49,519 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| `vgrid.in` | 172 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |
| `windrot_geo2proj.gr3` | 370,667,778 | 02 Nov 2026 16:24 |  |  | [coastal](#desc-coastal) |

#### `parm/coastal/prvi/sflux/` (1 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `sflux_inputs.txt` | 16 | 02 Nov 2026 16:23 |  |  | [coastal](#desc-coastal) |

#### `parm/constants/` (5 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `CHANPARM.TBL` | 471 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `GENPARM.TBL` | 261 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `HYDRO.TBL` | 2,199 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `MPTABLE.TBL` | 47,966 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `SOILPARM.TBL` | 5,275 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |

#### `parm/constants_alaska/` (5 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `CHANPARM.TBL` | 471 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `GENPARM.TBL` | 261 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `HYDRO.TBL` | 2,199 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `MPTABLE.TBL` | 47,969 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |
| `SOILPARM.TBL` | 5,275 | 02 Nov 2026 16:24 |  |  | [constants](#desc-tbl) |

#### `parm/domain/` (22 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [Diversion_CONUS.nc](headers/ncep_v3.1.7/parm__domain__Diversion_CONUS.nc.cdl) | 16,062 | 02 Nov 2026 16:24 | diversion=1, string15=15 | NWM v3.1 | [Diversion](#desc-diversion) |
| [Fulldom_CONUS_FullRouting.nc](headers/ncep_v3.1.7/parm__domain__Fulldom_CONUS_FullRouting.nc.cdl) | 12,460,271,263 | 02 Nov 2026 16:24 | y=15360, x=18432, string1=1 | NWM v3.1 | [Fulldom](#desc-fulldom) |
| [Fulldom_CONUS_LongRange.nc](headers/ncep_v3.1.7/parm__domain__Fulldom_CONUS_LongRange.nc.cdl) | 760,987,866 | 02 Nov 2026 16:24 | y=3840, x=4608 | NWM v3.1 | [Fulldom](#desc-fulldom) |
| [GEOGRID_LDASOUT_Spatial_Metadata_CONUS.nc](headers/ncep_v3.1.7/parm__domain__GEOGRID_LDASOUT_Spatial_Metadata_CONUS.nc.cdl) | 70,420 | 02 Nov 2026 16:24 | y=3840, x=4608 | NWM v3.1 | [GEOGRID_LDASOUT](#desc-geogrid-ldasout) |
| [GWBUCKPARM_CONUS_FullRouting.nc](headers/ncep_v3.1.7/parm__domain__GWBUCKPARM_CONUS_FullRouting.nc.cdl) | 87,206,818 | 02 Nov 2026 16:24 | BasinDim=2724837 | NWM v3.1 | [GWBUCKPARM](#desc-gwbuckparm) |
| [GWBUCKPARM_CONUS_LongRange.nc](headers/ncep_v3.1.7/parm__domain__GWBUCKPARM_CONUS_LongRange.nc.cdl) | 87,206,816 | 02 Nov 2026 16:24 | BasinDim=2724837 | NWM v3.1 | [GWBUCKPARM](#desc-gwbuckparm) |
| [RouteLink_CONUS.nc](headers/ncep_v3.1.7/parm__domain__RouteLink_CONUS.nc.cdl) | 269,369,766 | 02 Nov 2026 16:24 | feature_id=2776734, IDLength=15 | — | [RouteLink](#desc-routelink) |
| [RouteLink_CONUS.nc_TxDOTstream](headers/ncep_v3.1.7/parm__domain__RouteLink_CONUS.nc_TxDOTstream.cdl) | 269,363,375 | 02 Nov 2026 16:24 | feature_id=2776734, IDLength=15 | — | [RouteLink](#desc-routelink) |
| [RouteLink_CONUS.nc_turnoffTxDOTstream](headers/ncep_v3.1.7/parm__domain__RouteLink_CONUS.nc_turnoffTxDOTstream.cdl) | 269,363,375 | 02 Nov 2026 16:24 | feature_id=2776734, IDLength=15 | — | [RouteLink](#desc-routelink) |
| [geo_em_CONUS.nc](headers/ncep_v3.1.7/parm__domain__geo_em_CONUS.nc.cdl) | 9,555,402,732 | 02 Nov 2026 16:25 | Time=UNLIMITED(1), south_north=3840, west_east=4608, month=12, land_cat=24, west_east_stag=4609, south_north_stag=3841, soil_cat=16, DateStrLen=19 | NWM v3.1 | [geo_em](#desc-geo-em) |
| [hydro2dtbl_CONUS_FullRouting.nc](headers/ncep_v3.1.7/parm__domain__hydro2dtbl_CONUS_FullRouting.nc.cdl) | 424,730,323 | 02 Nov 2026 16:25 | south_north=3840, west_east=4608 | NWM v3.1 | [hydro2dtbl](#desc-hydro2dtbl) |
| [hydro2dtbl_CONUS_LongRange.nc](headers/ncep_v3.1.7/parm__domain__hydro2dtbl_CONUS_LongRange.nc.cdl) | 424,730,323 | 02 Nov 2026 16:25 | south_north=3840, west_east=4608 | NWM v3.1 | [hydro2dtbl](#desc-hydro2dtbl) |
| [nudgingParams_CONUS.nc](headers/ncep_v3.1.7/parm__domain__nudgingParams_CONUS.nc.cdl) | 2,923,384 | 02 Nov 2026 16:25 | stationIdStrLen=15, stationIdInd=UNLIMITED(8739), threshInd=1, monthInd=12, threshCatInd=2 | — | [nudgingParams](#desc-nudgingparams) |
| [reservoir_index_AnA.nc](headers/ncep_v3.1.7/parm__domain__reservoir_index_AnA.nc.cdl) | 114,296 | 02 Nov 2026 16:25 | feature_id=5782, USGS_COMID=76, usgs_gage_id_len=15, number_of_lags=12, USACE_COMID=70, usace_gage_id_len=15, RFC_COMID=397, rfc_gage_id_len=5 | — | [reservoir_index](#desc-reservoir-index) |
| [reservoir_index_Extended_AnA.nc](headers/ncep_v3.1.7/parm__domain__reservoir_index_Extended_AnA.nc.cdl) | 114,296 | 02 Nov 2026 16:25 | feature_id=5782, USGS_COMID=76, usgs_gage_id_len=15, number_of_lags=12, USACE_COMID=70, usace_gage_id_len=15, RFC_COMID=397, rfc_gage_id_len=5 | — | [reservoir_index](#desc-reservoir-index) |
| [reservoir_index_Medium_Range.nc](headers/ncep_v3.1.7/parm__domain__reservoir_index_Medium_Range.nc.cdl) | 107,600 | 02 Nov 2026 16:25 | feature_id=5782, USGS_COMID=47, usgs_gage_id_len=15, number_of_lags=12, USACE_COMID=52, usace_gage_id_len=15, RFC_COMID=389, rfc_gage_id_len=5 | — | [reservoir_index](#desc-reservoir-index) |
| [reservoir_index_Short_Range.nc](headers/ncep_v3.1.7/parm__domain__reservoir_index_Short_Range.nc.cdl) | 114,296 | 02 Nov 2026 16:25 | feature_id=5782, USGS_COMID=76, usgs_gage_id_len=15, number_of_lags=12, USACE_COMID=70, usace_gage_id_len=15, RFC_COMID=397, rfc_gage_id_len=5 | — | [reservoir_index](#desc-reservoir-index) |
| [soilproperties_CONUS_FullRouting.nc](headers/ncep_v3.1.7/parm__domain__soilproperties_CONUS_FullRouting.nc.cdl) | 3,965,368,300 | 02 Nov 2026 16:25 | Time=UNLIMITED(1), south_north=3840, west_east=4608, soil_layers_stag=4 | NWM v3.1 | [soilproperties](#desc-soilproperties) |
| [soilproperties_CONUS_LongRange.nc](headers/ncep_v3.1.7/parm__domain__soilproperties_CONUS_LongRange.nc.cdl) | 3,965,368,300 | 02 Nov 2026 16:25 | Time=UNLIMITED(1), south_north=3840, west_east=4608, soil_layers_stag=4 | NWM v3.1 | [soilproperties](#desc-soilproperties) |
| [spatialweights_CONUS_FullRouting.nc](headers/ncep_v3.1.7/parm__domain__spatialweights_CONUS_FullRouting.nc.cdl) | 4,962,512,130 | 02 Nov 2026 16:25 | polyid=2724837, data=176453744 | NWM v3.1 | [spatialweights](#desc-spatialweights) |
| [spatialweights_CONUS_LongRange.nc](headers/ncep_v3.1.7/parm__domain__spatialweights_CONUS_LongRange.nc.cdl) | 639,711,046 | 02 Nov 2026 16:25 | polyid=2724837, data=22067991 | NWM v3.1 | [spatialweights](#desc-spatialweights) |
| [wrfinput_CONUS.nc](headers/ncep_v3.1.7/parm__domain__wrfinput_CONUS.nc.cdl) | 1,903,568,542 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=3840, west_east=4608, soil_layers_stag=4 | NWM v3.1 | [wrfinput](#desc-wrfinput) |

#### `parm/domain_alaska/` (12 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [Fulldom_AK_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_alaska__Fulldom_AK_FullRouting.nc.cdl) | 329,305,930 | 02 Nov 2026 16:26 | y=1836, x=3516, string1=1 | NWM v3.1 | [Fulldom](#desc-fulldom) |
| [GEOGRID_LDASOUT_Spatial_Metadata_AK.nc](headers/ncep_v3.1.7/parm__domain_alaska__GEOGRID_LDASOUT_Spatial_Metadata_AK.nc.cdl) | 30,298 | 02 Nov 2026 16:26 | y=459, x=879, string1=1 | NWM v3.1 | [GEOGRID_LDASOUT](#desc-geogrid-ldasout) |
| [GWBUCKPARM_AK_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_alaska__GWBUCKPARM_AK_FullRouting.nc.cdl) | 14,073,141 | 02 Nov 2026 16:26 | BasinDim=390548 | NWM v3.1 | [GWBUCKPARM](#desc-gwbuckparm) |
| [LAKEPARM_AK.nc](headers/ncep_v3.1.7/parm__domain_alaska__LAKEPARM_AK.nc.cdl) | 45,788 | 02 Nov 2026 16:26 | feature_id=237 | NWM v3.1 | [LAKEPARM](#desc-lakeparm) |
| [RouteLink_AK.nc](headers/ncep_v3.1.7/parm__domain_alaska__RouteLink_AK.nc.cdl) | 47,399,233 | 02 Nov 2026 16:26 | feature_id=391528, IDLength=15 | NWM v3.1 | [RouteLink](#desc-routelink) |
| [geo_em_AK.nc](headers/ncep_v3.1.7/parm__domain_alaska__geo_em_AK.nc.cdl) | 62,057,809 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=459, west_east=879, DateStrLen=19, south_north_stag=460, west_east_stag=880, land_cat=95, soil_cat=16, month=12, polar_stereographic=1 | NWM v3.1 | [geo_em](#desc-geo-em) |
| [hydro2dtbl_AK_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_alaska__hydro2dtbl_AK_FullRouting.nc.cdl) | 9,711,438 | 02 Nov 2026 16:26 | south_north=459, west_east=879 | NWM v3.1 | [hydro2dtbl](#desc-hydro2dtbl) |
| [nudgingParams_AK.nc](headers/ncep_v3.1.7/parm__domain_alaska__nudgingParams_AK.nc.cdl) | 68,158 | 02 Nov 2026 16:26 | stationIdStrLen=15, stationIdInd=UNLIMITED(65), threshInd=1, monthInd=12, threshCatInd=2 | NWM v3.1 | [nudgingParams](#desc-nudgingparams) |
| [reservoir_index_GDL_AK.nc](headers/ncep_v3.1.7/parm__domain_alaska__reservoir_index_GDL_AK.nc.cdl) | 15,090 | 02 Nov 2026 16:26 | feature_id=237, RFC_COMID=6, rfc_gage_id_len=5 | NWM v3.1 | [reservoir_index](#desc-reservoir-index) |
| [soilproperties_AK_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_alaska__soilproperties_AK_FullRouting.nc.cdl) | 85,858,516 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=459, west_east=879, soil_layers_stag=4 | NWM v3.1 | [soilproperties](#desc-soilproperties) |
| [spatialweights_AK_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_alaska__spatialweights_AK_FullRouting.nc.cdl) | 186,703,565 | 02 Nov 2026 16:26 | polyid=390548, data=5687748 | NWM v3.1 | [spatialweights](#desc-spatialweights) |
| [wrfinput_AK.nc](headers/ncep_v3.1.7/parm__domain_alaska__wrfinput_AK.nc.cdl) | 32,674,577 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=459, west_east=879, soil_layers_stag=4, polar_stereographic=1 | NWM v3.1 | [wrfinput](#desc-wrfinput) |

#### `parm/domain_hawaii/` (10 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [Fulldom_HI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_hawaii__Fulldom_HI_FullRouting.nc.cdl) | 828,475,389 | 02 Nov 2026 16:26 | y=3900, x=5900 | NWM v3.1 | [Fulldom](#desc-fulldom) |
| [GEOGRID_LDASOUT_Spatial_Metadata_HI.nc](headers/ncep_v3.1.7/parm__domain_hawaii__GEOGRID_LDASOUT_Spatial_Metadata_HI.nc.cdl) | 10,688 | 02 Nov 2026 16:26 | y=390, x=590 | NWM v3.1 | [GEOGRID_LDASOUT](#desc-geogrid-ldasout) |
| [GWBUCKPARM_HI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_hawaii__GWBUCKPARM_HI_FullRouting.nc.cdl) | 435,500 | 02 Nov 2026 16:26 | BasinDim=13296 | NWM v3.1 | [GWBUCKPARM](#desc-gwbuckparm) |
| [RouteLink_HI.nc](headers/ncep_v3.1.7/parm__domain_hawaii__RouteLink_HI.nc.cdl) | 1,346,576 | 02 Nov 2026 16:26 | feature_id=13637, IDLength=15 | NWM v3.1 | [RouteLink](#desc-routelink) |
| [geo_em_HI.nc](headers/ncep_v3.1.7/parm__domain_hawaii__geo_em_HI.nc.cdl) | 320,889,324 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=390, west_east=590, string19=19, south_north_stag=391, west_east_stag=591, land_cat=24, soil_cat=16, month=12, num_urb_params=132, soilcomp=8 | NWM v3.1 | [geo_em](#desc-geo-em) |
| [hydro2dtbl_HI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_hawaii__hydro2dtbl_HI_FullRouting.nc.cdl) | 5,545,543 | 02 Nov 2026 16:26 | south_north=390, west_east=590 | NWM v3.1 | [hydro2dtbl](#desc-hydro2dtbl) |
| [nudgingParams_HI.nc](headers/ncep_v3.1.7/parm__domain_hawaii__nudgingParams_HI.nc.cdl) | 49,188 | 02 Nov 2026 16:26 | stationIdStrLen=15, stationIdInd=UNLIMITED(58), threshInd=1, monthInd=12, threshCatInd=2 | NWM v3.1 | [nudgingParams](#desc-nudgingparams) |
| [soilproperties_HI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_hawaii__soilproperties_HI_FullRouting.nc.cdl) | 48,909,557 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=390, west_east=590, soil_layers_stag=4 | NWM v3.1 | [soilproperties](#desc-soilproperties) |
| [spatialweights_HI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_hawaii__spatialweights_HI_FullRouting.nc.cdl) | 40,222,955 | 02 Nov 2026 16:26 | polyid=13296, data=1432428 | NWM v3.1 | [spatialweights](#desc-spatialweights) |
| [wrfinput_HI.nc](headers/ncep_v3.1.7/parm__domain_hawaii__wrfinput_HI.nc.cdl) | 22,197,919 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=390, west_east=590, soil_layers_stag=4 | NWM v3.1 | [wrfinput](#desc-wrfinput) |

#### `parm/domain_puertorico/` (10 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [Fulldom_PRVI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_puertorico__Fulldom_PRVI_FullRouting.nc.cdl) | 181,574,634 | 02 Nov 2026 16:26 | y=1100, x=3000 | NWM v3.1 | [Fulldom](#desc-fulldom) |
| [GEOGRID_LDASOUT_Spatial_Metadata_PRVI.nc](headers/ncep_v3.1.7/parm__domain_puertorico__GEOGRID_LDASOUT_Spatial_Metadata_PRVI.nc.cdl) | 13,022 | 02 Nov 2026 16:26 | y=110, x=300 | NWM v3.1 | [GEOGRID_LDASOUT](#desc-geogrid-ldasout) |
| [GWBUCKPARM_PRVI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_puertorico__GWBUCKPARM_PRVI_FullRouting.nc.cdl) | 449,672 | 02 Nov 2026 16:26 | BasinDim=13692 | NWM v3.1 | [GWBUCKPARM](#desc-gwbuckparm) |
| [RouteLink_PRVI.nc](headers/ncep_v3.1.7/parm__domain_puertorico__RouteLink_PRVI.nc.cdl) | 1,380,709 | 02 Nov 2026 16:26 | feature_id=14017, IDLength=15 | NWM v3.1 | [RouteLink](#desc-routelink) |
| [geo_em_PRVI.nc](headers/ncep_v3.1.7/parm__domain_puertorico__geo_em_PRVI.nc.cdl) | 3,521,915 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), month=12, south_north=110, west_east=300, west_east_stag=301, south_north_stag=111, land_cat=25, soil_cat=16, soilcomp=8, DateStrLen=19 | NWM v3.1 | [geo_em](#desc-geo-em) |
| [hydro2dtbl_PRVI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_puertorico__hydro2dtbl_PRVI_FullRouting.nc.cdl) | 815,078 | 02 Nov 2026 16:26 | south_north=110, west_east=300 | NWM v3.1 | [hydro2dtbl](#desc-hydro2dtbl) |
| [nudgingParams_PRVI.nc](headers/ncep_v3.1.7/parm__domain_puertorico__nudgingParams_PRVI.nc.cdl) | 71,038 | 02 Nov 2026 16:26 | stationIdStrLen=15, stationIdInd=UNLIMITED(83), threshInd=1, monthInd=12, threshCatInd=2 | NWM v3.1 | [nudgingParams](#desc-nudgingparams) |
| [soilproperties_PRVI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_puertorico__soilproperties_PRVI_FullRouting.nc.cdl) | 7,277,535 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=110, west_east=300, soil_layers_stag=4 | NWM v3.1 | [soilproperties](#desc-soilproperties) |
| [spatialweights_PRVI_FullRouting.nc](headers/ncep_v3.1.7/parm__domain_puertorico__spatialweights_PRVI_FullRouting.nc.cdl) | 36,604,358 | 02 Nov 2026 16:26 | polyid=13692, data=1138467 | NWM v3.1 | [spatialweights](#desc-spatialweights) |
| [wrfinput_PRVI.nc](headers/ncep_v3.1.7/parm__domain_puertorico__wrfinput_PRVI.nc.cdl) | 2,591,129 | 02 Nov 2026 16:26 | Time=UNLIMITED(1), south_north=110, west_east=300, soil_layers_stag=4 | NWM v3.1 | [wrfinput](#desc-wrfinput) |

#### `parm/forcingConfigs/` (19 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `template_forcing_engine_Alaska_Analysis.config` | 14,938 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Alaska_ExtAnalysis.config` | 15,067 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Alaska_Medium.config` | 14,773 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Alaska_Medium_Blend.config` | 14,982 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Alaska_Short.config` | 14,641 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Analysis.config` | 15,128 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Hawaii_Analysis.config` | 14,359 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Hawaii_RRFS_Analysis.config` | 14,437 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Hawaii_RRFS_Short.config` | 14,411 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Hawaii_Short.config` | 14,480 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Long.config` | 14,473 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Medium_GFS-Blend.config` | 14,641 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Medium_GFS-NDFD.config` | 14,657 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Medium_GFS-Only.config` | 14,203 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_PuertoRico_Analysis.config` | 14,052 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_PuertoRico_RRFS_Analysis.config` | 14,420 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_PuertoRico_RRFS_Short.config` | 14,440 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_PuertoRico_Short.config` | 14,457 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |
| `template_forcing_engine_Short.config` | 14,671 | 02 Nov 2026 16:26 |  |  | [forcing config](#desc-forcingconfigs) |

#### `parm/forcingParam/AnA/` (25 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `MRMS_WGT_RQI0.9_m01_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m01_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m01_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m02_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m02_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m02_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m03_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m03_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m03_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m04_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m04_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m04_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m05_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m05_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m05_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m06_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m06_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m06_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m07_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m07_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m07_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m08_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m08_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m08_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m09_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m09_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m09_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m10_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m10_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m10_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m11_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m11_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m11_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| `MRMS_WGT_RQI0.9_m12_v1.1_geosmth.grb2` | 26,542,268 | 02 Nov 2026 16:26 |  |  |  |
| [MRMS_WGT_RQI0.9_m12_v1.1_geosmth.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__MRMS_WGT_RQI0.9_m12_v1.1_geosmth.nc.cdl) | 353,963,564 | 02 Nov 2026 16:26 | y=3840, x=4608, time=UNLIMITED(1) | — |  |
| [lapse_param.nc](headers/ncep_v3.1.7/parm__forcingParam__AnA__lapse_param.nc.cdl) | 70,779,120 | 02 Nov 2026 16:26 | ncl0=3840, ncl1=4608 | — |  |

#### `parm/forcingParam/ESMFWeightFiles/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [ESMF_weight_GFS_Production_GRIB2_b0.nc4](headers/ncep_v3.1.7/parm__forcingParam__ESMFWeightFiles__ESMF_weight_GFS_Production_GRIB2_b0.nc4.cdl) | 1,199,570,944 | 02 Nov 2026 16:26 | n_s=70778880 | — |  |
| [ESMF_weight_NDFD_b0.nc4](headers/ncep_v3.1.7/parm__forcingParam__ESMFWeightFiles__ESMF_weight_NDFD_b0.nc4.cdl) | 350,224,384 | 02 Nov 2026 16:26 | n_s=17694720 | — |  |

#### `parm/forcingParam/Long_Range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [lapse_param.nc](headers/ncep_v3.1.7/parm__forcingParam__Long_Range__lapse_param.nc.cdl) | 70,779,120 | 02 Nov 2026 16:48 | ncl0=3840, ncl1=4608 | — |  |
| `map_NLDAS_climo_to_CFSv2.py` | 5,354 | 02 Nov 2026 16:48 |  |  |  |

#### `parm/forcingParam/Long_Range/CFSv2_Climo/` (11713 files)

Listing only (exact sizes not requested for a directory this large). Name patterns: `cfs_dlwsfc_N_N_dist_params.nc` ×1464; `cfs_dswsfc_N_N_dist_params.nc` ×1464; `cfs_prate_N_N_dist_params.nc` ×1464; `cfs_pressfc_N_N_dist_params.nc` ×1464; `cfs_qNm_N_N_dist_params.nc` ×1464; `cfs_tmpNm_N_N_dist_params.nc` ×1464; `cfs_ugrd_N_N_dist_params.nc` ×1464; `cfs_vgrd_N_N_dist_params.nc` ×1464; `copy_N_to_N.csh` ×1. Listing dates 2026-11-02 16:26 to 2026-11-02 16:32; listing sizes 1.1M, 1.7M, 2.2K.

#### `parm/forcingParam/Long_Range/NLDAS_Climo/` (8785 files)

Listing only (exact sizes not requested for a directory this large). Name patterns: `nldasN_N_dist_params.nc` ×8784; `copy_N_to_N.csh` ×1. Listing dates 2026-11-02 16:32 to 2026-11-02 16:48; listing sizes 1.5K, 9.5M.

#### `parm/forcingParam/Medium_Range/` (49 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [PRISM_Precip_Clim_Apr_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Apr_GFS_to_NWM_Grid.nc.cdl) | 213,969,935 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Apr_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Apr_NWM_Grid.nc.cdl) | 214,373,263 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Apr_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Apr_NWM_Mtn_Mapper_Denom.nc.cdl) | 213,969,935 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Apr_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Apr_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,373,263 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Aug_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Aug_GFS_to_NWM_Grid.nc.cdl) | 213,923,262 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Aug_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Aug_NWM_Grid.nc.cdl) | 214,383,925 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Aug_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Aug_NWM_Mtn_Mapper_Denom.nc.cdl) | 213,923,262 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Aug_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Aug_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,383,925 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Dec_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Dec_GFS_to_NWM_Grid.nc.cdl) | 214,316,893 | 02 Nov 2026 16:48 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Dec_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Dec_NWM_Grid.nc.cdl) | 214,708,244 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Dec_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Dec_NWM_Mtn_Mapper_Denom.nc.cdl) | 214,316,893 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Dec_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Dec_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,708,244 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Feb_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Feb_GFS_to_NWM_Grid.nc.cdl) | 214,306,749 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Feb_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Feb_NWM_Grid.nc.cdl) | 214,692,160 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Feb_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Feb_NWM_Mtn_Mapper_Denom.nc.cdl) | 214,306,749 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Feb_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Feb_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,692,160 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jan_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jan_GFS_to_NWM_Grid.nc.cdl) | 214,330,822 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jan_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jan_NWM_Grid.nc.cdl) | 214,721,263 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jan_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jan_NWM_Mtn_Mapper_Denom.nc.cdl) | 214,330,822 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jan_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jan_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,721,263 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jul_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jul_GFS_to_NWM_Grid.nc.cdl) | 213,983,106 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jul_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jul_NWM_Grid.nc.cdl) | 214,422,619 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jul_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jul_NWM_Mtn_Mapper_Denom.nc.cdl) | 213,983,106 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jul_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jul_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,422,619 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jun_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jun_GFS_to_NWM_Grid.nc.cdl) | 213,854,712 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jun_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jun_NWM_Grid.nc.cdl) | 214,285,175 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jun_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jun_NWM_Mtn_Mapper_Denom.nc.cdl) | 213,854,712 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Jun_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Jun_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,285,175 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Mar_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Mar_GFS_to_NWM_Grid.nc.cdl) | 214,107,155 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Mar_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Mar_NWM_Grid.nc.cdl) | 214,505,026 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Mar_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Mar_NWM_Mtn_Mapper_Denom.nc.cdl) | 214,107,155 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Mar_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Mar_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,505,026 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_May_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_May_GFS_to_NWM_Grid.nc.cdl) | 213,796,320 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_May_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_May_NWM_Grid.nc.cdl) | 214,228,769 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_May_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_May_NWM_Mtn_Mapper_Denom.nc.cdl) | 213,796,320 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_May_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_May_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,228,769 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Nov_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Nov_GFS_to_NWM_Grid.nc.cdl) | 214,252,003 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Nov_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Nov_NWM_Grid.nc.cdl) | 214,643,755 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Nov_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Nov_NWM_Mtn_Mapper_Denom.nc.cdl) | 214,252,003 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Nov_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Nov_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,643,755 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Oct_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Oct_GFS_to_NWM_Grid.nc.cdl) | 213,967,329 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Oct_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Oct_NWM_Grid.nc.cdl) | 214,390,085 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Oct_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Oct_NWM_Mtn_Mapper_Denom.nc.cdl) | 213,967,329 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Oct_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Oct_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,390,085 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Sep_GFS_to_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Sep_GFS_to_NWM_Grid.nc.cdl) | 213,925,124 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Sep_NWM_Grid.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Sep_NWM_Grid.nc.cdl) | 214,372,748 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Sep_NWM_Mtn_Mapper_Denom.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Sep_NWM_Mtn_Mapper_Denom.nc.cdl) | 213,925,124 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [PRISM_Precip_Clim_Sep_NWM_Mtn_Mapper_Numer.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__PRISM_Precip_Clim_Sep_NWM_Mtn_Mapper_Numer.nc.cdl) | 214,372,748 | 02 Nov 2026 16:49 | x=4608, y=3840 | — |  |
| [lapse_param.nc](headers/ncep_v3.1.7/parm__forcingParam__Medium_Range__lapse_param.nc.cdl) | 70,779,120 | 02 Nov 2026 16:49 | ncl0=3840, ncl1=4608 | — |  |

#### `parm/forcingParam/Short_Range/` (1 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [lapse_param.nc](headers/ncep_v3.1.7/parm__forcingParam__Short_Range__lapse_param.nc.cdl) | 70,779,120 | 02 Nov 2026 16:49 | ncl0=3840, ncl1=4608 | — |  |

#### `parm/hi_analysis_assim/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,291 | 02 Nov 2026 16:49 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,468 | 02 Nov 2026 16:49 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/hi_short_range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,296 | 02 Nov 2026 16:49 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,471 | 02 Nov 2026 16:49 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/long_range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,424 | 02 Nov 2026 16:49 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,483 | 02 Nov 2026 16:49 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/manualclimateRestart/` (1536 files)

Listing only (exact sizes not requested for a directory this large). Name patterns: `HYDRO_RST.N-N-N_N:N_DOMAINN.N` ×768; `RESTART.N_DOMAINN.N` ×768. Listing dates 2026-11-02 16:49 to 2026-11-02 16:52; listing sizes 16M, 17M, 18M, 19M, 20M, 5.6M.

#### `parm/medium_range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,779 | 02 Nov 2026 16:52 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,760 | 02 Nov 2026 16:52 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/medium_range_alaska_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,633 | 02 Nov 2026 16:52 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,475 | 02 Nov 2026 16:52 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/medium_range_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,675 | 02 Nov 2026 16:52 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,760 | 02 Nov 2026 16:52 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/mpe/` (6 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [HRAP_to_NWM_regrid_weight_bilinear.nc](headers/ncep_v3.1.7/parm__mpe__HRAP_to_NWM_regrid_weight_bilinear.nc.cdl) | 2,878,075,269 | 02 Nov 2026 16:52 | n_a=987601, n_b=17694720, n_s=63114016, nv_a=4, nv_b=4, num_wgts=1, src_grid_rank=2, dst_grid_rank=2 | — |  |
| [HRRR_to_HRAP_regrid_weight_conserve.nc](headers/ncep_v3.1.7/parm__mpe__HRRR_to_HRAP_regrid_weight_conserve.nc.cdl) | 371,603,694 | 02 Nov 2026 16:52 | n_a=1905141, n_b=987601, n_s=5144410, nv_a=4, nv_b=4, num_wgts=1, src_grid_rank=2, dst_grid_rank=2 | — |  |
| `MPE.config` | 4,203 | 02 Nov 2026 16:52 |  |  |  |
| [MRMS_to_HRAP_regrid_weight_conserve.nc](headers/ncep_v3.1.7/parm__mpe__MRMS_to_HRAP_regrid_weight_conserve.nc.cdl) | 2,997,897,215 | 02 Nov 2026 16:52 | n_a=24500000, n_b=987601, n_s=28069777, nv_a=4, nv_b=4, num_wgts=1, src_grid_rank=2, dst_grid_rank=2 | — |  |
| [RAP130_to_HRAP_regrid_weight_conserve.nc](headers/ncep_v3.1.7/parm__mpe__RAP130_to_HRAP_regrid_weight_conserve.nc.cdl) | 143,042,330 | 02 Nov 2026 16:52 | n_a=151987, n_b=987601, n_s=1816537, nv_a=4, nv_b=4, num_wgts=1, src_grid_rank=2, dst_grid_rank=2 | — |  |
| [RFC_grid_HRAP.nc](headers/ncep_v3.1.7/parm__mpe__RFC_grid_HRAP.nc.cdl) | 17,812,904 | 02 Nov 2026 16:52 | x=1121, y=881, RFC=13 | — |  |

#### `parm/post_processing/masks/` (30 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [abrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__abrfc.nc.cdl) | 112,512 | 02 Nov 2026 16:52 | feature_id=1009 | — |  |
| [alaska.aprfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__alaska.aprfc.nc.cdl) | 3,370 | 02 Nov 2026 16:52 | feature_id=106 | — |  |
| [aprfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__aprfc.nc.cdl) | 3,157 | 02 Nov 2026 16:52 | feature_id=138 | — |  |
| [cbrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__cbrfc.nc.cdl) | 117,152 | 02 Nov 2026 16:52 | feature_id=1125 | — |  |
| [cnrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__cnrfc.nc.cdl) | 136,912 | 02 Nov 2026 16:52 | feature_id=1619 | — |  |
| [lmrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__lmrfc.nc.cdl) | 140,552 | 02 Nov 2026 16:52 | feature_id=1710 | — |  |
| [marfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__marfc.nc.cdl) | 112,912 | 02 Nov 2026 16:52 | feature_id=1019 | — |  |
| [mbrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__mbrfc.nc.cdl) | 191,760 | 02 Nov 2026 16:52 | feature_id=2171 | — |  |
| [ncrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__ncrfc.nc.cdl) | 197,000 | 02 Nov 2026 16:52 | feature_id=2302 | — |  |
| [nerfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__nerfc.nc.cdl) | 116,472 | 02 Nov 2026 16:52 | feature_id=1108 | — |  |
| [nwrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__nwrfc.nc.cdl) | 130,992 | 02 Nov 2026 16:52 | feature_id=1471 | — |  |
| [ohrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__ohrfc.nc.cdl) | 130,072 | 02 Nov 2026 16:52 | feature_id=1448 | — |  |
| [processing_mask_1000m_ABRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_ABRFC.nc.cdl) | 490,178 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_APRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_APRFC.nc.cdl) | 62,003 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=390, x=590 | — |  |
| [processing_mask_1000m_CBRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_CBRFC.nc.cdl) | 496,648 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_CNRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_CNRFC.nc.cdl) | 496,883 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_LMRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_LMRFC.nc.cdl) | 497,788 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_MARFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_MARFC.nc.cdl) | 493,232 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_MBRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_MBRFC.nc.cdl) | 498,963 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_NCRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_NCRFC.nc.cdl) | 506,070 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_NERFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_NERFC.nc.cdl) | 494,358 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_NWRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_NWRFC.nc.cdl) | 501,294 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_OHRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_OHRFC.nc.cdl) | 490,567 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_PRVI.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_PRVI.nc.cdl) | 36,774 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=110, x=300 | — |  |
| [processing_mask_1000m_SERFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_SERFC.nc.cdl) | 502,660 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_WGRFC.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_WGRFC.nc.cdl) | 502,002 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [processing_mask_1000m_extents.nc](headers/ncep_v3.1.7/parm__post_processing__masks__processing_mask_1000m_extents.nc.cdl) | 480,637 | 02 Nov 2026 16:52 | time=1, reference_time=1, y=3840, x=4608 | — |  |
| [prvi.serfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__prvi.serfc.nc.cdl) | 8,404 | 02 Nov 2026 16:52 | station=69 | — |  |
| [serfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__serfc.nc.cdl) | 5,231 | 02 Nov 2026 16:52 | feature_id=1024 | — |  |
| [wgrfc.nc](headers/ncep_v3.1.7/parm__post_processing__masks__wgrfc.nc.cdl) | 190,840 | 02 Nov 2026 16:52 | feature_id=2148 | — |  |

#### `parm/post_processing/thresholds/` (7 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| [p05.nc](headers/ncep_v3.1.7/parm__post_processing__thresholds__p05.nc.cdl) | 523,623,811 | 02 Nov 2026 16:53 | feature_id=2776734, time=366 | — |  |
| [p10.nc](headers/ncep_v3.1.7/parm__post_processing__thresholds__p10.nc.cdl) | 554,526,197 | 02 Nov 2026 16:53 | feature_id=2776734, time=366 | — |  |
| [p25.nc](headers/ncep_v3.1.7/parm__post_processing__thresholds__p25.nc.cdl) | 618,311,936 | 02 Nov 2026 16:53 | feature_id=2776734, time=366 | — |  |
| [p50.nc](headers/ncep_v3.1.7/parm__post_processing__thresholds__p50.nc.cdl) | 698,410,668 | 02 Nov 2026 16:53 | feature_id=2776734, time=366 | — |  |
| [p75.nc](headers/ncep_v3.1.7/parm__post_processing__thresholds__p75.nc.cdl) | 788,048,380 | 02 Nov 2026 16:53 | feature_id=2776734, time=366 | — |  |
| [p90.nc](headers/ncep_v3.1.7/parm__post_processing__thresholds__p90.nc.cdl) | 874,906,651 | 02 Nov 2026 16:53 | feature_id=2776734, time=366 | — |  |
| [p95.nc](headers/ncep_v3.1.7/parm__post_processing__thresholds__p95.nc.cdl) | 933,540,035 | 02 Nov 2026 16:53 | feature_id=2776734, time=366 | — |  |

#### `parm/pr_analysis_assim/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,309 | 02 Nov 2026 16:53 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,473 | 02 Nov 2026 16:53 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/pr_short_range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,314 | 02 Nov 2026 16:53 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,476 | 02 Nov 2026 16:53 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/short_range/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 11,778 | 02 Nov 2026 16:53 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,757 | 02 Nov 2026 16:53 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/short_range_hawaii_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,292 | 02 Nov 2026 16:53 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,470 | 02 Nov 2026 16:53 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/short_range_puertorico_no_da/` (2 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `hydro.namelist` | 10,310 | 02 Nov 2026 16:53 |  |  | [hydro.namelist](#ncep-namelists) |
| `namelist.hrldas` | 2,476 | 02 Nov 2026 16:53 |  |  | [namelist.hrldas](#ncep-namelists) |

#### `parm/transfer/` (30 files)

| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |
|---|---:|---|---|---|---|
| `transfer_nwm_1.list` | 2,064 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_2.list` | 2,065 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_3.list` | 1,969 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_4.list` | 1,907 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_nwges_1.list` | 2,017 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_nwges_2.list` | 1,945 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_nwges_3.list` | 1,895 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_nwges_4.list` | 1,888 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_nwges_5.list` | 1,888 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_nwges_6.list` | 1,888 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_nwges_7.list` | 1,888 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_1.list` | 2,160 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_2.list` | 2,161 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_3.list` | 2,065 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_4.list` | 2,003 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_nwges_1.list` | 2,125 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_nwges_2.list` | 2,053 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_nwges_3.list` | 2,003 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_nwges_4.list` | 1,996 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_nwges_5.list` | 1,996 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_nwges_6.list` | 1,996 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_nwges_7.list` | 1,996 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_post_1.list` | 2,270 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_post_2.list` | 2,276 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_post_3.list` | 2,218 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_p2t_restart.list` | 1,933 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_post_1.list` | 2,174 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_post_2.list` | 2,180 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_post_3.list` | 2,122 | 02 Nov 2026 16:53 |  |  |  |
| `transfer_nwm_restart.list` | 1,837 | 02 Nov 2026 16:53 |  |  |  |

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
