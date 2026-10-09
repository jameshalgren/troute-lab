"""Query USGS services for river names and outlet/continuity facts; write river_names.json.

This is the only step that uses live web services, so it is NOT part of run.sh. Its
output, river_names.json, is committed as a dated snapshot and read by analyze.py.
Re-run it (after analyze.py has written results/networks_CONUS.csv) to refresh:

    uv run --locked python river_names.py            # top 500 CONUS networks (~5 min)
    uv run --locked python river_names.py --top 50

Sources (all public, no key):
  * NHDPlus V2 flowline attributes from the USGS geoserver WFS layer
    `wmadata:nhdflowline_network` (the layer behind the USGS NLDI and nhdplusTools):
    https://api.water.usgs.gov/geoserver/wmadata/ows . NWM feature_id == NHDPlus V2
    COMID wherever the ID exists in NHDPlus V2. Any attribute can be fetched by COMID,
    e.g. GNIS names:
      {WFS}&propertyName=comid,gnis_name&CQL_FILTER=comid IN (22811611,626220)
    (URL-encode the filter). Filters on levelpathi, hydroseq, gnis_name also work.
  * USGS NLDI upstream-mainstem navigation:
    https://api.water.usgs.gov/nldi/linked-data/comid/{comid}/navigation/UM/flowlines

Name rule: on the NHDPlus level path (mainstem) through the outlet, `name` is the first
non-blank GNIS_NAME going upstream from the outlet (NHDPlus hydroseq increases
upstream), and `mainstem_name` is the most frequent non-blank GNIS_NAME on that level
path (e.g., the Atchafalaya outlet's level path is mostly the Red River). If the outlet
COMID is not in NHDPlus V2, we walk up the RouteLink mainstem (the upstream branch with
the most segments, at most 50 steps) to the first COMID that is, and record the number
of steps. No name found => "UNVERIFIED".

Outlet facts recorded for classification in analyze.py: NHDPlus terminalfl,
dnhydroseq, and the FTYPE of the NHDPlus flowline with hydroseq == dnhydroseq (NHDPlus
links terminal flowlines that reach the sea to a "Coastline" feature).
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from analyze import DATA, RESULTS, graph, load, traverse

HERE = Path(__file__).resolve().parent
WFS = ("https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.0.0&request=GetFeature"
       "&typeName=wmadata:nhdflowline_network&outputFormat=application/json")
NLDI = "https://api.water.usgs.gov/nldi/linked-data/comid/{}/navigation/UM/flowlines?distance=9999"
PROPS = "comid,gnis_name,levelpathi,hydroseq,terminalfl,dnhydroseq,totdasqkm,vpuid,streamorde"
# Mainstems checked for continuity (NLDI upstream mainstem of the outlet COMID).
CONTINUITY = [626220, 21412883, 22811611, 23832907]
# Named tributaries checked for membership in a network: {outlet: [(GNIS name, VPU)]}.
TRIBUTARIES = {626220: [("Pecos River", "13"), ("Rio Chama", "13")]}
CAP = 5000  # rows per WFS request we accept as complete; larger batches are split


def get(url: str, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "troute-paper-repro/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry ({e})", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError


def wfs(cql: str, props: str = PROPS) -> list[dict]:
    url = f"{WFS}&propertyName={props}&CQL_FILTER={urllib.parse.quote(cql, safe="'(),=")}"
    return [f["properties"] for f in get(url)["features"]]


def wfs_in(field: str, values: list[int], props: str, batch: int) -> list[dict]:
    out = []
    for k in range(0, len(values), batch):
        chunk = values[k:k + batch]
        rows = wfs(f"{field} IN ({','.join(str(int(v)) for v in chunk)})", props)
        if len(rows) >= CAP and len(chunk) > 1:  # possibly truncated: split
            rows = wfs_in(field, chunk, props, max(1, len(chunk) // 4))
        out += rows
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=500)
    args = ap.parse_args()
    today = dt.date.today().isoformat()
    d = load(DATA / "RouteLink_CONUS.nc")
    ds, indeg, up_order, up_ptr, _ = graph(d["link"], d["to"])
    net, depth, _, _ = traverse(ds, indeg, up_order, up_ptr, d["length_m"])
    size = np.ones(ds.size, np.int64)  # subtree sizes, deepest level first
    order = np.argsort(-depth, kind="stable")
    for idx in np.split(order, np.flatnonzero(np.diff(depth[order])) + 1):
        if depth[idx[0]] > 0:
            np.add.at(size, ds[idx], size[idx])
    id2i = pd.Series(np.arange(ds.size), index=d["link"])

    def mainstem_up(i: int, steps: int = 50) -> list[int]:
        path = [i]
        for _ in range(steps):
            ups = up_order[up_ptr[i]:up_ptr[i + 1]]
            if ups.size == 0:
                break
            i = int(ups[np.argmax(size[ups])])
            path.append(i)
        return path

    nets = pd.read_csv(RESULTS / "networks_CONUS.csv")
    fids = [int(f) for f in nets["outlet_feature_id"].head(args.top)]
    print(f"outlet attributes for {len(fids)} networks")
    attrs = {r["comid"]: r for r in wfs_in("comid", fids, PROPS, 100)}
    used: dict[int, tuple[dict, int]] = {}
    for fid in fids:
        if fid in attrs:
            used[fid] = (attrs[fid], 0)
            continue
        path = [int(d["link"][j]) for j in mainstem_up(int(id2i[fid]))]
        rows = {r["comid"]: r for r in wfs_in("comid", path, PROPS, 51)}
        hit = next(((rows[c], s) for s, c in enumerate(path) if c in rows), None)
        if hit:
            used[fid] = hit
    lps = sorted({int(r["levelpathi"]) for r, _ in used.values()})
    print(f"names along {len(lps)} level paths")
    lprows = collections.defaultdict(list)
    for r in wfs_in("levelpathi", lps, "comid,gnis_name,hydroseq,levelpathi", 20):
        lprows[int(r["levelpathi"])].append(r)
    dn = sorted({int(r["dnhydroseq"]) for r, s in used.values() if s == 0 and r["dnhydroseq"]})
    print(f"downstream features for {len(dn)} outlets")
    dnrows = {int(r["hydroseq"]): r for r in wfs_in("hydroseq", dn, "comid,hydroseq,ftype,gnis_name", 100)}

    names = {}
    for fid in fids:
        i = int(id2i[fid])
        rec = {"outlet_feature_id": fid, "lat": round(float(d["lat"][i]), 4),
               "lon": round(float(d["lon"][i]), 4), "checked": today}
        if fid not in used:
            rec.update(name="UNVERIFIED", outlet_in_nhdplus_v2=False,
                       source="no COMID within 50 RouteLink mainstem segments found in NHDPlus V2")
            names[str(fid)] = rec
            continue
        hit, steps = used[fid]
        lp = int(hit["levelpathi"])
        rows = sorted(lprows[lp], key=lambda r: r["hydroseq"])
        cnt = collections.Counter(r["gnis_name"].strip() for r in rows)
        named = [(n, c) for n, c in cnt.most_common() if n]
        first = next((r["gnis_name"].strip() for r in rows if r["gnis_name"].strip()), None)
        dnf = dnrows.get(int(hit["dnhydroseq"] or 0)) if steps == 0 else None
        rec.update(
            outlet_in_nhdplus_v2=steps == 0, nhdplus_comid_used=int(hit["comid"]), mainstem_steps_up=steps,
            nhdplus_outlet_gnis_name=hit["gnis_name"].strip() or None,
            nhdplus_levelpathi=lp, levelpath_flowlines=len(rows),
            levelpath_gnis_counts=dict(cnt.most_common(4)),
            nhdplus_terminalfl=hit["terminalfl"], nhdplus_dnhydroseq=hit["dnhydroseq"],
            nhdplus_downstream_ftype=dnf["ftype"] if dnf else None,
            nhdplus_totdasqkm=hit["totdasqkm"], nhdplus_vpuid=hit["vpuid"],
            name=first or "UNVERIFIED", mainstem_name=named[0][0] if named else None,
            source=(f"NHDPlus V2 GNIS_NAME on level path {lp} (USGS geoserver wmadata:nhdflowline_network, "
                    f"{today})") if named else f"level path {lp} has no GNIS_NAME ({today})",
        )
        names[str(fid)] = rec
    for k, fid in enumerate(fids[:25]):
        print(f"{k + 1:>4} {fid:>11} {names[str(fid)]['name']} / {names[str(fid)].get('mainstem_name')}")

    cont = {}
    for fid in CONTINUITY:
        feats = get(NLDI.format(fid))["features"]
        cont[str(fid)] = {
            "source": NLDI.format(fid), "checked": today,
            "_mainstem_columns": ["comid", "lat_first_vertex", "lon_first_vertex"],
            "mainstem": [[int(f["properties"]["nhdplus_comid"]), round(f["geometry"]["coordinates"][0][1], 4),
                          round(f["geometry"]["coordinates"][0][0], 4)] for f in feats],
        }
        print(f"UM {fid}: {len(feats)} flowlines")
    tribs = {}
    for fid, lst in TRIBUTARIES.items():
        for name, vpu in lst:
            # (a CQL "AND" in the URL is refused with HTTP 403 by the service; filter VPU here)
            rows = [r for r in wfs(f"gnis_name='{name}'", "comid,gnis_name,hydroseq,terminalpa,vpuid")
                    if r["vpuid"] == vpu]
            low = min(rows, key=lambda r: r["hydroseq"])
            tribs[f"{fid}:{name}"] = {
                "outlet_feature_id": fid, "gnis_name": name, "vpuid": vpu, "checked": today,
                "downstream_most_comid": int(low["comid"]),
                "nhdplus_terminalpa": sorted({int(r["terminalpa"]) for r in rows}),
                "source": f"USGS geoserver wmadata:nhdflowline_network, gnis_name='{name}', vpuid == '{vpu}'",
                "comids_downstream_first": [int(r["comid"]) for r in sorted(rows, key=lambda r: r["hydroseq"])],
            }
            print(f"trib {name}: {len(rows)} flowlines, downstream-most {low['comid']}")
    out = {"_about": __doc__, "generated": today, "top": args.top, "names": names,
           "mainstem_continuity": cont, "tributaries": tribs}
    (HERE / "river_names.json").write_text(json.dumps(out, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
