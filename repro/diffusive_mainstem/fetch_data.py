"""Download every input into data/ and verify its SHA-256.

Idempotent: a file already present with the expected hash is not downloaded again.
Fails (exit 1) with an explanation if a URL is gone or the content has changed, except for
the live USACE eHydro service (see below).

    uv run python fetch_data.py            # everything
    uv run python fetch_data.py --verify   # verify only, never download

Inputs (sources, versions, licences: README.md "Sources"):
  RouteLink_{CONUS,AK,HI,PRVI}.nc  NWM v3.1.6 (NCEP), same URLs/hashes as ../network_stats;
                                   a verified sibling copy is hard-linked if present
  nhdplusVAA.parquet               NHDPlusV2 value-added attributes as packaged for
                                   nhdplusTools (HydroShare 6092c8a62fac45be97a09bfd0b0bf726)
  erom/*.7z                        NHDPlusV2.1 EROM extension, 21 CONUS VPUs (EPA S3)
  physio/physio_shp.zip            USGS physiographic divisions (Fenneman & Johnson 1946)
  nwn/nwn_lines.geojson            BTS NTAD / USACE National Waterway Network lines,
                                   ArcGIS FeatureServer, paged, written deterministically
  ehydro/ehydro_outlines.geojson   USACE eHydro SurveyJob outlines (LIVE service; filtered to
                                   surveys starting on or before EHYDRO_CUTOFF; a changed hash
                                   is reported as a warning, not an error)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
NCEP = "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.6/parm"
EPA = "https://dmap-data-commons-ow.s3.amazonaws.com/NHDPlusV21/Data"
UA = {"User-Agent": "troute-paper-repro/1.0"}

# relative path: (url, sha256, size); hashes observed on the dates noted
FILES = {
    # NWM v3.1.6, observed 2026-09-30 (identical to ../network_stats/fetch_data.py)
    "RouteLink_CONUS.nc": (f"{NCEP}/domain/RouteLink_CONUS.nc",
                           "4957655896f4f27854f893d02fa084f9f79c1cf8e80ce77565a7356dadb6fc0e", 269369766),
    "RouteLink_AK.nc": (f"{NCEP}/domain_alaska/RouteLink_AK.nc",
                        "d27384e77303e9a61ee1f059775a4904d1c54727d717f2d81249721533ecc793", 47399233),
    "RouteLink_HI.nc": (f"{NCEP}/domain_hawaii/RouteLink_HI.nc",
                        "9e4ae9de3a6ec9dfabfa774c3acc4c185f675086aac366439f4c7dcb1df19a34", 1346576),
    "RouteLink_PRVI.nc": (f"{NCEP}/domain_puertorico/RouteLink_PRVI.nc",
                          "f72ab05cc810cc9498ca7f26fd5097292c5bc4020a10fb83c27b273848a04447", 1380709),
    # HydroShare resource 6092c8a62fac45be97a09bfd0b0bf726 (file modified 2021-02-26; HydroShare
    # MD5 5691af50ffc1c1d66960a9dae690dc6e); observed 2026-10-08
    "nhdplusVAA.parquet": ("https://www.hydroshare.org/resource/6092c8a62fac45be97a09bfd0b0bf726/data/contents/nhdplusVAA.parquet",
                           "33f2bfdd2b6d99e73e1f4b77b2680fb23271dd33cc3b66336a44949ebc58f4d7", 257747436),
    # USGS, Fenneman & Johnson (1946), doi:10.5066/P9B1S3K8; Last-Modified 27 Feb 2015; observed 2026-10-08
    "physio/physio_shp.zip": ("https://water.usgs.gov/GIS/dsdl/physio_shp.zip",
                              "3fd988563ed3ac2d5cb5c14ed8f7d729946049fa07674de90383e7ec1f143f9c", 451315),
}
# NHDPlusV2.1 EROM extension per VPU (S3 LastModified 2022-12-16); observed 2026-10-08
EROM = {
    "NHDPlusCA/NHDPlusV21_CA_18_EROMExtension_07.7z": ("5f83fcebab23ab9102aa538c02189618f070fc28f025ed38ce4ea8ef11026711", 67138094),
    "NHDPlusCO/NHDPlus14/NHDPlusV21_CO_14_EROMExtension_05.7z": ("5f3e0a87af8c36a13c2ca9643f15ea4e33465013fccb24ce3fcc45dc37dd1caf", 37134718),
    "NHDPlusCO/NHDPlus15/NHDPlusV21_CO_15_EROMExtension_07.7z": ("e04e6824c834953eb931c2cc6e584bf17cea6c23f9ab97f7d38b3dc93513ac18", 45162587),
    "NHDPlusGB/NHDPlusV21_GB_16_EROMExtension_04.7z": ("9bb352cb373a8bed730fb0a46c7dc8e2a3d058fa52b8aa55937dc743eb111533", 41360748),
    "NHDPlusGL/NHDPlusV21_GL_04_EROMExtension_11.7z": ("511f25dbfa661f0dbe2a090e5e67da07f4c5cf63ac6d9edc6495bb18af248790", 54066085),
    "NHDPlusMA/NHDPlusV21_MA_02_EROMExtension_06.7z": ("d51b4e780bb6fbd8332a59fedae3f4fa88ceefd31cf77409514f8e974360274e", 64699119),
    "NHDPlusMS/NHDPlus05/NHDPlusV21_MS_05_EROMExtension_06.7z": ("1ad175e4f2e1248f7064e12603e5984669bea5d107b06871e0dfe37980b853f7", 87402302),
    "NHDPlusMS/NHDPlus06/NHDPlusV21_MS_06_EROMExtension_07.7z": ("4c084861a7c916d1de498968b5178f9c447b9e1be1fd33e32c963702eae39709", 28787821),
    "NHDPlusMS/NHDPlus07/NHDPlusV21_MS_07_EROMExtension_07.7z": ("544d53ccb84bd4b6fe4b0f6847f7ced818f7a1bee8f207eba027a22921c7c27b", 96436124),
    "NHDPlusMS/NHDPlus08/NHDPlusV21_MS_08_EROMExtension_06.7z": ("369dfdbebe9422214959cd1c1ba30f7fa11389ed95dfa245dc2953cbcddb09ae", 73221052),
    "NHDPlusMS/NHDPlus10L/NHDPlusV21_MS_10L_EROMExtension_08.7z": ("d47040fe6f890608dbd49ada20ddae59d0e713f0e7251ffad6b10475242e40e5", 101998136),
    "NHDPlusMS/NHDPlus10U/NHDPlusV21_MS_10U_EROMExtension_07.7z": ("eddd4c30b9107c6ebd69fca0ef24191b19b17ad487e3b812b714c39940638bdd", 133388801),
    "NHDPlusMS/NHDPlus11/NHDPlusV21_MS_11_EROMExtension_04.7z": ("78bdc0f59f9fa5a6d2f9a02d377c97205b627c76e326e6410b1aac930a7d136c", 100303219),
    "NHDPlusNE/NHDPlusV21_NE_01_EROMExtension_06.7z": ("051e96fa299bfa42d41fa36b1c63ace64f0de9e43041cd702526fe61835129aa", 34260446),
    "NHDPlusPN/NHDPlusV21_PN_17_EROMExtension_09.7z": ("e720e686da757dd58f0011bf002f70d15c282f2ae4896fe36b743718d46b210d", 111303747),
    "NHDPlusRG/NHDPlusV21_RG_13_EROMExtension_05.7z": ("1c9219129d229869bd8c522870b9a220ee2a029728bc95a70cc86b92f6f0885b", 25376277),
    "NHDPlusSA/NHDPlus03N/NHDPlusV21_SA_03N_EROMExtension_05.7z": ("1e88edeed915d3d217700ef6eb7c6a973cd261fd0036f8d7acc69014aea531a7", 64548309),
    "NHDPlusSA/NHDPlus03S/NHDPlusV21_SA_03S_EROMExtension_05.7z": ("def819a60dc6cc5c4ee165d57a3ee74e5827ae043822f05cbd06566c994d9442", 26944487),
    "NHDPlusSA/NHDPlus03W/NHDPlusV21_SA_03W_EROMExtension_05.7z": ("a12dc2a00c4592bed236ad6d8c7269315e4bd292caea209e9d121a5047454b07", 66802417),
    "NHDPlusSR/NHDPlusV21_SR_09_EROMExtension_05.7z": ("fa3a0eaeeff8aaf14daf277ab3caa15584e8ad8ae21855dc121d26267e78d98f", 12191862),
    "NHDPlusTX/NHDPlusV21_TX_12_EROMExtension_06.7z": ("a55bb1f146f537d98e3d276a0fefad58ab40b12a860155d400d63a057e015147", 35186220),
}
for key, (h, s) in EROM.items():
    FILES[f"erom/{Path(key).name}"] = (f"{EPA}/{key}", h, s)

# ArcGIS FeatureServer layers, paged by OBJECTID and written deterministically
NWN_URL = "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/ArcGIS/rest/services/Waterway_Networks/FeatureServer/1/query"
NWN_FIELDS = "OBJECTID,LINKNUM,RIVERNAME,WATERWAY,WTWY_TYPE,FUNC_CLASS,GEO_CLASS,STATE,NON_US"
NWN_SHA = "d799e4bad8e55b677d272e75617c1c06722becbd8f969f05ad576a8935555cd5"                # observed 2026-10-08 (layer dataLastEditDate 2025-09-30)
EHYDRO_URL = "https://services7.arcgis.com/n1YM8pTrFmm7L4hs/arcgis/rest/services/eHydro_Survey_Data/FeatureServer/0/query"
EHYDRO_FIELDS = "OBJECTID,surveytype,surveydatestart,usacedistrictcode,channelareaidfk"
EHYDRO_CUTOFF = "2026-10-08"
EHYDRO_SHA = "f7e5b7dccd354b7d717f062d7d43f1e856d88ba3a03c84c50f388c4de2c5a786"             # observed 2026-10-08 (live service; drift = warning)
SIBLINGS = [HERE.parent / "network_stats" / "data", HERE.parent / "routelink_topwidth" / "data"]

MOVED_HELP = """\
If a source has moved, obtain the exact file (matching the SHA-256 above) and place it in data/.
NCEP keeps only operational NWM versions under /pmb/codes/nwprod/; EPA's NHDPlusV2 data are
mirrored at https://www.epa.gov/waterdata/get-nhdplus-national-hydrography-dataset-plus-data."""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(1 << 20):
            h.update(b)
    return h.hexdigest()


def get(url: str, timeout: int = 300) -> bytes:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 3:
                sys.exit(f"ERROR: {url}: {e}\n{MOVED_HELP}")
            time.sleep(5 * (attempt + 1))
    raise AssertionError


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"ERROR: {url} returned HTTP {e.code}.\n{MOVED_HELP}")
    except urllib.error.URLError as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"ERROR: could not reach {url}: {e.reason}")
    tmp.replace(dest)


def arcgis_layer(url: str, fields: str, where: str, offset_deg: float | None) -> dict:
    """All features of an ArcGIS FeatureServer layer as one GeoJSON FeatureCollection,
    ordered by OBJECTID, geometry in EPSG:4326 at 1e-6 degree precision."""
    feats, off = [], 0
    while True:
        q = {"where": where, "outFields": fields, "orderByFields": "OBJECTID", "resultOffset": off,
             "resultRecordCount": 2000, "outSR": 4326, "geometryPrecision": 6, "f": "geojson"}
        if offset_deg:
            q["maxAllowableOffset"] = offset_deg
        d = json.loads(get(url + "?" + urllib.parse.urlencode(q)))
        if "error" in d:
            sys.exit(f"ERROR: {url}: {d['error']}")
        feats += d["features"]
        print(f"\r  {len(feats):,} features", end="", flush=True)
        if not d.get("properties", {}).get("exceededTransferLimit") and len(d["features"]) < 2000:
            break
        off += len(d["features"])
    print()
    feats.sort(key=lambda f: f["properties"]["OBJECTID"])
    return {"type": "FeatureCollection", "features": feats}


def write_json(obj: dict, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    b = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    dest.write_bytes(b)
    return hashlib.sha256(b).hexdigest()


def fetch_file(name: str, url: str, want: str, verify: bool) -> str | None:
    dest = DATA / name
    if dest.exists() and sha256(dest) == want:
        print(f"ok      {name} (sha256 verified)")
        return None
    if verify:
        return f"{name}: missing or wrong hash"
    if name.startswith("RouteLink_"):
        for sib in SIBLINGS:
            s = sib / name
            if s.exists() and sha256(s) == want:
                dest.unlink(missing_ok=True)
                try:
                    os.link(s, dest)
                except OSError:
                    shutil.copy2(s, dest)
                print(f"ok      {name} (from sibling experiment, sha256 verified)")
                return None
    print(f"fetch   {url}")
    download(url, dest)
    got = sha256(dest)
    if got != want:
        return f"{name}: sha256 {got} != expected {want} (the file at the URL has changed)"
    print(f"ok      {name} (downloaded, sha256 verified)")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    bad = [e for n, (u, h, _) in FILES.items() if (e := fetch_file(n, u, h, args.verify))]
    # unzip the physiographic shapefile
    z = DATA / "physio" / "physio_shp.zip"
    if z.exists() and not (DATA / "physio" / "physio.shp").exists():
        with zipfile.ZipFile(z) as zf:
            zf.extractall(DATA / "physio")
    # NWN
    nwn = DATA / "nwn" / "nwn_lines.geojson"
    if nwn.exists() and sha256(nwn) == NWN_SHA:
        print("ok      nwn/nwn_lines.geojson (sha256 verified)")
    elif args.verify:
        bad.append("nwn/nwn_lines.geojson: missing or wrong hash")
    else:
        print(f"fetch   {NWN_URL} (paged)")
        got = write_json(arcgis_layer(NWN_URL, NWN_FIELDS, "1=1", None), nwn)
        if got != NWN_SHA:
            bad.append(f"nwn/nwn_lines.geojson: sha256 {got} != expected {NWN_SHA} (the NWN has been revised; "
                       "results may differ)")
        else:
            print("ok      nwn/nwn_lines.geojson (downloaded, sha256 verified)")
    # eHydro (live)
    eh = DATA / "ehydro" / "ehydro_outlines.geojson"
    meta = DATA / "ehydro" / "ehydro_meta.json"
    if eh.exists() and meta.exists():
        got = json.loads(meta.read_text())["sha256"]
        print(f"ok      ehydro/ehydro_outlines.geojson (snapshot of {json.loads(meta.read_text())['retrieved']})")
    elif args.verify:
        bad.append("ehydro/ehydro_outlines.geojson: missing")
        got = None
    else:
        print(f"fetch   {EHYDRO_URL} (paged; surveys starting on or before {EHYDRO_CUTOFF})")
        where = f"surveydatestart <= DATE '{EHYDRO_CUTOFF}'"
        fc = arcgis_layer(EHYDRO_URL, EHYDRO_FIELDS, where, 0.0002)
        got = write_json(fc, eh)
        meta.write_text(json.dumps({"retrieved": time.strftime("%Y-%m-%d"), "cutoff": EHYDRO_CUTOFF,
                                    "features": len(fc["features"]), "sha256": got,
                                    "max_allowable_offset_deg": 0.0002, "url": EHYDRO_URL}, indent=2) + "\n")
    if got is not None and got != EHYDRO_SHA:
        print(f"WARNING ehydro: sha256 {got} differs from the 2026-10-08 snapshot ({EHYDRO_SHA}). The eHydro "
              "service is live, so records may have been added, edited or removed; eHydro-derived numbers "
              "may differ slightly from expected/ (check.py uses a loose tolerance for them).")
    if bad:
        print("\n".join(["ERROR:"] + bad + [MOVED_HELP]))
        return 1
    print("all inputs present and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
