"""Piecewise demand and stable discounted integration. MIT License."""
from dataclasses import dataclass, asdict
from math import exp, expm1, isfinite, factorial, log
from numbers import Real
from fractions import Fraction
from functools import lru_cache
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
import numpy as np

STRATEGIES = ("RF", "RL", "DF", "DL")
NET_PAYOFF_GUARD_RATIO = 1e-8

def _rational_net_payoff(p, strategy, delay, announcement, envelope=False):
    """Exact original-binary64 objective when all relevant decays are unity."""
    s,n,h,T,w,m,c,C,t,d=map(Fraction,(p.growth,p.network,p.growth_end,p.horizon,
        p.quality_ratio,p.margin_x,p.announcement_cost,p.deployment_cost,delay,announcement))
    if strategy=='RF':a,b=1+n*(s+d)*t,w
    elif strategy=='DF':a,b=1+n*s*t,w
    elif strategy=='RL':a,b=1+n*d*t,w*(1+n*s*t)
    else:a,b=Fraction(1),w*(1+n*s*t)
    mass=(h-t)*(2*T-h-t)/2
    if envelope:return m*s*mass-C
    leader=t*(2*T-t)/2 if strategy.endswith('F') else 0
    return m*s*(leader+mass*a/(a+b))-c*d*d/2-C

def _decimal_net_payoff(p, strategy, delay, announcement, precision, envelope=False):
    """Recompute positive integral components before the final subtraction."""
    with localcontext() as ctx:
        ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
        s,n,h,T,w,m,r,c,C,k,t,d=map(Decimal.from_float,(p.growth,p.network,
            p.growth_end,p.horizon,p.quality_ratio,p.margin_x,p.discount,
            p.announcement_cost,p.deployment_cost,p.learning_rate,delay,announcement))
        def decay(x):
            # Even the largest finite-input weighted moment cannot recover a
            # binary64 value after exp(-100000). This is an output-range cut.
            return Decimal(0) if x>100000 else (-x).exp()
        def moments(length):
            if length==0:return Decimal(0),Decimal(0)
            if r==0:return length,length*length/2
            x=r*length
            if x<Decimal('.1'):
                a=b=Decimal(0);power=Decimal(1)
                epsilon=Decimal(10)**(-precision-5)
                for j in range(500):
                    u=power/(j+1);v=power/(j+2);a+=u;b+=v
                    if abs(u)<epsilon*abs(a) and abs(v)<epsilon*abs(b):break
                    power*=-x/(j+1)
                else:raise ValueError('net payoff moment series did not converge')
                return length*a,length*length*b
            e=decay(x)
            return (1-e)/r,(1-(1+x)*e)/(r*r)
        def segment(left,right,value,slope):
            if right<=left:return Decimal(0)
            j0,j1=moments(right-left)
            return decay(r*left)*(value*j0+slope*j1)
        if strategy=='RF':a,b=1+n*(s+d)*t,w
        elif strategy=='DF':a,b=1+n*s*t,w
        elif strategy=='RL':a,b=1+n*d*t,w*(1+n*s*t)
        else:a,b=Decimal(1),w*(1+n*s*t)
        mass=segment(t,h,Decimal(0),Decimal(1))+segment(h,T,h-t,Decimal(0))
        lead=segment(Decimal(0),t,Decimal(0),Decimal(1))+segment(t,T,t,Decimal(0)) if strategy.endswith('F') else Decimal(0)
        revenue=m*s*mass if envelope else m*s*(lead+mass*a/(a+b))
        entry=Decimal(0) if strategy.endswith('F') else t
        deployment=C*decay(k*entry+r*entry);announcement_cost=c*d*d/2
        return revenue-announcement_cost-deployment,revenue+announcement_cost+deployment

def _guarded_net_payoff(p, strategy, delay, announcement, revenue, cost, deployment, envelope=False):
    """Keep the log fast path, guarding ill-conditioned final cancellation.

    Rational branches round once. Transcendental branches need two matching
    80/160/320/640/1280-digit results and an unresolved-cancellation guard.
    This is adaptive numerical guarding, not interval certification.
    """
    result=revenue-cost-deployment;scale=max(revenue,cost,deployment)
    if scale and abs(result)/scale>NET_PAYOFF_GUARD_RATIO:return result
    if not scale and p.deployment_cost==0 and (p.announcement_cost==0 or announcement==0):return result
    if p.discount==0 and (p.deployment_cost==0 or p.learning_rate==0 or strategy.endswith('F') or delay==0):
        try:return float(_rational_net_payoff(p,strategy,delay,announcement,envelope))
        except OverflowError:raise ValueError('net payoff exceeds floating-point range; rescale inputs') from None
    previous=None
    for precision in (80,160,320,640,1280):
        value,gross=_decimal_net_payoff(p,strategy,delay,announcement,precision,envelope)
        converted=float(value)
        if not isfinite(converted):raise ValueError('net payoff exceeds floating-point range; rescale inputs')
        with localcontext() as ctx:
            ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
            uncertainty=gross*Decimal(10)**(-precision+12)
            quantum=Decimal.from_float(float.fromhex('0x0.0000000000001p-1022'))/2
            resolved=gross==0 or abs(value)>uncertainty or (converted==0 and abs(value)+uncertainty<quantum)
        if resolved and previous==converted:return converted
        previous=converted if resolved else None
    raise ValueError('net payoff cancellation is unresolved at 1280 digits; change numerical scaling or formulation')


def _objective_signature(p, strategy, delay, announcement):
    """Exact coefficients of common discounted integrals and cost decays.

    Used only to cancel identical terms, not as a floating integral evaluator.
    None denotes a rational constant; J0/J1 are primitives from zero to time.
    """
    s,n,h,T,w,m,r,c,C,k,t,d=map(Fraction,(p.growth,p.network,p.growth_end,
        p.horizon,p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,
        p.deployment_cost,p.learning_rate,delay,announcement))
    terms={}
    def add(key,value):
        terms[key]=terms.get(key,Fraction(0))+value
        if not terms[key]:terms.pop(key)
    def moment(order,time,coefficient):
        if not time:return
        if not r:add(None,coefficient*time**(order+1)/(order+1))
        else:add(('J'+str(order),time),coefficient)
    if strategy=='RF':a,b=1+n*(s+d)*t,w
    elif strategy=='DF':a,b=1+n*s*t,w
    elif strategy=='RL':a,b=1+n*d*t,w*(1+n*s*t)
    else:a,b=Fraction(1),w*(1+n*s*t)
    scale=m*s;share=a/(a+b)
    if strategy.endswith('F'):
        moment(1,t,scale);moment(0,T,scale*t);moment(0,t,-scale*t)
    weighted=scale*share
    moment(1,h,weighted);moment(1,t,-weighted)
    moment(0,h,-weighted*t);moment(0,t,weighted*t)
    moment(0,T,weighted*(h-t));moment(0,h,-weighted*(h-t))
    add(None,-c*d*d/2)
    entry=Fraction(0) if strategy.endswith('F') else t
    exponent=(k+r)*entry
    add(('exp',exponent) if exponent else None,-C)
    return terms


def _gap_diagnostic(value,tolerance,basis,precision=None):
    """Keep decision sign and tolerance relation even outside float range."""
    sign=(value>0)-(value<0)
    relation=1 if value>tolerance else -1 if value < -tolerance else 0
    try:converted=float(value)
    except OverflowError:converted=float('inf') if sign>0 else -float('inf')
    representation='outside_float_range' if not isfinite(converted) else 'underflow' if converted==0 and sign else 'finite'
    if not sign:log_abs=None
    elif isinstance(value,Fraction):log_abs=log(abs(value.numerator))-log(value.denominator)
    else:log_abs=float(abs(value).ln())
    return {'value':converted if isfinite(converted) else None,'representation':representation,
            'log_abs':log_abs,'sign':sign,'tolerance_relation':relation,
            'decision_basis':basis,'precision_digits':precision}


def _exponential_signature(terms, rate):
    """Expand integral primitives into exact rational exponential coefficients."""
    result={}
    def add(exponent,coefficient):
        result[exponent]=result.get(exponent,Fraction(0))+coefficient
        if not result[exponent]:result.pop(exponent)
    for key,coefficient in terms.items():
        if key is None:add(Fraction(0),coefficient)
        elif key[0]=='exp':add(key[1],coefficient)
        else:
            time=key[1];exponent=rate*time
            if key[0]=='J0':
                add(Fraction(0),coefficient/rate)
                add(exponent,-coefficient/rate)
            else:
                add(Fraction(0),coefficient/(rate*rate))
                add(exponent,-coefficient*(1+exponent)/(rate*rate))
    return result


def _scaled_objective_gap(terms,rate,tie_tolerance):
    """Keep comparison sign before binary64 conversion of tiny exponential sums.

    Factor the least exponent exactly. Terms beyond the relative exponent cut
    contribute a positive absolute tail bound; they are never silently zero in
    the decision guard. The Decimal arithmetic guard remains adaptive rather
    than an interval certificate. Small-rate ordinary cases retain the stable
    segment/moment evaluator in _guarded_objective_gap.
    """
    terms=_exponential_signature(terms,rate)
    if not terms or set(terms)=={Fraction(0)}:
        return _gap_diagnostic(terms.get(Fraction(0),Fraction(0)),Fraction(tie_tolerance),
                               'exact_original_input_difference')
    common=min(terms);previous=None
    for precision in (80,160,320,640,1280):
        with localcontext() as ctx:
            ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
            D=lambda x:Decimal(x.numerator)/Decimal(x.denominator)
            value=gross=tail=Decimal(0)
            cutoff=Decimal(100000);tail_decay=(-cutoff).exp()
            for exponent,coefficient in sorted(terms.items()):
                delta=exponent-common;c=D(coefficient)
                if delta>100000:
                    tail+=abs(c)*tail_decay
                else:
                    term=c*(-D(delta)).exp();value+=term;gross+=abs(term)
            arithmetic_guard=Decimal(10)**(-precision+12)
            uncertainty=tail+(gross+tail)*arithmetic_guard
            magnitude=abs(value)
            if magnitude<=uncertainty:
                previous=None;continue
            sign=1 if value>0 else -1
            exponent=D(common)
            log_abs=magnitude.ln()-exponent
            log_value=float(log_abs)
            if not isfinite(log_value):
                raise ValueError('objective comparison unresolved: logarithmic magnitude exceeds floating-point range; rescale inputs')
            if tie_tolerance==0:relation=sign
            else:
                lower=(magnitude-uncertainty).ln()-exponent
                upper=(magnitude+uncertainty).ln()-exponent
                threshold=Decimal.from_float(tie_tolerance).ln()
                log_guard=(abs(lower)+abs(upper)+abs(exponent)+abs(threshold)+1)*arithmetic_guard
                if lower>threshold+log_guard:relation=sign
                elif upper<threshold-log_guard:relation=0
                else:
                    previous=None;continue
            if log_abs<-1000:converted=-0.0 if sign<0 else 0.0
            elif log_abs>1000:converted=-float('inf') if sign<0 else float('inf')
            else:converted=float(log_abs.exp())*sign
            representation='outside_float_range' if not isfinite(converted) else 'underflow' if converted==0 else 'finite'
            diagnostic={'value':converted if isfinite(converted) else None,'representation':representation,
                'log_abs':log_value,'sign':sign,'tolerance_relation':relation,
                'decision_basis':'scaled_original_input_difference','precision_digits':precision}
            state=(diagnostic['value'],sign,relation,log_value)
            if previous==state:return diagnostic
            previous=state
    raise ValueError('objective comparison unresolved at 1280 digits; change numerical scaling or formulation')


def _guarded_objective_gap(p,left,right=None,outside_option=0.,tie_tolerance=1e-8):
    """Original-input gap at recorded controls; not a global/interval bound.

    Exact common terms cancel before transcendental guards. Rational gaps
    retain their sign at final underflow and beyond binary64 magnitude.
    Other gaps require two stable rounded values, signs and tolerance sides.
    """
    a=_objective_signature(p,left['strategy'],left['delay'],left['announcement'])
    b=(_objective_signature(p,right['strategy'],right['delay'],right['announcement'])
       if right is not None else {None:Fraction(outside_option)})
    for key,value in b.items():
        a[key]=a.get(key,Fraction(0))-value
        if not a[key]:a.pop(key)
    if not any(key is not None for key in a):
        return _gap_diagnostic(a.get(None,Fraction(0)),Fraction(tie_tolerance),
                               'exact_original_input_difference')
    # The ordinary segment evaluator has an output-range cut. Before that cut
    # could erase a decision-sign contribution, switch to a factored sum with
    # an explicit omitted-tail bound. Avoid expanded primitive cancellation in
    # ordinary small-discount cases by retaining their stable moment series.
    rate=Fraction(p.discount);learning=Fraction(p.learning_rate)
    entries=[Fraction(0) if row['strategy'].endswith('F') else Fraction(row['delay'])
             for row in (left,right) if row is not None]
    if (rate*Fraction(p.horizon)>100000 or
            any((rate+learning)*entry>100000 for entry in entries)):
        return _scaled_objective_gap(a,rate,tie_tolerance)
    previous=None
    for precision in (80,160,320,640,1280):
        with localcontext() as ctx:
            ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
            x,gx=_decimal_net_payoff(p,left['strategy'],left['delay'],left['announcement'],precision)
            if right is None:y=Decimal.from_float(outside_option);gy=abs(y)
            else:y,gy=_decimal_net_payoff(p,right['strategy'],right['delay'],right['announcement'],precision)
            value=x-y;tolerance=Decimal.from_float(tie_tolerance)
            uncertainty=(gx+gy)*Decimal(10)**(-precision+12)
            # Structural exact constants were handled above. An unresolved
            # zero from finite precision or an output-range decay cut is not
            # evidence of exact equality, even with a positive tie tolerance.
            resolved=abs(value)>uncertainty and abs(abs(value)-tolerance)>uncertainty
            diagnostic=_gap_diagnostic(value,tolerance,'adaptive_original_input_difference',precision)
            state=(diagnostic['value'],diagnostic['sign'],diagnostic['tolerance_relation'])
            if resolved and previous==state:return diagnostic
            previous=state if resolved else None
    raise ValueError('objective comparison unresolved at 1280 digits; change numerical scaling or formulation')


def finite_number(value, name, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite real number")
    try:converted=float(value)
    except (OverflowError,ValueError,TypeError):
        raise ValueError(f"{name} is outside the binary64 range; rescale inputs") from None
    if not isfinite(converted):raise ValueError(f"{name} must be finite in binary64")
    if value!=0 and converted==0:
        raise ValueError(f"{name} underflows to zero in binary64; rescale inputs")
    if positive and converted <= 0:
        raise ValueError(f"{name} must be positive")
    if minimum is not None and converted < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return converted

def finite_float_text(token, name='number'):
    """Check a floating token before its original nonzero value can be lost.

    Python's float grammar is retained for CLI inputs. JSON callers already
    restrict lexical grammar in their decoder. Decimal Unicode digits and
    underscores accepted by float do not bypass the mantissa check.
    """
    if not isinstance(token,str):raise ValueError(name+' must be numeric text')
    try:value=float(token)
    except (ValueError,OverflowError):raise ValueError(name+' must be finite numeric text') from None
    mantissa=token.lower().split('e',1)[0]
    if value==0 and any(character.isdecimal() and int(character)!=0 for character in mantissa):
        raise ValueError(name+' underflows to zero in binary64; rescale inputs')
    return finite_number(value,name)

@dataclass(frozen=True)
class ModelParams:
    growth: float = 0.1
    network: float = 0.85
    growth_end: float = 0.3
    horizon: float = 1.0
    quality_ratio: float = 1.0
    margin_x: float = 0.25
    margin_y: float = 0.25
    discount: float = 0.0
    announcement_cost: float = 0.0
    deployment_cost: float = 0.0
    learning_rate: float = 0.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            object.__setattr__(self, name, finite_number(value, name, minimum=0, positive=name in ("horizon", "quality_ratio")))
        if self.growth_end > self.horizon:
            raise ValueError("growth_end must not exceed horizon")

    @classmethod
    def from_dict(cls, obj):
        if not isinstance(obj, dict):
            raise ValueError("params must be a JSON object")
        return cls(**obj)

def _controls(p, strategy, delay, announcement):
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {STRATEGIES}")
    delay=finite_number(delay, "delay", minimum=0)
    announcement=finite_number(announcement, "announcement", minimum=0)
    if delay > p.growth_end:
        raise ValueError("delay must not exceed growth_end")
    if strategy.startswith("D") and announcement != 0:
        raise ValueError("D strategies require announcement=0")
    return delay,announcement

def decisions(p, strategy, delay, announcement):
    _controls(p,strategy,delay,announcement)

def _real_array(values,name,allow_object=False):
    """Preserve shape and validate original reals before lossy array arithmetic."""
    raw=np.asarray(values)
    if raw.dtype.kind in 'iuf':
        with np.errstate(over='ignore',under='ignore',invalid='ignore'):
            value=raw.astype(float)
        if not np.all(np.isfinite(value)):raise ValueError(name+' must be finite in binary64')
        if np.any((raw!=0)&(value==0)):raise ValueError(name+' underflows to zero in binary64; rescale inputs')
        return value
    if allow_object and raw.dtype.kind=='O':
        return np.array([finite_number(item,name) for item in raw.flat],dtype=float).reshape(raw.shape)
    raise ValueError(name+' must contain real numeric values')

def _log_product(*values):
    return sum(log(v) for v in values) if all(v > 0 for v in values) else -float("inf")

def _log_weights(p, strategy, delay, announcement):
    k = _log_product(p.network, p.growth, delay)
    b = _log_product(p.network, announcement, delay)
    if strategy.endswith("F"):
        a = float(np.logaddexp(0., k))
        if strategy == "RF": a = float(np.logaddexp(a, b))
        return a, log(p.quality_ratio)
    return (float(np.logaddexp(0., b)) if strategy == "RL" else 0.,
            log(p.quality_ratio)+float(np.logaddexp(0., k)))

def shares(p, strategy, delay, announcement=0.0):
    delay,announcement=_controls(p, strategy, delay, announcement)
    w, k, b = p.quality_ratio, p.network*p.growth*delay, p.network*announcement*delay
    if strategy == "RF":
        x_weight, y_weight = 1+k+b, w
    elif strategy == "DF":
        x_weight, y_weight = 1+k, w
    elif strategy == "RL":
        x_weight, y_weight = 1+b, w*(1+k)
    else:
        x_weight, y_weight = 1.0, w*(1+k)
    total = x_weight+y_weight
    if not isfinite(total):
        a, b = _log_weights(p, strategy, delay, announcement)
        total = float(np.logaddexp(a, b))
        return exp(a-total), exp(b-total)
    return x_weight/total, y_weight/total

def demand(p, strategy, time, delay, announcement=0.0):
    """Return (D_x, D_y) for scalar or NumPy-compatible time values."""
    delay,announcement=_controls(p, strategy, delay, announcement)
    a,b = _log_weights(p, strategy, delay, announcement)
    total = float(np.logaddexp(a,b))
    t = _real_array(time,'time',allow_object=True)
    if not np.all(np.isfinite(t)) or np.any(t < 0) or np.any(t > p.horizon):
        raise ValueError("time must be finite and within [0, horizon]")
    u = np.minimum(t, p.growth_end)
    # A share may underflow although its weighted consumer stock is finite.
    # Combine all scales before conversion, as in the revenue kernel.
    with np.errstate(divide='ignore',over='ignore',under='ignore'):
        mass = _log_product(p.growth)+np.log(np.maximum(u-delay,0))
        lead = _log_product(p.growth)+np.log(np.minimum(u,delay))
        lx,ly = mass+(a-total),mass+(b-total)
        if strategy.endswith("F"):lx = np.logaddexp(lead,lx)
        else:ly = np.logaddexp(lead,ly)
        x,y = np.exp(lx),np.exp(ly)
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("demand exceeds floating-point range; rescale input parameters")
    if t.ndim == 0:
        return float(x), float(y)
    return x, y

def _log_moments(length, rate):
    """Log moments keep the time-square scale until final revenue weighting."""
    if length <= 0:
        return -float("inf"), -float("inf")
    scale = log(length)
    if rate == 0:
        return scale, 2*scale-log(2)
    x = rate*length
    if x < 0.01:
        # Series avoids cancellation at tiny discounts and tiny intervals.
        j0 = scale+log(sum((-x)**n/(factorial(n)*(n+1)) for n in range(12)))
        j1 = 2*scale+log(sum((-x)**n/(factorial(n)*(n+2)) for n in range(12)))
    else:
        j0 = log(-expm1(-x))-log(rate)
        decay_term = 0.0 if not isfinite(x) else x*exp(-x)
        j1 = log(-expm1(-x)-decay_term)-2*log(rate)
    return j0, j1

def _from_log(value, name):
    try:
        result = exp(value)
    except OverflowError:
        raise ValueError(f"{name} exceeds floating-point range; rescale inputs") from None
    if not isfinite(result):
        raise ValueError(f"{name} exceeds floating-point range; rescale inputs")
    return result

def _moments(length, rate):
    """Representable scalar moments; the revenue kernel uses their logs."""
    a,b = _log_moments(length,rate)
    return _from_log(a,"zeroth moment"), _from_log(b,"first moment")

def _log_segment(a, b, value_at_a, slope, rate):
    if b <= a:
        return -float("inf")
    j0, j1 = _log_moments(b-a, rate)
    return float(np.logaddexp(_log_product(value_at_a)+j0,
                             _log_product(slope)+j1))-rate*a

def _log_response_mass(p, delay):
    return float(np.logaddexp(_log_segment(delay,p.growth_end,0,1,p.discount),
        _log_segment(p.growth_end,p.horizon,p.growth_end-delay,0,p.discount)))

def response_mass(p, delay):
    """Discounted post-entry demand multiplier, excluding growth and share."""
    return _from_log(_log_response_mass(p,delay),"response mass")

def _envelope_payoff(p, delay):
    """The uncapped RL limit shares the finite-objective precision policy."""
    delay,_=_controls(p,'RL',delay,0)
    revenue=_from_log(_log_product(p.margin_x,p.growth)+_log_response_mass(p,delay),'joint envelope revenue')
    value=_guarded_net_payoff(p,'RL',delay,0.,revenue,0.,deployment_present_value(p,delay),True)
    if not isfinite(value):raise ValueError('joint envelope payoff exceeds floating-point range; rescale inputs')
    return value

def _log_revenues(p, strategy, delay, announcement=0.0):
    """Compute each revenue scale without requiring either final value to fit."""
    delay,announcement=_controls(p,strategy,delay,announcement)
    a,b = _log_weights(p,strategy,delay,announcement)
    total = float(np.logaddexp(a,b))
    zx,zy = a-total,b-total
    mass = _log_product(p.growth)+_log_response_mass(p,delay)
    lead_base = _log_product(p.growth)+float(np.logaddexp(
        _log_segment(0,delay,0,1,p.discount),
        _log_segment(delay,p.horizon,delay,0,p.discount)))
    if strategy.endswith("F"):
        rx,ry = float(np.logaddexp(lead_base,mass+zx)),mass+zy
    else:
        rx,ry = mass+zx,float(np.logaddexp(lead_base,mass+zy))
    return _log_product(p.margin_x)+rx, _log_product(p.margin_y)+ry

def revenues(p, strategy, delay, announcement=0.0):
    """Return both discounted revenues; both requested values must fit."""
    rx,ry = _log_revenues(p,strategy,delay,announcement)
    return _from_log(rx,"revenue"), _from_log(ry,"revenue")

@lru_cache(maxsize=8192)
def _objective_gross_scale(p, strategy, delay, announcement):
    """Positive original-control component scale for comparison risk screening.

    A rounded net payoff can hide the scale of revenue/cost cancellation.
    Keep this bounded cache separate from extension-supplied objective values.
    This is a trigger for the original-input evaluator, not an error bound.
    """
    revenue=_from_log(_log_revenues(p,strategy,delay,announcement)[0],"object revenue")
    cost=_from_log(_log_product(p.announcement_cost,announcement,announcement)-log(2),"announcement cost")
    entry=0.0 if strategy.endswith('F') else delay
    return max(revenue,cost,deployment_present_value(p,entry))

def payoff(p, strategy, delay, announcement=0.0):
    """Object platform payoff; costs are present values, announcement paid at 0."""
    delay,announcement=_controls(p,strategy,delay,announcement)
    rx = _from_log(_log_revenues(p,strategy,delay,announcement)[0],"object revenue")
    entry_time = 0.0 if strategy.endswith("F") else delay
    deployment = deployment_present_value(p, entry_time)
    cost_log = _log_product(p.announcement_cost, announcement, announcement)-log(2)
    try: cost = exp(cost_log)
    except OverflowError: raise ValueError("announcement cost exceeds floating-point range; rescale inputs") from None
    result = _guarded_net_payoff(p,strategy,delay,announcement,rx,cost,deployment)
    if not isfinite(result):
        raise ValueError("payoff overflow; rescale input parameters")
    return result

def deployment_present_value(p, entry_time):
    """Evaluate the cost without overflowing a sum of rates or losing its scale."""
    if p.deployment_cost == 0 or entry_time == 0:
        return p.deployment_cost
    return exp(log(p.deployment_cost)-p.learning_rate*entry_time-p.discount*entry_time)

def log_announcement_benefit(p, strategy, delay, announcement):
    """Log marginal revenue, without squaring unscaled share weights."""
    delay,announcement=_controls(p, strategy, delay, announcement)
    if not _announcement_has_effect(p,strategy,delay):
        return -float("inf")
    mass = _log_response_mass(p, delay)
    if not isfinite(mass):
        raise ValueError("announcement benefit logarithmic magnitude exceeds floating-point range; reformulate numerical scales")
    a, b = _log_weights(p, strategy, delay, announcement)
    return _log_product(p.margin_x,p.growth,p.network,delay)+mass+b-2*float(np.logaddexp(a,b))


def _announcement_has_effect(p,strategy,delay):
    """Structural positivity, independently of exponent/output representation."""
    return (strategy.startswith('R') and p.margin_x>0 and p.growth>0
            and p.network>0 and 0<delay<p.growth_end)


def _announcement_derivative_record(value,scale,basis,precision=None):
    sign=(value>0)-(value<0)
    try:amount=float(value)
    except OverflowError:amount=float('inf') if sign>0 else -float('inf')
    def logarithm(x):
        return log(abs(x.numerator))-log(x.denominator) if isinstance(x,Fraction) else float(abs(x).ln())
    relative=float(abs(value)/scale) if scale else 0.
    return {'value':amount if isfinite(amount) else None,'sign':sign,
            'log_abs':logarithm(value) if sign else None,'scaled':relative,
            'representation':'outside_float_range' if not isfinite(amount) else 'underflow' if sign and amount==0 else 'finite',
            'scaled_representation':'underflow' if sign and relative==0 else 'finite',
            'decision_basis':basis,'precision_digits':precision}


def _announcement_derivative_diagnostic(p,strategy,delay,announcement):
    """Original-input protection for a near cancelling marginal difference.

    This diagnoses the returned control. It is not an optimality certificate
    or a comparison against the payoff-unit neighborhood tolerance.
    """
    if not strategy.startswith('R'):raise ValueError('announcement derivative requires an R strategy')
    delay,announcement=_controls(p,strategy,delay,announcement)
    lb=log_announcement_benefit(p,strategy,delay,announcement)
    lc=_log_product(p.announcement_cost,announcement)
    if lb==lc==-float('inf'):
        return _announcement_derivative_record(Fraction(0),Fraction(0),'structural_zero_announcement_difference')
    if isfinite(lb) and isfinite(lc) and abs(lb-lc)<=NET_PAYOFF_GUARD_RATIO:
        if p.discount==0:
            s,n,H,T,w,m,c,t,d=map(Fraction,(p.growth,p.network,p.growth_end,p.horizon,
                p.quality_ratio,p.margin_x,p.announcement_cost,delay,announcement))
            a=1+n*((s+d) if strategy=='RF' else d)*t
            b=w if strategy=='RF' else w*(1+n*s*t)
            mass=(H-t)*(2*T-H-t)/2
            benefit=m*s*n*t*b*mass/(a+b)**2;cost=c*d
            return _announcement_derivative_record(benefit-cost,max(benefit,cost),
                'exact_original_input_announcement_difference')
        previous=None
        for precision in (80,160,320,640,1280):
            with localcontext() as ctx:
                ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
                s,n,H,T,w,m,r,c,t,d=map(Decimal.from_float,(p.growth,p.network,p.growth_end,
                    p.horizon,p.quality_ratio,p.margin_x,p.discount,p.announcement_cost,delay,announcement))
                def moments(length):
                    if not length:return Decimal(0),Decimal(0)
                    x=r*length
                    if x<Decimal('.1'):
                        a=b=Decimal(0);power=Decimal(1);epsilon=Decimal(10)**(-precision-5)
                        for j in range(500):
                            u=power/(j+1);v=power/(j+2);a+=u;b+=v
                            if abs(u)<epsilon*abs(a) and abs(v)<epsilon*abs(b):break
                            power*=-x/(j+1)
                        else:raise ValueError('announcement derivative moment series did not converge')
                        return length*a,length*length*b
                    e=(-x).exp()
                    return (1-e)/r,(1-(1+x)*e)/(r*r)
                a=1+n*((s+d) if strategy=='RF' else d)*t
                b=w if strategy=='RF' else w*(1+n*s*t)
                if r*t>100000:
                    raise ValueError('announcement derivative cancellation exceeds numerical range; reformulate inputs')
                response=(-r*t).exp()*moments(H-t)[1]+(H-t)*(-r*H).exp()*moments(T-H)[0]
                benefit=m*s*n*t*b*response/(a+b)**2;cost=c*d
                value=benefit-cost;gross=abs(benefit)+abs(cost)
                resolved=abs(value)>gross*Decimal(10)**(-precision+12)
                result=_announcement_derivative_record(value,max(benefit,cost),
                    'adaptive_original_input_announcement_difference',precision)
                state=(result['value'],result['sign'],result['scaled'],result['log_abs'])
                if resolved and previous==state:return result
                previous=state if resolved else None
        raise ValueError('announcement derivative cancellation is unresolved at 1280 digits; reformulate inputs')
    sign=1 if lb>lc else -1
    relative=-expm1(-abs(lb-lc))
    magnitude=max(lb,lc)+log(relative)
    if not isfinite(magnitude):raise ValueError('announcement gradient logarithmic magnitude exceeds floating-point range')
    try:amount=exp(magnitude)*sign
    except OverflowError:amount=None
    return {'value':amount,'sign':sign,'log_abs':magnitude,'scaled':relative,
            'representation':'outside_float_range' if amount is None else 'underflow' if amount==0 else 'finite',
            'scaled_representation':'finite','decision_basis':'log_marginal_difference','precision_digits':None}


def announcement_gradient(p, strategy, delay, announcement):
    """Marginal payoff with original-input protection near cancellation."""
    result=_announcement_derivative_diagnostic(p,strategy,delay,announcement)
    if result['value'] is None:raise ValueError('announcement gradient exceeds floating-point range; rescale inputs')
    return result['value']



def payoff_grid(p,strategy,delays,announcements):
    """Stable vector zero-discount matrix; discounted cases use scalar kernel.

    Rows are announcement intensities and columns are delays. This evaluates
    mathematical controls, not an optimizer or a configured feasibility check.
    """
    def array(values,name):
        raw=np.asarray(values)
        if raw.dtype.kind not in 'iuf' or raw.ndim!=1 or not raw.size:raise ValueError(name+' must be a nonempty numeric vector')
        value=_real_array(raw,name)
        if not np.all(np.isfinite(value)) or np.any(value<0):raise ValueError(name+' must be finite and nonnegative')
        return value
    t=array(delays,'delays');d=array(announcements,'announcements')
    if strategy not in STRATEGIES or np.any(t>p.growth_end) or (strategy.startswith('D') and np.any(d!=0)):raise ValueError('invalid payoff grid controls')
    if t.size*d.size>1000000:raise ValueError('payoff grid exceeds one million controls')
    if p.discount!=0:return np.array([[payoff(p,strategy,float(tau),float(delta)) for tau in t] for delta in d])
    t=t[None,:];d=d[:,None]
    def logs(v):
        v=np.asarray(v,dtype=float);out=np.full(v.shape,-np.inf);np.log(v,out=out,where=v>0);return out
    logt=logs(t);logd=logs(d);k=_log_product(p.network,p.growth)+logt;b=_log_product(p.network)+logt+logd
    if strategy.endswith('F'):
        a=np.logaddexp(0.,k)
        if strategy=='RF':a=np.logaddexp(a,b)
        y=log(p.quality_ratio)
    else:a=np.logaddexp(0.,b) if strategy=='RL' else 0.;y=log(p.quality_ratio)+np.logaddexp(0.,k)
    share=a-np.logaddexp(a,y)
    length=p.growth_end-t;loglength=logs(length)
    # Form the half-length moments in log space before revenue weighting.
    # Direct length/2 or t/2 can lose a positive subnormal time completely.
    mass=loglength+np.logaddexp(logs(p.horizon-p.growth_end),loglength-log(2))
    leader=logt+np.logaddexp(logs(p.horizon-t),logt-log(2))
    stock=np.logaddexp(leader,mass+share) if strategy.endswith('F') else mass+share
    revenue_log=_log_product(p.growth,p.margin_x)+stock
    cost_log=_log_product(p.announcement_cost)+2*logd-log(2)
    with np.errstate(over='ignore',under='ignore'):
        revenue=np.exp(revenue_log);cost=np.exp(cost_log)
        deployment=p.deployment_cost if strategy.endswith('F') else np.exp(_log_product(p.deployment_cost)-p.learning_rate*t)
        result=revenue-cost-deployment
    result=np.broadcast_to(result,(d.shape[0],t.shape[1])).copy()
    if not np.all(np.isfinite(revenue)) or not np.all(np.isfinite(cost)) or not np.all(np.isfinite(result)):raise ValueError('payoff grid exceeds floating-point range; rescale inputs')
    rv,cs,dp=np.broadcast_arrays(revenue,cost,deployment)
    scale=np.maximum(np.maximum(rv,cs),dp)
    with np.errstate(divide='ignore',invalid='ignore',under='ignore'):
        guarded=(scale>0)&(np.abs(result)/scale<=NET_PAYOFF_GUARD_RATIO)
    if p.deployment_cost>0 or p.announcement_cost>0:guarded|=scale==0
    for i,j in np.argwhere(guarded):
        result[i,j]=_guarded_net_payoff(p,strategy,float(t[0,j]),float(d[i,0]),
                                      float(rv[i,j]),float(cs[i,j]),float(dp[i,j]))
    return result
