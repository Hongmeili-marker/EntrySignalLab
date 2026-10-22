# Version 0.19.0 acceptance

This release addresses A11 and A12 from the v0.18.0 audit. Original report, evidence ZIP, probe, observations, source modules and wheel are frozen under audit/v0.18.0. The original complete release is identified by SHA256 without nesting a second full release archive.

## A11 comparison differences

The default model compares objectives at returned controls. For payoffs a,b and configured absolute tolerance q, the original-input guard triggers when min(abs(a-b),abs(abs(a-b)-q))/max(abs(a),abs(b),q) <= 1e-8. Zero scale or a nonzero subnormal payoff operand also triggers. The heuristic is not a rigorous error bound.

Exact rational coefficients of the common primitive integrals and deployment decays cancel before comparison. If the remaining difference is rational, its sign and membership in the inclusive [-q,q] band are exact. Otherwise the original objective values are reevaluated at 80,160,320,640,1280 Decimal digits. Two successive rounded gap values, signs and tolerance sides must agree; both the sign and distance from the tolerance boundary must exceed a gross-component cancellation guard. A structural exact constant is handled before this guard. An unresolved zero, including one caused by a below-output-range decay cut, is not proof of equality: NumericalError is raised after 1280 digits.

The built-in CachedFirstOptimizer is a default-model implementation and shares the same guarded comparison in both serial and process execution. Arbitrary explicit optimizer callbacks and compare_results retain supplied-float semantics. No callback identity or empirical validity is inferred. This release does not change the announcement profiler, delay search certificate, null-supremum ranking rules, underlying model equations or sampling algorithm.

Gap fields may differ from subtracting separately rounded displayed payoff fields. Diagnostics include decision_basis, precision_digits, sign, tolerance_relation and representation. A true rounded-zero difference is marked underflow with a nonzero original-input sign. A gap outside binary64 magnitude has value=null and a log magnitude, while the decision retains its relation. CSV discloses gap basis and outside gap representation/sign; HTML explains the distinction. The original scalar/grid payoff and envelope guards remain.

## A12 figures

A two-control singleton surface draws one point at the actual announcement/payoff, with the fixed delay/intensity stated. A one-dimensional slice remains a line. Sensitivity series with one finite observation use distinct strategy markers; null values remain gaps and all-null input does not create data. Curves with multiple finite observations retain their lines. No feasible control range is expanded and no synthetic samples are added.

## Independent acceptance

The 32 new regressions cover original positive/negative/zero comparisons, tolerance edges, exact cost translations/units, common discounted-term cancellation, adaptive discounted gaps, subnormal gap sign, controlled unresolved comparisons, external float semantics, null-state withholding and point/slice/null figures.

scripts/validate_v0190.py uses an independently integrated simultaneous-entry objective from exact original binary64 inputs, the retained independent rational scenario transcription, and separately evaluated global antiderivatives at 800/1600 Decimal digits. It does not use production precision helpers as references. The fixed corpus contains 132 comparisons: frozen original observations and 36 boundary cases, 24 far controls, four cost translations, two exact unit changes, tolerance edges, 40 rational and 12 discounted scenario cases, and a genuine final gap underflow. The scenario references evaluate recorded candidate controls; they are not a global optimizer oracle.

Nine figure cases inspect actual coordinates and markers and export 27 PNG/PDF/SVG files. Nine installed-package CLI processes cover evaluate/optimize/reproduce, cached serial/process sweeps, paired uncertainty and controlled refusal/error-record accounting. The new acceptance currently records 654 checks. All required prior validators and experiments are rerun against the current isolated installed wheel, with the 72 frozen indexed-pcg64-v2 streams unchanged. Execution evidence remains local Linux; remote CI is configured only. Finite corpus agreement does not imply general correct rounding, interval certification, continuous global optimality or empirical calibration.
