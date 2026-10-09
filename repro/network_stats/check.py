"""Compare results/ with expected/expected.json. Exit 1 on any mismatch.

Also compares results/subrivers.json with expected/subrivers_expected.json (sub-river
statistics, subrivers.py) and results/domains.json with expected/domains_expected.json
(domains.py: AK/HI/PRVI names, lake-outlet renames, sub-rivers), and checks the SHA-256 of
the snapshots subriver_gnis.json (committed) and domains_snapshot.json (release asset).

Tolerances: integers and strings exact; floats relative 1e-6. Domains listed in
expected["_optional"] (the NWM v2.1 comparison) are skipped, with a note, when they are
absent from results (fetch_data.py --required-only).
"""
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTOL = 1e-6


def cmp(path: str, want, have, fails: list, n: list) -> None:
    if isinstance(want, dict):
        for k, v in want.items():
            if not k.startswith("_"):
                cmp(f"{path}.{k}", v, None if not isinstance(have, dict) else have.get(k), fails, n)
        return
    if isinstance(want, list):
        if not isinstance(have, list) or len(have) != len(want):
            n[0] += 1
            fails.append(f"{path}: got {have!r}, expected {want!r}")
            print(f"FAIL {path}: got {have!r}, expected {want!r}")
            return
        for i, (w, h) in enumerate(zip(want, have)):
            cmp(f"{path}[{i}]", w, h, fails, n)
        return
    n[0] += 1
    if isinstance(want, float) and isinstance(have, (int, float)):
        ok = math.isclose(have, want, rel_tol=RTOL, abs_tol=1e-9)
    else:
        ok = have == want
    if not ok:
        fails.append(path)
    print(f"{'ok  ' if ok else 'FAIL'} {path}: got {have!r}, expected {want!r}")


def check_subrivers(fails: list, n: list) -> None:
    """Sub-river statistics (subrivers.py) vs expected/subrivers_expected.json. The GNIS
    snapshot subriver_gnis.json must hash to the recorded SHA-256."""
    exp = json.loads((HERE / "expected" / "subrivers_expected.json").read_text())
    try:
        res = json.loads((HERE / "results" / "subrivers.json").read_text())
    except FileNotFoundError:
        n[0] += 1
        fails.append("subrivers")
        print("FAIL subrivers: results/subrivers.json not found; run subrivers.py first")
        return
    got = {
        "snapshot_sha256": hashlib.sha256((HERE / "subriver_gnis.json").read_bytes()).hexdigest(),
        "n_by_status": res["n_by_status"],
        "great_lakes": res["great_lakes"],
        "rivers": res["rivers"],
        "mississippi_primary_equals_network": res["rivers"]["mississippi"],
    }
    cmp("subrivers", {k: v for k, v in exp.items() if not k.startswith("_")}, got, fails, n)


def check_domains(fails: list, n: list) -> None:
    """Full-domain names, lake-outlet renames, AK/HI/PRVI sub-rivers and lake-inflow sub-rivers
    (domains.py) vs expected/domains_expected.json; the snapshot domains_snapshot.json must
    hash to the recorded SHA-256."""
    p = HERE / "expected" / "domains_expected.json"
    if not p.exists():
        print("skip domains: expected/domains_expected.json not present")
        return
    exp = json.loads(p.read_text())
    try:
        res = json.loads((HERE / "results" / "domains.json").read_text())
    except FileNotFoundError:
        n[0] += 1
        fails.append("domains")
        print("FAIL domains: results/domains.json not found; run domains.py first")
        return
    res["snapshot_sha256_file"] = hashlib.sha256((HERE / "domains_snapshot.json").read_bytes()).hexdigest()
    cmp("domains", {k: v for k, v in exp.items() if not k.startswith("_")}, res, fails, n)


def main() -> int:
    exp = json.loads((HERE / "expected" / "expected.json").read_text())
    try:
        res = json.loads((HERE / "results" / "results.json").read_text())
    except FileNotFoundError:
        print("FAIL: results/results.json not found; run analyze.py first")
        return 1
    D = res["domains"]
    s = D["CONUS"]["scheduling_segments"]
    w = D["CONUS"]["without_ids_ge_1e9"]["pieces"]["626220"]["largest_pieces"]
    got = {
        "domains": {},
        "conus_top": res["top_networks"]["CONUS"][:len(exp["conus_top"])],
        "scheduling": {
            "CONUS_segments_lpt_makespan_pct_P1_to_4": [r["makespan_pct_of_total"] for r in s["lpt_makespan_vs_P"][:4]],
            "CONUS_lpt_smallest_P_with_makespan_equal_largest": s["lpt_smallest_P_with_makespan_equal_largest"]},
        "continuity": {**D["CONUS"]["mainstem_continuity"],
                       "tributaries": {k: {**v, "confluence_flows_to": (v["confluence"] or {}).get("flows_to")}
                                       for k, v in D["CONUS"]["tributaries"].items()}},
        "splits": {"rio_grande_without_ids_ge_1e9": {
            "n_pieces": D["CONUS"]["without_ids_ge_1e9"]["pieces"]["626220"]["n_pieces"],
            "largest_two_outlets": [p["outlet_feature_id"] for p in w[:2]],
            "largest_two_sizes": [p["n_segments"] for p in w[:2]]}},
    }
    for dom, e in exp["domains"].items():
        if dom not in D:
            if dom in exp.get("_optional", []):
                print(f"skip {dom}: optional input not analyzed")
                exp["domains"][dom] = {}
                continue
        g = dict(D.get(dom, {}))
        if g:
            g["n_networks_ge_10000"] = g["n_networks_ge"]["10000"]
            g["ffd_processors_segments"] = g["scheduling_segments"]["ffd_processors_with_capacity_largest"]
            g["ffd_processors_length"] = g["scheduling_length_km"]["ffd_processors_with_capacity_largest"]
            if "ids_ge_1e9" in g:
                g["n_ids_ge_1e9"] = g["ids_ge_1e9"]["n_segments"]
                g["networks_without_ids_ge_1e9"] = g["without_ids_ge_1e9"].get("n_networks")
                g["networks_without_segments_in_canada_mexico"] = g["without_segments_in_canada_mexico"].get("n_networks")
        got["domains"][dom] = g
    fails, n = [], [0]
    cmp("", {k: v for k, v in exp.items() if not k.startswith("_")}, got, fails, n)
    check_subrivers(fails, n)
    check_domains(fails, n)
    print(f"\n{n[0] - len(fails)}/{n[0]} checks passed")
    if fails:
        print("FAILED: " + ", ".join(fails[:20]))
        return 1
    print("PASS: NWM network statistics reproduced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
