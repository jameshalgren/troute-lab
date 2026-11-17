#!/usr/bin/env bash
# Rebuild the NWM parameter-archive catalog. Run from anywhere; works in this folder.
#
#   ./rebuild.sh                 offline: regenerate build/ tables from listings/, headers/
#                                and raw/ncep_text/, then assemble nwm_parameter_archives.md
#   ./rebuild.sh --crawl [opts]  re-survey NOHRSC and NCEP first, then the offline step
#
# Crawl options:
#   --only STEP[,STEP...]   run only these crawl steps (repeatable). Steps:
#                             nohrsc-index   NOHRSC owp_files listing + README*.txt
#                             v2.1 v3.0 coastal_v3.0 hydrofabric_v2.0 hydrofabric_v2.1
#                             hydrofabric_v3.0          one NOHRSC tarball each
#                             tarballs       all six tarballs
#                             ncep-tree      NCEP nwm.v3.1.7 listing (HEAD per file)
#                             ncep-parm      NCEP parm/ netCDF headers (byte-range) + text files
#                             ncep-code      NCEP jobs/ scripts/ ush/ small text files (raw/, not in git)
#                             ncep-doc       NCEP doc/ files (raw/, not in git)
#                             ncep-hashes    SHA-256 of 17 small parm/domain* routing files (~0.8 GB)
#                             ncep           all ncep-* steps
#   --ncep-subtree REL      limit ncep-tree, ncep-parm and ncep-hashes to one folder, e.g.
#                           parm/domain_hawaii/ (its rows, files and hashes are replaced;
#                           the rest is kept)
#   --cache DIR             look here (and up to 3 folder levels down) for local copies of
#                           tarballs and NCEP files before downloading (repeatable; also
#                           NWM_CATALOG_CACHE=DIR1:DIR2). A copy is used only if the server
#                           still shows the listed size and date and the copy's size and
#                           SHA-256 match the previous survey's values.
#   --keep DIR              save each streamed tarball in DIR
#   --no-build              skip the offline step after a crawl
#
# Requires uv; the crawl also needs ncdump (netCDF-C) on the PATH. Downloads go through
# a scratch folder in $TMPDIR that is removed on exit.
set -euo pipefail
cd "$(dirname "$0")"

NOHRSC=https://www.nohrsc.noaa.gov/owp_files/
NCEP=https://www.nco.ncep.noaa.gov/pmb/codes/nwprod/nwm.v3.1.7/
TARBALLS="v2.1=nwm/nwm_parameters/NWM_parameter_files_v2.1.tar.gz
v3.0=nwm/nwm_parameters/NWM_parameter_files_v3.0.tar.gz
coastal_v3.0=nwm/nwm_parameters/NWM_coastal_parameters_v3.0.tar.gz
hydrofabric_v2.0=nwm/data_tools/NWM_v2.0_channel_hydrofabric.tar.gz
hydrofabric_v2.1=nwm/data_tools/NWM_v2.1_channel_hydrofabric.tar.gz
hydrofabric_v3.0=nwm/data_tools/NWM_v3.0_channel_hydrofabric.tar.gz"
ALL_STEPS="nohrsc-index v2.1 v3.0 coastal_v3.0 hydrofabric_v2.0 hydrofabric_v2.1 hydrofabric_v3.0 ncep-tree ncep-parm ncep-code ncep-doc ncep-hashes"

crawl=0; build=1; only=""; subtree=""; keep=""; caches=()
IFS=: read -r -a env_caches <<< "${NWM_CATALOG_CACHE:-}"
for c in "${env_caches[@]+"${env_caches[@]}"}"; do [ -n "$c" ] && caches+=("$c"); done
while [ $# -gt 0 ]; do
  case "$1" in
    --crawl) crawl=1 ;;
    --only) only="$only ${2//,/ }"; shift ;;
    --ncep-subtree) subtree="$2"; shift ;;
    --cache) caches+=("$2"); shift ;;
    --keep) keep="$2"; shift ;;
    --no-build) build=0 ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done
if [ $crawl = 0 ] && { [ -n "$only" ] || [ -n "$subtree" ] || [ ${#caches[@]} -gt 0 ] || [ -n "$keep" ]; }; then
  echo "--only/--ncep-subtree/--cache/--keep need --crawl" >&2; exit 2
fi

py() { uv run --no-project --quiet python -I "$@"; }

offline() {
  echo "== offline build"
  py scripts/gen_nohrsc_tables.py
  py scripts/gen_ncep_tables.py
  py scripts/nml_table.py hydro.namelist > build/hydro_namelist_table.txt
  py scripts/nml_table.py namelist.hrldas > build/hrldas_namelist_table.txt
  py scripts/assemble.py
}

if [ $crawl = 0 ]; then offline; exit 0; fi

# ---------------------------------------------------------------- crawl
command -v ncdump >/dev/null || { echo "ncdump (netCDF-C) is not on the PATH" >&2; exit 1; }
steps=""
for s in ${only:-$ALL_STEPS}; do
  case "$s" in
    tarballs) steps="$steps v2.1 v3.0 coastal_v3.0 hydrofabric_v2.0 hydrofabric_v2.1 hydrofabric_v3.0" ;;
    ncep) steps="$steps ncep-tree ncep-parm ncep-code ncep-doc ncep-hashes" ;;
    *) case " $ALL_STEPS " in *" $s "*) steps="$steps $s" ;; *) echo "unknown step: $s" >&2; exit 2 ;; esac ;;
  esac
done
want() { case " $steps " in *" $1 "*) return 0 ;; *) return 1 ;; esac; }
cache_args=(); for c in "${caches[@]+"${caches[@]}"}"; do cache_args+=(--cache "$c"); done

WORK=$(mktemp -d "${TMPDIR:-/tmp}/nwm_catalog.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
mkdir -p raw/logs
LOG=raw/logs/crawl_$(date -u +%Y%m%dT%H%M%SZ).log
exec > >(tee -a "$LOG") 2>&1
echo "== crawl $(date -u) steps:$steps${subtree:+ (NCEP subtree $subtree)}"
cp -R listings "$WORK/prev"   # previous survey: reference sizes and hashes for --cache

if want nohrsc-index; then
  echo "== nohrsc-index"
  py scripts/crawl_nohrsc.py "$NOHRSC" "$WORK/nohrsc.tsv" --save-text "$WORK/nohrsc_text"
  mv "$WORK/nohrsc.tsv" listings/nohrsc_owp_files.tsv
  mkdir -p raw/nohrsc_text && cp "$WORK"/nohrsc_text/README*.txt raw/nohrsc_text/
fi

# Last-Modified of a NOHRSC URL in the previous listing (empty if absent)
prev_lm() { awk -F'\t' -v u="$1" '$2==u {print $4}' "$WORK/prev/nohrsc_owp_files.tsv"; }

while IFS== read -r label path <&3; do
  want "$label" || continue
  url="$NOHRSC$path"; echo "== tarball $label  $url"
  local_copy=""
  if [ ${#cache_args[@]} -gt 0 ] && [ -f "$WORK/prev/members_$label.json" ]; then
    read -r size sha < <(py -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["compressed_bytes"], d["compressed_sha256"])' "$WORK/prev/members_$label.json")
    lm=$(prev_lm "$url")
    local_copy=$(nice -n 10 uv run --no-project --quiet python -I scripts/find_cached.py "$url" --size "$size" --sha256 "$sha" ${lm:+--last-modified "$lm"} "${cache_args[@]}")
  elif [ ${#cache_args[@]} -gt 0 ]; then
    echo "cache: no previous listing for $label; streaming"
  fi
  out="$WORK/scan_$label"; gdb=()
  case "$label" in hydrofabric_*) gdb=(--gdb-dir "$WORK/gdb_$label") ;; esac
  nice -n 10 uv run --no-project --quiet python -I -W ignore scripts/scan_tar.py "$url" "$label" "$out" \
    ${local_copy:+--local "$local_copy"} ${keep:+--keep "$keep"} "${gdb[@]+"${gdb[@]}"}" > "raw/logs/scan_$label.log"
  tail -1 "raw/logs/scan_$label.log"
  if [ ${#gdb[@]} -gt 0 ]; then
    nice -n 10 uv run --no-project --quiet --with pyogrio python -I -W ignore scripts/gdb_schema.py \
      "$WORK/gdb_$label" "$url" "$label" "$out/headers/$label/gdb_layers.txt"
    rm -rf "$WORK/gdb_$label"
  fi
  rm -rf "headers/$label" "raw/nohrsc_text/$label"
  mv "$out/headers/$label" "headers/$label"
  mkdir -p raw/nohrsc_text && mv "$out/raw/nohrsc_text/$label" "raw/nohrsc_text/$label"
  mv "$out/listings/members_$label.json" "listings/members_$label.json"
  rm -rf "$out"
done 3<<< "$TARBALLS"

TREE=listings/ncep_nwm.v3.1.7_tree.tsv
if want ncep-tree; then
  echo "== ncep-tree${subtree:+ $subtree}"
  if [ -n "$subtree" ]; then
    py scripts/crawl_ncep.py "$NCEP" "$WORK/tree.tsv" --subtree "$subtree" --merge "$TREE"
  else
    py scripts/crawl_ncep.py "$NCEP" "$WORK/tree.tsv"
  fi
  mv "$WORK/tree.tsv" "$TREE"
fi

if want ncep-parm; then
  prefix=${subtree:-parm/}
  echo "== ncep-parm $prefix"
  py scripts/ncep_headers.py "$TREE" --prefix "$prefix" --hdr-dir "$WORK/h" --text-dir "$WORK/t" --log raw/logs/ncep_headers.log
  mkdir -p headers/ncep_v3.1.7 raw/ncep_text
  if [ -z "$subtree" ]; then  # full survey: drop files that are no longer published
    rm -f headers/ncep_v3.1.7/*.cdl raw/ncep_text/*
  fi
  cp "$WORK"/h/* headers/ncep_v3.1.7/ 2>/dev/null || true
  cp "$WORK"/t/* raw/ncep_text/ 2>/dev/null || true
  rm -rf "$WORK/h" "$WORK/t"
fi

if want ncep-code; then
  echo "== ncep-code"
  py scripts/ncep_headers.py "$TREE" --prefix jobs/ --prefix scripts/ --prefix ush/ --text-dir raw/ncep_code --log raw/logs/ncep_code.log
fi

if want ncep-doc; then
  echo "== ncep-doc"
  py scripts/ncep_headers.py "$TREE" --prefix doc/ --keep-binary --max-bytes 100000000 --text-dir raw/ncep_doc --log raw/logs/ncep_doc.log
fi

if want ncep-hashes; then
  echo "== ncep-hashes"
  nice -n 10 uv run --no-project --quiet python -I scripts/ncep_hashes.py "$TREE" "$WORK/hashes.txt" \
    --prev "$WORK/prev/ncep_parm_hashes.txt" ${subtree:+--subtree "$subtree"} "${cache_args[@]+"${cache_args[@]}"}"
  mv "$WORK/hashes.txt" listings/ncep_parm_hashes.txt
fi

echo "== crawl done $(date -u); log: $LOG"
echo "   compare with git: git diff --stat listings/ headers/ raw/ncep_text/"
if [ $build = 1 ]; then offline; fi
