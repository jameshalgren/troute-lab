# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Side-by-side table of one namelist across the 25 NCEP configurations (offline).
Reads raw/ncep_text/parm__<config>__<NAME>; prints options identical in all configs,
then the varying ones grouped by value. rebuild.sh writes the output to
build/hydro_namelist_table.txt and build/hrldas_namelist_table.txt (source for §6).
Usage (from the catalog folder): uv run python -I scripts/nml_table.py hydro.namelist
"""
import glob, re, os, sys, collections
pat = sys.argv[1]
files = sorted(glob.glob(f"raw/ncep_text/parm__*__{pat}"))
vals = collections.OrderedDict(); cfgs = []
for f in files:
    cfg = f.split("__")[1]; cfgs.append(cfg)
    for line in open(f, errors="replace"):
        line = line.split("!")[0].strip()
        m = re.match(r"([A-Za-z_0-9()]+)\s*=\s*(.+?),?\s*$", line)
        if m:
            vals.setdefault(m.group(1), {})[cfg] = m.group(2).strip()
const = {k: v for k, v in vals.items() if len(set(v.values())) == 1 and len(v) == len(cfgs)}
print("## identical in all", len(cfgs), "configs:")
for k, v in const.items(): print(f"  {k} = {list(v.values())[0]}")
print("\n## varying:")
for k, v in vals.items():
    if k in const: continue
    groups = collections.defaultdict(list)
    for c in cfgs: groups[v.get(c, "(absent)")].append(c)
    print(f"  {k}:")
    for val, cs in groups.items(): print(f"      {val}  <- {', '.join(cs)}")
