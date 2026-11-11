"""Instrumented float32 port of T-Route's MC kernel, compiled with numba, for network replays.

Source: CIROH-UA/t-route d29f663, src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90
(`muskingcungenwm` L8-186, `secant2_h` L198-334, `hydraulic_geometry` L374-430). Used
only by closure_replay.py (README "Closure diagnostics on the network"). It replays every
segment-step of a recorded T-Route run with the inputs T-Route used, and records what the
compiled kernel does not return: the values the Cunge closure produced (Ck, dx/Ck, Km,
both X estimates, the reference discharge, the X width, C1..C4, the negative-flow guard).

Faithfulness notes
- float32 throughout (varPrecision: prec = kind(1.0)); every literal is a numpy float32
  constant, so numba keeps single precision (powf, sqrtf). Parentheses and the
  left-to-right order of the Fortran expressions are kept. The compiled kernel may fuse
  multiply-adds, so agreement is to float32 rounding, not bit-for-bit
  (closure_replay.py measures it).
- Argument aliasing as in the Fortran: `secant2_h`'s intent(out) C1..C4 are the caller's
  variables, so the interval-2 X (L285/L295) reads the interval-1 coefficients; the
  interval-1 X (L281/L291) reads its intent(out) `Qj`, i.e. the caller's `Qj_0`.
- `Qj_0` is read before it is set on the first secant iteration (an uninitialized read; fixed by ../kernel_fixes patch 0001).
  The port starts it at `qj0` (0.0 = the patched build of build_troute.py --patch-qj,
  which sets `Qj_0 = 0` per call and declares `Qj` intent(inout); WRF-Hydro also starts
  at 0). On later iterations the interval-1 X reads the previous iteration's
  interval-1 residual Qj_0 = f(h_0), not a discharge.
- reach.pyx initializes the intent(out) `qdc` to 0, so the "water to route?" test (L73)
  sees qdc = 0, as here.
- corrected=True (added 2026-10-09) follows the corrected kernel, the default build
  (../kernel_fixes/patches/0001-0008): Qj_0, Qj and C1..C4 reset to 0 at label 110 on
  every try; a solve that met tolerance on its last pass is converged; a retry restarts
  rerror and aerror (0004 and 0005 do not change qdc or depth); a negative Secant step
  halves h; a degenerate slope (Qj_0 == Qj) is a stall, not convergence; an abandoned
  search holds max(depthp, mindepth) and re-evaluates both intervals there; a search
  whose residual exceeds a tenth of the Muskingum estimate restarts from normal-depth
  seeds (0008, NGWPC 4ecefec1).
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
def mc_kernel(dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, depthp, qj0, corrected=False):
    """muskingcungenwm (L8-186). All arguments float32. Returns (qdc, depthc, diag) with
    diag in the order of DIAG (float32; flags as 0/1). corrected: see module docstring."""
    secant = corrected            # patches 0006-0008 are part of the corrected kernel
    maxiter = 100
    aerror = AERR0
    rerror = F1
    tries = 0
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
    nan = F(np.nan)
    if not (ql > F0 or qup > F0 or quc > F0 or qdp > F0):
        return F0, F0, (F0, nan, nan, dt, nan, nan, nan, nan, nan, nan, F0, F0, bfd,
                        nan, nan, nan, nan, F0, F0, F0)
    Qj_0 = qj0
    Qj = F0
    C1 = C2 = C3 = C4 = F0
    X1 = X1r = nan
    Ck = dxck = Km = X2r = X2 = qref = width = nan
    over = False
    hc = h
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
            (Qj_0, C1, C2, C3, C4, X1, _ck, _dk, _km, X1r, _qr, _w, _ov) = _secant2_h(
                z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h_0, 1, Qj_0, C1, C2, C3, C4)
            (Qj, C1, C2, C3, C4, X2, Ck, dxck, Km, X2r, qref, width, over) = _secant2_h(
                z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, 2, Qj, C1, C2, C3, C4)
            hc = h
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
                    h = h * F133
                    h_0 = h_0 * F067
                    maxiter += 25
                    rerror = F1
                    aerror = AERR0
                    continue                              # goto 110
                if not secant:                            # d29f663: publish the last iterate
                    break
                h = max(depthp, MINDEPTH)                 # patch 0007: hold the depth
                (Qj_0, C1, C2, C3, C4, X1, _ck, _dk, _km, X1r, _qr, _w, _ov) = _secant2_h(
                    z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, 1, Qj_0, C1, C2, C3, C4)
                (Qj, C1, C2, C3, C4, X2, Ck, dxck, Km, X2r, qref, width, over) = _secant2_h(
                    z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, 2, Qj, C1, C2, C3, C4)
                hc = h
            break
        if it >= maxiter:
            tries += 1
            if tries <= 4:
                h = h * F133
                h_0 = h_0 * F067
                maxiter += 25
                continue                                  # goto 110
        break
    s = (C1 * qup) + (C2 * quc) + (C3 * qdp) + C4
    guard = F0
    if s < F0:
        if (C4 < F0) and (abs(C4) > (C1 * qup) + (C2 * quc) + (C3 * qdp)):
            qdc = F0
            guard = F(2.0)
        else:
            qdc = max(((C1 * qup) + (C2 * quc) + C4), ((C1 * qup) + (C3 * qdp) + C4))
            guard = F1
    else:
        qdc = s
    return qdc, h, (F1, Ck, dxck, Km, X1r, X1, X2r, X2, qref, width, F(1.0 if over else 0.0), hc, bfd,
                    C1, C2, C3, C4, guard, F(total), F(tries))
