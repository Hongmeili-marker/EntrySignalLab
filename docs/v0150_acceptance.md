# v0.15.0 acceptance map

| Audit | Repair | Executable acceptance |
|---|---|---|
| A01 | Compare envelope component differences; guard close ordering | 24 constant-cost cases, 12 independent 120-digit envelopes, two near-equal component cases, actual CLI null/unrankable schema |
| A02 | Zero/sign protection for model-owned envelope metadata | Four original wrong zero/sign states reject; correct null and singleton-maturity controls and signed zero remain valid |
| A03 | Exact rational relative precision and time-separation guards | Two original lossy scale factors reject, 16 independent unit-payoff references and three positive time-separation checks |
| A04 | Bound sample/attempt fields to unsigned 32 bits | 72 unchanged v0.14.0 raw streams, unsupported indices/attempts reject in direct RNG and SamplingPlan, domains recorded |

The new validator has 151 checks and the test suite adds 55 regressions (608 total). Component ordering uses numerical 80/160/320-digit escalation only when logarithmic differences are close; unresolved order rejects. This is not interval or global certification. Unit-conversion fields require relative error <=1e-12 against exact rational transforms and positive configured time separations cannot collapse. indexed-pcg64-v2 remains unchanged for every supported input; metadata declares the new input restriction. All execution claims remain local Linux. Original v0.14.0 audit identities and evidence are sealed under audit/v0.14.0, and the stream test fixture is explicitly bound as a release input.
