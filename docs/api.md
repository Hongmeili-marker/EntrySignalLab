# API and configuration

`ModelParams(**values)` creates an immutable validated model. `DecisionBounds` sets follower delay bounds, intensity upper bound, scouting points and solver tolerance. Optional upper delay defaults to H. Optional intensity upper bound `None` means no cap. JSON `null` has this meaning in configuration files.

`shares(params, strategy, delay, announcement=0)` returns two shares. `demand(params, strategy, time, delay, announcement=0)` accepts a scalar or array of valid times and returns two consumer stocks. `revenues` returns two discounted gross revenues. `payoff` returns object platform net payoff.

`optimize(params, strategy, bounds=None, rival_delay=None)` returns a dictionary. `compare(params, bounds=None, rival_delay=None, tie_tolerance=1e-8, outside_option=0.0)` returns four results, co-best labels, an outside-option comparison and interpretive metadata. API and CLI first-entrant defaults both use min(0.15,H); explicit first-entrant rival controls must be admissible. RL/DL ignore this irrelevant parameter. A four-scenario JSON configuration still validates its fixed rival control.

## Result fields

| Field | Meaning |
|---|---|
| status | profile_optimum, numerical_candidate, attained_joint_optimum, no_finite_announcement_optimum, or no_finite_joint_optimum |
| delay | Fixed rival lag in RF/DF; chosen object lag in RL/DL |
| announcement | Chosen object announcement intensity; 0 for D strategies |
| payoff | Discounted net object payoff, or null if no finite result |
| evaluations | Number of distinct profiled delays evaluated; it excludes derivative evaluations and must not be compared as identical work to a 2D objective count |
| delay_active | Lower, upper, interior, fixed singleton or fixed rival delay |
| announcement_active | Lower, upper, interior, fixed cap at 0 or not applicable |
| announcement_stationarity_residual | Feasible-direction KKT violation in payoff/intensity units; null if unrepresentable |
| announcement_stationarity_log_residual | Log magnitude of a nonzero violation; null when there is no violation |
| announcement_stationarity_scaled_residual | Violation divided by the larger marginal benefit/cost, between 0 and 1 |
| announcement_stationarity_representation | finite, underflow or outside_float_range; no silently lost raw violation |
| local_improvement_residual | Deprecated nullable field; zero only for a measured unchanged-control probe neighborhood or an analytically flat delay, otherwise null |
| local_improvement_residual_assessment | Deprecated flag, status, final-control assessment and last-probe quality status; never infer measured zero from null |
| local_probe_diagnostics | Actual controls, signed gains and numeric thresholds for at most four local probe rounds, with explicit final-neighborhood assessment and reasons |
| announcement_stationarity_diagnostic | Marginal-difference basis, precision, sign and projected raw/log/scaled KKT representation |
| announcement_nonunique | Zero announcement effect and cost at returned delay permits multiple intensities |
| delay_nonunique | An identified zero-revenue flat delay profile permits multiple delays |
| attainment | attained or not_attained; absent maximizing controls remain null |
| supremum | Joint envelope value for the zero-cost unbounded RL branch; otherwise null |
| supremum_delay | Envelope maximizing lag when no finite joint optimizer is returned; zero can denote a right limit |
| envelope_evaluations | Number of envelope candidate values evaluated for an attained joint solution |
| globally_certified | False; delay search is not a formal certificate |
| equilibrium | False; no game equilibrium computation is performed |

## Batch operations

`workflow.sweep(params, bounds, rival, axes, comparison=None, on_error="raise")` evaluates a Cartesian product of one to three named parameter lists. Every resulting model is validated. `workflow.uncertainty(params, bounds, rival, ranges, n=100, seed=104, comparison=None, on_error="raise")` draws independent uniforms with paired model draws across scenarios. A tie and an unrankable result have their own categories. These frequencies rank entry scenarios before applying the outside-option reference.

The CLI supports `audit`, `evaluate`, `optimize`, `sweep`, `uncertainty`, `reproduce`, `benchmark`, `verify` and `--version`. Configuration accepts params, bounds, rival_delay, axes, uncertainty, seed, label, plot, comparison and on_error. Unknown or duplicate JSON keys, nonfinite values and invalid decision domains are rejected. The `uncertainty` object follows the current field table below; `batch` is a top-level configuration object. `plot` accepts announcement, follower delay and surface_announcement_max. First-entrant trajectories always use the supplied rival lag. Output directories must be empty. Domain and option errors precede directory creation; a later I/O/export error can leave partial output without a completed manifest.

`rescale_experiment(params, bounds, rival_delay, time_factor=1, consumer_factor=1)` returns parameters, bounds and rival lag for t'=a*t and D'=b*D with payoff units unchanged. Transform a delay by a and an intensity by b/a. See `docs/model_contract.md` for dimensional formulas. This changes representation rather than economic assumptions.

## Extending the implementation

Add a new configured research case by changing a JSON file. A new demand kernel or cost function requires editing the model module and independently validating its integrals and optimizer assumptions. The intensity profiler is valid for this release's concave linear-fractional benefit and quadratic cost. It must not be reused unmodified for a nonconcave announcement effect. No automatic plugin registration or arbitrary symbolic expression execution is provided.


## Result integrity

`verify_manifest(directory, expected_source=None)` checks a valid manifest schema, exact artifact inventory, file/configuration hashes and agreement with archived config.json when present. Add `current_source_hashes()` as expected_source, or CLI `verify DIRECTORY --check-source`, to require recorded source identity to match the installed package. Publication/release gates require this source check. Historical archives can be verified without requiring the current version. This is content correspondence, not authentication, authorship or proof that execution occurred.

Activity labels describe actual selected boundaries; positive interior intensities are not compared to a time tolerance. A singleton delay domain is fixed. Unit conversion rejects lost positive terms and avoidable binary exponent overflow; finite inputs can still exceed numerical intermediate ranges in other calculations.

## Current uncertainty configuration

The nested `uncertainty` object accepts exactly the following keys. Place `batch` at the top level beside `uncertainty`, never inside it.

| Nested key | Meaning |
|---|---|
| ranges | Parameter names mapped to [lower, upper] uniform ranges |
| samples | Requested paired sample count, default 100 |
| marginals | Named uniform, triangular, loguniform or beta specifications |
| correlation | Gaussian latent-normal copula names and matrix |
| constraints | Explicit joint parameter constraints |
| constraint_mode | record or resample |
| max_draw_attempts | Maximum attempts per sample |

For example, `{"uncertainty":{"ranges":{"growth":[0.1,0.1]},"samples":2},"batch":{"workers":2,"checkpoint_every":1}}` keeps execution settings outside the sampling specification. See `examples/documented_uncertainty_batch.json` for all nested options together. Unknown nested keys are rejected before output creation.

<!-- BEGIN GENERATED RELEASE CONTRACT -->
Publication synchronization requires valid receipts for all 28 independent verification directories and 61 experiments declared in `scripts/release_contract.json` for version 0.25.0. Regenerate this paragraph with `python scripts/sync_api_docs.py` after updating the contract; `--check` rejects stale text.
<!-- END GENERATED RELEASE CONTRACT -->

## Independent verification receipts

`record_validation(directory, validator_path)` records all outputs with package hashes, software version and validator-file hash. `verify_validation(directory, validator_path, expected_seed=None)` checks the exact inventory and these identities. Receipt integrity does not prove execution, authorship or scientific correctness; independent reference formulations and the raw results address numerical agreement separately.

Manifest readers validate required execution metadata and reject duplicate JSON keys. Complete historical records without manifest_schema remain readable as schema 1; missing required fields do not pass. Current-source verification is opt-in for ordinary archived results and mandatory for publication evidence.

## Test and publication receipts

`record_test_evidence(directory, runner, test_directory)` binds the entire Python test-source inventory, runner, version, package and result files. `verify_test_evidence` also checks consistent successful counts, zero skips and the text log. The release stores these files under `validation/tests`.

`scripts/release_contract.json` specifies the exact experiment inventory and validator seeds. The portable publication chain uses logical `results/`, `validation/` and repository-relative paths. `seal_publication.py` runs after document generation and PDF compilation; `check_release.py` rejects missing experiments, stale inputs, and changed final files. Rerun synchronization and document generation after input edits. Visual inspection remains a separate release gate. None of these receipts authenticates authorship or proves execution.

Source-formula audits have a narrower range than operational payoffs. Out-of-range printed expressions raise a controlled ValueError. Reproduction writes `source_audit_status.json` with evaluated or skipped status and a skip reason.

## Revenue scope and floating delay intervals

`payoff` evaluates only the object revenue used by the objective. Its value does not depend on `margin_y`, and an unrepresentable rival revenue cannot block it. `revenues` explicitly requests both revenues and retains controlled range errors for either one. Unrepresentable object revenue or costs still raise errors.

The scouting mesh retains distinct binary64 delays. Adjacent floating endpoints have no representable interior point and are compared directly, with no scalar refinement or zero-width interval. `delay_refinement_intervals` counts actual refinement attempts. Local perturbation tests retain their sampled scope.

The release contract includes per-experiment operation, configuration path or inline configuration, and expected seed. The final gate compares each archived recipe with its shipped input. The input chain also binds the orchestrator, reproduction script, unit demonstration, checker, rejection probe, packager, project metadata and lock. Changing these inputs requires resynchronization and regeneration; configuration changes require regenerating the affected experiments.

## Comparison policy and evaluation feasibility (v0.7.0)

JSON `comparison` accepts `tie_tolerance` (absolute payoff tolerance, default 1e-8, nonnegative) and `outside_option` (default 0, finite). Pass the same dictionary as `comparison=` to sweep/uncertainty and as keyword arguments to `compare`. This policy is recorded in JSON/CSV, HTML and sweep reference lines. No relative tolerance or automatic payoff-scale adjustment is applied. A smaller tolerance can change labels without changing payoffs.

CLI `evaluate` enforces configured follower delay bounds, first-entrant fixed rival delay and announcement caps by default. `--allow-outside-bounds` permits diagnostic evaluations within the mathematical domain and returns `within_configured_bounds=false`, `diagnostic_only=true`, `evaluation_scope=outside_configured_bounds` and structured `bound_violations`. It cannot bypass the global delay domain or silent-strategy zero-announcement requirement. Direct `payoff` and `revenues` remain mathematical functions; use `workflow.configured_feasibility` when evaluating a configured experiment through the API. `evaluate` requests both revenues and retains range checking for both.

## Batch preflight and recorded failures (v0.7.0)

The default `on_error="raise"` checks conservative Cartesian/marginal domains before iteration, with the v0.10.0 exact copula-equality exception described below, including growth end versus horizon, fixed rival and explicit delay bounds. Malformed ranges, unknown keys, negative/nonfinite inputs, invalid base configurations and unknown policies remain fatal in both modes.

Opt-in `on_error="record"` allows individually infeasible cases to be recorded. Each failed paired case has four rows with null payoff and control values, empty winner/reference preference, error stage/type/message and either `invalid_configuration` or `numerical_error`. Unexpected exception types still abort. Valid cases continue. `sweep_summary.json` reports requested/completed/failed/rankable counts and failure records. Unrankable valid models remain distinct from failed computations.

Uncertainty `frequency` divides by all requested draws, including failures. `valid_sample_frequency` divides nonfailure categories by completed draws; failure categories and all-failed runs have null conditional frequencies. These denominators and full failed parameter sets are recorded. No resampling or renormalization is hidden. Summary `run_status` is complete, partial_failure or all_failed. CLI exit 0 in record mode means the recording workflow completed; inspect run_status and counts to assess success. Strict rejection exits 2 and creates no output directory.

Sweep curves retain missing values as gaps and mark failed cases; regime maps have separate failure categories and symbols. The three new release examples demonstrate custom comparisons and recorded sweep/uncertainty failures. Independent interface validation uses a separate Decimal label selector and independent feasibility/RNG accounting; it is not a numerical payoff oracle.

## v0.8.0 APIs

DecisionBounds additionally accepts payoff_atol=1e-10, payoff_rtol=1e-8 and max_evaluations=20000. Scouting and profile evaluation enforce the budget. Better actually evaluated probes are promoted; local_quality_passed, probe_improvement_found, last_probe_improvement and probe_rounds report the bounded local check. This does not establish global optimality.

compare reports entry_payoff_gap/outside_option_gap and representation diagnostics, plus all_local_quality_passed. Overflowing informational gaps remain null with an explicit outside_float_range diagnostic instead of blocking finite objectives. compare_stability(params,bounds=None,rival_delay=None,comparison=None,factors=(1,2,4)) reports observed spreads, payoff_stable and ranking_stable. No observed spread is an upper bound on optimizer error.

workflow.prepare_sweep/prepare_uncertainty preflight and return metadata plus a task factory. batch.run_batch executes into a checkpoint directory. CLI --resume accepts only incomplete matched batches. normalize_batch accepts max_cases, workers and checkpoint_every. summarize_sweep now infers comparison/error policy and rejects disagreement or mixed policies.

uncertainty additionally accepts batch, marginals, correlation, constraints, constraint_mode and max_draw_attempts. Indexed draws are independent of JSON ordering. Requested and completed frequencies have marginal Wilson intervals; payoff quantiles record finite-case counts. The Python function accepts batch as an argument; JSON places batch at the top level. The nested uncertainty object accepts ranges, samples, marginals, correlation, constraints, constraint_mode and max_draw_attempts. Full syntax and statistical/operational limits are in docs/reproducibility.md.

payoff_grid(params,strategy,delays,announcements) returns a matrix with announcement rows and delay columns, limited to one million controls. Zero-discount evaluation is vectorized and scaled logarithmically; discounted cases use scalar payoff. It checks the mathematical domain, not narrower configured experiment bounds.

research.default_research_kernel, evaluate_research and optimize_research provide explicit model adapters. An extension must supply validation/evaluation callbacks and its own conditional_solver; default solver assumptions are not silently inherited. Returned finite objectives are reevaluated through the kernel. Capability flags are declarations and do not establish calibration or mathematical proofs.

## Batch ownership in 0.9.0

`entrysignallab.batch.run_batch` acquires a `DirectoryLock` by default. The optional `lock` parameter accepts an active lease owned by the current process/thread for exactly the resolved output directory. CLI callers hold it through plot and manifest generation. External Python publishers should use the outer-lease pattern in `batch_ownership.md`. A task factory must supply every missing case in order until `meta["requested_cases"]` is reached. Resume may omit the committed prefix and may use an empty factory if that prefix is already complete. Short new runs and indices beyond the declared total cannot complete. Resume additionally checks `runtime_fingerprint()`; incompatible runtimes are rejected before progress mutation.

Draw accounting distinguishes accepted parameter draws from successful optimizations. Check `attempt_accounting` and each explicit counter rather than deriving rejections as attempts minus requested samples.

## v0.10.0 API contracts

prepare_sweep returns axes and task_generator_version in metadata; axis key order is canonical, while value order and duplicates are significant. run_batch binds this identity even when config is empty. Resume cannot mix different prepared scans. Use matching metadata/factories; factories must still supply the declared ordered missing cases.

DirectoryLock rejects active and already materialized ancestor/descendant experiments. Siblings remain independent. The same-user shared-temp coordinator and persistent OS registry leases protect the hierarchy check/create transaction. Existing leases still cover final publication. See batch_ownership.md for protocol and filesystem scope.

SamplingPlan.proves_equal(left,right) is a conservative exact joint-support proof for identical normalized marginals and exact identical rho=1 rows. Strict model/constraint preflight uses this proof without resampling; unproven crossing boxes remain rejected. indexed-pcg64-v2 records exact latent aliases.

sampling.linear_quantiles(values,probabilities) uses linear order-statistic interpolation with finite, bounded results and validates probabilities in [0,1]. Uncertainty summaries use it without dropping finite cases. sampling.wilson_interval uses the lower tail for every valid confidence in (0,1), returning None for total=0. demand retains positive representable weighted stocks even if the unweighted share underflows; it supports scalar and array times and retains final-range checks.


## v0.11.0 checked input, statistical and solution contracts

`sampling.wilson_interval` accepts Python int and NumPy integer counts, excluding booleans. Validated counts become Python int; reciprocal-count arithmetic avoids fixed-width products and squared denominators. Confidence is a validated float in (0,1). Zero totals return None. Finite binary64 endpoints can round to 0 or 1 at sufficiently large counts; arbitrary-precision endpoints are not promised.

`ResearchKernel` appends optional `validate_solution(params,strategy,bounds,rival_delay,result)`. Evaluation-only kernels need no solution validator. Optimization now requires both a dedicated solver and this callable; it must return the literal True after checking the configuration, otherwise the adapter rejects the result. Existing custom optimization kernels must add it. General models own their bounds/parameter semantics; these are passed unchanged when supplied. The default kernel reuses configured_feasibility to check follower bounds, announcement cap, silent intensity and fixed rival delay; finite objectives are also reevaluated. An unattained state is shape-checked and passed to the validator. This is callback validation, not a proof that a custom callback is correct.

`rescale_experiment` preserves delay_upper=None as adaptive to each current growth_end. Explicit numeric bounds alone are multiplied by the time factor. Width/collapse validation uses effective bounds and remains active. Converted configurations can be reused in growth-end sweeps and uncertainty.

`demand` accepts real scalars and NumPy-compatible real arrays of any supported shape, including integers. Complex scalars, complex dtypes (even zero imaginary parts), and object-array complex elements are rejected before conversion. Real inputs still require finite times in [0,horizon].

`sampling.linear_quantiles` sorts finite samples and retains h=(n-1)*q and its binary64 fractional part. It interpolates binary64 endpoints as exact rational numbers and rounds the final value once to binary64, including nearest-even subnormal ties. This avoids both endpoint-difference overflow and separate-product double rounding. Ordinary final bits can improve relative to earlier versions; sample membership, probabilities, denominators and draw streams do not change. The exact guarantee concerns endpoint interpolation at the computed index, not exact real-arithmetic computation of h.

`compare`/`compare_results` add local_quality_by_strategy: pass/fail for explicit boolean checks on finite candidates, not_assessed for a finite candidate without a check, not_applicable for a null-payoff/unattained candidate. Aggregate local_quality_status is fail if any assessed check fails, pass if all four finite candidates are assessed and pass, and not_assessed otherwise. local_quality_assessment_complete reports whether all four are assessed. all_local_quality_passed is now True/False/None for these three aggregate states. Missing checks no longer imply pass. Ranking and co-best policies are unchanged.

Batch rows carry local_quality_status, local_quality_assessment_complete and scenario_local_quality_status. Sweep/uncertainty summaries add quality_status_counts (pass/fail/not_assessed), quality_assessment_complete_cases/samples and quality_excluded_failed_cases/samples. Status counts partition completed cases/samples; configuration/computation failures are excluded and disclosed separately. quality_warning_cases/samples counts actual fail only. A failed check takes precedence even when another scenario is not applicable, so assessment completeness is a separate field. All diagnostics remain local, without a global optimality certificate.


## v0.12.0 conversion, execution and research-state contracts

The shared finite_number first converts an allowed Real input to binary64 with controlled errors, rejects nonfinite conversion and any nonzero value that underflows to zero, then applies positivity/lower-bound checks to the stored value. Fraction and extended-precision reals are accepted only when representable under this rule. This is a binary64 API, without arbitrary-precision parameter storage. Representable subnormals and permitted signed zero remain valid.

DecisionBounds construction canonicalizes representable finite numeric fields (delay bounds, announcement cap, time tolerance and payoff tolerances) to Python float. Explicit validate(params) still checks the complete domain, budgets and invalid specifications, retaining the established validation call pattern. Defaults and None bounds retain their meaning. optimize returns a native bool local_quality_passed. compare_results also normalizes an explicit np.bool_ check to bool; strings/numbers are not treated as boolean checks. The research validate_solution callback separately continues to require literal True.

run_batch requires nonnegative Python integer task indices. A new factory starts at zero; recovery accepts a contiguous full factory from zero or a contiguous remaining suffix starting at the initially committed resume_prefix. The prefix is fixed before iteration. Every supplied index must be in range, in order and nonrepeating, including supplied prefix entries. A complete prefix may use an empty factory. Missing, extra, duplicate, negative, boolean and float indices are rejected in both serial and process execution. An interrupted run may retain a valid committed prefix; rejection does not imply identical operational progress across worker counts or that a lazy factory can be validated before it is consumed. Metadata does not authenticate arbitrary factory changes.

Research solver results explicitly include payoff, delay and announcement. Finite results permit attainment=attained or candidate; omission normalizes to candidate, which does not certify optimality. not_attained requires null controls and null payoff. Unknown/contradictory attainment states, finite payoffs with known no_finite_* statuses, and nonfinite optional supremum fields are rejected. Generic kernels still own mathematical control and existence semantics through validate_solution. The default piecewise model cross-checks a null-optimum claim with its own default solver before accepting it; this comparison is model-specific and does not prove arbitrary extensions or numerical global optimality. Existing configured-feasibility and objective reevaluation checks remain.

wilson_interval retains the ordinary path when 1/total is normal. If that reciprocal is subnormal or zero, a 120-digit Decimal guard keeps the integer count scale until final binary64 endpoint conversion. The fallback has explicit exponent bounds supporting the tested enormous integers; output endpoints remain binary64 and can correctly coincide when the true interval is below their resolution. This is not a claim of formally correctly rounded arbitrary-precision intervals. Counts, confidence semantics, sampling draws and frequency denominators are unchanged. The 140 independent 1200-digit cases include a representable-width counterexample at count=10**25,total=10**325.


## v0.13.0 numeric ingress and metadata contracts

compare_results copies result dictionaries and stores checked native float payoffs before ranking or gap arithmetic. Explicit np.bool_ quality flags also become bool. The caller's dictionaries retain their original objects. Native binary64 rounding defines stored payoff values; fixed-width NumPy arithmetic is not used for ranking. Actual binary64 gap overflow keeps its explicit range diagnostic.

load_config and read_json use checked floating-literal parsing. A literal whose mantissa is nonzero but whose binary64 conversion is zero is rejected before model construction. Overflow/nonfinite literals reject as before; exact zero, including signed/exponent forms, remains zero. Integer parsing is unchanged. Strings containing numeric-looking text are not parsed as numbers. JSON CLI preflight errors exit 2 before creating the output directory.

demand accepts supported real scalar/array shapes, including integer and object arrays of numbers.Real such as Fraction. Numeric arrays are checked for finite conversion and raw nonzero-to-zero loss; object reals use finite_number elementwise. Complex, boolean, string and unsupported object arrays reject. payoff_grid retains its nonempty one-dimensional integer/unsigned/floating vector contract and one-million-control limit, with the same conversion-loss check before either discount branch. Exact zero, signed zero and representable subnormals remain admissible in their mathematical domains. A value already rounded to zero before the API call cannot be distinguished from an intentional zero.

Scalar mathematical controls normalize to native float before demand, shares, revenues, payoff and announcement-gradient computation. decisions remains validation-only and returns None. Fraction(1,8) is an ordinary accepted delay equivalent to 0.125; arbitrary-precision computation is not provided.

Null research results reject known finite-solution statuses. Generic kernels still own their domain and existence semantics. The default piecewise kernel additionally requires the matching no_finite_* status; RL null results require finite supremum and supremum_delay within effective delay bounds. Both the reported value and the envelope evaluated at its reported lag must agree with the reference envelope. Numerical equality is model-owned: math.isclose with relative tolerance 1e-10 and absolute tolerance eight times math.ulp(reference), independently of payoff_atol/payoff_rtol. No positive economic-scale absolute floor is added. Alternative equal envelope locations may pass, so exact lag equality is not required. RF null results, whose default schema has no envelope fields, reject non-null optional envelope metadata. Missing required default metadata is an intentional compatibility change.

Finite default-model envelope claims are also checked against an attained joint reference and the returned payoff/position. Custom model callbacks can define other bounds/statuses, including negative locations in their own domain; they still must return literal True. These checks establish model-specific numerical consistency, not arbitrary-model global optimality. Original v0.12.0 audit inputs are frozen under audit/v0.12.0. Author details are now populated in CITATION.cff.


## v0.14.0 configured controls and research objective consistency

configured_feasibility and resolve_plot_settings store checked binary64 controls before comparing configured boundaries or emitting controls. Exact-real inputs such as Fraction(1,10) are assessed at their declared stored float value. Genuine violations and unsupported or unrepresentable inputs retain controlled rejection.

Finite optimize_research results copy and normalize delay, announcement and payoff before validate_solution and mathematical reevaluation. Core result fields therefore export through JSON and checkpoint/CSV as native floats; null controls remain None. The generic adapter does not impose the default model's nonnegative domain on custom finite controls: model-specific domains, bounds and existence semantics still belong to callbacks. Extra extension metadata is not recursively reinterpreted or promised JSON-compatible. Caller objects are not modified.

ResearchKernel adds optional trailing objective_atol=0.0 and objective_rtol=1e-8 fields, preserving previous positional arguments. Both must be finite nonnegative Real values representable as binary64. Objective correspondence uses math.isclose with this relative tolerance and max(objective_atol,8*math.ulp(reference)) absolute tolerance. With objective_atol=0, zero/nonzero mismatches and opposite signs also reject, even in subnormal cases. Exact signed zeros are equivalent. An explicitly positive objective_atol permits a declared approximation across zero; it is not silently inherited from DecisionBounds.payoff_atol/payoff_rtol.

Returned objective_consistency overwrites a solver-supplied field of the same name and records status, reference_payoff, declared absolute/relative tolerances, eight-ULP allowance, effective absolute tolerance and zero_sign_guard. Unattained results record not_applicable rather than a passed finite-objective check. Explicit relaxed policies are declarations; passing them does not establish exact payoffs, calibration or optimality. The default kernel's separate envelope-metadata tolerance remains relative 1e-10 and eight ULPs, as in v0.13.0. Approximate extensions relying on the former hidden 1e-10 absolute floor must declare their intended policy.

CLI evaluate --delay and --announcement check the original floating token before model construction. Nonzero-to-zero conversion, overflow and nonfinite text exit 2 with a controlled argument diagnostic. Existing Python float text grammar is preserved, including supported whitespace, underscores and decimal Unicode digits; JSON continues to use its narrower decoder grammar and unchanged integer parsing. Exact exponent/signed zeros and representable subnormals remain valid subject to mathematical/configured bounds. Use --delay=-1e-400 when passing a negative scientific token so argparse treats it as the option value.


## v0.15.0 ordering precision and indexed-domain contracts

Uncapped RL envelope ordering compares revenue differences with deployment-cost differences, cancelling the common discount factor before arithmetic. Rounded net payoff equality is not an attainment criterion. With a constant deployment cost or zero deployment cost, the envelope strictly decreases on every positive-width lag interval in this effective-benefit branch. Singleton zero and maturity endpoints retain their actual finite payoffs. Close logarithmic comparisons use adaptive 80/160/320-digit Decimal evaluation of component differences; unresolved ordering raises NumericalError. These numerical comparisons do not certify all continuous roots or a global interval bound.

The default research kernel additionally requires supremum metadata to preserve zero/nonzero status and sign. Signed zeros remain equivalent. Its relative 1e-10/eight-ULP policy is otherwise unchanged. This guard is distinct from the declared finite-objective policy and does not alter explicit custom objective_atol choices.

rescale_experiment rejects any nonzero transformed field whose binary64 value differs from its exact rational unit transform by more than relative 1e-12. No absolute economic floor is used. It also preserves every positive separation among effective delay bounds, fixed rival delay, growth_end and horizon; collapse raises a controlled ValueError. Rechoose units for rejected scales. Adequately represented subnormal transformations remain valid, but arbitrary subnormal rounding cannot be presented as a model-preserving conversion.

indexed_rng seed remains a nonnegative Python/NumPy integer of arbitrary size. sample index and draw attempt must additionally fit one unsigned 32-bit word (0..4294967295). SamplingPlan.draw shares this check; metadata adds sample_index_domain and draw_attempt_domain. The same supported inputs produce identical indexed-pcg64-v2 streams, so sampler_version is unchanged. Inputs beyond the declared index domain now reject instead of silently aliasing another entropy tuple. CLI max_cases <=10000000 and rejection-attempt budgets remain stricter. No previous-source checkpoint is resumed under the new package version.


## v0.16.0 envelope roots and small confidence

The uncapped RL envelope uses a strict sign bracket mapped to [0,1]. Normalized width is bounded by min(1e-13, tolerance/span), with a four-epsilon floor. A loose absolute time tolerance never turns an interior root into an original endpoint. When the computed balance is nonzero, both final bracket endpoints must remain strictly inside the original bracket; they enter the existing component-order comparison. A computed zero balance may select an interior representative. Adjacent floating controls can terminate an already interior bracket. Unresolved original-boundary separation, nonfinite interior balance or 256-iteration exhaustion raises NumericalError. The returned envelope_root_diagnostics list records initial_lower, initial_upper, final_lower, final_upper, iterations, normalized_tolerance and termination. Empty lists denote no bracketed internal roots. These records do not prove exact roots or interval/global optimality. Bounded follower refinement and logarithmic announcement profiling keep their separate tolerances.

wilson_interval uses sqrt(2)*erfinv(confidence) when confidence<0.5, avoiding cancellation in 1-confidence. For confidence>=0.5, the previous lower-tail NormalDist inverse remains. Large-count Decimal arithmetic is retained; final endpoints remain binary64. Positive representable small-confidence endpoints are preserved within the tested numerical policy, while truly unresolvable endpoint differences may still round together. Default 95% intervals and 39 frozen ordinary controls match v0.15.0 exactly. This is a numerical API repair; no new distribution, frequency denominator or sampler algorithm is introduced.
# v0.17.0 diagnostic metadata and numeric figure axes

source_audit retains its six check IDs and adds explanatory fields to DF_INTEGRAL_IDENTITY: decision_basis, exact_difference, normalized_discrepancy and numerical_values_are_descriptive. pass=false follows from sH/8>0 on the source domain, not a fixed absolute tolerance. Existing numeric output fields remain available and can include a correctly rounded zero; that does not override the analytic contradiction. Source assumptions and controlled range checks are unchanged.

regime_plot formats both numeric axes with adaptive scalar precision, scientific factors and offsets. A displayed offset is part of the coordinate meaning and must remain in exported figures and manuscript captions. No parameter, payoff, winner, CSV coordinate or sampling distribution is rescaled. Single-point axes show the actual colored samples, since a nearest mesh would have zero-width cells. They may have an expanded visualization range; this is not an expanded experiment domain. See docs/v0170_acceptance.md and the small_scale_regions/small_scale_y_regions examples.



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


## Version 0.21.0 search diagnostics

Finite optimize results include search_precision. Its original_input_profile_order_v1 policy shares the default-model difference helper with scenario comparison, with zero strict ordering tolerance. guarded_comparisons counts actual guarded computations; rounded_order_disagreements counts computations whose original sign differs from the rounded subtraction; max_precision_digits is zero for exclusively exact-rational/no guarded arithmetic. bounded_scalar_refinements and guarded_golden_refinements disclose local method use; both may apply to one interval if a collision appears during a scalar run. evaluated_candidate_consistency_checks counts final node comparisons excluding the returned node. These counters describe this search, not the outside-option comparison or a global certificate.

delay_refinement_diagnostics supplies interval, method and iterations, with termination for guarded golden steps. last_probe_improvement_diagnostic is null without a probe assessment; otherwise it has the existing gap schema (value, sign, tolerance_relation, representation, log_abs, decision_basis, precision_digits). Its tolerance is the configured local-quality threshold. last_probe_improvement and probe_improvement_found remain binary64 output amounts; a zero amount can accompany a positive underflow sign. local_quality_passed uses the guarded threshold relation.

Unattained early-return states retain their existing null semantics and need not contain finite-search diagnostics. Arbitrary optimizer callbacks and compare_results still own their supplied-float objective semantics. The built-in CachedFirstOptimizer continues to reevaluate actual first-entrant costs; no deployment/learning-rate change can alter its analytically cost-independent first-entrant control.

## Version 0.22.0 mesh spread diagnostics

`compare_stability` orders the model-owned controls returned by different mesh factors using original-input differences. Its spread can differ from `max(payoffs)-min(payoffs)`. Each strategy records `observed_payoff_spread_diagnostic` with the existing gap schema, `quality_threshold`, `maximum_payoff_factor` and `minimum_payoff_factor`. The threshold remains `payoff_atol + payoff_rtol * max(abs(displayed_payoffs))`. It must be finite. A zero displayed spread amount can retain a nonzero underflow sign; `tolerance_relation <= 0` decides `within_quality_tolerance`. Null/unattained results leave the spread diagnostic and selected factors null and this flag false.

`payoff_stability_precision.policy` is `original_input_mesh_spread_v1`. Near gaps use the shared original-input guard; unresolved order or an unrepresentable threshold raises NumericalError. `ranking_stable`, cross-mesh `payoff_stable`, and each individual report's local-quality status describe separate observations. Their agreement is not a continuous global or interval error certificate. See docs/v0220_acceptance.md.


## Version 0.23.0 announcement diagnostics and visible report quality

Announcement marginal benefit and cost whose log difference is at most 1e-8 use original binary64 inputs. Zero-discount differences use exact rational arithmetic. Discounted differences use 80/160/320/640/1280-digit arithmetic, requiring two stable rounded values, signs, scaled values and log magnitudes under a cancellation guard. Unresolved differences raise a controlled numerical error. The public announcement_gradient and optimize stationarity outputs share this policy. Existing raw/log/scaled fields remain. announcement_stationarity_diagnostic records decision_basis, precision_digits, gradient_sign and scaled_representation. Fixed controls and feasible monotone upper boundaries retain zero projected violation. These are adaptive diagnostics at returned controls, not interval or global certificates; a tiny nonzero KKT residual need not fail a local payoff check. Residual units are payoff per intensity, distinct from payoff tolerance units.

Structural zero announcement effect is determined from original growth, margin, network and 0 < delay < growth_end. An unrepresentable discount-times-delay exponent is a numerical range failure, not zero effect. A cost-free finite positive cap uses the monotone upper control without requiring the tiny marginal magnitude. Positive-cost range failures refuse. An unbounded effective cost-free profile retains its nonexistence semantics. Extreme full-scenario comparisons can still refuse when their log gap cannot be represented.

The deprecated local_improvement_residual is zero only with status assessed_zero for evaluated last-probe neighbors at an unchanged returned control, or analytic_zero for an analytically flat delay. Otherwise it is null with status not_assessed or not_applicable. local_improvement_residual_assessment records that status, deprecated=true, final_control_neighborhood_assessed and last_probe_quality_status. A finite payoff can pass its last-probe tolerance after promotion while the final neighborhood remains unassessed. last_probe_improvement and its signed diagnostic are increments relative to the previous probe control, not measured residuals at the newly returned control. Probe displacements that round back to the same control also leave the final neighborhood unassessed. Consumers must support null in JSON and empty CSV fields.

The default report.html now displays aggregate and per-strategy local quality, scaled announcement KKT diagnostics, and optional payoff/ranking mesh agreement. States pass, fail, not_assessed and not_checked are distinct; a stable ranking does not hide an unstable payoff spread. The report links comparison.json and, when generated, stability.json. Underflow spreads explain why a zero displayed amount can retain a positive difference. Exit zero still means completed execution, including correctly disclosed quality warnings.

The retained v0.22.0 mesh validator compares frozen reports after omitting only the revised legacy residual and the two added diagnostic objects. All other old fields, including controls, payoffs, policies and scenario comparisons, remain checked; the frozen source records are unchanged. See docs/v0230_acceptance.md.


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

## Validation portability (CI revision, 2026-10-22)

The public numerical API is unchanged. Validation tooling separates ENTRYSIGNAL_STRICT_REPLAY=1 from the portable scientific contract in scripts/validation_portability.py. Portable frozen projections use relative tolerance 2e-11 for nonzero same-sign scientific values and 2e-7 for nonzero same-sign controls; no constant absolute payoff floor is added and zero/sign changes reject. Configured domains and independent 200/400-digit or exact rational original-input payoff evaluations are checked separately. A displayed net payoff can inherit gross-component rounding, bounded by 64 ULPs of an independently computed gross component; economic comparison signs and tie bands are checked from the original-input references rather than displayed subtraction. Comparator trace records may appear in another order, but every retained record is checked for amount, sign and tie-band relation. Control-dependent residuals and execution work are validated at the actual new controls, rather than equated to an old execution trace. Strict replay keeps original-field equality. The validation outputs record the helper source hash and selected policy. This is not a global or empirical certificate.
