# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Generate the NCEP tables in build/ from listings/ncep_nwm.v3.1.7_tree.tsv and
headers/ncep_v3.1.7/ (offline): build/ncep_parm_tables.md (per-folder file tables for
parm/) and build/ncep_tree_summary.md (files and bytes per folder).
Usage (from the catalog folder): uv run python -I scripts/gen_ncep_tables.py
"""
import csv, re, os, collections, glob
B = "https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/"
rows = [r for r in csv.reader(open("listings/ncep_nwm.v3.1.7_tree.tsv"), delimiter="\t")][1:]
files = [r for r in rows if r[0] == "FILE"]
# purpose keys for parm files
def key(rel):
    b = os.path.basename(rel)
    rules = [(r"^hydro\.namelist$", "[hydro.namelist](#ncep-namelists)"), (r"^namelist\.hrldas$", "[namelist.hrldas](#ncep-namelists)"),
             (r"^(CHANPARM|GENPARM|HYDRO|MPTABLE|SOILPARM)\.TBL$", "[constants](#desc-tbl)"),
             (r"^Fulldom", "[Fulldom](#desc-fulldom)"), (r"^RouteLink", "[RouteLink](#desc-routelink)"), (r"^LAKEPARM", "[LAKEPARM](#desc-lakeparm)"),
             (r"^nudgingParams", "[nudgingParams](#desc-nudgingparams)"), (r"^spatialweights", "[spatialweights](#desc-spatialweights)"),
             (r"^GWBUCKPARM", "[GWBUCKPARM](#desc-gwbuckparm)"), (r"^hydro2dtbl", "[hydro2dtbl](#desc-hydro2dtbl)"), (r"^soilproperties", "[soilproperties](#desc-soilproperties)"),
             (r"^wrfinput", "[wrfinput](#desc-wrfinput)"), (r"^geo_em", "[geo_em](#desc-geo-em)"), (r"^GEOGRID_LDASOUT", "[GEOGRID_LDASOUT](#desc-geogrid-ldasout)"),
             (r"^reservoir_index", "[reservoir_index](#desc-reservoir-index)"), (r"^Diversion", "[Diversion](#desc-diversion)"),
             (r"^template_forcing_engine", "[forcing config](#desc-forcingconfigs)")]
    for p, k in rules:
        if re.search(p, b): return k
    if "/coastal/" in "/" + rel: return "[coastal](#desc-coastal)"
    return ""
def hdrlink(rel):
    p = f"headers/ncep_v3.1.7/{rel.replace('/', '__')}.cdl"
    return p if os.path.exists(p) else None
def dims(p):
    t = open(p).read(); m = re.search(r"dimensions:\n(.*?)variables:", t, re.S)
    return ", ".join(x.strip().rstrip(" ;").replace(" = ", "=").replace("UNLIMITED ; // (", "UNLIMITED(").replace(" currently)", ")") for x in m.group(1).strip().splitlines()) if m else ""
def ver(p):
    m = re.search(r'^\t\t:version = "([^"]*)"', open(p).read(), re.M); return m.group(1) if m else "—"
by_dir = collections.defaultdict(list)
for r in files: by_dir[r[1][len(B):].rsplit("/", 1)[0]].append(r)
out = []
for d in sorted(k for k in by_dir if k.startswith("parm")):
    fs = by_dir[d]
    out.append(f"\n#### `{d}/` ({len(fs)} files)\n")
    if len(fs) > 300:
        pats = collections.Counter(re.sub(r"\d+", "N", r[1].rsplit("/", 1)[1]) for r in fs)
        out.append(f"Listing only (exact sizes not requested for a directory this large). Name patterns: " + "; ".join(f"`{k}` ×{v}" for k, v in pats.most_common()) +
                   f". Listing dates {min(r[4] for r in fs)} to {max(r[4] for r in fs)}; listing sizes {', '.join(sorted(set(r[5] for r in fs)))}.")
        continue
    out.append("| File | Bytes | Last-Modified | Format / dims | `version` | Purpose |\n|---|---:|---|---|---|---|")
    for r in sorted(fs, key=lambda r: r[1]):
        rel = r[1][len(B):]; h = hdrlink(rel)
        name = f"[{os.path.basename(rel)}]({h})" if h else f"`{os.path.basename(rel)}`"
        size = f"{int(r[2]):,}" if r[2] else r[5]
        lm = r[3][5:22] if r[3] else r[4]
        fd = dims(h) if h else ""
        out.append(f"| {name} | {size} | {lm} | {fd} | {ver(h) if h else ''} | {key(rel)} |")
open("build/ncep_parm_tables.md", "w").write("\n".join(out) + "\n")
# folder summary for the whole tree
summ = collections.OrderedDict()
for r in files:
    rel = r[1][len(B):]; parts = rel.split("/")
    top = "/".join(parts[:2]) if parts[0] in ("parm", "sorc", "ush") and len(parts) > 2 else parts[0] + ("/" if len(parts) > 1 else "")
    s = summ.setdefault(top, [0, 0, 0]); s[0] += 1
    if r[2]: s[1] += int(r[2])
    else: s[2] += 1
lines = ["| Folder | Files | Bytes (exact, HEAD) | Files without exact size |", "|---|---:|---:|---:|"]
for k in sorted(summ): lines.append(f"| `{k}` | {summ[k][0]:,} | {summ[k][1]:,} | {summ[k][2]:,} |")
open("build/ncep_tree_summary.md", "w").write("\n".join(lines) + "\n")
print("NCEP tables written:", len(files), "files in listing")
