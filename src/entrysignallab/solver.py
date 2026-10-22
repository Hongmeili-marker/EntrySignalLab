"""Concave announcement profiling and bounded delay search. MIT License."""
from dataclasses import dataclass, asdict
from functools import cmp_to_key
from math import isfinite, exp, expm1, log, log1p, ulp
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
import sys
import struct
import numpy as np
from scipy.optimize import brentq, minimize_scalar
from .model import (finite_number, payoff, STRATEGIES, shares,
                    log_announcement_benefit, _log_response_mass, _log_moments,
                    _from_log, deployment_present_value, decisions, _envelope_payoff,
                    _guarded_objective_gap, NET_PAYOFF_GUARD_RATIO,
                    _announcement_has_effect, _announcement_derivative_diagnostic,
                    _objective_gross_scale)

def announcement_stationarity(p, strategy, delay, intensity, active):
    """KKT violation in raw and scale-free units, without forming huge gradients.

    Fixed controls have no feasible intensity perturbation. A null raw residual
    denotes an unrepresentable violation, never a silently rounded zero.
    """
    def zero(basis,gradient=None):
        return {'raw':0.0,'log':None,'scaled':0.0,'representation':'finite',
                'scaled_representation':'finite','decision_basis':basis,
                'precision_digits':None if gradient is None else gradient['precision_digits'],
                'gradient_sign':None if gradient is None else gradient['sign']}
    if active in ('fixed','not_applicable'):return zero('fixed_or_not_applicable_feasible_direction')
    # A cost-free upper cap has no feasible improving intensity direction.
    # Its projection needs no unrepresentable discounted benefit magnitude.
    if active=='upper' and p.announcement_cost==0:return zero('analytic_cost_free_upper_projection')
    try:gradient=_announcement_derivative_diagnostic(p,strategy,delay,intensity)
    except ValueError as error:raise NumericalError(str(error)) from None
    if (active=='lower' and gradient['sign']<=0) or (active=='upper' and gradient['sign']>=0):
        return zero('projected_'+gradient['decision_basis'],gradient)
    return {'raw':abs(gradient['value']) if gradient['value'] is not None else None,
            'log':gradient['log_abs'],'scaled':gradient['scaled'],
            'representation':gradient['representation'],'scaled_representation':gradient['scaled_representation'],
            'decision_basis':gradient['decision_basis'],'precision_digits':gradient['precision_digits'],
            'gradient_sign':gradient['sign']}

class NumericalError(ValueError):
    """A numerical computation could not be certified as converged."""

def checked_root(function, lower, upper, tolerance):
    root, info = brentq(function, lower, upper, xtol=tolerance, rtol=1e-14,
                       maxiter=256, full_output=True, disp=False)
    if not info.converged:
        raise NumericalError("root solver did not converge; rescale inputs or adjust bounds")
    return float(root)


def _model_control_gap(p, left, right=None, outside_option=0., tolerance=0.):
    """One ordering policy for model-owned recorded controls and search nodes.

    Screen both the rounded net scale and the original gross component scale.
    The latter prevents cancellation-amplified rounding from looking safely
    separated. This is an adaptive trigger, not an error bound or certificate.
    """
    a=left['payoff'];b=right['payoff'] if right is not None else outside_option
    raw=a-b;scale=max(abs(a),abs(b),tolerance)
    distance=min(abs(raw),abs(abs(raw)-tolerance))
    close=scale==0 or any(0<abs(v)<sys.float_info.min for v in (a,b)) or distance/scale<=NET_PAYOFF_GUARD_RATIO
    if not close:
        gross=_objective_gross_scale(p,left['strategy'],left['delay'],left['announcement'])
        if right is not None:
            gross=max(gross,_objective_gross_scale(p,right['strategy'],right['delay'],right['announcement']))
        # In particular, the apparent net gap can be much larger than a net
        # relative threshold while still smaller than gross rounding noise.
        close=gross>0 and distance/gross<=NET_PAYOFF_GUARD_RATIO
    if close:
        try:return _guarded_objective_gap(p,left,right,outside_option,tolerance)
        except ValueError as error:raise NumericalError(str(error)) from None
    return {'value':raw if isfinite(raw) else None,
            'representation':'finite' if isfinite(raw) else 'outside_float_range',
            'log_abs':log(abs(raw)) if isfinite(raw) else float(np.logaddexp(log(abs(a)),log(abs(b)))),
            'sign':1 if raw>0 else -1,
            'tolerance_relation':1 if raw>tolerance else -1 if raw < -tolerance else 0,
            'decision_basis':'rounded_payoff_difference','precision_digits':None}


def _ordered_golden_refine(evaluate, order, a, b, tolerance):
    """Bounded normalized golden refinement using original-input comparisons.

    Used after a rounded-value ordering collision, so no tiny objective is
    passed to a scalar optimizer as an identically zero function. Endpoints
    and all probes remain in the shared candidate cache. As with bounded
    scalar refinement, this supplies local candidates, not a global proof.
    """
    ratio=(5.**.5-1)/2;left,right=0.,1.;span=b-a
    u=right-ratio*(right-left);v=left+ratio*(right-left)
    x=a+span*u;y=a+span*v;evaluate(x);evaluate(y)
    iterations=0
    while right-left>tolerance:
        if not a+span*left<x<y<a+span*right:
            return {'method':'guarded_golden','iterations':iterations,'termination':'floating_control_separation'}
        if iterations>=512:raise NumericalError('guarded delay refinement did not converge')
        if order(x,y)>=0:
            right,v,y=v,u,x;u=right-ratio*(right-left);x=a+span*u;evaluate(x)
        else:
            left,u,x=u,v,y;v=left+ratio*(right-left);y=a+span*v;evaluate(y)
        iterations+=1
    return {'method':'guarded_golden','iterations':iterations,'termination':'normalized_interval_width'}

@dataclass(frozen=True)
class DecisionBounds:
    delay_lower: float = 0.0
    delay_upper: float | None = None
    announcement_upper: float | None = 2.0
    scouting_points: int = 65
    tolerance: float = 1e-10
    payoff_atol: float = 1e-10
    payoff_rtol: float = 1e-8
    max_evaluations: int = 20000

    def __post_init__(self):
        for name in ['delay_lower','delay_upper','announcement_upper','tolerance','payoff_atol','payoff_rtol']:
            value=getattr(self,name)
            if value is None:continue
            try:converted=finite_number(value,name)
            except ValueError:continue  # validate() rejects invalid specifications.
            object.__setattr__(self,name,converted)

    def validate(self, p):
        hi = p.growth_end if self.delay_upper is None else self.delay_upper
        finite_number(self.delay_lower, "delay_lower", minimum=0)
        finite_number(hi, "delay_upper", minimum=0)
        if self.delay_lower > hi or hi > p.growth_end:
            raise ValueError("delay bounds must satisfy 0 <= lower <= upper <= growth_end")
        if self.announcement_upper is not None:
            finite_number(self.announcement_upper, "announcement_upper", minimum=0)
        if isinstance(self.scouting_points, bool) or not isinstance(self.scouting_points, int) or self.scouting_points < 3:
            raise ValueError("scouting_points must be an integer >= 3")
        finite_number(self.tolerance, "tolerance", positive=True)
        finite_number(self.payoff_atol,"payoff_atol",minimum=0)
        finite_number(self.payoff_rtol,"payoff_rtol",minimum=0)
        if isinstance(self.max_evaluations,bool) or not isinstance(self.max_evaluations,int) or self.max_evaluations<1:
            raise ValueError("max_evaluations must be a positive integer")
        # Signed zero is the same mathematical endpoint; its sign bit must not
        # participate in the nonnegative-float lattice cardinality below.
        return (0.0 if self.delay_lower == 0 else float(self.delay_lower)), (0.0 if hi == 0 else float(hi))

def _announcement_float_bracket(gradient, lower, upper):
    """Refine a strict derivative bracket on the positive binary64 lattice.

    Only used when log/exp cannot retain a real endpoint bracket. Ordered
    positive float encodings avoid overflowing a span or collapsing minsubnormal
    controls. At most 63 bisections reach adjacent representable controls.
    """
    bits=lambda x:struct.unpack('>Q',struct.pack('>d',x))[0]
    value=lambda x:struct.unpack('>d',struct.pack('>Q',x))[0]
    lo,hi=bits(lower),bits(upper)
    while hi-lo>1:
        mid=(lo+hi)//2;g=gradient(value(mid))
        if g['sign']==0:return value(mid)
        if g['sign']>0:lo=mid
        else:hi=mid
    # Both endpoints bracket the unique root; select the smaller scaled KKT
    # violation. Neither is a claim of bit-exact transcendental root accuracy.
    return min((value(lo),value(hi)),key=lambda x:gradient(x)['scaled'])


def profile_announcement(p, strategy, delay, upper, tolerance=1e-10):
    """Solve the concave intensity subproblem. Return intensity and degeneracy."""
    delay=finite_number(delay, "delay", minimum=0)
    upper=None if upper is None else finite_number(upper, "announcement_upper", minimum=0)
    tolerance=finite_number(tolerance, "tolerance", positive=True)
    decisions(p,strategy,delay,0)
    if strategy.startswith("D"):
        return 0.0, False
    if not _announcement_has_effect(p,strategy,delay):
        return 0.0, p.announcement_cost == 0 and (upper is None or upper > 0)
    if upper==0:return 0.0,False
    if p.announcement_cost == 0:
        if upper is None:
            raise ValueError("no finite announcement optimum at positive effective delay; provide a finite upper bound or positive announcement_cost")
        return float(upper), False
    def gradient(intensity):
        try:return _announcement_derivative_diagnostic(p,strategy,delay,intensity)
        except ValueError as error:raise NumericalError(str(error)) from None
    # Solve equality of marginal revenue and marginal cost in log intensity.
    # This avoids an enormous g(0)/c_A bracket and underflowed derivatives.
    log_cost = log(p.announcement_cost)
    def balance(u):
        return log_announcement_benefit(p, strategy, delay, exp(u))-log_cost-u
    if upper is not None and gradient(upper)['sign'] >= 0:
        return float(upper), False
    minimum=float.fromhex('0x0.0000000000001p-1022')
    maximum=float(upper) if upper is not None else sys.float_info.max
    low,high=log(minimum),log(maximum)
    lower_sign=gradient(minimum)['sign']
    if lower_sign==0:return minimum,False
    if lower_sign<0:
        raise NumericalError("positive intensity optimum is below floating-point range; rescale inputs")
    upper_sign=gradient(maximum)['sign']
    if upper_sign==0:return maximum,False
    if upper_sign>0:
        raise NumericalError("positive intensity optimum exceeds floating-point range; rescale inputs")
    # log(max_float) can map back hundreds of ULPs below max_float. Check
    # the actual round-tripped controls too; no range decision uses them.
    try:
        roundtrip_low,roundtrip_high=exp(low),exp(high)
        log_bracket=(minimum<=roundtrip_low<roundtrip_high<=maximum
            and (lower_sign if roundtrip_low==minimum else gradient(roundtrip_low)['sign'])>0
            and (upper_sign if roundtrip_high==maximum else gradient(roundtrip_high)['sign'])<0)
    except OverflowError:
        log_bracket=False
    if not log_bracket or low>=high or balance(low)<=0 or balance(high)>=0:
        return _announcement_float_bracket(gradient,minimum,maximum),False
    u = checked_root(balance, low, high, 1e-13)
    return min(float(upper), exp(u)) if upper is not None else exp(u), False

def _decimal_envelope_order(p, a, b):
    """Resolve close component differences without subtracting net payoffs.

    This is an adaptive numerical guard, not interval certification. Cancel
    the common exp(-r*a) before comparing revenue and deployment differences.
    """
    previous=None
    for precision in (80,160,320):
        with localcontext() as ctx:
            ctx.prec=precision;ctx.Emax=MAX_EMAX;ctx.Emin=MIN_EMIN
            D=Decimal.from_float
            A,B,T,R,K,M,S,C=map(D,(a,b,p.horizon,p.discount,p.learning_rate,p.margin_x,p.growth,p.deployment_cost))
            delta=B-A
            def decay(x):
                # Beyond this exponent the term is far below every possible
                # positive component made from finite binary64 model inputs.
                return Decimal(0) if x>100000 else (-x).exp()
            def moments(length,rate):
                if length==0:return Decimal(0),Decimal(0)
                if rate==0:return length,length*length/2
                x=rate*length
                if x<Decimal('.1'):
                    j0=Decimal(0);j1=Decimal(0);power=Decimal(1)
                    epsilon=Decimal(10)**(-precision-5)
                    for n in range(500):
                        term0=power/(n+1);term1=power/(n+2)
                        j0+=term0;j1+=term1
                        if abs(term0)<epsilon*abs(j0) and abs(term1)<epsilon*abs(j1):break
                        power*=-x/(n+1)
                    else:raise NumericalError('joint envelope moment series did not converge')
                    return length*j0,length*length*j1
                e=decay(x)
                return (1-e)/rate,(1-(1+x)*e)/(rate*rate)
            _,j1=moments(delta,R);tail,_=moments(T-B,R)
            revenue=M*S*(j1+delta*decay(R*delta)*tail)
            x=(K+R)*delta
            loss=x*moments(Decimal(1),x)[0] if x<Decimal('.1') else 1-decay(x)
            cost=C*decay(K*A)*loss
            difference=revenue-cost;scale=abs(revenue)+abs(cost)
            reliable=abs(difference)>scale*(Decimal(10)**(-precision+12))
            sign=1 if difference>0 else -1 if difference<0 else 0
            if reliable and previous==sign:return sign
            previous=sign if reliable else None
    raise NumericalError('joint envelope ordering is unresolved; rescale inputs')

def _envelope_order(p, a, b):
    """Sign of U(a)-U(b) from positive component differences, not net values."""
    if a==b:return 0
    if a>b:return -_envelope_order(p,b,a)
    # a<b. Revenue strictly decreases over this nonempty lag interval.
    if p.deployment_cost==0 or (p.learning_rate==0 and p.discount==0):return 1
    delta=b-a;r=p.discount;k=p.learning_rate
    _,j1=_log_moments(delta,r);tail=_log_moments(p.horizon-b,r)[0]
    log_revenue=log(p.margin_x)+log(p.growth)+float(np.logaddexp(j1,log(delta)-r*delta+tail))
    log_x=float(np.logaddexp(log(k) if k else -float('inf'),log(r) if r else -float('inf')))+log(delta)
    log_loss=log_x if log_x<-36 else 0. if log_x>log(50.) else log(-expm1(-exp(log_x)))
    log_cost=log(p.deployment_cost)-k*a+log_loss
    if log_cost==-float('inf'):return 1
    guard=1e-10+64*max(ulp(log_revenue),ulp(log_cost))
    if abs(log_revenue-log_cost)>guard:return 1 if log_revenue>log_cost else -1
    return _decimal_envelope_order(p,a,b)

def _envelope_root_candidates(balance, a, b, tolerance):
    """Retain a strict root bracket in normalized time, independently of units.

    A loose user time tolerance cannot remove an interior stationary point.
    Endpoints of an unresolved original bracket are never passed off as its
    root. This is a floating-point safeguard, not an interval certificate.
    """
    fa,fb=balance(a),balance(b)
    if not ((fa<0<fb) or (fb<0<fa)):
        raise NumericalError('joint envelope root requires a strict sign bracket')
    span=b-a
    target=max(4*sys.float_info.epsilon,min(1e-13,tolerance/span if tolerance<span else 1e-13))
    left,right=a,b;u_left,u_right=0.,1.
    for iteration in range(1,257):
        u=(u_left+u_right)/2
        mid=a+span*u
        if not left<mid<right:
            if not a<left<right<b:
                raise NumericalError('joint envelope root cannot be separated from its boundary; rescale inputs')
            return [left,right],{'initial_lower':a,'initial_upper':b,'final_lower':left,'final_upper':right,
                'iterations':iteration,'normalized_tolerance':target,'termination':'adjacent_float_controls'}
        fm=balance(mid)
        if not isfinite(fm):
            raise NumericalError('joint envelope interior root balance is not finite; rescale inputs')
        if fm==0:
            return [mid],{'initial_lower':a,'initial_upper':b,'final_lower':left,'final_upper':right,
                'iterations':iteration,'normalized_tolerance':target,'termination':'zero_computed_balance'}
        if (fa<0<fm) or (fm<0<fa):
            right,u_right=mid,u
        else:
            left,u_left,fa=mid,u,fm
        if u_right-u_left<=target and a<left<right<b:
            return [left,right],{'initial_lower':a,'initial_upper':b,'final_lower':left,'final_upper':right,
                'iterations':iteration,'normalized_tolerance':target,'termination':'normalized_bracket_width'}
    raise NumericalError('joint envelope root bracket did not resolve; rescale inputs')

def _unbounded_follower(p, lo, hi, tolerance):
    """Maximize the zero-cost intensity envelope over the joint delay domain.

    U(t) = m_x s M_r(t) - c_D exp(-(k+r)t). For 0<t<H,
    U is a supremum approached as intensity tends to infinity. At H it is
    attained by every finite intensity. At zero the envelope is only the
    right-hand limit when the delay interval contains positive points.
    The derivative balance has at most two roots, separated by its unique
    minimum, so no scouting grid is used to infer attainment.
    """
    if lo == hi and (lo == 0 or lo == p.growth_end):
        return {"attained": True, "delay": lo, "supremum": payoff(p,"RL",lo,0), "evaluations": 1,"root_diagnostics":[]}
    log_a = log(p.margin_x)+log(p.growth)
    k, r = p.learning_rate, p.discount
    rate = k+r
    def envelope(t):
        return _envelope_payoff(p,t)
    points = [lo, hi];root_diagnostics=[]
    if p.deployment_cost > 0 and rate > 0:
        log_rate = float(np.logaddexp(log(k) if k else -float("inf"), log(r) if r else -float("inf")))
        def balance(t):
            integral = _log_moments(p.horizon-t, r)[0]
            if integral == -float("inf"): return float("inf")
            return log_rate+log(p.deployment_cost)-k*t-log_a-integral
        # d log(cost derivative / revenue derivative) / dt vanishes once.
        if k > 0:
            ratio = r/k
            distance = 1/k if r == 0 or ratio == 0 else (
                log1p(ratio)/r if isfinite(ratio) else
                (float(np.logaddexp(log(r),log(k)))-log(k))/r)
            split = p.horizon-distance
        else:
            split = lo
        knots = sorted(set([lo, hi, min(hi,max(lo,split))]))
        for a,b in zip(knots,knots[1:]):
            fa,fb = balance(a),balance(b)
            if fa == 0: points.append(a)
            if fb == 0: points.append(b)
            if (fa < 0 < fb) or (fb < 0 < fa):
                candidates,diagnostic=_envelope_root_candidates(balance,a,b,tolerance)
                points.extend(candidates);root_diagnostics.append(diagnostic)
    values = {t:envelope(t) for t in sorted(set(points))}
    best_t=next(iter(values))
    for t in values:
        if _envelope_order(p,t,best_t)>0:best_t=t
    value=values[best_t]
    # Test the actually attainable boundary against the entire envelope.
    at_h = values.get(p.growth_end)
    attained = at_h is not None and _envelope_order(p,p.growth_end,best_t)>=0
    return {"attained": attained, "delay": p.growth_end if attained else best_t,
            "supremum": at_h if attained else value, "evaluations": len(values),"root_diagnostics":root_diagnostics}

def _local_probe_diagnostics(status, reason, rounds=(), final_assessed=False):
    """Describe only probes actually performed; never infer a final residual."""
    return {'policy':'recorded_local_probes_v1','status':status,'reason':reason,
            'max_rounds':4,'rounds':list(rounds),
            'final_control_neighborhood_assessed':bool(final_assessed),
            'threshold_policy':'payoff_atol + payoff_rtol * abs(selected displayed payoff)',
            'interpretation':'Recorded finite probes, not a continuous or global error bound. A passed increment after control promotion does not assess the new final neighborhood.'}


def optimize(p, strategy, bounds=None, rival_delay=None):
    """Conditional optimum. RF/DF hold rival delay fixed; RL/DL choose delay."""
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy {strategy}")
    bounds = bounds or DecisionBounds()
    lo, hi = bounds.validate(p)
    if strategy.endswith('F'):
        rival_delay=min(.15,p.growth_end) if rival_delay is None else finite_number(rival_delay,'rival_delay',minimum=0)
        if rival_delay > p.growth_end:
            raise ValueError("rival_delay must not exceed growth_end")
    flat_delay = (strategy.endswith("L") and hi > lo and (p.growth == 0 or p.margin_x == 0)
                  and (p.deployment_cost == 0 or (p.learning_rate == 0 and p.discount == 0)))
    points=[float(rival_delay)] if strategy.endswith('F') else [lo] if flat_delay or lo==hi else None
    upper = bounds.announcement_upper
    effective = p.margin_x > 0 and p.growth > 0 and p.network > 0
    joint = None
    if strategy.startswith("R") and upper is None and p.announcement_cost == 0 and effective:
        if strategy == "RL":
            joint = _unbounded_follower(p,lo,hi,bounds.tolerance)
            if joint["attained"]:
                points = [joint["delay"]]
            else:
                return {"strategy": strategy, "status": "no_finite_joint_optimum", "delay": None,
                        "announcement": None, "payoff": None, "supremum": joint["supremum"],
                        "supremum_delay": joint["delay"], "attainment": "not_attained",
                        "evaluations": joint["evaluations"],
                        "envelope_root_diagnostics":joint["root_diagnostics"],
                        "local_probe_diagnostics":_local_probe_diagnostics('not_applicable','unattained_joint_optimum'),
                        "message": "The joint envelope supremum is approached with unbounded intensity; no finite maximizing control is returned.",
                        "equilibrium": False, "globally_certified": False}
        elif 0 < rival_delay < p.growth_end:
            return {"strategy": strategy, "status": "no_finite_announcement_optimum", "delay": None,
                    "announcement": None, "payoff": None, "evaluations": 0,
                    "message": "Specify a finite announcement bound or positive announcement cost.",
                    "local_probe_diagnostics":_local_probe_diagnostics('not_applicable','unattained_announcement_optimum'),
                    "attainment": "not_attained", "equilibrium": False, "globally_certified": False}
    if points is None:
        representable=int(np.asarray(hi,dtype=np.float64).view(np.uint64))-int(np.asarray(lo,dtype=np.float64).view(np.uint64))+1
        if 1<=representable<=bounds.scouting_points and representable<=bounds.max_evaluations:
            points=[lo]
            for _ in range(1,representable):
                following=float(np.nextafter(points[-1],hi))
                if not points[-1]<following<=hi:raise NumericalError('invalid floating delay lattice')
                points.append(following)
            if points[-1]!=hi:raise NumericalError('incomplete floating delay lattice')
        else:
            if bounds.scouting_points>bounds.max_evaluations:raise NumericalError('initial scouting mesh exceeds profile evaluation budget')
            points=sorted(set(float(t) for t in np.linspace(lo,hi,bounds.scouting_points)))
    evaluations = 0
    cache = {};best=None;orders={};refinement_diagnostics=[]
    search_precision={'policy':'original_input_profile_order_v1','guard_ratio':NET_PAYOFF_GUARD_RATIO,
        'guarded_comparisons':0,'rounded_order_disagreements':0,'max_precision_digits':0,
        'bounded_scalar_refinements':0,'guarded_golden_refinements':0,
        'interpretation':'Near evaluated controls use original-input gaps. Rounded-order collisions switch local refinement to comparison-driven golden steps. This is adaptive local numerical guarding, not interval or global certification.'}
    def recorded(t):
        value,d,_=cache[t]
        return {'strategy':strategy,'delay':t,'announcement':d,'payoff':value}
    def gap(a,b,tolerance=0.):
        r=_model_control_gap(p,recorded(a),recorded(b),tolerance=tolerance)
        if r['decision_basis']!='rounded_payoff_difference':
            search_precision['guarded_comparisons']+=1
            search_precision['max_precision_digits']=max(search_precision['max_precision_digits'],r['precision_digits'] or 0)
        raw=cache[a][0]-cache[b][0];rounded=(raw>0)-(raw<0)
        if rounded!=r['sign']:search_precision['rounded_order_disagreements']+=1
        return r
    def order(a,b):
        if a==b:return 0
        key=(a,b)
        if key not in orders:
            sign=gap(a,b)['sign'];orders[key]=sign;orders[(b,a)]=-sign
        return orders[key]
    def evaluate(t):
        nonlocal evaluations,best
        t = min(hi, max(lo, float(t))) if strategy.endswith("L") else float(t)
        if t not in cache:
            if evaluations>=bounds.max_evaluations:raise NumericalError("profile evaluation budget exhausted")
            d, nonunique = profile_announcement(p, strategy, t, upper, bounds.tolerance)
            cache[t] = (payoff(p, strategy, t, d), d, nonunique)
            evaluations += 1
            if best is None or order(t,best)>0:best=t
        return cache[t][0]
    vals = [evaluate(t) for t in points]
    refinements=0
    if strategy.endswith("L") and hi > lo and joint is None and not flat_delay:
        # Edge cells can hide a maximum even when the first mesh value wins.
        intervals={(points[0],points[1]),(points[-2],points[-1])}
        for i in range(1, len(points)-1):
            before=order(points[i],points[i-1]);after=order(points[i],points[i+1])
            if before>=0 and after>=0 and (before>0 or after>0):
                intervals.add((points[i-1],points[i+1]))
        for a,b in sorted(intervals):
            # Adjacent representable endpoints have no interior control to search.
            if a >= b or float(np.nextafter(a,b)) >= b:
                continue
            # Normalize each interval so the stopping rule does not depend on
            # the magnitude of its time coordinates or measurement units.
            span=b-a
            tolerance=1. if bounds.tolerance >= span else max(5e-15,bounds.tolerance/span)
            if not search_precision['rounded_order_disagreements']:
                sol=minimize_scalar(lambda u:-evaluate(a+(b-a)*u),bounds=(0.,1.),
                    method="bounded",options={"xatol":tolerance,"maxiter":512})
                if not sol.success:raise NumericalError("delay refinement did not converge")
                evaluate(a+(b-a)*sol.x)
                search_precision['bounded_scalar_refinements']+=1
                refinement_diagnostics.append({'lower':a,'upper':b,'method':'bounded_scalar','iterations':int(sol.nit)})
            if search_precision['rounded_order_disagreements']:
                diagnostics=_ordered_golden_refine(evaluate,order,a,b,tolerance)
                search_precision['guarded_golden_refinements']+=1
                refinement_diagnostics.append({'lower':a,'upper':b,**diagnostics})
            refinements+=1
    value, d, nonunique = cache[best]
    if flat_delay:
        best=lo;value,d,nonunique=cache[best]
    def active(t, low, high):
        if low == high: return "fixed"
        if t == low: return "lower"
        if t == high: return "upper"
        return "interior"
    # Promote every better actually evaluated probe before final diagnostics.
    probe_improvement=0.;last_improvement=0.;probe_rounds=0;quality_passed=True;improvement_diagnostic=None
    probe_neighbors_distinct=False;probe_records=[]
    if strategy.endswith("L") and joint is None and not flat_delay:
        step=(hi-lo)*1e-5
        for _ in range(4):
            previous=best
            probe_targets=[max(lo,best-step),min(hi,best+step)]
            probe_neighbors_distinct=((best==lo or probe_targets[0]<best)
                                      and (best==hi or probe_targets[1]>best))
            probes=[]
            for side,t in zip(('lower','upper'),probe_targets):
                reused=t in cache
                evaluate(t)
                probes.append({'side':side,'control':recorded(t),
                               'distinct_from_start':bool(t!=previous),'already_evaluated':reused})
            value,d,nonunique=cache[best]
            threshold=bounds.payoff_atol+bounds.payoff_rtol*abs(value)
            if not isfinite(threshold):raise NumericalError('local quality threshold exceeds floating-point range; rescale inputs')
            improvement_diagnostic=gap(best,previous,threshold)
            last_improvement=max(0.,improvement_diagnostic['value']) if improvement_diagnostic['value'] is not None else None
            if last_improvement is None:raise NumericalError('local probe improvement exceeds floating-point range; rescale inputs')
            probe_improvement+=last_improvement;probe_rounds+=1
            if not isfinite(probe_improvement):raise NumericalError('accumulated local probe improvement exceeds floating-point range; rescale inputs')
            quality_passed=improvement_diagnostic['tolerance_relation']<=0
            probe_records.append({'round':probe_rounds,'starting_control':recorded(previous),
                'probes':probes,'selected_control':recorded(best),
                'quality_threshold':float(threshold),'improvement_diagnostic':dict(improvement_diagnostic),
                'passed':bool(quality_passed),'control_promoted':bool(best!=previous),
                'distinct_neighbors_in_feasible_directions':bool(probe_neighbors_distinct),
                'selected_control_neighborhood_assessed':bool(best==previous and hi>lo and probe_neighbors_distinct),
                'termination':'within_quality_tolerance' if quality_passed else 'round_limit' if probe_rounds==4 else 'continue'})
            if quality_passed:break
    # Recheck the returned candidate against every already evaluated control.
    # No complete ranking is promised over unevaluated continuous controls.
    legacy_assessed=bool(strategy.endswith('L') and hi>lo and not flat_delay and joint is None
                         and improvement_diagnostic is not None and best==previous and probe_neighbors_distinct)
    legacy_status='assessed_zero' if legacy_assessed else 'analytic_zero' if flat_delay else 'not_applicable' if strategy.endswith('F') or lo==hi else 'not_assessed'
    legacy_value=0. if legacy_status in ('assessed_zero','analytic_zero') else None
    if strategy.endswith('F'):probe_status,probe_reason='not_applicable','fixed_rival_delay'
    elif joint is not None:probe_status,probe_reason='not_applicable','attained_joint_envelope'
    elif flat_delay:probe_status,probe_reason='analytic_flat','analytically_flat_delay'
    elif lo==hi:probe_status,probe_reason='not_assessed','fixed_delay'
    elif legacy_assessed:probe_status,probe_reason='assessed','unchanged_control_with_feasible_neighbors'
    else:probe_status,probe_reason='not_assessed','control_promoted' if best!=previous else 'probe_control_coincidence'
    consistency_checks=0
    for t in cache:
        if t!=best:
            if order(best,t)<0:raise NumericalError('evaluated candidate ordering is inconsistent; rescale inputs')
            consistency_checks+=1
    zx,zy=shares(p,strategy,best,d)
    ann_active = "not_applicable" if strategy.startswith("D") else "fixed" if upper == 0 else (
        "lower" if d == 0 else (
        "upper" if upper is not None and d == upper else "interior"))
    stationarity=announcement_stationarity(p,strategy,best,d,ann_active)
    return {"strategy": strategy, "status": "attained_joint_optimum" if joint else "numerical_candidate" if strategy.endswith("L") and hi>lo else "profile_optimum",
            "delay": float(best), "announcement": float(d), "payoff": float(value),
            "share_x": zx, "share_y": zy, "evaluations": evaluations,
            "delay_refinement_intervals":refinements,
            "delay_refinement_diagnostics":refinement_diagnostics,
            "search_precision":{**search_precision,'evaluated_candidate_consistency_checks':consistency_checks},
            "delay_active": active(best,lo,hi) if strategy.endswith("L") else "fixed_rival_delay",
            "announcement_active": ann_active,
            "announcement_nonunique": nonunique, "delay_nonunique": flat_delay,
            "announcement_stationarity_residual": stationarity['raw'],
            "announcement_stationarity_log_residual": stationarity['log'],
            "announcement_stationarity_scaled_residual": stationarity['scaled'],
            "announcement_stationarity_representation": stationarity['representation'],
            "announcement_stationarity_diagnostic":stationarity,
            "local_improvement_residual":legacy_value,
            "local_improvement_residual_assessment":{'status':legacy_status,'deprecated':True,
                'final_control_neighborhood_assessed':legacy_assessed,
                'last_probe_quality_status':('pass' if quality_passed else 'fail') if improvement_diagnostic is not None else 'not_applicable',
                'interpretation':'Legacy field. Zero is supplied only for an unchanged returned control with evaluated last-probe neighbors, or an analytically flat delay. Null is not an assessed zero. Last-probe increments are not residuals at newly promoted controls.'},
            "probe_improvement_found":float(probe_improvement),"probe_rounds":probe_rounds,
            "local_quality_passed":quality_passed,"last_probe_improvement":float(last_improvement),
            "last_probe_improvement_diagnostic":improvement_diagnostic,
            "local_probe_diagnostics":_local_probe_diagnostics(probe_status,probe_reason,probe_records,legacy_assessed),
            "quality_interpretation":"Local diagnostics on evaluated controls; no global certificate.",
            "attainment": "attained", "supremum": joint["supremum"] if joint else None,
            "envelope_evaluations": joint["evaluations"] if joint else 0,
            "envelope_root_diagnostics":joint["root_diagnostics"] if joint else [],
            "equilibrium": False, "globally_certified": False,
            "conditional_control": "announcement; rival timing fixed" if strategy=="RF" else "rival timing fixed" if strategy=="DF" else "delay and announcement" if strategy=="RL" else "delay"}

def compare(p, bounds=None, rival_delay=None, tie_tolerance=1e-8, outside_option=0.0, optimizer=None):
    tie_tolerance=finite_number(tie_tolerance, "tie_tolerance", minimum=0)
    outside_option=finite_number(outside_option, "outside_option")
    results = [(optimizer or optimize)(p, st, bounds, rival_delay) for st in STRATEGIES]
    report=compare_results(results,tie_tolerance,outside_option)
    # An extension owns its supplied payoff semantics. Without its original
    # objective callbacks, do not reinterpret those values as this model.
    if optimizer is not None:return report
    return _compare_model_results(p,report)


def _compare_model_results(p,report):
    """Refine comparisons for results owned by the default model only."""
    results=report['results'];tie_tolerance=report['tie_tolerance']
    outside_option=report['outside_option_payoff']
    valid=[i for i,r in enumerate(results) if r['payoff'] is not None]
    cache={};refined=[]
    def difference(i,j=None):
        key=(i,j)
        if key in cache:return cache[key]
        left=results[i];right=results[j] if j is not None else None
        r=_model_control_gap(p,left,right,outside_option,tie_tolerance)
        if r['decision_basis']!='rounded_payoff_difference':
            refined.append({'left':left['strategy'],'right':right['strategy'] if right is not None else 'outside_option',**r})
        cache[key]=r
        if j is not None:
            cache[(j,i)]={**r,'value':-r['value'] if r['value'] is not None else None,
                           'sign':-r['sign'],'tolerance_relation':-r['tolerance_relation']}
        return r
    ordered=sorted(valid,key=cmp_to_key(lambda i,j:-difference(i,j)['sign']))
    best=ordered[0] if ordered else None
    labels=[] if best is None else [results[i]['strategy'] for i in valid if difference(best,i)['tolerance_relation']<=0]
    report['co_best']=labels if report['all_rankable'] else []
    report['finite_candidate_co_best']=labels
    if report['all_rankable']:
        outside=difference(best)
        entry=difference(best,ordered[1])
        report.update(entry_payoff_gap=entry['value'],entry_payoff_gap_diagnostic=entry,
                      outside_option_gap=outside['value'],outside_option_gap_diagnostic=outside,
                      preferred_with_outside_option=labels if outside['tolerance_relation']>0 else
                          ['no_entry'] if outside['tolerance_relation']<0 else labels+['no_entry'])
    report['comparison_precision']={'policy':'original_input_gap_guard_v2',
        'guard_ratio':NET_PAYOFF_GUARD_RATIO,'refined_comparisons':refined,
        'interpretation':'Near gaps use original model inputs at recorded controls and may differ from subtracting displayed payoffs. Extreme decays use a factored exponential sum with an omitted-tail bound. Adaptive guards are not interval or global certificates; unresolved order or an unrepresentable log magnitude raises NumericalError.'}
    return report

def compare_results(results,tie_tolerance=1e-8,outside_option=0.0):
    tie_tolerance=finite_number(tie_tolerance,"tie_tolerance",minimum=0);outside_option=finite_number(outside_option,"outside_option")
    if [r.get("strategy") for r in results]!=list(STRATEGIES):raise ValueError("comparison requires ordered RF/RL/DF/DL results")
    results=[dict(r) for r in results]
    for result in results:
        if isinstance(result.get('local_quality_passed'),np.bool_):result['local_quality_passed']=bool(result['local_quality_passed'])
        if result.get("payoff") is not None:result['payoff']=finite_number(result["payoff"],"comparison payoff")
    valid = [r for r in results if r["payoff"] is not None]
    best = max((r["payoff"] for r in valid), default=None)
    labels = [] if best is None else [r["strategy"] for r in valid if best-r["payoff"] <= tie_tolerance]
    # Use the same subtraction as the reported gap, including signed overflow
    # for comparisons. Finite tolerance cannot tie an infinite-magnitude gap.
    outside_delta=best-outside_option if best is not None else None
    preferred=[] if len(valid)!=len(STRATEGIES) else labels if outside_delta>tie_tolerance else ["no_entry"] if outside_delta<-tie_tolerance else labels+["no_entry"]
    ordered=sorted((r["payoff"] for r in valid),reverse=True)
    def gap_record(a,b):
        raw=a-b
        return {'value':raw if isfinite(raw) else None,'representation':'finite' if isfinite(raw) else 'outside_float_range',
                'log_abs':log(abs(raw)) if isfinite(raw) and raw else None if raw==0 else float(np.logaddexp(log(abs(a)),log(abs(b))))}
    entry_gap=gap_record(ordered[0],ordered[1]) if len(ordered)>1 and len(valid)==4 else None
    outside_gap=gap_record(best,outside_option) if best is not None and len(valid)==4 else None
    statuses={r['strategy']:('not_applicable' if r['payoff'] is None else
              'pass' if r.get('local_quality_passed') is True else
              'fail' if r.get('local_quality_passed') is False else 'not_assessed') for r in results}
    complete=all(s in ['pass','fail'] for s in statuses.values())
    quality_status='fail' if 'fail' in statuses.values() else 'pass' if complete else 'not_assessed'
    return {"local_quality_status":quality_status,"local_quality_assessment_complete":complete,
            "local_quality_by_strategy":statuses,"entry_payoff_gap":entry_gap["value"] if entry_gap else None,"entry_payoff_gap_diagnostic":entry_gap,
            "outside_option_gap":outside_gap["value"] if outside_gap else None,"outside_option_gap_diagnostic":outside_gap,
            "all_local_quality_passed":True if quality_status=="pass" else False if quality_status=="fail" else None,
            "results": results, "co_best": labels if len(valid)==len(STRATEGIES) else [], "finite_candidate_co_best": labels, "tie_tolerance": tie_tolerance,
            "outside_option_payoff":outside_option,"preferred_with_outside_option":preferred,
            "all_rankable": len(valid)==len(STRATEGIES),
            "interpretation": "Conditional scenario comparison; first-mover cases hold rival delay fixed. No Nash or mixed-strategy equilibrium claim."}


def compare_stability(p,bounds=None,rival_delay=None,comparison=None,factors=(1,2,4)):
    """Mesh/tolerance agreement, not a bound on global objective error."""
    from dataclasses import replace
    bounds=bounds or DecisionBounds();bounds.validate(p)
    if not isinstance(factors,(list,tuple)) or len(factors)<2 or any(isinstance(x,bool) or not isinstance(x,int) or x<1 for x in factors) or len(set(factors))!=len(factors):
        raise ValueError("stability factors must contain at least two distinct positive integers")
    options={} if comparison is None else comparison
    if not isinstance(options,dict) or set(options)-{"tie_tolerance","outside_option"}:raise ValueError("invalid stability comparison policy")
    reports=[compare(p,replace(bounds,scouting_points=1+(bounds.scouting_points-1)*factor,tolerance=bounds.tolerance/factor),rival_delay,**options) for factor in sorted(factors)]
    rows=[]
    for i,st in enumerate(STRATEGIES):
        controls=[r['results'][i] for r in reports]
        values=[r['payoff'] for r in controls]
        scale=max(abs(v) for v in values if v is not None) if any(v is not None for v in values) else 0.
        threshold=bounds.payoff_atol+bounds.payoff_rtol*scale
        if not isfinite(threshold):
            raise NumericalError('mesh stability quality threshold exceeds floating-point range; rescale inputs')
        diagnostic=None;maximum=minimum=None
        if all(v is not None for v in values):
            maximum=minimum=0
            for j in range(1,len(controls)):
                if _model_control_gap(p,controls[j],controls[maximum],tolerance=0.)['sign']>0:maximum=j
                if _model_control_gap(p,controls[j],controls[minimum],tolerance=0.)['sign']<0:minimum=j
            diagnostic=_model_control_gap(p,controls[maximum],controls[minimum],tolerance=threshold)
            if diagnostic['sign']<0:
                raise NumericalError('mesh payoff ordering is inconsistent; rescale inputs')
        rows.append({'strategy':st,'payoffs':values,
                     'observed_payoff_spread':diagnostic['value'] if diagnostic is not None else None,
                     'observed_payoff_spread_diagnostic':diagnostic,
                     'quality_threshold':threshold,
                     'maximum_payoff_factor':sorted(factors)[maximum] if maximum is not None else None,
                     'minimum_payoff_factor':sorted(factors)[minimum] if minimum is not None else None,
                     'within_quality_tolerance':diagnostic is not None and diagnostic['tolerance_relation']<=0})
    ranks=[(r['co_best'],r['preferred_with_outside_option']) for r in reports]
    ranking_stable=all(ranks[0]==x for x in ranks[1:]) and all(r['all_rankable'] for r in reports)
    return {'factors':sorted(factors),'reports':reports,'strategies':rows,'ranking_stable':ranking_stable,
            'payoff_stable':all(x['within_quality_tolerance'] for x in rows),'globally_certified':False,
            'payoff_stability_precision':{'policy':'original_input_mesh_spread_v1','guard_ratio':NET_PAYOFF_GUARD_RATIO,
                'interpretation':'Order and compare model-owned returned controls using original-input gap guards. The quality threshold uses the configured absolute/relative tolerances and the maximum absolute displayed payoff. Amounts may underflow; the signed tolerance relation decides stability. Unresolved order or an unrepresentable threshold raises NumericalError. This is separate from local-quality assessment and supplies no global error bound.'},
            'interpretation':'Observed agreement across meshes and tighter delay tolerances; this is not a global error bound or empirical robustness guarantee.'}
