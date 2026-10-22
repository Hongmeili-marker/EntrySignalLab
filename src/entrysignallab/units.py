"""Preserve the model when changing time and consumer units. MIT License."""
from dataclasses import replace
from math import frexp, ldexp
from fractions import Fraction
from .model import finite_number

UNIT_CONVERSION_RTOL=1e-12

def _scaled(value, name, *factors):
    """Multiply powers using binary exponents; never silently remove a positive term."""
    if value == 0:
        return 0.0
    mantissa, exponent = frexp(value)
    for factor, power in factors:
        part, scale = frexp(factor)
        mantissa *= part**power
        mantissa, shift = frexp(mantissa)
        exponent += power*scale+shift
    try:
        answer = ldexp(mantissa, exponent)
    except OverflowError:
        raise ValueError(f'unit conversion makes {name} exceed floating-point range; choose smaller factors') from None
    if answer == 0:
        raise ValueError(f'unit conversion makes positive {name} underflow to zero; choose different factors')
    exact=Fraction.from_float(value)
    for factor,power in factors:exact*=Fraction.from_float(factor)**power
    if abs(Fraction.from_float(answer)-exact)>abs(exact)*Fraction.from_float(UNIT_CONVERSION_RTOL):
        raise ValueError(f'unit conversion loses relative precision in {name}; choose different factors')
    return answer


def rescale_experiment(params,bounds,rival_delay,time_factor=1.,consumer_factor=1.):
    """Return (params, bounds, rival_delay) for t'=a*t and D'=b*D.

    Payoff units stay fixed. Transform an intensity by b/a and a delay by a.
    This is a representation change, not a new market or calibration.
    A positive term outside floating-point range is rejected, not set to zero.
    """
    a=finite_number(time_factor,'time_factor',positive=True)
    b=finite_number(consumer_factor,'consumer_factor',positive=True)
    lo,hi=bounds.validate(params)
    rival_delay=finite_number(rival_delay,'rival_delay',minimum=0)
    if rival_delay>params.growth_end: raise ValueError('rival_delay exceeds growth_end')
    s=lambda value,name,*powers:_scaled(value,name,*powers)
    p=replace(params,growth=s(params.growth,'growth',(b,1),(a,-1)),network=s(params.network,'network',(b,-1)),
              growth_end=s(params.growth_end,'growth_end',(a,1)),horizon=s(params.horizon,'horizon',(a,1)),
              margin_x=s(params.margin_x,'margin_x',(a,-1),(b,-1)),margin_y=s(params.margin_y,'margin_y',(a,-1),(b,-1)),
              discount=s(params.discount,'discount',(a,-1)),learning_rate=s(params.learning_rate,'learning_rate',(a,-1)),
              announcement_cost=s(params.announcement_cost,'announcement_cost',(a,2),(b,-2)))
    q=replace(bounds,delay_lower=s(lo,'delay_lower',(a,1)),delay_upper=None if bounds.delay_upper is None else s(bounds.delay_upper,'delay_upper',(a,1)),
              announcement_upper=None if bounds.announcement_upper is None else s(bounds.announcement_upper,'announcement_upper',(b,1),(a,-1)),
              tolerance=s(bounds.tolerance,'tolerance',(a,1)))
    qlo,qhi=q.validate(p)
    if lo < hi and qlo == qhi:
        raise ValueError('unit conversion collapses a positive-width delay interval; choose different factors')
    converted_rival=s(rival_delay,'rival_delay',(a,1))
    times=[('delay_lower',lo,qlo),('delay_upper',hi,qhi),
           ('rival_delay',rival_delay,converted_rival),
           ('growth_end',params.growth_end,p.growth_end),('horizon',params.horizon,p.horizon)]
    for name,x,y in times:
        for other,u,v in times:
            if x<u and y>=v:
                raise ValueError(f'unit conversion collapses positive time separation between {name} and {other}; choose different factors')
    return p,q,converted_rival
