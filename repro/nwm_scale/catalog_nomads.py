# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Catalog one NOMADS National Water Model day directory from its Apache listings.

Three steps; all use only the standard library.

  fetch: download every listing under
         https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod/<day>/ (recursing into
         post_processed/) and save each as <path with "/" -> "__">.html in LISTING_DIR.
         The listings are untrusted downloads: put them in a fresh, empty directory.

      uv run catalog_nomads.py fetch nwm.20261029 LISTING_DIR

  fetch-s3 (optional): save the S3 ListObjectsV2 pages for the same day from the NOAA Open
         Data mirror https://noaa-nwm-pds.s3.amazonaws.com/ into S3_DIR (fresh, empty). These
         give exact byte sizes.

      uv run catalog_nomads.py fetch-s3 nwm.20261029 S3_DIR

  parse: read the saved listings and write
         results/nomads_catalog.csv           one row per (directory, product, cycle group)
         results/nomads_channel_rt_cycles.csv one row per (directory, cycle) for channel_rt
         results/nomads_footprint.csv         folders, files and bytes per domain-day

      uv run --no-project python -I catalog_nomads.py parse LISTING_DIR [DAY] [S3_DIR]

The file inventory (which files exist) always comes from the NOMADS listings. Sizes: the
NOMADS listings print Apache's rounded sizes ("12M", "4.3M", "125K"; 1K = 1024 bytes), which
can be off by a few percent per file (a 12,354,018-byte CONUS channel_rt file is listed as
"12M" = 12,582,912). With S3_DIR, each file's exact size is taken from the S3 listing when
the same key exists there; the rounded NOMADS size is used otherwise, and the counts are printed.
"""
import csv, os, re, sys, time, urllib.parse, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
BASE = "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod/"
S3 = "https://noaa-nwm-pds.s3.amazonaws.com/"
S3ROW = re.compile(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", re.S)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

ROW = re.compile(r'<a href="([^"?][^"]*)">[^<]*</a>\s+(\d\d-\w{3}-\d{4} \d\d:\d\d)\s+(\S+)')
NAME = re.compile(r"^nwm\.t(?P<cyc>\d\d)z\.(?P<run>[a-z_]+)\.(?P<prod>[a-z_]+?)(?:_(?P<mem>\d+))?"
                  r"\.(?:(?P<tt>tm|f)(?P<ts>\d+)\.)?(?P<dom>[a-z]+)(?:\.[a-z]+)?\.(?P<ext>nc|shef)$")
UNIT = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}
MODEL_PRODUCTS = {"channel_rt", "land", "reservoir", "terrain_rt"}


# ---------------------------------------------------------------- fetch
def get(url, tries=4, end=b"</html>"):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read()
            if body.rstrip().endswith(end):
                return body
        except Exception as e:  # retry on any network error
            print(f"  retry {k + 1}: {url}: {e}", file=sys.stderr)
        time.sleep(2 * (k + 1))
    raise RuntimeError(f"could not fetch a complete listing: {url}")


def fetch(day, outdir):
    os.makedirs(outdir, exist_ok=True)
    log = []

    def walk(rel):
        url = BASE + day + "/" + rel
        body = get(url)
        name = (rel.rstrip("/").replace("/", "__") or "_day") + ".html"
        with open(os.path.join(outdir, name), "wb") as f:
            f.write(body)
        log.append((url, len(body), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        for href, _, _ in ROW.findall(body.decode("latin-1")):
            if href.endswith("/") and not href.startswith("/"):
                walk(rel + href)

    walk("")
    with open(os.path.join(outdir, "_fetch_log.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["url", "bytes", "fetched_utc"]); w.writerows(log)
    print(f"saved {len(log)} listings to {outdir}")


def fetch_s3(day, outdir):
    os.makedirs(outdir, exist_ok=True)
    token, page, nkeys = None, 0, 0
    while True:
        q = {"list-type": "2", "prefix": day + "/", "max-keys": "1000"}
        if token:
            q["continuation-token"] = token
        body = get(S3 + "?" + urllib.parse.urlencode(q), end=b"</ListBucketResult>")
        page += 1
        with open(os.path.join(outdir, f"s3_page_{page:04d}.xml"), "wb") as f:
            f.write(body)
        txt = body.decode("utf-8")
        nkeys += len(S3ROW.findall(txt))
        m = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", txt)
        if "<IsTruncated>true</IsTruncated>" not in txt or not m:
            break
        token = m.group(1)
    print(f"saved {page} S3 listing pages ({nkeys} keys) to {outdir}")


# ---------------------------------------------------------------- parse
def size_bytes(s):
    m = re.fullmatch(r"([\d.]+)([KMGT]?)", s)
    return float(m.group(1)) * UNIT[m.group(2)] if m else 0.0


def stamp_minutes(tt, ts):
    """tmNN / tmHHMM (look-back, negative) and fHHH / fHHHMM (lead) -> minutes from cycle time."""
    if tt == "tm":
        return -(int(ts) * 60 if len(ts) == 2 else int(ts[:2]) * 60 + int(ts[2:]))
    return int(ts) * 60 if len(ts) == 3 else int(ts[:3]) * 60 + int(ts[3:])


def domain_of(directory):
    d = directory
    if d.startswith("post_processed"):
        return "post_processed"
    if d.startswith("usgs_timeslices"):
        return "observations"
    if "coastal" in d:
        sub = d.split("coastal_")[1].split("_")[0]
        return {"atlgulf": "CONUS", "pacific": "CONUS", "hawaii": "Hawaii",
                "puertorico": "PuertoRico_USVI"}[sub]
    for key, dom in (("alaska", "Alaska"), ("hawaii", "Hawaii"), ("puertorico", "PuertoRico_USVI")):
        if key in d:
            return dom
    return "CONUS"


def family_of(directory):
    d = directory
    if d.startswith("post_processed"):
        return "post_processed"
    if d.startswith("usgs_timeslices"):
        return "usgs_timeslices"
    if d.startswith("forcing_"):
        return "forcing"
    if "coastal" in d:
        return "coastal_schism"
    return "nwm_hydro"


def fmt_cycles(cs):
    cs = sorted(cs)
    if len(cs) > 2 and cs == list(range(cs[0], cs[-1] + 1)):
        return f"{cs[0]:02d}-{cs[-1]:02d}"
    return "/".join(f"{c:02d}" for c in cs)


def label(m, kind="forecast"):
    if m < 0 or (m == 0 and kind == "analysis"):
        h, mm = divmod(-m, 60); return f"tm{h:02d}" + (f"{mm:02d}" if mm else "")
    h, mm = divmod(m, 60); return f"f{h:03d}" + (f"{mm:02d}" if mm else "")


def load_s3(s3dir):
    sizes = {}
    for fn in sorted(os.listdir(s3dir)):
        if fn.startswith("s3_page_") and fn.endswith(".xml"):
            txt = open(os.path.join(s3dir, fn), encoding="utf-8").read()
            if not txt.rstrip().endswith("</ListBucketResult>"):
                sys.exit(f"incomplete S3 page: {fn}")
            for key, size in S3ROW.findall(txt):
                sizes[key] = int(size)
    return sizes


def parse(listdir, day, s3dir=None):
    files = []  # (directory, name, bytes, exact)
    for fn in sorted(os.listdir(listdir)):
        if not fn.endswith(".html") or fn == "_day.html":
            continue
        directory = fn[:-5].replace("__", "/")
        txt = open(os.path.join(listdir, fn), encoding="latin-1").read()
        if not txt.rstrip().endswith("</html>"):
            sys.exit(f"incomplete listing: {fn}")
        for href, _, size in ROW.findall(txt):
            if href.endswith("/"):
                continue
            files.append((directory, href[2:] if href.startswith("./") else href, size_bytes(size), False))

    if s3dir:
        s3 = load_s3(s3dir)
        seen, out = set(), []
        for directory, name, b, _ in files:
            key = f"{day}/{directory}/{name}"
            if key not in s3 and f"{day}/{directory}/./{name}" in s3:  # usgs_timeslices keys keep "./"
                key = f"{day}/{directory}/./{name}"
            seen.add(key)
            out.append((directory, name, s3[key], True) if key in s3 else (directory, name, b, False))
        files = out
        nex = sum(f[3] for f in files)
        extra = defaultdict(int)
        for k in s3:
            if k not in seen:
                extra[k.split("/")[1]] += 1
        rb = sum(f[2] for f in files if not f[3])
        print(f"S3 sizes: {nex} of {len(files)} NOMADS files matched an S3 key (exact size); "
              f"{len(files) - nex} keep the rounded NOMADS size ({rb / 1024 ** 3:.2f} GiB). "
              f"S3 keys for {day} not on NOMADS: {sum(extra.values())} {dict(extra) if extra else ''}")

    # group by directory/product, then per cycle
    per = defaultdict(lambda: defaultdict(list))  # (dir, prod) -> cycle -> [(minutes, mem, bytes, run, exact)]
    other = defaultdict(lambda: [0, 0.0, set(), 0])   # (dir, prod) for unparsed or untimed files
    for directory, name, b, exact in files:
        m = NAME.match(name)
        top = directory.split("/")[0]
        if m and m.group("tt") and family_of(top) != "post_processed":
            mins = stamp_minutes(m.group("tt"), m.group("ts"))
            per[(directory, m.group("prod"))][int(m.group("cyc"))].append(
                (mins, int(m.group("mem") or 1), b, m.group("run"), exact))
        else:
            prod = (m.group("prod") + ("" if m.group("tt") else "_" + m.group("ext"))) if m else "other"
            o = other[(directory, prod)]
            o[0] += 1; o[1] += b; o[3] += exact
            if m:
                o[2].add(int(m.group("cyc")))

    catalog, cycles_rows = [], []
    for (directory, prod), cyc in sorted(per.items()):
        top = directory.split("/")[0]
        groups = defaultdict(list)  # signature -> [cycle]
        info = {}
        for c, recs in cyc.items():
            stamps = sorted({r[0] for r in recs})
            mems = sorted({r[1] for r in recs})
            diffs = sorted({b - a for a, b in zip(stamps, stamps[1:])})
            interval = diffs[0] if diffs else 60
            if stamps[0] < 0 or (stamps[-1] <= 0):          # analysis look-back
                hours = (-stamps[0] + interval) / 60.0
                kind = "analysis"
            else:                                             # forecast from cycle time
                hours = stamps[-1] / 60.0
                kind = "forecast"
            expect = round(hours * 60 / interval) * len(mems)
            nfiles = len(recs)
            sig = (kind, stamps[0], stamps[-1], interval, tuple(mems))
            groups[sig].append(c)
            info[c] = dict(hours=hours, interval=interval, n=nfiles, expect=expect,
                           bytes=sum(r[2] for r in recs), run=recs[0][3], mems=mems, gaps=len(diffs) > 1,
                           exact=sum(r[4] for r in recs))
            if prod == "channel_rt":
                cycles_rows.append(dict(day=day, domain=domain_of(top), directory=directory, cycle=f"t{c:02d}z",
                                        first=label(stamps[0], kind), last=label(stamps[-1], kind), interval_min=interval,
                                        hours_simulated=f"{hours:g}", members="/".join(map(str, mems)),
                                        files=nfiles, expected_files=expect, bytes=int(info[c]["bytes"])))
        for sig, cs in sorted(groups.items(), key=lambda kv: min(kv[1])):
            kind, s0, s1, interval, mems = sig
            hours = info[cs[0]]["hours"]
            nfiles = sum(info[c]["n"] for c in cs)
            expect = sum(info[c]["expect"] for c in cs)
            catalog.append(dict(
                day=day, domain=domain_of(top), family=family_of(top), directory=directory,
                run=info[cs[0]]["run"], product=prod, routing="yes" if prod == "channel_rt" and family_of(top) == "nwm_hydro" else "no",
                kind=kind, cycles_seen=len(cs), cycles=fmt_cycles(cs), first_stamp=label(s0, kind), last_stamp=label(s1, kind),
                output_interval_min=interval, hours_per_cycle=f"{hours:g}", members="/".join(map(str, mems)),
                files=nfiles, expected_files=expect, complete="yes" if nfiles == expect else "NO",
                bytes=int(sum(info[c]["bytes"] for c in cs)),
                files_exact_size=sum(info[c]["exact"] for c in cs), note=excl_note(top, prod)))
    for (directory, prod), (n, b, cs, nex) in sorted(other.items()):
        top = directory.split("/")[0]
        catalog.append(dict(day=day, domain=domain_of(top), family=family_of(top), directory=directory, run="",
                            product=prod, routing="no", kind="", cycles_seen=len(cs) or "",
                            cycles=fmt_cycles(cs) if cs else "", first_stamp="", last_stamp="",
                            output_interval_min="", hours_per_cycle="", members="", files=n, expected_files="",
                            complete="", bytes=int(b), files_exact_size=nex, note=excl_note(top, prod)))

    os.makedirs(OUT, exist_ok=True)
    cols = list(catalog[0].keys())
    with open(os.path.join(OUT, "nomads_catalog.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(catalog)
    with open(os.path.join(OUT, "nomads_channel_rt_cycles.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cycles_rows[0].keys())); w.writeheader(); w.writerows(cycles_rows)

    # footprint per domain-day
    fp = defaultdict(lambda: defaultdict(float))
    tops = defaultdict(set)  # (domain, family) -> top-level directories ("folders" in the day listing)
    for r in catalog:
        d, fam = r["domain"], r["family"]
        tops[(d, fam)].add(r["directory"].split("/")[0]); tops[(d, "all")].add(r["directory"].split("/")[0])
        fp[d]["files_all"] += r["files"]; fp[d]["bytes_all"] += r["bytes"]
        fp[d][f"bytes_{fam}"] += r["bytes"]; fp[d][f"files_{fam}"] += r["files"]
        if r["routing"] == "yes":
            fp[d]["files_channel_rt"] += r["files"]; fp[d]["bytes_channel_rt"] += r["bytes"]
    for (d, fam), s in tops.items():
        fp[d][f"dirs_{fam}"] = len(s)
    fcols = ["day", "domain", "dirs_nwm_hydro", "dirs_all", "files_channel_rt", "bytes_channel_rt", "files_nwm_hydro", "bytes_nwm_hydro",
             "files_forcing", "bytes_forcing", "files_coastal_schism", "bytes_coastal_schism",
             "files_post_processed", "bytes_post_processed", "files_usgs_timeslices", "bytes_usgs_timeslices",
             "files_all", "bytes_all"]
    order = ["CONUS", "Alaska", "Hawaii", "PuertoRico_USVI", "post_processed", "observations"]
    with open(os.path.join(OUT, "nomads_footprint.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(fcols)
        for d in order:
            if d in fp:
                w.writerow([day, d] + [int(fp[d].get(c, 0)) for c in fcols[2:]])
    n = len(files); tb = sum(x[2] for x in files)
    print(f"{n} files, {tb / 1024 ** 3:.1f} GiB in {len({x[0] for x in files})} directories")
    bad = [r for r in catalog if r["complete"] == "NO"]
    for r in bad:
        print(f"INCOMPLETE: {r['directory']} {r['product']} cycles {r['cycles']}: {r['files']} of {r['expected_files']}")
    for r in catalog:
        if r["routing"] == "yes":
            print(f"{r['domain']:16s} {r['directory']:36s} cycles {r['cycles_seen']:2d} [{r['cycles']:>11s}] "
                  f"{r['first_stamp']}..{r['last_stamp']} every {r['output_interval_min']} min -> "
                  f"{r['hours_per_cycle']:>4s} h  files {r['files']:5d}/{r['expected_files']:<5d} {r['bytes'] / 1024 ** 2:9.0f} MiB")


def excl_note(top, prod):
    fam = family_of(top)
    if fam == "forcing":
        return "excluded: meteorological forcing (input), not routing"
    if fam == "coastal_schism":
        return "excluded: SCHISM coastal total water, not NWM channel routing"
    if fam == "usgs_timeslices":
        return "excluded: observation timeslices for assimilation"
    if fam == "post_processed":
        return "excluded: post-processed subsets/derivatives of model output"
    if prod != "channel_rt":
        return "same run as channel_rt; not counted separately"
    return ""


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "fetch":
        fetch(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == "fetch-s3":
        fetch_s3(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "parse":
        parse(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "nwm.20261029",
              sys.argv[4] if len(sys.argv) > 4 else None)
    else:
        sys.exit(__doc__)
