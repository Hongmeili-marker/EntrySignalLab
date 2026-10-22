"""Portable scientific checks, separate from opt-in exact frozen replay.

Exact replay is retained by ENTRYSIGNAL_STRICT_REPLAY=1. Other environments
check finite numerical values with declared tolerances and independently
evaluate the returned controls. Discrete states, signs, domains and economic
decisions are never made approximately equal.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
from math import isclose, isfinite, ulp
import os
import hashlib
from pathlib import Path

STRICT_REPLAY = os.environ.get('ENTRYSIGNAL_STRICT_REPLAY') == '1'
NUMERIC_RTOL = 2e-11
CONTROL_RTOL = 2e-7


def validation_policy_record():
    return {'mode': 'exact_frozen_replay' if STRICT_REPLAY else 'portable_scientific_contract',
            'numeric_rtol': NUMERIC_RTOL, 'control_rtol': CONTROL_RTOL,
            'gross_component_display_ulps': 64,
            'policy_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
# Search work and the order of sorting comparator calls are implementation
# observations. They are checked within each execution, not across interpreters.
EXECUTION_FIELDS = frozenset({
    'evaluations', 'envelope_evaluations', 'delay_refinement_intervals',
    'delay_refinement_diagnostics', 'search_precision', 'refined_comparisons',
    'local_probe_diagnostics',
})
# These are recomputed from the actual returned controls by the independent
# derivative/probe validators; a different final float has a different residual.
CONTROL_DIAGNOSTICS = frozenset({
    'announcement_stationarity_residual', 'announcement_stationarity_log_residual',
    'announcement_stationarity_scaled_residual',
    'announcement_stationarity_diagnostic',
    'last_probe_improvement', 'last_probe_improvement_diagnostic',
    'probe_improvement_found',
})


def finite_close(actual, expected, rtol=NUMERIC_RTOL):
    """No absolute economic floor, sign reversal or nonzero-to-zero waiver."""
    if not isfinite(actual) or not isfinite(expected):
        return False
    if actual == expected:
        return True
    if actual == 0 or expected == 0 or (actual < 0) != (expected < 0):
        return False
    return isclose(actual, expected, rel_tol=rtol, abs_tol=0.)


def frozen_matches(actual, expected, field=None):
    """Compare a frozen scientific projection, or all bytes in strict mode.

Only explicit execution observations and control-dependent residuals are
excluded from cross-environment snapshots. Their mathematical meaning is
checked against independent values at the new controls, not the old controls.
"""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        keys = set(expected) if STRICT_REPLAY else set(expected) - EXECUTION_FIELDS - CONTROL_DIAGNOSTICS
        return all(k in actual and frozen_matches(actual[k], expected[k], k) for k in keys)
    if isinstance(expected, (list, tuple)):
        return (isinstance(actual, (list, tuple)) and len(actual) == len(expected)
                and all(frozen_matches(a, b, field) for a, b in zip(actual, expected)))
    if isinstance(expected, bool) or expected is None or isinstance(expected, (str, int)):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, float):
        if STRICT_REPLAY:
            return actual == expected
        return (isinstance(actual, float) and finite_close(actual, expected,
                CONTROL_RTOL if field in {'delay', 'announcement', 'supremum_delay'} else NUMERIC_RTOL))
    return actual == expected


def reference_payoff(p, row, digits=400, components=False):
    """Independent original-input event antiderivatives (no production helper)."""
    rational = p.discount == 0 and (p.learning_rate == 0 or p.deployment_cost == 0
                                   or row['strategy'].endswith('F'))
    with localcontext() as ctx:
        ctx.prec = digits
        convert = Fraction if rational else Decimal.from_float
        s, n, H, T, w, m, r, c, C, k, t, d = map(convert, (
            p.growth, p.network, p.growth_end, p.horizon, p.quality_ratio,
            p.margin_x, p.discount, p.announcement_cost, p.deployment_cost,
            p.learning_rate, row['delay'], row['announcement']))
        st = row['strategy']
        if st == 'RF': a, b = 1+n*(s+d)*t, w
        elif st == 'DF': a, b = 1+n*s*t, w
        elif st == 'RL': a, b = 1+n*d*t, w*(1+n*s*t)
        else: a, b = convert(1.), w*(1+n*s*t)
        if rational:
            mass = (H-t)*(2*T-H-t)/2
            lead = t*(2*T-t)/2 if st.endswith('F') else 0
            deployment = C
        else:
            def j0(x): return x if r == 0 else (1-(-r*x).exp())/r
            def j1(x): return x*x/2 if r == 0 else (1-(1+r*x)*(-r*x).exp())/(r*r)
            mass = j1(H)-j1(t)-t*(j0(H)-j0(t))+(H-t)*(j0(T)-j0(H))
            lead = j1(t)+t*(j0(T)-j0(t)) if st.endswith('F') else 0
            deployment = C if st.endswith('F') else C*(-(k+r)*t).exp()
        revenue = m*s*(lead+mass*a/(a+b))
        cost = c*d*d/2
        value = revenue-cost-deployment
        return (value, max(abs(revenue), abs(cost), abs(deployment))) if components else value


def result_matches(p, bounds, rival, actual, expected):
    """Frozen scientific agreement plus configured domain and independent value."""
    if not frozen_matches(actual, expected):
        return False
    if actual.get('payoff') is None:
        return (actual.get('delay') is None and actual.get('announcement') is None
                and actual.get('attainment') == 'not_attained')
    lo, hi = bounds.validate(p)
    t, d = actual['delay'], actual['announcement']
    if not (0 <= t <= p.growth_end and d >= 0): return False
    if actual['strategy'].endswith('L') and not lo <= t <= hi: return False
    if actual['strategy'].endswith('F') and t != rival: return False
    if actual['strategy'].startswith('D') and d != 0: return False
    if bounds.announcement_upper is not None and d > bounds.announcement_upper: return False
    a, b = reference_payoff(p, actual, 200), reference_payoff(p, actual, 400)
    if float(a) != float(b): return False
    if finite_close(actual['payoff'], float(b)):
        return True
    # Displayed net payoffs can inherit gross-component rounding; the model's
    # original-input comparison guards own economic ordering in these cases.
    # Bound that display error in ULPs of an independently computed gross
    # component, not by a constant absolute economic tolerance.
    rounded = float(b)
    if actual['payoff'] == 0 or rounded == 0 or (actual['payoff'] < 0) != (rounded < 0):
        return False
    _, gross = reference_payoff(p, actual, 400, components=True)
    scale = float(gross)
    return isfinite(scale) and abs(actual['payoff']-rounded) <= 64*ulp(scale)


def comparison_evidence_valid(p, report):
    """Check rankings and each recorded comparator's sign/band independently."""
    if not report['all_rankable']:
        return report['co_best'] == report['preferred_with_outside_option'] == []
    with localcontext() as ctx:
        ctx.prec = 400
        def dec(v):
            return Decimal(v.numerator)/Decimal(v.denominator) if isinstance(v, Fraction) else v
        values = {r['strategy']: dec(reference_payoff(p, r)) for r in report['results']}
        values['outside_option'] = Decimal.from_float(report['outside_option_payoff'])
        tol = Decimal.from_float(report['tie_tolerance'])
        best = max(values[r['strategy']] for r in report['results'])
        labels = [r['strategy'] for r in report['results'] if best-values[r['strategy']] <= tol]
        outside = best-values['outside_option']
        preferred = labels if outside > tol else ['no_entry'] if outside < -tol else labels+['no_entry']
        if report['co_best'] != labels or report['preferred_with_outside_option'] != preferred:
            return False
        for record in report.get('comparison_precision', {}).get('refined_comparisons', []):
            if record['left'] not in values or record['right'] not in values:
                return False
            gap = values[record['left']]-values[record['right']]
            sign = (gap > 0)-(gap < 0)
            band = 1 if gap > tol else -1 if gap < -tol else 0
            if record['sign'] != sign or record['tolerance_relation'] != band:
                return False
            rounded = float(gap)
            if isfinite(rounded):
                if record['value'] is None or not finite_close(record['value'], rounded):
                    return False
            elif record['value'] is not None:
                return False
    return True
