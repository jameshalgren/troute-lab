# NWM routing-calculation estimate: 2020 poster vs. operations now

*AI-assembled (Claude, 2026-10-29); not reviewed by the author.*

How many channel-routing calculations does the operational National Water Model (NWM) do per
day? Calculation: sum over configurations of simulation-hours/day (cycles/day x hours/cycle x
members) x 3600/`DTRT_CH` (300 s, so 12 routing steps per hour) x routed segments in that
domain. A "calculation" is one segment update per 300-s step, as on the 2020 poster.

## Files

| File | What |
|---|---|
| `configs.csv` | one row per configuration: cycles, hours, members, dt, `status` (measured/inferred), `how`, `dt_source`, source URL, date |
| `segments.csv` | RouteLink segments per domain, and the `feature_id` count read from one channel_rt file per domain |
| `dt_sources.csv` | `DTRT_CH`, `channel_option`, `out_dt`, `KHOUR`, `NOAH_TIMESTEP`, `RESTART_FREQUENCY_HOURS` from all 25 v3.1.6 parm families |
| `catalog_nomads.py` | fetches and parses the NOMADS day listing (and the S3 mirror listing for exact sizes) |
| `nc_attrs.py` | prints `model_initialization_time`, `model_total_valid_times`, `feature_id` count of channel_rt files |
| `nwm_scale.py` | the calculation; cross-checks every `configs.csv` row against the catalog |
| `expected/` | committed snapshot of the catalog for nwm.20261029 (NOMADS keeps only two days): `nomads_catalog.csv`, `nomads_channel_rt_cycles.csv`, `nomads_footprint.csv`, `nomads_fetch_log.csv` |
| `results/` | outputs (gitignored): `table_2020.csv`, `table_current.csv/.md`, `domain_shares.csv`, and fresh `nomads_*.csv` if the catalog is re-run |

Reproduce (the day must still be on NOMADS; otherwise `nwm_scale.py` uses `expected/`):

```sh
D=<fresh empty directory outside the repo>
uv run catalog_nomads.py fetch nwm.20261029 $D/listings      # 143 Apache listings
uv run catalog_nomads.py fetch-s3 nwm.20261029 $D/s3         # 132 S3 ListObjectsV2 pages
uv run --no-project python -I catalog_nomads.py parse $D/listings nwm.20261029 $D/s3
uv run nwm_scale.py
```

## Result (nwm.20261029, NWM v3.1)

| Total | calcs/day | sim-h/day |
|---|---:|---:|
| 2020 spreadsheet (2.7e6 segments) | 5.79e11 | 17,880 |
| **Now, all domains, all configurations** | **6.75e11** | 27,480 |
| Now, without `_no_da` (open-loop) runs | 6.33e11 | 24,876 |
| Now, without `_blend` runs | 6.39e11 | 25,560 |
| Now, without `_no_da` and `_blend` runs | 5.97e11 | 22,956 |
| Now, CONUS only | 6.40e11 | 19,208 |
| Sensitivity: CONUS 2,729,077 segments (v2.0) | 6.64e11 | 27,480 |
| Sensitivity: analysis windows counted once per valid hour | 6.70e11 | 27,048 |

Per configuration: `results/table_current.md`. The 2020 table is unchanged.

### By domain: segments, work and NOMADS footprint

Folders = top-level directories of the day listing, all products (routing folders in
parentheses). Bytes are exact (S3 mirror sizes), GB = 1e9 bytes per day. "All files" = model
output + forcing + coastal SCHISM for that domain.

| Domain | segments | % | sim-h/day | % | calcs/day | % | folders (routing) | % | channel_rt GB | % | all files GB | % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONUS | 2,776,734 | 86.9 | 19,208 | 69.9 | 6.40e11 | 94.8 | 34 (19) | 50.0 | 93.6 | 86.7 | 1,065.2 | 95.8 |
| Alaska | 391,528 | 12.3 | 7,408 | 27.0 | 3.48e10 | 5.2 | 18 (13) | 26.5 | 14.1 | 13.0 | 42.2 | 3.8 |
| Hawaii | 13,637 | 0.4 | 336 | 1.2 | 5.5e7 | 0.008 | 8 (4) | 11.8 | 0.16 | 0.1 | 1.7 | 0.2 |
| Puerto Rico/USVI | 14,017 | 0.4 | 528 | 1.9 | 8.9e7 | 0.013 | 8 (4) | 11.8 | 0.06 | 0.06 | 2.5 | 0.2 |
| OCONUS (AK+HI+PR) | 419,182 | 13.1 | 8,272 | 30.1 | 3.50e10 | 5.2 | 34 | 50.0 | 14.3 | 13.3 | 46.5 | 4.2 |
| Total | 3,195,916 | | 27,480 | | 6.75e11 | | 68 (40) | | 107.9 | | 1,111.7 | |

Also in the day directory: `post_processed/` (RFC and WMS subsets; 77,837 files, 122.1 GB) and
`usgs_timeslices/` (96 files, 0.12 GB). Whole day: 131,603 files, 1,233.9 GB.

**The expectation that OCONUS domains take a lot of folder space but few segments, so their
share of the computation is trivial.** Folders: yes, OCONUS is half of the domain folders (34
of 68). Bytes: no, OCONUS is 4.2 % of the bytes (13.3 % of channel_rt bytes); the CONUS
medium-range land files alone are 490 GB/day. Computation: trivial for Hawaii and Puerto Rico
(0.021 % together), small for Alaska (5.2 %). Alaska has 12 % of the segments and 27 % of the
simulation-hours (it runs the full 6-member medium range, blend and open loop), but CONUS has
both the long range (11,520 sim-h/day) and 7 times the segments. Segments match output: the
channel_rt files carry exactly the RouteLink count in every domain (`segments.csv`).

## Method (2026-10-29 local; 2026-10-30 03:58-04:20 UTC)
1. `https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod/` listed `nwm.20261029/` and
   `nwm.20261030/` only. nwm.20261029 is the most recent complete day: every channel_rt
   cycle has its full set of files (`expected_files` = `files` in every catalog row), the
   last cycles (t23z analysis, t18z long range) are present, a second fetch about six
   minutes later found the same file entries, and five directories re-listed at 04:25 UTC
   (long range, medium range, short range, analysis, coastal) had the same file counts.
2. `curl -s -A 'Mozilla/5.0'` returned HTTP 200 with 0 bytes over HTTP/2. `curl --http1.1`
   with a full browser user agent returned complete listings: the 70 top-level directories
   and the 72 directories below `post_processed/` (142 listings), each checked to end in
   `</html>`; no WebFetch, no truncation. `catalog_nomads.py fetch` then re-fetched all of them
   plus the day index (143) with Python's `urllib`; the file entries were identical.
3. Exact sizes: the NOMADS listings round sizes ("12M" for a 12,354,018-byte file, +1.9 %).
   The NOAA Open Data mirror `https://noaa-nwm-pds.s3.amazonaws.com/` (ListObjectsV2,
   prefix `nwm.20261029/`) has the same 131,603 keys, so every size in the catalog is exact.
4. Per configuration and cycle, `catalog_nomads.py parse` reads the channel_rt time stamps
   (`fHHH`, `fHHHMM` lead; `tmNN`, `tmHHMM` look-back), the output interval, and the
   simulated hours: last lead for forecasts; look-back + one interval for analyses.
5. 21 channel_rt files (88 MB) were downloaded and read with `nc_attrs.py` (netCDF4):
   initialization and valid times, number of valid times, `feature_id` count, version.
6. All 25 parm families of `https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/`
   were read (`hydro.namelist`, `namelist.hrldas`): `DTRT_CH = 300` and `channel_option = 2`
   in every one (`dt_sources.csv`).

## What changed from the previous pass (6.75e11)
- **The total is unchanged: 6.750e11 calculations/day, 27,480 sim-h/day.** Every value the
  previous pass inferred or assumed is now measured on a complete day, and all 30 rows match.
  `nwm_scale.py` checks this on every run.
- The listings are complete: curl over HTTP/1.1, not WebFetch truncated at 100k characters.
  CONUS short range t12z-t23z, medium-range members t12z/t18z, blend t06z-t18z, long range
  t18z and the Alaska t21z short range were all seen.
- Analysis cycles: 3 h per cycle is measured, no longer assumed (next section).
- Puerto Rico short range, 4 cycles: confirmed. NWS SCN 26-64 (v3.1) added "New 00Z and 12Z
  Short-Range forecast cycles"; water.noaa.gov and `nwmurl` (06Z/18Z) predate v3.1.
- Hawaii short range and open loop: t00z and t12z for both. The previous pass had noted
  00Z/18Z for the Hawaii open loop on water.noaa.gov; NOMADS shows 00Z/12Z.
- `analysis_assim_long`: 4 cycles/day with 12-h windows, not hourly (water.noaa.gov).
- Version: v3.1 is operational (below). `DTRT_CH` was checked in all 25 parm families, not 13.
- New: folders, files and exact bytes per domain; totals with and without `_no_da` and `_blend`.

## How many hours does an analysis cycle integrate?
Each cycle re-runs its whole look-back window from a restart, so overlapping windows are
computed again. Evidence:
- `model_initialization_time` in the files: CONUS, Alaska and Puerto Rico `analysis_assim`
  t03z start at 00Z (3 h); PR t00z, t01z, t02z start at 21Z, 22Z, 23Z; Hawaii t12z starts at
  09Z with 12 quarter-hour outputs. `analysis_assim_extend` t16z starts 28 h back (2026-10-28
  12Z); Alaska t20z starts 32 h back. `analysis_assim_long` t06z starts 12 h back, with
  cycles 6 h apart.
- `namelist.hrldas`: `KHOUR = 3` (analysis, all domains), 28 / 32 (extended), 12 (long);
  `RESTART_FREQUENCY_HOURS = 1` (4 for extended), so the next cycle can start from the
  previous cycle's restart.
- The same valid hour (PR, 2026-10-29 00Z) from cycles t00z, t01z and t02z: t01z and t02z are
  identical; t00z differs in 0.76 % of reaches (up to 3.05 m3/s). So the overlap is
  recomputed (here with new inputs between t00z and t01z), not copied.

The work is therefore 72 sim-h/day for each hourly analysis, though only 24 h of valid time.
Counting each valid hour once would lower the total by 0.8 % (6.70e11).

## NWM version running
- NWS SCN 26-64 Updated (2026-07-30): "Effective on or about August 18th, 2026, beginning
  with the 1200 Coordinated Universal Time (UTC) run, the National Weather Service (NWS) will
  begin operationally running Version 3.1 of the National Water Model (NWM)" (the first
  version, 2026-07-13, gave August 12th); the NWM "provides streamflow for over 3.2 million
  river reaches" (sum of the four RouteLink counts: 3,195,916). It also cuts the medium-range
  coastal runs to 120 h (seen: f001-f120) and adds a PR P-surge coastal run "only created
  when upstream Psurge forcing data is available" (absent on 2026-10-29).
- NOMADS: `.../com/nwm/prod/` and `.../com/nwm/v3.1/` list the same days; `.../com/nwm/v3.0/`
  stops at `nwm.20260818/`. Files: `NWM_version_number = v3.1`, `code_version = v5.4.0`.
- NCO `https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/` lists only `nwm.v3.1.6/`. The NCO
  changes page `https://www.nco.ncep.noaa.gov/pmb/changes/` lists NWM entries only up to the
  v3.0 upgrade (2023-09-20, SCN 23-76); v3.1 is not on it.

## Excluded (in the catalog, not counted)
- `forcing_*` (14 folders): meteorological input.
- Coastal SCHISM total water: `*_coastal_atlgulf`, `*_coastal_pacific`, `*_coastal_hawaii`,
  `*_coastal_puertorico` (14 folders, 61.5 GB/day). It is driven by NWM streamflow but is not
  NWM channel routing.
- Folder tally: 40 with channel_rt + 14 forcing + 14 coastal + `post_processed` +
  `usgs_timeslices` = 70.
- `post_processed/` (RFC and WMS subsets of model output) and `usgs_timeslices/` (observations).
- `land`, `reservoir`, `terrain_rt` files: same runs as channel_rt; listed, not counted again.

## Medium-range members
CONUS and Alaska each have `medium_range_*mem1` to `mem6`: member 1 to 240 h, members 2-6 to
204 h (`model_total_valid_times = 204`), 4 cycles. There is no `mem7` directory. Official
notices: NWS SCN 19-42 (NWM v2.0, seven members,
`https://www.weather.gov/media/notification/pdf2/scn19-42natl_water_model.pdf`); NWS PNS 23-06
lists "Removal of ensemble member seven from the existing GFS-forced medium-range model
output" for v3.0 (`https://www.weather.gov/media/notification/pdf_2023_24/pns23-06_nwm_v3.0.pdf`).
The 2020 sheet's 7-member medium range is 5,856 sim-h/day per domain; now it is 5,040.

## What changed since 2020
- Medium range: 7 members to 6 (-816 sim-h/day per domain), see above.
- Added CONUS runs: medium-range open loop (`no_da`, 4 x 240 h) and NBM-forced `blend`
  (4 x 240 h), extended (28 h) and long-range (4 x 12 h) analyses, and open-loop twins of
  every analysis.
- New domains: Alaska (391,528 reaches, with its own 6-member medium range, blend and open
  loop), and, small, Hawaii and Puerto Rico/USVI.
- CONUS network: 2,729,077 to 2,776,734 segments (+1.7 %).
- Long range unchanged: 4 members x 4 cycles x 720 h = 11,520 sim-h/day; 64 % of the 2020
  sim-hours and 57 % of today's calculations.
- Routing step 300 s everywhere, including the 15-minute-output Hawaii runs, the 3-hourly
  `no_da` medium range and the 6-hourly long range.

## Remaining unknowns
1. Blend runs: no `medium_range_blend` parm directory exists in v3.1.6, so `DTRT_CH = 300` is
   assumed from `medium_range` / `ak_medium_range`.
2. Parm directories are matched to NOMADS directories by name. The job scripts were not read.
   Where they override `KHOUR` (Alaska 45-h cycles; members 2-6 at 204 h), the output shows
   what actually ran.
3. One day sampled. Runs that appear only on some days (PR P-surge coastal), failed and re-run
   jobs, and day-to-day changes are not covered.
4. Unpublished work is not counted: spin-up, manual climatological restarts
   (`parm/manualclimateRestart/`), anything without channel_rt on NOMADS. Lake and reservoir
   updates are not counted, and nor are sub-iterations inside a routing step.
5. The open-loop files examined (PR `analysis_assim_no_da`, CONUS `medium_range_no_da`) carry
   `dev_channel_only = 1`, and `_no_da` folders hold only channel_rt files. They may be
   channel-only re-runs. This was not traced in the scripts, and the count is unaffected
   (they route every segment).
6. Retention of the S3 mirror is unknown; `expected/` keeps the catalog.
7. Bytes are what NOMADS publishes per day, not the model's working disk (restarts,
   intermediate files).

## Sources (retrieved 2026-10-29 local date unless noted)
- NOMADS: `https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod/nwm.20261029/` and
  `.../com/nwm/` (fetch log with UTC times: `expected/nomads_fetch_log.csv`).
- S3 mirror: `https://noaa-nwm-pds.s3.amazonaws.com/?list-type=2&prefix=nwm.20261029/`.
- channel_rt files read with `nc_attrs.py`, from `.../prod/nwm.20261029/<dir>/`:
  PR `analysis_assim` t00z tm00, t01z tm01, t02z tm02, t03z tm02; PR `analysis_assim_no_da`
  t03z tm02; PR `short_range` t06z f001; Hawaii `analysis_assim` t12z tm0245 and tm0000;
  Hawaii `short_range` t12z f00015; Alaska `analysis_assim` t03z tm02,
  `analysis_assim_extend` t20z tm00, `short_range` t03z f001, `medium_range_alaska_mem2`
  t00z f001; CONUS `analysis_assim` t03z tm02, `analysis_assim_extend` t16z tm00,
  `analysis_assim_long` t06z tm00, `long_range_mem2` t00z f006, `medium_range_mem2` t00z
  f001, `medium_range_blend` t00z f001, `medium_range_no_da` t00z f003, `short_range` t00z f001.
- Namelists: `https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/<dir>/`
  (`dt_sources.csv`).
- NWS SCN 26-64 Updated, 2026-07-30:
  `https://www.weather.gov/media/notification/pdf_2026/scn26-64_Updated_National_Water_Model_V3.1_aaa.pdf`
  (first version, 2026-07-13, effective August 12:
  `https://www.weather.gov/media/notification/pdf_2026/scn26-64_National_Water_Model_V3.1.pdf`;
  proposal: PNS 25-77, `https://www.weather.gov/media/notification/pdf_2025/pns25-77_nwm_v3.1.pdf`,
  downloaded but not read).
- NCO changes page: `https://www.nco.ncep.noaa.gov/pmb/changes/` (newest NWM entry: v3.0,
  SCN 23-76).
- Segment counts: `repro/network_stats/README.md` (RouteLink v3.1.6 from
  `https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/domain*/`, downloaded
  2026-09-30). The 2020 count 2,729,077: AGU 2020 poster,
  `https://github.com/NOAA-OWP/t-route/blob/0d512ba026e3b10a432fb707fc80655a6c2f63e2/doc/AGU_Poster.md#L38`.
- Earlier pass (kept for reference): `https://water.noaa.gov/about/nwm`; `nwmurl` 1.0.8 (PyPI),
  whose cycle and member tables are older than v3.1.
