# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Read NCEP files listed in a crawl TSV without downloading large ones.

For every FILE row with an exact size whose path (relative to the nwm.v3.x root) starts
with one of the --prefix values: read the first 8 bytes by HTTP Range. netCDF/HDF5 files
get `ncdump -h "<url>#mode=bytes"` (netCDF-C byte-range reads) written to
HDR_DIR/<path with / -> __>.cdl. Other files up to --max-bytes (default 200,000) are
downloaded to TEXT_DIR/<path with / -> __> if they look like text (or always, with
--keep-binary). One line per file goes to --log.
Usage: ncep_headers.py TSV --prefix parm/ --text-dir raw/ncep_text [--hdr-dir headers/ncep_v3.1.7]
       [--max-bytes N] [--keep-binary] [--log FILE]
Requires ncdump (netCDF-C, built with byte-range support) on the PATH for --hdr-dir.
"""
import argparse, os, subprocess, sys, time, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (catalog script)"}
BASE = "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/"
ap = argparse.ArgumentParser()
ap.add_argument("tsv"); ap.add_argument("--prefix", action="append", required=True)
ap.add_argument("--text-dir", required=True); ap.add_argument("--hdr-dir")
ap.add_argument("--max-bytes", type=int, default=200_000); ap.add_argument("--keep-binary", action="store_true")
ap.add_argument("--log", default=os.devnull)
a = ap.parse_args()
os.makedirs(a.text_dir, exist_ok=True)
if a.hdr_dir: os.makedirs(a.hdr_dir, exist_ok=True)
log = open(a.log, "a")


def get(url, rng=None, timeout=60):
    h = dict(UA, **({"Range": rng} if rng else {}))
    err = None
    for i in range(3):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=timeout).read()
        except Exception as e: err = e; time.sleep(2)
    raise err


n = dict(NC=0, TXT=0, BIN=0, BIG=0, ERR=0)
for line in open(a.tsv):
    p = line.rstrip("\n").split("\t")
    if p[0] != "FILE" or not p[1].startswith(BASE) or not p[2]: continue
    rel = p[1][len(BASE):]
    if not rel.startswith(tuple(a.prefix)): continue
    url, size, flat = p[1], int(p[2]), rel.replace("/", "__")
    try:
        magic = get(url, "bytes=0-7")[:8]
    except Exception as e:
        log.write(f"ERR {rel} {e}\n"); n["ERR"] += 1; continue
    if magic[:3] == b"CDF" or magic == b"\x89HDF\r\n\x1a\n":
        if not a.hdr_dir: continue
        r = subprocess.run(["ncdump", "-h", url + "#mode=bytes"], capture_output=True, text=True, timeout=900)
        k = subprocess.run(["ncdump", "-k", url + "#mode=bytes"], capture_output=True, text=True, timeout=300).stdout.strip()
        with open(os.path.join(a.hdr_dir, flat + ".cdl"), "w") as o:
            o.write(f"// source: {url} ({size} bytes; ncdump -k: {k}; header read by HTTP byte-range, {time.strftime('%Y-%m-%d', time.gmtime())})\n")
            o.write(r.stdout if r.returncode == 0 else f"// ncdump failed: {r.stderr}\n")
        log.write(f"NC {rel} {k}\n"); n["NC"] += 1
    elif size <= a.max_bytes:
        data = get(url)
        if a.keep_binary or b"\x00" not in data[:4096]:
            open(os.path.join(a.text_dir, flat), "wb").write(data); log.write(f"TXT {rel}\n"); n["TXT"] += 1
        else:
            log.write(f"BIN {rel} magic={magic.hex()}\n"); n["BIN"] += 1
    else:
        log.write(f"BIG {rel} magic={magic.hex()} size={size}\n"); n["BIG"] += 1
    log.flush()
print("ncep_headers:", ", ".join(f"{k} {v}" for k, v in n.items()))
sys.exit(1 if n["ERR"] else 0)
