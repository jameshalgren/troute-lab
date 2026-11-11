"""Instrumented float32 port of the courant_test kernel (MCsingleSegStime_f2py_NOLOOP-anw.f90).

Source: awlostowski-noaa/t-route @ 27e06ee, `muskingcungenwm` (L10-192), `secant2_h`
(L204-370) and `courant` (L377-411), as fetched into build/courant/. Used only by
run_extended.py to expose what the compiled kernel does not return: the routing
parameters its Cunge closure produces (Ck, dx/Ck, Km, X from both secant estimates, the
unclamped X, the reference discharge, C1..C4). The hydrographs reported by the extension
always come from the compiled Fortran; the port runs beside it on the same inputs
("shadow mode") and run_extended.py reports how closely its outflow and depth agree.

Faithfulness notes
- float32 throughout (varPrecision.f90: prec = kind(1.0)), numpy float32 scalars, so
  powf/sqrtf as in the compiled code. The compiled code may contract a*b+c into fused
  multiply-adds (gcc's default -ffp-contract=fast at -O3), so agreement is to float32
  rounding, not bit-for-bit.
- Argument aliasing is reproduced: secant2_h's intent(out) C1..C4 are the caller's
  variables, so the interval-2 X (L321/L331) reads the interval-1 coefficients; the
  interval-1 X (L318/L327) reads its intent(out) `Qj`, which is the caller's `Qj_0`.
- `Qj_0` is read before it is set on the first secant iteration (the uninitialized read
  fixed by ../kernel_fixes patch 0001, here in the 2020 kernel). Its value is whatever the compiled code
  leaves there. `qj0_mode` selects the emulation: "zero" (WRF-Hydro's initialization)
  or "carry" (the value left by the previous kernel call). run_extended.py reports
  agreement for the chosen mode.
- f2py initializes the intent(out) `qdc` to 0 before the call, so the "water to route?"
  test (L81) sees qdc = 0, as here.
"""
from __future__ import annotations

import numpy as np

F = np.float32
_0, _1, _2, _3, _5 = F(0.0), F(1.0), F(2.0), F(3.0), F(5.0)
_H, _025 = F(0.5), F(0.25)
_P23, _P53 = _2 / _3, _5 / _3            # 2.0_prec/3.0_prec, 5.0_prec/3.0_prec
_MINDEPTH = F(0.01)
_133, _067 = F(1.33), F(0.67)


def _secant2_h(z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, interval, qj_in, cprev):
    """Port of secant2_h. Returns (Qj, (C1..C4), X, diag)."""
    twl = bw + _2 * z * h
    WPC = _0
    AREAC = _0
    if h > bfd:
        AREA = (bw + bfd * z) * bfd
        AREAC = twcc * (h - bfd)
        WP = bw + _2 * bfd * np.sqrt(_1 + z * z)
        WPC = twcc + _2 * (h - bfd)
        R = (AREA + AREAC) / (WP + WPC)
    else:
        AREA = (bw + h * z) * h
        WP = bw + _2 * h * np.sqrt(_1 + z * z)
        R = AREA / WP if WP > _0 else _0
    if h > bfd:
        Ck = max(_0, ((np.sqrt(s0) / n) * (_P53 * R ** _P23 - (_P23 * R ** _P53
              * (_2 * np.sqrt(_1 + z * z) / (bw + _2 * bfd * z)))) * AREA
              + ((np.sqrt(s0) / ncc) * _P53 * (h - bfd) ** _P23) * AREAC) / (AREA + AREAC))
    elif h > _0:
        Ck = max(_0, (np.sqrt(s0) / n) * (_P53 * R ** _P23 - (_P23 * R ** _P53
                 * (_2 * np.sqrt(_1 + z * z) / (bw + _2 * h * z)))))
    else:
        Ck = _0
    dx_over_ck = dx / Ck if Ck > _0 else F(np.inf)
    Km = max(dt, dx_over_ck) if Ck > _0 else dt
    c1p, c2p, c3p, c4p = cprev
    qref = x_raw = width = np.nan
    if h > bfd:
        width = twcc
        if interval == 1:
            qref = qj_in
            x_raw = _H * (_1 - (qj_in / (_2 * twcc * s0 * Ck * dx)))
            X = min(_H, max(_0, x_raw))
        else:
            qref = (c1p * qup) + (c2p * quc) + (c3p * qdp) + c4p
            x_raw = _H * (_1 - (qref / (_2 * twcc * s0 * Ck * dx)))
            X = min(_H, max(_025, x_raw))
    else:
        width = twl
        if Ck > _0:
            if interval == 1:
                qref = qj_in
                x_raw = _H * (_1 - (qj_in / (_2 * twl * s0 * Ck * dx)))
                X = min(_H, max(_0, x_raw))
            else:
                qref = (c1p * qup) + (c2p * quc) + (c3p * qdp) + c4p
                x_raw = _H * (_1 - (qref / (_2 * twl * s0 * Ck * dx)))
                X = min(_H, max(_025, x_raw))
        else:
            X = _H
    D = Km * (_1 - X) + dt / _2
    C1 = (Km * X + dt / _2) / D
    C2 = (dt / _2 - Km * X) / D
    C3 = (Km * (_1 - X) - dt / _2) / D
    C4 = (ql * dt) / D
    if interval == 2:
        if (C4 < _0) and (abs(C4) > (C1 * qup) + (C2 * quc) + (C3 * qdp)):
            C4 = -((C1 * qup) + (C2 * quc) + (C3 * qdp))
    if (WP + WPC) > _0:
        Qj = ((C1 * qup) + (C2 * quc) + (C3 * qdp) + C4) - ((_1 / (((WP * n) + (WPC * ncc)) / (WP + WPC)))
                                                             * (AREA + AREAC) * (R ** _P23) * np.sqrt(s0))
    else:
        Qj = _0
    diag = {"h": h, "width": width, "Ck": Ck, "dx_over_Ck": dx_over_ck, "Km": Km,
            "qref": qref, "X_raw": x_raw, "X": X}
    return Qj, (C1, C2, C3, C4), X, diag


def _courant(h, bfd, bw, twcc, ncc, s0, n, z, dx, dt):
    h_gt_bf = max(h - bfd, _0)
    h_lt_bf = min(bfd, h)
    AREA = (bw + h_lt_bf * z) * h_lt_bf
    WP = bw + _2 * h_lt_bf * np.sqrt(_1 + z * z)
    AREAC = twcc * h_gt_bf
    WPC = twcc + _2 * h_gt_bf if h_gt_bf > _0 else _0
    R = (AREA + AREAC) / (WP + WPC)
    ck = ((np.sqrt(s0) / n) * (_P53 * R ** _P23 - (_P23 * R ** _P53
          * (_2 * np.sqrt(_1 + z * z) / (bw + _2 * h_lt_bf * z)))) * AREA
          + ((np.sqrt(s0) / ncc) * _P53 * h_gt_bf ** _P23) * AREAC) / (AREA + AREAC)
    return ck, ck * (dt / dx)


class Kernel:
    """Stateful wrapper so qj0_mode='carry' can keep the last Qj_0 between calls."""

    def __init__(self, qj0_mode: str = "zero"):
        if qj0_mode not in ("zero", "carry"):
            raise ValueError(qj0_mode)
        self.mode = qj0_mode
        self.qj0_last = _0

    def __call__(self, dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, velp, depthp):
        """Port of muskingcungenwm. Returns (qdc, velc, depthc, ck, cn, X, internals)."""
        dt, qup, quc, qdp, ql, dx = map(F, (dt, qup, quc, qdp, ql, dx))
        bw, tw, twcc, n, ncc, cs, s0, depthp = map(F, (bw, tw, twcc, n, ncc, cs, s0, depthp))
        qdc = _0                                  # f2py zero-initializes intent(out)
        maxiter, tries = 100, 0
        aerror, rerror = F(0.01), _1
        z = _1 if cs == _0 else _1 / cs
        if bw > tw:
            bfd = bw / F(0.00001)
        elif bw == tw:
            bfd = bw / (_2 * z)
        else:
            bfd = (tw - bw) / (_2 * z)
        depthc = max(depthp, _0)
        h = (depthc * _133) + _MINDEPTH
        h_0 = depthc * _067
        Qj_0 = self.qj0_last if self.mode == "carry" else _0
        Qj = _0
        C = (_0, _0, _0, _0)
        X = _0
        d1 = d2 = None
        total_iter = 0
        guard = 0
        velc = _0
        if ql > _0 or qup > _0 or qdp > _0 or qdc > _0:
            while True:                                         # label 110
                it = 0
                while rerror > F(0.01) and aerror >= _MINDEPTH and it <= maxiter:
                    Qj_0, C, X, d1 = _secant2_h(z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc,
                                                h_0, 1, Qj_0, C)
                    Qj, C, X, d2 = _secant2_h(z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc,
                                              h, 2, Qj, C)
                    if Qj_0 - Qj != _0:
                        h_1 = h - ((Qj * (h_0 - h)) / (Qj_0 - Qj))
                        if h_1 < _0:
                            h_1 = h
                    else:
                        h_1 = h
                    if h > _0:
                        rerror = abs((h_1 - h) / h)
                        aerror = abs(h_1 - h)
                    else:
                        rerror = _0
                        aerror = F(0.9)
                    h_0 = max(_0, h)
                    h = max(_0, h_1)
                    it += 1
                    total_iter += 1
                    if h < _MINDEPTH:
                        break
                if it >= maxiter:
                    tries += 1
                    if tries <= 4:
                        h = h * _133
                        h_0 = h_0 * _067
                        maxiter += 25
                        continue
                break
            C1, C2, C3, C4 = C
            s = (C1 * qup) + (C2 * quc) + (C3 * qdp) + C4
            if s < _0:
                if (C4 < _0) and (abs(C4) > (C1 * qup) + (C2 * quc) + (C3 * qdp)):
                    qdc, guard = _0, 2
                else:
                    qdc, guard = max((C1 * qup) + (C2 * quc) + C4, (C1 * qup) + (C3 * qdp) + C4), 1
            else:
                qdc = s
            twl = bw + (_2 * z * h)
            R = (h * (bw + twl) / _2) / (bw + _2 * (((twl - bw) / _2) ** _2 + h ** _2) ** _H)
            velc = (_1 / n) * (R ** _P23) * np.sqrt(s0)
            depthc = h
        else:
            qdc = _0
            depthc = _0
        self.qj0_last = Qj_0
        ck, cn = _courant(h, bfd, bw, twcc, ncc, s0, n, z, dx, dt)
        internals = None
        if d2 is not None:
            internals = {
                # final interval-2 call: the coefficients that produced qdc
                "h_closure": float(d2["h"]), "width": float(d2["width"]), "Ck": float(d2["Ck"]),
                "dx_over_Ck": float(d2["dx_over_Ck"]), "Km": float(d2["Km"]),
                "qref": float(d2["qref"]), "X2_raw": float(d2["X_raw"]), "X2": float(d2["X"]),
                # interval-1 call of the same (last) secant iteration
                "X1_raw": float(d1["X_raw"]), "X1": float(d1["X"]),
                "C1": float(C[0]), "C2": float(C[1]), "C3": float(C[2]), "C4": float(C[3]),
                "iterations": total_iter, "tries": tries, "guard": guard,
                "courant_closure": float(d2["Ck"] * dt / dx),
                # cell Reynolds number (Ponce) with the kernel's own reference discharge,
                # width, celerity: D = Q/(B*S0*Ck*dx); the kernel's X2_raw = 0.5*(1 - D/2)
                "D_cell": float(d2["qref"] / (d2["width"] * s0 * d2["Ck"] * dx)) if d2["Ck"] > 0 else float("nan"),
            }
        return float(qdc), float(velc), float(depthc), float(ck), float(cn), float(X), internals
