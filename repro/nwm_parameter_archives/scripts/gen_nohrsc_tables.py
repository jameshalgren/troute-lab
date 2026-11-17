# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Generate the NOHRSC tables in build/ from listings/ and headers/ (offline).

Writes build/nohrsc_all_files.md (from listings/nohrsc_owp_files.tsv) and
build/table_<label>.md for each tarball (from listings/members_<label>.json and the
netCDF headers in headers/<label>/).
Usage (from the catalog folder): uv run python -I scripts/gen_nohrsc_tables.py
"""
import csv, json, re, os

NOHRSC = "https://www.nohrsc.noaa.gov/owp_files/"


def hdr(label, name):
    p = f"headers/{label}/{name.replace('/', '__')}.cdl"
    if name.startswith("./"): p = f"headers/{label}/{name[2:].replace('/', '__')}.cdl"
    if not os.path.exists(p): return None
    t = open(p).read()
    m = re.search(r"dimensions:\n(.*?)variables:", t, re.S)
    dims = ", ".join(x.strip().rstrip(" ;").replace(" = ", "=").replace("UNLIMITED ; // (", "UNLIMITED(").replace(" currently)", ")") for x in m.group(1).strip().splitlines()) if m else ""
    k = re.search(r"ncdump -k: ([^)]*)\)", t.splitlines()[0]); k = k.group(1) if k else ""
    ver = re.search(r'^\t\t:version = "([^"]*)"', t, re.M)
    return dims, k, (ver.group(1) if ver else "—"), os.path.relpath(p)


def members(label):
    return json.load(open(f"listings/members_{label}.json"))


def table(label, keyfn=None):
    d = members(label)
    out = [f"| Member | Bytes | Date in tar (UTC) | MD5 | Format | Dimensions | `version` attr | Description key |", "|---|---:|---|---|---|---|---|---|"]
    for x in d["members"]:
        if x["type"] != "file": continue
        h = hdr(label, x["name"])
        dims, kind, ver, hp = h if h else ("", "", "", "")
        fmt = kind or ("text" if x["name"].endswith((".txt", ".csv", ".in", ".nml", ".gr3", ".ll", ".ic", ".cpp", ".utm", ".vtk")) else "")
        key = keyfn(x["name"]) if keyfn else ""
        name = x["name"][2:] if x["name"].startswith("./") else x["name"]
        link = f"[{name}]({hp})" if hp else f"`{name}`"
        out.append(f"| {link} | {x['size']:,} | {x['mtime'][:16]} | `{x['md5']}` | {fmt} | {dims} | {ver} | {key} |")
    return "\n".join(out), d


def key_param(n):
    b = os.path.basename(n)
    for k in ["Fulldom", "RouteLink", "LAKEPARM", "nudgingParams", "spatialweights", "md5sum", "README"]:
        if b.startswith(k): return f"[{k}](#desc-{k.lower()})"
    return ""


def key_coastal(n):
    b = os.path.basename(n)
    if re.match(r"(k1|k2|m2|n2|o1|p1|q1|s2)\.nc", b): return "[tides](#desc-tides)"
    if b.startswith("Ocean_Land_Mask"): return "[mask](#desc-mask)"
    return f"[{b}](#desc-coastal)"


# every file in owp_files
rows = [r for r in csv.reader(open("listings/nohrsc_owp_files.tsv"), delimiter="\t")][1:]
out = ["| Path | Bytes | Last-Modified (HTTP) |", "|---|---:|---|"]
for r in rows:
    if r[0] == "DIR-ERR":  # a folder listed in its parent index that does not open
        m = re.search(r"HTTP Error (\d+)", r[4])
        out.append(f"| `{r[1][len(NOHRSC):]}` | — | listed in parent index, but {'HTTP ' + m.group(1) if m else r[4]} |")
    if r[0] != "FILE": continue
    size = f"{int(r[2]):,}" if r[2] else ""
    out.append(f"| `{r[1][len(NOHRSC):]}` | {size} | {r[3][5:25]} |")
open("build/nohrsc_all_files.md", "w").write("\n".join(out) + "\n")

for label, kf in [("v2.1", key_param), ("v3.0", key_param), ("coastal_v3.0", key_coastal)]:
    t, d = table(label, kf)
    open(f"build/table_{label}.md", "w").write(f"Compressed: {d['compressed_bytes']:,} bytes, SHA-256 `{d['compressed_sha256']}` (computed on the stream, {d['scanned_utc'][:10]}).\n\n" + t + "\n")
# hydrofabric: dir summary + layers
for label in ["hydrofabric_v2.0", "hydrofabric_v2.1", "hydrofabric_v3.0"]:
    d = members(label)
    files = [x for x in d["members"] if x["type"] == "file"]
    nongdb = [x for x in files if ".gdb/" not in x["name"]]
    gdb = [x for x in files if ".gdb/" in x["name"]]
    dates = sorted(x["mtime"] for x in gdb)
    s = [f"Compressed: {d['compressed_bytes']:,} bytes, SHA-256 `{d['compressed_sha256']}`. {len(files)} files, {sum(x['size'] for x in files):,} bytes uncompressed.",
         f"- {len(gdb)} ESRI File Geodatabase internal files (`a0000000NN.gdbtable/.gdbtablx/.spx/.atx/.gdbindexes/.freelist/.horizon`, plus `gdb`, `timestamps`), {sum(x['size'] for x in gdb):,} bytes, dated {dates[0][:10]} to {dates[-1][:10]}. Full per-file list with MD5: [listings/members_{label}.json](listings/members_{label}.json)."]
    for x in nongdb: s.append(f"- `{x['name']}` ({x['size']:,} bytes, {x['mtime'][:10]}, MD5 `{x['md5']}`)")
    open(f"build/table_{label}.md", "w").write("\n".join(s) + "\n")
print("NOHRSC tables written")
