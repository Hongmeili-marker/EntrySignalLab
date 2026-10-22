# EntrySignalLab

Current v0.25.0 acceptance: canonical typed profiler inputs, actual local probe records and explicit displayed-payoff precision notices. See docs/v0250_acceptance.md; generated counts are in docs/api.md.
EntrySignalLab is a research toolkit for preannouncement and market-entry timing. It evaluates four conditional scenarios, integrates piecewise demand, profiles announcement intensity, searches a bounded follower delay, and saves reproducible experiment records. Version 0.25.0 uses Python, NumPy, SciPy and Matplotlib under the MIT license.

## Install and first run

The package declares Python >=3.10 with compatible dependencies. The locked scientific environment was executed on Python 3.12.14; those pins require Python >=3.11. This CI revision also passed the full local Linux test suite on Python 3.10.22 with minimum dependencies and Python 3.13.16 with newer dependencies; native Windows/macOS results require the new remote matrix. Use a virtual environment. From this directory:

```sh
python -m pip install .
entrysignal reproduce --config examples/product_launch.json --out results/first_run
entrysignal verify results/first_run
```

Open `results/first_run/report.html` in a browser. No server, account, API key or external data is required. The report contains the conditional optima, consumer trajectories and follower payoff surface. CSV, JSON, PNG, SVG and PDF outputs accompany it. Existing nonempty output directories are preserved; choose a new output path for another run.

## What the four scenarios mean

| Code | Object platform x | Control of deployment delay |
|---|---|---|
| RF | Announces and enters first at time 0 | Rival delay is supplied and held fixed; x chooses intensity |
| RL | Announces and follows a rival entering at 0 | x chooses delay and intensity |
| DF | Does not announce and enters first at 0 | Rival delay is supplied and held fixed |
| DL | Does not announce and follows a rival entering at 0 | x chooses delay |

These are conditional scenarios. Their payoff ranking is not a Nash equilibrium, a mixed-strategy equilibrium, or an empirical prediction. When delay is 0, entry is simultaneous even though the selected scenario label retains its F/L suffix. A zero-payoff non-entry reference is reported separately: the best entry scenario may still lose money.

## Source model and extensions

The supplied manuscript *First-Mover and Late-Mover Advantages in the AI Deployment under Platform Preannouncement Behavior* provides the motivating demand equations. Several printed optimal candidates violate its own domain or derivative conditions. The audit command reproduces six explicit checks; its printed formulae are isolated from operational optimization. See `docs/source_audit.md` for the transcription and provenance.

Operational revenues come from independent integration of the four demand trajectories. The synthetic product-launch example adds a quadratic announcement cost, an exponentially declining deployment cost and explicit intensity bounds. Quality ratios, per-consumer margins, discounting and the horizon are configurable. These additions are identified as model extensions. They are not claimed to reproduce the source manuscript's optimum or to estimate a real firm's behavior.

## Commands

```sh
entrysignal audit --config examples/source_baseline.json --out results/audit
entrysignal evaluate --config examples/source_baseline.json --strategy DF --delay 0
entrysignal optimize --config examples/unbounded_announcement.json --out results/diagnostic
entrysignal sweep --config examples/cost_sensitivity.json --out results/sensitivity
entrysignal sweep --config examples/strategy_regions.json --out results/regions
entrysignal uncertainty --config examples/uncertainty.json --out results/uncertainty
entrysignal benchmark --out results/benchmark
python scripts/reproduce.py --out results/all
python -m unittest discover -s tests -v
```

## API example

```python
from entrysignallab import ModelParams, DecisionBounds, optimize, compare

model = ModelParams(announcement_cost=0.0002,
                    deployment_cost=0.012, learning_rate=12.0)
bounds = DecisionBounds(announcement_upper=2.0)
result = optimize(model, "RL", bounds)
comparison = compare(model, bounds, rival_delay=0.15)
print(result["delay"], result["announcement"], result["payoff"])
print(comparison["preferred_with_outside_option"])
```

See `docs/model_contract.md`, `docs/api.md` and the executable notebook in `examples/` before changing assumptions.

## Numerical status and reproducibility

The intensity subproblem is concave and solved by derivative bracketing or an explicit bound. Delay optimization scouts the interval, refines both edge intervals and every detected local maximum in normalized coordinates, and compares endpoints. It returns a numerical candidate, not a global certificate. Intensity stationarity diagnostics and the actual local probe ledger accompany the result. The legacy delay residual is nullable; a passed increment after promotion does not assess the new final neighborhood. Scouting density and tolerances are user-visible. A vanishing growth rate, zero network effect or simultaneous entry may yield nonunique intensities.

With no cap or announcement cost, RF at an effective fixed lag reports `no_finite_announcement_optimum`. RL evaluates its joint delay envelope: it can return `attained_joint_optimum` at maturity, or `no_finite_joint_optimum` with a reported supremum and null maximizing controls. The right limit at simultaneous entry is not treated as attained. See `docs/joint_envelope.md`. All-scenario ranking is withheld if any scenario lacks a finite result. The manifest records configuration, versions, seed, hardware observations and source/artifact hashes. `verify` checks integrity, not scientific correctness or authorship. Scientific values and seeded draws can be reproduced; timestamps and figure metadata can differ.

Positive announcement costs are profiled in log intensity with checked root convergence. Unrepresentable numerical scales raise a controlled error; accepting a finite parameter does not promise all intermediate quantities fit floating point. The CLI exits 2 with a diagnostic on numerical failure. Flat-delay flags require a positive-width admissible interval and an analytically constant objective.

Figures record their controls in `plot_settings.json` and the HTML report. Reference intensity defaults to the smaller of 0.2 and the configured cap. An unbounded optimizer remains unbounded when its surface is displayed over a recorded finite window. Optional configuration: `"plot": {"announcement": 0.1, "surface_announcement_max": 1.0}`; explicitly infeasible plot settings are rejected.

## Validation and benchmarks

The current CI portability revision includes 917 unit/workflow tests (907 original tests and 10 validation-policy counterexamples), 3,200 independent revenue comparisons, 120 independently optimized follower results, 80 independent joint-envelope comparisons, and three optimizer methods on four identical bounded RL cases. Benchmark timing is warm and in-process; import, plotting and shared setup are excluded. The vectorized grid is faster on these small cases; no universal speed claim is made. Sixty-one experiment directories and the SoftwareX manuscript are supplied in the complete release. Execute `scripts/validate_release.py --out NEW_DIRECTORY` and `scripts/validate_envelope.py --out ANOTHER_NEW_DIRECTORY` against the installed wheel. The recorded dependency lock is `requirements-lock.txt` and has NumPy, SciPy and contourpy pins declaring Python >=3.11; the original frozen release was executed on Python 3.12. This CI revision additionally executes the local Linux suite on Python 3.10 with minimum dependencies and Python 3.13 with newer dependencies; see the recorded revision evidence.

`examples/discounted_quality.json` changes quality, discounting and the horizon. `examples/joint_boundary.json` reproduces the corrected joint-attainment case. The public `rescale_experiment` API preserves payoff meaning for representable unit changes and rejects positive underflow; `scripts/unit_invariance.py` demonstrates it. These are synthetic reuse checks, not empirical applications.

Execution has been verified on the Linux environment recorded in the shipped manifests. Other supported Python environments can run the package; Windows and macOS executions are not claimed as tested. CI configuration is included for future automated runs and does not represent a remotely executed CI result.

## Authors

**Hongmei Li**  
School of Medical Information Engineering, Shenyang Medical College, Shenyang, China  
Email: [Hongmeili@symc.edu.cn](mailto:Hongmeili@symc.edu.cn)

## Citation, support and publication status

A populated `CITATION.cff` provides human author details for citation metadata. The public source repository is [https://github.com/Hongmeili-marker/EntrySignalLab](https://github.com/Hongmeili-marker/EntrySignalLab). A versioned GitHub Release and an archival DOI are not yet assigned. Support contact: Hongmei Li (Hongmeili@symc.edu.cn). The accompanying SoftwareX manuscript is a complete technical draft; its submission metadata must be completed before journal submission. See the release readiness document in the complete bundle. No external adoption, downloads, citations or market validation are claimed.

## Submission documentation revision

The frozen v0.25.0 release passed 907 tests, 28 validators and 61 experiments on Linux/Python 3.12.14. The original specialized v0.25.0 validator recorded 4217 checks. The current CI portability revision updates validation tooling and documentation; its actual counts are recorded with the new outputs. All fourteen runtime modules, the dependency locks and examples retain their verified standalone v0.25.0 bytes. Tests and validators have been revised for portable scientific checks and a separate exact-replay mode. The wheel in this upload package is rebuilt from those unchanged runtime modules to include the supplied author and public repository metadata. Original whole-wheel hashes and historical receipts identify the original frozen distribution, rather than this metadata revision.

Install `dist/entrysignallab-0.25.0-py3-none-any.whl` from this version. See `QUICKSTART.md` for a complete launch experiment and `RELEASE_CHECKLIST.md` for publication metadata and permanent links still required. Historical audit narratives are available in the original complete release, rather than mixed into the current quickstart.

## CI portability revision

The compatibility matrix retains Windows, macOS, Python 3.12/3.13 and the Python 3.10 minimum-dependency job. A separate Linux/Python 3.12 job installs requirements-lock.txt and sets ENTRYSIGNAL_STRICT_REPLAY=1 for exact frozen replay. Other environments use scripts/validation_portability.py: exact categorical decisions, no payoff sign or zero/nonzero waiver, declared numerical/control tolerances, independent original-input event integrals and comparator sign/band/amount checks. Execution counts and sorting-comparator call order are not cross-interpreter scientific invariants. Actual probe ledgers and derivative checks remain independently tested. Windows lock inventories retain file identity, size and modification-time checks without trying to read a byte that the OS deliberately locks.

See CI_FIX_NOTES_zh.md and docs/ci_portability_validation.json for the executed local checks. Uploading this source does not establish a successful remote matrix; inspect the new Actions run before making that claim. Numerical model code is unchanged.
