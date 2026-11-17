# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Crawl the NOHRSC owp_files Apache index recursively; HEAD every file.

Writes a TSV (type, url, size, last_modified, status), one row per folder and file in
crawl order; a folder that is listed but does not open is a DIR-ERR row. With
--save-text DIR, also saves every README*.txt found (small text) into DIR.
Usage: crawl_nohrsc.py ROOT_URL OUT_TSV [--save-text DIR]
"""
import argparse, os, time, urllib.request, urllib.parse
from html.parser import HTMLParser

UA = {"User-Agent": "Mozilla/5.0 (catalog script)"}
ap = argparse.ArgumentParser()
ap.add_argument("root"); ap.add_argument("out"); ap.add_argument("--save-text")
a = ap.parse_args()


class P(HTMLParser):
    def __init__(s): super().__init__(); s.links = []
    def handle_starttag(s, t, attrs):
        if t == "a":
            h = dict(attrs).get("href")
            if h: s.links.append(h)


def req(u, method="GET"):
    err = None
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA, method=method), timeout=60)
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            err = e; time.sleep(2)
    raise err


def head(u):
    try:
        r = req(u, "HEAD")
        return r.headers.get("Content-Length"), r.headers.get("Last-Modified"), r.status
    except Exception as e:
        return None, None, str(e)


rows = []


def crawl(u):
    try: page = req(u).read().decode("utf-8", "replace")
    except Exception as e:
        rows.append(("DIR-ERR", u, "", "", str(e))); return
    p = P(); p.feed(page)
    for h in p.links:
        if h.startswith("?") or h.startswith("#"): continue
        full = urllib.parse.urljoin(u, h)
        if not full.startswith(u) or full == u: continue  # parent / absolute elsewhere
        if full.endswith("/"):
            rows.append(("DIR", full, "", "", "")); crawl(full)
        else:
            sz, lm, st = head(full); rows.append(("FILE", full, sz or "", lm or "", str(st)))
            name = os.path.basename(urllib.parse.urlparse(full).path)
            if a.save_text and name.startswith("README") and name.endswith(".txt") and sz and int(sz) < 200_000:
                os.makedirs(a.save_text, exist_ok=True)
                open(os.path.join(a.save_text, name), "wb").write(req(full).read())
        time.sleep(0.2)


crawl(a.root)
with open(a.out, "w") as f:
    f.write("type\turl\tsize\tlast_modified\tstatus\n")
    for r in rows: f.write("\t".join(r) + "\n")
print(len(rows), "rows ->", a.out)
