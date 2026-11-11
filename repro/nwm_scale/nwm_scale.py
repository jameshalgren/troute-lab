# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Routing-calculation estimate for the NWM: 2020 spreadsheet vs current operations.

Plain calculation. Inputs: segments.csv, configs.csv (each row carries source URL and
retrieval date), and the NOMADS catalog written by catalog_nomads.py
(nomads_catalog.csv, nomads_footprint.csv; read from results/ if present, else from the
committed snapshot in expected/), which is used to cross-check every configs.csv row and to
give the bytes and folders per domain.
Calculations/day = sim-hours/day * 3600/dt * segments.
Run: uv run nwm_scale.py
"""
import csv, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
os.makedirs(OUT, exist_ok=True)
DOMAINS = ["CONUS", "Alaska", "Hawaii", "PuertoRico_USVI"]

def rd(name):
    with open(os.path.join(HERE, name), newline="") as f:
        return list(csv.DictReader(f))

def catalog_file(name):
    """results/<name> if catalog_nomads.py has been run here, else the committed snapshot in expected/."""
    for d in ("results", "expected"):
        if os.path.exists(os.path.join(HERE, d, name)):
            return f"{d}/{name}"
    return None

# 2020 poster spreadsheet (as given by the author): name, hours, cycles/day, members.
# 2020 medium range = 7 members: member 1 at 240 h + members 2-7 at 204 h (NWM v2.0).
Y2020 = [("analysis_assim", 3, 24, 1), ("short_range", 18, 24, 1), ("medium_range_member1", 240, 4, 1),
         ("medium_range_members2-7", 204, 4, 6), ("long_range", 720, 4, 4)]
DT, SEG2020 = 300, 2.7e6

def run2020():
    rows, tot = [], 0
    for n, h, c, m in Y2020:
        sh = h * c * m; rows.append((n, h, c, m, sh)); tot += sh
    steps = tot * 3600 // DT
    return rows, tot, steps, steps * SEG2020

def current(segs, cfgs, conus_seg=None, unique_analysis=False):
    out = []
    for r in cfgs:
        dom = r["domain"]; seg = segs[dom]
        if dom == "CONUS" and conus_seg: seg = conus_seg
        cyc, h = float(r["cycles_per_day"]), float(r["hours_per_cycle"])
        m, dt = int(r["members"]), float(r["dt_s"])
        simh = cyc * h * m
        if unique_analysis and r["config"].startswith("analysis_assim"):
            simh = min(cyc * h, 24.0) if cyc > 1 else h   # count each valid hour once
        steps = simh * 3600 / dt
        out.append(dict(r, cycles_per_day=cyc, sim_hours_per_day=simh, steps_per_day=steps,
                        segments=seg, calcs_per_day=steps * seg))
    return out

def crosscheck(cfgs):
    """Each configs.csv row must equal the channel_rt cycles x hours found on NOMADS."""
    path = catalog_file("nomads_catalog.csv")
    if not path:
        return ["(no nomads_catalog.csv in results/ or expected/: run catalog_nomads.py parse first)"]
    cat = [r for r in rd(path) if r["routing"] == "yes"]
    msgs, used = [], set()
    for r in cfgs:
        dirs = r["nomads_dirs"].split(";")
        h = float(r["hours_per_cycle"])
        hits = [c for c in cat if c["directory"] in dirs and float(c["hours_per_cycle"]) == h]
        seen = sum(int(c["cycles_seen"]) * h for c in hits)
        want = float(r["cycles_per_day"]) * h * int(r["members"])
        used.update((c["directory"], c["cycles"]) for c in hits)
        ok = abs(seen - want) < 1e-6 and all(c["complete"] == "yes" for c in hits)
        if not ok:
            msgs.append(f"MISMATCH {r['domain']} {r['config']}: configs {want:g} sim-h/day, NOMADS {seen:g}")
    for c in cat:
        if (c["directory"], c["cycles"]) not in used:
            msgs.append(f"NOT IN configs.csv: {c['domain']} {c['directory']} cycles {c['cycles']}")
    return msgs or [f"OK: all {len(cfgs)} configs.csv rows match the NOMADS channel_rt catalog "
                    f"`{path}` ({len(cat)} catalog rows, all complete)"]

def fmt(x): return f"{x:,.0f}"
def pct(a, b):
    if not b: return ""
    v = 100 * a / b
    return f"{v:.1f}" if v >= 0.1 or v == 0 else f"{v:.3f}"

def main():
    segrows = rd("segments.csv")
    segs = {r["domain"]: int(r["segments"]) for r in segrows}
    cfgs = rd("configs.csv")
    check = crosscheck(cfgs)
    rows20, tot20, steps20, calc20 = run2020()
    cur = current(segs, cfgs)
    tot = sum(r["calcs_per_day"] for r in cur)
    simh = sum(r["sim_hours_per_day"] for r in cur)
    def subtotal(pred):
        sel = [r for r in cur if pred(r)]
        return sum(r["calcs_per_day"] for r in sel), sum(r["sim_hours_per_day"] for r in sel)
    conus = subtotal(lambda r: r["domain"] == "CONUS")
    no_noda = subtotal(lambda r: "no_da" not in r["config"])
    no_blend = subtotal(lambda r: "blend" not in r["config"])
    lean = subtotal(lambda r: "no_da" not in r["config"] and "blend" not in r["config"])
    alt_conus = sum(r["calcs_per_day"] for r in current(segs, cfgs, conus_seg=2729077))
    uniq = current(segs, cfgs, unique_analysis=True)
    uniq_tot = sum(r["calcs_per_day"] for r in uniq); uniq_simh = sum(r["sim_hours_per_day"] for r in uniq)

    # per-domain shares, with folders/files/bytes from the NOMADS footprint
    fp = {}
    if catalog_file("nomads_footprint.csv"):
        fp = {r["domain"]: r for r in rd(catalog_file("nomads_footprint.csv"))}
    dom = {d: dict(segments=segs[d], simh=0.0, calcs=0.0) for d in DOMAINS}
    for r in cur:
        dom[r["domain"]]["simh"] += r["sim_hours_per_day"]; dom[r["domain"]]["calcs"] += r["calcs_per_day"]
    for d in DOMAINS:
        f = fp.get(d, {})
        for k in ("dirs_all", "dirs_nwm_hydro", "files_channel_rt", "bytes_channel_rt", "files_all", "bytes_all"):
            dom[d][k] = int(f.get(k, 0) or 0)
    T = {k: sum(dom[d][k] for d in DOMAINS) for k in dom["CONUS"]}

    with open(os.path.join(OUT, "table_2020.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["config", "hours_per_cycle", "cycles_per_day", "members", "sim_hours_per_day"])
        w.writerows(rows20)
        w.writerow(["TOTAL", "", "", "", tot20])
    cols = ["domain", "config", "nomads_dirs", "cycles_per_day", "hours_per_cycle", "members", "dt_s",
            "sim_hours_per_day", "steps_per_day", "segments", "calcs_per_day", "status", "how", "dt_source",
            "source_url", "retrieved", "note"]
    with open(os.path.join(OUT, "table_current.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for r in cur: w.writerow({k: (int(r[k]) if k in ("cycles_per_day","sim_hours_per_day","steps_per_day","segments","calcs_per_day") else r[k]) for k in cols})
    dcols = ["domain", "segments", "segments_pct", "sim_hours_per_day", "sim_hours_pct", "calcs_per_day", "calcs_pct",
             "folders", "folders_pct", "routing_folders", "files_channel_rt", "bytes_channel_rt", "bytes_channel_rt_pct",
             "files_all", "bytes_all", "bytes_all_pct"]
    with open(os.path.join(OUT, "domain_shares.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(dcols)
        for d in DOMAINS + ["TOTAL"]:
            x = dom[d] if d != "TOTAL" else T
            w.writerow([d, x["segments"], pct(x["segments"], T["segments"]), int(x["simh"]), pct(x["simh"], T["simh"]),
                        int(x["calcs"]), pct(x["calcs"], T["calcs"]), x["dirs_all"], pct(x["dirs_all"], T["dirs_all"]),
                        x["dirs_nwm_hydro"], x["files_channel_rt"], x["bytes_channel_rt"],
                        pct(x["bytes_channel_rt"], T["bytes_channel_rt"]), x["files_all"], x["bytes_all"],
                        pct(x["bytes_all"], T["bytes_all"])])

    L = []
    L.append("## 2020 spreadsheet reproduced (dt = 300 s, 2.7e6 segments)\n")
    L.append("| Configuration | h/cycle | cycles/day | members | sim-h/day |\n|---|---:|---:|---:|---:|")
    for n, h, c, m, sh in rows20: L.append(f"| {n} | {h} | {c} | {m} | {fmt(sh)} |")
    L.append(f"| **Total** | | | | **{fmt(tot20)}** |\n")
    L.append(f"Steps/day = {fmt(steps20)}; calculations/day = {calc20:.3e}\n")
    L.append("## Current estimate (NOMADS nwm.20261029, NWM v3.1, every file listed; segments per domain)\n")
    L.append("Cross-check: " + "; ".join(check) + "\n")
    L.append("| Domain | Configuration | cycles/day | h/cycle | members | dt (s) | sim-h/day | segments | calcs/day (1e9) | status | dt source |\n|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for r in cur:
        L.append(f"| {r['domain']} | {r['config']} | {r['cycles_per_day']:g} | {r['hours_per_cycle']} | {r['members']} | {r['dt_s']} | {fmt(r['sim_hours_per_day'])} | {fmt(r['segments'])} | {r['calcs_per_day']/1e9:,.3f} | {r['status']} | {r['dt_source']} |")
    L.append(f"| **Total** | | | | | | **{fmt(simh)}** | | **{tot/1e9:,.3f}** | | |\n")
    L.append("## Totals\n")
    L.append("| Quantity | calcs/day | sim-h/day |\n|---|---:|---:|")
    L.append(f"| 2020 spreadsheet | {calc20:.3e} | {fmt(tot20)} |")
    L.append(f"| Current, all domains, all configurations | {tot:.3e} | {fmt(simh)} |")
    L.append(f"| Current, without `_no_da` (open-loop) runs | {no_noda[0]:.3e} | {fmt(no_noda[1])} |")
    L.append(f"| Current, without `_blend` runs | {no_blend[0]:.3e} | {fmt(no_blend[1])} |")
    L.append(f"| Current, without `_no_da` and `_blend` runs | {lean[0]:.3e} | {fmt(lean[1])} |")
    L.append(f"| Current, CONUS only | {conus[0]:.3e} | {fmt(conus[1])} |")
    L.append(f"| Sensitivity: CONUS = 2,729,077 segments (v2.0) | {alt_conus:.3e} | {fmt(simh)} |")
    L.append(f"| Sensitivity: analysis windows counted once per valid hour (no overlap re-run) | {uniq_tot:.3e} | {fmt(uniq_simh)} |")
    L.append(f"| Ratio current / 2020 | {tot/calc20:.2f} | {simh/tot20:.2f} |")
    L.append("\n## By domain: segments vs simulation-hours vs calculations vs NOMADS footprint\n")
    L.append("Folders = top-level directories in the day listing (including forcing and coastal); "
             "routing folders = those with channel_rt output. Bytes are exact (S3 mirror listing), "
             "GB = 1e9 bytes, per day. \"All files\" = model output + forcing + coastal SCHISM for that domain.\n")
    L.append("| Domain | segments | % | sim-h/day | % | calcs/day | % | folders (routing) | % | channel_rt GB | % | all files GB | % |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for d in DOMAINS + ["TOTAL"]:
        x = dom[d] if d != "TOTAL" else T
        b = "**" if d == "TOTAL" else ""
        L.append(f"| {b}{d}{b} | {fmt(x['segments'])} | {pct(x['segments'], T['segments'])} | {fmt(x['simh'])} | {pct(x['simh'], T['simh'])} | "
                 f"{x['calcs']:.3e} | {pct(x['calcs'], T['calcs'])} | {x['dirs_all']} ({x['dirs_nwm_hydro']}) | {pct(x['dirs_all'], T['dirs_all'])} | "
                 f"{x['bytes_channel_rt']/1e9:,.1f} | {pct(x['bytes_channel_rt'], T['bytes_channel_rt'])} | "
                 f"{x['bytes_all']/1e9:,.1f} | {pct(x['bytes_all'], T['bytes_all'])} |")
    oc = {k: sum(dom[d][k] for d in DOMAINS[1:]) for k in ("segments", "simh", "calcs", "dirs_all", "bytes_channel_rt", "bytes_all")}
    L.append(f"| OCONUS (AK+HI+PR) | {fmt(oc['segments'])} | {pct(oc['segments'], T['segments'])} | {fmt(oc['simh'])} | {pct(oc['simh'], T['simh'])} | "
             f"{oc['calcs']:.3e} | {pct(oc['calcs'], T['calcs'])} | {oc['dirs_all']} | {pct(oc['dirs_all'], T['dirs_all'])} | "
             f"{oc['bytes_channel_rt']/1e9:,.1f} | {pct(oc['bytes_channel_rt'], T['bytes_channel_rt'])} | {oc['bytes_all']/1e9:,.1f} | {pct(oc['bytes_all'], T['bytes_all'])} |")
    for k in ("post_processed", "observations"):
        if k in fp:
            L.append(f"\nAlso in the day directory: {k}: {fp[k]['files_all']} files, {int(fp[k]['bytes_all'])/1e9:,.1f} GB.")
    L.append("\nSegments vs channel_rt output: " + "; ".join(
        f"{r['domain']} {int(r['segments']):,} RouteLink reaches, {int(r['channel_rt_feature_ids']):,} feature_id in channel_rt"
        for r in segrows if r.get("channel_rt_feature_ids")))
    open(os.path.join(OUT, "table_current.md"), "w").write("\n".join(L) + "\n")
    print("\n".join(L))
    if any(m.startswith(("MISMATCH", "NOT IN")) for m in check):
        sys.exit(1)

if __name__ == "__main__":
    main()
