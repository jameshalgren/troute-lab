"""Work-counting copy of the float32 MC kernel port, for the cost-variability experiment.

Source of the copy: ../short_ts_switch/closure_port.py (sha256 448e74af...c6c9, 2026-10-30),
itself a port of CIROH-UA/t-route d29f663 src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90
(`muskingcungenwm` L8-186, `secant2_h` L198-334, `hydraulic_geometry` L374-430), with the
corrected-kernel mode (../kernel_fixes/patches/0001-0008). Everything from the imports
down to the end of `_secant2_h` is that file's text verbatim. `mc_count` is
`closure_port.mc_kernel` with the closure diagnostics replaced by work counters; every
statement that sets qdc or the depth is unchanged. check.py replays every call of every
run through the unmodified closure_port.mc_kernel and requires identical outflow, depth,
iteration count and try count.

Cost of one kernel call (what can vary between calls):
- the secant loop (Fortran L82-118): each pass is two `secant2_h` calls (interval 1 at
  h_0, interval 2 at h) plus the secant update. Passes are counted in `n_iter`, summed
  over every restart of the loop;
- restarts of the loop at label 110 (Fortran L120-128 and patches 0002-0008): a collapsed
  search restarted from normal-depth seeds (patch 0008, `n_collapse`), or a search that
  did not converge (iter >= maxiter, or a stalled secant), restarted with a widened bracket
  and maxiter + 25 (`n_noconv`); after four tries the corrected kernel holds the previous
  depth and evaluates both intervals once more (patch 0007, `fail` = 1, two extra
  secant2_h calls);
- the negative-flow guard (Fortran L147-156) and the water test (L72-73) are O(1).
So the work of a call is n_eval = 2 * n_iter + 2 * fail secant2_h evaluations (corrected
kernel), plus a fixed part (bankfull depth, initial guesses, the guard, and, in the
compiled kernel only, the velocity and `courant` calls after the loop, L161-181).
"""
from __future__ import annotations

import numpy as np
from numba import njit

F = np.float32
F0, F1, F2, F3, F5 = F(0.0), F(1.0), F(2.0), F(3.0), F(5.0)
FH, F025 = F(0.5), F(0.25)
F23, F53 = F2 / F3, F5 / F3            # 2.0_prec/3.0_prec, 5.0_prec/3.0_prec (folded in float32)
MINDEPTH, AERR0, RTOL = F(0.01), F(0.01), F(0.01)
F133, F067, F09, FBIG = F(1.33), F(0.67), F(0.9), F(0.00001)

# indices of the diagnostic tuple returned by mc_kernel
DIAG = ("active", "Ck", "dx_over_Ck", "Km", "X1_raw", "X1", "X2_raw", "X2", "qref", "width",
        "over", "h", "bfd", "C1", "C2", "C3", "C4", "guard", "iters", "tries")


@njit(cache=True, inline="always")
def _geom(h, bfd, bw, twcc, z):
    """hydraulic_geometry (L374-430), including the NWM 3.0 no-floodplain exception."""
    twl = bw + F2 * z * h
    hgt = max(h - bfd, F0)
    hlt = min(bfd, h)
    if hgt > F0 and twcc <= F0:
        hgt = F0
        hlt = h
    area = (bw + hlt * z) * hlt
    wp = bw + F2 * hlt * np.sqrt(F1 + z * z)
    areac = twcc * hgt
    wpc = twcc + (F2 * hgt) if hgt > F0 else F0
    r = (area + areac) / (wp + wpc)
    return twl, r, area, areac, wp, wpc


@njit(cache=True, inline="always")
def _secant2_h(z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, interval,
               qj_in, c1p, c2p, c3p, c4p):
    """secant2_h (L198-334). Returns Qj, C1..C4, X and the closure internals."""
    twl, R, AREA, AREAC, WP, WPC = _geom(h, bfd, bw, twcc, z)
    over = (h > bfd) and (twcc > F0) and (ncc > F0)
    if over:
        Ck = max(F0, ((np.sqrt(s0) / n) * ((F53 * R ** F23) - ((F23 * R ** F53)
                 * (F2 * np.sqrt(F1 + z * z) / (bw + F2 * bfd * z)))) * AREA
                 + ((np.sqrt(s0) / ncc) * F53 * (h - bfd) ** F23) * AREAC) / (AREA + AREAC))
    elif h > F0:
        Ck = max(F0, (np.sqrt(s0) / n) * ((F53 * R ** F23) - ((F23 * R ** F53)
                 * (F2 * np.sqrt(F1 + z * z) / (bw + F2 * h * z)))))
    else:
        Ck = F0
    if Ck > F0:
        dxck = dx / Ck
        Km = max(dt, dxck)
    else:
        dxck = F(np.inf)
        Km = dt
    xraw = F(np.nan)
    qref = F(np.nan)
    width = F(np.nan)
    if over and Ck > F0:
        width = twcc
        if interval == 1:
            qref = qj_in
            xraw = FH * (F1 - (qj_in / (F2 * twcc * s0 * Ck * dx)))
            X = min(FH, max(F0, xraw))
        else:
            qref = (c1p * qup) + (c2p * quc) + (c3p * qdp) + c4p
            xraw = FH * (F1 - (qref / (F2 * twcc * s0 * Ck * dx)))
            X = min(FH, max(F025, xraw))
    elif Ck > F0:
        width = twl
        if interval == 1:
            qref = qj_in
            xraw = FH * (F1 - (qj_in / (F2 * twl * s0 * Ck * dx)))
            X = min(FH, max(F0, xraw))
        else:
            qref = (c1p * qup) + (c2p * quc) + (c3p * qdp) + c4p
            xraw = FH * (F1 - (qref / (F2 * twl * s0 * Ck * dx)))
            X = min(FH, max(F025, xraw))
    else:
        X = FH
    D = (Km * (F1 - X) + dt / F2)
    C1 = (Km * X + dt / F2) / D
    C2 = (dt / F2 - Km * X) / D
    C3 = (Km * (F1 - X) - dt / F2) / D
    C4 = (ql * dt) / D
    if interval == 2:
        if (C4 < F0) and (abs(C4) > (C1 * qup) + (C2 * quc) + (C3 * qdp)):
            C4 = -((C1 * qup) + (C2 * quc) + (C3 * qdp))
    if (WP + WPC) > F0:
        Qj = ((C1 * qup) + (C2 * quc) + (C3 * qdp) + C4) - ((F1 / (((WP * n) + (WPC * ncc)) / (WP + WPC)))
                                                           * (AREA + AREAC) * (R ** F23) * np.sqrt(s0))
    else:
        Qj = F0
    return Qj, C1, C2, C3, C4, X, Ck, dxck, Km, xraw, qref, width, over



@njit(cache=True)
def mc_count(dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, depthp, qj0, corrected=True):
    """closure_port.mc_kernel with work counters. All float arguments float32.
    Returns (qdc, depthc, n_iter, n_collapse, n_noconv, fail, guard, active):
      n_iter      secant passes summed over all tries (== closure_port diag 'iters')
      n_collapse  patch-0008 restarts; n_noconv: restarts after a non-converged search
      fail        1 if the fifth try was reached (corrected: depth held, patch 0007, two
                  more secant2_h calls; d29f663: last iterate published)
                  n_collapse + n_noconv + fail == closure_port diag 'tries'
      guard       0 none, 1 qdc = max(...) branch, 2 qdc = 0 branch (Fortran L149-156)
      active      0 if there was no water to route (early return)"""
    secant = corrected            # patches 0006-0008 are part of the corrected kernel
    maxiter = 100
    aerror = AERR0
    rerror = F1
    tries = 0
    n_collapse = 0
    n_noconv = 0
    fail = 0
    if cs == F0:
        z = F1
    else:
        z = F1 / cs
    if bw > tw:
        bfd = bw / FBIG
    elif bw == tw:
        bfd = bw / (F2 * z)
    else:
        bfd = (tw - bw) / (F2 * z)
    qref0 = max(max(qup, quc), max(qdp, ql))         # patch 0008
    h_seed = F0
    h_low = F0
    h_last = F0
    depthc = max(depthp, F0)
    h = (depthc * F133) + MINDEPTH
    h_0 = (depthc * F067)
    if not (ql > F0 or qup > F0 or quc > F0 or qdp > F0):
        return F0, F0, 0, 0, 0, 0, 0, 0
    Qj_0 = qj0
    Qj = F0
    C1 = C2 = C3 = C4 = F0
    total = 0
    stalled = False
    while True:                                           # label 110
        if corrected:                                     # patch 0001 (+ 0006)
            stalled = False
            Qj_0 = F0
            Qj = F0
            C1 = C2 = C3 = C4 = F0
        it = 0
        while rerror > RTOL and aerror >= MINDEPTH and it <= maxiter:
            (Qj_0, C1, C2, C3, C4, _x1, _ck, _dk, _km, _x1r, _qr, _w, _ov) = _secant2_h(
                z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h_0, 1, Qj_0, C1, C2, C3, C4)
            (Qj, C1, C2, C3, C4, _x2, _ck2, _dk2, _km2, _x2r, _qr2, _w2, _ov2) = _secant2_h(
                z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, 2, Qj, C1, C2, C3, C4)
            if Qj_0 - Qj != F0:
                h_1 = h - ((Qj * (h_0 - h)) / (Qj_0 - Qj))
                if h_1 < F0:
                    h_1 = (FH * h) if secant else h       # patch 0006
            else:
                h_1 = h
                if secant:
                    stalled = True                        # patch 0006
            if h > F0:
                rerror = abs((h_1 - h) / h)
                aerror = abs(h_1 - h)
            else:
                rerror = F0
                aerror = F09
            h_0 = max(F0, h)
            h = max(F0, h_1)
            it += 1
            total += 1
            if h < MINDEPTH:
                break                                     # goto 111
            if stalled:
                break                                     # goto 111 (patch 0006)
        if corrected:                                     # patch 0008: degenerate-root restart
            qmc = (C1 * qup) + (C2 * quc) + (C3 * qdp) + C4
            collapsed = (qref0 > F0) and (abs(Qj) > F(0.1) * abs(qmc)) and (abs(Qj) > F(0.01))
            if h_last > F0 and abs(h - h_last) <= F(0.05) * max(h, MINDEPTH) and Qj <= FH * abs(qmc):
                collapsed = False
            if collapsed and tries <= 4:
                tries += 1
                n_collapse += 1
                h_last = h
                if h_seed == F0:
                    h_seed = (qref0 * n / (bw * np.sqrt(s0))) ** F(0.6)
                    h_low = (qref0 * n / (max(max(twcc, tw), bw) * np.sqrt(s0))) ** F(0.6)
                if tries == 1:
                    h = h_low
                elif tries == 2:
                    h = np.sqrt(h_low * h_seed)
                elif tries == 3:
                    h = h_seed
                else:
                    h = F(4.0) * h_seed
                h_0 = h * F067
                h = h * F133
                maxiter += 25
                aerror = AERR0
                rerror = F1
                continue                                  # goto 110
        if corrected:                                     # patches 0002, 0003, 0006, 0007
            converged = (not stalled) and ((rerror <= RTOL) or (aerror < MINDEPTH))
            if (not converged) and (stalled or it >= maxiter):
                tries += 1
                if tries <= 4:
                    n_noconv += 1
                    h = h * F133
                    h_0 = h_0 * F067
                    maxiter += 25
                    rerror = F1
                    aerror = AERR0
                    continue                              # goto 110
                fail = 1
                if not secant:                            # d29f663: publish the last iterate
                    break
                h = max(depthp, MINDEPTH)                 # patch 0007: hold the depth
                (Qj_0, C1, C2, C3, C4, _x1, _ck, _dk, _km, _x1r, _qr, _w, _ov) = _secant2_h(
                    z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, 1, Qj_0, C1, C2, C3, C4)
                (Qj, C1, C2, C3, C4, _x2, _ck2, _dk2, _km2, _x2r, _qr2, _w2, _ov2) = _secant2_h(
                    z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, 2, Qj, C1, C2, C3, C4)
            break
        if it >= maxiter:
            tries += 1
            if tries <= 4:
                n_noconv += 1
                h = h * F133
                h_0 = h_0 * F067
                maxiter += 25
                continue                                  # goto 110
            fail = 1
        break
    s = (C1 * qup) + (C2 * quc) + (C3 * qdp) + C4
    guard = 0
    if s < F0:
        if (C4 < F0) and (abs(C4) > (C1 * qup) + (C2 * quc) + (C3 * qdp)):
            qdc = F0
            guard = 2
        else:
            qdc = max(((C1 * qup) + (C2 * quc) + C4), ((C1 * qup) + (C3 * qdp) + C4))
            guard = 1
    else:
        qdc = s
    return qdc, h, total, n_collapse, n_noconv, fail, guard, 1
