# v0.11.0 acceptance map

> Metadata status updated 2026-10-22: Hongmei Li and the contact/affiliation are recorded in CITATION.cff; the public source repository is https://github.com/Hongmeili-marker/EntrySignalLab. Any pending-authorship or pending-repository wording below describes the historical validation stage. The current upload wheel has refreshed metadata and unchanged runtime modules; original whole-wheel hashes remain historical. Versioned archival links and the original source bibliography still require completion.

| Audit | Repair | Executable acceptance |
|---|---|---|
| A01 | Normalize NumPy counts; reciprocal arithmetic | 25 independent Decimal Wilson cases, confidence/empty/huge-count checks |
| A02 | Required model-owned validate_solution callback | Bounds/cap/fixed-rival rejection, custom-model semantics, valid controls and objective checks |
| A03 | Preserve implicit upper bound | None/explicit/roundtrip, three time factors, scaled sweep/uncertainty and payoff invariance |
| A04 | Validate original complex input before cast | Complex scalar/vector/matrix/object rejection; real shape and domain controls |
| A05 | Exact rational endpoint interpolation; one rounding | 77 independent Decimal values; actual four-scenario tiny-payoff API/CLI and interrupted recovery |
| A06 | Explicit quality status and partitioned counts | Unattained, all-pass, actual failed check, missing diagnostics and excluded configuration failures |

`scripts/validate_v0110.py --out NEW_DIRECTORY` must run against the installed wheel. Fifty-five dedicated regression tests supplement the validator. Current release evidence is regenerated, including the prior twelve validators. Exact quantile interpolation uses the computed binary64 h=(n-1)*q and fractional part, not an exact-real rank. For endpoint arithmetic, Fraction and the 1200-digit Decimal reference are independent. Custom validators can themselves be wrong; the interface cannot prove external scientific correctness. All executed evidence is local Linux; authors remain blank.
