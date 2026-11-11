# Corrections to T-Route's Muskingum-Cunge kernel

*AI-assembled (Claude), 2026-10-09; not yet reviewed by the author. The patch messages
are AI-drafted suggestions; James Halgren rewrites them before anything is submitted.*

## Why

The author set a rule (James Halgren, 2026-10-09):

> For this work, all tests in this repo should use a kernel that doesn't have any
> uninitialized variables or other true coding errors in the MC kernel, even where these
> cause a deviation from the NWM. Improvements to the MC algorithm or implementation of
> diffusive routing can come later, but we shouldn't publish with known errors. [...] An
> appendix to the paper could be a documentation of the algorithm corrections.

This directory holds what that rule needs:
- the corrections, as a patch series against CIROH-UA/t-route
  [`d29f663`](https://github.com/CIROH-UA/t-route/commit/d29f663ac23f435b2e5c176f6e0d22ac4528c6a6),
  the commit every repro/ experiment builds. NOAA-OWP `master` has the identical kernel;
- the evidence that each correction does what it says and nothing else.

A line-by-line audit of the kernel, and a review that tests the same NGWPC changes on the
shipped LowerColorado cases, were done for the paper and will be published with it.

**Credit.**
- Patches 0001, 0002, 0006, 0007 and 0008 are **Taher Chegini's** kernel fixes, ported
  to d29f663:
  - from [NGWPC/t-route#123](https://github.com/NGWPC/t-route/pull/123) (merged
    2026-08-21);
  - and from [#127](https://github.com/NGWPC/t-route/pull/127) (commit 4ecefec1, merged
    2026-09-17).

  The NGWPC team found these defects while chasing a serial vs MPI disagreement and an
  Old River flow collapse.
- **Brodie Alexander** and the CIROH rs_route team reported and fixed the C1..C4 read
  (part of 0001) in [CIROH-UA/rs_route#7](https://github.com/CIROH-UA/rs_route/pull/7)
  (merged 2026-04-03).
- Patches 0003–0005 are new here.
- The optional X patch is the T-Route counterpart of NCAR/wrf_hydro_nwm_public#921 /
  #923. The evidence is in [`../wrfhydro_mc_x_factor/`](../wrfhydro_mc_x_factor/): a
  prismatic channel test and the Potomac network, run with WRF-Hydro's own routine and
  with T-Route.

## The corrections (draft for the paper appendix)

Each patch is one reviewable commit. Apply them in order with
`git am patches/000*.patch` on d29f663.

**The corrected kernel = all eight patches.** Since 2026-10-09 it is the default for
every T-Route build in this repository.

| Patch | What was wrong | Correction | Class | Origin |
|---|---|---|---|---|
| [0001](patches/0001-fix-kernel-make-the-Muskingum-Cunge-kernel-determini.patch) | `secant2_h` reads `Qj` (interval 1) and `C1..C4` (interval 2) on entry although they are `intent(out)`. The caller's `Qj_0` is never set. The first Secant iterate depends on leftover memory, so results are not a function of the inputs | `Qj_0 = Qj = C1..C4 = 0` at label 110, as in WRF-Hydro; the four coefficients and `Qj` become `intent(inout)` | uninitialized read / intent | Taher Chegini, NGWPC #123 (2bd0c0c2); Brodie Alexander, rs_route #7 |
| [0002](patches/0002-fix-kernel-do-not-treat-a-solve-that-met-tolerance-o.patch) | A solve that met tolerance on its last allowed pass counted as a failure, and its depth × 1.33 was published | explicit `converged` flag | logic error (also in WRF-Hydro) | Taher Chegini, NGWPC #123 (ea62cc90, first half) |
| [0003](patches/0003-fix-kernel-restart-the-error-measures-when-the-Secan.patch) | A retry jumped back without resetting `rerror`/`aerror`. If the failed pass ended inside the tolerance, the retried loop never ran, and the kernel published depth 1.33·h and **qdc = 0** | reset both before `goto 110` | logic error (defensive in d29f663; live in NGWPC #123 as merged) | new |
| [0004](patches/0004-fix-kernel-decide-whether-to-route-from-the-inputs-n.patch) | The "water to route?" test reads `qdc`, an `intent(out)` argument | test the inputs only (as WRF-Hydro does, plus `quc`) | uninitialized read (harmless through T-Route's C caller, which passes 0) | new |
| [0005](patches/0005-fix-kernel-define-ck-cn-and-X-on-every-path.patch) | On the no-flow branch, `X` was never set and `ck`, `cn` were overwritten from an unused depth guess. `courant` computed 0/0 at h = 0 | define all three; call `courant` on the flow branch only; return ck = 0 for a dry section | undefined outputs (diagnostics only) | new |
| [0006](patches/0006-fix-kernel-stop-reading-a-failed-Secant-step-as-conv.patch) | False convergence: a negative Secant step, or a zero slope, sets `h_1 = h`. The step-size test reads that as a root, and the current iterate is published as the depth. In T-Route runs about 0.28% of kernel calls (Potomac) end this way | a negative step halves h; a zero slope is a stall, which triggers a retry | logic error (also in WRF-Hydro) | Taher Chegini, NGWPC #123 (af24a7c4) |
| [0007](patches/0007-fix-kernel-hold-the-previous-depth-when-the-Secant-s.patch) | An abandoned search (4 retries) publishes its last iterate | hold the previous depth and re-evaluate the coefficients there | policy for non-convergence (WRF-Hydro publishes the iterate) | Taher Chegini, NGWPC #123 (ea62cc90, second half) |
| [0008](patches/0008-fix-kernel-restart-the-Muskingum-Cunge-depth-search-.patch) | Once 0006 no longer accepts a false root, a search can settle on the degenerate near-zero-depth root (celerity ≈ 0, C3 = 1), where the segment passes its previous outflow whatever arrives | if the residual exceeds a tenth of the Muskingum estimate, restart from normal-depth seeds (up to 4 times) | **required companion of 0006** (an algorithm change, but without it 0006 loses water) | Taher Chegini, NGWPC #127 (4ecefec1) |
| [optional/x-cunge-factor2](patches/optional/x-cunge-factor2.patch) | X = ½(1 − Q/(**2**·T·S0·Ck·Δx)) carries a factor 2 that Cunge's matching does not | drop the `2.0_prec*` in the four X expressions | **modelling question, under review in NCAR/wrf_hydro_nwm_public#923; off by default** | #921 / #923; [`../wrfhydro_mc_x_factor/`](../wrfhydro_mc_x_factor/) |

**0006 must never be taken without 0008.** Alone (level `L7`, kept only as a diagnostic),
0006 lets searches fall onto the degenerate root:
- on the LowerColorado cold starts of the fork review, 13–16% of routed volume is lost;
- here:
  - the network volume falls 0.5–1.1% on LowerColorado (warm start);
  - the Potomac outlet volume falls 1.6% with `assume_short_ts` False;
  - 352 slope-floor Potomac segments sit at about 5 mm depth for hours while carrying tens
    of m³/s (`expected/l7_collapse_example.json`).
- With 0008 the volume changes are below 0.25% (tables below).

0007 is a policy, not a coding error. It goes with 0006 and 0008 as NGWPC ships them.
`L5` (0001–0005, without the Secant package) remains available for comparison.

Not corrected, because they are modelling choices or have no effect with valid inputs:
- the X floors and cap;
- K = max(dt, dx/Ck);
- the negative-flow guard;
- the bankfull conveyance jump;
- the trapezoid velocity;
- convergence tested on the step and not the residual;
- the empty parameter check (NGWPC f318d0c5).

See the audit, sections B and C.

`patches/anw2020/` applies the same corrections (FIX 0001–0008) to Adam Wlostowski's 2020
copy of the kernel (`repro/mc_courant_timestep`, `run_corrected.py`). On that channel only
the 0008 restart is ever taken, and the results agree within 10⁻⁶ of peak.

## How the kernel is selected elsewhere

- `../short_ts_switch/build_troute.py`: `--kernel` or environment `KERNEL`:
  - `corrected` (default, 0001–0008);
  - `unpatched`;
  - `L<k>` (first k patches);
  - `corrected+x` / `L<k>x` (with the optional X patch);
  - `trace-L<k>` (instrumented).

  A build is redone when the patch files change: `build_info.json` records their SHA-256.
- `../upstream_inflow_patch/build_patched.py`: `--variant corrected` (default) or
  `unpatched` (`COMPARE_UNPATCHED=1 run.sh`).
- `kernels.py` holds the series, `DEFAULT_LEVEL = 8` and `apply_series()`. It runs
  `git apply` with a git ceiling: inside this repository a bare `git apply` skips every
  path silently, which happened once in this work. It then verifies that each patch
  applied.

## How to run

```bash
repro/kernel_fixes/run.sh          # ~40 min; SKIP_TROUTE=1: kernel harness only (~1 min)
```

Needs `uv`, `gfortran`, git and, for the network part, what `../short_ts_switch` needs.
The steps:
1. `fetch_data.py` fetches T-Route at d29f663 and NGWPC's kernels at `34e6984d` (#123
   merged) and `9a3c303e` (development, with #127), checked by SHA-256.
2. `sweep.py` runs the kernel harness; results go to `results/sweep.json`.
3. `troute_compare.sh` runs the network comparison; results go to
   `results/troute_compare.json`.
4. `check.py` checks the results.

## Kernel-level tests (`sweep.py`, 46,128 input cases)

`harness/driver.F90` calls the kernel on every case. `harness/cases.py` makes the cases:
- 16,128 structured: 9 channels (NWM-like, slope floor, estuary-like, steep, TwCC = 0,
  Bw > Tw, cs = 0, Wlostowski's 2020 channel) × 4 dt × 8 flow scales × 8 flow patterns
  (steady, sharp rise, fall, lateral only, headwater, recession, negative lateral, dry)
  × 7 antecedent depths;
- 30,000 random over NWM-like ranges.

Builds:
- T-Route's makefile flags (`-g -O2 -fPIC`), for every patch level, the optional patch,
  and NGWPC's two kernels;
- `-O0 -fcheck=all -finit-real=snan`: every uninitialized real is a signalling NaN, so a
  read raises IEEE invalid;
- instrumented copies that count how often each code path is taken.

| Test | Unpatched (d29f663) | Corrected (0001–0008) |
|---|---|---|
| Cases that read an undefined real (snan build) | **39,104** of 46,128 | 0 |
| Cases raising IEEE invalid at `-O2` (0/0 in `courant`) | 88 | 0 |
| Outputs that depend on what is in the output arguments on entry (qdc = 1; X = −999) | 3,290 dry cases take the flow branch; X passes through in 3,832 | none |
| Call order / stack state changes results | not in this harness (see below) | no |
| Manning flow at the published depth within 1% of the published outflow (flowing cases) | 20% (median mismatch 78%) | 35% (median 3.5%) |

Each patch changes results only where its own code path is taken. The path is read from
an instrumented build one level down; for 0008 it is read from its own restart counter.
Instrumented and plain builds agree bitwise.

| Patch | Cases changed (flow, velocity or depth) | On its path | Off its path |
|---|---|---|---|
| 0001 | 42 | — | 0 against the unpatched kernel with undefined reals zeroed: the 42 are retried cases, where 0001 also resets `Qj_0` per try, as WRF-Hydro does |
| 0002 | 0 | 0 | 0 |
| 0003 | 0 | 0 | 0. In NGWPC's merged #123 kernel (no 0003) the path is taken in 7 cases, and all 7 publish qdc = 0 with inflow |
| 0004 | 0 (through the C interface) | — | — |
| 0005 | 0 (ck/cn/X change in the 3,832 dry cases only) | — | 0 |
| 0006 | 17,275 | 17,275 (negative step or zero slope) | 0 |
| 0007 | 1,309 | 1,309 (abandoned searches) | 0 |
| 0008 | 19,564 | 20,763 (restart fired) | 0 |

Notes:
- **Port fidelity to NGWPC.**
  - d29f663 + 0001–0008 and NGWPC `development` take the same paths (restarts 20,763 vs
    20,766; abandoned 5,427 vs 5,392). Their outflows differ by > 10⁻³ in 331 cases,
    because NGWPC's earlier performance refactor (7c9153ff) reorders floating-point work
    in an ill-conditioned solver.
  - 0006–0008 reproduce NGWPC's kernel diffs line for line, except that d29f663 has no
    hoisted `sqrt(s0)` arguments.
- The sweep is deliberately adversarial: depths inconsistent with flows, all dt. Its rates
  show where the code paths are, not how often T-Route meets them; the network counts below
  do that.
- The unpatched kernel happened to be repeatable in this Fortran harness and in plain ctypes
  scripts: what it reads depends on registers and stack left by the caller. The
  `-finit-real=snan` count is the compiler-independent evidence; the determinism test below shows
  the variation in a heavier process.

## Network results (`troute_compare.sh`, dt = 300 s)

`troute_compare.sh` builds T-Route several times, each in a working copy of
`../short_ts_switch` with its own environment:
- `unpatched`;
- `L1`;
- `L5`;
- `L7` (diagnostic);
- `corrected` (L8);
- `corrected+x`;
- instrumented `trace-L1` and `trace-L8`.

Each build runs that experiment's two cases with `assume_short_ts` True and False:
- the Potomac synthetic 25 mm storm (16,454 segments, 40 days);
- LowerColorado_TX with 28 h of recorded NWM forcing from the NWM's routed flows
  (11,248 segments; T-Route's initial depth is 0).

Results are in `results/troute_compare.json`.

**Determinism test.** The test makes 6,000 Potomac-like kernel calls through
ctypes in two fresh processes (`../short_ts_switch/qj_patch_compare.py --kernel-batch`):
- the unpatched kernel returned different outflows in 14–50% of calls, depending on the
  run (four runs so far);
- the corrected kernel returned identical outflows every time.

**Headwaters** receive no upstream inflow, so they cannot depend on `assume_short_ts`:
- unpatched: 3,629 of 6,069 Potomac and 755 of 3,871 LowerColorado headwaters differ
  between True and False;
- corrected: 0 and 0.

**Volume** (change in routed volume, %: network = sum over every segment, outlet = at
the outlet):

| Run | Unpatched → corrected: network / outlet | 0006–0007 without 0008 (unpatched → L7): network / outlet | 0008 alone (L7 → corrected): network |
|---|---|---|---|
| Potomac, True | −0.005 / 0.0 | −0.005 / 0.0 | −0.0001 |
| Potomac, False | −0.14 / −0.25 | **−1.04 / −1.63** | +0.91 |
| LowerColorado, True | +0.03 / 0.0 | **−0.54** / 0.0 | +0.57 |
| LowerColorado, False | +0.03 / 0.0 | **−1.14** / 0.0 | +1.19 |

On the fork review's LowerColorado cold starts the same comparison is −13 to −16% without
0008 and +0.9 to +2.1% with it. The LowerColorado outlet here does not move
within the 28-h window.

**How often the code paths are taken** (per million kernel calls; 1.9 × 10⁸ calls per
Potomac run, 3.8 × 10⁶ per LowerColorado run):

| Event | Potomac True / False, before (L1) | Potomac True / False, corrected | LowerColorado True / False, before | LowerColorado True / False, corrected |
|---|---|---|---|---|
| search ended at a negative Secant step (false convergence, 0006) | 2,809 / 2,809 | 0 (now 10,930 / 11,570 halvings) | 1,326 / 2,080 | 0 (3,676 / 7,257 halvings) |
| degenerate-root restart (0008) | — | 355 / 395 | — | 11,790 / 11,420 |
| abandoned search (0007 holds depth) | 0 / 0 | 0 / 3.5 | 0 / 0 | 63 / 90 |
| solve met tolerance on its last pass (0002) | 0 / 0 | 0.011 / 0.037 | 0 / 0 | 0 / 0.26 |
| loop skipped after a retry (0003) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

So before the corrections, about 0.28% of Potomac kernel calls published a depth that is
not a root of the depth equation. The restarts on LowerColorado (1.2% of calls) come mostly
from T-Route's cold start at depth 0.

**Size of the change** (dt = 300 s; "segments" = segments whose hourly flow differs by
> 1% / > 10% of their own peak):

| Run | Unpatched → corrected | of which 0001 alone (unpatched → L1) |
|---|---|---|
| Potomac, True | outlet 2195 → 2196 m³/s (+0.05%), −0.1 h; 51 / 0 segments; largest 2.0% of peak | nothing above 0.66% of a peak |
| Potomac, False | outlet 1587 → 1586 m³/s (−0.06%), −0.1 h; 2,743 / 382 segments; largest 78% | 1,378 / 163 |
| LowerColorado, True | outlet 76.94 m³/s, unchanged; 571 / 142 | 46 / 4 |
| LowerColorado, False | outlet 75.30 → 75.31 m³/s; 1,792 / 552 (small peaks) | 578 / 235 |

- 0002–0005 change nothing on either network (L1 → L5 identical).
- The ../short_ts_switch headline (Potomac, True vs False, outlet peak) moves from +38.3% / −77.6 h to
  **+38.5% / −77.6 h**. LowerColorado moves from +2.18% to +2.16%.
- The full rerun of `../short_ts_switch` with the corrected kernel has every dt; old and
  new values are in its `expected/kernel_update_2026-10-09.json`.

**Optional Cunge-X patch** (corrected → corrected+x; under review in NCAR/wrf_hydro_nwm_public#923):

| Run | Outlet peak | Peak time | Volume, network | Segments > 1% / > 10% of peak | Largest |
|---|---|---|---|---|---|
| Potomac, True | −1.7% (2196 → 2158 m³/s) | +2.5 h | −0.01% | 3,158 / 234 | 30% |
| Potomac, False | +1.3% (1586 → 1606 m³/s) | −0.5 h | +0.23% | 2,778 / 543 | 64% |
| LowerColorado, True / False | unchanged | 0 | +0.004% / +0.04% | 624 / 34 and 899 / 298 | 22% / 633% (small peaks) |

With it, the Potomac True-vs-False comparison would be +34.4% / −74.6 h.

## Checks (`check.py`)

140 checks, all passing (macOS arm64, gfortran 15.2.0, 2026-10-09). They cover:
- the corrected kernel reads no undefined value, gives the same result in any call order,
  and ignores what is in its output arguments on entry;
- each patch changes no case off its path;
- instrumented and plain builds agree bitwise, both in the sweep and on the networks;
- the determinism test and the headwater test pass with the corrected kernel;
- regression against `expected/expected.json` (sweep counts exact; network numbers rel
  10⁻³, percentages ±0.5 points).

## Caveats

- One platform: macOS arm64, gfortran 15.2.0. What the unpatched kernel reads from
  undefined memory depends on compiler, flags and calling context. So its results, and the
  "unpatched → corrected" differences driven by 0001, are not portable. The corrected
  kernel's are.
- 0006–0008 change the solver's strategy, not only remove undefined behaviour.
  - The author's rule includes them because false convergence is a true error, and its
    fix needs 0008 not to lose water.
  - 0007 (hold the depth) is a policy.
  - 0008's thresholds (a tenth of the estimate, four seeds) are NGWPC's choices and have
    not been evaluated here beyond volume and determinism.
- The residual test still checks only the step size (audit M8). Convergence on the
  residual is open, as Taher Chegini notes in #123.
- 0003's bug is present in NGWPC/t-route as merged in #123. NGWPC `development` avoids it
  in the sweep only because 4ecefec1's restart intercepts those cases first. Worth
  reporting to Taher Chegini.
