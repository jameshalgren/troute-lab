"""Named sub-river (tributary) statistics for the NWM v3.1.6 CONUS RouteLink.

For every candidate river in the candidate list (encoded
below in CANDIDATES), find its MOUTH segment from NHDPlus V2 GNIS names and compute the
statistics of the subtree upstream of the mouth (the same definitions as analyze.py).

    uv run --locked python subrivers.py            # offline: uses committed subriver_gnis.json
    uv run --locked python subrivers.py --refresh  # live USGS queries; rewrites subriver_gnis.json

Inputs: data/RouteLink_CONUS.nc, results/networks_CONUS.csv (from analyze.py), and
subriver_gnis.json, a committed snapshot of USGS geoserver WFS queries
(layer wmadata:nhdflowline_network, the layer behind NLDI; see river_names.py):
  * per GNIS name: the COMIDs (grouped by VPU) of every NHDPlus V2 flowline with exactly
    that gnis_name; the WFS 1.1.0 `resultType=hits` count is stored with it and must
    equal the number of features returned (no truncation);
  * per COMID: gnis_name, for the segments walked downstream of each mouth.
In offline mode every lookup must be in the snapshot (otherwise: error, rerun --refresh).
The snapshot's SHA-256 is checked by check.py against expected/subrivers_expected.json.

Mouth rule (details in README "Sub-rivers" and in follow()/resolve() below):
  1. Named set: RouteLink segments whose NHDPlus V2 COMID has a gnis_name in the
     candidate's `names` (a union), within the candidate's VPUs.
  2. Scope: the subtree of the parent's mouth (the whole network for a parent that is
     its own network). An optional bounding box (`box`) on the mouth location encodes
     the list's state/city qualifiers; boxes are interpretations, listed in the README.
  3. Components: named segments are joined to the next named segment downstream across
     at most GAP other segments; a component's root is its most-downstream segment.
  4. Mouth: from the root, move downstream along own-named segments, along the root's
     NHDPlus level path (blank or non-candidate names), or through blank / non-NHDPlus
     segments with exactly one upstream segment (see follow()).
  5. Receiving river ("joins"): the name of the segment below the mouth, else the most
     frequent name on its level path, else the first name walking down (a "gap").
  6. Choice: the largest component (of the MAX_EVAL largest) whose receiving river is
     the listed parent; otherwise the largest in scope, with the river it joins
     reported. Status: confident | gap | not_in_parent | UNVERIFIED (ambiguous: a second
     qualifying component with >= AMBIG of the chosen one's segments).
  Primary rivers (own networks): the largest component in the VPUs; if nothing named
  lies below its mouth, the network outlet is used; the network's rank is reported.

Outputs: results/subrivers.csv, results/subrivers.json, results/T_subrivers_rows.md.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

from analyze import BIG_ID, DATA, RESULTS, WB_MISSING, graph, load, traverse

HERE = Path(__file__).resolve().parent
SNAP = HERE / "subriver_gnis.json"
WFS10 = ("https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.0.0&request=GetFeature"
         "&typeName=wmadata:nhdflowline_network&outputFormat=application/json")
WFS11_HITS = ("https://api.water.usgs.gov/geoserver/wmadata/ows?service=WFS&version=1.1.0&request=GetFeature"
              "&typeName=wmadata:nhdflowline_network&resultType=hits")
GAP = 15        # max unnamed segments bridged when joining named segments into one river
WALK = 400      # max segments walked downstream from a mouth to find the receiving river
MAX_EVAL = 8    # components (largest first) whose receiving river is looked up
AMBIG = 0.25    # a 2nd qualifying component this large (relative) makes the row ambiguous
GREAT_LAKES = ["maumee", "saginaw", "grand_mi", "fox_wi", "genesee", "cuyahoga", "rouge", "milwaukee"]
ST_LAWRENCE_OUTLET = 25293410

# Bounding boxes (lat_min, lat_max, lon_min, lon_max) on the mouth location. They encode
# the candidate list's qualifiers (state / city); they are interpretations, not data.
BOX = {
    "MO": (35.9, 40.7, -95.8, -89.1), "IN": (37.7, 41.8, -88.1, -84.7), "KY": (36.4, 39.2, -89.6, -81.9),
    "WI": (42.4, 47.1, -92.9, -86.7), "MI": (41.6, 46.0, -87.2, -82.3), "NE": (39.9, 43.1, -104.1, -95.3),
    "KC": (38.8, 39.4, -94.8, -94.2), "Memphis": (34.9, 35.4, -90.3, -89.6), "Denver": (39.5, 40.0, -105.3, -104.7),
    "Seattle": (47.0, 47.8, -122.6, -121.0), "OH": (38.3, 42.0, -84.9, -80.5), "NY": (40.4, 45.1, -79.8, -71.8),
    "VA": (36.5, 39.5, -83.7, -75.2), "TX": (25.8, 36.6, -106.7, -93.5), "MIL": (42.9, 43.2, -88.1, -87.8),
    "Detroit": (42.1, 42.6, -83.5, -83.0), "Cleveland": (41.3, 41.6, -81.8, -81.5),
}


def C(key, label, names, parent, source, vpus, group, box=None, joins=None, kind="sub", city=None, note=None,
      above=None, scope=None):
    return dict(key=key, label=label, names=names, parent=parent, source=source, vpus=vpus, group=group,
                box=box, joins=joins, kind=kind, city=city, note=note, above=above, scope=scope)


# Candidate list (2026-10-06). `source`:
# JH = author's list; AI = AI suggestion; city = the "rivers important to major cities"
# section (AI suggestions the author asked for); "AI; JH-endorsed" = Yampa/White.
# Parents come first (each candidate's scope is its parent's subtree).
CANDIDATES = [
    # ---- primary networks that act as parents
    C("mississippi", "Mississippi", ["Mississippi River"], None, "parent", ["07", "08"], "Mississippi system", kind="primary"),
    C("columbia", "Columbia", ["Columbia River"], None, "parent", ["17"], "Pacific", kind="primary"),
    C("colorado", "Colorado", ["Colorado River"], None, "parent", ["14", "15"], "Colorado system", kind="primary"),
    C("rio_grande", "Rio Grande", ["Rio Grande"], None, "parent", ["13"], "Gulf rivers", kind="primary"),
    C("mobile", "Mobile", ["Mobile River"], None, "parent", ["03"], "Gulf rivers", kind="primary"),
    C("apalachicola", "Apalachicola", ["Apalachicola River"], None, "parent", ["03"], "Gulf rivers", kind="primary"),
    C("sacramento", "Sacramento", ["Sacramento River"], None, "parent", ["18"], "Pacific", kind="primary"),
    C("san_joaquin", "San Joaquin", ["San Joaquin River"], None, "parent (AI)", ["18"], "Pacific", kind="primary"),
    C("susquehanna", "Susquehanna", ["Susquehanna River"], None, "parent", ["02"], "Atlantic / Great Lakes", kind="primary"),
    C("st_lawrence", "St. Lawrence", ["Saint Lawrence River"], None, "parent", ["04"], "Atlantic / Great Lakes", kind="primary"),
    C("potomac", "Potomac", ["Potomac River"], None, "city (parent)", ["02"], "Atlantic / Great Lakes", kind="primary"),
    C("delaware", "Delaware", ["Delaware River"], None, "city (parent)", ["02"], "Atlantic / Great Lakes", kind="primary"),
    C("hudson", "Hudson", ["Hudson River"], None, "city (parent)", ["02"], "Atlantic / Great Lakes", kind="primary"),
    C("santee", "Santee", ["Santee River"], None, "city (parent)", ["03"], "Atlantic / Great Lakes", kind="primary"),
    C("atchafalaya", "Atchafalaya", ["Atchafalaya River", "Lower Atchafalaya River"], None, "parent (data)", ["08"],
      "Mississippi system", kind="primary", note="added: the RouteLink network that holds the Red River (south)"),
    C("trinity", "Trinity (TX)", ["Trinity River"], None, "city", ["12"], "Primary networks", kind="primary",
      city="Dallas-Fort Worth"),
    C("guadalupe", "Guadalupe", ["Guadalupe River"], None, "city", ["12"], "Primary networks", kind="primary",
      box=BOX["TX"], city="San Antonio"),
    # ---- Mississippi system
    C("ohio", "Ohio", ["Ohio River"], "mississippi", "JH", ["05"], "Mississippi system"),
    C("missouri", "Missouri", ["Missouri River"], "mississippi", "JH", ["10"], "Mississippi system"),
    C("upper_mississippi", "Upper Mississippi", ["Mississippi River"], "mississippi", "JH", ["07"], "Mississippi system",
      above="ohio", note="Mississippi River above the Ohio confluence (Cairo)"),
    C("illinois", "Illinois", ["Illinois River"], "mississippi", "JH", ["07"], "Mississippi system"),
    C("red_south", "Red (south)", ["Red River"], "mississippi", "JH", ["11", "08"], "Mississippi system",
      scope="atchafalaya"),
    C("arkansas", "Arkansas", ["Arkansas River"], "mississippi", "JH", ["11", "08"], "Mississippi system"),
    C("yazoo", "Yazoo", ["Yazoo River"], "mississippi", "AI", ["08"], "Mississippi system"),
    C("white_ar", "White (AR)", ["White River"], "mississippi", "AI", ["11", "08"], "Mississippi system"),
    C("st_francis", "St. Francis", ["Saint Francis River"], "mississippi", "AI", ["08", "11"], "Mississippi system"),
    C("minnesota", "Minnesota", ["Minnesota River"], "mississippi", "AI", ["07"], "Mississippi system"),
    C("wisconsin", "Wisconsin", ["Wisconsin River"], "mississippi", "AI", ["07"], "Mississippi system"),
    C("rock", "Rock", ["Rock River"], "mississippi", "AI", ["07"], "Mississippi system"),
    C("des_moines", "Des Moines", ["Des Moines River"], "mississippi", "AI", ["07"], "Mississippi system"),
    C("iowa", "Iowa (with Cedar)", ["Iowa River"], "mississippi", "AI", ["07"], "Mississippi system"),
    C("st_croix", "St. Croix", ["Saint Croix River"], "mississippi", "AI", ["07"], "Mississippi system"),
    C("chippewa_wi", "Chippewa (WI)", ["Chippewa River"], "mississippi", "AI", ["07"], "Mississippi system", box=BOX["WI"]),
    C("meramec", "Meramec", ["Meramec River"], "mississippi", "city", ["07"], "Mississippi system", city="St. Louis"),
    C("wolf_tn", "Wolf (TN)", ["Wolf River"], "mississippi", "city", ["08"], "Mississippi system", box=BOX["Memphis"],
      city="Memphis"),
    # Ohio
    C("tennessee", "Tennessee", ["Tennessee River"], "ohio", "AI", ["06"], "Mississippi system",
      note="listed under both Mississippi and Ohio (AI); it joins the Ohio at Paducah"),
    C("cumberland", "Cumberland", ["Cumberland River"], "ohio", "JH", ["05"], "Mississippi system"),
    C("wabash", "Wabash", ["Wabash River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("green_ky", "Green (KY)", ["Green River"], "ohio", "AI", ["05"], "Mississippi system", box=BOX["KY"]),
    C("kentucky", "Kentucky", ["Kentucky River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("kanawha", "Kanawha", ["Kanawha River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("scioto", "Scioto", ["Scioto River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("muskingum", "Muskingum", ["Muskingum River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("great_miami", "Great Miami", ["Great Miami River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("allegheny", "Allegheny", ["Allegheny River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("monongahela", "Monongahela", ["Monongahela River"], "ohio", "AI", ["05"], "Mississippi system"),
    C("licking_ky", "Licking (KY)", ["Licking River"], "ohio", "city", ["05"], "Mississippi system", box=BOX["KY"],
      city="Cincinnati"),
    C("little_miami", "Little Miami", ["Little Miami River"], "ohio", "city", ["05"], "Mississippi system", city="Cincinnati"),
    C("salt_ky", "Salt (KY)", ["Salt River"], "ohio", "city", ["05"], "Mississippi system", box=BOX["KY"], city="Louisville"),
    C("white_in", "White (IN)", ["White River"], "wabash", "city", ["05"], "Mississippi system", box=BOX["IN"],
      city="Indianapolis"),
    C("olentangy", "Olentangy", ["Olentangy River"], "scioto", "city", ["05"], "Mississippi system", city="Columbus (OH)"),
    C("harpeth", "Harpeth", ["Harpeth River"], "cumberland", "city", ["05"], "Mississippi system", city="Nashville"),
    C("stones", "Stones", ["Stones River"], "cumberland", "city", ["05"], "Mississippi system", city="Nashville"),
    C("youghiogheny", "Youghiogheny", ["Youghiogheny River"], "monongahela", "city", ["05"], "Mississippi system",
      city="Pittsburgh"),
    # Tennessee
    C("clinch", "Clinch", ["Clinch River"], "tennessee", "AI", ["06"], "Mississippi system"),
    C("holston", "Holston", ["Holston River"], "tennessee", "AI", ["06"], "Mississippi system"),
    C("french_broad", "French Broad", ["French Broad River"], "tennessee", "AI", ["06"], "Mississippi system"),
    # Missouri
    C("platte", "Platte", ["Platte River"], "missouri", "JH", ["10"], "Mississippi system", box=BOX["NE"]),
    C("north_platte", "North Platte", ["North Platte River"], "platte", "JH", ["10"], "Mississippi system"),
    C("south_platte", "South Platte", ["South Platte River"], "platte", "JH", ["10"], "Mississippi system"),
    C("yellowstone", "Yellowstone", ["Yellowstone River"], "missouri", "JH", ["10"], "Mississippi system"),
    C("milk", "Milk", ["Milk River"], "missouri", "JH", ["10"], "Mississippi system"),
    C("marias", "Marias", ["Marias River"], "missouri", "JH", ["10"], "Mississippi system", note='author wrote "Maria"'),
    C("kansas", "Kansas", ["Kansas River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("osage", "Osage", ["Osage River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("grand_mo", "Grand (MO)", ["Grand River"], "missouri", "AI", ["10"], "Mississippi system", box=BOX["MO"]),
    C("niobrara", "Niobrara", ["Niobrara River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("cheyenne", "Cheyenne", ["Cheyenne River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("james_sd", "James (SD/ND)", ["James River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("big_sioux", "Big Sioux", ["Big Sioux River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("little_missouri", "Little Missouri", ["Little Missouri River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("musselshell", "Musselshell", ["Musselshell River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("jefferson", "Jefferson", ["Jefferson River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("madison", "Madison", ["Madison River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("gallatin", "Gallatin", ["Gallatin River"], "missouri", "AI", ["10"], "Mississippi system"),
    C("blue_mo", "Blue (MO)", ["Blue River"], "missouri", "city", ["10"], "Mississippi system", box=BOX["KC"],
      city="Kansas City"),
    # Yellowstone
    C("bighorn", "Bighorn", ["Bighorn River"], "yellowstone", "AI", ["10"], "Mississippi system"),
    C("powder", "Powder", ["Powder River"], "yellowstone", "AI", ["10"], "Mississippi system"),
    C("tongue", "Tongue", ["Tongue River"], "yellowstone", "AI", ["10"], "Mississippi system"),
    # South Platte (Denver area)
    C("clear_creek_co", "Clear Creek (CO)", ["Clear Creek"], "south_platte", "JH; city", ["10"], "Mississippi system",
      box=BOX["Denver"], city="Denver"),
    C("cherry_creek", "Cherry Creek", ["Cherry Creek"], "south_platte", "city", ["10"], "Mississippi system",
      box=BOX["Denver"], city="Denver"),
    C("bear_creek_co", "Bear Creek (CO)", ["Bear Creek"], "south_platte", "city", ["10"], "Mississippi system",
      box=BOX["Denver"], city="Denver"),
    C("st_vrain", "St. Vrain", ["Saint Vrain Creek"], "south_platte", "city", ["10"], "Mississippi system",
      city="Boulder", note="added as the parent of Boulder Creek"),
    C("boulder_creek", "Boulder Creek", ["Boulder Creek"], "st_vrain", "city", ["10"], "Mississippi system", city="Boulder"),
    C("cache_la_poudre", "Cache la Poudre", ["Cache la Poudre River"], "south_platte", "city", ["10"], "Mississippi system",
      city="Fort Collins"),
    # Arkansas
    C("canadian", "Canadian", ["Canadian River"], "arkansas", "AI", ["11"], "Mississippi system"),
    C("cimarron", "Cimarron", ["Cimarron River"], "arkansas", "AI", ["11"], "Mississippi system"),
    C("verdigris", "Verdigris", ["Verdigris River"], "arkansas", "AI", ["11"], "Mississippi system"),
    C("neosho", "Neosho (Grand)", ["Neosho River", "Grand River"], "arkansas", "AI", ["11"], "Mississippi system"),
    C("fountain_creek", "Fountain Creek", ["Fountain Creek"], "arkansas", "city", ["11"], "Mississippi system",
      city="Colorado Springs / Pueblo"),
    C("north_canadian", "North Canadian", ["North Canadian River"], "canadian", "city", ["11"], "Mississippi system",
      city="Oklahoma City"),
    # Red (south)
    C("washita", "Washita", ["Washita River"], "red_south", "AI", ["11"], "Mississippi system"),
    C("sulphur", "Sulphur", ["Sulphur River"], "red_south", "AI", ["11"], "Mississippi system"),
    C("ouachita_black", "Ouachita / Black", ["Ouachita River", "Black River"], "red_south", "AI", ["08", "11"],
      "Mississippi system"),
    # Illinois (Chicago)
    C("des_plaines", "Des Plaines", ["Des Plaines River"], "illinois", "city", ["07"], "Mississippi system", city="Chicago"),
    C("kankakee", "Kankakee", ["Kankakee River"], "illinois", "city", ["07"], "Mississippi system", city="Chicago"),
    C("dupage", "DuPage", ["DuPage River", "Du Page River"], "illinois", "city", ["07"], "Mississippi system", city="Chicago"),
    C("chicago", "Chicago River (Sanitary and Ship Canal)",
      ["Chicago Sanitary and Ship Canal", "North Branch Chicago River", "South Branch Chicago River", "Chicago River"],
      "illinois", "city", ["07"], "Mississippi system", city="Chicago",
      note='no flowline is named "Chicago River" in the NHDPlus V2 layer; the canal and the North Branch are'),
    C("cedar_ia", "Cedar (IA)", ["Cedar River"], "iowa", "AI", ["07"], "Mississippi system",
      note='"Iowa (with Cedar)" in the list; Cedar computed separately'),
    # ---- Gulf rivers
    C("alabama", "Alabama", ["Alabama River"], "mobile", "JH", ["03"], "Gulf rivers"),
    C("tombigbee", "Tombigbee", ["Tombigbee River"], "mobile", "JH", ["03"], "Gulf rivers"),
    C("black_warrior", "Black Warrior", ["Black Warrior River"], "mobile", "JH", ["03"], "Gulf rivers"),
    C("cahaba", "Cahaba", ["Cahaba River"], "mobile", "JH", ["03"], "Gulf rivers"),
    C("coosa", "Coosa", ["Coosa River"], "mobile", "AI", ["03"], "Gulf rivers"),
    C("tallapoosa", "Tallapoosa", ["Tallapoosa River"], "mobile", "AI", ["03"], "Gulf rivers"),
    C("chattahoochee", "Chattahoochee", ["Chattahoochee River"], "apalachicola", "AI; city", ["03"], "Gulf rivers",
      city="Atlanta"),
    C("flint", "Flint", ["Flint River"], "apalachicola", "AI", ["03"], "Gulf rivers"),
    C("pecos", "Pecos", ["Pecos River"], "rio_grande", "AI", ["13"], "Gulf rivers"),
    C("rio_chama", "Rio Chama", ["Rio Chama"], "rio_grande", "AI", ["13"], "Gulf rivers"),
    C("devils", "Devils", ["Devils River"], "rio_grande", "AI", ["13"], "Gulf rivers"),
    # ---- Colorado system
    C("gila", "Gila", ["Gila River"], "colorado", "JH", ["15"], "Colorado system"),
    C("san_juan", "San Juan", ["San Juan River"], "colorado", "JH", ["14"], "Colorado system"),
    C("eagle", "Eagle (CO)", ["Eagle River"], "colorado", "JH", ["14"], "Colorado system"),
    C("green_ut", "Green (UT/WY)", ["Green River"], "colorado", "AI", ["14"], "Colorado system"),
    C("gunnison", "Gunnison", ["Gunnison River"], "colorado", "AI", ["14"], "Colorado system"),
    C("dolores", "Dolores", ["Dolores River"], "colorado", "AI", ["14"], "Colorado system"),
    C("little_colorado", "Little Colorado", ["Little Colorado River"], "colorado", "AI", ["15"], "Colorado system"),
    C("virgin", "Virgin", ["Virgin River"], "colorado", "AI", ["15"], "Colorado system"),
    C("bill_williams", "Bill Williams", ["Bill Williams River"], "colorado", "AI", ["15"], "Colorado system"),
    C("las_vegas_wash", "Las Vegas Wash", ["Las Vegas Wash"], "colorado", "city", ["15"], "Colorado system",
      city="Las Vegas"),
    C("salt_az", "Salt (AZ)", ["Salt River"], "gila", "JH", ["15"], "Colorado system"),
    C("verde", "Verde", ["Verde River"], "gila", "AI", ["15"], "Colorado system", joins=["Salt River"],
      note="the list says Verde joins the Salt"),
    C("san_pedro", "San Pedro", ["San Pedro River"], "gila", "AI", ["15"], "Colorado system"),
    C("santa_cruz_az", "Santa Cruz (AZ)", ["Santa Cruz River"], "gila", "city", ["15"], "Colorado system", city="Tucson"),
    C("agua_fria", "Agua Fria", ["Agua Fria River"], "gila", "city", ["15"], "Colorado system", city="Phoenix"),
    C("new_az", "New (AZ)", ["New River"], "gila", "city", ["15"], "Colorado system", city="Phoenix"),
    C("animas", "Animas", ["Animas River"], "san_juan", "JH", ["14"], "Colorado system"),
    C("yampa", "Yampa", ["Yampa River"], "green_ut", "AI; JH-endorsed", ["14"], "Colorado system"),
    C("white_ut", "White (UT/CO)", ["White River"], "green_ut", "AI; JH-endorsed", ["14"], "Colorado system"),
    C("duchesne", "Duchesne", ["Duchesne River"], "green_ut", "AI", ["14"], "Colorado system"),
    C("price", "Price", ["Price River"], "green_ut", "AI", ["14"], "Colorado system"),
    C("san_rafael", "San Rafael", ["San Rafael River"], "green_ut", "AI", ["14"], "Colorado system"),
    # ---- Pacific
    C("snake", "Snake", ["Snake River"], "columbia", "AI", ["17"], "Pacific"),
    C("willamette", "Willamette", ["Willamette River"], "columbia", "AI", ["17"], "Pacific"),
    C("yakima", "Yakima", ["Yakima River"], "columbia", "AI", ["17"], "Pacific"),
    C("deschutes", "Deschutes", ["Deschutes River"], "columbia", "AI", ["17"], "Pacific"),
    C("john_day", "John Day", ["John Day River"], "columbia", "AI", ["17"], "Pacific"),
    C("spokane", "Spokane", ["Spokane River"], "columbia", "AI", ["17"], "Pacific"),
    C("pend_oreille", "Pend Oreille", ["Pend Oreille River"], "columbia", "AI", ["17"], "Pacific"),
    C("kootenai", "Kootenai", ["Kootenai River"], "columbia", "AI", ["17"], "Pacific"),
    C("okanogan", "Okanogan", ["Okanogan River"], "columbia", "AI", ["17"], "Pacific"),
    C("cowlitz", "Cowlitz", ["Cowlitz River"], "columbia", "AI", ["17"], "Pacific"),
    C("salmon_id", "Salmon (ID)", ["Salmon River"], "snake", "AI", ["17"], "Pacific"),
    C("clearwater", "Clearwater", ["Clearwater River"], "snake", "AI", ["17"], "Pacific"),
    C("owyhee", "Owyhee", ["Owyhee River"], "snake", "AI", ["17"], "Pacific"),
    C("boise", "Boise", ["Boise River"], "snake", "AI", ["17"], "Pacific"),
    C("payette", "Payette", ["Payette River"], "snake", "AI", ["17"], "Pacific"),
    C("henrys_fork", "Henrys Fork", ["Henrys Fork"], "snake", "AI", ["17"], "Pacific"),
    C("clackamas", "Clackamas", ["Clackamas River"], "willamette", "city", ["17"], "Pacific", city="Portland (OR)"),
    C("tualatin", "Tualatin", ["Tualatin River"], "willamette", "city", ["17"], "Pacific", city="Portland (OR)"),
    C("feather", "Feather", ["Feather River"], "sacramento", "JH", ["18"], "Pacific"),
    C("american", "American", ["American River", "North Fork American River", "South Fork American River"],
      "sacramento", "JH", ["18"], "Pacific",
      note='no VPU-18 flowline is named "American River" in the NHDPlus V2 layer; found via the North/South Forks'),
    C("pit", "Pit", ["Pit River"], "sacramento", "AI", ["18"], "Pacific"),
    C("yuba", "Yuba", ["Yuba River"], "sacramento", "AI", ["18"], "Pacific"),
    C("mccloud", "McCloud", ["McCloud River"], "sacramento", "AI", ["18"], "Pacific"),
    C("merced", "Merced", ["Merced River"], "san_joaquin", "AI", ["18"], "Pacific"),
    C("tuolumne", "Tuolumne", ["Tuolumne River"], "san_joaquin", "AI", ["18"], "Pacific"),
    C("stanislaus", "Stanislaus", ["Stanislaus River"], "san_joaquin", "AI", ["18"], "Pacific"),
    C("mokelumne", "Mokelumne", ["Mokelumne River"], "san_joaquin", "AI", ["18"], "Pacific"),
    # ---- Atlantic / Great Lakes
    C("west_branch_susq", "West Branch Susquehanna", ["West Branch Susquehanna River"], "susquehanna", "AI", ["02"],
      "Atlantic / Great Lakes"),
    C("juniata", "Juniata", ["Juniata River"], "susquehanna", "AI", ["02"], "Atlantic / Great Lakes"),
    C("chemung", "Chemung", ["Chemung River"], "susquehanna", "AI", ["02"], "Atlantic / Great Lakes"),
    C("anacostia", "Anacostia", ["Anacostia River"], "potomac", "city", ["02"], "Atlantic / Great Lakes",
      city="Washington, DC"),
    C("schuylkill", "Schuylkill", ["Schuylkill River"], "delaware", "city", ["02"], "Atlantic / Great Lakes",
      city="Philadelphia"),
    C("mohawk", "Mohawk", ["Mohawk River"], "hudson", "city", ["02"], "Atlantic / Great Lakes", city="New York / Albany"),
    C("catawba_wateree", "Catawba (Wateree)", ["Catawba River", "Wateree River"], "santee", "city", ["03"],
      "Atlantic / Great Lakes", city="Charlotte"),
    C("genesee", "Genesee", ["Genesee River"], "st_lawrence", "AI", ["04"], "Atlantic / Great Lakes", box=BOX["NY"]),
    C("maumee", "Maumee", ["Maumee River"], "st_lawrence", "AI", ["04"], "Atlantic / Great Lakes"),
    C("fox_wi", "Fox (WI)", ["Fox River"], "st_lawrence", "AI", ["04"], "Atlantic / Great Lakes", box=BOX["WI"]),
    C("saginaw", "Saginaw", ["Saginaw River"], "st_lawrence", "AI", ["04"], "Atlantic / Great Lakes"),
    C("grand_mi", "Grand (MI)", ["Grand River"], "st_lawrence", "AI", ["04"], "Atlantic / Great Lakes", box=BOX["MI"]),
    C("cuyahoga", "Cuyahoga", ["Cuyahoga River"], "st_lawrence", "city", ["04"], "Atlantic / Great Lakes",
      city="Cleveland"),
    C("rouge", "Rouge (MI)", ["River Rouge", "Rouge River"], "st_lawrence", "city", ["04"], "Atlantic / Great Lakes",
      box=BOX["Detroit"], city="Detroit"),
    C("milwaukee", "Milwaukee", ["Milwaukee River"], "st_lawrence", "city", ["04"], "Atlantic / Great Lakes",
      box=BOX["WI"], city="Milwaukee"),
    # ---- city sub-rivers of Texas primaries (group label only; parents are primaries above)
    C("west_fork_trinity", "West Fork Trinity", ["West Fork Trinity River"], "trinity", "city", ["12"],
      "Texas (city rivers)", city="Dallas-Fort Worth"),
    C("elm_fork_trinity", "Elm Fork Trinity", ["Elm Fork Trinity River"], "trinity", "city", ["12"],
      "Texas (city rivers)", city="Dallas-Fort Worth"),
    C("san_antonio", "San Antonio", ["San Antonio River"], "guadalupe", "city", ["12"], "Texas (city rivers)",
      city="San Antonio"),
    # ---- primary networks: city rivers and "primary networks to check alongside"
    C("red_north", "Red River of the North", ["Red River of the North"], None, "AI (check)", ["09"], "Primary networks",
      kind="primary"),
    C("rainy", "Rainy", ["Rainy River"], None, "AI (check)", ["09"], "Primary networks", kind="primary"),
    C("souris", "Souris", ["Souris River"], None, "AI (check)", ["09"], "Primary networks", kind="primary"),
    C("connecticut", "Connecticut", ["Connecticut River"], None, "AI (check)", ["01"], "Primary networks", kind="primary"),
    C("savannah", "Savannah", ["Savannah River"], None, "AI (check)", ["03"], "Primary networks", kind="primary"),
    C("brazos", "Brazos", ["Brazos River"], None, "AI (check)", ["12"], "Primary networks", kind="primary"),
    C("colorado_tx", "Colorado (TX)", ["Colorado River"], None, "AI (check); city", ["12"], "Primary networks",
      kind="primary", city="Austin"),
    C("klamath", "Klamath", ["Klamath River"], None, "AI (check)", ["18"], "Primary networks", kind="primary"),
    C("rogue", "Rogue", ["Rogue River"], None, "AI (check)", ["17"], "Primary networks", kind="primary"),
    C("humboldt", "Humboldt", ["Humboldt River"], None, "AI (check)", ["16"], "Primary networks", kind="primary"),
    C("truckee", "Truckee", ["Truckee River"], None, "AI (check); city", ["16"], "Primary networks", kind="primary",
      city="Reno"),
    C("bear_ut", "Bear (UT/ID/WY)", ["Bear River"], None, "AI (check); city", ["16"], "Primary networks",
      kind="primary", city="Salt Lake City"),
    C("jordan", "Jordan (UT)", ["Jordan River"], None, "city", ["16"], "Primary networks", kind="primary",
      city="Salt Lake City"),
    C("weber", "Weber", ["Weber River"], None, "city", ["16"], "Primary networks", kind="primary", city="Salt Lake City"),
    C("san_jacinto", "San Jacinto", ["San Jacinto River"], None, "city", ["12"], "Primary networks", kind="primary",
      city="Houston"),
    C("buffalo_bayou", "Buffalo Bayou", ["Buffalo Bayou"], None, "city", ["12"], "Primary networks", kind="primary",
      city="Houston"),
    C("cedar_wa", "Cedar (WA)", ["Cedar River"], None, "city", ["17"], "Primary networks", kind="primary",
      box=BOX["Seattle"], city="Seattle"),
    C("green_duwamish", "Green-Duwamish", ["Green River", "Duwamish River", "Duwamish Waterway"], None, "city", ["17"],
      "Primary networks", kind="primary", box=BOX["Seattle"], city="Seattle"),
    C("los_angeles", "Los Angeles", ["Los Angeles River"], None, "city", ["18"], "Primary networks", kind="primary",
      city="Los Angeles"),
    C("san_gabriel", "San Gabriel", ["San Gabriel River"], None, "city", ["18"], "Primary networks", kind="primary",
      city="Los Angeles"),
    C("santa_ana", "Santa Ana", ["Santa Ana River"], None, "city", ["18"], "Primary networks", kind="primary",
      city="Los Angeles"),
    C("san_diego", "San Diego", ["San Diego River"], None, "city", ["18"], "Primary networks", kind="primary",
      city="San Diego"),
    C("patapsco", "Patapsco", ["Patapsco River"], None, "city", ["02"], "Primary networks", kind="primary",
      city="Baltimore"),
    C("charles", "Charles", ["Charles River"], None, "city", ["01"], "Primary networks", kind="primary", city="Boston"),
    C("merrimack", "Merrimack", ["Merrimack River"], None, "city", ["01"], "Primary networks", kind="primary",
      city="Boston"),
    C("james_va", "James (VA)", ["James River"], None, "city", ["02"], "Primary networks", kind="primary",
      box=BOX["VA"], city="Richmond"),
]


# ----------------------------------------------------------------------------- USGS lookups
def _get(url: str, as_json: bool = True, tries: int = 4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "troute-paper-repro/1.0"})
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
            return json.loads(body) if as_json else body.decode()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry ({e})", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError


def _q(cql: str) -> str:
    return urllib.parse.quote(cql, safe="'(),=")


class Gnis:
    """GNIS lookups: live (refresh=True, recorded) or from the committed snapshot."""

    def __init__(self, refresh: bool):
        self.refresh = refresh
        if refresh:
            self.snap = {"generated": dt.date.today().isoformat(), "service": WFS10, "names": {}, "comid_attrs": {}, "levelpath_names": {}}
        else:
            if not SNAP.exists():
                raise SystemExit(f"{SNAP.name} missing; run `subrivers.py --refresh`")
            self.snap = json.loads(SNAP.read_text())

    def name_comids(self, name: str) -> dict[str, list[int]]:
        rec = self.snap["names"].get(name)
        if rec is None:
            if not self.refresh:
                raise SystemExit(f"GNIS name {name!r} not in {SNAP.name}; run `subrivers.py --refresh`")
            cql = f"gnis_name='{name}'"
            url = f"{WFS10}&propertyName=comid,vpuid&CQL_FILTER={_q(cql)}"
            feats = _get(url)["features"]
            hits_xml = _get(f"{WFS11_HITS}&CQL_FILTER={_q(cql)}", as_json=False)
            hits = int(hits_xml.split('numberOfFeatures="')[1].split('"')[0])
            if hits != len(feats):
                raise SystemExit(f"{name!r}: WFS returned {len(feats)} of {hits} features (truncated)")
            by = collections.defaultdict(list)
            for f in feats:
                by[f["properties"]["vpuid"]].append(int(f["properties"]["comid"]))
            rec = {"cql": cql, "hits": hits, "comids_by_vpu": {k: sorted(v) for k, v in sorted(by.items())}}
            self.snap["names"][name] = rec
            print(f"  GNIS {name!r}: {hits} flowlines")
        return rec["comids_by_vpu"]

    def levelpath_names(self, lp: int) -> dict[str, int]:
        """Counts of GNIS names ('' = blank) on one NHDPlus level path (mainstem)."""
        cache = self.snap["levelpath_names"]
        if str(lp) not in cache:
            if not self.refresh:
                raise SystemExit(f"level path {lp} not in {SNAP.name}; run `subrivers.py --refresh`")
            url = f"{WFS10}&propertyName=comid,gnis_name&CQL_FILTER={_q(f'levelpathi IN ({lp})')}"
            cnt = collections.Counter((f["properties"]["gnis_name"] or "").strip() for f in _get(url)["features"])
            cache[str(lp)] = dict(cnt.most_common())
        return cache[str(lp)]

    def comid_attrs(self, comids: list[int]) -> dict[int, tuple | None]:
        """(gnis_name ('' if blank), levelpathi, totdasqkm) per COMID; None if not in NHDPlus V2."""
        cn = self.snap["comid_attrs"]
        need = [c for c in comids if c < BIG_ID and str(c) not in cn]
        if need:
            if not self.refresh:
                raise SystemExit(f"COMIDs {need[:5]}... not in {SNAP.name}; run `subrivers.py --refresh`")
            for k in range(0, len(need), 100):
                chunk = need[k:k + 100]
                cql = f"comid IN ({','.join(map(str, chunk))})"
                url = f"{WFS10}&propertyName=comid,gnis_name,levelpathi,totdasqkm&CQL_FILTER={_q(cql)}"
                got = {int(f["properties"]["comid"]): [(f["properties"]["gnis_name"] or "").strip(),
                                                       int(f["properties"]["levelpathi"] or 0) or None,
                                                       round(float(f["properties"]["totdasqkm"] or 0), 1)]
                       for f in _get(url)["features"]}
                for c in chunk:
                    cn[str(c)] = got.get(c)
        return {c: (None if c >= BIG_ID or cn[str(c)] is None else tuple(cn[str(c)])) for c in comids}

    def save(self) -> None:
        self.snap["comid_attrs"] = dict(sorted(self.snap["comid_attrs"].items(), key=lambda kv: int(kv[0])))
        # keep the COMIDs only for the VPUs some candidate searches with that name; the
        # per-VPU counts of all hits stay (their sum equals the WFS hits count)
        used = collections.defaultdict(set)
        for cand in CANDIDATES:
            for nm in cand["names"]:
                used[nm].update(cand["vpus"])
        for nm, rec in self.snap["names"].items():
            if "vpu_counts" not in rec:
                rec["vpu_counts"] = {k: len(v) for k, v in rec["comids_by_vpu"].items()}
            rec["comids_by_vpu"] = {k: v for k, v in rec["comids_by_vpu"].items()
                                    if any(k.startswith(u) for u in used[nm])}
        self.snap["names"] = dict(sorted(self.snap["names"].items()))
        self.snap["levelpath_names"] = dict(sorted(self.snap["levelpath_names"].items(), key=lambda kv: int(kv[0])))
        self.snap["_about"] = ("Snapshot of USGS geoserver WFS queries (wmadata:nhdflowline_network = NHDPlus V2) "
                               "made by subrivers.py --refresh. names: per exact gnis_name, the WFS 1.1.0 hits count, "
                               "the number of flowlines per VPU, and the COMIDs in the VPUs that subrivers.py searches. comid_attrs: [gnis_name, levelpathi, totdasqkm] per COMID "
                               "('' = blank name, null = COMID not in the layer). levelpath_names: GNIS name counts "
                               "per level path.")
        c = lambda v: json.dumps(v, separators=(",", ":"))  # noqa: E731
        lines = ["{"]
        for k in ("_about", "generated", "service"):
            lines.append(f"{json.dumps(k)}: {json.dumps(self.snap[k])},")
        for i, k in enumerate(("names", "comid_attrs", "levelpath_names")):
            items = [f"{json.dumps(kk)}: {c(vv)}" for kk, vv in self.snap[k].items()]
            lines.append(f"{json.dumps(k)}: {{\n" + ",\n".join(items) + "\n}" + ("," if i < 2 else ""))
        lines.append("}")
        SNAP.write_text("\n".join(lines) + "\n")


# ----------------------------------------------------------------------------- graph
class Net:
    def __init__(self, d: dict):
        self.d = d
        self.link = d["link"]
        ds, indeg, up_order, up_ptr, _ = graph(d["link"], d["to"])
        net, depth, dist, rcount = traverse(ds, indeg, up_order, up_ptr, d["length_m"])
        self.ds, self.indeg, self.up_order, self.up_ptr = ds, indeg, up_order, up_ptr
        self.net, self.depth, self.dist, self.rcount = net, depth, dist, rcount
        n = ds.size
        # subtree sizes, deepest level first
        size = np.ones(n, np.int64)
        order = np.argsort(-depth, kind="stable")
        for idx in np.split(order, np.flatnonzero(np.diff(depth[order])) + 1):
            if depth[idx[0]] > 0:
                np.add.at(size, ds[idx], size[idx])
        self.size = size
        # pre-order index (tin): subtree of v = nodes with tin in [tin[v], tin[v] + size[v])
        tin = np.zeros(n, np.int64)
        outl = np.flatnonzero(ds < 0)
        tin[outl] = np.cumsum(size[outl]) - size[outl]
        front = outl
        while front.size:
            counts = indeg[front]
            if counts.sum() == 0:
                break
            starts = up_ptr[front]
            offs = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
            ups = up_order[np.repeat(starts, counts) + offs]
            par = np.repeat(front, counts)
            s = size[ups]
            cs = np.cumsum(s) - s
            grp0 = np.repeat(np.cumsum(counts) - counts, counts)
            tin[ups] = tin[par] + 1 + (cs - cs[grp0])
            front = ups
        self.tin = tin
        self.by_tin = np.empty(n, np.int64)
        self.by_tin[tin] = np.arange(n)
        self.outlet_of = outl[net]  # outlet index of every segment
        srt = np.argsort(self.link)
        self._srt, self._sorted = srt, self.link[srt]

    def idx(self, comids) -> np.ndarray:
        c = np.asarray(comids, np.int64)
        pos = np.clip(np.searchsorted(self._sorted, c), 0, self._sorted.size - 1)
        hit = self._sorted[pos] == c
        return self._srt[pos[hit]]

    def in_subtree(self, nodes: np.ndarray, root: int) -> np.ndarray:
        t = self.tin[nodes]
        return (t >= self.tin[root]) & (t < self.tin[root] + self.size[root])

    def subtree(self, v: int) -> np.ndarray:
        return self.by_tin[self.tin[v]:self.tin[v] + self.size[v]]

    def stats(self, v: int) -> dict:
        d = self.d
        s = self.subtree(v)
        ind = self.indeg[s]
        wb = d["wb"][s]
        return {
            "n_segments": int(s.size),
            "n_reaches": int((ind != 1).sum()),
            "length_km": float(d["length_m"][s].sum() / 1000),
            "max_order": int(d["order"][s].max()),
            "longest_path_segments": int((self.depth[s] - self.depth[v]).max() + 1),
            "longest_path_reaches": int((self.rcount[s] - self.rcount[v]).max() + 1),
            "longest_path_km": float((self.dist[s] - self.dist[v] + d["length_m"][v]).max() / 1000),
            "n_headwaters": int((ind == 0).sum()),
            "n_gages": int(d["gage"][s].sum()),
            "n_waterbodies": int(np.unique(wb[wb != WB_MISSING]).size),
        }


# ----------------------------------------------------------------------------- resolution
def components(g: Net, nodes: np.ndarray) -> list[np.ndarray]:
    """Group named segments into rivers: join each to the first named segment within GAP+1
    steps downstream. Returns the roots (most-downstream member) with member counts."""
    named = set(int(i) for i in nodes)
    parent = {i: i for i in named}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in named:
        j, k = int(g.ds[i]), 0
        while j >= 0 and k <= GAP:
            if j in named:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b
                break
            j, k = int(g.ds[j]), k + 1
    groups = collections.defaultdict(list)
    for i in named:
        groups[find(i)].append(i)
    out = []
    for mem in groups.values():
        mem = np.array(mem)
        root = int(mem[np.argmin(g.depth[mem])])
        out.append((root, mem.size))
    out.sort(key=lambda r: -g.size[r[0]])
    return out


def follow(g: Net, gn: Gnis, root: int, own: set[str]) -> dict:
    """Mouth and receiving river of the named component whose most-downstream member is `root`.

    Walking downstream from the root, a segment is still part of the river if
      (a) its GNIS name is one of the river's own names, or
      (b) it is on the root's NHDPlus level path (mainstem) and is blank-named, or carries
          a name that is not one of the candidate-list names (KNOWN), e.g. the
          artificial paths labelled "Big Bayou" on the lower Wabash, or
      (c) it is blank-named or not in NHDPlus V2, and has exactly one upstream segment
          (no other inflow can have joined).
    The mouth is the last such segment; D is the segment below it. The receiving river
    ("joins") is D's GNIS name, or, if D is blank, the most frequent name on D's NHDPlus
    level path. If D is not in NHDPlus or its level path is unnamed, the first name met
    walking down is used and the segments in between are reported as a gap. `chain`
    lists the distinct names met walking down (at most WALK segments)."""
    walk, j = [], int(g.ds[root])
    while j >= 0 and len(walk) < WALK:
        walk.append(j)
        j = int(g.ds[j])
    at = gn.comid_attrs([int(g.link[root])] + [int(g.link[w]) for w in walk])
    a0 = at[int(g.link[root])]
    lp0 = a0[1] if a0 else None
    ext, other_names = 0, []
    for k, w in enumerate(walk):
        a = at[int(g.link[w])]
        if a is None:
            ok = g.indeg[w] == 1
        else:
            nm, lp = a[0], a[1]
            ok = (nm in own or (lp0 is not None and lp == lp0 and (nm == "" or nm not in KNOWN))
                  or (nm == "" and g.indeg[w] == 1))
            if ok and nm and nm not in own:
                other_names.append(nm)
        if not ok:
            break
        ext = k + 1
    mouth = walk[ext - 1] if ext else root
    chain = []
    for w in walk[ext:]:
        a = at[int(g.link[w])]
        if a and a[0] and a[0] not in own and (not chain or chain[-1] != a[0]):
            chain.append(a[0])
    joins, via, steps, junctions = None, None, None, 0
    if ext < len(walk):
        dn = walk[ext]
        a = at[int(g.link[dn])]
        if a and a[0]:
            joins, via, steps = a[0], "name of the segment below the mouth", 1
        elif a and a[1]:
            cnt = {k: v for k, v in gn.levelpath_names(a[1]).items() if k}
            if cnt:
                joins, via, steps = max(cnt, key=cnt.get), "most frequent name on the level path below the mouth", 1
        if joins is None:  # walk down to the first name; segments in between are a gap
            for kk in range(ext, len(walk)):
                w = walk[kk]
                b = at[int(g.link[w])]
                if b and b[0] and b[0] not in own:
                    joins, via, steps = b[0], "first name walking down (gap)", kk + 1 - ext
                    break
                if g.indeg[w] > 1:
                    junctions += 1
    am = at.get(int(g.link[mouth]))
    return {"mouth": mouth, "extended": ext, "joins": joins, "joins_via": via, "joins_steps": steps,
            "junctions_before_joins": junctions, "chain": chain[:6], "levelpathi": lp0,
            "nhdplus_totdasqkm_at_mouth": am[2] if am else None,
            "renamed_on_mainstem": sorted(set(other_names)), "mouth_is_outlet": bool(g.ds[mouth] < 0)}


def in_box(g: Net, i: int, box) -> bool:
    if box is None:
        return True
    la, lo = g.d["lat"][i], g.d["lon"][i]
    return box[0] <= la <= box[1] and box[2] <= lo <= box[3]


def named_nodes(g: Net, gn: Gnis, cand: dict) -> np.ndarray:
    comids = []
    for nm in cand["names"]:
        for vpu, cs in gn.name_comids(nm).items():
            if any(vpu.startswith(v) for v in cand["vpus"]):
                comids += cs
    return g.idx(sorted(set(comids)))


def _loc(g: Net, i: int) -> str:
    return f"{g.d['lat'][i]:.3f}, {g.d['lon'][i]:.3f}"


def resolve(g: Net, gn: Gnis, cand: dict, res: dict) -> dict:
    own = set(cand["names"])
    out = {"key": cand["key"], "status": "UNVERIFIED", "issues": []}
    if cand["above"]:  # e.g. Upper Mississippi: same name, above the sibling's confluence
        sib = res[cand["above"]]
        conf = int(g.ds[sib["_mouth"]])
        ups = g.up_order[g.up_ptr[conf]:g.up_ptr[conf + 1]]
        at = gn.comid_attrs([int(g.link[u]) for u in ups] + [int(g.link[conf])])
        nm = lambda i: (at[int(g.link[i])] or ("",))[0]  # noqa: E731
        hits = [int(u) for u in ups if u != sib["_mouth"] and nm(u) in own]
        if len(hits) == 1 and nm(conf) in own:
            out.update(_mouth=hits[0], status="confident", joins=nm(conf), joins_steps=1, chain=[nm(conf)],
                       joins_via="name of the confluence segment",
                       nhdplus_totdasqkm_at_mouth=(at[int(g.link[hits[0]])] or (0, 0, None))[2],
                       extended=0, junctions_before_joins=0, mouth_is_outlet=False, n_components=1,
                       method=f"the {sorted(own)[0]} segment entering confluence segment {int(g.link[conf])} "
                              f"(where the {CAND[cand['above']]['label']} joins)")
        else:
            out["issues"].append("could not identify the same-named upstream branch at the confluence")
        return out

    nodes = named_nodes(g, gn, cand)
    if cand["kind"] == "primary":
        comps = [c for c in components(g, nodes) if in_box(g, c[0], cand["box"])] if nodes.size else []
        if not comps:
            out["issues"].append("no named segments found in RouteLink")
            return out
        root = comps[0][0]
        f = follow(g, gn, root, own)
        out.update(n_components=len(comps), **{k: v for k, v in f.items() if k != "mouth"})
        # nothing else named below the river: the river is its network's mainstem -> use the outlet
        if f["joins"] in own:
            f["joins"] = None
        out["_mouth"] = int(g.outlet_of[f["mouth"]]) if f["joins"] is None else f["mouth"]
        out["status"] = "confident"
        out["method"] = ("largest named component in VPU(s) " + ",".join(cand["vpus"]) +
                         (" and box" if cand["box"] else ""))
        if f["joins"] is not None:
            out["issues"].append(f"drains into {f['joins']!r} ({f['joins_steps']} segments below), "
                                 f"i.e. into a network named for another river")
        if len(comps) > 1 and g.size[comps[1][0]] >= AMBIG * g.size[root] and g.outlet_of[comps[1][0]] != g.outlet_of[root]:
            out["status"] = "UNVERIFIED"
            out["issues"].append(f"ambiguous: another '{cand['names'][0]}' with {g.size[comps[1][0]]} segments at "
                                 f"{_loc(g, comps[1][0])}")
        return out

    scope_key = cand["scope"] or cand["parent"]
    par = res[scope_key]
    if "_mouth" not in par:
        out["issues"].append(f"parent {scope_key} unresolved")
        return out
    scope_root = int(g.outlet_of[par["_mouth"]]) if par["kind"] == "primary" else par["_mouth"]
    expected = set(cand["joins"] or []) | set(CAND[cand["parent"]]["names"]) | set(CAND[scope_key]["names"])
    in_scope = nodes[g.in_subtree(nodes, scope_root)] if nodes.size else nodes
    comps = [c for c in components(g, in_scope) if in_box(g, c[0], cand["box"])] if in_scope.size else []
    if not comps:
        # not inside the parent: report the largest named component in the VPUs (box applied)
        comps = [c for c in components(g, nodes) if in_box(g, c[0], cand["box"])] if nodes.size else []
        if not comps:
            out["issues"].append(f"no '{'/'.join(cand['names'])}' flowline found in RouteLink (VPU "
                                 f"{','.join(cand['vpus'])})")
            return out
        root = comps[0][0]
        f = follow(g, gn, root, own)
        out.update(_mouth=f["mouth"], n_components=len(comps), status="not_in_parent",
                   method="largest named component in the VPU(s); none inside the parent's "
                          + ("network" if par["kind"] == "primary" else "subtree"),
                   **{k: v for k, v in f.items() if k != "mouth"})
        out["issues"].append(f"not inside the listed parent's {'network' if par['kind'] == 'primary' else 'subtree'}")
        return out
    evals = [(root, nmem, follow(g, gn, root, own)) for root, nmem in comps[:MAX_EVAL]]
    direct = [e for e in evals if e[2]["joins"] in expected]
    out["n_components"] = len(comps)
    pool = direct if direct else evals
    root, nmem, f = pool[0]
    out["status"] = "confident"
    out["method"] = ("largest named component in scope that flows directly into the expected river" if direct else
                     "largest named component in scope (it reaches the parent via another river)")
    if len(pool) > 1 and g.size[pool[1][0]] >= AMBIG * g.size[root]:
        out["status"] = "UNVERIFIED"
        out["issues"].append("ambiguous: " + "; ".join(
            f"another component ({e[2]['joins']}) with {g.size[e[0]]} segments at {_loc(g, e[0])}"
            for e in pool[1:3] if g.size[e[0]] >= AMBIG * g.size[root]))
    elif len(pool) > 1:
        out["also"] = [f"{g.size[e[0]]} seg at {_loc(g, e[0])}" for e in pool[1:4]]
    if not direct:
        out["issues"].append(f"joins the {f['joins']}" + (f" ({f['joins_via']})" if f["joins_via"] and
                             f["joins_via"].startswith("most") else "") + ", not directly the "
                             + "/".join(sorted(expected)) + "; names met further down: " + " -> ".join(f["chain"][:4]))
    if f["junctions_before_joins"] > 0 and out["status"] == "confident":
        out["status"] = "gap"
        out["issues"].append(f"{f['joins_steps'] - 1} unnamed segments ({f['junctions_before_joins']} junctions) "
                             f"between the mouth and the {f['joins']}; their inflows are not counted")
    if cand["scope"]:
        out["issues"].append(f"listed parent is the {CAND[cand['parent']]['label']}; in RouteLink it lies in the "
                             f"{CAND[cand['scope']]['label']} network")
    out.update(_mouth=f["mouth"], **{k: v for k, v in f.items() if k != "mouth"})
    return out


CAND = {c["key"]: c for c in CANDIDATES}
KNOWN = {n for c in CANDIDATES for n in c["names"]}


TABLE_COLS = ["group", "label", "kind", "parent_label", "share_of", "source", "city", "status", "mouth_feature_id",
              "mouth_lat", "mouth_lon", "joins", "n_segments", "pct_parent", "pct_network", "pct_conus", "n_reaches",
              "length_km", "max_order", "longest_path_segments", "longest_path_reaches", "longest_path_km",
              "n_headwaters", "n_gages", "n_waterbodies", "parent_mouth_feature_id", "network_outlet_feature_id",
              "network_rank", "network_name", "network_segments", "mouth_steps_to_outlet",
              "nhdplus_totdasqkm_at_mouth", "notes"]


def _pct(x) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "–"
    return f"{x:.2f}" if x < 1 else f"{x:.1f}"


def _notes(r: dict, res: dict) -> str:
    out = []
    st = r["status"]
    if st == "not_in_parent":
        out.append(f"**Not inside the {r['parent_label']} in RouteLink**: its own network (rank {r['network_rank']}, "
                   f"outlet {r['network_outlet_feature_id']})")
    if st == "gap":
        out.append("**Gap**: " + [i for i in res["issues"] if "unnamed segments" in i][0])
    if st == "UNVERIFIED":
        out.append("**UNVERIFIED**: " + "; ".join(res["issues"]))
    if r["kind"] == "sub" and r.get("joins") and st != "not_in_parent":
        exp = set(CAND[r["key"]]["joins"] or []) | set(CAND[CAND[r["key"]]["parent"]]["names"])
        if r["joins"] not in exp:
            out.append(f"joins the {r['joins']}" + (" (NHDPlus level-path name below the mouth)"
                                                     if (r.get("joins_via") or "").startswith("most") else "")
                       + (f"; downstream names: {r['chain']}" if r.get("chain") and r["chain"] != r["joins"] else ""))
    if r["kind"] == "primary":
        if r.get("joins"):
            out.append(f"drains into the {r['joins']}; network '{r['network_name']}' (rank {r['network_rank']})")
        else:
            out.append(f"network rank {r['network_rank']}")
    if CAND[r["key"]]["scope"]:
        out.append(f"listed under the {r['parent_label']}; in RouteLink the Red joins the Atchafalaya, a separate "
                   f"network (rank {r['network_rank']}); % is of that network")
    if r.get("renamed_on_mainstem"):
        out.append(f"mainstem segments also named {r['renamed_on_mainstem']}")
    if r.get("also_named"):
        out.append(f"smaller same-named rivers also join: {r['also_named']}")
    if CAND[r["key"]]["box"] is not None:
        out.append("location qualifier applied")
    if r.get("note"):
        out.append(r["note"])
    if r.get("city"):
        out.append(f"city: {r['city']}")
    return "; ".join(out)


def md_rows(df: pd.DataFrame) -> str:
    lines = []
    subs = df[df["kind"] == "sub"]
    for grp in dict.fromkeys(subs["group"]):
        lines.append(f"\n### {grp}\n")
        lines.append("| Sub-river | Parent | Mouth feature_id | Segments (% of parent / % CONUS) | Reaches | Channel km "
                     "| Max order | Longest path (reaches / km) | Source | Notes |")
        lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|---|")
        g = subs[subs["group"] == grp]
        for par in dict.fromkeys(g["parent_label"]):
            for r in g[g["parent_label"] == par].to_dict("records"):
                if pd.isna(r.get("mouth_feature_id")):
                    lines.append(f"| {r['label']} | {par} | – | – | – | – | – | – | {r['source']} | {r['notes']} |")
                    continue
                lines.append(
                    f"| {r['label']} | {par} | {int(r['mouth_feature_id'])} | {int(r['n_segments']):,} "
                    f"({_pct(r['pct_parent'] if r['status'] != 'not_in_parent' else None)} / {_pct(r['pct_conus'])}) | {int(r['n_reaches']):,} | "
                    f"{r['length_km']:,.0f} | {int(r['max_order'])} | {int(r['longest_path_reaches']):,} / "
                    f"{r['longest_path_km']:,.0f} | {r['source']} | {r['notes']} |")
    prim = df[df["kind"] == "primary"]
    lines.append("\n### Primary networks (parents and city rivers with their own outlet)\n")
    lines.append("| River | Network rank | Outlet / mouth feature_id | Segments (% CONUS) | Reaches | Channel km "
                 "| Max order | Longest path (reaches / km) | Source | Notes |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for r in prim.sort_values("network_rank", kind="stable").to_dict("records"):
        lines.append(
            f"| {r['label']} | {int(r['network_rank'])} | {int(r['mouth_feature_id'])} | {int(r['n_segments']):,} "
            f"({_pct(r['pct_conus'])}) | {int(r['n_reaches']):,} | {r['length_km']:,.0f} | {int(r['max_order'])} | "
            f"{int(r['longest_path_reaches']):,} / {r['longest_path_km']:,.0f} | {r['source']} | {r['notes']} |")
    return "\n".join(lines) + "\n"


INT_COLS = {"mouth_feature_id", "parent_mouth_feature_id", "network_outlet_feature_id", "network_rank",
            "network_segments", "mouth_steps_to_outlet", "parent_segments", "joins_steps", "mouth_extended",
            "n_components", "n_segments", "n_reaches", "max_order", "longest_path_segments", "longest_path_reaches",
            "n_headwaters", "n_gages", "n_waterbodies"}


def _clean(k: str, v):
    if isinstance(v, float) and np.isnan(v):
        return None
    v = v.item() if hasattr(v, "item") else v
    return int(v) if k in INT_COLS and v is not None else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="query USGS live and rewrite subriver_gnis.json")
    args = ap.parse_args()
    gn = Gnis(args.refresh)
    d = load(DATA / "RouteLink_CONUS.nc")
    g = Net(d)
    nets = pd.read_csv(RESULTS / "networks_CONUS.csv")
    rank = dict(zip(nets["outlet_feature_id"], nets["rank"]))
    netname = dict(zip(nets["outlet_feature_id"], nets["river_name"].fillna("")))
    total = int(g.ds.size)
    res: dict[str, dict] = {}
    for c in CANDIDATES:
        r = resolve(g, gn, c, res)
        r.update(label=c["label"], kind=c["kind"], parent=c["parent"], source=c["source"], group=c["group"],
                 city=c["city"], gnis_names=c["names"], note=c["note"])
        res[c["key"]] = r
    if args.refresh:
        gn.save()
    rows = []
    for c in CANDIDATES:
        r = res[c["key"]]
        row = {k: r.get(k) for k in ("key", "label", "kind", "group", "parent", "source", "city", "status")}
        row["parent_label"] = CAND[c["parent"]]["label"] if c["parent"] else None
        if "_mouth" in r:
            m = r["_mouth"]
            st = g.stats(m)
            o = int(g.outlet_of[m])
            row.update(mouth_feature_id=int(g.link[m]), mouth_lat=round(float(d["lat"][m]), 4),
                       mouth_lon=round(float(d["lon"][m]), 4), **st,
                       network_outlet_feature_id=int(g.link[o]), network_rank=int(rank[int(g.link[o])]),
                       network_name=netname[int(g.link[o])], network_segments=int(g.size[o]),
                       mouth_steps_to_outlet=int(g.depth[m]),
                       pct_network=100 * st["n_segments"] / g.size[o], pct_conus=100 * st["n_segments"] / total,
                       joins=r.get("joins"), joins_steps=r.get("joins_steps"), mouth_extended=r.get("extended"),
                       n_components=r.get("n_components"))
            pk = c["scope"] or c["parent"]
            if pk and "_mouth" in res[pk]:
                pm = res[pk]["_mouth"]
                p_root = int(g.outlet_of[pm]) if CAND[pk]["kind"] == "primary" else pm
                row.update(share_of=CAND[pk]["label"], parent_mouth_feature_id=int(g.link[p_root]),
                           parent_segments=int(g.size[p_root]), pct_parent=100 * st["n_segments"] / g.size[p_root],
                           in_parent=bool(g.in_subtree(np.array([m]), p_root)[0]))
                if not row["in_parent"] and row["status"] != "not_in_parent":
                    row["status"] = "UNVERIFIED"
                    r["issues"].append("mouth is NOT inside the parent's network/subtree")
            row["chain"] = " -> ".join(r.get("chain") or [])
            row["joins_via"] = r.get("joins_via")
            row["nhdplus_totdasqkm_at_mouth"] = r.get("nhdplus_totdasqkm_at_mouth")
            row["renamed_on_mainstem"] = "; ".join(r.get("renamed_on_mainstem") or [])
        row["issues"] = " | ".join(r["issues"])
        row["also_named"] = " ; ".join(r.get("also", []))
        row["method"] = r.get("method")
        row["candidates"] = json.dumps(r["candidates"]) if r.get("candidates") else ""
        row["note"] = c["note"] or ""
        rows.append(row)
    for row in rows:
        row["notes"] = _notes(row, res[row["key"]])
    df = pd.DataFrame(rows)
    RESULTS.mkdir(exist_ok=True)
    df.to_csv(RESULTS / "subrivers.csv", index=False, float_format="%.4f")
    df[TABLE_COLS].to_csv(RESULTS / "T_subrivers.csv", index=False, float_format="%.4f")
    (RESULTS / "T_subrivers_rows.md").write_text(md_rows(df))
    gl = {}
    for k in GREAT_LAKES:
        rr = df.set_index("key").loc[k]
        gl[k] = {"label": rr["label"], "network_outlet_feature_id": None if pd.isna(rr.get("network_outlet_feature_id"))
                 else int(rr["network_outlet_feature_id"]),
                 "in_st_lawrence_network": bool(rr.get("network_outlet_feature_id") == ST_LAWRENCE_OUTLET),
                 "joins": rr.get("joins") if isinstance(rr.get("joins"), str) else None}
    out = {
        "snapshot_sha256": hashlib.sha256(SNAP.read_bytes()).hexdigest(),
        "n_candidates": len(df),
        "n_by_status": {k: int(v) for k, v in df["status"].value_counts().sort_index().items()},
        "n_sub_by_status": {k: int(v) for k, v in df[df["kind"] == "sub"]["status"].value_counts().sort_index().items()},
        "great_lakes": gl,
        "rivers": {r["key"]: {k: _clean(k, v) for k, v in r.items()} for r in df.to_dict("records")},
    }
    (RESULTS / "subrivers.json").write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(f"status (all): {out['n_by_status']}; sub-rivers: {out['n_sub_by_status']}")
    for r in rows:
        print(f"{r['status'][:4]:5} {r['label']:24} {r.get('mouth_feature_id', '')!s:>11} "
              f"{r.get('n_segments', '')!s:>8} r{r.get('network_rank', '')!s:4} joins={r.get('joins')!s:24} "
              f"{r['issues'][:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
