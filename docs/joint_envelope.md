# Joint attainment with unbounded cost-free announcement

This branch applies to RL when c_A=0, the announcement cap is absent and m_x, s, phi are positive. For fixed 0<tau<H the share approaches one but never equals one at a finite intensity. Define M_r(tau) as the integral of (t-tau) exp(-r*t) from tau to H plus (H-tau) times the integral of exp(-r*t) from H to T. The upper envelope is U(tau)=m_x*s*M_r(tau)-c_D*exp(-(kappa+r)*tau).

At H, M_r(H)=0 and U(H) is attained for every finite intensity. At zero intensity has no effect: the actual share is 1/(1+w), so U(0) is only a right limit if positive delays are available. A singleton {0} has its actual finite payoff. Positive singleton delays below H lack a finite intensity maximizer.

Write A=m_x*s, K=kappa+r and J(tau)=integral[tau,T] exp(-r*t) dt. Then U'=-A*J+K*c_D*exp(-K*tau). For K*c_D>0, factor exp(-r*tau) and compare log(K*c_D)-kappa*tau with log(A)+log(j0(T-tau,r)). The log ratio has derivative -kappa+r/(exp(r*(T-tau))-1), or -kappa+1/(T-tau) at r=0. This derivative increases, so there is at most one minimum and at most two zero crossings. The minimum is T-log(1+r/kappa)/r for r,kappa>0, or T-1/kappa for r=0. With kappa=0 the ratio is monotone. Zero deployment cost or K=0 gives a decreasing envelope.

The solver splits the admissible interval at the minimum, brackets all derivative roots, checks convergence and compares roots and endpoints. If admissible U(H) is at least every candidate, it returns delta=0 at H. Otherwise it returns no_finite_joint_optimum, null maximizing controls/payoff, the supremum and its envelope lag. Co-best tolerance is not used to manufacture attainment. Root arithmetic is not an interval-arithmetic certificate; globally_certified stays false.

For A=.025,H=.3,T=1,c_D=.05,kappa=1,r=0, U'(tau) >= .05*exp(-.3)-.025 = .012040911034085895>0. The attained joint maximum is U(H)=-.0370409110340859, despite missing fixed-interior-lag intensity maxima. The regression test and joint_boundary.json exercise this audit counterexample.

Zero growth, margin or network bypass effective-benefit classification. Degeneracy flags recognize analytic constant objectives over domains with multiple values; they do not enumerate every possible numerical tie.


## Candidate ordering in v0.15.0

For a<b, compare U(a)-U(b) using the positive revenue difference and the positive deployment-cost decrease, rather than subtracting two rounded net values. The common exp(-r*a) cancels. The revenue difference after cancellation is m_x*s times the sum of the first exponential moment on [0,b-a] and (b-a)*exp(-r*(b-a)) times the zeroth moment on [0,T-b]. The cost decrease is c_D*exp(-kappa*a)*(1-exp(-(kappa+r)*(b-a))). Logarithmic scales retain these components. If c_D=0 or kappa=r=0, the sign is strictly positive, regardless of rounded net payoffs.

Close logarithmic component values trigger Decimal evaluation at 80, 160 and, if necessary, 320 digits, with series moments for small rate-length products. A stable separated sign is required; unresolved ordering raises a controlled NumericalError. This is a numerical guard, not interval arithmetic or a new global certificate. The maturity boundary is attained only when it wins this candidate comparison. The fixed-cost audit example margin_x=1e-20,c_D=1,kappa=r=0 remains unattained although all binary64 net values round to -1.


## Root brackets in v0.16.0

Raw absolute time tolerance is insufficient for classifying an uncapped envelope. At H=3e-13,T=1e-12 with the audit costs, xtol=1e-10 formerly returned a bracket endpoint as a root. A positive feasible RL payoff then exceeded the reported negative attained optimum. Root isolation now uses normalized brackets, a 1e-13 accuracy cap and an explicit floating-point floor, regardless of a looser requested time tolerance. Interior bracket endpoints are retained for guarded ordering. A bracket that cannot separate its root from the original boundary is refused, rather than silently deduplicated into a boundary maximum. Root diagnostics retain their numerical nature; globally_certified remains false. The acceptance file covers 55 independent envelope cases, including discounted maturity maxima, 500 decades of time scales, original counterexamples and controlled unresolved-boundary rejection.


## v0.18.0 final envelope value

The selected envelope payoff now uses the shared guarded net evaluator, including its exact rational and adaptive Decimal paths. Component ordering and normalized roots are unchanged. Default research metadata reevaluation uses the same policy; rounded revenue minus rounded deployment cost is not an independent reference for a near-zero envelope. See docs/v0180_acceptance.md for numerical limits.
