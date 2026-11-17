# NWM parameter archives: what is published, where, and in which version

A catalog of the public National Water Model (NWM) parameter files. It covers two places:

- **NOHRSC `owp_files`** (<https://www.nohrsc.noaa.gov/owp_files/>): the versioned
  parameter tarballs (v2.1, v3.0), the coastal tarball, and the channel-hydrofabric
  geodatabases;
- **NCEP `nwm.v3.1.7`** (<https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/>):
  the operational code package and its `parm/` tree. NCEP only ever serves the current
  version (about 208 GB, too large to archive here), so this catalog is the record of
  v3.1.7: the listing of every file with its size and date, and the checksums and
  headers of the files it read. The experiments in this repository pin the RouteLink
  files they use by SHA-256.

For every file it gives size, date, checksum, netCDF header, and what the file is for
(from the WRF-Hydro and NWM documentation where they say so, marked "undocumented"
where they don't). A cross-walk table shows which file is in which archive.

**Read [`nwm_parameter_archives.md`](nwm_parameter_archives.md).** Its §1 lists the key
findings and §8 the open questions.

We built it because the 2022 timing rerun ([`repro/perf_2022`](../perf_2022/))
needed the NWM v2.1 `LAKEPARM_CONUS.nc`, which we found in the NOHRSC
tarballs. As a community service, we created this catalog of the contents along with
a description of how they relate to the files the operational model reads.

## Provenance

- Assembled by Claude (AI) on 2026-11-10. 
  Everything was read from the live servers that day unless another date is given.
- Statements of fact come from listings, checksums and headers. Interpretation is marked
  "Note (AI):" in the catalog.
- The `LkArea` unit check (km², §8 question 7) was added 2026-11-11. The documentation
  error it found is reported upstream as
  [NCAR/wrf_hydro_nwm_public#933](https://github.com/NCAR/wrf_hydro_nwm_public/issues/933),
  and fixed by
  [PR #934](https://github.com/NCAR/wrf_hydro_nwm_public/pull/934) (merged 2026-11-12).

## Layout

| Path | What | In git |
|---|---|---|
| `nwm_parameter_archives.md` | the catalog (generated; see Rebuild) | yes |
| `rebuild.sh` | rebuilds the catalog, offline or with a fresh crawl (see Rebuild; `./rebuild.sh --help`) | yes |
| `.gitignore` | keeps crawl outputs, tarball copies and scratch out of git | yes |
| `listings/` | every NOHRSC and NCEP file with size and date (TSV), and every tarball member with size, date, MD5 and SHA-256 (JSON) | yes |
| `listings/ncep_parm_hashes.txt` | SHA-256 and MD5 of the 17 small routing files in NCEP `parm/domain*/` (RouteLink, LAKEPARM, nudgingParams, Diversion, reservoir_index) | yes |
| `headers/` | `ncdump -h` of every readable netCDF file (261), and the FileGDB layer schemas | yes |
| `build/` | `main_template.md` (the hand-written text) and the generated tables it includes | yes |
| `raw/ncep_text/` | NCEP namelists and small text files that the namelist tables are built from | yes |
| `raw/nohrsc_text/` | the NOHRSC READMEs and the small text members of each tarball | yes |
| `raw/` (rest) | crawl logs (`raw/logs/`), NCEP scripts (`raw/ncep_code/`) and NCEP doc files and PDFs (`raw/ncep_doc/`) | no (`.gitignore`); re-created by the crawl. The first survey's `raw/docs/` and `raw/ncep_text_heads/` are not re-created |
| `scripts/` | crawl, scan and table scripts | yes |
| `scripts/analysis/` | the one-off checks quoted in the catalog (`hdrdiff.py`, `rl_diff.py`, `lake_check.py`, `lakearea_check.py`) | yes |

## Rebuild

All commands run from this folder.

**1. Rebuild the catalog from the committed listings and headers.** This needs no
network access and takes a few seconds:

```sh
./rebuild.sh
```

That regenerates the tables in `build/` from `listings/` and `headers/`, then assembles
`nwm_parameter_archives.md` from `build/main_template.md`. Edit the template to change
the text. The tables are generated, so don't edit them by hand.

**2. Re-survey the servers.** This is needed if NOHRSC or NCEP change their files. It
streams about 21 GB (about 17 GB with the v2.1 tarball cached; see `--cache` below) and
keeps none of it; plan on a few hours.

```sh
./rebuild.sh --crawl
```

- Crawls both servers into `listings/`.
- Streams each NOHRSC tarball once, hashing every member and writing headers to
  `headers/`.
- Reads the NCEP netCDF headers by HTTP byte range, without full downloads.
- Fetches the namelists into `raw/ncep_text/`.
- Then does step 1.
- The v2.1 tarball streams from NOHRSC like the others. Pass `--cache DIR` (repeatable,
  or set `NWM_CATALOG_CACHE=DIR1:DIR2`) to use local copies of the tarballs and NCEP
  files instead. A copy is used only if the server still shows the listed size and date
  and the copy's size and SHA-256 match the previous survey.
- Other options (`./rebuild.sh --help` lists them all):
  - `--keep DIR` saves each streamed tarball in `DIR`;
  - `--only STEP[,STEP...]` runs only some crawl steps (e.g. `--only v3.0` or
    `--only ncep-tree`);
  - `--ncep-subtree REL` limits the NCEP listing, header and hash steps to one folder,
    e.g. `parm/domain_hawaii/`, and merges the result into the existing listings;
  - `--no-build` skips step 1 after the crawl.

Compare the new listings with git (`git diff --stat listings/ headers/ raw/ncep_text/`)
to see what changed.
Numbers quoted in the template text (counts and sizes outside the generated tables) are
not updated automatically; check them against the diff.

Requires `uv`, plus `ncdump` (netCDF-C) on the PATH for the header steps.
