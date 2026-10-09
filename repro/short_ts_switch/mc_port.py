"""Line-by-line Python port of T-Route's Muskingum-Cunge kernel, with diagnostics.

Source: CIROH-UA/t-route d29f663, src/kernel/muskingum/MCsingleSegStime_f2py_NOLOOP.f90
(`muskingcungenwm`, `secant2_h`, `courant`, `hydraulic_geometry`). Used only by
mechanism.py, to expose what the compiled kernel does not return: the coefficients
C1..C4, Km and X actually used for qdc, and whether the negative-flow guard fired.

Differences from the compiled kernel:
- float64 arithmetic (the kernel is float32);
- `Qj_0` starts at `qj0_init` (default 0.0). In the Fortran it is read before it is set:
  on the first secant iteration `secant2_h(..., interval=1)` uses its intent(out) `Qj`
  argument (the caller's uninitialized `Qj_0`) in the X formula (L281, L291). The
  compiled kernel therefore uses whatever value that variable holds (its output varies
  between processes); see README "Mechanism checks", E.
mechanism.py validates the port against T-Route's own outputs (mainstem replays);
qj_patch_compare.py validates it against the compiled kernel with that read patched.
"""
from __future__ import annotations

import math


def _geom(h, bfd, bw, twcc, z):
    twl = bw + 2.0 * z * h
    hgt = max(h - bfd, 0.0)
    hlt = min(bfd, h)
    if hgt > 0.0 and twcc <= 0.0:          # NWM 3.0 exception: no floodplain width
        hgt, hlt = 0.0, h
    area = (bw + hlt * z) * hlt
    wp = bw + 2 * hlt * math.sqrt(1 + z * z)
    areac = twcc * hgt
    wpc = twcc + 2 * hgt if hgt > 0.0 else 0.0
    r = (area + areac) / (wp + wpc) if (wp + wpc) > 0 else 0.0
    return twl, r, area, areac, wp, wpc


def _secant2_h(z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, interval, qj_in, cprev):
    twl, R, AREA, AREAC, WP, WPC = _geom(h, bfd, bw, twcc, z)
    over = h > bfd and twcc > 0.0 and ncc > 0.0
    if over:
        ck = max(0.0, ((math.sqrt(s0) / n) * ((5 / 3) * R ** (2 / 3) - ((2 / 3) * R ** (5 / 3)
              * (2 * math.sqrt(1 + z * z) / (bw + 2 * bfd * z)))) * AREA
              + ((math.sqrt(s0) / ncc) * (5 / 3) * (h - bfd) ** (2 / 3)) * AREAC) / (AREA + AREAC))
    elif h > 0.0:
        ck = max(0.0, (math.sqrt(s0) / n) * ((5 / 3) * R ** (2 / 3) - ((2 / 3) * R ** (5 / 3)
                 * (2 * math.sqrt(1 + z * z) / (bw + 2 * h * z)))))
    else:
        ck = 0.0
    km = max(dt, dx / ck) if ck > 0 else dt
    w = twcc if (over and ck > 0) else twl
    if ck > 0.0:
        if interval == 1:                   # uses the incoming value of intent(out) Qj
            x = min(0.5, max(0.0, 0.5 * (1 - qj_in / (2 * w * s0 * ck * dx))))
        else:                               # uses C1..C4 left by the interval-1 call
            c1p, c2p, c3p, c4p = cprev
            x = min(0.5, max(0.25, 0.5 * (1 - (c1p * qup + c2p * quc + c3p * qdp + c4p)
                                         / (2 * w * s0 * ck * dx))))
    else:
        x = 0.5
    d = km * (1 - x) + dt / 2
    c1 = (km * x + dt / 2) / d
    c2 = (dt / 2 - km * x) / d
    c3 = (km * (1 - x) - dt / 2) / d
    c4 = ql * dt / d
    if interval == 2 and c4 < 0 and abs(c4) > c1 * qup + c2 * quc + c3 * qdp:
        c4 = -(c1 * qup + c2 * quc + c3 * qdp)
    if WP + WPC > 0:
        qj = (c1 * qup + c2 * quc + c3 * qdp + c4) - ((1 / ((WP * n + WPC * ncc) / (WP + WPC)))
              * (AREA + AREAC) * R ** (2 / 3) * math.sqrt(s0))
    else:
        qj = 0.0
    return qj, (c1, c2, c3, c4), x, km


def mc(dt, qup, quc, qdp, ql, dx, bw, tw, twcc, n, ncc, cs, s0, depthp, qj0_init=0.0):
    """One kernel call. Returns (qdc, depthc, diag) with diag = C (C1..C4), Km, X, clip
    (0 none, 1 negative-flow guard replaced the MC value, 2 set to zero)."""
    mindepth = 0.01
    aerror, rerror = 0.01, 1.0
    tries, maxiter = 0, 100
    z = 1.0 if cs == 0 else 1.0 / cs
    if bw > tw:
        bfd = bw / 0.00001
    elif bw == tw:
        bfd = bw / (2 * z)
    else:
        bfd = (tw - bw) / (2 * z)
    depthc = max(depthp, 0.0)
    h = depthc * 1.33 + mindepth
    h_0 = depthc * 0.67
    c = (0.0, 0.0, 0.0, 0.0)
    qj_0 = qj0_init
    x = km = float("nan")
    if not (ql > 0 or qup > 0 or quc > 0 or qdp > 0):
        return 0.0, 0.0, {"C": c, "Km": dt, "X": 0.5, "clip": 0}
    while True:
        it = 0
        while rerror > 0.01 and aerror >= mindepth and it <= maxiter:
            qj_0, c, x, km = _secant2_h(z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h_0, 1, qj_0, c)
            qj, c, x, km = _secant2_h(z, bw, bfd, twcc, s0, n, ncc, dt, dx, qdp, ql, qup, quc, h, 2, 0.0, c)
            h_1 = h - (qj * (h_0 - h)) / (qj_0 - qj) if qj_0 - qj != 0 else h
            if h_1 < 0:
                h_1 = h
            if h > 0:
                rerror, aerror = abs((h_1 - h) / h), abs(h_1 - h)
            else:
                rerror, aerror = 0.0, 0.9
            h_0 = max(0.0, h)
            h = max(0.0, h_1)
            it += 1
            if h < mindepth:
                break
        if it >= maxiter:
            tries += 1
            if tries <= 4:
                h *= 1.33
                h_0 *= 0.67
                maxiter += 25
                continue
        break
    c1, c2, c3, c4 = c
    s = c1 * qup + c2 * quc + c3 * qdp + c4
    clip = 0
    if s < 0:                               # T-Route/WRF-Hydro negative-flow guard (L149-156)
        if c4 < 0 and abs(c4) > c1 * qup + c2 * quc + c3 * qdp:
            qdc, clip = 0.0, 2
        else:
            qdc, clip = max(c1 * qup + c2 * quc + c4, c1 * qup + c3 * qdp + c4), 1
    else:
        qdc = s
    return qdc, h, {"C": c, "Km": km, "X": x, "clip": clip}
