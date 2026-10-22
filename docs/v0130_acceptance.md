# v0.13.0 acceptance map

| Audit | Repair | Executable acceptance |
|---|---|---|
| A01 | Native copied payoff values before comparison | Seven dtypes, Decimal rankings/gaps, custom optimizer, JSON, input preservation and true binary64 overflow |
| A02 | Checked JSON floating-literal conversion | Eight actual CLI rejections before directory creation; exact zero, minimum subnormal, integer/string, duplicate/nonfinite controls |
| A03 | Shape-preserving checked real arrays | Nine wide-type underflow cases, invalid types, exact zero, integers, empty arrays and representable subnormal controls |
| A04 | Use normalized mathematical scalar controls | Twelve Fraction delay/shape configurations; 56 Decimal stock values; 36 Decimal grid-integral values |
| A05 | Model-owned state, envelope and position checks | Seven original metadata mutations; missing fields, reference domain, tiny scales, user-tolerance independence, equal locations and custom models |

scripts/validate_v0130.py records 152 checks. Sixty-six regression tests supplement it. All previous tests and validators remain. Default model metadata tolerance is relative 1e-10 with an eight-ULP absolute allowance; it is independent of user quality tolerances and not a proof of arbitrary-model optimality. JSON integer parsing and mathematical model/sampler definitions are unchanged. Frozen originals are in audit/v0.12.0. Actual execution remains local Linux, with blank authors.
