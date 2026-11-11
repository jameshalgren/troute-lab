#!/usr/bin/env bash
# Check a machine for the long runs (Stage ii), and optionally build the t-route versions
# there. Installs nothing; prints what is missing and how it is usually added.
#
#   remote_check.sh [--data-dir DIR] [--build | --build-all]
#
#   --data-dir DIR  where data/ will live (default: this directory); disk space is checked there
#   --build         if every tool is present: build_troute.sh era original + current corrected
#   --build-all     the full 2 x 2: era/current x original/corrected kernel
#
# Written for a lab computer reached by remote access. Copy repro/perf_2022 and repro/kernel_fixes there
# (or clone this repository) and run it in a native shell. A Linux branch is kept for other
# machines. The report is also written to results/remote_env.txt.
#
# What the CPU type changes for the 2022-era build (details in README.md, "Lab Mac"):
#   Apple silicon: the 2022 wheels of netCDF4, pyproj, fiona do not exist for arm64, so
#                  envs/era-macos-arm64.txt uses newer ones; Homebrew has gcc/netcdf
#                  bottles for arm64 macOS 14 and later only.
#   Intel:         envs/era-macos-x86_64.txt is the exact 2022 package set (same as
#                  Linux); but Homebrew has no Intel macOS bottles of gcc or netcdf
#                  (2026-11-04), so the toolchain comes from a source build or conda-forge.
#
# AI-written (Claude, 2026-11-04); not yet reviewed by the author. Tested only on the
# author's Apple-silicon laptop.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DATA_DIR=$HERE
BUILD=none
while (($#)); do
  case "$1" in
    --data-dir) DATA_DIR=$2; shift 2 ;;
    --build) BUILD=two; shift ;;
    --build-all) BUILD=all; shift ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
mkdir -p "$HERE/results"
REPORT=$HERE/results/remote_env.txt
exec > >(tee "$REPORT") 2>&1

need=()
warn=()
ok()   { printf '  %-30s %s\n' "$1" "$2"; }
miss() { printf '  %-30s MISSING  (%s)\n' "$1" "$2"; need+=("$1"); }
ver()  { "$@" 2>&1 | head -1; }
have() { command -v "$1" >/dev/null 2>&1; }
OS=$(uname -s)
ARCH=$(uname -m)

echo "== perf_2022 environment report, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "-- system"
if [[ "$OS" == Darwin ]]; then
  MACOS=$(sw_vers -productVersion); MAJOR=${MACOS%%.*}
  ok "macOS" "$MACOS ($(sw_vers -buildVersion)), model $(sysctl -n hw.model)"
  ok "architecture" "$ARCH"
  if [[ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" == 1 ]]; then
    warn+=("this shell runs under Rosetta 2: open a native arm64 shell (arch -arm64 zsh) before building")
  fi
  ok "cpu" "$(sysctl -n machdep.cpu.brand_string)"
  ok "cores (hw.ncpu / physical)" "$(sysctl -n hw.ncpu) / $(sysctl -n hw.physicalcpu)"
  if [[ "$ARCH" == arm64 ]]; then
    NPERF=$(sysctl -n hw.perflevel0.physicalcpu 2>/dev/null || echo ?)
    ok "performance + efficiency" "$NPERF + $(sysctl -n hw.perflevel1.physicalcpu 2>/dev/null || echo ?) (use the performance count for cpu_pool)"
  fi
  MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
  ok "memory (hw.memsize)" "$MEM_GB GiB"
  ok "sleep settings" "$(pmset -g 2>/dev/null | awk '$1=="sleep"{s=$2} $1=="disksleep"{d=$2} END{print "sleep "s", disksleep "d" (0 = never)"}')"
  warn+=("long runs: start them under 'caffeinate -i' (or set system sleep to 0) and keep the Mac on power")
else
  [[ -r /etc/os-release ]] && ok "os" "$(. /etc/os-release; echo "$PRETTY_NAME")"
  ok "architecture" "$ARCH"
  have lscpu && ok "cpu" "$(lscpu | sed -n 's/^Model name: *//p' | head -1)"
  have nproc && ok "nproc (usable cores)" "$(nproc)"
  have free && { MEM_GB=$(free -g | awk '/^Mem:/{print $2}'); ok "memory" "$MEM_GB GiB"; }
fi
mkdir -p "$DATA_DIR"
DISK_GB=$(df -Pk "$DATA_DIR" | awk 'NR==2{print int($4/1048576)}')
ok "free disk at data dir" "$DISK_GB GiB ($DATA_DIR)"
ok "open files limit" "$(ulimit -n)"

echo "-- tools for the t-route builds"
for t in uv git make; do have $t && ok "$t" "$(ver $t --version)" || miss "$t" "required"; done
if [[ "$OS" == Darwin ]]; then
  xcode-select -p >/dev/null 2>&1 && ok "Command Line Tools" "$(xcode-select -p)" || miss "xcode-select" "Xcode Command Line Tools (xcode-select --install)"
  if have brew; then
    ok "Homebrew" "$(brew --prefix) ($(ver brew --version))"
    ok "brew gcc/netcdf/netcdf-fortran" "$(brew list --versions gcc netcdf netcdf-fortran 2>/dev/null | tr '\n' ';' || true)"
  else
    ok "Homebrew" "absent"
  fi
fi
have "${CC:-cc}" && ok "C compiler (${CC:-cc})" "$(ver "${CC:-cc}" --version)" || miss "${CC:-cc}" "C compiler"
have "${F90:-gfortran}" && ok "Fortran (${F90:-gfortran})" "$(ver "${F90:-gfortran}" --version)" || miss "${F90:-gfortran}" "Fortran compiler"
if have nc-config; then ok "netCDF-C" "$(nc-config --version)"; else miss nc-config "netCDF-C"; fi
if have nf-config; then ok "netCDF-Fortran" "$(nf-config --version)"; else miss nf-config "netCDF-Fortran"; fi

echo "-- what this platform means for the builds"
if [[ "$OS" == Darwin && "$ARCH" == arm64 ]]; then
  ok "era Python packages" "envs/era-macos-arm64.txt: 2022 set except netCDF4 1.6.2, cftime 1.6.2, pyproj 3.6.0, fiona 1.9.4, shapely 2.0.1 (no 2022 arm64 wheels)"
  ((MAJOR >= 14)) && ok "current Python packages" "envs/current-macos-arm64.txt (needs macOS >= 14: yes)" || warn+=("macOS $MACOS < 14: no netCDF4 1.7.4 wheel for current-code env, and no Homebrew bottles of gcc/netcdf; netCDF4 would build from source")
  ok "toolchain" "brew install gcc netcdf netcdf-fortran (arm64 bottles for macOS 14+)"
elif [[ "$OS" == Darwin && "$ARCH" == x86_64 ]]; then
  ok "era Python packages" "envs/era-macos-x86_64.txt: the exact 2022 set (netCDF4 1.5.8, numpy 1.22.2, Cython 0.29.27, ...)"
  ((MAJOR >= 13)) && ok "current Python packages" "envs/current-macos-x86_64.txt (needs macOS >= 13: yes)" || warn+=("macOS $MACOS < 13: no Intel wheels for parts of the current-code env (netCDF4 1.7.4)")
  ok "toolchain" "Homebrew has no Intel-macOS bottles of gcc or netcdf (2026-11-04): brew would compile gcc for hours; conda-forge has osx-64 gfortran 16.2.0, libnetcdf 4.10.1, netcdf-fortran 4.6.4 (e.g. micromamba create -p ~/perf2022-tc -c conda-forge gfortran netcdf-fortran)"
else
  ok "era Python packages" "envs/era-linux-x86_64.txt (exact 2022 set) if Linux x86_64"
fi

echo "-- network (anonymous HTTPS)"
probe() { local code; code=$(curl -s -o /dev/null -m 20 -w '%{http_code}' -I "$2" 2>/dev/null); [[ "$code" =~ ^(200|301|302|307|403)$ ]] && ok "$1" "HTTP $code" || miss "$1" "no HTTPS access ($code): $2"; }
probe "NWM v2.1 retrospective" "https://noaa-nwm-retrospective-2-1-pds.s3.amazonaws.com/model_output/2018/201801010100.CHRTOUT_DOMAIN1.comp"
probe "HydroShare (RouteLink)" "https://www.hydroshare.org/resource/0a596929a3e5411bb0032a8de35e5089/"
probe "GitHub (t-route source)" "https://github.com/NOAA-OWP/t-route"
probe "PyPI (wheels)" "https://pypi.org/simple/numpy/"
probe "uv Python downloads" "https://github.com/astral-sh/python-build-standalone/releases"

echo "-- sizing (estimates in README.md, Stage ii)"
[[ -n "${MEM_GB:-}" ]] && { ((MEM_GB >= 64)) && ok "memory >= 64 GiB" "yes" || ok "memory >= 64 GiB" "NO: use 12-h (or 6-h) loops and watch peak memory"; }
((DISK_GB >= 150)) && ok "disk >= 150 GiB (slim year)" "yes" || ok "disk >= 150 GiB (slim year)" "NO"
((DISK_GB >= 600)) && ok "disk >= 600 GiB (full CHRTOUT year)" "yes" || ok "disk >= 600 GiB (full CHRTOUT year)" "no (needed only for the WRF-Hydro reference or CHRTOUT output)"

for w in "${warn[@]+"${warn[@]}"}"; do echo "  NOTE: $w"; done
if ((${#need[@]})); then
  echo "-- missing: ${need[*]}"
  if [[ "$OS" == Darwin ]]; then
    echo "   Apple silicon, macOS 14+: brew install gcc netcdf netcdf-fortran"
    echo "   Intel Mac:                conda-forge toolchain (see above), then export F90=<prefix>/bin/gfortran and put <prefix>/bin on PATH"
  else
    echo "   Debian/Ubuntu: sudo apt install gfortran make git libnetcdf-dev libnetcdff-dev netcdf-bin"
    echo "   RHEL/Rocky:    sudo dnf install gcc-gfortran make git netcdf-devel netcdf-fortran-devel"
  fi
  echo "   uv:            curl -LsSf https://astral.sh/uv/install.sh | sh"
  echo "   (nothing was installed; installs need the author's approval)"
fi

if [[ "$BUILD" != none ]]; then
  if ((${#need[@]})); then echo "-- not building: tools missing"; exit 1; fi
  echo "-- building"
  "$HERE/build_troute.sh" era original
  "$HERE/build_troute.sh" current corrected
  if [[ "$BUILD" == all ]]; then
    "$HERE/build_troute.sh" era corrected
    "$HERE/build_troute.sh" current original
  fi
fi
echo "-- report written to results/remote_env.txt"
