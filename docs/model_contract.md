# Model contract

All quantities refer to one consistent unit system chosen by the user. Time is normalized in the supplied examples. `growth` s is consumers per unit time; `growth_end` H and `horizon` T satisfy 0 <= H <= T, T > 0. The deployment delay tau satisfies 0 <= tau <= H. `network` phi is inverse consumers. Announcement intensity delta is additional consumers per unit time in the share weights, so phi * delta * tau is dimensionless. `quality_ratio` w is q_y / q_x > 0. Margins multiply consumer-stock time; this model uses a consumer-stock revenue flow, not sales counts.

## Share equations

The operational share equations retain the supplied manuscript's four scenario equations. The quality ratio extends its w=1 simplification.

| Scenario | Object weight a | Rival weight b |
|---|---|---|
| RF | 1 + phi (s + delta) tau | w |
| RL | 1 + phi delta tau | w (1 + phi s tau) |
| DF | 1 + phi s tau | w |
| DL | 1 | w (1 + phi s tau) |

Shares are z_x=a/(a+b), z_y=b/(a+b). Announcement does not create additional total consumers in these demand equations; it redistributes post-entry growth. The source's prose about initial consumer scales is not sufficient to derive all four shares unambiguously, so the explicit scenario equations define this release's contract. Rival announcement is not an independent decision variable in this release.

## Demand and revenues

The first entrant has s*t consumers before tau. Between tau and H its stock is s*tau + s*(t-tau)*z_leader. The follower has zero before tau and s*(t-tau)*z_follower after tau. Both retain their H stocks during maturity. At tau=0 entry is simultaneous; at tau=H the follower attracts no consumers. Total stock is s*min(t,H) in every scenario. There is no churn, migration, strategic pricing or heterogeneous consumer utility.

Revenue j is margin_j times the integral from 0 to T of exp(-discount*t)*D_j(t). Operational integration splits at tau and H and uses exact linear-exponential moments, with a cancellation-resistant series for small discount*segment-length. Independent quadrature is implemented in the benchmark module, without calling the operational demand or revenue kernel.

Object platform net payoff is revenue_x minus announcement_cost*delta^2/2 minus deployment_cost*exp(-(learning_rate+discount)*entry_time_x). Entry time is 0 for RF/DF and tau for RL/DL. Announcement cost is a present value at time 0; deployment cost is paid at entry and discounted. The rival's revenues are returned, but its cost-adjusted objective is not solved. Costs and discounting are model extensions, not source assumptions.

`source_baseline.json` restores source demand assumptions and adds an explicit intensity upper bound of 2 for a well-posed operational example. `unbounded_announcement.json` instead keeps no cap and no announcement cost and demonstrates the diagnostic. `product_launch.json` adds synthetic cost assumptions. No supplied setting is an empirical calibration.

## Control and optimization

RF optimizes only delta with supplied rival_delay held fixed. DF has no object decision. RL optimizes tau and delta. DL optimizes tau. These controls are conditional on who enters first. Bounds on delay apply to the follower's controllable delay, not the supplied rival delay, which must independently satisfy 0 <= rival_delay <= H.

Announcement revenue is a positive constant times a linear-fractional share, a concave increasing function of delta at positive effective delay. A nonnegative quadratic cost preserves concavity. The derivative is bracketed to obtain the optimal intensity; if the objective is monotone on a finite bound, the relevant endpoint is used. With zero effect and zero cost, intensity is nonunique. With effective benefit, no cap and no cost, no finite optimum exists at a fixed positive lag; optimization reports this condition and withholds all-scenario ranking.

For RL with zero announcement cost and no cap, a missing fixed-delay intensity maximizer is not sufficient to classify the joint problem. The solver compares the supremum envelope and checks attainment at H, or an actual singleton zero-lag domain. It returns an attained finite representative or a joint supremum with null maximizing controls. The zero-delay envelope is a right limit, not the actual simultaneous-entry payoff. Its derivative structure permits at most two stationary candidates; see `joint_envelope.md`.

Other follower profiles use a scouting mesh, normalized local refinement of both edge intervals and detected mesh maxima, and retained endpoints. `globally_certified` and `equilibrium` remain false. Positive-cost profiling solves a log marginal balance with checked convergence. Floating-point limits remain; controlled errors ask for rescaling instead of returning an unconverged root.

## Unit conversion

For t'=a*t and D'=b*D with payoff units fixed, transform s'=b*s/a, phi'=phi/b, H'=a*H, T'=a*T, tau'=a*tau, delta'=b*delta/a, m_j'=m_j/(a*b), r'=r/a, kappa'=kappa/a and c_A'=c_A*(a/b)^2. Quality ratio and deployment cost stay fixed. Transform feasible caps and delay bounds too. `rescale_experiment` applies these changes and scales the absolute delay-search tolerance by a; log-intensity tolerance is dimensionless. Changing only horizon or quality is an economic sensitivity experiment, not a unit change.

## Interpretation

`co_best` uses an absolute net-payoff tolerance of 1e-8. Scaling margins, growth and costs may require a different tolerance through the shared comparison configuration. A default zero non-entry reference is exposed separately. It is a payoff reference and does not simulate the rival's response to non-entry. Users can supply another finite outside_option to `compare`.

The model has not been fitted to or validated against observed platform outcomes. Uniform uncertainty ranges are assumptions supplied by the user. Frequencies summarize these assumptions and the conditional control structure. They are not probabilities that real firms will choose a strategy. Mixed strategies and endogenous order, learning from observations, non-entry games and network dynamics require additional model definitions.


## Numerical representation and verification

Deployment cost uses exp(log(c_D)-kappa*t_x-r*t_x), with explicit zero-cost/zero-time handling. It avoids overflowing kappa+r before a small time multiplication or prematurely underflowing a discount factor. This does not guarantee that all mathematical moments at every finite scale are representable. Unit conversion uses binary exponent arithmetic and rejects a positive converted term rounded to zero.

Selected-boundary labels use exact feasible endpoints, independent of measurement units; singleton delay domains are fixed. The nearby-delay perturbation is proportional to interval width. Source-bound manifests validate content correspondence, not actual execution or global correctness.

## Integration scale and delay search

The linear-exponential moments and revenue weights remain in logarithmic scale until the final revenue is formed. This avoids intermediate time-square underflow or overflow when the weighted revenue is representable. Final values still round to binary floating point, and unrepresentable outputs raise controlled errors. The scalar response_mass helper can itself underflow or overflow because it returns an unweighted moment; the operational revenue and gradient kernels do not require that scalar intermediate.

Each bounded delay-refinement interval maps to [0,1]; its absolute time tolerance is divided by interval width, with a floating-point floor. Both edge cells are refined even when their mesh endpoints appear monotone. Undetected multiple peaks inside another cell are not ruled out, so globally_certified remains false. delay_refinement_intervals records how many intervals were searched. Endpoint and local residual information remains diagnostic rather than a global proof.

## Constraint-aware stationarity diagnostics

Fixed-zero intensity has no feasible direction and zero KKT violation, regardless of the unrestricted derivative range. Free controls compare log marginal benefit and cost before forming the sign-adjusted violation. The raw field retains payoff/intensity units; log and scale-free fields preserve diagnostic information when the raw violation underflows or is unrepresentable. A null raw field is explicitly labeled outside_float_range, never interpreted as zero. The original raw-gradient API still rejects an unrepresentable derivative.

Object payoff requires only the object's revenue to be representable. The public two-revenue call requires both revenues to fit. This difference concerns requested outputs and does not change the demand or objective equations. Binary64 delay scouting removes duplicate nodes; intervals without a representable interior are evaluated at their endpoints. These numerical candidates remain subject to the stated local-search limits.

## Configured experiment domains and reporting policy

The mathematical domain permits delay in [0,H] and nonnegative announcing intensity; silent scenarios require intensity zero. A configured experiment can impose a narrower follower interval, announcement cap and fixed rival lag. CLI evaluation now enforces these controls unless an explicit diagnostic flag is supplied. Diagnostic values are labeled and cannot relax the mathematical domain.

Comparison uses an explicit absolute payoff tolerance and finite outside-option reference. Defaults remain 1e-8 and zero; tiny payoffs can all be co-best under this default. Scale changes require a deliberate policy choice. Failed batch configurations or computations have no payoffs or preferences and remain in requested-draw accounting; conditional frequencies disclose their completed-draw denominator. Valid unattained-supremum models are unrankable rather than failed.

## v0.8.0 quality and sampling contract

Neighborhood evaluations can improve a selected candidate. The returned control is updated before shares, activity and stationarity are reported. Up to four probe rounds disclose improvement and a local quality threshold; a failed local diagnostic remains a numerical candidate with a warning, not an attained global certificate. Mesh/tolerance stability and ranking gaps are additional observations.

Sampling now specifies an indexed, canonical-name PCG64 algorithm and bounded marginal transformations. Correlation describes Gaussian copula latent normals. Explicit feasible conditional sampling discloses rejections; independent input distributions cannot be claimed for the accepted constrained draws. Monte Carlo intervals measure finite draw count error only. The underlying demand, revenue and cost equations are unchanged.

Research adapters describe model capabilities and require dedicated callbacks/solvers for extensions. They do not transfer the current concavity or envelope derivation to churn, migration, pricing or other mechanisms. Such extensions need their own numerical and scientific evidence.


## v0.18.0 net payoff and source bound repairs

A09 guards final revenue/cost cancellation without changing the model equations. Near-cancelling net values are recomputed from original binary64 inputs, with exact rational arithmetic for the rational branch and adaptive 80/160/320/640/1280-digit Decimal arithmetic otherwise. Two successive rounded results must agree under the documented cancellation/rounding guard; unresolved values raise a controlled error. Scalar, grid, uncapped RL supremum values and default research metadata use this policy. It is numerical guarding, not interval certification. Requested gross components must still fit. Individually rounded revenue outputs need not reconstruct a guarded net by ordinary subtraction.

A10 decides RL_REVENUE_BOUND from P-B=s*(1/k**2+2/k)/8>0, k=s*network, within the original source assumptions. Printed candidates are calculated before final rounding; an intermediate infinity cannot silently become zero. New representation fields label genuine final underflow. Existing six source checks and module isolation are retained.

See docs/v0180_acceptance.md and examples/net_cancellation_positive.json, net_cancellation_negative.json, discounted_cancellation.json and source_bound_extreme.json. All earlier repairs and indexed-pcg64-v2 are retained; old source/version checkpoints require fresh runs. Author details and the public source repository are now recorded in CITATION.cff. Versioned archival links and official journal-template verification remain pending.


## Version 0.19.0 original-input comparison policy

The default model compares objectives at returned controls. Close scenario/outside gaps and gaps near the absolute tie boundary use original binary64 inputs when min(abs(a-b),abs(abs(a-b)-tie_tolerance))/max(abs(a),abs(b),tie_tolerance) <= 1e-8; zero scale and subnormal payoff operands also trigger. This heuristic guard is not an interval error bound. Exact common primitive/cost coefficients are cancelled. Pure rational differences retain exact order and tolerance membership. Other gaps use 80/160/320/640/1280 Decimal digits, requiring two stable rounded values, signs and tolerance sides, with a gross-scale cancellation guard. Unresolved order raises NumericalError. The built-in cached batch optimizer shares this model-owned policy.

`entry_payoff_gap` and `outside_option_gap` may differ from subtracting displayed `results[*].payoff`: the latter remain independent binary64 objective evaluations. Diagnostics include decision_basis, sign, tolerance_relation (-1/below -tol, 0/inclusive band, +1/above tol), precision_digits and representation. A true rounded-zero gap has underflow and its original-input nonzero sign; an out-of-range magnitude has null value and a log magnitude. The decision uses the guarded relation. CSV adds gap basis and outside gap representation/sign. Unattained/null results still withhold complete ranking.

`compare_results` and explicit arbitrary optimizer callbacks retain supplied-float semantics; their original objective cannot be inferred from ModelParams. Research extensions retain their own objective policies. Local quality and mesh agreement do not prove comparison accuracy or global optimality. The guard changes evaluated-candidate comparisons, not the search certificate.

A two-control singleton payoff visualization uses a point at the actual control/payoff, with fixed controls stated. A sensitivity series with one finite value uses a strategy-specific marker, preserving null gaps. Other slices and curves remain lines; no extra feasible points are invented. See docs/v0190_acceptance.md.


## Version 0.20.0 extreme decay and finite run figures

A13 separates output-range conversion from original-input sign comparison. If extreme decay could reach the segment evaluator's exp(-100000) cut, exact rational integral coefficients are expanded into exponential terms, identical terms cancel, and the least exponent is factored out before Decimal evaluation. A discarded relative tail contributes the bound sum(abs(coefficient))*exp(-100000), rather than zero, to the scaled cancellation guard. The ordinary small-discount segment/series path remains. Two precision levels must agree on rounded value, sign, tolerance relation and log magnitude for the scaled path. This is adaptive guarding with a tail bound, not interval arithmetic or a universal rounding certificate.

The v2 comparison policy retains the 1e-8 trigger and external supplied-float semantics. scaled_original_input_difference identifies the new basis. Final underflow can have value zero with negative or positive original sign. Finite positive absolute tie tolerances still define their own inclusive band; zero tolerance is supported. If the required log magnitude itself is outside binary64 range, the comparison explicitly refuses with NumericalError. The former discount=1e308, delay=1 case now resolves; the inherited v0.19.0 refusal fixture was moved to discount=1e308, delay=H=T=1e308 to test the explicit log-output range boundary. The original fixture remains as a new successful regression, and original v0.19.0 files are frozen under audit/v0.19.0.

A14 marks every contiguous finite run that has only one unique coordinate. Repeated vertices remain in the line and CSV; the actual coordinate gets one marker. Missing values keep their breaks. Runs with a nonzero line segment retain ordinary lines; all-null and empty input creates no data. Strategy markers remain distinct. This completes the A12 single-observation coverage for repeated and disconnected observations, without changing controls or filling missing data. See docs/v0200_acceptance.md.


## Version 0.21.0 follower candidate ordering

A15 makes bounded follower search use the original-input gap policy for near control comparisons, rounded equality and subnormal payoffs. Search order uses zero tolerance independently of scenario co-best tolerance. Grid peaks and candidate promotion share this order. Rounded-order disagreements trigger normalized comparison-driven golden refinement; ordinary intervals retain bounded scalar refinement unless a collision appears. A final scan compares the returned candidate with every evaluated node, using the same adaptive heuristic guard. It does not examine every continuous control and is not a global/error certificate. Every profile evaluation remains budgeted.

search_precision records policy original_input_profile_order_v1, guard/collision counts, maximum Decimal precision, method counts and final evaluated-node checks. delay_refinement_diagnostics records methods and termination. last_probe_improvement_diagnostic retains original sign and quality-threshold relation when the float improvement underflows. Existing floating improvement amounts remain output values, not independent accuracy bounds. An unresolved order raises NumericalError. True exact equality is permitted; all zero float outputs alone do not establish a flat objective. Model formulas, index/name keyed sampling and external supplied-result semantics are unchanged.

## Version 0.22.0 cross-mesh payoff differences

Cross-mesh stability compares original objectives at the returned model controls, with the shared adaptive gap policy. It does not infer equality from identical rounded payoff fields. The observed amount is accompanied by its sign, representation and tolerance relation; a positive underflow spread fails a zero quality threshold and can pass a positive band. The threshold retains payoff_atol + payoff_rtol * max(abs(displayed_payoffs)). Null candidates withhold complete stability; unresolved order and unrepresentable thresholds raise controlled numerical errors. Individual local-quality checks and cross-mesh agreement are independent observations, with no global or interval certificate. Economic formulas, scenario comparison and sampling are unchanged.


## Version 0.23.0 announcement precision and assessment

Near marginal benefit/cost differences use original inputs; exact rational and adaptive Decimal diagnostics retain sign, log and scale meaning. Structural zero effect is separate from an unrepresentable exponent. A free finite cap is selected analytically for a strictly increasing profile; unrepresentable positive-cost roots refuse. KKT units are payoff/intensity, distinct from payoff tolerance units. The nullable legacy residual and its assessment describe only a measured final-control probe neighborhood or an analytic flat profile; increments at a previously returned control are separate. The HTML report shows existing quality and mesh warnings without changing exit-zero completion semantics. See docs/v0230_acceptance.md.


## Version 0.24.0 cancellation and root endpoints

A20 screens both rounded net differences and the original positive revenue/cost component scale. Gross cancellation cannot bypass the shared model-owned ordering guard merely because its rounded net gap appears well separated. Close or risky comparisons use the existing exact rational or adaptive Decimal original-input gap evaluator; unresolved ordering refuses. The same policy applies to evaluated delay nodes, default scenario comparison, outside options and mesh spreads. Custom optimizer values are not reinterpreted. Displayed scalar payoffs remain approximate; guarded gap diagnostics can disagree with their subtraction. No interval or continuous global optimum is claimed.

The frozen audit corpus supplies 896 cancellation comparisons (448 parameter sets under zero and default tolerance), 168 noncancellation controls, 45 evaluated-node configurations and 80 representable-root cases. Independent rational references are recomputed at returned controls. Evaluated nodes use independent 200/400-digit event integrals. The returned node must equal the best among nodes actually evaluated, without interpreting local_quality_passed as a global error bound. Default and strict mismatch counts must both be zero. The named RF/DF case must select RF with gap 24.691358024690995; serial/process batch and HTML/mesh paths use the corrected ranking.

A19 checks the original-input marginal sign at the actual minimum positive float, actual finite cap and actual maximum float before a range refusal. Exact endpoint equality is admissible. Ordinary log-intensity refinement is retained when it has a strict bracket. If log/exp round-trip loses that bracket, bisection over ordered positive binary64 encodings reaches an exact root or adjacent controls, choosing the smaller scaled feasible derivative violation. This avoids an overflowing span and unit-dependent interpolation. All 80 known representable roots must produce finite positive controls. The six earlier genuine unrepresentable cases still refuse; ordinary roots, free caps and fixed zero caps retain their semantics.

R01 binds the complete current wheel SHA256 into the publication input graph. Metadata Name, Version, Requires-Python and Requires-Dist must match pyproject.toml, and the current interpreter must be supported. WHEEL tags and purelib, declared console scripts and all RECORD hashes/inventory are checked. Ten regenerated-record metadata mutations must refuse, including missing command entry and Requires-Python >=99. Full release probes repeat both original audit variants against sealed publication inputs. A fresh isolated environment receives copies of locked dependency distributions, pip installs only the current wheel with --no-deps --no-index, and declared console commands execute from an unrelated directory with inherited Python path overrides removed. This is an offline install smoke, not an independent dependency-resolution or cross-platform execution claim. Python 3.10 release tooling uses the conditional tomli entry in requirements-lock.txt.

The complete release preserves all frozen v0.23.0 audit source, original wheel, report and evidence bytes; fixtures are independently identified under tests/data. Standalone software tests and validators do not require audit history. Word and LaTeX share current measured evidence. Author details and the public source repository are now recorded in CITATION.cff. Versioned archival metadata, source bibliography and official SoftwareX template confirmation remain pending. Local Linux execution does not assert remote CI execution.


## Version 0.25.0 recorded local probes

`solver.profile_announcement` canonicalizes all accepted Real control fields before structural tests. Its module-level return remains `(intensity, nonunique)`; it is not added to the top-level exports. Fractions that round to maturity use the stored binary64 control consistently.

Default `optimize` results add `local_probe_diagnostics`; existing fields keep their meanings. The policy is `recorded_local_probes_v1`. `rounds` has at most four records, each with `round`, `starting_control`, two `probes`, `selected_control`, `quality_threshold`, `improvement_diagnostic`, `passed`, `control_promoted`, `distinct_neighbors_in_feasible_directions`, `selected_control_neighborhood_assessed` and `termination`. Each probe has `side`, `control`, `distinct_from_start` and `already_evaluated`. A control contains strategy, delay, announcement and displayed payoff. No additional model evaluation is performed for logging.

`status` is assessed, not_assessed, analytic_flat or not_applicable. `reason` distinguishes unchanged feasible neighbors, promoted controls, coincident probes, fixed delay, flat delay, first-entrant timing, attained envelope and unattained results. `final_control_neighborhood_assessed` reports only an actual unchanged final neighborhood. A passed last increment after promotion does not assess that newly selected neighborhood. Fixed-delay results retain and record their existing coincident round; first-entrant, analytic-flat and joint-envelope branches have empty rounds. Thresholds retain the displayed-payoff scale convention.

JSON/checkpoints and Python rows retain dictionaries. In CSV, only the added `local_probe_diagnostics` field is serialized as strict JSON, parsed with `json.loads`; absent fields in failed or custom rows are empty. Existing nested CSV cells are not silently reformatted. New versions require new source-bound checkpoints.

HTML shows recorded rounds and warns on observed differences between displayed subtraction and guarded comparison sign/tie-band membership. The warning includes gap sign and decision basis; it never changes optimization or supplied custom-float semantics. See docs/v0250_acceptance.md for independent references, measured wide-type capabilities and exact scope.
