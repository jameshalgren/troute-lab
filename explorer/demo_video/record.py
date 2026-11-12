# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright"]
# ///
"""Record the frames of the looping demo video.

Drives the hosted basin explorer (or a local one, --url http://localhost:8765/) in headless
Chromium and renders the title, terminal and closing cards from cards.py. Every frame is a
1920x1080 PNG (1280x720 CSS px at device scale 1.5, so on-screen type is large). Each
frame has a duration; build/frames/list.json records (file, seconds, fade_in) for
assemble.py.

  uv run explorer/demo_video/record.py            # ~5-10 min, needs network
  uv run explorer/demo_video/assemble.py          # -> troute_lab_demo_loop.mp4
"""
import argparse
import asyncio
import json
import math
import time
from pathlib import Path

from playwright.async_api import async_playwright

import cards

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "build" / "frames"
FPS = 30
FLY_FPS = 30  # camera frames per second during flights
VIEW = {"width": 1280, "height": 720}

# Places used on screen (keys in explorer/data/places.json)
ANTIETAM, SHEPHERDSTOWN, MARSH = "usgs:01619500", "usgs:01618000", "usgs:01617800"
SHARPSBURG_VIEW = ([-77.765, 39.475], 11.0)

OVERLAY_CSS = """
body.demo-focus nav.top, body.demo-focus .intro, body.demo-focus #domsw,
body.demo-focus .viz > .panel:nth-child(2), body.demo-focus .selbar, body.demo-focus section,
body.demo-focus footer, body.demo-focus .legend { display: none !important; }
body.demo-focus main { max-width: none; padding: 0; }
body.demo-focus .viz { display: block; }
body.demo-focus .viz > .panel { border: 0; border-radius: 0; }
body.demo-focus #map { height: 100vh; }
body.demo-focus .maplibregl-ctrl-top-right { display: none; }
body.demo-focus .maplibregl-popup-content { font: 17px/1.35 Helvetica, Arial, sans-serif; padding: 10px 14px; }
#demo-cap { position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000; display: none;
  padding: 14px 36px 18px; background: rgba(252,252,251,0.95); border-top: 1px solid #d9d8d2;
  font: 26px/1.3 Helvetica, Arial, sans-serif; color: #111; }
#demo-cap .sub { font-size: 18px; color: #555; margin-top: 4px; }
#demo-cap .step { color: #2a78d6; font-weight: 700; margin-right: 10px; }
#demo-panel { position: fixed; top: 22px; right: 22px; z-index: 1000; display: none; width: 640px;
  background: rgba(252,252,251,0.97); border: 1px solid #c9c8c0; border-radius: 6px; padding: 14px 18px 12px;
  font: 16px/1.35 Helvetica, Arial, sans-serif; color: #111; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }
#demo-panel h4 { margin: 0 0 8px; font-size: 19px; }
#demo-panel table { border-collapse: collapse; width: 100%; }
#demo-panel th, #demo-panel td { padding: 5px 6px; border-bottom: 1px solid #e1e0d9; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
#demo-panel th { color: #555; font-weight: 600; font-size: 14px; position: static; cursor: default; }
#demo-panel th:first-child, #demo-panel td:first-child { text-align: left; white-space: normal; }
#demo-panel td.bad { color: #c2410c; font-weight: 700; }
#demo-panel tr.hl td { background: rgba(235,104,52,0.10); }
#demo-panel .id { color: #777; font-size: 13px; }
#demo-panel .foot { color: #666; font-size: 13px; margin-top: 7px; }
.demo-label { font: 600 17px/1.2 Helvetica, Arial, sans-serif; color: #111; background: rgba(255,255,255,0.92);
  border: 1px solid #bbb; border-radius: 4px; padding: 3px 7px; white-space: nowrap; }
.demo-label .n { color: #555; font-weight: 400; }
"""

OVERLAY_JS = """
() => {
  const st = document.createElement('style'); st.textContent = %s; document.head.appendChild(st);
  const cap = document.createElement('div'); cap.id = 'demo-cap'; document.body.appendChild(cap);
  const pan = document.createElement('div'); pan.id = 'demo-panel'; document.body.appendChild(pan);
  window.demo = {
    markers: [],
    focus(on) { document.body.classList.toggle('demo-focus', on); S.map.resize(); },
    caption(html, sub) { cap.style.display = html ? 'block' : 'none';
      cap.innerHTML = html ? html + (sub ? `<div class="sub">${sub}</div>` : '') : ''; },
    panel(html) { pan.style.display = html ? 'block' : 'none'; pan.innerHTML = html || ''; },
    labels(list) { for (const m of this.markers) m.remove(); this.markers = [];
      for (const L of list) { const el = document.createElement('div'); el.className = 'demo-label'; el.innerHTML = L.text;
        this.markers.push(new maplibregl.Marker({element: el, anchor: L.anchor || 'left', offset: L.offset || [12, 0]}).setLngLat([L.lon, L.lat]).addTo(S.map)); } },
    closePopups() { document.querySelectorAll('.maplibregl-popup').forEach(p => p.remove()); },
  };
}
""" % json.dumps(OVERLAY_CSS)

IDLE_JS = """
async (ms) => { const t0 = performance.now(); const raf = () => new Promise(r => requestAnimationFrame(r));
  S.map.triggerRepaint(); await raf();
  while (!(S.map.loaded() && S.map.areTilesLoaded()) && performance.now() - t0 < ms) await new Promise(r => setTimeout(r, 40));
  await raf(); await raf(); }
"""


class Recorder:
    def __init__(self, page):
        self.page = page
        self.n = 0
        self.items = []  # [file, seconds, fade_in]
        self._fade_next = False

    async def snap(self, seconds, fade=False):
        f = FRAMES / f"f{self.n:05d}.png"
        self.n += 1
        await self.page.screenshot(path=str(f))
        self.items.append([f.name, seconds, fade or self._fade_next])
        self._fade_next = False

    def fade_next(self):
        self._fade_next = True

    def total(self):
        return sum(i[1] for i in self.items)

    def save(self):
        (FRAMES / "list.json").write_text(json.dumps({"fps": FPS, "items": self.items}, indent=0))


def merc(lon, lat):
    x = (lon + 180) / 360
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2
    return x, y


def unmerc(x, y):
    lon = x * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))
    return lon, lat


def ease(t):
    return t * t * (3 - 2 * t)


async def idle(page, ms=6000):
    await page.evaluate(IDLE_JS, ms)


async def camera(page):
    c = await page.evaluate("[S.map.getCenter().lng, S.map.getCenter().lat, S.map.getZoom()]")
    return [c[0], c[1]], c[2]


async def fly(rec, center, zoom, seconds):
    """Zoom about the target point so it stays put on screen (frames rendered one by one)."""
    page = rec.page
    c0, z0 = await camera(page)
    zin = zoom >= z0
    a, b = (c0, z0), (center, zoom)
    if not zin:  # zoom out = zoom in reversed in time
        a, b = b, a
    (ca, za), (cb, zb) = a, b
    ma, mb = merc(*ca), merc(*cb)
    nfr = max(2, round(seconds * FLY_FPS))
    for k in range(nfr):
        t = (k + 1) / nfr
        s = ease(t) if zin else 1 - ease(1 - t)
        u = s if zin else 1 - s  # progress of the zoom-in path
        z = za + (zb - za) * u
        w = 2 ** (-(z - za)) - u * 2 ** (-(zb - za))
        cx, cy = mb[0] + (ma[0] - mb[0]) * w, mb[1] + (ma[1] - mb[1]) * w
        lon, lat = unmerc(cx, cy)
        t0 = time.time()
        await page.evaluate("([c, z]) => { S.map.jumpTo({center: c, zoom: z}); }", [[lon, lat], z])
        t1 = time.time()
        await idle(page, 4000)
        t2 = time.time()
        await rec.snap(1 / FLY_FPS)
        if k < 3 or k % 20 == 0:
            print(f"fly frame {k}/{nfr}: jump {t1-t0:.2f}s idle {t2-t1:.2f}s shot {time.time()-t2:.2f}s", flush=True)


async def place_index(page, key):
    return await page.evaluate("k => S.places.findIndex(p => p.key === k)", key)


async def card(rec, page, html, seconds, fade=True):
    await page.set_content(html)
    await page.wait_for_timeout(150)
    await rec.snap(seconds, fade=fade)


async def terminal(rec, page, script):
    """Play a terminal script: typed prompt, streamed lines, tool results."""
    await page.set_content(cards.terminal_page())
    await page.wait_for_timeout(150)
    first = True
    for step in script:
        kind = step[0]
        if kind == "type":  # ("type", html_prefix, text, chars_per_frame)
            _, prefix, text, cpf = step
            for i in range(0, len(text) + 1, cpf):
                await page.evaluate("([p, t]) => term.typing(p, t)", [prefix, text[:i]])
                await rec.snap(2 / FPS, fade=first)
                first = False
            await page.evaluate("([p, t]) => term.commit(p + t)", [prefix, text])
        elif kind == "line":  # ("line", html, hold)
            await page.evaluate("h => term.add(h)", step[1])
            await rec.snap(step[2], fade=first)
            first = False
        elif kind == "spin":  # ("spin", label, seconds)
            for j in range(int(step[2] * 4)):
                await page.evaluate("([l, j]) => term.spin(l, j)", [step[1], j])
                await rec.snap(0.25)
            await page.evaluate("() => term.spin(null)")
        elif kind == "clear":
            await page.evaluate("() => term.clear()")
        elif kind == "hold":
            await rec.snap(step[1])


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://jameshalgren.github.io/troute-lab/")
    args = ap.parse_args()
    FRAMES.mkdir(parents=True, exist_ok=True)
    for f in FRAMES.glob("f*.png"):
        f.unlink()

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        ctx = await browser.new_context(viewport=VIEW, device_scale_factor=1.5, color_scheme="light")
        cardp = await ctx.new_page()
        ex = await ctx.new_page()
        rec_c = Recorder(cardp)

        # ---------- explorer setup ----------
        await ex.goto(args.url)
        await ex.wait_for_function("typeof S !== 'undefined' && S.mapReady === true", timeout=90000)
        await ex.evaluate(OVERLAY_JS)
        await idle(ex, 15000)
        await ex.wait_for_timeout(2000)
        rec = Recorder(ex)
        rec.items = rec_c.items  # one shared timeline
        rec_c.n = 0

        # shared numbering across the two pages
        class Shared:
            n = 0
        def bind(r):
            async def snap(seconds, fade=False, _r=r):
                f = FRAMES / f"f{Shared.n:05d}.png"
                Shared.n += 1
                await _r.page.screenshot(path=str(f))
                _r.items.append([f.name, seconds, fade or _r._fade_next])
                _r._fade_next = False
            r.snap = snap
        bind(rec)
        bind(rec_c)

        # ---------- 1. title card ----------
        await card(rec_c, cardp, cards.title_page(), 10.0, fade=False)

        # ---------- 2. explore ----------
        await ex.bring_to_front()
        await ex.evaluate("demo.caption('<span class=\"step\">Explore</span>The NWM v3.1.6 channel network (RouteLink): 2.78 million segments in 12,820 independent CONUS networks', 'Basin explorer: jameshalgren.github.io/troute-lab · every river, gauge, forecast point, reservoir, dam and bridge keyed to NWM feature IDs')")
        await idle(ex)
        await rec.snap(7.0, fade=True)

        # search the rivers table for the Potomac
        await ex.evaluate("document.querySelector('#rivers').scrollIntoView({behavior: 'instant'})")
        await ex.evaluate("demo.caption('Search the river table: Potomac', '')")
        await ex.click("#q")
        await rec.snap(1.0)
        for i, ch in enumerate("Potomac"):
            await ex.type("#q", ch)
            await ex.wait_for_timeout(60)
            await rec.snap(0.2)
        await rec.snap(2.0)
        await ex.click('#rt tr[data-code="16"] td.name strong')
        await ex.wait_for_timeout(300)
        await ex.evaluate("demo.caption('Potomac River: network #16 · 16,454 segments', 'Row selected: the network lights up on the map, with its width function')")
        await rec.snap(3.0)
        await ex.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        await ex.wait_for_timeout(1200)
        await idle(ex)
        await rec.snap(5.0)

        # full-screen map on the Potomac, then fly to Sharpsburg
        await ex.evaluate("demo.focus(true); demo.caption('Zoom in: Sharpsburg, Maryland, beside the Antietam National Battlefield', 'Blue: the selected Potomac network · gray: every other NWM segment')")
        await ex.evaluate("(() => { const [w,s,e,n] = S.bboxes[16]; S.map.fitBounds([[w,s],[e,n]], {padding: 40, duration: 0}); })()")
        await idle(ex, 15000)
        await rec.snap(3.0, fade=True)
        await fly(rec, *SHARPSBURG_VIEW, 7.0)
        await rec.snap(2.0)

        # gauges
        ia, ish, im = [await place_index(ex, k) for k in (ANTIETAM, SHEPHERDSTOWN, MARSH)]
        places = await ex.evaluate("ks => ks.map(i => S.places[i])", [ia, ish, im])
        pa, psh, pm = places
        await ex.evaluate("demo.caption('Purple dots: USGS stream gauges, each tagged to an NWM link in RouteLink', 'Three of them within about 10 km of the battlefield')")
        await ex.evaluate("""([a, sh, m]) => demo.labels([
            {lon: a.lon, lat: a.lat, text: 'Antietam Creek <span class="n">01619500</span>'},
            {lon: sh.lon, lat: sh.lat, text: 'Potomac at Shepherdstown <span class="n">01618000</span>', anchor: 'right', offset: [-12, 0]},
            {lon: m.lon, lat: m.lat, text: 'Marsh Run <span class="n">01617800</span>'}])""", places)
        await idle(ex)
        await rec.snap(6.0)

        # select the Antietam gauge: upstream trace
        await ex.evaluate("i => selectPlace(i, {fly: false})", ia)
        await ex.evaluate("demo.labels([])")
        await ex.evaluate("demo.caption('Click the Antietam Creek gauge (USGS 01619500): it sits on NWM link 5894726', 'Orange: every segment upstream of that link in the routed network')")
        await idle(ex)
        await rec.snap(6.0)
        await ex.evaluate("demo.closePopups()")
        await fly(rec, [-77.66, 39.60], 9.2, 5.0)
        await ex.evaluate("demo.caption('<span class=\"step\">First answer</span>USGS says Antietam Creek near Sharpsburg drains 281 mi² (728 km²)', 'The orange network: 255 NWM segments upstream of link 5894726')")
        await rec.snap(6.0)

        # the flag
        await ex.evaluate("i => selectPlace(i, {fly: false})", ia)
        await ex.evaluate("demo.caption('But the explorer flags this gauge: <b>da_mismatch</b>', 'It compares USGS with NHDPlusV2 TotDASqKM for the same link: 16,124 km², a Potomac-sized number')")
        await idle(ex)
        await rec.snap(7.0)
        await ex.evaluate("demo.closePopups()")

        # Shepherdstown
        await ex.evaluate("i => selectPlace(i, {fly: false})", ish)
        await ex.evaluate("demo.closePopups()")
        await ex.evaluate("demo.caption('Six km away: Potomac River at Shepherdstown, WV (USGS 01618000)', 'Upstream of NWM link 5894792: 5,955 mi² (15,423 km²) per USGS')")
        await idle(ex)
        await rec.snap(2.0)
        await fly(rec, [-78.45, 39.15], 7.1, 6.0)
        await rec.snap(6.0)

        # ---------- 3. realization ----------
        await card(rec_c, cardp, cards.realization_page(), 9.0)

        # ---------- 4. Claude ----------
        await terminal(rec_c, cardp, cards.TERMINAL_SCRIPT)

        # ---------- 5. updated answer ----------
        await ex.bring_to_front()
        await ex.evaluate("demo.labels([]); demo.panel(null)")
        await ex.evaluate("i => selectPlace(i, {fly: false})", ia)
        await ex.evaluate("demo.closePopups()")
        await ex.evaluate("([c, z]) => { S.map.jumpTo({center: c, zoom: z}); }", [[-77.72, 39.48], 10.6])
        await ex.evaluate("demo.caption('<span class=\"step\">Updated answer</span>Three gauges, three questions, and one link with two areas', 'USGS = published drainage area · NHDPlus = TotDASqKM of the COMID = NWM link · routed = area upstream in the NWM network')")
        await ex.evaluate("h => demo.panel(h)", cards.answer_panel())
        await ex.evaluate("""([a, sh, m]) => demo.labels([
            {lon: a.lon, lat: a.lat, text: 'Antietam Ck <span class="n">728 km²</span>'},
            {lon: sh.lon, lat: sh.lat, text: 'Potomac <span class="n">15,423 km²</span>', anchor: 'right', offset: [-12, 0]},
            {lon: m.lon, lat: m.lat, text: 'Marsh Run <span class="n">49 km²</span>'}])""", places)
        await idle(ex, 15000)
        await rec.snap(12.0, fade=True)

        # the side channel: minor divergence path off the Potomac into Antietam's last reach
        chain = [5894756, 5894226, 5894248, 5894724]
        found = await ex.evaluate("""(ids) => { const out = {}; for (const k of [0,1,2,3,4,5,6]) { const src = 'flow' + (k || ''); if (!S.map.getSource(src)) continue;
            for (const f of S.map.querySourceFeatures(src, {sourceLayer: 'flow', filter: ['in', ['get', 'id'], ['literal', ids]]})) {
              const g = f.geometry; const cs = g.type === 'LineString' ? g.coordinates : g.coordinates.flat();
              (out[f.properties.id] ||= []).push(...cs); } } return out; }""", chain)
        print("side-channel links found:", {k: len(v) for k, v in found.items()})
        pts = [c for v in found.values() for c in v]
        if pts:
            lons, lats = [c[0] for c in pts], [c[1] for c in pts]
            l24 = found.get("5894724") or found.get(5894724) or pts
            mid = l24[len(l24) // 2]
            await ex.evaluate("ids => { setUpstream({p: null}); setF('flow-seg', ['in', ['get', 'id'], ['literal', ids]]); }", chain)
            await ex.evaluate("demo.labels([{lon: %f, lat: %f, text: 'link 5894724 <span class=\"n\">order 1</span>'}])" % (mid[0], mid[1]))
            await ex.evaluate("demo.caption('Why 16,124? A minor side channel leaves the Potomac at a divergence and joins Antietam Creek’s last reach', 'TotDASqKM credits it with the whole upper Potomac (15,399 km² on order-1 link 5894724; routed: about 7 km²). DivDASqKM and NWM routing do not.')")
            await ex.evaluate("h => demo.panel(h)", cards.answer_panel(highlight="5894724"))
            cx, cy = (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2
            span = max(max(lons) - min(lons), (max(lats) - min(lats)) * 1.3, 0.01)
            z = min(13.5, math.log2(360 / span * 0.45))  # map ~45% of the width
            await fly(rec, [cx + span * 0.35, cy], z, 4.0)
            await rec.snap(12.0)
        await ex.evaluate("demo.caption('<span class=\"step\">Answer</span>About 730 km²: use the divergence-routed area', 'USGS 728 km² · NHDPlusV2 DivDASqKM 730 km² · NWM routed ≈ 656 km². Not ‘NHDPlus is wrong’: it has two attributes, and the question picks one.')")
        await rec.snap(9.0)

        # ---------- 6. closing ----------
        await card(rec_c, cardp, cards.closing_page(), 15.0)
        # last item fades into the first frame (the title) at assembly time
        rec.items.append([rec.items[0][0], 0.0, True])  # marker: loop fade
        rec.save()
        print(f"{Shared.n} frames, {rec.total():.1f} s")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
