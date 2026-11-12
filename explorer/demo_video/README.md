# Demo video: a question to a river network

*AI-assembled (Claude, 2026-10-28); not yet reviewed by the author.*

A silent looping video (about 3.5 min, 1920x1080, 30 fps, H.264) for a table display. The story:
a question ("How much land drains to the stream gauge at the Antietam battlefield?"), an answer
found by exploring the NWM channel network in the basin explorer, the realization that the
answer is incomplete, a (reconstructed, abridged) Claude Code session that checks each source,
and the updated answer. Then a closing card, which fades back into the title so the file loops.

## Play it on a loop

- **QuickTime Player** (macOS): `open troute_lab_demo_loop.mp4`, then View › Loop (⌥⌘L), then
  View › Enter Full Screen.
- **ffplay**: `ffplay -fs -loop 0 troute_lab_demo_loop.mp4` (`-fs` full screen; `q` quits).
- **VLC**: `vlc --loop --fullscreen troute_lab_demo_loop.mp4`.
- **Browser**: open the file and use the video's Loop option (right-click in Chrome).

## Rebuild

Needs [uv](https://docs.astral.sh/uv/), ffmpeg with libx264, and network access (the recorder
drives the hosted explorer at <https://jameshalgren.github.io/troute-lab/>, which has the
full web tileset; a local `explorer/serve.py` needs the web tileset too, via
`explorer/fetch_data.py`).

```sh
uv run --with playwright playwright install chromium     # once
uv run explorer/demo_video/record.py                      # ~10 min -> build/frames/*.png + list.json
uv run explorer/demo_video/assemble.py                    # ~1 min  -> troute_lab_demo_loop.mp4
# local explorer instead of the hosted one:
uv run explorer/demo_video/record.py --url http://localhost:8765/
```

- `record.py` opens the explorer in headless Chromium (1280x720 CSS px at device scale 1.5,
  so type is large at 1080p), adds a caption bar, labels and an answer panel, and drives it:
  river search, selection, places, upstream traces. Camera moves are rendered frame by frame
  (15 frames/s, zooming about the target point). Cards and the terminal come from `cards.py`.
- `assemble.py` blends 0.6 s cross-fades with Pillow and encodes with ffmpeg (concat demuxer,
  `-crf 18 -preset slow`, yuv420p, `+faststart`).
- To change wording or timing: captions and holds are in `record.py`; card text, the terminal
  script and the answer panel are in `cards.py`. Re-run both scripts.

`build/` (frames, ~1-2 GB of PNG) and the MP4 are gitignored.

## Scenes (draft 1: 3:29, 209 s)

| Time | Scene |
|---|---|
| 0:00-0:10 | Title card: the question |
| 0:10-0:17 | Explorer overview (CONUS networks, histogram) |
| 0:17-0:29 | River table search "Potomac"; network #16 lights up with its width function |
| 0:29-0:41 | Full-screen map: zoom from the Potomac basin to Sharpsburg, MD |
| 0:41-0:47 | Three USGS gauges labelled (Antietam Creek, Potomac at Shepherdstown, Marsh Run) |
| 0:47-1:04 | Click the Antietam gauge: link 5894726, upstream trace (orange), zoom out; "first answer" 281 mi² (728 km²) |
| 1:04-1:11 | The explorer's `da_mismatch` flag: NHDPlusV2 TotDASqKM 16,124 km² |
| 1:11-1:25 | Potomac at Shepherdstown: upstream trace, zoom out; 5,955 mi² (15,423 km²) |
| 1:25-1:34 | Card: three gauges, three questions; one link with two areas |
| 1:34-2:37 | Claude Code terminal (reconstructed, abridged): prompt typed, plan, 6 tool steps, answer table |
| 2:37-2:49 | Explorer: updated answer panel (USGS 728 / routed ≈ 656 / DivDASqKM 730 / TotDASqKM 16,124 / NLDI 16,124) |
| 2:49-3:05 | Zoom to the side channel 5894756 → 5894226 → 5894248 → 5894724 (orange) |
| 3:05-3:14 | "About 730 km²: use the divergence-routed area" |
| 3:14-3:29 | Closing card (approach, repo URL, "AI-assisted; human-reviewed"), cross-fade back to the title |

## Facts on screen (checked 2026-10-28)

| On screen | Value | Source |
|---|---|---|
| CONUS RouteLink segments / networks | 2,776,734 / 12,820 | `explorer/README.md` (Methods) |
| Potomac River network | #16, 16,454 segments | `explorer/data/rivers.json` |
| Antietam Creek near Sharpsburg, MD | USGS 01619500, 281 mi² (728 km²) | USGS site service, `waterservices.usgs.gov/nwis/site/?sites=01619500` |
| Potomac River at Shepherdstown, WV | USGS 01618000, 5,955 mi² (15,423 km²) | same |
| Marsh Run at Grimes, MD | USGS 01617800, 18.9 mi² (49 km²) | same |
| RouteLink links of the gauges | 01619500 → 5894726 (order 4, 255 segments upstream); 01618000 → 5894792; 01617800 → 5891846 | `explorer/data/places.json` |
| `da_mismatch` flag on 01619500 | USGS 281 mi² vs NHDPlusV2 TotDASqKm 6,225 mi² (16,124 km²) | `explorer/data/places.json` |
| NHDPlusV2 for COMID 5894726 | TotDASqKM 16,124 km²; DivDASqKM 730 km² | coordinator brief (EPA WATERS NHDPlusV2), not re-fetched here |
| NLDI basin for COMID 5894726 | 16,124 km² | coordinator brief (`api.water.usgs.gov/nldi/linked-data/comid/5894726/basin`) |
| Side channel | 5894756 (ArtificialPath, divergence = 2) → 5894226 → 5894248 → 5894724 → 5894726 | coordinator brief |
| Link 5894724 | order 1; NHDPlus TotDASqKM 15,399 km²; routed ≈ 7 km² | coordinator brief |
| NWM routed area at 5894726 | ≈ 656 km² | coordinator brief |
| Distances | Antietam gauge to Shepherdstown gauge ≈ 6 km; Marsh Run ≈ 8 km | computed from the gauge coordinates |

The Claude Code session on screen is **reconstructed and abridged** (labelled so in its title
bar and on the closing card): the tool calls show the kind of steps taken, and every number in
them is from the table above.

## Extended cut (storyboard only; not built)

James's follow-up idea (2026-10-28): after exploring, he wants to **export a mask and run
T-Route on part of the network**. The explorer has no button for that, so he asks Claude to
build the capability, then exports the mask and runs the simulation. Status: a storyboard,
waiting for James to confirm scope. No run output has been made up; the scenes marked
*needs a real run* should be recorded from an actual run.

Facts for it (from the coordinator, verified 2026-10-28 in CIROH-UA/t-route
[`d29f663`](https://github.com/CIROH-UA/t-route/tree/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6)):
- Mask config keys sit under `network_topology_parameters.supernetwork_parameters`:
  `mask_file_path`, `mask_layer_string`, `mask_driver_string`, `mask_key`
  (`src/troute-config/troute/config/network_topology_parameters.py` L71-78; "Not implemented
  for HYFeatures"). The format is a plain text file with one NWM link ID per line.
- Public example:
  [`test/LowerColorado_TX/test_AnA_V4_NHD.yaml` L13](https://github.com/CIROH-UA/t-route/blob/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6/test/LowerColorado_TX/test_AnA_V4_NHD.yaml),
  `mask_file_path: domain/coastal_subset.txt` (11,248 link IDs).
- Caveat: a mask keeps only the listed links. Inflow from upstream links outside the mask is
  lost, and T-Route at that commit cannot take a boundary inflow series. troute-lab's
  `repro/upstream_inflow_patch` adds `forcing_parameters.upstream_inflow_file` /
  `upstream_inflow_segments` (a clipped run fed the full run's boundary outflow reproduces the
  full run). It is an unmerged proposal for CIROH-UA T-Route.
- Inputs: Potomac RouteLink subset and synthetic-storm qlat from troute-lab
  `repro/short_ts_switch` (`fetch_data.py` + `make_inputs.py`, `potomac_storm` case).

Storyboard (about +2 min, inserted after "Updated answer", or as a separate 2-min video):

| # | Scene | ~s | What is shown |
|---|---|---|---|
| E1 | Card | 8 | "Next question: what does a storm do on Antietam Creek? Route just this part of the network." |
| E2 | Explorer | 10 | Click the Antietam gauge (orange upstream trace, 255 segments). Caption: "There's no button to export this as a T-Route mask." |
| E3 | Terminal | 25 | Prompt: "Add an 'Export mask' button: write the upstream links of the selected point as a T-Route mask_file_path file (one link ID per line). Check T-Route's config docs first." Plan: read `network_topology_parameters.py` (mask keys), the LowerColorado example; add the button (the explorer already has the upstream interval `[p, p+z)`); test that the count equals the trace (255). |
| E4 | Explorer | 12 | *Needs the feature built*: the new "Export mask (255 links)" button; the file `antietam_mask.txt` downloads; first lines shown. |
| E5 | Terminal | 20 | YAML diff: `mask_file_path: antietam_mask.txt`. Claude flags the caveat: Antietam is a headwater sub-basin, so nothing upstream is lost; for a mid-river cut (e.g. above Shepherdstown) the boundary inflow would be lost unless the `upstream_inflow_patch` proposal is used. |
| E6 | Run | 20 | *Needs a real run*: `python -m nwm_routing -f antietam.yaml` log lines, then a hydrograph at link 5894726 (blue line; one gray reference line from the full-Potomac run if available). |
| E7 | Card | 8 | "Explorer → mask → T-Route on part of the network: a capability built in one session, with checkable steps." |

Open choices for James: build the export button for real in `explorer/index.html` first (then
E4 is a real recording), and whether E6 uses the Potomac storm inputs or a T-Route test case.
