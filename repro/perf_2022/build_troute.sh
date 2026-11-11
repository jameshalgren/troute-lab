#!/usr/bin/env bash
# Build one t-route version, in its own uv environment, into build/<code>-<kernel>/.
#
#   build_troute.sh era      [original|corrected]   NOAA-OWP/t-route a6efbf4e (2022-02-16), Python 3.9.25
#   build_troute.sh current  [corrected|original]   CIROH-UA/t-route d29f663 (ngiab, 2026-09-18), Python 3.12.13
#
# Kernel: "original" = the Fortran Muskingum-Cunge kernel as committed; "corrected" = plus
# patches 0001-0008 of ../kernel_fixes/patches (the repro/ default since 2026-10-09). All
# eight patches also apply cleanly to a6efbf4e's kernel (checked 2026-11-04), so the
# 2 x 2 design {era, current} x {original, corrected} separates framework from kernel.
# Defaults: era -> original (the faithful 2022 build), current -> corrected.
#
# Needs (not installed by this script): uv, git, make, a C compiler, gfortran, and
# netCDF-C + netCDF-Fortran (nc-config, nf-config), all approved by the author first.
# Apple-silicon Mac (macOS 14+): `brew install gcc netcdf netcdf-fortran`. Intel Mac:
# Homebrew has no Intel bottles of gcc/netcdf (2026-11-04); use conda-forge (gfortran,
# netcdf-fortran, libnetcdf for osx-64) and set F90. Linux: distribution packages.
#
# Steps mirror each commit's own compiler.sh (Fortran kernels with t-route's makefiles,
# then the Cython packages), with three deliberate differences, all recorded in
# build_info.json:
#   * Python packages come from hash-pinned files envs/<code>-<platform>.txt;
#   * era only: CFLAGS=-Wno-error=implicit-int, because a6efbf4e's levelpool_structs.c
#     and rfc_structs.c declare init_*_reach() without a return type (implicit int),
#     which Apple clang >= 16 and GCC >= 14 reject by default (found 2026-11-04 with
#     Apple clang 21; the current code declares them `void`);
#   * era only: NETCDFINC comes from nf-config (compiler.sh hard-codes an openmpi path).
#
# AI-written (Claude, 2026-11-04); not yet reviewed by the author. NOT YET RUN: gfortran
# and netCDF-Fortran were not installed on the machine where it was written.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
CODE=${1:?usage: build_troute.sh era|current [original|corrected]}
case "$CODE" in
  era)     REPO=https://github.com/NOAA-OWP/t-route.git
           SHA=a6efbf4e58f86c7bab73735ad021c628f69329b8; PYV=3.9.25
           KERNEL=${2:-original}; DIFF_OBJS="diffusive.o pydiffusive.o" ;;
  current) REPO=https://github.com/CIROH-UA/t-route.git
           SHA=d29f663ac23f435b2e5c176f6e0d22ac4528c6a6; PYV=3.12.13
           KERNEL=${2:-corrected}; DIFF_OBJS="diffusive.o pydiffusive.o chxsec_lookuptable.o pychxsec_lookuptable.o" ;;
  *) echo "ERROR: first argument must be era or current" >&2; exit 2 ;;
esac
[[ "$KERNEL" == original || "$KERNEL" == corrected ]] || { echo "ERROR: kernel must be original or corrected" >&2; exit 2; }

if [[ "$(uname -s)" == Darwin && "$(sysctl -n sysctl.proc_translated 2>/dev/null)" == 1 ]]; then
  echo "ERROR: this shell runs under Rosetta 2 on Apple silicon; use a native shell (arch -arm64 zsh)" >&2; exit 2
fi
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64)  PLAT=linux-x86_64; LIBEXT=so ;;
  Darwin-arm64)  PLAT=macos-arm64;  LIBEXT=dylib ;;   # era env: newer netCDF4/pyproj/fiona/shapely (no 2022 arm64 wheels)
  Darwin-x86_64) PLAT=macos-x86_64; LIBEXT=dylib ;;   # era env: the exact 2022 package set
  *) echo "ERROR: no pinned environment for $(uname -s)-$(uname -m); add one to envs/ (README.md, Environments)" >&2; exit 2 ;;
esac

F90=${F90:-gfortran}
missing=()
# ONLY_ENV=1: steps 1-3 only (source, kernel patches, Python environment); needs no compilers.
TOOLS=(uv git)
[[ "${ONLY_ENV:-0}" == 1 ]] || TOOLS+=(make "$F90" nc-config nf-config "${CC:-cc}")
for t in "${TOOLS[@]}"; do command -v "$t" >/dev/null || missing+=("$t"); done
if ((${#missing[@]})); then
  echo "ERROR: missing tools: ${missing[*]}" >&2
  echo "  Apple-silicon Mac (Homebrew): brew install gcc netcdf netcdf-fortran   # gcc provides gfortran" >&2
  echo "  Intel Mac: conda-forge gfortran + netcdf-fortran (see README.md, Lab Mac); export F90=..." >&2
  echo "  Debian/Ubuntu:    apt install gfortran make git libnetcdf-dev libnetcdff-dev" >&2
  echo "  RHEL/Rocky:       dnf install gcc-gfortran make git netcdf-devel netcdf-fortran-devel" >&2
  exit 1
fi

LABEL=$CODE-$KERNEL
B=$HERE/build/$LABEL
SRC=$B/t-route
PY=$B/.venv/bin/python
mkdir -p "$B"
LOG=$B/build.log
: > "$LOG"
say() { echo "$*" | tee -a "$LOG"; }
sha() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
run() { echo "+ $*" >> "$LOG"; "$@" >> "$LOG" 2>&1 || { echo "ERROR: step failed: $* (see $LOG)" >&2; tail -30 "$LOG" >&2; exit 1; }; }

# 1. Source at the pinned commit (shallow fetch by SHA), exported fresh into $SRC.
if [[ ! -d "$B/repo/.git" ]]; then
  run git init -q "$B/repo"
  run git -C "$B/repo" remote add origin "$REPO"
fi
git -C "$B/repo" cat-file -e "$SHA^{commit}" 2>/dev/null || run git -C "$B/repo" fetch -q --depth 1 origin "$SHA"
rm -rf "$SRC"; mkdir -p "$SRC"
git -C "$B/repo" archive "$SHA" | tar -x -C "$SRC"
say "ok      source $REPO @ ${SHA:0:12} -> $SRC"

# 2. Kernel patches. $SRC gets its own git repository first: inside another git working
#    tree (such as this repository's), `git apply` would otherwise resolve paths against it
#    and skip every hunk silently (see ../kernel_fixes/kernels.py).
PATCHES_JSON="[]"
if [[ "$KERNEL" == corrected ]]; then
  KF=$HERE/../kernel_fixes/patches
  run git -C "$SRC" init -q
  recs=()
  while read -r p; do
    [[ -z "$p" || "$p" == \#* ]] && continue
    run git -C "$SRC" apply --check "$KF/$p"
    run git -C "$SRC" apply "$KF/$p"
    recs+=("{\"patch\": \"$p\", \"sha256\": \"$(sha "$KF/$p")\"}")
  done < "$KF/series"
  PATCHES_JSON="[$(IFS=,; echo "${recs[*]}")]"
  rm -rf "$SRC/.git"
  say "ok      applied ${#recs[@]} kernel patches from ../kernel_fixes/patches"
fi

# 3. Python environment from the hash-pinned requirements.
[[ -x "$PY" ]] || run uv venv -q --managed-python --python "$PYV" "$B/.venv"
run uv pip sync -q --python "$PY" "$HERE/envs/$CODE-$PLAT.txt"
say "ok      python $("$PY" -c 'import sys; print(sys.version.split()[0])') + envs/$CODE-$PLAT.txt"
if [[ "${ONLY_ENV:-0}" == 1 ]]; then say "ok      ONLY_ENV=1: stopping before the compile steps"; exit 0; fi

# 4. Fortran kernels (each commit's makefiles).
export F90 FC=$F90 CC=${CC:-cc}
export NETCDFINC=$(nf-config --includedir)
LIBGF=$(cd "$(dirname "$("$F90" -print-file-name=libgfortran.$LIBEXT)")" && pwd)
export LIBRARY_PATH="$LIBGF:$(nf-config --prefix)/lib:$(nc-config --prefix)/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
if [[ "$CODE" == era ]]; then export CFLAGS="${CFLAGS:-} -Wno-error=implicit-int"; fi
K=$SRC/src/kernel
run make -C "$K/muskingum" clean
run make -C "$K/muskingum"
run make -C "$K/muskingum" install
run make -C "$K/diffusive" clean
run make -C "$K/diffusive" $DIFF_OBJS
run make -C "$K/diffusive" install
run make -C "$K/reservoir" clean
run make -C "$K/reservoir" install_lp
run make -C "$K/reservoir" install_rfc
say "ok      Fortran kernels ($F90)"

# 5. Cython/Python packages.
if [[ "$CODE" == era ]]; then
  # a6efbf4e compiler.sh: `python setup.py build_ext --inplace --use-cython; pip install -e .`
  # setuptools 60 predates PEP 660 editable wheels, so `setup.py develop` is used for -e.
  for pkg in troute-network troute-routing; do
    (cd "$SRC/src/$pkg" && run "$PY" setup.py build_ext --inplace --use-cython && run "$PY" setup.py develop --no-deps)
  done
  (cd "$SRC/src/troute-nwm" && run "$PY" setup.py develop --no-deps)
else
  PIP=(uv pip install --python "$PY" --no-deps --no-build-isolation --reinstall)
  for pkg in troute-network troute-routing; do
    run "${PIP[@]}" --config-setting=--build-option=--use-cython "$SRC/src/$pkg"
  done
  for pkg in troute-config troute-nwm; do run "${PIP[@]}" "$SRC/src/$pkg"; done
fi
(cd "$B" && run "$PY" -c "import troute.routing.fast_reach.mc_reach, nwm_routing.__main__; print('import ok')")
say "ok      t-route packages import"

# 6. Provenance.
first() { "$@" 2>&1 | head -1; }
cat > "$B/build_info.json" <<EOF
{
  "label": "$LABEL",
  "repo": "$REPO",
  "commit": "$SHA",
  "kernel": "$KERNEL",
  "patches": $PATCHES_JSON,
  "python": "$("$PY" -c 'import sys; print(sys.version.split()[0])')",
  "requirements": "envs/$CODE-$PLAT.txt",
  "fortran": "$(first "$F90" --version)",
  "cc": "$(first "$CC" --version)",
  "nc_config": "$(nc-config --version)",
  "nf_config": "$(nf-config --version)",
  "cflags": "${CFLAGS:-}",
  "muskingum_flags": "$(grep -hE '^(FCFLAGS|F90FLAGSGFORTRAN) *=' "$K/muskingum/makefile" | head -1 | sed 's/"/\\"/g')",
  "uname": "$(uname -a)",
  "built_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
uv pip freeze --python "$PY" > "$B/pip_freeze.txt"
say "ok      $B/build_info.json"
