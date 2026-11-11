"""Which Muskingum X reproduces the physical diffusion of a flood wave?

AI-written (Claude, 2026-10-09); not reviewed. Runs, for one prismatic trapezoidal
channel at several segment lengths dx (so the cell Reynolds number
D_cell = Q/(B S0 c dx) spans 0.15 to 2.4):

  1. reference solutions of the diffusion problem the Muskingum-Cunge method is meant
     to reproduce:
       a. the analytical linear convection-diffusion solution (Hayami kernel, c and
          D = Q/(2 B S0) at the base flow), for a small pulse;
       b. a fine-grid (100 m) zero-inertia (diffusive-wave) solver in depth, for the
          same small pulse (checks a.) and for a large, nonlinear pulse;
  2. linear constant-parameter Muskingum-Cunge with Cunge's X and with the kernel's X
     (isolates the X question from everything else);
  3. the verbatim WRF-Hydro SUBMUSKINGCUNGE, original and patched, through the
     Fortran harness (build/driver, built by build_harness.py).

Writes results/summary.json, results/hydrographs_*.csv and results/fig_*.png.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.sparse import diags

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
RES = HERE / "results"

# ---- channel (in-bank trapezoid; NWM-like parameter names) ---------------------------
Q0 = 50.0        # base flow, m3/s
BW = 20.0        # bottom width, m
CS = 0.5         # ChSlp (side slope run/rise in the NWM sense: z = 1/ChSlp = 2)
Z = 1.0 / CS
MANN = 0.045     # Manning n
S0 = 1.0e-3      # bed slope
TW_BANKFULL = 400.0   # large: bankfull depth (Tw-Bw)/(2z) = 95 m, never reached
L = 64_000.0     # routed length, m
DT = 300.0       # s, the NWM channel time step
DXS = [500.0, 1000.0, 2000.0, 4000.0, 8000.0]
T_END = 40 * 3600.0
PULSE_T0 = 6 * 3600.0
PULSE_SIG = 1.0 * 3600.0
SMALL = 0.05 * Q0       # linear regime
LARGE = 3.0 * Q0        # nonlinear: 50 -> 200 m3/s


def geom(h: float | np.ndarray):
    A = (BW + Z * h) * h
    P = BW + 2.0 * h * math.sqrt(1.0 + Z * Z)
    R = A / P
    Q = A * R ** (2.0 / 3.0) * math.sqrt(S0) / MANN
    B = BW + 2.0 * Z * h
    # kinematic celerity dQ/dA, same expression as the WRF-Hydro kernel's in-bank Ck
    c = (math.sqrt(S0) / MANN) * ((5.0 / 3.0) * R ** (2.0 / 3.0)
                                   - (2.0 / 3.0) * R ** (5.0 / 3.0)
                                   * (2.0 * math.sqrt(1.0 + Z * Z) / (BW + 2.0 * h * Z)))
    return A, Q, B, c, R, P


def normal_depth(Q: float) -> float:
    lo, hi = 1e-6, 100.0
    for _ in range(200):
        m = 0.5 * (lo + hi)
        if geom(m)[1] < Q:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def tgrid(dt: float) -> np.ndarray:
    return np.arange(0.0, T_END + dt, dt)


def inflow(t: np.ndarray, amp: float) -> np.ndarray:
    return Q0 + amp * np.exp(-0.5 * ((t - PULSE_T0) / PULSE_SIG) ** 2)


# ---- 1a. analytical linear convection-diffusion (Hayami) ----------------------------
def hayami(t: np.ndarray, amp: float, c: float, D: float, x: float) -> np.ndarray:
    """Outflow at x for upstream Dirichlet inflow on a semi-infinite channel."""
    tf = np.arange(1.0, T_END + 1.0, 10.0)  # fine kernel grid (10 s)
    k = x / (2.0 * np.sqrt(math.pi * D * tf ** 3)) * np.exp(-((x - c * tf) ** 2) / (4.0 * D * tf))
    exc_in = inflow(tf, amp) - Q0
    out = np.convolve(exc_in, k)[: tf.size] * 10.0
    return Q0 + np.interp(t, tf, out)


# ---- 1b. zero-inertia (diffusive wave) reference, fine grid ---------------------------
def zero_inertia(t_out: np.ndarray, amp: float, dxf: float = 100.0) -> np.ndarray:
    Lext = 1.5 * L
    N = int(round(Lext / dxf))
    i_out = int(round(L / dxf))
    h0 = normal_depth(Q0)

    def conv(h):
        A, _, _, _, R, _ = geom(h)
        return A * R ** (2.0 / 3.0) / MANN

    def rhs(t, h):
        h = np.maximum(h, 1e-4)
        K = conv(0.5 * (h[:-1] + h[1:]))
        Sf = S0 - (h[1:] - h[:-1]) / dxf
        qf = K * np.sign(Sf) * np.sqrt(np.abs(Sf))          # interior faces
        q_in = inflow(np.array([t]), amp)[0]
        q_out = conv(h[-1]) * math.sqrt(S0)                    # normal-depth outlet
        qin = np.concatenate(([q_in], qf))
        qout = np.concatenate((qf, [q_out]))
        B = BW + 2.0 * Z * h
        return (qin - qout) / (dxf * B)

    jac = diags([1.0, 1.0, 1.0], [-1, 0, 1], shape=(N, N))
    sol = solve_ivp(rhs, (0.0, t_out[-1]), np.full(N, h0), method="BDF", t_eval=t_out,
                    jac_sparsity=jac, rtol=1e-7, atol=1e-9)
    if not sol.success:
        raise RuntimeError(sol.message)
    h = sol.y
    hm = 0.5 * (h[i_out - 1] + h[i_out])
    hp = 0.5 * (h[i_out] + h[i_out + 1])
    K = conv(np.stack([hm, hp]))
    Sf_m = S0 - (h[i_out] - h[i_out - 1]) / dxf
    Sf_p = S0 - (h[i_out + 1] - h[i_out]) / dxf
    return 0.5 * (K[0] * np.sqrt(Sf_m) + K[1] * np.sqrt(Sf_p))


# ---- 2. linear constant-parameter Muskingum-Cunge ------------------------------------
def linear_mc(amp: float, dx: float, X: float, c: float, dt: float) -> np.ndarray:
    K = dx / c  # (no K clamp needed: every case here has C <= 1)
    Dn = K * (1.0 - X) + dt / 2.0
    C1, C2, C3 = (K * X + dt / 2.0) / Dn, (dt / 2.0 - K * X) / Dn, (K * (1.0 - X) - dt / 2.0) / Dn
    nseg = int(round(L / dx))
    t = tgrid(dt)
    I = inflow(t, amp)
    q = np.full(nseg + 1, Q0)  # q[0] = inflow node
    out = np.empty(t.size)
    out[0] = Q0
    for n in range(1, t.size):
        qn = np.empty_like(q)
        qn[0] = I[n]
        for j in range(1, nseg + 1):
            qn[j] = C1 * q[j - 1] + C2 * qn[j - 1] + C3 * q[j]
        q = qn
        out[n] = q[-1]
    return out


def x_cunge(dcell: float) -> float:
    return 0.5 * (1.0 - dcell)


def x_kernel(dcell: float) -> float:
    return 0.5 * (1.0 - dcell / 2.0)


# ---- 3. the Fortran harness -----------------------------------------------------------
def fortran(variant: str, amp: float, dx: float, dt: float, tag: str) -> np.ndarray:
    nseg = int(round(L / dx))
    work = BUILD / "runs"
    work.mkdir(parents=True, exist_ok=True)
    t = tgrid(dt)
    inf = work / f"inflow_{tag}.txt"
    np.savetxt(inf, inflow(t, amp), fmt="%.8e")
    cfg = work / f"cfg_{tag}.txt"
    cfg.write_text(f"{nseg} {dx} {dt} {S0} {MANN} {CS} {BW} {TW_BANKFULL} 0.0 0.0 400 1\n{nseg}\n")
    out = work / f"out_{variant}_{tag}.txt"
    subprocess.run([str(BUILD / "driver"), variant, str(cfg), str(inf), str(out)], check=True)
    d = np.loadtxt(out)
    return np.concatenate(([Q0], d[:, 2]))


# ---- metrics --------------------------------------------------------------------------
def moments(t: np.ndarray, q: np.ndarray) -> tuple[float, float, float]:
    e = q - Q0
    m0 = np.trapezoid(e, t)
    m1 = np.trapezoid(e * t, t) / m0
    var = np.trapezoid(e * (t - m1) ** 2, t) / m0
    return m0, m1, var


def peak(t: np.ndarray, q: np.ndarray) -> tuple[float, float]:
    i = int(np.argmax(q))
    if 0 < i < q.size - 1:  # parabolic refinement
        y0, y1, y2 = q[i - 1], q[i], q[i + 1]
        den = y0 - 2 * y1 + y2
        off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
        return float(y1 - 0.25 * (y0 - y2) * off), float(t[i] + off * (t[1] - t[0]))
    return float(q[i]), float(t[i])


def dt_for_courant(dx: float, c0: float, cr: float) -> float:
    return max(60.0, round(cr * dx / c0 / 60.0) * 60.0)


def small_pulse_case(dx, dt, c0, B0, Dphys, ref_fn, rows) -> dict:
    t = tgrid(dt)
    ref = ref_fn(t)
    pk_ref, tp_ref = peak(t, ref)
    _, _, var_in = moments(t, inflow(t, SMALL))
    m0_in = moments(t, inflow(t, SMALL))[0]
    dcell = Q0 / (B0 * S0 * c0 * dx)
    tag = f"dx{int(dx)}_dt{int(dt)}"
    case = {"dx_m": dx, "dt_s": dt, "nseg": int(round(L / dx)), "courant": c0 * dt / dx,
            "D_cell": dcell, "X_cunge_raw": x_cunge(dcell), "X_kernel_raw": x_kernel(dcell),
            "X_cunge_final": min(0.5, max(0.25, x_cunge(dcell))),
            "X_kernel_final": min(0.5, max(0.25, x_kernel(dcell))),
            "exact_peak_excess": pk_ref - Q0, "exact_t_peak_h": tp_ref / 3600}
    series = {
        # linear MC with X exactly as each formula gives it (no floor): isolates the factor 2
        "linear_mc_cunge": linear_mc(SMALL, dx, x_cunge(dcell), c0, dt) if x_cunge(dcell) >= 0 else None,
        "linear_mc_kernel": linear_mc(SMALL, dx, x_kernel(dcell), c0, dt) if x_kernel(dcell) >= 0 else None,
        # the verbatim WRF-Hydro routine (includes its 0.25 floor, secant, etc.)
        "wrfhydro_orig": fortran("orig", SMALL, dx, dt, tag + "_small"),
        "wrfhydro_patched": fortran("patched", SMALL, dx, dt, tag + "_small"),
    }
    for name, q in series.items():
        if q is None:
            case[name] = None
            continue
        m0, _, var = moments(t, q)
        pk, tp = peak(t, q)
        case[name] = {
            "peak_excess_over_exact": (pk - Q0) / (pk_ref - Q0),
            "t_peak_minus_exact_h": (tp - tp_ref) / 3600,
            "D_eff_over_D_phys": (var - var_in) * c0 ** 3 / (2.0 * L) / Dphys,
            "volume_ratio": m0 / m0_in,
            "rmse_vs_exact_over_amp": float(np.sqrt(np.mean((q - ref) ** 2)) / SMALL),
        }
        if dt == DT:
            rows[f"{name}_{tag}"] = q
    return case


def large_pulse_case(dx, dt, c0, rows) -> dict:
    t = tgrid(dt)
    zi = zero_inertia(t, LARGE)
    zp, ztp = peak(t, zi)
    m0_in = moments(t, inflow(t, LARGE))[0]
    tag = f"dx{int(dx)}_dt{int(dt)}"
    case = {"dx_m": dx, "dt_s": dt, "courant_at_base": c0 * dt / dx,
            "zero_inertia_peak": zp, "zero_inertia_t_peak_h": ztp / 3600}
    for variant in ("orig", "patched"):
        q = fortran(variant, LARGE, dx, dt, tag + "_large")
        pk, tp = peak(t, q)
        case[f"wrfhydro_{variant}"] = {
            "peak": pk, "peak_error_rel_to_ref_excess": (pk - zp) / (zp - Q0),
            "t_peak_minus_ref_h": (tp - ztp) / 3600,
            "min_flow": float(q.min()),
            "volume_ratio": moments(t, q)[0] / m0_in,
            "rmse_vs_ref_over_amp": float(np.sqrt(np.mean((q - zi) ** 2)) / LARGE),
        }
        if dt == DT:
            rows[f"wrfhydro_{variant}_{tag}"] = q
    if dt == DT:
        rows["zero_inertia_large"] = zi
    return case


def main() -> None:
    RES.mkdir(exist_ok=True)
    h0 = normal_depth(Q0)
    _, _, B0, c0, _, _ = geom(h0)
    Dphys = Q0 / (2.0 * B0 * S0)
    summary: dict = {
        "channel": {"Q0": Q0, "Bw": BW, "ChSlp": CS, "z": Z, "n": MANN, "S0": S0, "L_m": L,
                    "h0_m": h0, "B0_m": B0, "c0_mps": c0, "D_phys_m2ps": Dphys,
                    "pulse_t0_h": PULSE_T0 / 3600, "pulse_sigma_h": PULSE_SIG / 3600,
                    "small_amp": SMALL, "large_amp": LARGE, "T_end_h": T_END / 3600},
        "analytic": {"travel_time_h": L / c0 / 3600,
                     "variance_increment_h2": 2.0 * Dphys * L / c0 ** 3 / 3600 ** 2},
    }
    t = tgrid(DT)
    ref300 = hayami(t, SMALL, c0, Dphys, L)
    zi300 = zero_inertia(t, SMALL)
    ph, _ = peak(t, ref300)
    pz, _ = peak(t, zi300)
    summary["reference_check"] = {
        "what": "small pulse: analytical convection-diffusion (Hayami) vs fine-grid zero-inertia",
        "hayami_peak_excess": ph - Q0, "zero_inertia_peak_excess": pz - Q0,
        "rel_diff_peak_excess": (pz - ph) / (ph - Q0),
        "max_abs_diff_over_amp": float(np.max(np.abs(zi300 - ref300)) / SMALL),
    }
    rows_small = {"t_h": t / 3600, "inflow_small": inflow(t, SMALL), "exact": ref300,
                  "zero_inertia_small": zi300}
    rows_large = {"t_h": t / 3600, "inflow_large": inflow(t, LARGE)}

    small = []
    for dx in DXS:
        for dt in sorted({DT, dt_for_courant(dx, c0, 1.0)}):
            small.append(small_pulse_case(dx, dt, c0, B0, Dphys,
                                          lambda tt: hayami(tt, SMALL, c0, Dphys, L), rows_small))
    summary["small_pulse"] = small
    large = []
    for dx in (2000.0, 4000.0, 8000.0):
        for dt in sorted({DT, dt_for_courant(dx, c0, 0.5), dt_for_courant(dx, c0, 1.0)}):
            large.append(large_pulse_case(dx, dt, c0, rows_large))
    summary["large_pulse"] = large

    for fname, rows in (("hydrographs_small_dt300.csv", rows_small),
                        ("hydrographs_large_dt300.csv", rows_large)):
        keys = list(rows)
        arr = np.column_stack([rows[k] for k in keys])
        np.savetxt(RES / fname, arr, delimiter=",", header=",".join(keys), comments="", fmt="%.6f")
    (RES / "summary.json").write_text(json.dumps(summary, indent=2))
    make_figures(summary, rows_small, rows_large)
    print_table(summary)


def print_table(summary) -> None:
    print("SMALL PULSE (linear regime): effective/physical diffusivity, peak excess / exact")
    print(f"{'dx':>6} {'dt':>6} {'C':>5} {'Dcell':>6} {'Xc':>5} {'Xk':>5} | "
          f"{'linC':>6} {'linK':>6} | {'orig':>6} {'patch':>6} | {'pk_orig':>7} {'pk_pat':>7}")
    for c in summary["small_pulse"]:
        g = lambda k, f: (f"{c[k][f]:6.3f}" if c[k] else "   n/a")
        print(f"{c['dx_m']:6.0f} {c['dt_s']:6.0f} {c['courant']:5.2f} {c['D_cell']:6.2f} "
              f"{c['X_cunge_final']:5.3f} {c['X_kernel_final']:5.3f} | "
              f"{g('linear_mc_cunge','D_eff_over_D_phys')} {g('linear_mc_kernel','D_eff_over_D_phys')} | "
              f"{g('wrfhydro_orig','D_eff_over_D_phys')} {g('wrfhydro_patched','D_eff_over_D_phys')} | "
              f"{c['wrfhydro_orig']['peak_excess_over_exact']:7.3f} {c['wrfhydro_patched']['peak_excess_over_exact']:7.3f}")
    print("LARGE PULSE (50 -> 200 m3/s) vs zero-inertia reference")
    for c in summary["large_pulse"]:
        o, p = c["wrfhydro_orig"], c["wrfhydro_patched"]
        print(f"dx={c['dx_m']:5.0f} dt={c['dt_s']:5.0f} C0={c['courant_at_base']:.2f} | "
              f"rmse {o['rmse_vs_ref_over_amp']:.3f}->{p['rmse_vs_ref_over_amp']:.3f} | "
              f"peak err {o['peak_error_rel_to_ref_excess']:+.3f}->{p['peak_error_rel_to_ref_excess']:+.3f} | "
              f"tpk {o['t_peak_minus_ref_h']:+.2f}->{p['t_peak_minus_ref_h']:+.2f} h | "
              f"vol {o['volume_ratio']:.3f}->{p['volume_ratio']:.3f} | min {o['min_flow']:.1f}->{p['min_flow']:.1f}")


def make_figures(summary, rows_small, rows_large) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker

    th = rows_small["t_h"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)
    ax = axes[0]
    tag = f"dx4000_dt{int(DT)}"
    dc4 = next(c["D_cell"] for c in summary["small_pulse"] if c["dx_m"] == 4000)
    ax.plot(th, rows_small["inflow_small"] - Q0, color="0.6", lw=1, label="inflow")
    ax.plot(th, rows_small["exact"] - Q0, color="black", lw=2.2,
            label="convection-diffusion, D = Q/(2BS0) (exact)")
    ax.plot(th, rows_small[f"wrfhydro_orig_{tag}"] - Q0, color="#eb6834", lw=1.6,
            label="WRF-Hydro SUBMUSKINGCUNGE, current")
    ax.plot(th, rows_small[f"wrfhydro_patched_{tag}"] - Q0, color="#2a78d6", lw=1.6, ls="--",
            label="same routine, patched (Cunge X)")
    ax.set_xlim(0, 30)
    ax.set_xlabel("time (h)")
    ax.set_ylabel("flow above base (m³/s)")
    ax.set_title(f"Small pulse, 64 km, dx = 4 km, dt = {int(DT)} s (D_cell = {dc4:.2f})")
    ax.legend(frameon=False, fontsize=8)
    ax = axes[1]
    for dtsel, mk in ((DT, "o"), (None, "s")):
        cs = [c for c in summary["small_pulse"] if (c["dt_s"] == DT) == (dtsel == DT)]
        dc = [c["D_cell"] for c in cs]
        lab = f"dt = {int(DT)} s" if dtsel == DT else "C = 1"
        ax.plot(dc, [c["wrfhydro_orig"]["D_eff_over_D_phys"] for c in cs], mk + "-", color="#eb6834",
                label=f"current kernel, {lab}", alpha=0.9 if dtsel == DT else 0.5)
        ax.plot(dc, [c["wrfhydro_patched"]["D_eff_over_D_phys"] for c in cs], mk + "--", color="#2a78d6",
                label=f"patched kernel, {lab}", alpha=0.9 if dtsel == DT else 0.5)
    ax.axhline(1.0, color="black", lw=1)
    ax.axhline(0.5, color="0.5", lw=0.8, ls=":")
    ax.axvline(0.5, color="0.7", lw=0.8, ls="--")
    ax.axvline(1.0, color="0.7", lw=0.8, ls="--")
    ax.text(0.52, 0.05, "patched X\non 0.25 floor", fontsize=7, color="0.35",
            transform=ax.get_xaxis_transform())
    ax.text(1.04, 0.05, "both X on\n0.25 floor", fontsize=7, color="0.35",
            transform=ax.get_xaxis_transform())
    ax.set_xscale("log")
    ax.set_xticks([0.15, 0.3, 0.6, 1.2, 2.4])
    ax.xaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter("%g"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.grid(axis="y", color="0.9", lw=0.6)
    ax.set_xlabel("cell Reynolds number D_cell = Q/(B S0 c dx)")
    ax.set_ylabel("effective / physical diffusivity")
    ax.set_title("Diffusion delivered (hydrograph variance)")
    ax.legend(frameon=False, fontsize=7)
    fig.savefig(RES / "fig_small_pulse.png", dpi=150)
    plt.close(fig)

    if "zero_inertia_large" in rows_large:
        fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)
        th = rows_large["t_h"]
        ax.plot(th, rows_large["inflow_large"], color="0.6", lw=1, label="inflow")
        ax.plot(th, rows_large["zero_inertia_large"], color="black", lw=2.2, label="zero-inertia, 100 m grid")
        ax.plot(th, rows_large[f"wrfhydro_orig_{tag}"], color="#eb6834", lw=1.6, label="current kernel")
        ax.plot(th, rows_large[f"wrfhydro_patched_{tag}"], color="#2a78d6", lw=1.6, ls="--",
                label="patched kernel")
        ax.set_xlim(0, 30)
        ax.set_xlabel("time (h)")
        ax.set_ylabel("flow (m³/s)")
        ax.set_title(f"Large pulse (50→200 m³/s), 64 km, dx = 4 km, dt = {int(DT)} s")
        ax.legend(frameon=False, fontsize=8)
        fig.savefig(RES / "fig_large_pulse.png", dpi=150)
        plt.close(fig)


if __name__ == "__main__":
    main()
