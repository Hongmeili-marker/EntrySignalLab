# EntrySignalLab launch analysis quickstart

This example compares four conditional entry scenarios and a zero-payoff non-entry reference. Inputs are synthetic and normalized. It does not predict an observed firm's behavior or solve a game equilibrium.

## Install the frozen release

Use a fresh virtual environment. The executed scientific environment is Linux/Python 3.12.14. The package declares Python >=3.10 with compatible dependencies; requirements-lock.txt has pins requiring Python >=3.11, and that minimum-version alternative remains unverified. From the extracted EntrySignalLab-0.25.0 directory:

```sh
python -m venv .venv
```

Activate the environment using `.venv/bin/activate` on a POSIX shell or `.venv\Scripts\Activate.ps1` in PowerShell. Then run:

```sh
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps dist/entrysignallab-0.25.0-py3-none-any.whl
entrysignal --help
```

Dependency installation normally needs internet access. After installation, the supplied example uses local synthetic inputs and requires no account or API key. These commands describe a new installation; the original release's isolated installation test provisioned locked dependencies from available distributions. No fresh internet download of dependencies is claimed for this preparation.

## Run and verify

```sh
entrysignal reproduce --config examples/product_launch.json --out results/launch
entrysignal verify results/launch --check-source
```

Use an unused output directory. Open `results/launch/report.html`. Inspect `config.json` for all normalized defaults, `optima.csv` for the four candidates and `comparison.json` for the actual ranking and diagnostics. `verify` checks recorded inventory, configuration and hashes; it does not prove numerical validity, authorship or execution.

## Interpret the original run

The configuration supplies growth 0.1, network 0.85, maturity 0.3, announcement cost 0.0002, deployment cost 0.012, learning rate 12, intensity cap 2 and fixed rival lag 0.15. The horizon defaults to 1, both qualities to 1, both stock margins to 0.25 and discount to zero. RF and DF keep rival timing fixed; RL and DL choose the focal delay.

RL returns delay 0.2236463556, intensity 0.3157451131 and payoff -0.0001112132503. Its advantage over DL is about 0.00001038191321. `co_best` is `["RL"]`, while `preferred_with_outside_option` is `["no_entry"]`. All entry scenarios lose money under these assumptions. The full local probe ledger can be expanded in the HTML report and is retained in JSON. Passed local checks do not certify a continuous global optimum.

## Change one assumption

Copy `examples/product_launch.json` to `examples/launch_lower_cost.json`. Change only `params.deployment_cost` from 0.012 to 0.006; an optional label change has no scientific effect. Then run:

```sh
entrysignal reproduce --config examples/launch_lower_cost.json --out results/launch_lower_cost
entrysignal verify results/launch_lower_cost --check-source
```

The same Linux environment gives RL delay 0.1600337641, intensity 0.4324668399 and payoff 0.0004785549858. Both comparison fields now choose RL. This isolates how the assumed deployment cost changes the conditional outcome. It does not establish a market threshold.

## Continue the experiment

Use examples/cost_sensitivity.json for a sweep and examples/uncertainty.json for paired draws. Each output preserves its own configuration. Read docs/model_contract.md before changing accounting, and docs/reproducibility.md before using checkpoints or interpreting Monte Carlo intervals. No new mechanism is validated automatically by changing a parameter or callback.
