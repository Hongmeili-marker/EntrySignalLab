"""Isolated source-formula diagnostics. Never used as solver objectives. MIT License."""
from math import isfinite
from fractions import Fraction
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from .model import ModelParams, revenues, payoff

def _source_delay(k,h):
    """Positive rationalized radical, without finite-range intermediates."""
    a=4+4*k+k*k*h*(2-h);numerator=4+k*h*(2-h)
    previous=None
    for precision in (80,160,320):
        with localcontext() as ctx:
            ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
            convert=lambda x:Decimal(x.numerator)/Decimal(x.denominator)
            result=float(convert(numerator)/(convert(a).sqrt()+2))
        if result==previous:return result
        previous=result
    raise ValueError('printed source delay is unresolved at 320 digits')

def source_audit(p=None):
    p = p or ModelParams()
    if not (p.horizon==1 and p.quality_ratio==1 and p.margin_x==.25 and p.margin_y==.25 and p.discount==0 and p.announcement_cost==0 and p.deployment_cost==0):
        raise ValueError("source audit requires the source assumptions T=1, w=1, margins=.25, zero discount and costs")
    s, f, h = p.growth, p.network, p.growth_end
    if s<=0 or f<=0 or h<=0:
        raise ValueError("printed source candidates are singular at zero growth, network or growth_end; use the demand model instead")
    try:
        S,F,H=map(Fraction,(s,f,h));k=S*F
        exact={'announcement_RF':(4+k*H*(2-H))/(F*H*(H-2)),
               'delay_RL':1/k,'announcement_RL':S*(3+k*k*H*(2-H)+4*k)/(2*(1+k)),
               'payoff_RL':S*(1/k**2+2/k+H*(2-H))/8,
               'growth_derivative':-1/(S*S*F)}
        values={name:float(value) for name,value in exact.items()}
        delta_rf=values['announcement_RF'];delay_rl=values['delay_RL']
        delta_rl=values['announcement_RL'];profit_rl=values['payoff_RL']
        growth_derivative=values['growth_derivative'];delay_d=_source_delay(k,H)
    except (ZeroDivisionError,OverflowError):
        raise ValueError('printed source formulae exceed floating-point range; use operational demand calculations or rescale inputs') from None
    if not all(isfinite(v) for v in [delta_rf,delay_d,delay_rl,delta_rl,profit_rl,growth_derivative]):
        raise ValueError('printed source formulae exceed floating-point range; use operational demand calculations or rescale inputs')
    demand_df_at_zero = revenues(p,"DF",0)[0]
    printed_df_at_zero = float(-S*H*H/16)
    bound_exact=S*H*(2-H)/8;bound=float(bound_exact)
    representations={name:'underflow' if value!=0 and values[name]==0 else 'finite' for name,value in exact.items()}
    return {"mode": "source_formula_audit", "assumptions": {"growth":s,"network":f,"growth_end":h,"horizon":1},
            "source_locations": "Printed manuscript pages 12-16 and 26; equations 11-18; propositions 1-4",
            "printed_candidates": {"announcement_RF":delta_rf,"delay_RL":delay_rl,"announcement_RL":delta_rl,"delay_DF_DL":delay_d,"payoff_RL":profit_rl},
            "candidate_representations":{**representations,'delay_DF_DL':'finite'},
            "checks": [
                {"id":"RF_INTENSITY_DOMAIN","pass":delta_rf>=0,"observed":delta_rf,"required":"announcement >= 0","source_page":12},
                {"id":"RL_DELAY_DOMAIN","pass":0<=delay_rl<=h,"observed":delay_rl,"required":"0 <= delay <= growth_end","source_page":14},
                {"id":"DF_DL_DELAY_DOMAIN","pass":0<=delay_d<=h,"observed":delay_d,"required":"0 <= delay <= growth_end","source_pages":[15,16]},
                {"id":"RL_DELAY_DERIVATIVE","pass":False,"observed":growth_derivative,"required":"printed proposition asserts a positive derivative; printed candidate implies a negative derivative","source_pages":[14,26]},
                # The guarded source domain has s>0 and 0<h<=1. The exact
                # difference is s*h/8>0, including when a displayed value
                # underflows. An absolute numerical floor cannot prove identity.
                {"id":"DF_INTEGRAL_IDENTITY","pass":False,
                 "from_demand":demand_df_at_zero,"from_printed_eq15":printed_df_at_zero,
                 "decision_basis":"analytic_nonidentity",
                 "exact_difference":"growth * growth_end / 8 > 0",
                 "normalized_discrepancy":2/(2-h),
                 "numerical_values_are_descriptive":True,"source_page":15},
                {"id":"RL_REVENUE_BOUND","pass":False,"observed":profit_rl,"market_revenue_bound":bound,
                 "decision_basis":"analytic_positive_excess",
                 "exact_difference":"growth * (1/(growth*network)**2 + 2/(growth*network)) / 8 > 0",
                 "numerical_values_are_descriptive":True,
                 "observed_representation":representations['payoff_RL'],
                 "bound_representation":'underflow' if bound_exact!=0 and bound==0 else 'finite',
                 "source_page":14}],
            "interpretation": "Flags refer to this supplied manuscript version. They do not infer author intent or automatically correct printed formulae. Printed candidates are excluded from operational optimization."}
