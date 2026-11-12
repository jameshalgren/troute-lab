"""Title, realization, terminal and closing cards, plus the answer panel (HTML).

All numbers on screen are listed, with their sources, in README.md ("Facts on screen").
"""
import html as _h

FONT = "Helvetica, Arial, sans-serif"
INK, GRAY, BLUE, ACCENT, PAGE = "#111111", "#666666", "#2a78d6", "#c2410c", "#f9f9f7"

BASE_CSS = f"""
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; width: 1280px; height: 720px; overflow: hidden; background: {PAGE}; color: {INK};
  font-family: {FONT}; }}
.wrap {{ position: absolute; inset: 0; padding: 92px 110px; display: flex; flex-direction: column; justify-content: center; }}
.rule {{ width: 120px; height: 4px; background: {BLUE}; margin: 0 0 30px; }}
.kicker {{ font-size: 22px; color: {GRAY}; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 18px; }}
h1 {{ font-size: 56px; line-height: 1.15; font-weight: 700; margin: 0 0 30px; max-width: 1060px; }}
p {{ font-size: 28px; line-height: 1.4; color: #333; margin: 0 0 14px; max-width: 1060px; }}
.small {{ font-size: 19px; color: {GRAY}; }}
.foot {{ position: absolute; left: 110px; right: 110px; bottom: 44px; font-size: 18px; color: {GRAY}; }}
b.blue {{ color: {BLUE}; }} b.acc {{ color: {ACCENT}; }}
"""


def page(body, extra_css=""):
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{BASE_CSS}{extra_css}</style></head><body>{body}</body></html>"


def title_page():
    return page("""
<div class="wrap">
  <div class="kicker">A question to a river network</div>
  <div class="rule"></div>
  <h1>How much land drains to the stream gauge at the Antietam battlefield?</h1>
  <p>Exploring the NWM channel network (the hydrofabric T-Route routes over),
  then asking Claude, working as an agent, to check every source.</p>
</div>
<div class="foot">James Halgren · NWM basin explorer: github.com/jameshalgren/troute-lab</div>
""")


def realization_page():
    return page("""
<div class="wrap">
  <div class="kicker">The partial answer is incomplete</div>
  <div class="rule"></div>
  <h1>Three gauges within 10 km answer three different questions.</h1>
  <p>Marsh Run: <b>49 km²</b>. Antietam Creek: <b>728 km²</b>. The Potomac at Shepherdstown: <b>15,423 km²</b>.</p>
  <p>And the Antietam gauge's own NWM link carries two areas: <b class="blue">728 km²</b> of creek
  and a <b class="acc">16,124 km²</b> attribute. Which number is right?</p>
</div>
<div class="foot">Areas: USGS (published drainage area) and NHDPlusV2 TotDASqKM, checked 2026-10-28.</div>
""")


def closing_page():
    return page("""
<div class="wrap">
  <div class="kicker">The approach</div>
  <div class="rule"></div>
  <h1>Human question → explorer → Claude as an agent, with checkable steps → updated answer</h1>
  <p>The explorer shows the network and flags suspect links. Claude does the legwork:
  fetches, traces, compares, and cites a source for every number. The human asks and decides.</p>
  <p style="margin-top: 26px; font-size: 32px;"><b class="blue">github.com/jameshalgren/troute-lab</b></p>
</div>
<div class="foot">AI-assisted; human-reviewed. Data: NWM v3.1.6 RouteLink · NHDPlusV2 (EPA WATERS) · USGS Water Data and NLDI.
Claude session reconstructed and abridged for this demo.</div>
""")


# ---------------- terminal ----------------
TERM_CSS = f"""
html, body {{ background: #1b1b1a; }}
.win {{ position: absolute; inset: 26px 40px 30px; background: #0f0f0f; border: 1px solid #333; border-radius: 10px; overflow: hidden; }}
.bar {{ height: 34px; background: #222220; display: flex; align-items: center; padding: 0 14px; gap: 8px; }}
.dot {{ width: 12px; height: 12px; border-radius: 50%; background: #555; }}
.bar .t {{ margin-left: 12px; color: #9a9a95; font: 15px {FONT}; }}
.bar .r {{ margin-left: auto; color: #8a8a85; font: 14px {FONT}; }}
#out {{ padding: 16px 22px; font: 19px/1.42 Menlo, "SF Mono", Consolas, monospace; color: #e6e6e1; white-space: pre-wrap; }}
.p {{ color: #8fb8ff; }} .u {{ color: #ffffff; }} .g {{ color: #8a8a85; }} .ok {{ color: #7fd1a8; }}
.w {{ color: #ffb17a; }} .b {{ color: #e6e6e1; font-weight: 700; }} .tool {{ color: #c8a6ff; }}
.cur {{ display: inline-block; width: 11px; height: 21px; background: #e6e6e1; vertical-align: -3px; }}
"""

TERM_JS = """
<script>
const out = () => document.getElementById('out');
let committed = '';
window.term = {
  typing(prefix, t) { out().innerHTML = committed + prefix + t.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '<span class="cur"></span>'; },
  commit(h) { committed += h + '\\n'; out().innerHTML = committed; },
  add(h) { committed += h + '\\n'; out().innerHTML = committed; },
  spin(label, j) { const f = ['✻','✢','✳','✶']; out().innerHTML = committed + (label == null ? '' :
      `<span class="w">${f[j % 4]} ${label}…</span>`); },
  clear() { committed = ''; out().innerHTML = ''; },
};
</script>
"""


def terminal_page():
    body = ("<div class='win'><div class='bar'><span class='dot'></span><span class='dot'></span><span class='dot'></span>"
            "<span class='t'>claude — ~/troute-lab</span><span class='r'>Claude Code · reconstructed, abridged</span></div>"
            "<div id='out'></div></div>" + TERM_JS)
    return page(body, TERM_CSS)


def esc(s):
    return _h.escape(s, quote=False)


PROMPT = ("Which gauges near Sharpsburg, MD, and what does each drain: by USGS, "
          "by NWM routing, and by NHDPlus? Check each source.")

TERMINAL_SCRIPT = [
    ("line", "<span class='g'>~/troute-lab $</span> claude", 1.2),
    ("type", "<span class='p'>&gt;</span> <span class='u'>", PROMPT, 2),
    ("line", "</span>", 1.5),
    ("spin", "Planning", 2.0),
    ("line", "<span class='b'>● Plan</span>", 0.4),
    ("line", "  1. Fetch USGS site info for the gauges near Sharpsburg", 0.6),
    ("line", "  2. Find each gauge's NWM link (RouteLink v3.1.6)", 0.6),
    ("line", "  3. Trace RouteLink upstream; total the routed area", 0.6),
    ("line", "  4. Compare NHDPlusV2 TotDASqKM and DivDASqKM, and the NLDI basin", 0.6),
    ("line", "  5. Flag disagreements; give a source for every number", 5.0),
    ("clear",),
    ("line", "<span class='p'>&gt;</span> <span class='g'>Which gauges near Sharpsburg, MD … Check each source.</span>\n", 0.5),
    ("line", "<span class='tool'>● Fetch</span>(waterservices.usgs.gov/nwis/site ?sites=01617800,01618000,01619500)", 0.3),
    ("spin", "Fetching", 1.0),
    ("line", "<span class='g'>  ⎿</span> 01617800  MARSH RUN AT GRIMES, MD               18.9 mi²\n"
             "    01618000  POTOMAC RIVER AT SHEPHERDSTOWN, WV  5,955 mi²\n"
             "    01619500  ANTIETAM CREEK NEAR SHARPSBURG, MD    281 mi²", 3.5),
    ("line", "<span class='tool'>● Read</span>(explorer/data/places.json)  <span class='g'># RouteLink gauge → NWM link</span>", 0.3),
    ("spin", "Reading", 0.75),
    ("line", "<span class='g'>  ⎿</span> 01617800 → link 5891846   01618000 → link 5894792\n"
             "    01619500 → link 5894726  <span class='w'>⚠ da_mismatch</span>", 3.5),
    ("line", "<span class='tool'>● Bash</span>(uv run … <span class='g'># walk RouteLink upstream of link 5894726</span>)", 0.3),
    ("spin", "Tracing", 1.25),
    ("line", "<span class='g'>  ⎿</span> 255 segments upstream · routed area ≈ <span class='ok'>656 km²</span>", 3.0),
    ("line", "<span class='tool'>● Fetch</span>(NHDPlusV2 flowline, COMID 5894726)", 0.3),
    ("spin", "Fetching", 1.0),
    ("line", "<span class='g'>  ⎿</span> TotDASqKM <span class='w'>16,124 km²</span>   DivDASqKM <span class='ok'>730 km²</span>", 3.0),
    ("line", "<span class='tool'>● Fetch</span>(api.water.usgs.gov/nldi/linked-data/comid/5894726/basin)", 0.3),
    ("spin", "Fetching", 1.0),
    ("line", "<span class='g'>  ⎿</span> basin <span class='w'>16,124 km²</span>  <span class='g'>(follows total-upstream topology)</span>", 3.0),
    ("line", "<span class='tool'>● Bash</span>(uv run … <span class='g'># where does the 16,124 come from?</span>)", 0.3),
    ("spin", "Tracing", 1.25),
    ("line", "<span class='g'>  ⎿</span> 5894756 ArtificialPath, divergence = 2: a minor side channel off the Potomac\n"
             "    → 5894226 → 5894248 → 5894724 → 5894726 (Antietam's last reach)\n"
             "    TotDASqKM gives that channel the whole upper Potomac; RouteLink cuts it off", 7.0),
    ("clear",),
    ("line", "<span class='b'>● Answer</span>  <span class='g'>(every number has a source; checked 2026-10-28)</span>\n", 0.5),
    ("line", "  <span class='g'>Gauge (NWM link)</span>                       <span class='g'>USGS      NWM routed</span>", 0.4),
    ("line", "  Marsh Run at Grimes      (5891846)          49 km²", 0.4),
    ("line", "  Potomac at Shepherdstown (5894792)      15,423 km²", 0.4),
    ("line", "  Antietam Ck nr Sharpsburg (5894726)        728 km²   ≈ 656 km²\n", 1.5),
    ("line", "  For link 5894726, NHDPlusV2 has two areas:", 0.4),
    ("line", "    TotDASqKM  <span class='w'>16,124 km²</span>  counts the upper Potomac through a divergence", 0.6),
    ("line", "    DivDASqKM     <span class='ok'>730 km²</span>  divergence-routed: matches USGS (728)\n", 1.5),
    ("line", "  <span class='b'>Use the divergence-routed area: about 730 km².</span>\n"
             "  <span class='g'>Suggested follow-up: check the explorer's da_mismatch flag against DivDASqKM.</span>", 9.0),
]


def answer_panel(highlight=None):
    hl = ' class="hl"' if highlight == "5894724" else ""
    return f"""
<h4>What drains to USGS 01619500 (NWM link 5894726)?</h4>
<table>
<tr><th>Source</th><th>Area</th></tr>
<tr><td>USGS published drainage area</td><td><b>728 km²</b></td></tr>
<tr><td>NWM RouteLink, routed upstream</td><td>≈ 656 km²</td></tr>
<tr><td>NHDPlusV2 DivDASqKM <span class="id">(divergence-routed)</span></td><td>730 km²</td></tr>
<tr{hl}><td>NHDPlusV2 TotDASqKM <span class="id">(through divergences)</span></td><td class="bad">16,124 km²</td></tr>
<tr><td>USGS NLDI basin <span class="id">(total-upstream)</span></td><td class="bad">16,124 km²</td></tr>
</table>
<div class="foot">Other gauges (USGS): Marsh Run 01617800, 49 km² · Potomac at Shepherdstown 01618000, 15,423 km²</div>
"""
