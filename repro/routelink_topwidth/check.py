"""Compare results/results.json with expected/expected.json. Exit 1 on any mismatch.

Tolerances: counts and floors exact; percentages +-0.001 points; BtmWdth/TopWdth within
1e-6 of 0.6 for every reach (min and max).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PCT_TOL = 1e-3
RATIO_TOL = 1e-6


def main() -> int:
    exp = json.loads((HERE / "expected" / "expected.json").read_text())["domains"]
    try:
        got = json.loads((HERE / "results" / "results.json").read_text())["domains"]
    except FileNotFoundError:
        print("FAIL: results/results.json not found; run analyze.py first")
        return 1
    fails, n = [], 0
    for dom, e in exp.items():
        g = got.get(dom)
        if g is None:
            fails.append(f"{dom}: missing from results")
            continue
        for key, want in e.items():
            n += 1
            have = g.get(key)
            if key.startswith("pct_"):
                ok = have is not None and abs(have - want) <= PCT_TOL
            elif key == "BtmWdth_over_TopWdth":
                ok = have is not None and abs(have["min"] - want) <= RATIO_TOL and abs(have["max"] - want) <= RATIO_TOL
            else:
                ok = have == want
            print(f"{'ok  ' if ok else 'FAIL'} {dom:5s} {key}: got {have!r}, expected {want!r}")
            if not ok:
                fails.append(f"{dom}.{key}")
    print(f"\n{n - len(fails)}/{n} checks passed")
    if fails:
        print("FAILED: " + ", ".join(fails))
        return 1
    print("PASS: RouteLink TopWdthCC analysis reproduced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
