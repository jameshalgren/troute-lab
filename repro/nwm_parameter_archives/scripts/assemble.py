# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Assemble nwm_parameter_archives.md from build/main_template.md.

Expands `<<INCLUDE path>>` (file inserted as is) and `<<VERBATIM path>>` (text file
inserted with BOM and CRLF removed). Paths are relative to the catalog folder.
The template is the only hand-written source; edit it, not the output.
Usage (from the catalog folder): uv run python -I scripts/assemble.py
"""
import re

t = open("build/main_template.md", encoding="utf-8").read()
t = re.sub(r"<<INCLUDE (\S+)>>",
           lambda m: open(m.group(1), encoding="utf-8").read().rstrip("\n"), t)
t = re.sub(r"<<VERBATIM (\S+)>>",
           lambda m: open(m.group(1), encoding="utf-8-sig").read().replace("\r\n", "\n").rstrip("\n"), t)
assert "<<INCLUDE" not in t and "<<VERBATIM" not in t, "unexpanded marker"
open("nwm_parameter_archives.md", "w", encoding="utf-8").write(t)
print("nwm_parameter_archives.md:", len(t.splitlines()), "lines")
