# Related software and scope

This is a capability comparison, not a performance experiment across different problems. Official project documentation was checked on 2026-10-10.

| Capability | EntrySignalLab 0.16.0 | SciPy optimization | Gambit |
|---|---|---|---|
| Representation | Specified continuous entry model | User functions and bounds | Finite strategic/extensive games |
| Controls | Profiles intensity and searches delay | General scalar/vector solvers | Continuous models require a separately defined finite representation |
| Equilibrium | Not implemented | No built-in game for these firms | Pure/mixed Nash tools |
| Attainment interpretation | Fixed-lag and joint-supremum statuses | Application defines interpretation | Finite-game scope differs from unbounded continuous intensity |
| Demand accounting | Event integration and conserved stock | Application supplies equations | Application supplies payoff/game model |
| Records | Paired draws, sweeps, plot controls and hashes | Application supplies workflow | Separate game analysis workflow |

SciPy is a dependency. Gambit's finite-game scope is complementary; its equilibrium outputs are not a direct benchmark without specified discretization and players' actions. The toolkit adds an executable research contract, interpretation states and experiment records, not a general optimizer or demonstrated external adoption.

Sources: https://docs.scipy.org/doc/scipy/reference/optimize.html and https://www.gambit-project.org/ .
