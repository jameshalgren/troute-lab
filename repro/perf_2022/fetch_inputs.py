"""Fetch the public inputs for repro/perf_2022 into data/ (gitignored).

AI-written (Claude, 2026-11-04); not yet reviewed by the author. Tested only on the
small cases named in README.md ("What was tested").

Subcommands
-----------
routelink
    NWM v2.1 CONUS RouteLink (2,776,738 links) from the public HydroShare copy
    (resource 0a596929a3e5411bb0032a8de35e5089, the file deployed in nwm.v2.2.0), SHA-256
    checked (same file and hash as ../network_stats/fetch_data.py).
    -> data/static/RouteLink_CONUS_v2.1.nc

forcing START END [--mode slim|full] [--mask CSV] [--no-conus] [--workers N]
    Hourly CHRTOUT files of the NWM v2.1 retrospective (AWS Open Data,
    s3://noaa-nwm-retrospective-2-1-pds/model_output/YYYY/YYYYMMDDHHMM.CHRTOUT_DOMAIN1.comp,
    anonymous HTTPS), valid from START+1h through END inclusive. This is what both
    t-route builds read for a run that starts at START: a6efbf4e's build_forcing_sets()
    asks for t0 + 1 h, t0 + 2 h, ... (YYYYMMDDHHMM.CHRTOUT_DOMAIN1, no `.comp`).
      --mode slim (default): HTTP range reads of only feature_id, qSfcLatRunoff and
          qBucket (about 7 MB transferred per hour instead of about 47 MB). The packed
          int32 values and their attributes (scale_factor, _FillValue, ...) and all
          global attributes are copied unchanged, so t-route computes exactly the same
          lateral inflow (qSfcLatRunoff + qBucket, preferred since t-route #525) as from
          the original file. Written to data/forcing/conus_slim/.
      --mode full: the whole file (about 47.6 MB; 417.4 GB for calendar 2018), saved
          without the `.comp` suffix. Needed only for the WRF-Hydro reference run.
          Written to data/forcing/conus_full/.
      --mask CSV (from make_mask.py; repeatable): also write subset files holding only
          the masked feature_ids, in data/forcing/<CSV stem>/. With --no-conus the CONUS
          slim files are not kept (subsets only). One pass over the year can thus write
          the CONUS slim files and every subdomain at once.
    The S3 listing (key, size, ETag, LastModified) for every year touched is saved as
    data/forcing/s3_listing_<year>.json and each written file is logged with its
    source ETag in <dir>/manifest.jsonl. Idempotent: files already logged are skipped.

warmstart T0
    `streamflow` at T0 from the CHRTOUT valid at T0 (range read), as
    data/warmstart/<T0>.csv (feature_id, qu0, qd0, h0) with qu0 = qd0 = streamflow and
    h0 = 0. Convert it into a t-route "lite" restart with to_lite_restart.py, run by the
    Python of the build that will read it (pickle compatibility).

Times are UTC, format YYYY-MM-DD_HH (e.g. 2018-01-01_00).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
# PERF2022_DATA moves the (large) data directory, e.g. to a scratch disk.
DATA = Path(os.environ.get("PERF2022_DATA", HERE / "data")).resolve()
BUCKET = "noaa-nwm-retrospective-2-1-pds"
BASE = f"https://{BUCKET}.s3.amazonaws.com"

ROUTELINK = {
    "url": "https://www.hydroshare.org/resource/0a596929a3e5411bb0032a8de35e5089/data/contents/RouteLink_CONUS.nc",
    "sha256": "1b95f69aa8efcb48a1bd4a28136fabc6a59a5bda87de70f19bb0d453ace1d193",
    "size": 269366417,
    "dest": DATA / "static" / "RouteLink_CONUS_v2.1.nc",
}
SLIM_VARS = ("qSfcLatRunoff", "qBucket")
# HDF5/netCDF bookkeeping attributes that must not be copied as user attributes.
SKIP_ATTRS = {"DIMENSION_LIST", "REFERENCE_LIST", "CLASS", "NAME", "_Netcdf4Dimid",
              "_Netcdf4Coordinates", "_nc3_strict", "_NCProperties", "_FillValue"}
UA = {"User-Agent": "troute-paper-repro-perf2022/0.1"}


# --------------------------------------------------------------------------- helpers
def http_get(url: str, timeout: int = 120, tries: int = 6) -> bytes:
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 (network errors of every kind are retried)
            if k == tries - 1:
                raise
            print(f"retry   {url} ({e})", file=sys.stderr)
            time.sleep(5 * (k + 1))
    raise RuntimeError("unreachable")


def rel(p: Path) -> Path:
    try:
        return p.relative_to(HERE)
    except ValueError:
        return p


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def parse_time(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d_%H").replace(tzinfo=timezone.utc)


def stamp(t: datetime) -> str:
    return t.strftime("%Y%m%d%H%M")


def key_for(t: datetime) -> str:
    return f"model_output/{t.year}/{stamp(t)}.CHRTOUT_DOMAIN1.comp"


def s3_listing(year: int) -> dict:
    """{key: {size, etag, last_modified}} for every CHRTOUT of one year (cached on disk)."""
    cache = DATA / "forcing" / f"s3_listing_{year}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    out, token = {}, None
    while True:
        q = {"list-type": "2", "prefix": f"model_output/{year}/", "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        x = http_get(f"{BASE}/?" + urllib.parse.urlencode(q)).decode()
        for blk in re.findall(r"<Contents>(.*?)</Contents>", x, flags=re.S):
            k = re.search(r"<Key>([^<]+)</Key>", blk).group(1)
            if "CHRTOUT_DOMAIN1" not in k:
                continue
            out[k] = {"size": int(re.search(r"<Size>(\d+)</Size>", blk).group(1)),
                      "etag": re.search(r"<ETag>([^<]+)</ETag>", blk).group(1).replace("&quot;", "").strip('"'),
                      "last_modified": re.search(r"<LastModified>([^<]+)</LastModified>", blk).group(1)}
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", x)
        if not m:
            break
        token = m.group(1)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out, indent=0, sort_keys=True))
    return out


def open_remote(url: str):
    import fsspec  # noqa: PLC0415
    fs = fsspec.filesystem("http", headers=UA)
    return fs.open(url, "rb", block_size=1 << 20, cache_type="blockcache")


def h5_read(url: str, names: tuple[str, ...]) -> tuple[dict, dict, dict]:
    """Raw (still packed) arrays, their attributes, and the file's global attributes."""
    import h5py  # noqa: PLC0415
    for k in range(6):
        try:
            with open_remote(url) as fo, h5py.File(fo, "r") as f:
                arrs = {n: f[n][()] for n in names}
                vattrs = {n: {a: f[n].attrs[a] for a in f[n].attrs if a not in SKIP_ATTRS} for n in names}
                fill = {n: f[n].attrs["_FillValue"] for n in names if "_FillValue" in f[n].attrs}
                for n, v in fill.items():
                    vattrs[n]["__fill__"] = v
                gattrs = {a: f.attrs[a] for a in f.attrs if not a.startswith("_")}
            return arrs, vattrs, gattrs
        except Exception as e:  # noqa: BLE001
            if k == 5:
                raise
            print(f"retry   {url} ({e})", file=sys.stderr)
            time.sleep(5 * (k + 1))
    raise RuntimeError("unreachable")


def _attr(v):
    if isinstance(v, bytes):
        return v.decode()
    if isinstance(v, np.ndarray) and v.dtype.kind == "S":
        return v.astype(str).tolist()
    if isinstance(v, np.ndarray) and v.size == 1:
        return v.reshape(())[()]
    return v


def write_slim(path: Path, arrs: dict, vattrs: dict, gattrs: dict, rows: np.ndarray | None) -> None:
    """netCDF4 file with feature_id + the packed lateral-inflow variables (+ time)."""
    import netCDF4  # noqa: PLC0415
    tmp = path.parent / (path.name + ".part")
    fid = arrs["feature_id"] if rows is None else arrs["feature_id"][rows]
    with netCDF4.Dataset(tmp, "w", format="NETCDF4") as ds:
        ds.createDimension("feature_id", len(fid))
        ds.createDimension("time", 1)
        ds.createDimension("reference_time", 1)
        for name, dim in (("time", "time"), ("reference_time", "reference_time")):
            v = ds.createVariable(name, arrs[name].dtype, (dim,))
            v.setncatts({a: _attr(x) for a, x in vattrs[name].items() if not a.startswith("__")})
            v[:] = arrs[name]
        for name in ("feature_id",) + SLIM_VARS:
            a = arrs[name] if rows is None else arrs[name][rows]
            fill = vattrs[name].get("__fill__")
            v = ds.createVariable(name, a.dtype, ("feature_id",), zlib=True, complevel=2,
                                  fill_value=None if fill is None else np.asarray(fill).reshape(())[()])
            v.set_auto_maskandscale(False)  # write the packed integers exactly as stored
            v.setncatts({k: _attr(x) for k, x in vattrs[name].items() if not k.startswith("__")})
            v[:] = a
        ds.setncatts({k: _attr(x) for k, x in gattrs.items()})
        ds.setncattr("perf2022_note", "subset of the NWM v2.1 retrospective CHRTOUT (variables "
                     "feature_id, qSfcLatRunoff, qBucket, time, reference_time; values unchanged) "
                     "written by repro/perf_2022/fetch_inputs.py")
    tmp.replace(path)


SLIM_READ = ("feature_id", "time", "reference_time") + SLIM_VARS


def _full_worker(url: str, dest: str, size: int, etag: str) -> None:
    """Process-pool worker: one whole CHRTOUT file, written as <dest>.part then renamed.
    Size is checked against the S3 listing, and so is the MD5 when the ETag is a plain MD5
    (single-part upload: 32 hex digits, no '-')."""
    p = Path(dest)
    part = p.parent / (p.name + ".part")
    blob = http_get(url, timeout=600)
    if len(blob) != size:
        raise RuntimeError(f"size mismatch for {url}")
    if re.fullmatch(r"[0-9a-f]{32}", etag) and hashlib.md5(blob).hexdigest() != etag:
        raise RuntimeError(f"MD5 does not match the S3 ETag for {url}")
    part.write_bytes(blob)
    part.replace(p)


# --------------------------------------------------------------------------- commands
def cmd_routelink(_args) -> int:
    d = ROUTELINK["dest"]
    if d.exists() and sha256(d) == ROUTELINK["sha256"]:
        print(f"ok      {rel(d)} (sha256 verified)")
        return 0
    d.parent.mkdir(parents=True, exist_ok=True)
    print(f"fetch   {ROUTELINK['url']} (269 MB)")
    tmp = d.with_suffix(".part")
    tmp.write_bytes(http_get(ROUTELINK["url"], timeout=600))
    got = sha256(tmp)
    if got != ROUTELINK["sha256"]:
        tmp.unlink()
        sys.exit(f"ERROR: SHA-256 mismatch for RouteLink v2.1: {got}")
    tmp.replace(d)
    print(f"ok      {rel(d)}")
    return 0


class Manifest:
    def __init__(self, path: Path):
        self.path, self.lock = path, threading.Lock()
        self.done = set()
        if path.exists():
            for ln in path.read_text().splitlines():
                if ln.strip():
                    self.done.add(json.loads(ln)["file"])

    def add(self, rec: dict) -> None:
        with self.lock, open(self.path, "a") as f:
            f.write(json.dumps(rec) + "\n")
            self.done.add(rec["file"])


def cmd_forcing(args) -> int:
    t0, t1 = parse_time(args.start), parse_time(args.end)
    times = []
    t = t0 + timedelta(hours=1)
    while t <= t1:
        times.append(t)
        t += timedelta(hours=1)
    if not times:
        sys.exit("ERROR: END must be after START")
    listing = {}
    for y in sorted({t.year for t in times}):
        listing.update(s3_listing(y))
    missing = [key_for(t) for t in times if key_for(t) not in listing]
    if missing:
        sys.exit(f"ERROR: {len(missing)} files missing in s3://{BUCKET}, first {missing[0]}")
    nbytes = sum(listing[key_for(t)]["size"] for t in times)
    print(f"plan    {len(times)} hourly files {stamp(times[0])}..{stamp(times[-1])}; full size "
          f"{nbytes / 1e9:.1f} GB; mode {args.mode}")

    masks = {Path(m).stem: np.loadtxt(m, dtype=np.int64, ndmin=1) for m in (args.mask or [])}
    outdirs = {}
    if args.mode == "full":
        outdirs["conus"] = DATA / "forcing" / "conus_full"
    elif not args.no_conus:
        outdirs["conus"] = DATA / "forcing" / "conus_slim"
    for name in masks:
        outdirs[name] = DATA / "forcing" / name
    if not outdirs:
        sys.exit("ERROR: nothing to write (--no-conus without --mask)")
    mans = {}
    for k, d in outdirs.items():
        d.mkdir(parents=True, exist_ok=True)
        mans[k] = Manifest(d / "manifest.jsonl")

    # Work runs in processes, not threads: h5py serializes all calls behind one global
    # lock, so threaded range reads do not overlap (measured 2026-11-04: 16 threads gave
    # about one file per 3.8 s). netCDF files are written by this (main) process only;
    # netCDF-C/HDF5 print spurious error stacks when files are created off the main thread.
    jobs = {}
    with cf.ProcessPoolExecutor(max_workers=args.workers) as ex:
        for t in times:
            key, name = key_for(t), f"{stamp(t)}.CHRTOUT_DOMAIN1"
            todo = {k: d / name for k, d in outdirs.items() if name not in mans[k].done}
            if args.mode == "full" and "conus" in todo:
                jobs[ex.submit(_full_worker, f"{BASE}/{key}", str(todo.pop("conus")), listing[key]["size"],
                                     listing[key]["etag"])] = \
                    (name, key, {"conus": None})
            if todo:
                jobs[ex.submit(h5_read, f"{BASE}/{key}", SLIM_READ)] = (name, key, todo)
        t_start, n = time.time(), 0
        for fut in cf.as_completed(jobs):
            name, key, todo = jobs[fut]
            got = fut.result()
            src = listing[key]
            if "conus" in todo and todo["conus"] is None:      # full file already written
                mans["conus"].add({"file": name, "key": key, **src})
            else:
                arrs, vattrs, gattrs = got
                for k, p in todo.items():
                    rows = None if k == "conus" else np.flatnonzero(np.isin(arrs["feature_id"], masks[k]))
                    write_slim(p, arrs, vattrs, gattrs, rows)
                    mans[k].add({"file": name, "key": key, **src,
                                 "rows": int(len(arrs["feature_id"]) if rows is None else len(rows)),
                                 "sha256": sha256(p)})
            n += 1
            if n % 24 == 0 or n == len(jobs):
                rate = n / max(time.time() - t_start, 1e-9)
                print(f"        {n}/{len(jobs)} downloads ({rate * 3600:.0f}/h)", flush=True)
    import netCDF4  # noqa: PLC0415
    for k, mask in masks.items():
        # every masked segment must have a row, or t-route's qlats.loc[...] fails
        with netCDF4.Dataset(outdirs[k] / f"{stamp(times[0])}.CHRTOUT_DOMAIN1") as ds:
            got = set(ds["feature_id"][:].tolist())
        lost = set(mask.tolist()) - got
        if lost:
            print(f"WARNING {k}: {len(lost)} masked ids have no CHRTOUT row (e.g. {sorted(lost)[:5]})")
    print(f"ok      forcing in {', '.join(str(rel(d)) for d in outdirs.values())}")
    return 0


def cmd_warmstart(args) -> int:
    t = parse_time(args.t0)
    key = key_for(t)
    arrs, vattrs, _ = h5_read(f"{BASE}/{key}", ("feature_id", "streamflow"))
    raw = arrs["streamflow"].astype(np.int64)
    fill = int(np.asarray(vattrs["streamflow"].get("__fill__", -999900)).reshape(()))
    sf = float(np.asarray(vattrs["streamflow"].get("scale_factor", 1.0)).reshape(()))
    off = float(np.asarray(vattrs["streamflow"].get("add_offset", 0.0)).reshape(()))
    q = np.where(raw == fill, 0.0, raw * sf + off).astype(np.float32)
    out = DATA / "warmstart" / f"{stamp(t)}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write(f"# streamflow valid {t:%Y-%m-%d_%H:%M} from s3://{BUCKET}/{key}\n")
        f.write("feature_id,qu0,qd0,h0\n")
        for i, v in zip(arrs["feature_id"].tolist(), q.tolist()):
            f.write(f"{i},{v:.6g},{v:.6g},0\n")
    print(f"ok      {rel(out)} ({len(q)} segments, sum {q.sum():.0f} m3/s)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("routelink")
    f = sub.add_parser("forcing")
    f.add_argument("start", help="run start t0, YYYY-MM-DD_HH (first file is t0 + 1 h)")
    f.add_argument("end", help="last valid time, YYYY-MM-DD_HH (inclusive)")
    f.add_argument("--mode", choices=["slim", "full"], default="slim")
    f.add_argument("--mask", action="append", help="CSV of feature_ids (make_mask.py) for subset "
                   "files in data/forcing/<CSV stem>/; repeat for several domains in one pass")
    f.add_argument("--no-conus", action="store_true", help="with --mask: keep only the subset files")
    f.add_argument("--workers", type=int, default=16)
    w = sub.add_parser("warmstart")
    w.add_argument("t0", help="YYYY-MM-DD_HH")
    args = ap.parse_args()
    return {"routelink": cmd_routelink, "forcing": cmd_forcing, "warmstart": cmd_warmstart}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
