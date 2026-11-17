# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Read a .tar.gz once (streamed from its URL, or from a verified local copy) and record
every member: name, type, size, tar mtime (UTC), mode, MD5, SHA-256, and the SHA-256 of
the compressed stream.

Writes, under OUT (a staging folder laid out like the catalog folder):
  OUT/listings/members_<LABEL>.json   sanitized: `source` is always the public URL;
                                       `read_from` says whether a verified local copy
                                       was used (never its path); no tar user names
  OUT/headers/<LABEL>/<member>.cdl     `ncdump -h` of every netCDF member
  OUT/raw/nohrsc_text/<LABEL>/<member> small text members (README, md5sum, ...)
Options:
  --local PATH   read this local copy instead of the URL (the caller verified it)
  --keep DIR     also save the streamed tarball as DIR/<name> (ignored with --local)
  --gdb-dir DIR  extract members inside *.gdb/ folders to DIR (for gdb_schema.py)
Members are written one at a time to a scratch file in TMPDIR and deleted.
Usage: scan_tar.py URL LABEL OUT [--local PATH] [--keep DIR] [--gdb-dir DIR]
Requires ncdump (netCDF-C) on the PATH.
"""
import argparse, datetime, hashlib, json, os, shutil, subprocess, tarfile, tempfile, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("url"); ap.add_argument("label"); ap.add_argument("out")
ap.add_argument("--local"); ap.add_argument("--keep"); ap.add_argument("--gdb-dir")
a = ap.parse_args()
KEEP_MAX = 2_000_000
TEXT_EXT = (".txt", ".csv", ".in", ".nml", ".TBL", ".tbl", ".md", ".json", ".sh", ".py", ".ll", ".gr3", ".ic", ".cpp", ".utm", ".prop", ".xml", ".yaml", ".yml")
hdir = os.path.join(a.out, "headers", a.label)
tdir = os.path.join(a.out, "raw", "nohrsc_text", a.label)
ldir = os.path.join(a.out, "listings")
for d in (hdir, tdir, ldir): os.makedirs(d, exist_ok=True)


class HashReader:
    """File-like wrapper: hashes (and optionally copies) every byte read."""
    def __init__(s, f, copy=None): s.f = f; s.h = hashlib.sha256(); s.n = 0; s.copy = copy
    def read(s, n=-1):
        b = s.f.read(n); s.h.update(b); s.n += len(b)
        if s.copy: s.copy.write(b)
        return b


def safe_rel(name):
    p = os.path.normpath(name)
    if os.path.isabs(p) or p.startswith(".."): raise ValueError(f"unsafe member path {name!r}")
    return p


keep_part = keep_final = None
if a.local:
    raw = open(a.local, "rb"); read_from = "verified local copy (size and SHA-256 match the published file)"
else:
    raw = urllib.request.urlopen(urllib.request.Request(a.url, headers={"User-Agent": "Mozilla/5.0 (catalog script)"}), timeout=300)
    read_from = "streamed from source"
    if a.keep:
        os.makedirs(a.keep, exist_ok=True)
        keep_final = os.path.join(a.keep, os.path.basename(a.url)); keep_part = keep_final + ".part"
copy = open(keep_part, "wb") if keep_part else None
hr = HashReader(raw, copy)
scratch = tempfile.mkdtemp(prefix="scan_tar_")
tmp = os.path.join(scratch, "member.bin")
rows = []
ok = False
try:
    with tarfile.open(fileobj=hr, mode="r|gz") as tf:
        for m in tf:
            row = dict(name=m.name, type="dir" if m.isdir() else ("file" if m.isfile() else "other"),
                       size=m.size,
                       mtime=datetime.datetime.fromtimestamp(m.mtime, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                       mode=oct(m.mode))
            if m.isfile():
                f = tf.extractfile(m)
                md5, sha = hashlib.md5(), hashlib.sha256()
                with open(tmp, "wb") as o:
                    while True:
                        b = f.read(8 << 20)
                        if not b: break
                        md5.update(b); sha.update(b); o.write(b)
                row["md5"], row["sha256"] = md5.hexdigest(), sha.hexdigest()
                base = m.name.replace("/", "__")
                with open(tmp, "rb") as fh: magic = fh.read(8)
                row["magic"] = magic[:4].hex()
                if magic[:3] == b"CDF" or magic[:8] == b"\x89HDF\r\n\x1a\n":
                    r = subprocess.run(["ncdump", "-h", tmp], capture_output=True, text=True)
                    hdr = r.stdout.replace("netcdf member {", f"netcdf {os.path.basename(m.name).rsplit('.', 1)[0]} {{", 1)
                    k = subprocess.run(["ncdump", "-k", tmp], capture_output=True, text=True).stdout.strip()
                    row["nc_kind"] = k
                    with open(os.path.join(hdir, base + ".cdl"), "w") as o:
                        o.write(f"// source: {a.label} member {m.name} ({m.size} bytes, md5 {row['md5']}, ncdump -k: {k})\n")
                        o.write(hdr if r.returncode == 0 else f"// ncdump failed: {r.stderr}\n")
                elif m.size <= KEEP_MAX and (m.name.endswith(TEXT_EXT) or "README" in m.name or "." not in os.path.basename(m.name)):
                    shutil.copyfile(tmp, os.path.join(tdir, base))
                if a.gdb_dir and ".gdb/" in m.name:
                    dest = os.path.join(a.gdb_dir, safe_rel(m.name))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    os.replace(tmp, dest)
                if os.path.exists(tmp): os.remove(tmp)
            rows.append(row)
            print(row["name"], row["size"], row.get("md5", ""), flush=True)
    while hr.read(8 << 20): pass  # drain the remainder so the stream hash is complete
    ok = True
finally:
    shutil.rmtree(scratch, ignore_errors=True)
    if copy: copy.close()
    if keep_part and not ok and os.path.exists(keep_part): os.remove(keep_part)
if keep_part: os.replace(keep_part, keep_final); print("kept", keep_final)
summary = dict(source=a.url, read_from=read_from, label=a.label, compressed_bytes=hr.n,
               compressed_sha256=hr.h.hexdigest(),
               scanned_utc=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
               members=rows)
json.dump(summary, open(os.path.join(ldir, f"members_{a.label}.json"), "w"), indent=1)
print("DONE", hr.n, hr.h.hexdigest())
