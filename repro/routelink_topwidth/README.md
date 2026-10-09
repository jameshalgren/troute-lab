# RouteLink compound-channel top width (NWM v3.1.6)

*AI-assembled (Claude, 2026-10-05); not yet reviewed by the author.*

## Question
How is `TopWdthCC` (the compound-channel/floodplain top width used by Muskingum-Cunge
in the NWM and T-Route) derived from `TopWdth` and the other channel parameters in the
operational NWM v3.1.6 RouteLink files? Discussion and interpretation will be in the forthcoming paper (see the top-level
README).

## Provenance
- **Inputs:** `RouteLink_{CONUS,AK,HI,PRVI}.nc` from NCEP's operational parameter tree,
  <https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm/> (`domain/`,
  `domain_alaska/`, `domain_hawaii/`, `domain_puertorico/`). Downloaded 2026-09-30; server
  `Last-Modified` Thu, 09 Jul 2026. SHA-256 and sizes are recorded in `fetch_data.py`.
  The CONUS file's `processing_notes` say it was "produced on Tue Aug 5 2025 by Lynker".
- **Method:** `analyze.py` (first run 2026-10-01/02 as a standalone script).
  The analysis logic is unchanged; it now also writes machine-readable results.

## How to run
```bash
repro/routelink_topwidth/run.sh
```
Needs `uv` and ~320 MB of downloads (CONUS is 269 MB). `run.sh` runs `uv sync --locked`
(Python 3.12.13, numpy 2.5.3, pandas 3.0.6, xarray 2026.9.0, netCDF4 1.7.4; full tree in
`uv.lock`), then `fetch_data.py` → `analyze.py` → `check.py`. Outputs in `results/`:
`results.json`, `report.txt` (the same printed report as the original script), and
`provenance.json`. Analysis time is under a minute.

## Expected results (`expected/expected.json`)
| Domain | reaches | TopWdthCC = 3·TopWdth | max(3·TW, F(order)) | BtmWdth/TopWdth | nCC/n |
|---|---|---|---|---|---|
| CONUS | 2,776,734 | 2,487,036 (89.567%) | 2,776,709 (25 residuals) | 0.6 | 2 for all |
| AK | 391,528 | 100% | n/a | 0.6 | 2 for all |
| HI | 13,637 | 100% | n/a | 0.6 | 3.4286 / 3.1429 / 2.8571 (n = 0.035) |
| PRVI | 14,017 | 100% | n/a | 0.6 | 2 for all |

CONUS floors by Strahler order, inferred from the data and also tested as fixed values:
F = {2: 10, 3: 30, 4: 50, 5: 70, 6: 80, 8: 150} m. Matching uses `np.isclose(rtol=1e-4)`.
`check.py` requires exact counts and floors, percentages within 0.001 points, and
BtmWdth/TopWdth within 1e-6 of 0.6 for every reach.

**Status (2026-10-05, macOS arm64):** `check.py` passes, 23/23.

## Known caveats
- `report.txt` differs from the 2026-10-01 output only in the *order of tied counts* in
  two "most common values" listings (pandas 3 vs. the earlier pandas); no number differs.
- The `n_*_CONUS_floors` fields are computed for every domain but are meaningful (and
  checked) only for CONUS; AK, HI, and PRVI have no floors.
- NCEP's `nwprod` tree holds only current operational versions. If v3.1.6 is retired or
  the files are replaced, `fetch_data.py` stops with an explanation rather than using
  different data.
