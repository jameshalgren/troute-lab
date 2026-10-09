# troute-lab

Tools and reproducible experiments for the National Water Model (NWM) channel network and
[T-Route](https://github.com/NOAA-OWP/t-route), the NWM's channel-routing framework:

- **[`explorer/`](explorer/)**: an interactive basin explorer for the NWM v3.1.6 channel
  network (RouteLink) in all four NWM domains.
- **[`repro/`](repro/)**: four self-contained, deeply reproducible experiments (pinned
  environments, SHA-256-checked inputs downloaded by script, machine-checked expected results).

They were built for a forthcoming paper on the origins of T-Route (see [Citation](#citation)),
and are useful beyond it.

> **AI assistance.** Most of the code and text here was drafted with an AI assistant
> (Anthropic's Claude) working for James Halgren. He and his students are working on reviewing everything.
> If you would like to help with the review, please reach out to him. The explorer page carries an "AI-generated view · not approved" badge, and the
> READMEs say what has been reviewed. Check the results before you rely on them.

## Basin explorer

<!-- TODO (author): screenshot, e.g. docs/explorer.png, and a one-line caption -->

**Hosted:** <https://jameshalgren.github.io/troute-lab/> (GitHub Pages, overview tiles).

The explorer shows every independent drainage network of the NWM v3.1.6 channel network in
CONUS, Alaska (Cook Inlet and the Copper River, which is all the NWM Alaska domain contains),
Hawaii, and Puerto Rico and the U.S. Virgin Islands. It lists named tributaries, width functions
(segments per topological distance above the mouth), how much channel lies outside the United
States, and places (USGS gages, NWS forecast points, reservoirs, dams, bridges) keyed to NWM
feature IDs, with flags where a place's link to the network looks wrong.

Run it locally ([`uv`](https://docs.astral.sh/uv/) is the only prerequisite):

```sh
uv run explorer/fetch_data.py     # web data bundle (~31 MB) -> explorer/data/, SHA-256 checked
uv run explorer/serve.py          # then open http://localhost:8765/
```

`uv run explorer/fetch_data.py --full` adds the full-resolution tiles (983 MB), which enable the
"upstream of this point" highlight and waterbody polygons. Rebuilding all of the data from the
public sources (NWM RouteLink and hydrofabric, TIGER/Line, USGS, NWPS, NID, NBI, EPA) is
described in [`explorer/README.md`](explorer/README.md); file schemas are in
[`explorer/DATA_CONTRACT.md`](explorer/DATA_CONTRACT.md).

## Experiments

Each experiment runs with one command, `repro/<experiment>/run.sh` (locked environment ->
download and verify inputs -> run -> compare with `expected/`; exit status 0 means
reproduced). Conventions and prerequisites: [`repro/README.md`](repro/README.md).

- **[`short_ts_switch/`](repro/short_ts_switch/)**: what T-Route's `assume_short_ts` switch
  (WRF-Hydro's one-timestep lag of upstream inflow) does to routed flows, how the difference
  builds up through a network, and how it depends on the routing timestep. Builds T-Route from
  source at a pinned commit and runs it on a synthetic storm over the Potomac network and on
  the LowerColorado test case, with the switch on and off at four timesteps. Needs `gfortran`,
  `make`, `git` and netCDF-C/Fortran; about 8 minutes.
- **[`mc_courant_timestep/`](repro/mc_courant_timestep/)**: reproduces Adam Wlostowski's 2020
  synthetic-channel experiment showing that Muskingum-Cunge routing with a Courant number
  above 1 delays and attenuates waves. Compiles the original Fortran kernels fetched by commit
  SHA; needs `gfortran`. `QUICK=1 repro/mc_courant_timestep/run.sh` runs the primary
  experiment only (about 30 s); a pinned `Dockerfile` is included.
- **[`network_stats/`](repro/network_stats/)**: counts and sizes of the independent drainage
  networks in the NWM v3.1.6 RouteLink (all four domains), the share of the largest network
  (Mississippi, 40.2% of CONUS) and what it means for by-network parallelism, cuts at the
  international boundary, a comparison with NWM v2.1 and 2020 counts, and statistics for about
  160 named sub-rivers. A few minutes after the downloads (`REQUIRED_ONLY=1` skips the
  optional 269 MB NWM v2.1 file). Also produces the tables the explorer build reads.
- **[`routelink_topwidth/`](repro/routelink_topwidth/)**: how the compound-channel top width
  `TopWdthCC` is derived from `TopWdth` and the other channel parameters in the NWM v3.1.6
  RouteLink files. Under a minute after the 320 MB download.

## Data

No generated data is committed to git. Large inputs are downloaded from their public sources
by each experiment's `fetch_data.py` (pinned by URL and SHA-256). Data that this project
generates and that is too large or too slow to rebuild for every user is published as
versioned **data bundles**: release assets of this repository, listed with sizes and SHA-256 in
[`data_bundles.json`](data_bundles.json) and downloaded by
[`tools/fetch_bundle.py`](tools/fetch_bundle.py):

| Bundle | Release tag | Contents | Used by |
|---|---|---|---|
| `explorer` | `explorer-data-v1` | explorer web data (JSON + overview tiles, 31 MB); optional full tiles (983 MB) | `explorer/fetch_data.py`, the Pages workflow |
| `network-stats` | `network-stats-data-v1` | `domains_snapshot.json` (4.8 MB): every EPA and GNIS answer that `domains.py` used | `repro/network_stats/run.sh` |

A published tag never changes; new data gets a new tag. HydroShare is the intended archival
home for the bundles (TODO: the resource URLs go in `data_bundles.json`, and
`fetch_bundle.py --source hydroshare` then uses them). Every bundle can also be rebuilt from
the public sources (see the READMEs).

## Data sources and terms

The code is under the MIT License ([`LICENSE`](LICENSE)). Data products (the bundles, and
everything the scripts download) follow the terms of their sources:

- **Public domain (U.S. Government works):** NOAA National Water Model parameter files
  (RouteLink, reservoir indexes) and the NWM v3 channel hydrofabric; NOAA National Water
  Prediction Service (NWPS) gauge metadata; USGS water data, NLDI, GNIS and NHDPlus HR;
  EPA/USGS NHDPlus V2 (EPA WATERS services); U.S. Census Bureau TIGER/Line boundaries; FHWA
  National Bridge Inventory; USACE National Inventory of Dams.
- **Natural Earth** boundary data: public domain.
- **Environment and Climate Change Canada** hydrometric station metadata (names and drainage
  areas of Water Survey of Canada gauges in `places.json`): Open Government Licence – Canada.
- **Basemaps** (loaded by the explorer page at view time, not redistributed): light theme
  from [OpenFreeMap](https://openfreemap.org/) (© OpenMapTiles, data © OpenStreetMap
  contributors, ODbL); dark theme from [CARTO](https://carto.com/attributions)
  (© CARTO, © OpenStreetMap contributors). The map shows these attributions.
- **Libraries** loaded by the page: MapLibre GL JS and PMTiles (both BSD-3-Clause).

## Citation

A paper on the origins of T-Route is in preparation; this section will give its citation.
Until then, cite this repository by URL and commit SHA (e.g.
`https://github.com/jameshalgren/troute-lab/tree/<sha>/repro/short_ts_switch`). An archived,
DOI-bearing release (Zenodo) is planned.

## License

MIT for the code ([`LICENSE`](LICENSE)). Data products
follow their sources' terms, above.
