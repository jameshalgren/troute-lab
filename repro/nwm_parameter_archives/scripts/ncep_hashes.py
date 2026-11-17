# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""SHA-256 and MD5 of the small routing files in NCEP nwm.v3.1.7/parm/domain*/.

Files: RouteLink*, LAKEPARM*, nudgingParams*, Diversion*, reservoir_index* (17 files,
about 0.83 GB on 2026-11-10). Each is streamed and hashed in memory (nothing is saved),
unless a verified local copy is found with find_cached.py (--cache; the
reference hash is the one in --prev). Output lines: "sha256 md5 size path-under-parm/".
--subtree REL (relative to nwm.v3.1.7/, e.g. parm/domain_hawaii/) hashes only the files
under it; the --prev lines for all other files are kept, so the output is still complete.
Usage: ncep_hashes.py TREE_TSV OUT [--prev listings/ncep_parm_hashes.txt] [--cache DIR ...]
       [--subtree REL]
"""
import argparse, hashlib, os, re, subprocess, sys, urllib.request

ROOT = "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/"
BASE = ROOT + "parm/"
KINDS = ["RouteLink", "LAKEPARM", "nudgingParams", "Diversion", "reservoir_index"]  # output order
PAT = re.compile(r"^domain[^/]*/(" + "|".join(KINDS) + r")[^/]*$")
ap = argparse.ArgumentParser()
ap.add_argument("tsv"); ap.add_argument("out"); ap.add_argument("--prev")
ap.add_argument("--cache", action="append", default=[]); ap.add_argument("--subtree", default="")
a = ap.parse_args()
inside = lambda url: url.startswith(ROOT + a.subtree)
prev, prev_lines = {}, {}
if a.prev and os.path.exists(a.prev):
    for line in open(a.prev):
        sha, md5, size, rel = line.split()
        prev[rel] = (sha, int(size)); prev_lines[rel] = line
elif a.subtree:
    sys.exit("--subtree needs an existing --prev file to merge into")
rows = []
for line in open(a.tsv):
    p = line.rstrip("\n").split("\t")
    if p[0] == "FILE" and p[1].startswith(BASE) and PAT.match(p[1][len(BASE):]):
        rows.append((p[1], p[1][len(BASE):], int(p[2]), p[3]))
rows.sort(key=lambda r: (KINDS.index(PAT.match(r[1]).group(1)), r[1].split("/")[0], r[1]))
out = []
for url, rel, size, lm in rows:
    if not inside(url):
        assert rel in prev_lines, f"{rel}: outside --subtree but not in --prev"
        out.append(prev_lines[rel]); continue
    src = None
    if a.cache and rel in prev and prev[rel][1] == size:
        cmd = [sys.executable, "-I", os.path.join(os.path.dirname(os.path.abspath(__file__)), "find_cached.py"),
               url, "--size", str(size), "--sha256", prev[rel][0]] + sum((["--cache", c] for c in a.cache), [])
        src = subprocess.run(cmd, capture_output=False, stdout=subprocess.PIPE, text=True).stdout.strip() or None
    md5, sha, n = hashlib.md5(), hashlib.sha256(), 0
    f = open(src, "rb") if src else urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (catalog script)"}), timeout=300)
    with f:
        for b in iter(lambda: f.read(8 << 20), b""):
            md5.update(b); sha.update(b); n += len(b)
    assert n == size, f"{rel}: read {n} bytes, listing says {size}"
    out.append(f"{sha.hexdigest()} {md5.hexdigest()} {size} {rel}\n")
    print(rel, size, "local copy" if src else "downloaded", flush=True)
open(a.out, "w").writelines(out)
print(len(out), "files ->", a.out, f"({sum(inside(r[0]) for r in rows)} hashed under {a.subtree})" if a.subtree else "")
