# Version 0.18.0 acceptance

This release resolves A09 and A10 from the v0.17.0 audit. Original report, evidence ZIP, original probe, observations and wheel/module identities are frozen under audit/v0.17.0. The current production model is not used as its own numerical reference.

| Finding | Change | Independent acceptance |
|---|---|---|
| A09 net payoff cancellation | Retain the log range path; recompute ill-conditioned net values from original binary64 inputs. Exact rational evaluation when relevant decays are unity; otherwise adaptive Decimal evaluation. Scalar, grid, uncapped RL envelope and default research metadata share the policy. | Original four sign/preference counterexamples, two exact unit transforms, 36 frozen cases, active network/nonzero announcement costs, nonzero discount/learning, tiny rates, genuine final underflow, envelope metadata, actual JSON/HTML/CSV and serial/process cases |
| A10 RL source upper bound | Decide the strictly positive excess analytically; compute printed candidates with exact rational arithmetic and a positive radical guard. Distinguish a genuinely rounded zero from failed arithmetic. | Original three counterexamples, wide-scale candidates checked against independent original expressions, real audit CLI, genuine descriptive underflow and true output-range refusals |

## Net payoff policy

The guard activates when abs(rounded net)/max(rounded revenue, announcement cost, deployment cost) <= 1e-8. Rounded-zero components with nonzero underlying costs also enter the guard, because two individually unrepresentable costs may have a representable sum. Requested gross components must still fit the existing binary64 output contract.

Zero discount and unity relevant deployment decay permit exact Fraction evaluation of the original-input objective and one final binary64 conversion. Other guarded cases use 80, 160, 320, 640 and 1280 Decimal digits. Two successive conversions must agree. A twelve-digit conservative cancellation guard must resolve the result, or a below-half-subnormal-quantum guard must resolve a final rounded zero. Unresolved results raise a controlled ValueError rather than returning a fabricated sign. These are adaptive numerical guards, not rigorous interval error bounds or universal correct-rounding certificates.

The same guarded net policy covers the uncapped RL supremum's value and the default research metadata reevaluation. Existing component-wise envelope ordering, root diagnostics, nonattainment classification, comparison tolerance and withholding of null-result ranking are retained. Arbitrary research extensions retain their own callbacks and objective policies.

Reported revenues remain independently rounded binary64 outputs. A guarded net can therefore differ from subtracting separately rounded displayed components. This is intentional: the original parameters define the objective. Local-quality pass concerns evaluated controls; it is not a guarantee of independent objective accuracy.

## Source diagnostics

Let k=s*network. On the admitted source domain, the printed RL payoff P and market bound B satisfy P-B=s*(1/k**2+2/k)/8>0. RL_REVENUE_BOUND keeps its ID and returns pass=false with decision_basis=analytic_positive_excess, exact_difference and numerical_values_are_descriptive. Scalar magnitudes remain available as descriptive outputs.

Printed rational candidates, the growth derivative, DF expression and market bound are evaluated from exact binary64 rational inputs before final conversion. The DF/DL radical uses 80/160/320-digit stabilization. candidate_representations and the bound/observed representation fields label genuine underflow. A truly unrepresentable requested candidate still raises the existing controlled range error. All six source IDs, source assumptions and separation from operational objectives remain.

## Evidence scope

scripts/validate_v0180.py records exact rational comparisons and independent global Decimal antiderivatives at event times. The latter do not call the operational segmented moments or its small-argument series. Tiny-rate references use 1600 digits. Source candidates use the original rational expressions and a separately evaluated radical. Tests also cover four scenario payoffs, exact unit changes, nonzero costs and default research correspondence.

Actual CLI acceptance includes evaluate, optimize, reproduce, serial/process sweeps, paired uncertainty and source audit. The new fixtures, validator, examples, docs and frozen audit identities are release inputs; changed inputs are rejected by negative release-gate probes. Existing validators and experiments are regenerated for the current installed wheel. Indexed PCG64 streams are unchanged. Execution claims are local Linux; configured remote CI is not an executed remote run. Numerical guarding does not prove global optimization, empirical validity or general correctness for every floating input.
