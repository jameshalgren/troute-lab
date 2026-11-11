"""Record what the switch to the corrected MC kernel changed (2026-10-09), and re-baseline.

    uv run python kernel_update.py [--write]

Until 2026-10-08 this experiment ran T-Route's kernel as published (unpatched). Since
2026-10-09 the default build applies ../kernel_fixes/patches (the corrected kernel). This
script compares every regression value in expected/expected.json and expected/closure.json
(baselines from the unpatched kernel) with the current results, and writes
expected/kernel_update_2026-10-09.json: path, unpatched value, corrected value, change.

--write (once, after a full CLOSURE=1 run.sh with the corrected kernel):
  - keeps the old baselines as expected/expected_unpatched_kernel.json and
    expected/closure_unpatched_kernel.json (check.py uses them when the build's kernel is
    "unpatched", the opt-in comparison path: KERNEL=unpatched run.sh);
  - rewrites expected/expected.json and expected/closure.json with the corrected-kernel
    values (same paths, kinds and tolerances).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE / "expected"
RES = HERE / "results"
OLD_RES = RES / "unpatched_kernel_2026-10-08"


def get(d, path):
    for k in path.split("/"):
        d = d[k]
    return d


def main() -> int:
    write = "--write" in sys.argv
    new = {"expected": json.loads((RES / "results.json").read_text())["cases"]}
    sp = RES / "closure" / "summary.json"
    new["closure"] = json.loads(sp.read_text()) if sp.exists() else None
    out = {"note": "regression values of this experiment with T-Route's kernel as published "
                   "(unpatched, baselines of 2026-10-07/08) and with the corrected kernel "
                   "(../kernel_fixes, 2026-10-09). 'change' = corrected - unpatched.",
           "files": {}}
    for name in ("expected", "closure"):
        src = EXP / f"{name}.json"
        keep = EXP / f"{name}_unpatched_kernel.json"
        base = json.loads((keep if keep.exists() else src).read_text())
        if new[name] is None:
            print(f"note    results for {name} missing; skipped")
            continue
        rows, vals = [], []
        for item in base["values"]:
            try:
                got = get(new[name], item["path"])
            except (KeyError, TypeError):
                got = None
            old = item["value"]
            ch = (got - old) if isinstance(got, (int, float)) and isinstance(old, (int, float)) else None
            rows.append({"path": item["path"], "kind": item["kind"], "unpatched": old, "corrected": got,
                         "change": None if ch is None else float(f"{ch:.6g}")})
            vals.append({**item, "value": got})
        out["files"][name] = rows
        if write:
            if not keep.exists():
                shutil.copy2(src, keep)
                k = json.loads(keep.read_text())
                k["source"] = "UNPATCHED KERNEL (opt-in comparison, KERNEL=unpatched). " + k.get("source", "")
                keep.write_text(json.dumps(k, indent=1) + "\n")
            nb = dict(base)
            nb["source"] = ("Corrected MC kernel (../kernel_fixes/patches 0001-0007), macOS 26 arm64, "
                            "gfortran 15.2.0, rerun 2026-10-09 by Claude (AI) for James Halgren. Same paths, "
                            "kinds and tolerances as the unpatched-kernel baseline in "
                            f"{keep.name}; old -> new values in kernel_update_2026-10-09.json.")
            nb["values"] = vals
            src.write_text(json.dumps(nb, indent=1) + "\n")
            print(f"wrote   expected/{src.name} (old baseline kept in {keep.name})")
    (EXP / "kernel_update_2026-10-09.json").write_text(json.dumps(out, indent=1) + "\n")
    n = sum(len(v) for v in out["files"].values())
    big = [r for v in out["files"].values() for r in v
           if r["change"] is not None and abs(r["change"]) > (0.5 if r["kind"] == "pct" else 0.002 * max(abs(r["unpatched"]), 1e-6))]
    print(f"ok      expected/kernel_update_2026-10-09.json: {n} values, {len(big)} beyond the old tolerance")
    for r in big[:60]:
        print(f"        {r['path']}: {r['unpatched']} -> {r['corrected']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
