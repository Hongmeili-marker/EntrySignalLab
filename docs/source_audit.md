# Source manuscript audit

The source is the user-supplied PDF titled *First-Mover and Late-Mover Advantages in the AI Deployment under Platform Preannouncement Behavior*. Source page numbers below are the page labels printed in the manuscript, not the physical PDF indices. The release records a SHA-256 identity in `source_identity.json`. Author information, publication DOI and a public source URL were not present in the project inputs. The PDF is not redistributed in the software package.

For readable transcription, s denotes the source consumer growth rate, phi its network parameter, H its rapid-growth end and tau its deployment lag. The source uses T=1, equal qualities, unit consumer-stock revenue coefficient 1/4 and no explicit cost terms.

## Printed candidates

The isolated audit records these expressions exactly as visually checked in the supplied version:

* RF intensity: [4 + 2*s*phi*H - s*phi*H^2] / [phi*H*(H-2)], printed page 12.
* RL delay: 1/(s*phi), printed page 14.
* RF/RL source prose and the appendix assert a positive RL delay derivative; the printed delay instead implies -1/(s^2*phi), pages 14 and 26.
* DF/DL delay: [sqrt(4 + 4*s*phi + (s*phi)^2*H*(2-H)) - 2] / (s*phi), pages 15-16.
* RL printed net/gross payoff: [1 + 2*s*phi + (s*phi)^2*H*(2-H)] / (8*s*phi^2), page 14.
* Printed equation 15 at tau=0 gives -s*H^2/16, while independent integration of the stated DF demand gives s*H*(2-H)/16, page 15.

At s=0.1, phi=0.85 and H=0.3, the RF candidate is -9.3272203, the RL lag is 11.7647059, and the DF/DL lag is 0.9900100. The admissible lag is [0,0.3]. The candidate RL payoff is 2.0305965, exceeding the total market revenue bound 0.006375 implied by the stated nonnegative demand trajectories. Equation 15 at zero lag gives -0.0005625, while demand integration gives 0.0031875. These are consistency checks on this supplied version, not findings about an author's intent.

## Well-posedness and interpretation

For fixed 0 < tau < H with s, phi and margin_x positive, the source RL payoff strictly increases with delta when no announcement cost is present. Thus a finite announcement optimum needs a cap or a cost. Without announcement, the follower's source payoff is proportional to (H-tau)*(2-H-tau)/(2+s*phi*tau), which decreases on its admissible interval for H<=1; its legal optimum includes tau=0. Selecting a stationary root outside the feasible domain does not solve that constrained problem.

The source's four scenario payoff ranking alone does not specify both firms' complete action and deviation conditions. This release therefore makes no equilibrium claim. It retains the four explicit demand/share equations as its operational reference and adds separate, identified synthetic cost and bound assumptions. Source printed candidates never enter operational optimization.

Potential typographical corrections require author confirmation. The software reports discrepancies and independently recomputes specified integrals; it does not claim to have repaired the original article's economic theory.


## Numerical range

Finite positive inputs can make the printed candidate expressions unrepresentable or make intermediate products underflow. The diagnostic reports a controlled range error instead of a division traceback or nonfinite JSON. Operational reproduction records an explicit skipped-source-diagnostic status and reason while keeping demand calculations separate.

## Analytic identity decision

Version 0.17.0 corrects the fixed absolute 1e-12 identity test. On the admitted source domain, the two DF expressions differ by sH/8>0 for every positive s and H. DF_INTEGRAL_IDENTITY therefore returns pass=false from this analytic contradiction, including when the printed expression rounds to zero. The returned numerical values are descriptions, not the basis of the identity decision. decision_basis, exact_difference, normalized_discrepancy and numerical_values_are_descriptive record that distinction. The normalized discrepancy is 2/(2-H), relative to the demand integral, and has no growth-scale floor. Source candidate range errors still use the controlled numerical-range path.

For example, growth=1e-11 and H=0.3 give 3.1875e-13 from demand and approximately -5.625e-14 from the printed expression. Their absolute difference is below 1e-12 but they are structurally inconsistent. This diagnostic remains isolated from operational payoff and optimization; the original article is not silently rewritten.


## v0.18.0 RL market revenue bound

For k=s*network, P-B=s*(1/k**2+2/k)/8>0 on the admitted source domain. RL_REVENUE_BOUND therefore records an analytic failure even if descriptive P and B round equally. Printed candidate rational arithmetic and guarded positive-radical evaluation avoid intermediate binary64 overflow. candidate_representations and observed_representation/bound_representation distinguish genuine final underflow; truly unrepresentable requested candidate values still raise controlled range errors. The ordinary output fields and six check IDs remain. See docs/v0180_acceptance.md.
