"""Explicit model capabilities and checked research adapters; no implicit reuse."""
from dataclasses import dataclass
from typing import Callable
from math import isclose,ulp,log
from .model import (ModelParams,finite_number,STRATEGIES,payoff,decisions,
                    _from_log,_log_response_mass,deployment_present_value,_envelope_payoff)
from .solver import DecisionBounds,optimize

@dataclass(frozen=True)
class ModelCapabilities:
    model_id:str
    version:str
    concave_announcement:bool
    joint_envelope_available:bool
    calibrated:bool=False
    def validate(self):
        if not isinstance(self.model_id,str) or not self.model_id.strip() or not isinstance(self.version,str) or not self.version.strip():raise ValueError('model identity/version must be nonempty strings')
        for value in [self.concave_announcement,self.joint_envelope_available,self.calibrated]:
            if type(value) is not bool:raise ValueError('capability flags must be boolean')

@dataclass(frozen=True)
class ResearchKernel:
    capabilities:ModelCapabilities
    evaluate:Callable
    validate_params:Callable
    validate_controls:Callable
    conditional_solver:Callable|None=None
    validate_solution:Callable|None=None
    objective_atol:float=0.0
    objective_rtol:float=1e-8
    def objective_policy(self):
        return {'absolute_tolerance':finite_number(self.objective_atol,'objective_atol',minimum=0),
                'relative_tolerance':finite_number(self.objective_rtol,'objective_rtol',minimum=0),
                'ulp_allowance':8}
    def validate(self):
        self.capabilities.validate()
        if not all(callable(v) for v in [self.evaluate,self.validate_params,self.validate_controls]):raise ValueError('research kernel requires explicit validation and evaluation callbacks')
        if self.conditional_solver is not None and not callable(self.conditional_solver):raise ValueError('conditional_solver must be callable')
        if self.validate_solution is not None and not callable(self.validate_solution):raise ValueError('validate_solution must be callable')
        self.objective_policy()


def evaluate_research(kernel,params,strategy,delay,announcement=0.):
    kernel.validate();kernel.validate_params(params);kernel.validate_controls(params,strategy,delay,announcement)
    value=finite_number(kernel.evaluate(params,strategy,delay,announcement),'research payoff')
    return {'model_id':kernel.capabilities.model_id,'model_version':kernel.capabilities.version,'payoff':value,'calibrated':kernel.capabilities.calibrated}


def optimize_research(kernel,params,strategy,bounds=None,rival_delay=None):
    """Extensions supply their own solver; the default profiler is not assumed."""
    kernel.validate();kernel.validate_params(params)
    if kernel.conditional_solver is None:raise ValueError('research model requires its own explicit conditional_solver; default concavity/envelope assumptions are not inferred')
    if kernel.validate_solution is None:raise ValueError('research optimization requires explicit validate_solution(params,strategy,bounds,rival_delay,result)')
    effective_bounds=DecisionBounds() if bounds is None else bounds
    result=kernel.conditional_solver(params,strategy,effective_bounds,rival_delay)
    if not isinstance(result,dict) or result.get('strategy')!=strategy:raise ValueError('research solver must return the requested strategy')
    result=dict(result)
    for name in ['payoff','delay','announcement']:
        if name not in result:raise ValueError('research solver omitted '+name)
    for name in ['supremum','supremum_delay']:
        if result.get(name) is not None:result[name]=finite_number(result[name],'research '+name)
    objective_check={'status':'not_applicable',**kernel.objective_policy()}
    if result.get('payoff') is not None:
        result.setdefault('attainment','candidate')
        if result['attainment'] not in ('attained','candidate'):
            raise ValueError('finite research payoff requires attained or candidate state')
        if result.get('status') in ('no_finite_joint_optimum','no_finite_announcement_optimum'):
            raise ValueError('finite research payoff conflicts with nonexistence status')
        # Common controls are numeric binary64 values. The kernel's callbacks
        # still own their domain, including custom negative controls/bounds.
        for key in ['delay','announcement','payoff']:
            result[key]=finite_number(result[key],'research '+key)
        if kernel.validate_solution(params,strategy,effective_bounds,rival_delay,result) is not True:raise ValueError('research solution violates configured feasibility')
        reference=evaluate_research(kernel,params,strategy,result['delay'],result['announcement'])['payoff']
        actual=result['payoff'];policy=kernel.objective_policy()
        atol=policy['absolute_tolerance'];rtol=policy['relative_tolerance']
        effective_atol=max(atol,8*ulp(reference))
        sign_guard=atol==0
        incompatible_sign=sign_guard and ((reference==0)!=(actual==0) or (reference<0)!=(actual<0))
        if incompatible_sign or not isclose(reference,actual,rel_tol=rtol,abs_tol=effective_atol):
            raise ValueError('research solver payoff disagrees with kernel')
        objective_check={'status':'passed',**policy,'reference_payoff':reference,
                         'effective_absolute_tolerance':effective_atol,
                         'zero_sign_guard':sign_guard,'policy_source':'explicit_kernel_fields'}
    elif result.get('attainment')!='not_attained' or result.get('delay') is not None or result.get('announcement') is not None:
        raise ValueError('missing research payoff requires an explicit unattained state with null controls')
    elif result.get('status') in ('profile_optimum','numerical_candidate','attained_joint_optimum'):
        raise ValueError('null research payoff conflicts with finite-solution status')
    elif kernel.validate_solution(params,strategy,effective_bounds,rival_delay,result) is not True:
        raise ValueError('research solution violates configured feasibility')
    return {**result,'objective_consistency':objective_check,'model_id':kernel.capabilities.model_id,'model_version':kernel.capabilities.version,'calibrated':kernel.capabilities.calibrated,'globally_certified':False,'interface_scope':'Explicit result-state schema, configured-solution callback, mathematical domain and recorded objective correspondence policy; capabilities and callbacks are declarations, not proofs or empirical validation.'}


def default_research_kernel():
    def validate(p):
        if not isinstance(p,ModelParams):raise ValueError('default kernel requires ModelParams')
    def validate_solution(p,strategy,bounds,rival,result):
        from .workflow import configured_feasibility
        if strategy not in STRATEGIES:raise ValueError('unknown strategy')
        lo,hi=bounds.validate(p)
        if strategy.endswith('F'):
            rival=min(.15,p.growth_end) if rival is None else finite_number(rival,'rival_delay',minimum=0)
            if rival>p.growth_end:raise ValueError('rival_delay exceeds growth_end')
        if result.get('payoff') is None:
            reference=optimize(p,strategy,bounds,rival)
            if reference.get('payoff') is not None or reference.get('attainment')!='not_attained':return False
            if result.get('status')!=reference.get('status'):return False
            if reference.get('supremum') is None:
                return result.get('supremum') is None and result.get('supremum_delay') is None
            value=result.get('supremum');lag=result.get('supremum_delay')
            if value is None or lag is None or not lo<=lag<=hi:return False
            envelope=_envelope_payoff(p,lag)
            return close(value,reference['supremum']) and close(envelope,value)
        if not configured_feasibility(p,bounds,rival,strategy,result['delay'],result['announcement'])['within_configured_bounds']:return False
        if result.get('supremum') is not None or result.get('supremum_delay') is not None or result.get('status')=='attained_joint_optimum':
            reference=optimize(p,strategy,bounds,rival)
            if reference.get('status')!='attained_joint_optimum' or result.get('attainment')!='attained':return False
            value=result.get('supremum')
            if value is None or not close(value,reference['supremum']) or not close(value,finite_number(result['payoff'],'solver payoff')):return False
            lag=result.get('supremum_delay',result['delay'])
            if lag is None or not lo<=lag<=hi or not close(lag,finite_number(result['delay'],'solver delay')):return False
        return True
    def close(value,reference):
        # Model-owned numerical metadata tolerance, independent of user quality
        # settings. It admits alternative equal envelope maxima without forcing
        # the solver's selected lag or adding an absolute economic payoff floor.
        if (value==0)!=(reference==0) or (value<0)!=(reference<0):return False
        return isclose(value,reference,rel_tol=1e-10,abs_tol=8*ulp(reference))
    return ResearchKernel(ModelCapabilities('piecewise-demand-v1','1',True,True),payoff,validate,decisions,optimize,validate_solution)
