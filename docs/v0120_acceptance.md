# v0.12.0 acceptance map

| Audit | Repair | Executable acceptance |
|---|---|---|
| A01 | Immutable committed prefix and checked contiguous stream | 32 invalid serial/process/recovery sequences; full/suffix/empty normal recovery; original committed rows retained |
| A02 | Native numeric bounds and boolean diagnostics | float32/64 payoff tolerances, JSON, uncertainty, serial/process checkpoint recovery; explicit pass/fail and absent checks |
| A03 | Domain checks on binary64 after controlled conversion | Fraction, longdouble, huge integers, zero, representable minimum subnormal, bounds and unit factors |
| A04 | Candidate/attained/unattained schemas with model-owned semantics | Contradictory, unknown, omitted and null states; default false-nonexistence guard; custom open model and literal-True callback guard |
| A05 | Integer-scale Decimal fallback for subnormal reciprocals | 140 independent 1200-digit interval values; zero/full/near-full counts, confidence extremes, 10**325 counterexample and 10**10000 totals |

Run scripts/validate_v0120.py against the installed current wheel and a fresh output directory. Fifty-eight regression tests supplement its 89 checks. The validator launches real process workers and records original committed rows. All previous validators and scientific experiments are retained. Mathematical model/sampling definitions are unchanged; normalization and schema compatibility rules are in docs/api.md. Model-specific null-result cross-checks are not proofs for arbitrary extensions. Actual evidence is local Linux, with blank authors.
