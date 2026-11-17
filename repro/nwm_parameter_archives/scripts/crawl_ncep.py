# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Crawl the NCEP nwm.v3.x Apache index (fancy listing, ?F=1).

One row per folder and file: type, url, size_exact (HTTP HEAD Content-Length),
last_modified_head, listing_date, listing_size, dir_entries. Exact HEADs are made for
every file in folders with <= 1,000 entries, and for the first files (in listing order) of
the folders in HEAD_FIRST. The three big folders (CFSv2_Climo, NLDAS_Climo and
manualclimateRestart, 1,536 to 11,713 files) otherwise keep the listing's approximate size.
--subtree REL crawls only ROOT+REL; with --merge EXISTING_TSV the new rows replace that
subtree's rows in EXISTING_TSV (other rows kept) and the merged table is written to OUT.
Usage: crawl_ncep.py ROOT OUT_TSV [--subtree parm/domain/ --merge listings/ncep_nwm.v3.1.7_tree.tsv]
"""
import argparse, re, time, urllib.request, urllib.parse, html

UA = {"User-Agent": "Mozilla/5.0 (catalog script)"}
MAXHEAD = 1000  # the 2026-11-10 survey HEADed every folder up to 133 entries; the next is 1,536
# The 2026-11-10 survey also HEADed the first 353 files of CFSv2_Climo (cfs_dlwsfc_0101_00
# to cfs_dlwsfc_0329_00, all 1,170,616 bytes). Keep that sample so re-surveys stay comparable.
HEAD_FIRST = {"parm/forcingParam/Long_Range/CFSv2_Climo/": 353}
HEADER = "type\turl\tsize_exact\tlast_modified_head\tlisting_date\tlisting_size\tdir_entries\n"
ap = argparse.ArgumentParser()
ap.add_argument("root"); ap.add_argument("out")
ap.add_argument("--subtree", default=""); ap.add_argument("--merge")
a = ap.parse_args()
row_re = re.compile(r'<a href="([^"?][^"]*)">[^<]*</a>\s+(\d{4}-\d\d-\d\d \d\d:\d\d)\s+(\S+)')


def get(u):
    err = None
    for i in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read().decode("utf-8", "replace")
        except Exception as e: err = e; time.sleep(3)
    raise err


def head(u):
    err = None
    for i in range(3):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=UA, method="HEAD"), timeout=60)
            return r.headers.get("Content-Length") or "", r.headers.get("Last-Modified") or ""
        except Exception as e: err = e; time.sleep(2)
    return "", f"ERR {err}"


class Rows(list):
    """Collects rows; without --merge also writes each row to OUT at once (progress)."""
    def __init__(s, f): super().__init__(); s.f = f
    def append(s, r):
        super().append(r)
        if s.f: s.f.write(r); s.f.flush()


live = None if a.merge else open(a.out, "w")
if live: live.write(HEADER)
rows = Rows(live)


def crawl(u):
    try: page = get(u + "?F=1")
    except Exception as e:
        rows.append(f"DIR-ERR\t{u}\t\t{e}\t\t\t\n"); return
    entries = [(urllib.parse.urljoin(u, html.unescape(h)), d, s) for h, d, s in row_re.findall(page)]
    entries = [e for e in entries if e[0].startswith(u) and e[0] != u]
    n = len(entries)
    nhead = n if n <= MAXHEAD else HEAD_FIRST.get(u[len(a.root):], 0)
    nfile = 0
    for full, d, s in entries:
        if full.endswith("/"):
            rows.append(f"DIR\t{full}\t\t\t{d}\t\t\n"); crawl(full)
        else:
            nfile += 1
            if nfile <= nhead: se, lm = head(full); time.sleep(0.02)
            else: se, lm = "", ""
            rows.append(f"FILE\t{full}\t{se}\t{lm}\t{d}\t{s}\t{n}\n")


start = a.root + a.subtree
crawl(start)
if a.merge:
    assert a.subtree, "--merge needs --subtree"
    old = open(a.merge).readlines()[1:]
    inside = [i for i, l in enumerate(old) if l.split("\t")[1].startswith(start) and l.split("\t")[1] != start]
    if inside:
        i0, i1 = inside[0], inside[-1] + 1
        assert inside == list(range(i0, i1)), "subtree rows are not contiguous"
        out = old[:i0] + rows + old[i1:]
    else:
        out = old + rows
    print(f"subtree {a.subtree}: {len(inside)} old rows replaced by {len(rows)} new rows")
    with open(a.out, "w") as fo:
        fo.write(HEADER); fo.writelines(out)
else:
    live.close(); out = rows
print(len(out), "rows ->", a.out)
