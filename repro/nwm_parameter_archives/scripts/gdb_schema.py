# /// script
# requires-python = ">=3.9"
# dependencies = ["pyogrio"]
# ///
"""Dump the layer schemas of every ESRI File Geodatabase (*.gdb) under DIR.

DIR is the --gdb-dir that scan_tar.py extracted the tarball's .gdb members into.
Writes one text file: per layer, geometry type, feature count, CRS (first 60 chars) and
field names and types. SOURCE_URL and LABEL go into the first line.
Usage: uv run --with pyogrio python -I scripts/gdb_schema.py DIR SOURCE_URL LABEL OUT_TXT
"""
import os, sys
import pyogrio

dest, url, label, out = sys.argv[1:5]
lines = [f"# {label}: FileGDB layer schemas (pyogrio {pyogrio.__version__}, GDAL {pyogrio.__gdal_version_string__}) from {url}"]
for root, dirs, files in os.walk(dest):
    dirs.sort()
    for d in list(dirs):
        if d.endswith(".gdb"):
            g = os.path.join(root, d)
            lines.append(f"\n## {os.path.relpath(g, dest)}")
            for name, gtype in pyogrio.list_layers(g):
                try:
                    info = pyogrio.read_info(g, layer=name, force_feature_count=False)
                    crs = (info.get("crs") or "")
                    lines.append(f"\n### layer {name}  geometry={gtype}  features={info.get('features')}  crs={crs[:60]}")
                    for f, t in zip(info["fields"], info["dtypes"]):
                        lines.append(f"    {f}: {t}")
                except Exception as e:
                    lines.append(f"\n### layer {name} geometry={gtype}  ERROR {e}")
            dirs.remove(d)
os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
open(out, "w").write("\n".join(lines) + "\n")
print("FileGDB schema ->", out)
