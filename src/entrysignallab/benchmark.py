"""Independent quadrature and explicitly scoped optimizer comparisons. MIT License."""
from pathlib import Path
from dataclasses import replace, asdict
from math import exp
import time, statistics, platform
import numpy as np
from scipy.integrate import quad
from scipy.optimize import differential_evolution
from .model import ModelParams, revenues, payoff, STRATEGIES
from .solver import DecisionBounds, optimize
from .plots import write_csv
from .workflow import write_json
from .provenance import environment_record

def reference_demand(p,st,t,tau,delta):
    """Independent scalar transcription; does not call the operational kernel."""
    w=p.quality_ratio
    if st=="RF": a,b=1+p.network*(p.growth+delta)*tau,w
    elif st=="RL": a,b=1+p.network*delta*tau,w*(1+p.network*p.growth*tau)
    elif st=="DF": a,b=1+p.network*p.growth*tau,w
    else:a,b=1,w*(1+p.network*p.growth*tau)
    xshare,yshare=a/(a+b),b/(a+b)
    if t<tau:
        return (p.growth*t,0.) if st.endswith("F") else (0.,p.growth*t)
    u=t if t<p.growth_end else p.growth_end
    follower=p.growth*(u-tau)
    if st.endswith("F"):return p.growth*tau+follower*xshare,follower*yshare
    return follower*xshare,p.growth*tau+follower*yshare

def reference_revenues(p,st,tau,delta):
    boundaries=sorted(set([0.,tau,p.growth_end,p.horizon]))
    answers=[]
    for j,margin in enumerate([p.margin_x,p.margin_y]):
        total=sum(quad(lambda t: exp(-p.discount*t)*reference_demand(p,st,t,tau,delta)[j],a,b,
                       epsabs=1e-12,epsrel=1e-12)[0] for a,b in zip(boundaries,boundaries[1:]) if b>a)
        answers.append(margin*total)
    return tuple(answers)

def validate_benchmark(seed=104,accuracy_cases=80,repeats=5,grid_points=201):
    if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:raise ValueError("seed must be a nonnegative integer")
    if any(isinstance(v,bool) or not isinstance(v,int) or v<1 for v in [accuracy_cases,repeats,grid_points]):raise ValueError("benchmark sizes must be positive integers")
    if grid_points<3:raise ValueError("grid_points must be >=3")

def summarize_optimizer_trials(timing):
    """Summarize every repeat; coordinates are the best observed feasible trial."""
    summaries=[]
    for case,method in sorted({(t['case'],t['method']) for t in timing}):
        trials=[t for t in timing if (t['case'],t['method'])==(case,method)]
        selected=max(trials,key=lambda t:t['payoff'])
        summaries.append({"case":case,"method":method,
            "median_seconds":statistics.median(t['seconds'] for t in trials),
            "min_seconds":min(t['seconds'] for t in trials),"max_seconds":max(t['seconds'] for t in trials),
            "median_evaluations":statistics.median(t['evaluations'] for t in trials),
            "delay":selected['delay'],"announcement":selected['announcement'],"payoff":selected['payoff'],
            "evaluations":selected['evaluations'],"selected_repeat":selected['repeat'],
            "min_payoff":min(t['payoff'] for t in trials),"median_payoff":statistics.median(t['payoff'] for t in trials),
            "max_payoff":selected['payoff'],"successful_repeats":sum(t['solver_success'] for t in trials),
            "repeats":len(trials),"selection":"best observed repeat; timing aggregates all repeats"})
    for row in summaries:
        best=max(t['payoff'] for t in timing if t['case']==row['case'])
        row['gap_to_best_observed']=max(0.,best-row['payoff'])
    return summaries

def run_benchmark(directory,seed=104,accuracy_cases=80,repeats=5,grid_points=201):
    validate_benchmark(seed,accuracy_cases,repeats,grid_points)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    hardware=environment_record();write_json(directory/"hardware.json",hardware)
    rng=np.random.default_rng(seed);errors=[]
    for i in range(accuracy_cases):
        p=ModelParams(growth=float(rng.uniform(.02,2)),network=float(rng.uniform(0,2)),growth_end=float(rng.uniform(.05,.95)),
                      quality_ratio=float(rng.uniform(.3,3)),discount=[0,1e-12,1e-5,.5,5][i%5])
        tau=float(rng.uniform(0,p.growth_end));delta=float(rng.uniform(0,2))
        for st in STRATEGIES:
            d=delta if st.startswith("R") else 0.
            analytic=revenues(p,st,tau,d);reference=reference_revenues(p,st,tau,d)
            for j in range(2):errors.append({"case":i,"strategy":st,"platform":"xy"[j],"discount":p.discount,
                                           "analytic":analytic[j],"quadrature":reference[j],"absolute_error":abs(analytic[j]-reference[j])})
    write_csv(directory/"integration_accuracy.csv",errors)
    cases=[ModelParams(growth=.1,network=.85,growth_end=.3,announcement_cost=a,deployment_cost=c,learning_rate=12.)
           for a,c in [(0.,0.),(.00002,.004),(.0002,.012),(.002,.02)]]
    bounds=DecisionBounds(announcement_upper=2,scouting_points=65)
    timing=[]
    for ci,p in enumerate(cases):
        tgrid=np.linspace(0,p.growth_end,grid_points);dgrid=np.linspace(0,2,grid_points)
        def vector_grid():
            # Separate zero-discount closed form, same admissible controls and costs.
            t=tgrid[None,:];d=dgrid[:,None]
            stock_mass=p.growth*(p.growth_end-t)*(2*p.horizon-p.growth_end-t)/2
            z=(1+p.network*t*d)/(1+p.network*t*d+p.quality_ratio*(1+p.network*p.growth*t))
            v=p.margin_x*stock_mass*z-p.announcement_cost*d*d/2-p.deployment_cost*np.exp(-p.learning_rate*t)
            idx=np.unravel_index(np.argmax(v),v.shape)
            return {"delay":float(tgrid[idx[1]]),"announcement":float(dgrid[idx[0]]),"payoff":float(v[idx]),"evaluations":grid_points**2}
        methods={"profile_search":lambda:optimize(p,"RL",bounds),"vectorized_grid":vector_grid,
                 "differential_evolution":lambda:None}
        for name in methods:
            times=[];vals=[]
            for rep in range(repeats):
                # Imports, parameter construction and grid construction are outside timing for all methods.
                start=time.perf_counter()
                if name=="differential_evolution":
                    sol=differential_evolution(lambda v:-payoff(p,"RL",v[0],v[1]),[(0,p.growth_end),(0,2)],
                                               seed=seed+rep,tol=1e-10,atol=1e-12,popsize=15,maxiter=500,polish=True)
                    ans={"delay":float(sol.x[0]),"announcement":float(sol.x[1]),"payoff":float(-sol.fun),"evaluations":int(sol.nfev),"solver_success":bool(sol.success),"solver_message":str(sol.message)}
                else:
                    ans=methods[name]();ans.update(solver_success=True,solver_message="profile search completed" if name=="profile_search" else "exhaustive finite grid completed")
                elapsed=time.perf_counter()-start
                checked=payoff(p,"RL",ans["delay"],ans["announcement"])
                if not (0<=ans["delay"]<=p.growth_end and 0<=ans["announcement"]<=2 and abs(checked-ans["payoff"])<=1e-10):
                    raise ValueError("benchmark comparator returned an infeasible or inconsistent objective")
                ans["objective_check_error"]=abs(checked-ans["payoff"]);times.append(elapsed);vals.append(ans)
                timing.append({"case":ci,"method":name,"repeat":rep,"seconds":elapsed,**ans})
    solutions=summarize_optimizer_trials(timing)
    write_csv(directory/"optimizer_timings.csv",timing);write_csv(directory/"optimizer_summary.csv",solutions)
    summary={"environment":hardware,"seed":seed,"accuracy_parameter_sets":accuracy_cases,"accuracy_comparisons":len(errors),
             "max_absolute_integration_error":max(e["absolute_error"] for e in errors),"integration_pass":max(e["absolute_error"] for e in errors)<1e-10,
             "optimization_cases":[asdict(p) for p in cases],"repeats":repeats,"grid_points_per_axis":grid_points,
             "optimizer_results":solutions,"timing_scope":"Warm in-process solver call; shared configuration/grid construction and import/startup/plotting excluded. Vectorized grid includes matrix evaluation/allocation. No cross-platform or general speed claim.",
             "interpretation":"The profiled intensity subproblem is concave. Delay search and comparator runs provide numerical candidates. Best observed values are not formal global certificates."}
    write_json(directory/"benchmark_summary.json",summary);return summary

