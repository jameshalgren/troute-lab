# /// script
# requires-python = ">=3.11"
# dependencies = ["sympy==1.14.0"]
# ///
"""Modified-equation analysis of the Muskingum box scheme (AI-written, Claude, 2026-10-09).

Scheme (Cunge 1969; the WRF-Hydro / T-Route kernel's C1..C3 with K = dx/c):
  [X(Q2-Q1) + (1-X)(Q4-Q3)]/dt + c[theta(Q4-Q2) + (1-theta)(Q3-Q1)]/dx = 0
  Q1=(j,n) Q2=(j,n+1) Q3=(j+1,n) Q4=(j+1,n+1); theta = 1/2 in Muskingum.
We Taylor-expand a smooth Q(x,t) about the cell centre, then eliminate time
derivatives with the leading-order equation Q_t = -c Q_x, and read off the
coefficient of Q_xx: the numerical diffusion the scheme adds.
"""
import sympy as sp

x, t, dx, dt, c, X, th = sp.symbols("x t dx dt c X theta", positive=True)
a = sp.symbols("a0:5")  # placeholders not used
# Represent Q by its Taylor coefficients about the cell centre (dx/2, dt/2)
N = 3
d = {}
for i in range(N + 1):
    for k in range(N + 1 - i):
        d[(i, k)] = sp.Symbol(f"Q_x{i}t{k}")  # d^{i+k}Q / dx^i dt^k at centre


def Q(px, pt):
    """Taylor value at offset (px, pt) from the centre."""
    return sum(d[(i, k)] * px**i * pt**k / (sp.factorial(i) * sp.factorial(k)) for (i, k) in d)


hx, ht = dx / 2, dt / 2
Q1, Q2, Q3, Q4 = Q(-hx, -ht), Q(-hx, ht), Q(hx, -ht), Q(hx, ht)
R = (X * (Q2 - Q1) + (1 - X) * (Q4 - Q3)) / dt + c * (th * (Q4 - Q2) + (1 - th) * (Q3 - Q1)) / dx
R = sp.expand(R)
# keep terms up to first order in dx, dt (second derivatives)
R2 = sum(R.coeff(d[k]) * d[k] for k in d if sum(k) <= 2)
R2 = sp.expand(R2)
# eliminate time derivatives using the leading-order equation Q_t = -c Q_x
# Q_tt = c^2 Q_xx, Q_xt = -c Q_xx  (valid to this order)
Qxx = d[(2, 0)]
R2 = R2.subs({d[(1, 1)]: -c * Qxx, d[(0, 2)]: c**2 * Qxx})
R2 = sp.expand(R2)
# The modified equation reads Q_t + c Q_x = nu_num * Q_xx  =>  nu_num = -coeff(Q_xx)
coef_t, coef_x = R2.coeff(d[(0, 1)]), R2.coeff(d[(1, 0)])
nu_num = sp.simplify(-R2.coeff(Qxx))
print("coefficient of Q_t :", sp.simplify(coef_t))
print("coefficient of Q_x :", sp.simplify(coef_x))
print("numerical diffusion nu_num(theta) =", sp.factor(nu_num))
nu_half = sp.simplify(nu_num.subs(th, sp.Rational(1, 2)))
print("numerical diffusion at theta=1/2  =", sp.factor(nu_half))
# Cunge matching: nu_num = physical diffusivity D = Q/(2 B S0)
Qs, B, S0 = sp.symbols("Q B S_0", positive=True)
Xsol = sp.solve(sp.Eq(nu_half, Qs / (2 * B * S0)), X)[0]
print("matching X =", sp.simplify(Xsol), " = 1/2*(1 - Q/(B*S0*c*dx)) ?",
      sp.simplify(Xsol - sp.Rational(1, 2) * (1 - Qs / (B * S0 * c * dx))) == 0)
# What the kernel's X implies
Xk = sp.Rational(1, 2) * (1 - Qs / (2 * B * S0 * c * dx))
print("kernel X -> nu_num =", sp.simplify(nu_half.subs(X, Xk)), " (physical D = Q/(2 B S0))")
assert sp.simplify(nu_half - c * dx * (sp.Rational(1, 2) - X)) == 0
assert sp.simplify(nu_half.subs(X, Xk) - Qs / (4 * B * S0)) == 0
print("OK: theta=1/2 numerical diffusion = c*dx*(1/2 - X); kernel X gives Q/(4 B S0) = D/2")
