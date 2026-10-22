# Reproduction and batch execution

## Indexed random draws

v0.11.0 uses `indexed-pcg64-v2`, with an explicit NumPy PCG64 bit generator. Independent parameter streams use SeedSequence entropy `[seed, sample_index, attempt_index, *SHA256_words]`. The words are the eight little-endian 32-bit words of SHA-256 of UTF-8 `parameter:NAME`. Parameter names are canonicalized. Each scenario receives the same parameter draw. Changing JSON object order, replaying a sorted archived config, adding samples or changing worker scheduling preserves existing draws. Adding an unrelated independent parameter preserves existing independent streams. The v1 indexed streams introduced in v0.8.0 differ from v0.7.0; frequencies are always regenerated. Exact floating result correspondence is checked in the recorded environment; bitwise cross-hardware floating arithmetic is not claimed.

Gaussian copula streams use `copula:` followed by comma-joined canonical parameter names. The matrix is reordered with these names. Cholesky is used when possible; a symmetric eigen factor handles singular positive-semidefinite matrices. The recorded correlation is latent-normal correlation, generally not the Pearson correlation of transformed marginals. Altering a correlated group may change its draws. Dependency versions and factorization are recorded.

Uniform, triangular, loguniform and scaled beta marginals have explicit finite bounds. `uncertainty.ranges` retains the legacy uniform syntax; `marginals` provides richer definitions and must not duplicate ranges. A list of `constraints` compares named parameters with `le`/`ge`, another parameter (`right`) or a finite `value`. `constraint_mode=record` retains the original draws and delegates failure behavior to on_error. Explicit `resample` retries configuration-infeasible draws with a new attempt index, up to `max_draw_attempts`. Numerical optimization failures are not resampled. Accepted draws target a feasible conditional distribution; raw marginal descriptions do not describe that accepted joint distribution. Attempt and rejection counts, exhaustion failures and denominators remain visible.

Marginal Wilson 95% intervals quantify Monte Carlo count uncertainty under the specified draws. They are not simultaneous intervals, calibrated market-choice probabilities or numerical optimizer error bounds. Requested frequencies retain failed cases; completed-case frequencies use a separate denominator. Finite payoff quantiles disclose their own finite-case counts.

## Transactional execution and resume

CLI sweep/uncertainty preflight the configuration and requested cardinality. `batch` accepts max_cases (default 100000), workers (default 1) and checkpoint_every (default 25). Malformed input, impossible constraints and strict-domain rejection precede directory creation. Later numerical or I/O failures may leave an incomplete directory.

Each processed paired case is stored in checkpoint.sqlite. TRUNCATE journaling retains checkpoint.sqlite-journal as an empty component after a successful commit, avoiding repeated create/delete races on hosted filesystems. Both final files are inventoried. Commits occur at the requested interval and on ordinary interruption; an abrupt process kill retains the last committed prefix. CSV export streams complete case rows from the database. A maximum of twice the worker count is submitted ahead. Case order, sample indexing and configuration/source/version identity are checked. `batch_progress.json` records running, interrupted or completed state; no final manifest is produced on interruption.

Resume explicitly with `entrysignal uncertainty --config CONFIG --out EXISTING_INCOMPLETE_DIRECTORY --resume` (or sweep). Configuration, normalized options, source bytes, software version and runtime fingerprint must match; mismatches and altered case hashes are rejected. Resume will not accept a directory with a final manifest. Operational cache/evaluation counts can differ across workers or an interrupted execution; scientific draws, payoffs and labels must correspond. Checksum correspondence does not authenticate a checkpoint against intentional forgery.

The Python sweep/uncertainty convenience APIs still return in-memory collections and impose the same case budget. CLI complete rows are stored transactionally, but final summary counts, failure details and quantile collections use O(n) memory. Constant-memory summaries are not claimed. Very large sweeps skip automatic figures after 10000 cases and record the reason; use a smaller explicit plotting experiment rather than an undisclosed subset.

## Solver quality and model adapters

Scouting is bounded by max_evaluations before allocating an oversized mesh. Better neighborhood probes are promoted, with at most four rounds; local_quality_passed uses payoff_atol/payoff_rtol and last_probe_improvement. This diagnosis is not a global certificate. `compare_stability` repeats a comparison on disclosed mesh factors and tighter time tolerances, reporting observed payoff spreads and ranking agreement. A spread is an observation, not an upper bound on the unknown optimum error.

First-entrant cache keys include model and solver controls except deployment_cost and learning_rate. These terms do not change first-entrant announcement controls; payoff is reevaluated with actual costs. Worker-local caches are bounded and reused_search/evaluation fields disclose reuse. Analytically constant follower profiles return one evaluated representative. payoff_grid provides stable logarithmic zero-discount matrix evaluation; discounted models use the original scalar kernel. Neither path is an optimizer or a configured-bound evaluator.

`research.ModelCapabilities` and `ResearchKernel` supply explicit model identity/version, declared assumptions, parameter/control validation, evaluation and an optional dedicated conditional solver. Extensions without their own solver are refused. The default adapter uses the validated piecewise-demand model. Adapter checks compare returned objectives with the extension kernel and do not prove callback correctness, concavity, model validity or empirical calibration. Churn, migration and new cost mechanisms are not implemented by this interface alone.

## Platform evidence

The CI recipe builds and installs wheels on Ubuntu, Windows and macOS with Python 3.12/3.13, plus an Ubuntu Python 3.10 minimum-dependency job. These are configured checks. This release's executed evidence is local Linux/Python 3.12 only; remote runs and independent platform installations remain unverified. Full TeX/Word publishing additionally needs Pandoc, python-docx, LibreOffice, TeX and CJK fonts; these are not numerical package dependencies.

## Version 0.9.0 audit repairs

Directory ownership covers CLI execution, plotting and final manifest publication; see `batch_ownership.md` for public Python lifetime, crash recovery and filesystem limitations. Exact task cardinality is required before completion. Signed-zero delay bounds are canonicalized before float-lattice enumeration, which has an explicit candidate bound as well as the evaluation budget. Outside-option labels use the gap decision basis recorded in diagnostics. Vector time weights remain in log scale before halving.

Uncertainty summaries expose `accepted_draws`, `rejected_draw_attempts`, `sampling_numerical_failures` and `exhausted_samples`. Every draw attempt belongs to exactly one of the first three categories. A draw that passes configuration checks but fails numerical optimization remains an accepted draw; the case is failed. An exhausted sample counts its final rejection. Self comparisons such as growth <= growth are tautologies, preserved in metadata but excluded from independent-range impossibility checks.

The release lock records the exact locally available dependencies, including contourpy 1.3.3, fonttools 4.61.1, kiwisolver 1.4.9 and pyparsing 3.3.2. The unchanged v0.8.0 dependency lock and original strict audit are frozen under `audit/v0.8.0`. In v0.9.0 the scientific definitions and indexed-pcg64-v1 were unchanged.

## Version 0.10.0 numerical and joint-domain boundaries

The v2 sampler preserves the v1 entropy construction, marginal transforms and nonsingular factorization. For exact identical correlation rows at rho=1, each group shares its canonical first latent CDF value. Identical marginal specifications then yield bit-identical parameter values. Group aliases and sampler version are recorded. This is a versioned floating implementation change for singular cases, not an inferred empirical correlation. Key order replay and sample-prefix stability remain tested.

Strict domain preflight conservatively uses interval bounds except when two parameters have identical normalized marginal specifications and share a proven exact latent alias. That equality proves H<=T or explicit le/ge in either direction. Merely near-perfect correlation, different marginals or different correlation rows do not receive this proof; a crossing box remains rejected in strict mode. Record/resample remain explicit policies, and the equality check does not condition the distribution or consume extra draws.

Demand combines the log growth/time scale with log shares before exponentiation, matching the revenue kernel's scale handling. A share itself may round to zero while the requested consumer stock stays positive and representable. Genuine final-stock overflow remains an error. Linear payoff quantiles retain all finite values and use bounded weighted sums for opposite-sign endpoints and difference interpolation for same-sign endpoints. Quantile definitions and denominators are unchanged. Wilson intervals compute the small normal-tail probability to handle confidence nextafter(1,0); tiny confidence can round to a zero-width interval at machine precision.

See batch_ownership.md for task identity and directory hierarchy. Original v0.9.0 audit/probes/evidence are frozen under audit/v0.9.0; current acceptance is validation/audit_v0100. The 55-check validator includes 42 independent Decimal order-statistic values, four weighted demand references and four actual process races. Linux is the executed platform; remote CI remains configured only.


## Version 0.11.0 audit acceptance

The draw algorithm remains indexed-pcg64-v2; statistical endpoint interpolation and report statuses change, not random draws. Source/version checks intentionally forbid cross-version checkpoint recovery. Recompute v0.11 summaries from a new run. The 98-check validator uses 25 independent 120-digit Wilson references and 77 independent 1200-digit quantile values, plus actual subnormal CLI execution and interrupted-prefix recovery. It covers configured extension feasibility, adaptive unit-bound sweeps, complex inputs and assessed/unassessed/failed quality states. See docs/api.md for the new callback and nullable all_local_quality_passed contracts. The frozen v0.10.0 full release, audit report, evidence and probes are under audit/v0.10.0; their original bytes are preserved.


## Version 0.12.0 audit acceptance

The 89-check v0.12 validator adds 32 invalid sequence/worker/recovery combinations, NumPy/native scalar and JSON/checkpoint correspondence, conversion/domain checks, model-owned attainment-state checks and 140 independent 1200-digit Decimal Wilson references. Production uses 120 digits only when reciprocals are subnormal; the reference uses a separately transcribed proportion formula. All references matched the recorded binary64 endpoints. All fourteen validators, 431 tests and 28 experiments are rerun with the installed wheel. Sampler indexed-pcg64-v2 and scientific formulas remain unchanged. No old-version checkpoint is carried forward. Original v0.11.0 release bytes are recoverable from its frozen original audit ZIP; identity is recorded in audit/v0.11.0/input_identity.json. Actual execution remains Linux only; CI recipes are not remote execution evidence.


## Version 0.13.0 audit acceptance

All 497 tests, fifteen validators and 28 experiments run with the installed current wheel. The 152-check numeric-ingress validator uses independent Decimal rankings, JSON literal values, 56 piecewise stock references, 36 discounted/undiscounted grid integrals and three default envelopes. It checks real CLI rejection before output creation, shape-preserving numeric conversion and model-owned metadata. The array underflow cases require a measured wider longdouble on the recorded Linux host; platform capabilities must not be inferred from a type name. Its full CI validator is therefore configured for Linux; tests mark unsupported wide-type cases explicitly rather than claiming that they ran on other hosts. Source, wheel and installed bytes are matched. No remote CI execution or global numerical certificate is claimed. The economic formulas, sampling stream and denominators are unchanged; old-source/version checkpoints require new runs.


## v0.14.0 verification scope

The complete 553-test suite, sixteen validators and 28 experiments execute against the installed 0.14.0 wheel on the recorded Linux/Python host. The 178-check validator independently transcribes 100-digit piecewise payoff integrals for four strategies over five scales and both positive/negative objectives (40 values). It also covers twelve Fraction boundary configurations, original export counterexamples, SQLite/CSV roundtrip, eight actual CLI underflow rejections and ten CLI controls. Maximum observed payoff relative error is read from its receipt; sampled agreement is not a global error certificate.

Objective consistency is now a recorded kernel policy, independent of solver-quality tolerances. The default has no positive economic absolute floor and preserves zero/sign, including subnormal cases; explicit relaxed extension policies remain disclosed declarations. Raw controls normalize before configured checks and exports. CLI numeric text and JSON share a conversion-loss guard while retaining their own lexical grammars. Model equations, sampler indexed-pcg64-v2, seeds and frequency denominators are unchanged. CI includes the new validator on all configured operating systems, but no remote CI was executed in this round. Original v0.13.0 audit inputs and exact file identities are preserved under audit/v0.13.0; its evidence ZIP contains a minimal baseline rather than another full nested release.


## v0.15.0 verification scope

All 608 tests, seventeen validators and 28 experiments are rerun against the isolated installed 0.15.0 wheel. New acceptance records 151 checks: 24 structurally decreasing constant-cost envelopes, twelve independent 120-digit envelope references isolated on a fixed mesh and refined by bisection, two near-equal endpoint comparisons, four original wrong metadata states, sixteen independent unit-payoff references, actual CLI unrankability and 72 unchanged raw PCG64 streams. The independent envelopes cover their twelve moderate parameter cases; they are not a universal oracle.

The new ordering cancels common factors and uses positive differences before a guarded precision escalation. It does not turn binary64 net payoff ties into mathematical existence claims. Unit transformations carry a fixed relative 1e-12 field-precision policy and reject loss of positive configured time separations. The bounded indexed domain preserves all earlier valid production streams; index-domain metadata is now explicit. Scientific formulas, ordinary seeds and frequency denominators are unchanged. Original v0.14.0 audit DOCX, evidence ZIP, probe, input identities and raw stream goldens are frozen under audit/v0.14.0. CI includes the new validator on configured platforms; only local Linux execution is claimed.


## v0.16.0 verification scope

All 634 tests, eighteen validators and 28 experiments are rerun with the isolated installed v0.16.0 wheel. The new follow-up validator records 378 checks: 55 independent 120-digit envelope references with derivative bisection, 129 independently inverted Wilson intervals, the original failure cases, unresolved-boundary guards, a real CLI and 39 unchanged ordinary intervals. Central-normal probability is inverted through a separate 400-digit Decimal integral series with a 200-digit pi constant; no production inverse-normal/erfinv routine supplies the reference. High-confidence and enormous-count controls remain covered. Sampled agreement is not a universal accuracy guarantee or interval certification. Ordinary random draws and default 95% reports preserve their construction; version/source checks still require fresh runs. The follow-up audit, baseline observations and input hashes are frozen under audit/v0.15.0 without a second nested full release archive.
# v0.17.0 release validation

The release requires nineteen validators, 654 tests and 31 recipe-bound experiments. New scripts/validate_v0170.py checks analytic source decisions, reconstructed plotted coordinates, five real CLI processes and 4096 exact-rational zero-discount controls. The independent scripts/probe_numeric_controls.py, frozen tests/data/v0160_round3_observations.json and original audit inputs are sealed into the release input graph.

Use fresh output paths with:

    python scripts/validate_v0170.py --out NEW_V0170_ACCEPTANCE
    python scripts/probe_numeric_controls.py --out NEW_RATIONAL_CONTROLS
    entrysignal audit --config examples/source_audit_small_scale.json --out NEW_SMALL_AUDIT
    entrysignal sweep --config examples/small_scale_regions.json --out NEW_SMALL_X
    entrysignal sweep --config examples/small_scale_y_regions.json --out NEW_SMALL_Y

The original frozen probe_round3.py reproduces the old defects and is retained only as evidence. It is not the current acceptance command. The new gate covers changes to the validator, rational reference probe, baseline fixture, small-scale examples, acceptance document and original audit archive. Source, wheel and installed bytes must agree. Earlier release evidence and checkpoints require fresh runs after the source/version change.



## v0.18.0 current release evidence

Current evidence requires 677 tests, twenty validators and 35 recipe-bound experiments. The new validator adds 1875 checks of independent net payoffs, exact unit changes, guarded envelope values and source candidate/bound diagnostics. Nonzero costs and discount/learning are evaluated against exact rational or independent global Decimal antiderivatives. Tiny-rate references use 1600 digits; this does not make the production guards interval certificates. Original A09/A10 observations and the audit archive are frozen under audit/v0.17.0. All numerical code modules are bound by source hashes, with final wheel/source/install correspondence checked before packaging. Word and LaTeX use current measured values and experiment counts from the shared release contract.


## Version 0.19.0 original-input comparison policy

The default model compares objectives at returned controls. Close scenario/outside gaps and gaps near the absolute tie boundary use original binary64 inputs when min(abs(a-b),abs(abs(a-b)-tie_tolerance))/max(abs(a),abs(b),tie_tolerance) <= 1e-8; zero scale and subnormal payoff operands also trigger. This heuristic guard is not an interval error bound. Exact common primitive/cost coefficients are cancelled. Pure rational differences retain exact order and tolerance membership. Other gaps use 80/160/320/640/1280 Decimal digits, requiring two stable rounded values, signs and tolerance sides, with a gross-scale cancellation guard. Unresolved order raises NumericalError. The built-in cached batch optimizer shares this model-owned policy.

`entry_payoff_gap` and `outside_option_gap` may differ from subtracting displayed `results[*].payoff`: the latter remain independent binary64 objective evaluations. Diagnostics include decision_basis, sign, tolerance_relation (-1/below -tol, 0/inclusive band, +1/above tol), precision_digits and representation. A true rounded-zero gap has underflow and its original-input nonzero sign; an out-of-range magnitude has null value and a log magnitude. The decision uses the guarded relation. CSV adds gap basis and outside gap representation/sign. Unattained/null results still withhold complete ranking.

`compare_results` and explicit arbitrary optimizer callbacks retain supplied-float semantics; their original objective cannot be inferred from ModelParams. Research extensions retain their own objective policies. Local quality and mesh agreement do not prove comparison accuracy or global optimality. The guard changes evaluated-candidate comparisons, not the search certificate.

A two-control singleton payoff visualization uses a point at the actual control/payoff, with fixed controls stated. A sensitivity series with one finite value uses a strategy-specific marker, preserving null gaps. Other slices and curves remain lines; no extra feasible points are invented. See docs/v0190_acceptance.md.


## Version 0.20.0 extreme decay and finite run figures

A13 separates output-range conversion from original-input sign comparison. If extreme decay could reach the segment evaluator's exp(-100000) cut, exact rational integral coefficients are expanded into exponential terms, identical terms cancel, and the least exponent is factored out before Decimal evaluation. A discarded relative tail contributes the bound sum(abs(coefficient))*exp(-100000), rather than zero, to the scaled cancellation guard. The ordinary small-discount segment/series path remains. Two precision levels must agree on rounded value, sign, tolerance relation and log magnitude for the scaled path. This is adaptive guarding with a tail bound, not interval arithmetic or a universal rounding certificate.

The v2 comparison policy retains the 1e-8 trigger and external supplied-float semantics. scaled_original_input_difference identifies the new basis. Final underflow can have value zero with negative or positive original sign. Finite positive absolute tie tolerances still define their own inclusive band; zero tolerance is supported. If the required log magnitude itself is outside binary64 range, the comparison explicitly refuses with NumericalError. The former discount=1e308, delay=1 case now resolves; the inherited v0.19.0 refusal fixture was moved to discount=1e308, delay=H=T=1e308 to test the explicit log-output range boundary. The original fixture remains as a new successful regression, and original v0.19.0 files are frozen under audit/v0.19.0.

A14 marks every contiguous finite run that has only one unique coordinate. Repeated vertices remain in the line and CSV; the actual coordinate gets one marker. Missing values keep their breaks. Runs with a nonzero line segment retain ordinary lines; all-null and empty input creates no data. Strategy markers remain distinct. This completes the A12 single-observation coverage for repeated and disconnected observations, without changing controls or filling missing data. See docs/v0200_acceptance.md.


## Version 0.25.0 recorded local probes

`solver.profile_announcement` canonicalizes all accepted Real control fields before structural tests. Its module-level return remains `(intensity, nonunique)`; it is not added to the top-level exports. Fractions that round to maturity use the stored binary64 control consistently.

Default `optimize` results add `local_probe_diagnostics`; existing fields keep their meanings. The policy is `recorded_local_probes_v1`. `rounds` has at most four records, each with `round`, `starting_control`, two `probes`, `selected_control`, `quality_threshold`, `improvement_diagnostic`, `passed`, `control_promoted`, `distinct_neighbors_in_feasible_directions`, `selected_control_neighborhood_assessed` and `termination`. Each probe has `side`, `control`, `distinct_from_start` and `already_evaluated`. A control contains strategy, delay, announcement and displayed payoff. No additional model evaluation is performed for logging.

`status` is assessed, not_assessed, analytic_flat or not_applicable. `reason` distinguishes unchanged feasible neighbors, promoted controls, coincident probes, fixed delay, flat delay, first-entrant timing, attained envelope and unattained results. `final_control_neighborhood_assessed` reports only an actual unchanged final neighborhood. A passed last increment after promotion does not assess that newly selected neighborhood. Fixed-delay results retain and record their existing coincident round; first-entrant, analytic-flat and joint-envelope branches have empty rounds. Thresholds retain the displayed-payoff scale convention.

JSON/checkpoints and Python rows retain dictionaries. In CSV, only the added `local_probe_diagnostics` field is serialized as strict JSON, parsed with `json.loads`; absent fields in failed or custom rows are empty. Existing nested CSV cells are not silently reformatted. New versions require new source-bound checkpoints.

HTML shows recorded rounds and warns on observed differences between displayed subtraction and guarded comparison sign/tie-band membership. The warning includes gap sign and decision basis; it never changes optimization or supplied custom-float semantics. See docs/v0250_acceptance.md for independent references, measured wide-type capabilities and exact scope.
