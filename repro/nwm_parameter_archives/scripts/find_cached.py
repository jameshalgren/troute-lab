# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Find a verified local copy of a published file, so a crawl need not download it.

Looks for a file with the URL's file name in each --cache DIR (and its subfolders, up to
--depth levels). A candidate is used only if
  1. the server still publishes the same file: HTTP HEAD Content-Length equals
     --size, and Last-Modified equals --last-modified when that is given;
  2. the candidate has exactly --size bytes; and
  3. its SHA-256 equals --sha256 (the value recorded by the previous survey).
Prints the path of the first candidate that passes to stdout (nothing if none) and the
reason for each rejection to stderr. Exit code 0 either way.
Usage: find_cached.py URL --size N --sha256 HEX [--last-modified "HTTP date"]
       --cache DIR [--cache DIR ...] [--depth 3]
"""
import argparse, hashlib, os, sys, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("url"); ap.add_argument("--size", type=int, required=True)
ap.add_argument("--sha256", required=True); ap.add_argument("--last-modified")
ap.add_argument("--cache", action="append", default=[]); ap.add_argument("--depth", type=int, default=3)
a = ap.parse_args()
name = os.path.basename(a.url)


def say(msg): print(f"cache: {name}: {msg}", file=sys.stderr)


def candidates():
    for top in a.cache:
        top = os.path.abspath(top)
        if not os.path.isdir(top): say(f"cache folder not found, skipped"); continue
        for root, dirs, files in os.walk(top):
            depth = root[len(top):].count(os.sep)
            if depth >= a.depth: dirs[:] = []
            dirs.sort()
            if name in files: yield os.path.join(root, name)


cands = list(candidates()) if a.cache else []
if not cands:
    if a.cache: say("no file of that name in the cache folders")
    sys.exit(0)
try:
    r = urllib.request.urlopen(urllib.request.Request(a.url, method="HEAD", headers={"User-Agent": "Mozilla/5.0 (catalog script)"}), timeout=60)
    srv_size, srv_lm = int(r.headers.get("Content-Length") or -1), r.headers.get("Last-Modified")
except Exception as e:
    say(f"cannot check the server ({e}); not using a local copy"); sys.exit(0)
if srv_size != a.size:
    say(f"server size {srv_size} != listed {a.size}: the published file changed; not using a local copy"); sys.exit(0)
if a.last_modified and srv_lm != a.last_modified:
    say(f"server Last-Modified {srv_lm!r} != listed {a.last_modified!r}; not using a local copy"); sys.exit(0)
for c in cands:
    sz = os.path.getsize(c)
    if sz != a.size:
        say(f"candidate {sz} bytes != {a.size}: rejected"); continue
    say(f"candidate has the listed size; computing SHA-256 ...")
    h = hashlib.sha256()
    with open(c, "rb") as f:
        for b in iter(lambda: f.read(16 << 20), b""): h.update(b)
    if h.hexdigest() != a.sha256:
        say(f"candidate SHA-256 {h.hexdigest()} != listed {a.sha256}: rejected"); continue
    say("verified local copy (size and SHA-256 match); using it instead of downloading")
    print(c)
    break
else:
    say("no candidate passed; will stream from the server")
