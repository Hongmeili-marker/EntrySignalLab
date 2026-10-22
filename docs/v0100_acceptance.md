# v0.10.0 audit acceptance

The six findings in the unchanged v0.9.0 strict audit are linked to concrete production changes and executable acceptance. The original report, probes and evidence are under audit/v0.9.0. The complete baseline SHA-256 and report hash are in baseline_identity.json there.

| Finding | Production change | Acceptance evidence |
|---|---|---|
| R01 task drift on resume | workflow.prepare_sweep records normalized ordered axes and generator version; the existing batch recipe binds metadata independently of config | Empty, partial and full config; changed values/order; serial/two workers; unchanged output on refusal; original prefix recovery |
| R02 quantile overflow | sampling.linear_quantiles uses bounded opposite-sign interpolation | 42 independent Decimal reference values; all four real finite-payoff summaries; real CLI and complete-prefix resume |
| R03 demand underflow | model.demand combines log weights, growth and elapsed time before final conversion | Four independent 200-digit Decimal stocks; revenue integral, conservation, scalar/array correspondence and true overflow regressions |
| R04 correlated preflight | SamplingPlan proves equality only for identical marginals and exact identical rho=1 rows; v2 aliases those latent values | Strict H=T and explicit le/ge; independent/near-perfect/different-marginal conservative rejection; singular three-variable and key-order replay |
| R05 nested directories | DirectoryLock coordinates active OS leases and existing experiment markers before output creation; every CLI output command holds a lease | Parent-first, child-first, simultaneous and sibling process races; finished trees, symlinks and all CLI output types; previous kill/fork tests retained |
| R06 confidence boundary | Wilson normal quantile uses the smaller tail probability | Maximal binary64 confidence below one; default 95%; tiny confidence, boundary counts and empty denominator |

The unit/workflow suite adds 44 tests, bringing the total to 318. The independent scripts/validate_v0100.py records 55 checks, 42 Decimal quantiles, four Decimal demand values and four actual process races. It does not import the test oracle. Existing independent validators remain separate. Use the installed current wheel, not a historical wheel from audit/:

```sh
python scripts/run_tests.py --out NEW_TEST_DIRECTORY
python scripts/validate_v0100.py --out NEW_ACCEPTANCE_DIRECTORY
python scripts/reproduce.py --out NEW_EXPERIMENT_DIRECTORY
```

The release contract lists 26 experiments and twelve validators. A fresh isolated numerical environment executes them; publication generators consume and verify their receipts. Final checks require source/wheel/installed module byte correspondence. The release gate has separate missing-input and changed-input probes. Page inspection and standalone TeX compilation address document layout and portability separately from numerical evidence.

The support boundary is explicit. Prepared factories must match their metadata. Directory coordination requires cooperating same-user processes with a shared local temporary namespace and supported advisory locks; mixed old hierarchy protocols and network storage are not covered. Conservative copula preflight does not prove arbitrary joint inequalities. Linear quantiles keep the prior statistical definition and all finite cases. The v2 singular-latent normalization is versioned; old checkpoints cannot cross software/source/runtime identity. Local execution is Linux only; configured CI is not remote execution evidence. The model remains synthetic conditional scenario analysis.
