# Version 0.20.0 audit acceptance

| Finding | Change | Independent evidence |
|---|---|---|
| A13 P3 | Common exponential factoring with exact coefficients and an omitted-tail bound; retain sign and log magnitude before float conversion | 60 frozen boundary cases at 200/400 digits, all four strategies and 108 directed pair comparisons; zero/minimum/default tolerance controls; actual cached serial/process and paired uncertainty CLI |
| A14 P3 | Mark each finite run with one unique coordinate, including repeated vertices and multiple isolated points | Ten artist cases, 30 PNG/PDF/SVG exports, real duplicate-axis sweep and preserved CSV/line vertices |

The scaled comparator cancels shared primitive/cost coefficients exactly, expands remaining primitives into rational exponential coefficients and factors the least exponent. Relative exponent arguments above 100000 are omitted only with an absolute tail bound. This bound joins an adaptive arithmetic/cancellation guard; it does not certify interval enclosure or all-input correct rounding. Ordinary small-discount comparisons retain stable segment moments/series. Maximum precision stays 1280 Decimal digits and requires two matching decisions. Diagnostic basis is scaled_original_input_difference; comparison policy is original_input_gap_guard_v2.

The 15 frozen wrong preferences now agree with independent integrals, and all 24 former refusals in the 60-case corpus now resolve. All corpus cases use zero tie tolerance. The named case has sign -1 and log magnitude approximately -99954.9482981401, despite final binary64 payoff/gap zero. With default positive tolerance 1e-8 it remains a tolerance tie among RL, DL and no_entry; it is not an ordinary default-tolerance preference reversal. The corpus is adversarial, not an estimated real-use error rate.

The former discount=1e308, delay=1 refusal is now explicitly tested as a resolved negative gap. Inherited v0.19.0 tests/validator retain a controlled-refusal check at discount=1e308, delay=H=T=1e308, whose required log diagnostic is unrepresentable. It exits before directory creation in strict CLI and records numerical_error under batch recording. A helper-only tail stress case checks that an omitted tail cannot be silently declared zero; its coefficients deliberately exceed the model-input domain and it is not claimed as an admitted model scenario.

Figures keep every input vertex, mark only zero-extent finite runs, and preserve null breaks. Repeated points are not removed from CSV or case indexing. The isolated-point gap fixture is an explicit plotting API input, while duplicate points are also exercised through actual CLI.

Release tests, all required validators and all experiments must run with the current isolated installed wheel. The frozen 72 indexed-pcg64-v2 streams remain. Original audit report, evidence, probe, observations, wheel and 14 modules are bound under audit/v0.19.0; the prior complete ZIP is identified by hash rather than nested again. Local Linux execution, finite oracle agreement and reviewed page images do not establish remote CI execution, empirical calibration, equilibrium or continuous global optimality.
